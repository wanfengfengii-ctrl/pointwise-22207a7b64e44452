import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from balance.store import open_report_database
from intake.accept import accept
from reports.daybook import daybook
from reports.provenance import trace
from reports.reconcile import reconcile_range
from samples.demo import deliver, prepare_delivery
from source.day import StationDay
from tests import DAY, packet


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.report = self.root / 'report.sqlite'

    def test_offline_daybook(self):
        day, payloads, batches = prepare_delivery(self.root)
        for batch in batches:
            deliver(self.report, payloads, batch)
        for part in ('source.sqlite', 'issue.sqlite'):
            (self.root / part).rename(self.root / (part + '.offline'))
        report = reconcile_range(self.report, day, 10, 21)
        self.assertEqual([(row.key, row.litres, row.cut) for row in report.book.rows],
                         [(12, 13, 9), (15, 17, 11), (18, 5, 10), (20, 19, 4)])
        self.assertEqual(report.book.total_litres, 54)
        self.assertEqual([(item.key, item.cut, item.origin, item.artifact_id) for item in report.traces], [
            (12, 9, 'orig12', 'P9'), (15, 11, 'orig15', 'P11'),
            (18, 10, 'orig18', 'Z10'), (20, 4, 'orig20', 'P4'),
        ])
        throughout = daybook(self.report, day, 13, 14)
        self.assertEqual((throughout.rows, throughout.total_litres), ((), 0))
        self.assertIsNone(trace(self.report, day, 13))

    def test_empty_and_range(self):
        other_day = StationDay('HP', '2026-11-26')
        with closing(open_report_database(self.report)) as db:
            accept(db, packet('P1', 'point', 1, [(10, 7, 'ten')]))
            accept(db, packet('other', 'point', 1, [(10, 11, 'next day')], day=other_day))
        self.assertEqual(daybook(self.report, DAY, 10, 11).total_litres, 7)
        self.assertEqual(daybook(self.report, other_day, 10, 11).total_litres, 11)
        for day, lower, upper in ((DAY, 10, 10), (DAY, 1, 10), (StationDay('NORTH', DAY.day), 0, 20)):
            book = daybook(self.report, day, lower, upper)
            self.assertEqual((book.rows, book.total_litres), ((), 0))
        for lower, upper in ((11, 10), (True, 20), ('10', 20), (0, 20.0)):
            with self.subTest(bounds=(lower, upper)), self.assertRaises(ValueError):
                daybook(self.report, DAY, lower, upper)
        with self.assertRaises(ValueError):
            trace(self.report, DAY, True)

    def test_exact_total(self):
        big = 2**80
        with closing(open_report_database(self.report)) as db:
            accept(db, packet('P1', 'point', 1, [(10, 1, 'ten')]))
            accept(db, packet('P2', 'point', 2, [(2, 9007199254740992, 'two')]))
            accept(db, packet('P3', 'point', 3, [(big, big, 'large')]))
            accept(db, packet('P4', 'point', 4, [(-big, 0, 'zero')]))
        book = daybook(self.report, DAY, 0, 11)
        self.assertEqual([(row.key, row.litres) for row in book.rows], [(2, 9007199254740992), (10, 1)])
        self.assertEqual(book.total_litres, 9007199254740993)
        self.assertEqual([row.key for row in daybook(self.report, DAY, -big, big + 1).rows], [-big, 2, 10, big])
        self.assertEqual(daybook(self.report, DAY, big, big + 1).total_litres, big)

    def test_winning_receipt(self):
        with closing(open_report_database(self.report)) as db:
            accept(db, packet('new', 'point', 9, [(12, 13, 'verified12')]))
            late = accept(db, packet('late', 'point', 6, [(12, 11, 'orig12')]))
            self.assertEqual(late.number, 2)
        book = daybook(self.report, DAY, 10, 20)
        self.assertEqual([(row.litres, row.cut, row.artifact_id) for row in book.rows], [(13, 9, 'new')])
        item = trace(self.report, DAY, 12)
        self.assertEqual((item.key, item.cut, item.origin, item.artifact_id), (12, 9, 'verified12', 'new'))
        with closing(open_report_database(self.report)) as db:
            accept(db, packet('withdraw', 'point', 10, [(12, None, 'withdraw12')]))
        self.assertIsNone(trace(self.report, DAY, 12))
        self.assertEqual(daybook(self.report, DAY, 10, 20).total_litres, 0)

    def test_fixed_view(self):
        with closing(open_report_database(self.report)) as writer:
            accept(writer, packet('first', 'point', 8, [(12, 11, 'morning')]))
            calls = []

            def interleave(book):
                self.assertEqual((book.total_litres, book.rows[0].artifact_id), (11, 'first'))
                receipt = accept(writer, packet('second', 'point', 9, [(12, 13, 'evening')]))
                calls.append(receipt.artifact_id)
                self.assertEqual(daybook(self.report, DAY, 10, 20).total_litres, 13)

            first = reconcile_range(self.report, DAY, 10, 20, after_daybook=interleave)
        self.assertEqual(calls, ['second'])
        self.assertEqual((first.book.total_litres, first.book.rows[0].cut), (11, 8))
        self.assertEqual([(item.key, item.cut, item.origin, item.artifact_id) for item in first.traces],
                         [(12, 8, 'morning', 'first')])
        second = reconcile_range(self.report, DAY, 10, 20)
        self.assertEqual((second.book.total_litres, second.book.rows[0].cut), (13, 9))
        self.assertEqual([(item.key, item.cut, item.origin, item.artifact_id) for item in second.traces],
                         [(12, 9, 'evening', 'second')])
