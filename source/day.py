from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from source.store import SourceStore


def require_name(value: object, label: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f'{label} must be a nonblank string')
    value.encode('utf-8')
    return value


def require_integer(value: object, label: str) -> int:
    if type(value) is not int:
        raise ValueError(f'{label} must be an integer')
    return value


def require_interval(lower: int, upper: int) -> tuple[int, int]:
    require_integer(lower, 'lower bound')
    require_integer(upper, 'upper bound')
    if lower > upper:
        raise ValueError('lower bound exceeds upper bound')
    return lower, upper


def require_cut(cut: int) -> int:
    require_integer(cut, 'source cut')
    if cut < 0:
        raise ValueError('source cut must be nonnegative')
    return cut


@dataclass(frozen=True)
class StationDay:
    station: str
    day: str

    def __post_init__(self) -> None:
        require_name(self.station, 'station')
        require_name(self.day, 'day')

    @property
    def identity(self) -> tuple[str, str]:
        return self.station, self.day


def initialize_day(store: SourceStore, day: StationDay) -> bool:
    """Open a day and report whether its identity was newly registered."""
    return store.ensure_day(day)
