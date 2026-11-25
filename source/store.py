from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from os import PathLike
from typing import Iterator

from source.correct import PointChange
from source.day import StationDay

_SCHEMA = '''
CREATE TABLE IF NOT EXISTS station_days (
    station TEXT NOT NULL,
    day TEXT NOT NULL,
    PRIMARY KEY (station, day)
);
CREATE TABLE IF NOT EXISTS source_revisions (
    station TEXT NOT NULL,
    day TEXT NOT NULL,
    cut INTEGER NOT NULL,
    request_id TEXT NOT NULL,
    key TEXT NOT NULL,
    kind TEXT NOT NULL,
    litres TEXT,
    origin TEXT NOT NULL,
    PRIMARY KEY (station, day, cut),
    UNIQUE (station, day, request_id),
    FOREIGN KEY (station, day) REFERENCES station_days (station, day)
);
CREATE INDEX IF NOT EXISTS source_revisions_key
    ON source_revisions (station, day, key, cut DESC);
'''
_MAX_SQLITE_INTEGER = (1 << 63) - 1


@contextmanager
def write_transaction(db: sqlite3.Connection) -> Iterator[None]:
    db.execute('BEGIN IMMEDIATE')
    try:
        yield
        db.execute('COMMIT')
    except BaseException:
        if db.in_transaction:
            db.execute('ROLLBACK')
        raise


@dataclass(frozen=True)
class SourceRevision:
    cut: int
    request_id: str
    key: int
    kind: str
    litres: int | None
    origin: str

    @classmethod
    def from_record(cls, record: tuple) -> SourceRevision:
        cut, request_id, key, kind, litres, origin = record
        value = None if litres is None else int(litres, 16)
        return cls(cut, request_id, int(key, 16), kind, value, origin)

    @property
    def change(self) -> PointChange:
        return PointChange(self.kind, self.key, self.litres, self.origin)


class SourceStore:
    def __init__(self, db: sqlite3.Connection) -> None:
        self._db = db

    def close(self) -> None:
        self._db.close()

    def day_exists(self, day: StationDay) -> bool:
        return self._db.execute(
            'SELECT 1 FROM station_days WHERE station = ? AND day = ?', day.identity
        ).fetchone() is not None

    def ensure_day(self, day: StationDay) -> bool:
        with write_transaction(self._db):
            inserted = self._db.execute(
                'INSERT INTO station_days VALUES (?, ?) ON CONFLICT DO NOTHING', day.identity
            )
            return inserted.rowcount == 1

    def append_request(self, day: StationDay, request_id: str, change: PointChange) -> SourceRevision:
        with write_transaction(self._db):
            if not self.day_exists(day):
                raise ValueError('unknown station day')
            saved = self._db.execute(
                '''SELECT cut, request_id, key, kind, litres, origin FROM source_revisions
                   WHERE station = ? AND day = ? AND request_id = ?''',
                (*day.identity, request_id),
            ).fetchone()
            if saved is not None:
                revision = SourceRevision.from_record(saved)
                if revision.change != change:
                    raise ValueError('source request identity conflict')
                return revision

            key = hex(change.key)
            if change.kind != 'reading':
                latest = self._db.execute(
                    '''SELECT kind FROM source_revisions WHERE station = ? AND day = ? AND key = ?
                       ORDER BY cut DESC LIMIT 1''',
                    (*day.identity, key),
                ).fetchone()
                if latest is None:
                    raise ValueError('source key has never been recorded')
                if change.kind == 'withdrawal' and latest[0] == 'withdrawal':
                    raise ValueError('source key is already withdrawn')

            last_cut, = self._db.execute(
                'SELECT COALESCE(MAX(cut), 0) FROM source_revisions WHERE station = ? AND day = ?',
                day.identity,
            ).fetchone()
            if last_cut == _MAX_SQLITE_INTEGER:
                raise OverflowError('source commit counter exhausted')
            cut = last_cut + 1
            litres = None if change.litres is None else hex(change.litres)
            self._db.execute(
                '''INSERT INTO source_revisions (station, day, cut, request_id, key, kind, litres, origin)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (*day.identity, cut, request_id, key, change.kind, litres, change.origin),
            )
            return SourceRevision(cut, request_id, change.key, change.kind, change.litres, change.origin)

    def cut_exists(self, day: StationDay, cut: int) -> bool:
        if cut == 0:
            return self.day_exists(day)
        return self.revision_at(day, cut) is not None

    def revisions_through(self, day: StationDay, cut: int) -> Iterator[SourceRevision]:
        records = self._db.execute(
            '''SELECT cut, request_id, key, kind, litres, origin FROM source_revisions
               WHERE station = ? AND day = ? AND cut <= ? ORDER BY cut''',
            (*day.identity, cut),
        )
        for record in records:
            yield SourceRevision.from_record(record)

    def revisions_between(
        self, day: StationDay, start: int, end: int, lower: int, upper: int
    ) -> Iterator[SourceRevision]:
        """Yield original revisions ordered by commit number within (start, end] and [lower, upper)."""
        records = self._db.execute(
            '''SELECT cut, request_id, key, kind, litres, origin FROM source_revisions
               WHERE station = ? AND day = ? AND cut > ? AND cut <= ?
               ORDER BY cut''',
            (*day.identity, start, end),
        )
        for record in records:
            revision = SourceRevision.from_record(record)
            if lower <= revision.key < upper:
                yield revision

    def revision_at(self, day: StationDay, cut: int) -> SourceRevision | None:
        if not 0 < cut <= _MAX_SQLITE_INTEGER:
            return None
        record = self._db.execute(
            '''SELECT cut, request_id, key, kind, litres, origin FROM source_revisions
               WHERE station = ? AND day = ? AND cut = ?''',
            (*day.identity, cut),
        ).fetchone()
        return None if record is None else SourceRevision.from_record(record)


def open_source(path: str | PathLike[str]) -> SourceStore:
    db = sqlite3.connect(path, isolation_level=None)
    try:
        db.execute('PRAGMA foreign_keys = ON')
        db.executescript(_SCHEMA)
    except BaseException:
        db.close()
        raise
    return SourceStore(db)
