from __future__ import annotations

import sqlite3

from balance.coverage import latest_covering_stocktake, record_stocktake_evidence
from balance.history import record_history_evidence
from balance.revisions import latest_point_evidence, record_point_evidence, resolve_key_evidence
from balance.store import read_visible_rows, write_visible_key
from issue.artifact import FrozenArtifact, FrozenHistory


def post_artifact(db: sqlite3.Connection, artifact: FrozenArtifact | FrozenHistory) -> None:
    """Post a validated, newly receipted packet in the caller's write transaction."""
    if not db.in_transaction:
        raise ValueError('posting requires the receipt transaction')
    if isinstance(artifact, FrozenHistory):
        # History evidence never changes today's settlement.
        record_history_evidence(db, artifact)
        return
    day = artifact.station_day
    affected = {row.key for row in artifact.rows}
    if artifact.kind == 'stocktake':
        record_stocktake_evidence(db, artifact)
        affected.update(row.key for row in read_visible_rows(db, day, *artifact.bounds))
    else:
        record_point_evidence(db, artifact)

    for key in sorted(affected):
        point = latest_point_evidence(db, day, key)
        stocktake = latest_covering_stocktake(db, day, key)
        write_visible_key(db, day, key, resolve_key_evidence(point, stocktake))
