from __future__ import annotations

from dataclasses import dataclass
from os import PathLike

from balance.view import ReadView, open_read_view
from source.day import StationDay


@dataclass(frozen=True)
class Provenance:
    key: int
    cut: int
    origin: str
    artifact_id: str


def trace_in_view(view: ReadView, day: StationDay, key: int) -> Provenance | None:
    row = view.lookup_key(day, key)
    if row is None:
        return None
    return Provenance(row.key, row.cut, row.origin, row.artifact_id)


def trace(path: str | PathLike[str], day: StationDay, key: int) -> Provenance | None:
    with open_read_view(path) as view:
        return trace_in_view(view, day, key)
