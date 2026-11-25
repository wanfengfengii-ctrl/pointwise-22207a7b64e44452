from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from issue.artifact import FrozenArtifact, FrozenHistory, encode_packet


@dataclass(frozen=True)
class Receipt:
    number: int
    artifact_id: str
    payload: bytes = field(repr=False)


def initialize_receipts(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS receipts (
            number INTEGER PRIMARY KEY,
            artifact_id TEXT NOT NULL UNIQUE,
            payload BLOB NOT NULL
        )
    ''')


def lookup_receipt(db: sqlite3.Connection, artifact_id: str) -> Receipt | None:
    record = db.execute(
        'SELECT number, artifact_id, payload FROM receipts WHERE artifact_id = ?', (artifact_id,)
    ).fetchone()
    return None if record is None else Receipt(*record)


def same_artifact(receipt: Receipt, artifact: FrozenArtifact | FrozenHistory) -> bool:
    return receipt.payload == encode_packet(artifact)


def insert_receipt(db: sqlite3.Connection, artifact: FrozenArtifact | FrozenHistory) -> Receipt:
    payload = encode_packet(artifact)
    cursor = db.execute(
        'INSERT INTO receipts (artifact_id, payload) VALUES (?, ?)', (artifact.artifact_id, payload)
    )
    return Receipt(cursor.lastrowid, artifact.artifact_id, payload)
