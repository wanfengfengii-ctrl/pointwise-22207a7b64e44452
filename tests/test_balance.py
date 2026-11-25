import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from reports.daybook import daybook
from reports.provenance import trace
from samples.demo import deliver, prepare_delivery
from tests import DAY, packet


def entries(book):
    return [(row.key, row.litres, row.cut, row.origin, row.artifact_id) for row in book.rows]


class BalanceTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.report = self.root / 'report.sqlite'

    def test_late_point_after_stocktake(self):
        day, payloads, batches = prepare_delivery(self.root)
        first = deliver(self.report, payloads, batches[0])
        late = deliver(self.report, payloads, batches[1])
        book = daybook(self.report, day, 10, 20)
        self.assertEqual([(receipt.artifact_id, receipt.number) for receipt in first + late],
                         [('P9', 1), ('S8', 2), ('P7', 3)])
        self.assertEqual(entries(book), [(12, 13, 9, 'orig12', 'P9')])
        self.assertEqual(book.total_litres, 13)
        self.assertIsNone(trace(self.report, day, 15))
        origin = trace(self.report, day, 12)
        self.assertEqual((origin.cut, origin.origin, origin.artifact_id), (9, 'orig12', 'P9'))

    def test_pending_absence_from_independent_packet(self):
        payloads = {
            'S8': packet('S8', 'stocktake', 8, [(12, 11, 'orig12')], bounds=(10, 20)),
            'P7': packet('P7', 'point', 7, [(15, 7, 'orig15')]),
        }
        deliver(self.report, payloads, ['S8'])
        late, = deliver(self.report, payloads, ['P7'])
        self.assertEqual(late.artifact_id, 'P7')
        book = daybook(self.report, DAY, 10, 20)
        self.assertEqual(entries(book), [(12, 11, 8, 'orig12', 'S8')])
        self.assertEqual(book.total_litres, 11)
        self.assertIsNone(trace(self.report, DAY, 15))

    def test_newer_point_survives_independent_stocktake_in_both_orders(self):
        payloads = {
            'S8': packet('S8', 'stocktake', 8, [(12, 11, 'orig12')], bounds=(10, 20)),
            'P9': packet('P9', 'point', 9, [(12, 13, 'orig12')]),
        }
        for index, order in enumerate((['P9', 'S8'], ['S8', 'P9'])):
            with self.subTest(order=order):
                report = self.root / f'order-{index}.sqlite'
                deliver(report, payloads, order)
                book = daybook(report, DAY, 10, 20)
                self.assertEqual(entries(book), [(12, 13, 9, 'orig12', 'P9')])
                self.assertEqual(book.total_litres, 13)

    def test_overlap_reopen_and_boundary_keys(self):
        payloads = {
            'P4': packet('P4', 'point', 4, [(20, 19, 'orig20')]),
            'P7': packet('P7', 'point', 7, [(15, 7, 'orig15')]),
            'S8': packet('S8', 'stocktake', 8, [(12, 11, 'orig12'), (18, 5, 'orig18')], bounds=(10, 20)),
            'P9': packet('P9', 'point', 9, [(15, 9, 'retry15')]),
            'S10': packet('S10', 'stocktake', 10, [], bounds=(14, 18)),
            'P11': packet('P11', 'point', 11, [(15, 17, 'restore15')]),
        }
        deliver(self.report, payloads, ['P4', 'S8'])
        older, = deliver(self.report, payloads, ['P7'])
        deliver(self.report, payloads, ['P9'])
        self.assertEqual(daybook(self.report, DAY, 10, 21).total_litres, 44)
        deliver(self.report, payloads, ['S10'])
        self.assertIsNone(trace(self.report, DAY, 15))
        redelivered, = deliver(self.report, payloads, ['P7'])
        self.assertEqual(older, redelivered)
        self.assertEqual(entries(daybook(self.report, DAY, 10, 21)), [
            (12, 11, 8, 'orig12', 'S8'), (18, 5, 8, 'orig18', 'S8'), (20, 19, 4, 'orig20', 'P4'),
        ])
        deliver(self.report, payloads, ['P11'])
        book = daybook(self.report, DAY, 10, 21)
        self.assertEqual(book.total_litres, 52)
        self.assertEqual(entries(book), [
            (12, 11, 8, 'orig12', 'S8'), (15, 17, 11, 'restore15', 'P11'),
            (18, 5, 8, 'orig18', 'S8'), (20, 19, 4, 'orig20', 'P4'),
        ])

    def test_empty_stocktake_includes_its_lower_bound(self):
        payloads = {
            'P1': packet('P1', 'point', 1, [(18, 5, 'origin18')]),
            'P2': packet('P2', 'point', 2, [(14, 7, 'origin14')]),
            'S3': packet('S3', 'stocktake', 3, [], bounds=(14, 18)),
        }
        deliver(self.report, payloads, ['P1', 'S3'])
        deliver(self.report, payloads, ['P2'])
        self.assertEqual(entries(daybook(self.report, DAY, 14, 19)), [(18, 5, 1, 'origin18', 'P1')])
        self.assertIsNone(trace(self.report, DAY, 14))

    def test_withdraw_restore(self):
        payloads = {
            'P1': packet('P1', 'point', 1, [(13, 4, 'orig13')]),
            'P2': packet('P2', 'point', 2, [(12, 7, 'orig12')]),
            'P3': packet('P3', 'point', 3, [(12, None, 'withdraw12')]),
            'P4': packet('P4', 'point', 4, [(12, 0, 'restore12')]),
            'P5': packet('P5', 'point', 5, [(12, None, 'late-withdraw12')]),
            'P6': packet('P6', 'point', 6, [(12, 11, 'new-reading')]),
        }
        deliver(self.report, payloads, ['P1', 'P3', 'P2'])
        self.assertEqual(entries(daybook(self.report, DAY, 10, 20)), [(13, 4, 1, 'orig13', 'P1')])
        deliver(self.report, payloads, ['P4'])
        self.assertEqual(entries(daybook(self.report, DAY, 12, 13)), [(12, 0, 4, 'restore12', 'P4')])
        deliver(self.report, payloads, ['P6', 'P5'])
        self.assertEqual(entries(daybook(self.report, DAY, 12, 13)), [(12, 11, 6, 'new-reading', 'P6')])

    def test_equivalent_evidence_has_stable_attribution(self):
        payloads = {
            'A': packet('A', 'stocktake', 2, [(-1, 0, 'orig')], bounds=(-2, 0)),
            'Z': packet('Z', 'point', 2, [(-1, 0, 'orig')]),
        }
        for index, order in enumerate((['A', 'Z'], ['Z', 'A'])):
            with self.subTest(order=order):
                report = self.root / f'equal-{index}.sqlite'
                deliver(report, payloads, order)
                self.assertEqual(entries(daybook(report, DAY, -2, 0)), [(-1, 0, 2, 'orig', 'A')])
