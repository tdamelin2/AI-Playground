"""Memory of place and the sight interrupts.

A player remembers what it last saw on each tile. The memory is kept in ``Player.place_memory``
(under ``"tiles"``, JSON-safe) and is not corrected when the real tile changes out of sight.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ai_island.rules.senses.common import Pos, dist2, interrupt, pos_of, setting
from ai_island.rules.senses.ranges import sight_range


@dataclass(frozen=True)
class RememberedTile:
    terrain: str
    structure_kind: str | None
    plant_kind: str | None
    seen_tick: int


def tiles_in_sight(world: Any, centre: Pos, radius: int) -> list[Pos]:
    """Map tiles within ``radius`` (Euclidean) of ``centre``, row by row."""
    out: list[Pos] = []
    r2 = radius * radius
    for y in range(max(0, centre[1] - radius), min(world.height, centre[1] + radius + 1)):
        for x in range(max(0, centre[0] - radius), min(world.width, centre[0] + radius + 1)):
            if dist2(centre, (x, y)) <= r2:
                out.append((x, y))
    return out


def refresh_memory(world: Any, pid: str, tick: int) -> None:
    """Update the remembered tiles of ``pid`` for everything it can see now."""
    player = world.players[pid]
    centre = pos_of(player)
    radius = sight_range(world, pid, tick)
    r2 = radius * radius
    plants = {
        (p.x, p.y): p.kind for p in world.plants if p.present and dist2(centre, (p.x, p.y)) <= r2
    }
    structures = {
        (s.x, s.y): s.kind for s in world.structures.values() if dist2(centre, (s.x, s.y)) <= r2
    }
    tiles = player.place_memory.setdefault("tiles", {})
    for x, y in tiles_in_sight(world, centre, radius):
        tiles[f"{x},{y}"] = [world.terrain[y][x], structures.get((x, y)), plants.get((x, y)), tick]


def remembered_tile(world: Any, pid: str, pos: Pos) -> RememberedTile | None:
    """What ``pid`` last saw on ``pos`` (None if it never has)."""
    row = world.players[pid].place_memory.get("tiles", {}).get(f"{pos[0]},{pos[1]}")
    if row is None:
        return None
    return RememberedTile(row[0], row[1], row[2], row[3])


def remembered_positions(world: Any, pid: str, terrains: frozenset[str]) -> list[Pos]:
    """Remembered tiles whose remembered terrain is in ``terrains`` (sorted)."""
    found: list[Pos] = []
    for key, row in world.players[pid].place_memory.get("tiles", {}).items():
        if row[0] in terrains:
            x, y = key.split(",")
            found.append((int(x), int(y)))
    return sorted(found)


def visible_ids(world: Any, pid: str, tick: int) -> set[str]:
    """Ids of the other living players and the dogs that ``pid`` can see now."""
    me = world.players[pid]
    here = pos_of(me)
    r = sight_range(world, pid, tick)
    r2 = r * r
    seen: set[str] = set()
    for other_id, other in world.players.items():
        if other_id != pid and other.alive and dist2(here, pos_of(other)) <= r2:
            seen.add(other_id)
    for dog in world.dogs:
        if dist2(here, (dog.x, dog.y)) <= r2:
            seen.add(f"dog_{dog.id}")
    return seen


def detect_sight_interrupts(world: Any, tick: int) -> None:
    """Raise player_in_sight / dog_in_sight for ids that just came into sight (players only)."""
    refresh_every = int(setting(world, "memory_refresh_ticks"))
    for pid in sorted(world.players):
        player = world.players[pid]
        if not player.alive:
            player.seen_ids = []
            continue
        if tick % refresh_every == 0:
            refresh_memory(world, pid, tick)
        now = visible_ids(world, pid, tick)
        before = set(player.seen_ids)
        for ident in sorted(now - before):
            kind = "dog_in_sight" if ident.startswith("dog_") else "player_in_sight"
            interrupt(world, kind, pid, tick, source=ident)
        player.seen_ids = sorted(now)
