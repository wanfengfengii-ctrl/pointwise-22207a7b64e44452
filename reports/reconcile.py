from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import asdict, dataclass
from os import PathLike
from typing import Callable

from balance.view import open_read_view
from reports.daybook import Daybook, build_daybook
from reports.provenance import Provenance, trace_in_view
from source.day import StationDay


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Reconcile an offline station-day report')
    parser.add_argument('database')
    parser.add_argument('station')
    parser.add_argument('day')
    parser.add_argument('lower', type=int)
    parser.add_argument('upper', type=int)
    args = parser.parse_args(argv)
    try:
        result = reconcile_range(args.database, StationDay(args.station, args.day), args.lower, args.upper)
        print(json.dumps(asdict(result), ensure_ascii=False))
    except (ValueError, OSError, sqlite3.Error) as error:
        parser.exit(1, f'{error}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
