from __future__ import annotations

from issue.artifact import FrozenArtifact, FrozenRow
from source.day import StationDay, require_name
from source.history import source_change_at
from source.store import SourceStore


def freeze_point_change(
    source: SourceStore, artifact_id: str, day: StationDay, cut: int, key: int
) -> FrozenArtifact:
    require_name(artifact_id, 'artifact id')
    revision = source_change_at(source, day, cut, key)
    row = FrozenRow(revision.key, revision.litres, revision.origin)
    return FrozenArtifact(artifact_id, day, 'point', revision.cut, (row,))
