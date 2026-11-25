from __future__ import annotations

from issue.artifact import FrozenArtifact, FrozenRow
from source.day import StationDay, require_name
from source.history import source_at
from source.store import SourceStore


def freeze_stocktake(
    source: SourceStore, artifact_id: str, day: StationDay, cut: int, lower: int, upper: int
) -> FrozenArtifact:
    require_name(artifact_id, 'artifact id')
    history = source_at(source, day, cut, lower, upper)
    rows = tuple(FrozenRow(row.key, row.litres, row.origin) for row in history)
    return FrozenArtifact(artifact_id, day, 'stocktake', cut, rows, (lower, upper))
