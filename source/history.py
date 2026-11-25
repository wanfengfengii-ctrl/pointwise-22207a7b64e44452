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


def source_window(
    store: SourceStore, day: StationDay, start: int, lower: int, upper: int
) -> tuple[SourceRevision, ...]:
    """Return the keys in register at ``start`` with the cut of their true original revision."""
    require_cut(start)
    require_interval(lower, upper)
    if not store.cut_exists(day, start):
        raise ValueError('unknown station day or source cut')
    latest: dict[int, SourceRevision] = {}
    for revision in store.revisions_through(day, start):
        if lower <= revision.key < upper:
            latest[revision.key] = revision
    return tuple(latest[key] for key in sorted(latest) if latest[key].litres is not None)


def source_changes(
    store: SourceStore, day: StationDay, start: int, end: int, lower: int, upper: int
) -> tuple[SourceRevision, ...]:
    """Return every original revision committed in (start, end] for keys in [lower, upper)."""
    require_cut(start)
    require_cut(end)
    require_interval(lower, upper)
    if start >= end:
        raise ValueError('start must precede end')
    if not store.cut_exists(day, start) or not store.cut_exists(day, end):
        raise ValueError('unknown station day or source cut')
    return tuple(store.revisions_between(day, start, end, lower, upper))
