from __future__ import annotations

import sqlite3

from balance.store import KeyEvidence
from issue.artifact import FrozenArtifact
from source.day import StationDay


def record_stocktake_evidence(db: sqlite3.Connection, artifact: FrozenArtifact) -> None:
    lower, upper = artifact.bounds
    db.execute(
        '''INSERT INTO stocktake_evidence (artifact_id, station, day, cut, lower_key, upper_key)
           VALUES (?, ?, ?, ?, ?, ?)''',
        (artifact.artifact_id, *artifact.station_day.identity, hex(artifact.cut), hex(lower), hex(upper)),
    )
    db.executemany(
        'INSERT INTO stocktake_rows (artifact_id, key, litres, origin) VALUES (?, ?, ?, ?)',
        ((artifact.artifact_id, hex(row.key), hex(row.litres), row.origin) for row in artifact.rows),
    )


def latest_covering_stocktake(db: sqlite3.Connection, day: StationDay, key: int) -> KeyEvidence | None:
    # LEFT JOIN retains the winning coverage when that stocktake has no row for the key.
    stored_key = hex(key)
    record = db.execute(
        '''SELECT cover.cut, cover.artifact_id, body.litres, body.origin
           FROM stocktake_evidence AS cover
           LEFT JOIN stocktake_rows AS body ON body.artifact_id = cover.artifact_id AND body.key = ?
           WHERE cover.station = ? AND cover.day = ? AND cover.lower_key <= ? AND cover.upper_key > ?
           ORDER BY cover.cut DESC, cover.artifact_id LIMIT 1''',
        (stored_key, *day.identity, stored_key, stored_key),
    ).fetchone()
    return None if record is None else KeyEvidence.from_record(record)
