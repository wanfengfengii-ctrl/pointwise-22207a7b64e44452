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


@dataclass(frozen=True)
class HistoryRow:
    """A registered key at the tile's starting cut, with its true source revision."""

    key: int
    litres: int
    cut: int
    origin: str


@dataclass(frozen=True)
class HistoryChange:
    """One original source revision inside the tile's (start, end] window."""

    cut: int
    key: int
    kind: str
    litres: int | None
    origin: str


@dataclass(frozen=True)
class FrozenHistory:
    """A version 2 tile: a key interval crossed with a source commit window."""

    artifact_id: str
    station_day: StationDay
    bounds: tuple[int, int]
    start: int
    end: int
    initial: tuple[HistoryRow, ...]
    changes: tuple[HistoryChange, ...]


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


def encode_history(artifact: FrozenHistory) -> bytes:
    """Encode a version 2 history tile canonically so whitespace and key order never matter."""
    document = {
        'version': 2,
        'kind': 'history',
        'artifact_id': artifact.artifact_id,
        **asdict(artifact.station_day),
        'bounds': list(artifact.bounds),
        'start': artifact.start,
        'end': artifact.end,
        'initial': [asdict(row) for row in artifact.initial],
        'changes': [asdict(change) for change in artifact.changes],
    }
    return json.dumps(document, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def encode_packet(artifact: FrozenArtifact | FrozenHistory) -> bytes:
    """Encode either wire version through its canonical form."""
    if isinstance(artifact, FrozenHistory):
        return encode_history(artifact)
    return encode_artifact(artifact)
