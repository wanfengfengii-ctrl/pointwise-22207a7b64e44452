import json
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from balance.store import open_report_database
from intake.accept import accept
from intake.receipts import lookup_receipt
from reports.daybook import daybook
from tests import DAY, packet


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(self.enterContext(TemporaryDirectory())) / 'report.sqlite'

    def test_duplicate_and_conflict(self):
        original = packet('P1', 'point', 1, [(12, 7, 'orig12')])
        changed = packet('P1', 'point', 1, [(12, 11, 'orig12')])
        with closing(open_report_database(self.path)) as db:
            first = accept(db, original)
            self.assertEqual(accept(db, original), first)
            self.assertEqual(first.number, 1)
        with closing(open_report_database(self.path)) as db:
            reformatted = json.dumps(json.loads(original), indent=2).encode('utf-8')
            self.assertEqual(accept(db, reformatted), first)
            with self.assertRaisesRegex(ValueError, 'identity conflict'):
                accept(db, changed)
            self.assertEqual(lookup_receipt(db, 'P1'), first)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM receipts').fetchone(), (1,))
        book = daybook(self.path, DAY, 10, 20)
        self.assertEqual(book.total_litres, 7)
        self.assertEqual(book.rows[0].artifact_id, 'P1')

    def test_invalid_packet(self):
        original = packet('P1', 'point', 1, [(12, 7, 'orig12')])
        probe = json.loads(packet('bad', 'point', 2, [(12, 11, 'other')]))
        failures = [
            b'{', b'\xff', b'{"version":1,"version":1}',
            json.dumps({**probe, 'version': True}).encode(),
            json.dumps({**probe, 'version': 2}).encode(),
            json.dumps({**probe, 'station': ' '}).encode(),
            json.dumps({**probe, 'kind': 'unknown'}).encode(),
            json.dumps({**probe, 'cut': '2'}).encode(),
            json.dumps({**probe, 'bounds': [10, 20, 30]}).encode(),
            json.dumps({**probe, 'extension': 'extra'}).encode(),
            packet('bad', 'point', 0, [(12, 11, 'other')]),
            packet('bad', 'point', 2, [(True, 11, 'other')]),
            packet('bad', 'point', 2, [(12, 11.0, 'other')]),
            packet('bad', 'point', 2, [(12, '11', 'other')]),
            packet('bad', 'point', 2, [(12, 11, '')]),
            packet('bad', 'point', 2, [(12, 11, 'other'), (13, 1, 'orig13')]),
            packet('bad', 'point', 2, [(12, 11, 'other')], bounds=(10, 20)),
            packet('bad', 'stocktake', 2, [], bounds=(20, 10)),
            packet('bad', 'stocktake', 2, [], bounds=(False, 20)),
            packet('bad', 'stocktake', 2, [(20, 11, 'boundary')], bounds=(10, 20)),
            packet('bad', 'stocktake', 2, [(12, None, 'other')], bounds=(10, 20)),
            packet('bad', 'stocktake', 2, [(12, 11, 'other'), (11, 1, 'orig11')], bounds=(10, 20)),
            packet('bad', 'stocktake', 2, [(12, 11, 'other'), (12, 1, 'duplicate')], bounds=(10, 20)),
        ]
        with closing(open_report_database(self.path)) as db:
            initial_receipt = accept(db, original)
            initial_book = daybook(self.path, DAY, 10, 20)
            for payload in failures:
                with self.subTest(payload=payload), self.assertRaises(ValueError):
                    accept(db, payload)
            self.assertIsNone(lookup_receipt(db, 'bad'))
            self.assertEqual(lookup_receipt(db, 'P1'), initial_receipt)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM receipts').fetchone(), (1,))
        self.assertEqual(daybook(self.path, DAY, 10, 20), initial_book)

    def test_atomic_posting(self):
        original = packet('P6', 'point', 6, [(12, 7, 'orig12')])
        old_missing = packet('P5', 'point', 5, [(15, 3, 'orig15')])
        stocktake = packet('S8', 'stocktake', 8, [(12, 11, 'verified12')], bounds=(10, 20))
        commit_attempts = []

        def reject_commit(action, operation, _unused, _database, _source):
            if action == sqlite3.SQLITE_TRANSACTION and operation == 'COMMIT':
                commit_attempts.append(operation)
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        with closing(open_report_database(self.path)) as writer:
            first = accept(writer, original)
            before = daybook(self.path, DAY, 10, 20)
            self.assertEqual(before.total_litres, 7)
            writer.set_authorizer(reject_commit)
            with self.assertRaises(sqlite3.DatabaseError):
                accept(writer, stocktake)
            self.assertEqual(commit_attempts, ['COMMIT'])
            self.assertFalse(writer.in_transaction)
            with closing(open_report_database(self.path)) as observer:
                self.assertIsNone(lookup_receipt(observer, 'S8'))
                self.assertEqual(lookup_receipt(observer, 'P6'), first)
                self.assertEqual(observer.execute('SELECT COUNT(*) FROM receipts').fetchone(), (1,))
                self.assertEqual(daybook(self.path, DAY, 10, 20), before)

        with closing(open_report_database(self.path)) as writer:
            accept(writer, old_missing)
            self.assertEqual(daybook(self.path, DAY, 10, 20).total_litres, 10)
            receipt = accept(writer, stocktake)
            self.assertEqual(receipt.number, 3)
            self.assertEqual(accept(writer, stocktake), receipt)
            self.assertEqual(writer.execute('SELECT COUNT(*) FROM receipts').fetchone(), (3,))
        with closing(open_report_database(self.path)) as observer:
            self.assertEqual(lookup_receipt(observer, 'S8'), receipt)
        after = daybook(self.path, DAY, 10, 20)
        self.assertEqual([(row.key, row.litres, row.cut, row.artifact_id) for row in after.rows],
                         [(12, 11, 8, 'S8')])
        self.assertEqual(after.total_litres, 11)
