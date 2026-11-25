from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from source.day import StationDay


@dataclass(frozen=True)
class FrozenRow:
    key: int
    litres: int | None
    origin: str


@dataclass(frozen=True)
class FrozenArtifact:
    artifact_id: str
    station_day: StationDay
    kind: str
    cut: int
    rows: tuple[FrozenRow, ...]
    bounds: tuple[int, int] | None = None


def encode_artifact(artifact: FrozenArtifact) -> bytes:
    """Encode the version 1 envelope with a stable representation for storage."""
    document = {
        'version': 1,
        'kind': artifact.kind,
        'artifact_id': artifact.artifact_id,
        **asdict(artifact.station_day),
        'cut': artifact.cut,
        'bounds': artifact.bounds,
        'rows': [asdict(row) for row in artifact.rows],
    }
    return json.dumps(document, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
