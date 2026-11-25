from __future__ import annotations

from issue.artifact import FrozenArtifact, FrozenHistory
from source.day import require_cut, require_integer, require_interval, require_name

_CHANGE_KINDS = {'reading', 'correction', 'withdrawal'}


def validate_stocktake(artifact: FrozenArtifact) -> None:
    if artifact.bounds is None or len(artifact.bounds) != 2:
        raise ValueError('stocktake requires bounds')
    lower, upper = require_interval(*artifact.bounds)
    previous = None
    for row in artifact.rows:
        key = require_integer(row.key, 'key')
        require_integer(row.litres, 'litres')
        require_name(row.origin, 'origin')
        if not lower <= key < upper:
            raise ValueError('stocktake row outside bounds')
        if previous is not None and key <= previous:
            raise ValueError('stocktake rows must have increasing distinct keys')
        previous = key


def validate_point_change(artifact: FrozenArtifact) -> None:
    if artifact.bounds is not None or len(artifact.rows) != 1 or artifact.cut <= 0:
        raise ValueError('point requires one row, a positive source cut and null bounds')
    row, = artifact.rows
    require_integer(row.key, 'key')
    require_name(row.origin, 'origin')
    if row.litres is not None:
        require_integer(row.litres, 'litres')


def validate_history(artifact: FrozenHistory) -> None:
    require_name(artifact.artifact_id, 'artifact id')
    if artifact.bounds is None or len(artifact.bounds) != 2:
        raise ValueError('history requires bounds')
    lower, upper = require_interval(*artifact.bounds)
    start = require_cut(artifact.start)
    end = require_cut(artifact.end)
    if start >= end:
        raise ValueError('history must have start before end')

    previous = None
    for row in artifact.initial:
        key = require_integer(row.key, 'key')
        require_integer(row.litres, 'litres')
        cut = require_cut(row.cut)
        require_name(row.origin, 'origin')
        if not lower <= key < upper:
            raise ValueError('history initial row outside bounds')
        if not 0 < cut <= start:
            raise ValueError('history initial cut must lie within the opened day and start')
        if previous is not None and key <= previous:
            raise ValueError('history initial rows must have increasing distinct keys')
        previous = key

    previous_cut = None
    for change in artifact.changes:
        cut = require_cut(change.cut)
        key = require_integer(change.key, 'key')
        require_name(change.origin, 'origin')
        if not start < cut <= end:
            raise ValueError('history change cut must lie within the window')
        if not lower <= key < upper:
            raise ValueError('history change key outside bounds')
        if change.kind not in _CHANGE_KINDS:
            raise ValueError('unknown history change kind')
        if change.kind == 'withdrawal':
            if change.litres is not None:
                raise ValueError('a history withdrawal cannot carry litres')
        else:
            require_integer(change.litres, 'litres')
        if previous_cut is not None and cut <= previous_cut:
            raise ValueError('history changes must have increasing distinct cuts')
        previous_cut = cut


def validate_artifact(artifact: FrozenArtifact | FrozenHistory) -> None:
    if isinstance(artifact, FrozenHistory):
        validate_history(artifact)
        return
    require_name(artifact.artifact_id, 'artifact id')
    require_cut(artifact.cut)
    if artifact.kind == 'stocktake':
        validate_stocktake(artifact)
    elif artifact.kind == 'point':
        validate_point_change(artifact)
    else:
        raise ValueError('unknown artifact kind')
