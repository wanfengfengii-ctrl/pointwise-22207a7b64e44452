from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import asdict, dataclass
from os import PathLike
from typing import Callable

from balance.history import collect_history
from balance.view import open_read_view
from reports.daybook import Daybook, build_daybook
from reports.provenance import Provenance, trace_in_view
from source.day import StationDay, require_cut, require_interval


@dataclass(frozen=True)
class Reconciliation:
    book: Daybook
    traces: tuple[Provenance, ...]


def reconcile_range(
    path: str | PathLike[str], day: StationDay, lower: int, upper: int,
    *, after_daybook: Callable[[Daybook], None] | None = None,
) -> Reconciliation:
    with open_read_view(path) as view:
        book = build_daybook(view, day, lower, upper)
        if after_daybook is not None:
            after_daybook(book)
        traces = []
        for row in book.rows:
            item = trace_in_view(view, day, row.key)
            if item is None:
                raise RuntimeError('visible row lost its provenance within the report snapshot')
            traces.append(item)
        return Reconciliation(book, tuple(traces))


def review_history(
    path: str | PathLike[str], day: StationDay, bounds: tuple[int, int], start: int, end: int
) -> dict[str, list] | str:
    """Read the merged history from one fixed report snapshot, or PENDING when tiles are missing."""
    if not isinstance(bounds, (tuple, list)) or len(bounds) != 2:
        raise ValueError('history bounds must contain two endpoints')
    lower, upper = require_interval(bounds[0], bounds[1])
    require_cut(start)
    require_cut(end)
    if start >= end:
        raise ValueError('history window must have start before end')
    with open_read_view(path) as view:
        return collect_history(view.database, day, (lower, upper), start, end)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Reconcile an offline station-day report')
    parser.add_argument('database')
    parser.add_argument('station')
    parser.add_argument('day')
    parser.add_argument('lower', type=int)
    parser.add_argument('upper', type=int)
    parser.add_argument('--history', nargs=2, type=int, metavar=('START', 'END'))
    args = parser.parse_args(argv)
    try:
        day = StationDay(args.station, args.day)
        if args.history is not None:
            start, end = args.history
            result = review_history(args.database, day, (args.lower, args.upper), start, end)
        else:
            result = asdict(reconcile_range(args.database, day, args.lower, args.upper))
        print(json.dumps(result, ensure_ascii=False))
    except (ValueError, OSError, sqlite3.Error) as error:
        parser.exit(1, f'{error}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
