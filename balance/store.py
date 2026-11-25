from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from os import PathLike
from pathlib import Path

from intake.receipts import initialize_receipts
from source.day import StationDay, require_interval

_SCHEMA = '''
CREATE TABLE IF NOT EXISTS stocktake_evidence (
    artifact_id TEXT PRIMARY KEY REFERENCES receipts (artifact_id),
    station TEXT NOT NULL,
    day TEXT NOT NULL,
    cut TEXT COLLATE ledger_integer NOT NULL,
    lower_key TEXT COLLATE ledger_integer NOT NULL,
    upper_key TEXT COLLATE ledger_integer NOT NULL
);
CREATE INDEX IF NOT EXISTS stocktake_day_cut
    ON stocktake_evidence (station, day, cut DESC, artifact_id);
CREATE TABLE IF NOT EXISTS stocktake_rows (
    artifact_id TEXT NOT NULL REFERENCES stocktake_evidence (artifact_id),
    key TEXT NOT NULL,
    litres TEXT NOT NULL,
    origin TEXT NOT NULL,
    PRIMARY KEY (artifact_id, key)
);
CREATE TABLE IF NOT EXISTS point_evidence (
    artifact_id TEXT PRIMARY KEY REFERENCES receipts (artifact_id),
    station TEXT NOT NULL,
    day TEXT NOT NULL,
    cut TEXT COLLATE ledger_integer NOT NULL,
    key TEXT NOT NULL,
    litres TEXT,
    origin TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS point_day_key_cut
    ON point_evidence (station, day, key, cut DESC, artifact_id);
CREATE TABLE IF NOT EXISTS visible_rows (
    station TEXT NOT NULL,
    day TEXT NOT NULL,
    key TEXT COLLATE ledger_integer NOT NULL,
    litres TEXT NOT NULL,
    cut TEXT NOT NULL,
    origin TEXT NOT NULL,
    artifact_id TEXT NOT NULL REFERENCES receipts (artifact_id),
    PRIMARY KEY (station, day, key)
);
CREATE TABLE IF NOT EXISTS history_evidence (
    artifact_id TEXT PRIMARY KEY REFERENCES receipts (artifact_id),
    station TEXT NOT NULL,
    day TEXT NOT NULL,
    lower_key TEXT COLLATE ledger_integer NOT NULL,
    upper_key TEXT COLLATE ledger_integer NOT NULL,
    start_cut TEXT COLLATE ledger_integer NOT NULL,
    end_cut TEXT COLLATE ledger_integer NOT NULL
);
CREATE INDEX IF NOT EXISTS history_day_window
    ON history_evidence (station, day, start_cut, end_cut);
CREATE TABLE IF NOT EXISTS history_initial (
    artifact_id TEXT NOT NULL REFERENCES history_evidence (artifact_id),
    key TEXT COLLATE ledger_integer NOT NULL,
    litres TEXT NOT NULL,
    cut TEXT COLLATE ledger_integer NOT NULL,
    origin TEXT NOT NULL,
    PRIMARY KEY (artifact_id, key)
);
CREATE TABLE IF NOT EXISTS history_changes (
    artifact_id TEXT NOT NULL REFERENCES history_evidence (artifact_id),
    cut TEXT COLLATE ledger_integer NOT NULL,
    key TEXT COLLATE ledger_integer NOT NULL,
    kind TEXT NOT NULL,
    litres TEXT,
    origin TEXT NOT NULL,
    PRIMARY KEY (artifact_id, cut)
);
'''


@dataclass(frozen=True)
class KeyEvidence:
    cut: int
    artifact_id: str
    litres: int | None
    origin: str | None

    @classmethod
    def from_record(cls, record: tuple) -> KeyEvidence:
        cut, artifact_id, litres, origin = record
        return cls(int(cut, 16), artifact_id, None if litres is None else int(litres, 16), origin)


@dataclass(frozen=True)
class VisibleRow:
    key: int
    litres: int
    cut: int
    origin: str
    artifact_id: str


def _integer_order(left: str, right: str) -> int:
    first, second = int(left, 16), int(right, 16)
    return (first > second) - (first < second)


def connect_report_database(path: str | PathLike[str], *, read_only: bool = False) -> sqlite3.Connection:
    # Canonical hex preserves Python integer values across SQLite's machine-word boundary.
    target = Path(path).resolve().as_uri() + '?mode=ro' if read_only else path
    db = sqlite3.connect(target, uri=read_only, isolation_level=None)
    try:
        db.create_collation('ledger_integer', _integer_order)
        db.execute('PRAGMA foreign_keys = ON')
    except BaseException:
        db.close()
        raise
    return db


def initialize_balance_schema(db: sqlite3.Connection) -> None:
    if db.in_transaction:
        raise ValueError('initialize the balance schema outside a transaction')
    initialize_receipts(db)
    db.executescript(_SCHEMA)


def open_report_database(path: str | PathLike[str]) -> sqlite3.Connection:
    db = connect_report_database(path)
    try:
        mode, = db.execute('PRAGMA journal_mode = WAL').fetchone()
        if mode != 'wal':
            raise sqlite3.OperationalError('the report database requires WAL mode')
        initialize_balance_schema(db)
    except BaseException:
        db.close()
        raise
    return db


def read_visible_rows(
    db: sqlite3.Connection, day: StationDay, lower: int, upper: int
) -> tuple[VisibleRow, ...]:
    require_interval(lower, upper)
    records = db.execute(
        '''SELECT key, litres, cut, origin, artifact_id FROM visible_rows
           WHERE station = ? AND day = ? AND key >= ? AND key < ? ORDER BY key''',
        (*day.identity, hex(lower), hex(upper)),
    )
    return tuple(
        VisibleRow(int(key, 16), int(litres, 16), int(cut, 16), origin, artifact_id)
        for key, litres, cut, origin, artifact_id in records
    )


def write_visible_key(
    db: sqlite3.Connection, day: StationDay, key: int, evidence: KeyEvidence | None
) -> None:
    identity = (*day.identity, hex(key))
    if evidence is None or evidence.litres is None:
        db.execute('DELETE FROM visible_rows WHERE station = ? AND day = ? AND key = ?', identity)
        return
    db.execute(
        '''INSERT INTO visible_rows (station, day, key, litres, cut, origin, artifact_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT (station, day, key) DO UPDATE SET
               litres = excluded.litres, cut = excluded.cut,
               origin = excluded.origin, artifact_id = excluded.artifact_id''',
        (*identity, hex(evidence.litres), hex(evidence.cut), evidence.origin, evidence.artifact_id),
    )
