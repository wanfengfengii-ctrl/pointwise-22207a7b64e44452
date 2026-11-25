from __future__ import annotations

from dataclasses import dataclass
from os import PathLike

from balance.store import VisibleRow
from balance.view import ReadView, open_read_view
from reports.totals import sum_litres
from source.day import StationDay


@dataclass(frozen=True)
class Daybook:
    station_day: StationDay
    bounds: tuple[int, int]
    rows: tuple[VisibleRow, ...]
    total_litres: int


def build_daybook(view: ReadView, day: StationDay, lower: int, upper: int) -> Daybook:
    rows = view.rows(day, lower, upper)
    return Daybook(day, (lower, upper), rows, sum_litres(rows))


def daybook(path: str | PathLike[str], day: StationDay, lower: int, upper: int) -> Daybook:
    with open_read_view(path) as view:
        return build_daybook(view, day, lower, upper)
