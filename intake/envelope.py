from __future__ import annotations

import json

from issue.artifact import FrozenArtifact, FrozenRow
from source.day import StationDay

_ENVELOPE_FIELDS = {'version', 'kind', 'artifact_id', 'station', 'day', 'cut', 'bounds', 'rows'}
_ROW_FIELDS = {'key', 'litres', 'origin'}


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    fields: dict[str, object] = {}
    for key, value in pairs:
        if key in fields:
            raise ValueError(f'duplicate JSON field: {key}')
        fields[key] = value
    return fields


def _invalid_constant(value: str) -> None:
    raise ValueError(f'invalid JSON number: {value}')


def decode_envelope(payload: bytes) -> FrozenArtifact:
    """Parse the wire shape and preserve numeric types for business validation."""
    if type(payload) is not bytes:
        raise ValueError('packet must be UTF-8 JSON bytes')
    document = json.loads(
        payload.decode('utf-8'), object_pairs_hook=_unique_fields, parse_constant=_invalid_constant
    )
    if not isinstance(document, dict) or document.keys() != _ENVELOPE_FIELDS:
        raise ValueError('invalid envelope fields')
    if type(document['version']) is not int or document['version'] != 1:
        raise ValueError('unsupported envelope version')
    if not isinstance(document['rows'], list):
        raise ValueError('packet rows must be an array')
    rows = []
    for row in document['rows']:
        if not isinstance(row, dict) or row.keys() != _ROW_FIELDS:
            raise ValueError('invalid row fields')
        rows.append(FrozenRow(**row))
    bounds = document['bounds']
    if bounds is not None:
        if not isinstance(bounds, list) or len(bounds) != 2:
            raise ValueError('invalid envelope bounds')
        bounds = tuple(bounds)
    return FrozenArtifact(
        document['artifact_id'], StationDay(document['station'], document['day']),
        document['kind'], document['cut'], tuple(rows), bounds,
    )
