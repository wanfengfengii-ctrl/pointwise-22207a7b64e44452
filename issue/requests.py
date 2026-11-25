from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from contextlib import closing

from issue.artifact import encode_artifact
from issue.changes import freeze_point_change
from issue.registry import IssueRegistry, open_issue_registry
from issue.reissue import reissue
from issue.stocktake import freeze_stocktake
from source.day import StationDay, require_cut, require_integer, require_interval, require_name
from source.store import SourceStore, open_source


def issue(
    source: SourceStore,
    registry: IssueRegistry,
    artifact_id: str,
    day: StationDay,
    cut: int,
    *,
    bounds: tuple[int, int] | None = None,
    key: int | None = None,
) -> bytes:
    require_name(artifact_id, 'artifact id')
    require_cut(cut)
    if (bounds is None) == (key is None):
        raise ValueError('provide exactly one of bounds and key')

    if bounds is not None:
        if not isinstance(bounds, (tuple, list)) or len(bounds) != 2:
            raise ValueError('stocktake bounds must contain two endpoints')
        interval = require_interval(*bounds)
        identity = ('stocktake', *day.identity, cut, *interval)
    else:
        point_key = require_integer(key, 'key')
        identity = ('point', *day.identity, cut, point_key)

    request = json.dumps(identity, separators=(',', ':'))
    saved = registry.lookup_request(artifact_id, request)
    if saved is not None:
        return saved
    if bounds is not None:
        artifact = freeze_stocktake(source, artifact_id, day, cut, *interval)
    else:
        artifact = freeze_point_change(source, artifact_id, day, cut, point_key)
    return registry.register_issue(artifact_id, request, encode_artifact(artifact))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Issue and resend frozen station-day packets')
    parser.add_argument('registry')
    commands = parser.add_subparsers(dest='command', required=True)
    stocktake = commands.add_parser('stocktake')
    point = commands.add_parser('point')
    for command in (stocktake, point):
        command.add_argument('source')
        command.add_argument('station')
        command.add_argument('day')
        command.add_argument('artifact_id')
        command.add_argument('cut', type=int)
    stocktake.add_argument('lower', type=int)
    stocktake.add_argument('upper', type=int)
    point.add_argument('key', type=int)
    resend = commands.add_parser('reissue')
    resend.add_argument('artifact_id')
    args = parser.parse_args(argv)

    try:
        with closing(open_issue_registry(args.registry)) as registry:
            if args.command == 'reissue':
                payload = reissue(registry, args.artifact_id)
                if payload is None:
                    raise ValueError('unknown artifact id')
            else:
                day = StationDay(args.station, args.day)
                selection = {'key': args.key} if args.command == 'point' else {
                    'bounds': (args.lower, args.upper)
                }
                with closing(open_source(args.source)) as source:
                    payload = issue(source, registry, args.artifact_id, day, args.cut, **selection)
        sys.stdout.buffer.write(payload + b'\n')
    except (ValueError, OSError, sqlite3.Error) as error:
        parser.exit(1, f'{error}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
