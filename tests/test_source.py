import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from source.correct import PointChange, make_correction, make_withdrawal
from source.day import StationDay, initialize_day
from source.history import source_at, source_change_at
from source.ingest import apply
from source.store import open_source
from tests import DAY


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.db = Path(self.enterContext(TemporaryDirectory())) / 'source.sqlite'

    def test_revision_readback(self):
        with closing(open_source(self.db)) as source:
            self.assertTrue(initialize_day(source, DAY))
            self.assertEqual(source_at(source, DAY, 0, 10, 20), ())
            first = apply(source, DAY, 'reading', PointChange('reading', 12, 7, 'field-12'))
            newer = apply(source, DAY, 'edit', make_correction(12, 11, 'verified-12'))
            self.assertEqual((first.cut, first.origin, newer.cut, newer.origin),
                             (1, 'field-12', 2, 'verified-12'))
        with closing(open_source(self.db)) as source:
            self.assertFalse(initialize_day(source, DAY))
            old_rows = source_at(source, DAY, first.cut, 10, 20)
            new_rows = source_at(source, DAY, newer.cut, 10, 20)
            self.assertEqual([(row.key, row.litres, row.origin) for row in old_rows], [(12, 7, 'field-12')])
            self.assertEqual([(row.key, row.litres, row.origin) for row in new_rows], [(12, 11, 'verified-12')])
            self.assertEqual(apply(source, DAY, 'edit', make_correction(12, 11, 'verified-12')), newer)
            self.assertEqual(apply(source, DAY, 'next', make_correction(12, 13, 'field-12')).cut, 3)

    def test_invalid_correction(self):
        with closing(open_source(self.db)) as source:
            initialize_day(source, DAY)
            first = apply(source, DAY, 'reading', PointChange('reading', 12, 7, 'field'))
            for bad in (True, 11.0, '11', None):
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    apply(source, DAY, 'edit', make_correction(12, bad, 'verification'))
            self.assertEqual(source_at(source, DAY, first.cut, 10, 20), (first,))
            with self.assertRaises(ValueError):
                source_at(source, DAY, 2, 10, 20)
            self.assertEqual(apply(source, DAY, 'edit', make_correction(12, 11, 'verification')).cut, 2)

    def test_request_identity(self):
        change = PointChange('reading', 12, 7, 'field')
        other_day = StationDay('HP', '2026-11-26')
        with closing(open_source(self.db)) as source:
            with self.assertRaises(ValueError):
                apply(source, DAY, 'record', change)
            initialize_day(source, DAY)
            initialize_day(source, other_day)
            first = apply(source, DAY, 'record', change)
            correction = apply(source, DAY, 'edit', make_correction(12, 11, 'verification'))
            self.assertEqual(apply(source, DAY, 'record', change), first)
            for different in (PointChange('reading', 12, 8, 'field'),
                              PointChange('reading', 12, 7, 'other'),
                              PointChange('reading', 13, 7, 'field')):
                with self.subTest(change=different), self.assertRaises(ValueError):
                    apply(source, DAY, 'record', different)
            with self.assertRaises(ValueError):
                apply(source, DAY, '  ', change)
            with self.assertRaises(ValueError):
                apply(source, DAY, 'blank-origin', make_correction(12, 17, ' '))
            self.assertEqual(source_at(source, DAY, 2, 10, 20), (correction,))
            self.assertEqual(apply(source, other_day, 'record', change).cut, 1)
            self.assertEqual(apply(source, DAY, 'next', make_correction(12, 17, 'field')).cut, 3)

    def test_withdraw_restore(self):
        with closing(open_source(self.db)) as source:
            initialize_day(source, DAY)
            first = apply(source, DAY, 'first', PointChange('reading', 10, 7, 'ten'))
            zero = apply(source, DAY, 'zero', PointChange('reading', 2, 0, 'two'))
            self.assertEqual(source_at(source, DAY, 2, 2, 11), (zero, first))
            withdrawn = apply(source, DAY, 'withdraw', make_withdrawal(10, 'withdraw-ten'))
            self.assertEqual(source_at(source, DAY, withdrawn.cut, 2, 11), (zero,))
            self.assertEqual(source_change_at(source, DAY, withdrawn.cut, 10), withdrawn)
            self.assertIsNone(withdrawn.litres)
            self.assertEqual((withdrawn.kind, withdrawn.origin), ('withdrawal', 'withdraw-ten'))
            with self.assertRaises(ValueError):
                apply(source, DAY, 'second-withdrawal', make_withdrawal(10, 'withdraw-ten'))
            restored = apply(source, DAY, 'restore', make_correction(10, 11, 'restore-ten'))
            self.assertEqual(restored.cut, 4)
            self.assertEqual(source_at(source, DAY, 4, 10, 11), (restored,))
            self.assertEqual(source_at(source, DAY, 4, 2, 10), (zero,))
            self.assertEqual(source_at(source, DAY, 4, 10, 10), ())
            for lower, upper in ((11, 10), (False, 10), (2, 10.0)):
                with self.subTest(bounds=(lower, upper)), self.assertRaises(ValueError):
                    source_at(source, DAY, 4, lower, upper)
            with self.assertRaises(ValueError):
                source_at(source, StationDay('OTHER', DAY.day), 0, 2, 11)
