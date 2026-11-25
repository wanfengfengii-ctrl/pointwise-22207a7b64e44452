from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from issue.artifact import FrozenHistory
from source.day import StationDay

# Each history tile proves two rectangles over the (key, cut) plane:
#   * starting facts at its start cut, valid for every cut in [start, end];
#   * revisions in (start, end], valid for the key interval of the tile.
# A tile may cross a query boundary; completeness is judged per tile declaration.


@dataclass(frozen=True)
class Tile:
    artifact_id: str
    lower: int
    upper: int
    start: int
    end: int
    # key, litres, true original cut, origin -- sorted by key
    initial: tuple[tuple[int, int, int, str], ...]
    # cut, key, kind, litres, origin -- sorted by cut
    changes: tuple[tuple[int, int, str, int | None, str], ...]

    def initial_map(self) -> dict[int, tuple[int, int, str]]:
        return {key: (litres, cut, origin) for key, litres, cut, origin in self.initial}

    def changes_map(self) -> dict[int, tuple[int, int, str, int | None, str]]:
        return {change[0]: change for change in self.changes}

    def state_at(self, cut: int) -> dict[int, tuple[int, int, str]]:
        """Reconstruct the register at ``cut`` for this tile's key interval."""
        state = self.initial_map()
        for change_cut, key, _kind, litres, origin in self.changes:
            if change_cut > cut:
                break
            if litres is None:
                state.pop(key, None)
            else:
                state[key] = (litres, change_cut, origin)
        return state

    def covers_facts(self, cut: int) -> bool:
        return self.start <= cut <= self.end

    def covers_revision(self, cut: int) -> bool:
        return self.start < cut <= self.end


def tile_from_artifact(artifact: FrozenHistory) -> Tile:
    return Tile(
        artifact.artifact_id,
        artifact.bounds[0],
        artifact.bounds[1],
        artifact.start,
        artifact.end,
        tuple((row.key, row.litres, row.cut, row.origin) for row in artifact.initial),
        tuple((change.cut, change.key, change.kind, change.litres, change.origin)
              for change in artifact.changes),
    )


def record_history_evidence(db: sqlite3.Connection, artifact: FrozenHistory) -> None:
    lower, upper = artifact.bounds
    db.execute(
        '''INSERT INTO history_evidence (artifact_id, station, day, lower_key, upper_key, start_cut, end_cut)
           VALUES (?, ?, ?, ?, ?, ?, ?)''',
        (artifact.artifact_id, *artifact.station_day.identity,
         hex(lower), hex(upper), hex(artifact.start), hex(artifact.end)),
    )
    db.executemany(
        '''INSERT INTO history_initial (artifact_id, key, litres, cut, origin)
           VALUES (?, ?, ?, ?, ?)''',
        ((artifact.artifact_id, hex(row.key), hex(row.litres), hex(row.cut), row.origin)
         for row in artifact.initial),
    )
    db.executemany(
        '''INSERT INTO history_changes (artifact_id, cut, key, kind, litres, origin)
           VALUES (?, ?, ?, ?, ?, ?)''',
        ((artifact.artifact_id, hex(change.cut), hex(change.key), change.kind,
          None if change.litres is None else hex(change.litres), change.origin)
         for change in artifact.changes),
    )


def load_tiles(db: sqlite3.Connection, day: StationDay) -> list[Tile]:
    tables = {
        name for (name,) in db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN "
            "('history_evidence', 'history_initial', 'history_changes')"
        )
    }
    if len(tables) != 3:
        return []
    tiles = []
    for artifact_id, lower, upper, start, end in db.execute(
        '''SELECT artifact_id, lower_key, upper_key, start_cut, end_cut
           FROM history_evidence WHERE station = ? AND day = ? ORDER BY artifact_id''',
        day.identity,
    ).fetchall():
        initial = tuple(
            (int(key, 16), int(litres, 16), int(cut, 16), origin)
            for key, litres, cut, origin in db.execute(
                'SELECT key, litres, cut, origin FROM history_initial WHERE artifact_id = ? ORDER BY key',
                (artifact_id,),
            )
        )
        changes = tuple(
            (int(cut, 16), int(key, 16), kind, None if litres is None else int(litres, 16), origin)
            for cut, key, kind, litres, origin in db.execute(
                'SELECT cut, key, kind, litres, origin FROM history_changes WHERE artifact_id = ? ORDER BY cut',
                (artifact_id,),
            )
        )
        tiles.append(Tile(artifact_id, int(lower, 16), int(upper, 16),
                          int(start, 16), int(end, 16), initial, changes))
    return tiles


