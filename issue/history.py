from __future__ import annotations

import json

from issue.artifact import FrozenHistory, HistoryChange, HistoryRow, encode_history
from issue.registry import IssueRegistry
from source.day import StationDay, require_cut, require_interval, require_name
from source.history import source_changes, source_window
from source.store import SourceStore


def freeze_history(
    source: SourceStore,
    artifact_id: str,
    day: StationDay,
    bounds: tuple[int, int],
    start: int,
    end: int,
) -> FrozenHistory:
    """Freeze the initial register at ``start`` plus every revision in ``(start, end]``."""
    require_name(artifact_id, 'artifact id')
    lower, upper = require_interval(*bounds)
    require_cut(start)
    require_cut(end)
    if start >= end:
        raise ValueError('history window must have start before end')
    initial = tuple(
        HistoryRow(revision.key, revision.litres, revision.cut, revision.origin)
        for revision in source_window(source, day, start, lower, upper)
    )
    changes = tuple(
        HistoryChange(revision.cut, revision.key, revision.kind, revision.litres, revision.origin)
        for revision in source_changes(source, day, start, end, lower, upper)
    )
    return FrozenHistory(artifact_id, day, (lower, upper), start, end, initial, changes)


def issue_history(
    source: SourceStore,
    registry: IssueRegistry,
    artifact_id: str,
    day: StationDay,
    bounds: tuple[int, int],
    start: int,
    end: int,
) -> bytes:
    """Issue a frozen version 2 history tile, reissuing identical requests byte-for-byte."""
    require_name(artifact_id, 'artifact id')
    if not isinstance(bounds, (tuple, list)) or len(bounds) != 2:
        raise ValueError('history bounds must contain two endpoints')
    lower, upper = require_interval(bounds[0], bounds[1])
    require_cut(start)
    require_cut(end)
    if start >= end:
        raise ValueError('history window must have start before end')
    request = json.dumps(
        ['history', *day.identity, hex(lower), hex(upper), hex(start), hex(end)],
        separators=(',', ':'),
    )
    saved = registry.lookup_request(artifact_id, request)
    if saved is not None:
        return saved
    artifact = freeze_history(source, artifact_id, day, (lower, upper), start, end)
    return registry.register_issue(artifact_id, request, encode_history(artifact))
