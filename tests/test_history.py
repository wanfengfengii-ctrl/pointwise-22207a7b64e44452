import json
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from balance.store import open_report_database
from intake.accept import accept
from intake.receipts import lookup_receipt
from issue.history import issue_history
from issue.registry import open_issue_registry
from issue.reissue import reissue
from reports.reconcile import review_history
from samples.history_demo import deliver_history, prepare_history
from source.correct import PointChange
from source.day import StationDay, initialize_day
from source.ingest import apply
from source.store import open_source
from tests import DAY, history_packet, packet

PENDING = 'PENDING'


class HistorySampleTests(unittest.TestCase):
    """Drive the exact scenarios described by HISTORY.md's hand sample."""

    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.report = self.root / 'report.sqlite'

    def test_pending_then_complete(self):
        day, packets, names = prepare_history(self.root)
        self.assertEqual(names, list('ABCDEF'))
        deliver_history(self.report, packets, ['A', 'B'])
        self.assertEqual(review_history(self.report, day, (10, 20), 5, 9), PENDING)
        deliver_history(self.report, packets, ['C'])
        self.assertEqual(review_history(self.report, day, (10, 20), 5, 9), PENDING)
        deliver_history(self.report, packets, ['D'])
        expected = {
            'initial': [(12, 7, 5, 'field-12')],
            'revisions': [(8, 12, 'correction', 7, 'field-12')],
        }
        self.assertEqual(review_history(self.report, day, (10, 20), 5, 9), expected)

    def test_single_tile_queries(self):
        day, packets, _ = prepare_history(self.root)
        deliver_history(self.report, packets, ['A'])
        self.assertEqual(review_history(self.report, day, (11, 13), 6, 7), {
            'initial': [(12, 7, 5, 'field-12')], 'revisions': [],
        })
        other = self.root / 'b-only.sqlite'
        deliver_history(other, packets, ['B'])
        self.assertEqual(review_history(other, day, (15, 20), 7, 9), {'initial': [], 'revisions': []})
        self.assertEqual(review_history(other, day, (10, 20), 5, 9), PENDING)

    def test_restore_window_and_equal_endpoints(self):
        day, packets, _ = prepare_history(self.root)
        deliver_history(self.report, packets, list('ABCD'))
        deliver_history(self.report, packets, ['E', 'F'])
        self.assertEqual(review_history(self.report, day, (11, 13), 6, 11), {
            'initial': [(12, 7, 5, 'field-12')],
            'revisions': [
                (8, 12, 'correction', 7, 'field-12'),
                (10, 12, 'withdrawal', None, 'withdraw-12'),
                (11, 12, 'correction', 0, 'restore-12'),
            ],
        })
        self.assertEqual(review_history(self.report, day, (11, 13), 10, 11), {
            'initial': [], 'revisions': [(11, 12, 'correction', 0, 'restore-12')],
        })
        self.assertEqual(review_history(self.report, day, (12, 12), 6, 11),
                         {'initial': [], 'revisions': []})

    def test_reopen_and_repeat(self):
        day, packets, _ = prepare_history(self.root)
        deliver_history(self.report, packets, list('ABCDEF'))
        first = review_history(self.report, day, (11, 13), 6, 11)
        # Every file was closed by prepare_history; a fresh call reuses the same view contents.
        self.assertEqual(review_history(self.report, day, (11, 13), 6, 11), first)

    def test_any_order_and_redelivery_agree(self):
        day, packets, _ = prepare_history(self.root)
        expected = {
            'initial': [(12, 7, 5, 'field-12')],
            'revisions': [(8, 12, 'correction', 7, 'field-12')],
        }
        for index, order in enumerate((['A', 'B', 'C', 'D'], ['D', 'C', 'B', 'A'],
                                        ['B', 'D', 'A', 'C'], ['C', 'A', 'D', 'B'])):
            with self.subTest(order=order):
                report = self.root / f'order-{index}.sqlite'
                deliver_history(report, packets, order)
                self.assertEqual(review_history(report, day, (10, 20), 5, 9), expected)
                deliver_history(report, packets, ['D'])
                self.assertEqual(review_history(report, day, (10, 20), 5, 9), expected)


    def test_history_does_not_change_daily_settlement(self):
        from reports.daybook import daybook
        path = self.root / 'mixed.sqlite'
        point = packet('P9', 'point', 9, [(12, 13, 'orig12')])
        history = history_packet('H', (10, 20), 5, 9, [(12, 7, 5, 'field-12')],
                                 [(8, 12, 'correction', 7, 'field-12')])
        with closing(open_report_database(path)) as db:
            accept(db, point)
            before = daybook(path, DAY, 10, 20)
            accept(db, history)
            after = daybook(path, DAY, 10, 20)
        self.assertEqual(before, after)
        self.assertEqual([(row.key, row.litres, row.cut) for row in after.rows], [(12, 13, 9)])
        self.assertEqual(review_history(path, DAY, (10, 20), 5, 9), {
            'initial': [(12, 7, 5, 'field-12')],
            'revisions': [(8, 12, 'correction', 7, 'field-12')],
        })


class HistoryConflictTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        sample = json.loads((Path('samples') / 'history-window.json').read_text(encoding='utf-8'))
        self.day = StationDay(sample['station'], sample['day'])
        self.events = sample['events']
        self.outside = sample['outside_at_8']
        self.tiles = {tile[0]: tile[1:] for tile in sample['tiles']}

    def _issue_for(self, events, specs):
        source = self.root / f'src-{len(list(self.root.iterdir()))}.sqlite'
        registry = self.root / f'reg-{len(list(self.root.iterdir()))}.sqlite'
        with closing(open_source(source)) as store:
            initialize_day(store, self.day)
            for index, event in enumerate(events, 1):
                kind, key, litres, origin = event
                apply(store, self.day, f'r{index}', PointChange(kind, key, litres, origin))
            with closing(open_issue_registry(registry)) as issue_store:
                return {
                    name: issue_history(store, issue_store, name, self.day, tuple(bounds), start, end)
                    for name, bounds, start, end in specs
                }

    def _d_good(self):
        bounds, start, end = self.tiles['D']
        return self._issue_for(self.events, [['D', bounds, start, end]])['D']

    def _d_alternative(self):
        altered = list(self.events)
        altered[7] = self.outside
        bounds, start, end = self.tiles['D']
        return self._issue_for(altered, [['D2', bounds, start, end]])['D2']

    def _f_wrong_origin(self):
        altered = list(self.events)
        altered[7] = [altered[7][0], altered[7][1], altered[7][2], 'different-origin']
        bounds, start, end = self.tiles['F']
        return self._issue_for(altered, [['F2', bounds, start, end]])['F2']

    def test_missing_revision_window_rejected_both_orders(self):
        good = self._d_good()
        alt = self._d_alternative()
        for index, order in enumerate(((('D', good), ('D2', alt)), (('D2', alt), ('D', good)))):
            with self.subTest(index=index):
                report = self.root / f'conflict-{index}.sqlite'
                packets = dict(order)
                deliver_history(report, packets, [order[0][0]])
                before = review_history(report, self.day, (10, 15), 7, 9)
                with self.assertRaises(ValueError):
                    deliver_history(report, packets, [order[1][0]])
                with closing(open_report_database(report)) as db:
                    self.assertIsNone(lookup_receipt(db, order[1][0]))
                    self.assertIsNotNone(lookup_receipt(db, order[0][0]))
                self.assertEqual(review_history(report, self.day, (10, 15), 7, 9), before)

    def test_origin_mismatch_on_shared_cut_rejected(self):
        good = self._d_good()
        wrong = self._f_wrong_origin()
        for index, order in enumerate(((('D', good), ('F2', wrong)), (('F2', wrong), ('D', good)))):
            with self.subTest(index=index):
                report = self.root / f'origin-{index}.sqlite'
                packets = dict(order)
                deliver_history(report, packets, [order[0][0]])
                before = review_history(report, self.day, (10, 15), 7, 9)
                with self.assertRaises(ValueError):
                    deliver_history(report, packets, [order[1][0]])
                with closing(open_report_database(report)) as db:
                    self.assertIsNone(lookup_receipt(db, order[1][0]))
                self.assertEqual(review_history(report, self.day, (10, 15), 7, 9), before)


class HistoryIntakeTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(self.enterContext(TemporaryDirectory())) / 'report.sqlite'

    def test_independent_fixture_pending_until_full(self):
        left = history_packet('L', (10, 20), 5, 7, [(12, 7, 5, 'field-12')], [])
        right = history_packet('R', (15, 20), 7, 9, [], [])
        middle = history_packet('M', (10, 15), 7, 9, [(12, 7, 5, 'field-12')],
                                [(8, 12, 'correction', 7, 'field-12')])
        deliver_history(self.path, {'L': left, 'R': right}, ['L', 'R'])
        self.assertEqual(review_history(self.path, DAY, (10, 20), 5, 9), PENDING)
        deliver_history(self.path, {'M': middle}, ['M'])
        self.assertEqual(review_history(self.path, DAY, (10, 20), 5, 9), {
            'initial': [(12, 7, 5, 'field-12')],
            'revisions': [(8, 12, 'correction', 7, 'field-12')],
        })

    def test_same_value_correction_kept_by_true_cut(self):
        changes = [
            (1, 12, 'reading', 7, 'field-12'),
            (2, 12, 'correction', 7, 'same-12'),
            (3, 12, 'withdrawal', None, 'wd12'),
            (4, 12, 'correction', 0, 'restore0'),
        ]
        payload = history_packet('H', (10, 20), 0, 4, [], changes)
        deliver_history(self.path, {'H': payload}, ['H'])
        result = review_history(self.path, DAY, (10, 20), 0, 4)
        self.assertEqual(result['initial'], [])
        self.assertEqual(result['revisions'], [
            (1, 12, 'reading', 7, 'field-12'),
            (2, 12, 'correction', 7, 'same-12'),
            (3, 12, 'withdrawal', None, 'wd12'),
            (4, 12, 'correction', 0, 'restore0'),
        ])

    def test_reformatted_redelivery_is_same_receipt(self):
        payload = history_packet('H', (10, 20), 5, 7, [(12, 7, 5, 'field-12')], [])
        with closing(open_report_database(self.path)) as db:
            first = accept(db, payload)
            reformatted = json.dumps(json.loads(payload), indent=2, sort_keys=True).encode('utf-8')
            self.assertEqual(accept(db, reformatted), first)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM receipts').fetchone(), (1,))

    def test_bad_history_packets_rejected(self):
        good = json.loads(history_packet(
            'H', (10, 20), 5, 7, [(12, 7, 5, 'field-12')],
            [(6, 12, 'correction', 7, 'field-12')],
        ))
        failures = [
            {**good, 'kind': 'stocktake'},
            {**good, 'version': 3},
            {**good, 'bounds': [20, 10]},
            {**good, 'start': 7, 'end': 5},
            {**good, 'start': 5, 'end': 5},
            {**good, 'initial': [{'key': 20, 'litres': 7, 'cut': 5, 'origin': 'x'}]},
            {**good, 'initial': [{'key': 12, 'litres': 7, 'cut': 6, 'origin': 'x'}]},
            {**good, 'changes': [{'cut': 8, 'key': 12, 'kind': 'correction', 'litres': 7, 'origin': 'x'}]},
            {**good, 'changes': [{'cut': 6, 'key': 12, 'kind': 'withdrawal', 'litres': 0, 'origin': 'x'}]},
            {**good, 'changes': [{'cut': 6, 'key': 12, 'kind': 'mystery', 'litres': 7, 'origin': 'x'}]},
            {**good, 'changes': [{'cut': 6, 'key': 12, 'kind': 'correction', 'litres': 7.0, 'origin': 'x'}]},
            {**good, 'changes': [{'cut': 6, 'key': 20, 'kind': 'correction', 'litres': 7, 'origin': 'x'}]},
            {key: value for key, value in good.items() if key != 'start'},
            {**good, 'extra': 1},
        ]
        with closing(open_report_database(self.path)) as db:
            for index, broken in enumerate(failures):
                with self.subTest(index=index), self.assertRaises(ValueError):
                    accept(db, json.dumps(broken).encode('utf-8'))
            self.assertEqual(db.execute('SELECT COUNT(*) FROM receipts').fetchone(), (0,))

    def test_failed_commit_leaves_pending_then_recovers(self):
        left = history_packet('L', (10, 20), 5, 7, [(12, 7, 5, 'field-12')], [])
        right = history_packet('R', (15, 20), 7, 9, [], [])
        middle = history_packet('M', (10, 15), 7, 9, [(12, 7, 5, 'field-12')],
                                [(8, 12, 'correction', 7, 'field-12')])
        attempts = []

        def reject_commit(action, operation, _unused, _database, _source):
            if action == sqlite3.SQLITE_TRANSACTION and operation == 'COMMIT':
                attempts.append(operation)
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        with closing(open_report_database(self.path)) as writer:
            for name, payload in (('L', left), ('R', right)):
                accept(writer, payload)
            writer.set_authorizer(reject_commit)
            with self.assertRaises(sqlite3.DatabaseError):
                accept(writer, middle)
            writer.set_authorizer(None)
            self.assertEqual(attempts, ['COMMIT'])
            with closing(open_report_database(self.path)) as observer:
                self.assertIsNone(lookup_receipt(observer, 'M'))
                self.assertEqual(observer.execute('SELECT COUNT(*) FROM receipts').fetchone(), (2,))
        self.assertEqual(review_history(self.path, DAY, (10, 20), 5, 9), PENDING)
        with closing(open_report_database(self.path)) as writer:
            receipt = accept(writer, middle)
            self.assertEqual(accept(writer, middle), receipt)
        self.assertEqual(review_history(self.path, DAY, (10, 20), 5, 9), {
            'initial': [(12, 7, 5, 'field-12')],
            'revisions': [(8, 12, 'correction', 7, 'field-12')],
        })


class HistoryIssueTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(TemporaryDirectory()))
        self.source_path = self.directory / 'source.sqlite'
        self.registry_path = self.directory / 'issue.sqlite'

    def _seed(self):
        with closing(open_source(self.source_path)) as source:
            initialize_day(source, DAY)
            apply(source, DAY, 'r1', PointChange('reading', 12, 7, 'field-12'))
            apply(source, DAY, 'r2', PointChange('reading', 15, 9, 'field-15'))
            apply(source, DAY, 'r3', PointChange('correction', 12, 7, 'same-12'))

    def test_reissue_and_identity(self):
        self._seed()
        with closing(open_source(self.source_path)) as source, closing(open_issue_registry(self.registry_path)) as registry:
            payload = issue_history(source, registry, 'H', DAY, (10, 20), 1, 3)
            body = json.loads(payload)
            self.assertEqual((body['version'], body['kind']), (2, 'history'))
            self.assertEqual(body['initial'], [{'key': 12, 'litres': 7, 'cut': 1, 'origin': 'field-12'}])
            self.assertEqual(body['changes'], [
                {'cut': 2, 'key': 15, 'kind': 'reading', 'litres': 9, 'origin': 'field-15'},
                {'cut': 3, 'key': 12, 'kind': 'correction', 'litres': 7, 'origin': 'same-12'},
            ])
            self.assertEqual(issue_history(source, registry, 'H', DAY, (10, 20), 1, 3), payload)
            with self.assertRaises(ValueError):
                issue_history(source, registry, 'H', DAY, (10, 20), 1, 2)
            with self.assertRaises(ValueError):
                issue_history(source, registry, 'H', DAY, (10, 20), 3, 3)
            with self.assertRaises(ValueError):
                issue_history(source, registry, 'H', DAY, (10, 20), 0, 9)
            with self.assertRaises(ValueError):
                issue_history(source, registry, 'H', DAY, (20, 10), 1, 3)
        with closing(open_issue_registry(self.registry_path)) as registry:
            self.assertEqual(reissue(registry, 'H'), payload)
            self.assertIsNone(reissue(registry, 'missing'))

    def test_empty_window_tile(self):
        self._seed()
        with closing(open_source(self.source_path)) as source, closing(open_issue_registry(self.registry_path)) as registry:
            payload = issue_history(source, registry, 'H', DAY, (40, 50), 2, 3)
            body = json.loads(payload)
            self.assertEqual((body['initial'], body['changes']), ([], []))
            zero = issue_history(source, registry, 'Z', DAY, (40, 40), 2, 3)
            self.assertEqual((json.loads(zero)['initial'], json.loads(zero)['changes']), ([], []))


if __name__ == '__main__':
    unittest.main()