def compare_tiles(first: Tile, second: Tile) -> None:
    """Raise when two same-day tiles contradict a fact or revision they both claim."""
    lower = max(first.lower, second.lower)
    upper = min(first.upper, second.upper)
    if lower >= upper:
        return
    low_cut = max(first.start, second.start)
    high_cut = min(first.end, second.end)
    if low_cut > high_cut:
        return

    first_changes = first.changes_map()
    second_changes = second.changes_map()

    # Common revision window: every cut both tiles contain must list identical revisions.
    # A revision whose key lies outside the shared key interval was never claimed by the
    # other tile, so only revisions inside the shared interval can contradict absence.
    if low_cut < high_cut:
        for cut in sorted(set(first_changes) | set(second_changes)):
            if not low_cut < cut <= high_cut:
                continue
            left = first_changes.get(cut)
            right = second_changes.get(cut)
            if left is not None and right is not None:
                if left != right:
                    raise ValueError('history tiles disagree about a shared revision')
                continue
            present = left if left is not None else right
            if lower <= present[1] < upper:
                raise ValueError('history tiles disagree about a shared revision window')

    # Common cuts: the reconstructed register must match on shared keys, including absence.
    critical = {low_cut}
    critical.update(cut for cut in first_changes if low_cut < cut <= high_cut)
    critical.update(cut for cut in second_changes if low_cut < cut <= high_cut)
    for cut in sorted(critical):
        left_state = first.state_at(cut)
        right_state = second.state_at(cut)
        keys = {key for key in left_state if lower <= key < upper}
        keys.update(key for key in right_state if lower <= key < upper)
        for key in keys:
            if left_state.get(key) != right_state.get(key):
                raise ValueError('history tiles disagree about a shared starting fact')


def check_history_consistency(db: sqlite3.Connection, artifact: FrozenHistory) -> None:
    new_tile = tile_from_artifact(artifact)
    for existing in load_tiles(db, artifact.station_day):
        compare_tiles(new_tile, existing)


def _merge_covers(intervals, lower: int, upper: int) -> bool:
    cursor = lower
    for low, high in sorted(intervals):
        if high <= cursor:
            continue
        if low > cursor:
            return False
        cursor = high
        if cursor >= upper:
            return True
    return cursor >= upper


def _keys_covered_at(tiles: list[Tile], cut: int, lower: int, upper: int) -> bool:
    return _merge_covers(
        ((tile.lower, tile.upper) for tile in tiles if tile.covers_facts(cut)), lower, upper
    )


def _revisions_covered(tiles: list[Tile], lower: int, upper: int, start: int, end: int) -> bool:
    breaks = {start + 1, end + 1}
    for tile in tiles:
        breaks.add(tile.start + 1)
        breaks.add(tile.end + 1)
    ordered = sorted(breaks)
    for left, right in zip(ordered, ordered[1:]):
        segment_low = max(left, start + 1)
        segment_high = min(right, end + 1)
        if segment_low >= segment_high:
            continue
        cut = segment_low
        active = ((tile.lower, tile.upper) for tile in tiles if tile.covers_revision(cut))
        if not _merge_covers(active, lower, upper):
            return False
    return True


def collect_history(
    db: sqlite3.Connection, day: StationDay, bounds: tuple[int, int], start: int, end: int
) -> dict[str, list] | str:
    """Return the merged history once every (key, cut) pair is covered, otherwise PENDING."""
    lower, upper = bounds
    if lower >= upper:
        return {'initial': [], 'revisions': []}
    tiles = load_tiles(db, day)
    if not _keys_covered_at(tiles, start, lower, upper):
        return 'PENDING'
    if not _revisions_covered(tiles, lower, upper, start, end):
        return 'PENDING'

    initial: dict[int, tuple[int, int, str]] = {}
    for tile in tiles:
        if not tile.covers_facts(start):
            continue
        for key, fact in tile.state_at(start).items():
            if not lower <= key < upper:
                continue
            previous = initial.get(key)
            if previous is not None and previous != fact:
                raise ValueError('received history tiles disagree about a starting fact')
            initial[key] = fact

    revisions: dict[tuple, tuple] = {}
    for tile in tiles:
        for change in tile.changes:
            cut, key = change[0], change[1]
            if not (start < cut <= end and lower <= key < upper):
                continue
            previous = revisions.get((cut, key))
            if previous is not None and previous != change:
                raise ValueError('received history tiles disagree about a revision')
            revisions[(cut, key)] = change

    return {
        'initial': [(key, *initial[key]) for key in sorted(initial)],
        'revisions': [revisions[item] for item in sorted(revisions)],
    }
