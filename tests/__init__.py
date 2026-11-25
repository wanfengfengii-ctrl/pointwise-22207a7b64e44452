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
