from __future__ import annotations

from issue.artifact import FrozenArtifact
from source.day import require_cut, require_integer, require_interval, require_name


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


def validate_artifact(artifact: FrozenArtifact) -> None:
    require_name(artifact.artifact_id, 'artifact id')
    require_cut(artifact.cut)
    if artifact.kind == 'stocktake':
        validate_stocktake(artifact)
    elif artifact.kind == 'point':
        validate_point_change(artifact)
    else:
        raise ValueError('unknown artifact kind')
