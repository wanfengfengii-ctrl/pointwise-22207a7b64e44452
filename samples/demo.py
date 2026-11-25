from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from balance.store import open_report_database
from intake.accept import accept
from intake.receipts import Receipt
from issue.registry import open_issue_registry
from issue.reissue import reissue
from issue.requests import issue
from reports.provenance import trace
from reports.reconcile import Reconciliation, reconcile_range
from source.correct import PointChange
from source.day import StationDay, initialize_day
from source.ingest import apply
from source.store import open_source

_SAMPLES = Path(__file__).resolve().parent


def prepare_delivery(directory: Path) -> tuple[StationDay, dict[str, bytes], list[list[str]]]:
    source_input = json.loads((_SAMPLES / 'source-day.json').read_text(encoding='utf-8'))
    dispatch = json.loads((_SAMPLES / 'dispatch.json').read_text(encoding='utf-8'))
    day = StationDay(source_input['station'], source_input['day'])
    registry_path = directory / 'issue.sqlite'
    published = {}
    with closing(open_source(directory / 'source.sqlite')) as source:
        initialize_day(source, day)
        for event in source_input['events']:
            change = PointChange(event['kind'], event['key'], event['litres'], event['origin'])
            apply(source, day, event['request'], change)
        with closing(open_issue_registry(registry_path)) as registry:
            for request in dispatch['requests']:
                name = request['artifact_id']
                if 'bounds' in request:
                    payload = issue(source, registry, name, day, request['cut'], bounds=tuple(request['bounds']))
                else:
                    payload = issue(source, registry, name, day, request['cut'], key=request['key'])
                published[name] = payload

    resent = {}
    with closing(open_issue_registry(registry_path)) as registry:
        for name, payload in published.items():
            original = reissue(registry, name)
            if original != payload:
                raise SystemExit(f'HEPU_REISSUE_MISMATCH {name}')
            resent[name] = original
    return day, resent, dispatch['batches']


def deliver(report: Path, packets: dict[str, bytes], names: list[str]) -> list[Receipt]:
    with closing(open_report_database(report)) as db:
        return [accept(db, packets[name]) for name in names]


def _book_data(result: Reconciliation) -> dict:
    return {
        'rows': [[row.key, row.litres, row.cut, row.origin, row.artifact_id] for row in result.book.rows],
        'total_litres': result.book.total_litres,
    }


def _trace_data(result: Reconciliation) -> list[list]:
    return [[item.key, item.cut, item.origin, item.artifact_id] for item in result.traces]


def _check(marker: str, expected: object, actual: object) -> None:
    if expected != actual:
        detail = json.dumps({'expected': expected, 'actual': actual}, ensure_ascii=False)
        raise SystemExit(f'{marker} {detail}')


def main() -> int:
    with TemporaryDirectory(prefix='hepu-ledger-') as directory:
        root = Path(directory)
        day, packets, batches = prepare_delivery(root)
        report = root / 'report.sqlite'
        first = deliver(report, packets, batches[0])
        late, = deliver(report, packets, batches[1])
        result = reconcile_range(report, day, 10, 20)
        expected = {'rows': [[12, 13, 9, 'orig12', 'P9']], 'total_litres': 13}
        actual = _book_data(result)
        downstream_expected = {
            'traces': [[12, 9, 'orig12', 'P9']], 'key_15_absent': True,
            'receipts': [['P9', 1], ['S8', 2], ['P7', 3]],
        }
        downstream_actual = {
            'traces': _trace_data(result), 'key_15_absent': trace(report, day, 15) is None,
            'receipts': [[receipt.artifact_id, receipt.number] for receipt in (*first, late)],
        }
        _check('HEPU_STOCKTAKE_MISMATCH', expected, actual)
        _check('HEPU_STOCKTAKE_MISMATCH', downstream_expected, downstream_actual)

        later = deliver(report, packets, batches[2])
        _check('HEPU_REDELIVERY_MISMATCH', late.number, later[-1].number)
        _check('HEPU_EMPTY_STOCKTAKE_MISMATCH', None, trace(report, day, 15))
        deliver(report, packets, batches[3])
        final = reconcile_range(report, day, 10, 21)
        _check('HEPU_RESTORATION_MISMATCH', {
            'rows': [[12, 13, 9, 'orig12', 'P9'], [15, 17, 11, 'orig15', 'P11'],
                     [18, 5, 10, 'orig18', 'Z10'], [20, 19, 4, 'orig20', 'P4']],
            'total_litres': 54,
        }, _book_data(final))

        print('POINTWISE_SCENARIO ' + json.dumps({
            'case_id': 'V5',
            'input': {'station': day.station, 'day': day.day, 'bounds': [10, 20],
                      'delivery_batches': batches[:2],
                      'received_packets': [json.loads(packets[name]) for batch in batches[:2] for name in batch]},
            'expected': expected,
            'actual': actual,
            'downstream_expected': downstream_expected,
            'downstream_actual': downstream_actual,
            'code_paths': ['issue/stocktake.py', 'intake/accept.py', 'balance/coverage.py',
                           'balance/posting.py', 'reports/reconcile.py'],
            'oracle': 'Hand check: P9 outranks S8 at 12. S8 covers 15 and omits it, so P7 adds no litres.',
        }, ensure_ascii=False, sort_keys=True))
        print(json.dumps({'after_restoration': _book_data(final), 'traces': _trace_data(final)}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
