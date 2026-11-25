from __future__ import annotations

import sqlite3

from balance.store import KeyEvidence
from issue.artifact import FrozenArtifact
from source.day import StationDay


def record_point_evidence(db: sqlite3.Connection, artifact: FrozenArtifact) -> None:
    row, = artifact.rows
    litres = None if row.litres is None else hex(row.litres)
    db.execute(
        '''INSERT INTO point_evidence (artifact_id, station, day, cut, key, litres, origin)
           VALUES (?, ?, ?, ?, ?, ?, ?)''',
        (artifact.artifact_id, *artifact.station_day.identity, hex(artifact.cut), hex(row.key), litres, row.origin),
    )


def latest_point_evidence(db: sqlite3.Connection, day: StationDay, key: int) -> KeyEvidence | None:
    record = db.execute(
        '''SELECT cut, artifact_id, litres, origin FROM point_evidence
           WHERE station = ? AND day = ? AND key = ? ORDER BY cut DESC, artifact_id LIMIT 1''',
        (*day.identity, hex(key)),
    ).fetchone()
    return None if record is None else KeyEvidence.from_record(record)


def resolve_key_evidence(point: KeyEvidence | None, stocktake: KeyEvidence | None) -> KeyEvidence | None:
    candidates = (evidence for evidence in (point, stocktake) if evidence is not None)
    return min(candidates, key=lambda evidence: (-evidence.cut, evidence.artifact_id), default=None)
