from __future__ import annotations

from source.day import StationDay, require_cut, require_integer, require_interval
from source.store import SourceRevision, SourceStore


def source_at(
    store: SourceStore, day: StationDay, cut: int, lower: int, upper: int
) -> tuple[SourceRevision, ...]:
    require_cut(cut)
    require_interval(lower, upper)
    if not store.cut_exists(day, cut):
        raise ValueError('unknown station day or source cut')
    latest: dict[int, SourceRevision] = {}
    for revision in store.revisions_through(day, cut):
        if lower <= revision.key < upper:
            latest[revision.key] = revision
    return tuple(latest[key] for key in sorted(latest) if latest[key].litres is not None)


def source_change_at(store: SourceStore, day: StationDay, cut: int, key: int) -> SourceRevision:
    require_cut(cut)
    require_integer(key, 'key')
    revision = store.revision_at(day, cut)
    if revision is None or revision.key != key:
        raise ValueError('no source revision for that cut and key')
    return revision
