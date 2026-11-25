from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path

from balance.store import open_report_database
from intake.accept import accept
from intake.receipts import Receipt
from issue.history import issue_history
from issue.registry import open_issue_registry
from issue.reissue import reissue
from reports.reconcile import review_history
from source.correct import PointChange
from source.day import StationDay, initialize_day
from source.ingest import apply
from source.store import open_source

_SAMPLES = Path(__file__).resolve().parent


def load_history_sample() -> dict:
    return json.loads((_SAMPLES / 'history-window.json').read_text(encoding='utf-8'))


def read_source_events(path: Path, day: StationDay, events: list) -> None:
    """Replay sample events into a fresh source with request numbers starting at one."""
    with closing(open_source(path)) as source:
        initialize_day(source, day)
        for index, event in enumerate(events, 1):
            kind, key, litres, origin = event
            apply(source, day, f'r{index}', PointChange(kind, key, litres, origin))


def issue_tiles(
    source_path: Path, registry_path: Path, day: StationDay, tiles: list
) -> dict[str, bytes]:
    """Issue every sample tile against one source and registry, then close both files."""
    published = {}
    with closing(open_source(source_path)) as source, closing(open_issue_registry(registry_path)) as registry:
        for name, bounds, start, end in tiles:
            published[name] = issue_history(source, registry, name, day, tuple(bounds), start, end)
    return published


def reissue_tiles(registry_path: Path, published: dict[str, bytes]) -> dict[str, bytes]:
    resent = {}
    with closing(open_issue_registry(registry_path)) as registry:
        for name, payload in published.items():
            original = reissue(registry, name)
            if original != payload:
                raise SystemExit(f'HEPU_HISTORY_REISSUE_MISMATCH {name}')
            resent[name] = original
    return resent


def prepare_history(directory: Path) -> tuple[StationDay, dict[str, bytes], list[str]]:
    """Build an independent source, issue every tile, close the source, and reissue offline."""
    sample = load_history_sample()
    day = StationDay(sample['station'], sample['day'])
    source_path = directory / 'history-source.sqlite'
    registry_path = directory / 'history-issue.sqlite'
    read_source_events(source_path, day, sample['events'])
    published = issue_tiles(source_path, registry_path, day, sample['tiles'])
    # The source and registry are now closed; only their frozen bytes travel onward.
    return day, reissue_tiles(registry_path, published), [tile[0] for tile in sample['tiles']]


def deliver_history(report: Path, packets: dict[str, bytes], names: list[str]) -> list[Receipt]:
    with closing(open_report_database(report)) as db:
        return [accept(db, packets[name]) for name in names]


def scenario_result(report: Path, day: StationDay) -> dict:
    return {
        'pending_abc': review_history(report, day, (10, 20), 5, 9),
        'after_d': review_history(report, day, (10, 20), 5, 9),
        'narrow_after_restore': review_history(report, day, (11, 13), 6, 11),
    }


def _check(marker: str, expected: object, actual: object) -> None:
    if expected != actual:
        detail = json.dumps({'expected': expected, 'actual': actual}, ensure_ascii=False)
        raise SystemExit(f'{marker} {detail}')


def _history_lines(report: Path, day: StationDay, packets: dict[str, bytes]) -> list[dict]:
    """Walk the offline handover: pending, then each tile completing the window."""
    steps = [
        (['A', 'B'], (10, 20), 5, 9),
        (['C'], (10, 20), 5, 9),
        (['D'], (10, 20), 5, 9),
        (['E', 'F'], (11, 13), 6, 11),
    ]
    timeline = []
    for batch, bounds, start, end in steps:
        deliver_history(report, packets, batch)
        timeline.append({
            'delivered': batch,
            'bounds': list(bounds), 'start': start, 'end': end,
            'result': review_history(report, day, bounds, start, end),
        })
    return timeline


def main() -> int:
    from tempfile import TemporaryDirectory

    # The original daily-report business still runs first on its own frozen pieces.
    from samples.demo import main as baseline_main
    baseline_main()

    with TemporaryDirectory(prefix='hepu-history-') as directory:
        root = Path(directory)
        day, packets, names = prepare_history(root)
        report = root / 'history-report.sqlite'

        deliver_history(report, packets, ['A', 'B'])
        pending = review_history(report, day, (10, 20), 5, 9)
        _check('HEPU_HISTORY_PENDING_MISMATCH', 'PENDING', pending)

        deliver_history(report, packets, ['C'])
        _check('HEPU_HISTORY_PENDING_MISMATCH', 'PENDING', review_history(report, day, (10, 20), 5, 9))

        deliver_history(report, packets, ['D'])
        expected = {
            'initial': [(12, 7, 5, 'field-12')],
            'revisions': [(8, 12, 'correction', 7, 'field-12')],
        }
        _check('HEPU_HISTORY_COMPLETE_MISMATCH', expected, review_history(report, day, (10, 20), 5, 9))

        deliver_history(report, packets, ['E', 'F'])
        restore = review_history(report, day, (11, 13), 6, 11)
        _check('HEPU_HISTORY_RESTORE_MISMATCH', {
            'initial': [(12, 7, 5, 'field-12')],
            'revisions': [
                (8, 12, 'correction', 7, 'field-12'),
                (10, 12, 'withdrawal', None, 'withdraw-12'),
                (11, 12, 'correction', 0, 'restore-12'),
            ],
        }, restore)

        # Reissue from the frozen bytes and redeliver: the settled result does not change.
        replay_report = root / 'replay.sqlite'
        timeline = _history_lines(replay_report, day, packets)
        final = timeline[-1]['result']
        _check('HEPU_HISTORY_REPLAY_MISMATCH', restore, final)

        print('POINTWISE_HISTORY ' + json.dumps({
            'case_id': 'V6',
            'station': day.station, 'day': day.day,
            'tiles': names,
            'pending': pending,
            'after_d': expected,
            'after_restore': restore,
            'offline_timeline': timeline,
        }, ensure_ascii=False, sort_keys=True, default=list))
        print(json.dumps({'final_after_reissue': final, 'receipts': len(
            deliver_history(replay_report, packets, names))}, ensure_ascii=False, default=list))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
