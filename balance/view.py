from __future__ import annotations

import sqlite3
from contextlib import closing, contextmanager
from dataclasses import dataclass
from os import PathLike
from typing import Iterator

from balance.store import VisibleRow, connect_report_database, read_visible_rows
from source.day import StationDay, require_integer


@dataclass(frozen=True)
class ReadView:
    _db: sqlite3.Connection

    @property
    def database(self) -> sqlite3.Connection:
        return self._db

    def rows(self, day: StationDay, lower: int, upper: int) -> tuple[VisibleRow, ...]:
        return read_visible_rows(self._db, day, lower, upper)

    def lookup_key(self, day: StationDay, key: int) -> VisibleRow | None:
        require_integer(key, 'key')
        rows = self.rows(day, key, key + 1)
        return rows[0] if rows else None


@contextmanager
def open_read_view(path: str | PathLike[str]) -> Iterator[ReadView]:
    with closing(connect_report_database(path, read_only=True)) as db:
        db.execute('BEGIN')
        try:
            # A deferred transaction fixes its WAL read snapshot on the first table read.
            db.execute('SELECT 1 FROM visible_rows LIMIT 1').fetchone()
            yield ReadView(db)
        finally:
            db.execute('ROLLBACK')
