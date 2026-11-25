from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import closing
from dataclasses import asdict

from source.correct import PointChange, make_correction, make_withdrawal
from source.day import StationDay, initialize_day, require_name
from source.history import source_at
from source.store import SourceRevision, SourceStore, open_source


def apply(store: SourceStore, day: StationDay, request_id: str, change: PointChange) -> SourceRevision:
    require_name(request_id, 'source request id')
    if not isinstance(change, PointChange):
        raise ValueError('change must be a PointChange')
    return store.append_request(day, request_id, change)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Maintain and read the station-day source ledger')
    parser.add_argument('database')
    parser.add_argument('station')
    parser.add_argument('day')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('init')
    write = commands.add_parser('apply')
    write.add_argument('request_id')
    write.add_argument('kind', choices=('reading', 'correction', 'withdrawal'))
    write.add_argument('key', type=int)
    write.add_argument('origin')
    write.add_argument('litres', type=int, nargs='?')
    history = commands.add_parser('at')
    history.add_argument('cut', type=int)
    history.add_argument('lower', type=int)
    history.add_argument('upper', type=int)
    args = parser.parse_args(argv)

    try:
        day = StationDay(args.station, args.day)
        with closing(open_source(args.database)) as store:
            if args.command == 'init':
                result = {'created': initialize_day(store, day), **asdict(day)}
            elif args.command == 'at':
                rows = source_at(store, day, args.cut, args.lower, args.upper)
                result = {'cut': args.cut, 'rows': [asdict(row) for row in rows]}
            else:
                if args.kind == 'correction':
                    change = make_correction(args.key, args.litres, args.origin)
                elif args.kind == 'withdrawal' and args.litres is None:
                    change = make_withdrawal(args.key, args.origin)
                else:
                    change = PointChange(args.kind, args.key, args.litres, args.origin)
                result = asdict(apply(store, day, args.request_id, change))
        print(json.dumps(result, ensure_ascii=False))
    except (ValueError, OSError, sqlite3.Error, OverflowError) as error:
        parser.exit(1, f'{error}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
