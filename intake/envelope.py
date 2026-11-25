from __future__ import annotations

import json

from issue.artifact import FrozenArtifact, FrozenHistory, FrozenRow, HistoryChange, HistoryRow
from source.day import StationDay

_V1_ENVELOPE_FIELDS = {'version', 'kind', 'artifact_id', 'station', 'day', 'cut', 'bounds', 'rows'}
_ROW_FIELDS = {'key', 'litres', 'origin'}
_V2_ENVELOPE_FIELDS = {
    'version', 'kind', 'artifact_id', 'station', 'day', 'bounds', 'start', 'end', 'initial', 'changes',
}
_INITIAL_FIELDS = {'key', 'litres', 'cut', 'origin'}
_CHANGE_FIELDS = {'cut', 'key', 'kind', 'litres', 'origin'}


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    fields: dict[str, object] = {}
    for key, value in pairs:
        if key in fields:
            raise ValueError(f'duplicate JSON field: {key}')
        fields[key] = value
    return fields


def _invalid_constant(value: str) -> None:
    raise ValueError(f'invalid JSON number: {value}')


def _load(payload: bytes) -> dict[str, object]:
    if type(payload) is not bytes:
        raise ValueError('packet must be UTF-8 JSON bytes')
    document = json.loads(
        payload.decode('utf-8'), object_pairs_hook=_unique_fields, parse_constant=_invalid_constant
    )
    if not isinstance(document, dict):
        raise ValueError('invalid envelope fields')
    return document


def _decode_v1(document: dict[str, object]) -> FrozenArtifact:
    if document.keys() != _V1_ENVELOPE_FIELDS:
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


def _decode_v2(document: dict[str, object]) -> FrozenHistory:
    if document.keys() != _V2_ENVELOPE_FIELDS:
        raise ValueError('invalid history envelope fields')
    if document['kind'] != 'history':
        raise ValueError('history envelope requires kind history')
    bounds = document['bounds']
    if not isinstance(bounds, list) or len(bounds) != 2:
        raise ValueError('invalid history bounds')
    if not isinstance(document['initial'], list):
        raise ValueError('history initial must be an array')
    if not isinstance(document['changes'], list):
        raise ValueError('history changes must be an array')
    initial = []
    for row in document['initial']:
        if not isinstance(row, dict) or row.keys() != _INITIAL_FIELDS:
            raise ValueError('invalid history initial fields')
        initial.append(HistoryRow(**row))
    changes = []
    for change in document['changes']:
        if not isinstance(change, dict) or change.keys() != _CHANGE_FIELDS:
            raise ValueError('invalid history change fields')
        changes.append(HistoryChange(**change))
    return FrozenHistory(
        document['artifact_id'], StationDay(document['station'], document['day']),
        tuple(bounds), document['start'], document['end'], tuple(initial), tuple(changes),
    )


def decode_envelope(payload: bytes) -> FrozenArtifact | FrozenHistory:
    """Parse either wire version and preserve numeric types for business validation."""
    document = _load(payload)
    version = document.get('version')
    if type(version) is int and version == 2:
        return _decode_v2(document)
    return _decode_v1(document)
