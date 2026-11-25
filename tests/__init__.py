import json

from source.day import StationDay

DAY = StationDay('HP', '2026-11-25')


def packet(name, kind, cut, rows, *, bounds=None, day=DAY):
    """Build independent wire fixtures without calling the publisher or packet codec."""
    return json.dumps({
        'version': 1,
        'kind': kind,
        'artifact_id': name,
        'station': day.station,
        'day': day.day,
        'cut': cut,
        'bounds': bounds,
        'rows': [{'key': key, 'litres': litres, 'origin': origin} for key, litres, origin in rows],
    }).encode('utf-8')


def history_packet(name, bounds, start, end, initial, changes, *, day=DAY):
    """Build independent version 2 wire fixtures: initial rows carry their true cut."""
    return json.dumps({
        'version': 2,
        'kind': 'history',
        'artifact_id': name,
        'station': day.station,
        'day': day.day,
        'bounds': list(bounds),
        'start': start,
        'end': end,
        'initial': [
            {'key': key, 'litres': litres, 'cut': cut, 'origin': origin}
            for key, litres, cut, origin in initial
        ],
        'changes': [
            {'cut': cut, 'key': key, 'kind': kind, 'litres': litres, 'origin': origin}
            for cut, key, kind, litres, origin in changes
        ],
    }).encode('utf-8')
