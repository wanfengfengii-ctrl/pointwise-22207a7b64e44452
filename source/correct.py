from __future__ import annotations

from dataclasses import dataclass

from source.day import require_integer, require_name


@dataclass(frozen=True)
class PointChange:
    kind: str
    key: int
    litres: int | None
    origin: str

    def __post_init__(self) -> None:
        require_integer(self.key, 'key')
        require_name(self.origin, 'origin')
        if self.kind == 'withdrawal':
            if self.litres is not None:
                raise ValueError('a withdrawal cannot carry litres')
        elif self.kind in ('reading', 'correction'):
            require_integer(self.litres, 'litres')
        else:
            raise ValueError('unknown source change kind')


def make_correction(key: int, litres: int, origin: str) -> PointChange:
    """Replace a reading or restore a key after its withdrawal."""
    return PointChange('correction', key, litres, origin)


def make_withdrawal(key: int, origin: str) -> PointChange:
    return PointChange('withdrawal', key, None, origin)
