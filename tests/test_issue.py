import json
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from issue.artifact import encode_artifact
from issue.registry import open_issue_registry
from issue.reissue import reissue
from issue.requests import issue
from issue.stocktake import freeze_stocktake
from source.correct import PointChange, make_correction, make_withdrawal
from source.day import StationDay, initialize_day
from source.ingest import apply
from source.store import open_source
from tests import DAY


class IssueTests(unittest.TestCase):
    def setUp(self):
        directory = Path(self.enterContext(TemporaryDirectory()))
        self.registry_path = directory / 'issue.sqlite'
        self.source_path = directory / 'source.sqlite'

    def test_frozen_reissue(self):
        with closing(open_source(self.source_path)) as source, closing(open_issue_registry(self.registry_path)) as registry:
            initialize_day(source, DAY)
            first = apply(source, DAY, 'first', PointChange('reading', 12, 7, 'original'))
            frozen = freeze_stocktake(source, 'S1', DAY, first.cut, 10, 20)
            published = issue(source, registry, 'S1', DAY, first.cut, bounds=(10, 20))
            apply(source, DAY, 'later', make_correction(12, 11, 'correction'))
            self.assertEqual(encode_artifact(frozen), published)
            self.assertEqual(issue(source, registry, 'S1', DAY, first.cut, bounds=(10, 20)), published)
            later_request = issue(source, registry, 'S2', DAY, first.cut, bounds=(10, 20))
            self.assertEqual(json.loads(later_request), {**json.loads(published), 'artifact_id': 'S2'})
            with self.assertRaises(ValueError):
                issue(source, registry, 'S1', DAY, 2, bounds=(10, 20))
        with closing(open_issue_registry(self.registry_path)) as registry:
            self.assertEqual(reissue(registry, 'S1'), published)
        self.assertEqual(json.loads(published), {
            'version': 1, 'artifact_id': 'S1', 'kind': 'stocktake', 'station': 'HP', 'day': '2026-11-25',
            'cut': 1, 'bounds': [10, 20], 'rows': [{'key': 12, 'litres': 7, 'origin': 'original'}],
        })

    def test_unknown_cut(self):
        with closing(open_source(self.source_path)) as source, closing(open_issue_registry(self.registry_path)) as registry:
            initialize_day(source, DAY)
            for cut, day in ((99, DAY), (2**80, DAY), (-1, DAY), (True, DAY), (0, StationDay('OTHER', DAY.day))):
                with self.subTest(cut=cut, day=day), self.assertRaises(ValueError):
                    issue(source, registry, 'missing', day, cut, bounds=(10, 20))
                self.assertIsNone(reissue(registry, 'missing'))
            with self.assertRaises(ValueError):
                issue(source, registry, 'missing', DAY, 0, bounds=(20, 10))
            self.assertIsNone(reissue(registry, 'missing'))
            self.assertEqual(json.loads(issue(source, registry, 'missing', DAY, 0, bounds=(10, 20)))['rows'], [])

    def test_full_and_empty_bounds(self):
        with closing(open_source(self.source_path)) as source, closing(open_issue_registry(self.registry_path)) as registry:
            initialize_day(source, DAY)
            apply(source, DAY, 'first', PointChange('reading', 12, 11, 'orig12'))
            sparse = issue(source, registry, 'wide', DAY, 1, bounds=(10, 20))
            narrow = issue(source, registry, 'narrow', DAY, 1, bounds=(12, 13))
            empty = issue(source, registry, 'empty', DAY, 1, bounds=(14, 18))
            zero_width = issue(source, registry, 'zero', DAY, 1, bounds=(12, 12))
            for name, payload, bounds, rows in (
                ('wide', sparse, [10, 20], [{'key': 12, 'litres': 11, 'origin': 'orig12'}]),
                ('narrow', narrow, [12, 13], [{'key': 12, 'litres': 11, 'origin': 'orig12'}]),
                ('empty', empty, [14, 18], []), ('zero', zero_width, [12, 12], []),
            ):
                with self.subTest(name=name):
                    self.assertEqual(reissue(registry, name), payload)
                    body = json.loads(payload)
                    self.assertEqual((body['bounds'], body['cut'], body['rows']), (bounds, 1, rows))

    def test_point_revision(self):
        with closing(open_source(self.source_path)) as source, closing(open_issue_registry(self.registry_path)) as registry:
            initialize_day(source, DAY)
            apply(source, DAY, 'first', PointChange('reading', 12, 7, 'orig12'))
            apply(source, DAY, 'edit', make_correction(12, 11, 'edit12'))
            apply(source, DAY, 'withdraw', make_withdrawal(12, 'withdraw12'))
            payload = json.loads(issue(source, registry, 'P1', DAY, 1, key=12))
            self.assertEqual((payload['kind'], payload['cut'], payload['bounds']), ('point', 1, None))
            self.assertEqual(payload['rows'], [{'key': 12, 'litres': 7, 'origin': 'orig12'}])
            withdrawal = json.loads(issue(source, registry, 'P3', DAY, 3, key=12))
            self.assertEqual(withdrawal['rows'], [{'key': 12, 'litres': None, 'origin': 'withdraw12'}])
            with self.assertRaises(ValueError):
                issue(source, registry, 'wrong', DAY, 1, key=15)
            with self.assertRaises(ValueError):
                issue(source, registry, 'both', DAY, 1, key=12, bounds=(10, 20))
            self.assertIsNone(reissue(registry, 'wrong'))
            self.assertIsNone(reissue(registry, 'both'))
