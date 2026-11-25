from __future__ import annotations

from typing import Iterable, Protocol


class MeasuredRow(Protocol):
    @property
    def litres(self) -> int:
        ...


def sum_litres(rows: Iterable[MeasuredRow]) -> int:
    """Sum the exact integer litres from the rows used for the report."""
    return sum(row.litres for row in rows)
