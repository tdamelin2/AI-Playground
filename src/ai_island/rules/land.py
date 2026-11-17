"""Land: home plots, claimed tiles, stakes and borders."""

from __future__ import annotations

from ai_island.storage.events import LandClaimed
from ai_island.world.state import Pos, World


def _pool(world: World) -> set[Pos]:
    cached = getattr(world, "_pool_set", None)
    if cached is None:
        cached = set(world.unclaimed)
        world._pool_set = cached  # type: ignore[attr-defined]
    return cached


def home_owner(world: World, pos: Pos) -> str | None:
    zone = world.zone_at(*pos)
    if zone.startswith("home_"):
        return f"player_{int(zone.split('_')[1]) + 1}"
    return None


def owner_of(world: World, pos: Pos) -> str | None:
    """The player who owns ``pos``: its home plot's player or its claimant."""
    return home_owner(world, pos) or world.claims.get(pos)


def claimed_count(world: World, pid: str) -> int:
    return sum(1 for owner in world.claims.values() if owner == pid)


def free_pool(world: World) -> list[Pos]:
    return [t for t in world.unclaimed if t not in world.claims]


def _within(centre: Pos, radius: int):
    r2 = radius * radius
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if dx * dx + dy * dy <= r2:
                yield centre[0] + dx, centre[1] + dy


def place_stake(world: World, pid: str, pos: Pos, tick: int) -> int:
    """Put a stake at ``pos``; claims the unclaimed pool tiles within the claim radius."""
    radius = world.cfg.balance.claims.claim_radius
    pool = _pool(world)
    world.stakes[pos] = pid
    gained = 0
    for tile in _within(pos, radius):
        if tile in pool and tile not in world.claims:
            world.claims[tile] = pid
            gained += 1
    world.emit(LandClaimed(player=pid, x=pos[0], y=pos[1], tiles=gained), tick)
    return gained


def pull_stake(world: World, pos: Pos, tick: int) -> str | None:
    """Remove a stake. Its tiles return to the pool unless the owner has another stake there."""
    owner = world.stakes.pop(pos, None)
    if owner is None:
        return None
    radius = world.cfg.balance.claims.claim_radius
    still = [s for s, o in world.stakes.items() if o == owner]
    for tile in _within(pos, radius):
        if world.claims.get(tile) != owner:
            continue
        if any((tile[0] - s[0]) ** 2 + (tile[1] - s[1]) ** 2 <= radius * radius for s in still):
            continue
        del world.claims[tile]
    return owner


def grant_tiles(world: World, pid: str, n: int, tick: int) -> int:
    """Claim up to ``n`` free pool tiles nearest the player's home (no stake). Returns how many."""
    anchor = world.homes[world.players[pid].index - 1].anchor
    free = free_pool(world)
    free.sort(key=lambda t: (abs(t[0] - anchor[0]) + abs(t[1] - anchor[1]), t[1], t[0]))
    chosen = free[:n]
    for tile in chosen:
        world.claims[tile] = pid
    if chosen:
        world.emit(LandClaimed(player=pid, x=chosen[0][0], y=chosen[0][1], tiles=len(chosen)), tick)
    return len(chosen)


def owner_index(owner: str | None) -> int:
    return 0 if owner is None else int(owner.split("_")[1])


def border_tiles(world: World) -> tuple[tuple[int, int, int], ...]:
    """Claimed tiles (homes and claims) that touch another owner or unowned land."""
    out: list[tuple[int, int, int]] = []
    tiles: dict[Pos, str] = dict(world.claims)
    for home in world.homes:
        owner = f"player_{home.index + 1}"
        for y in range(home.y, home.y + home.size):
            for x in range(home.x, home.x + home.size):
                tiles[(x, y)] = owner
    for (x, y), owner in sorted(tiles.items()):
        for dx, dy in ((1, 0), (0, 1), (-1, 0), (0, -1)):
            if tiles.get((x + dx, y + dy)) != owner:
                out.append((x, y, owner_index(owner)))
                break
    return tuple(out)


def stake_tiles(world: World) -> tuple[tuple[int, int, int], ...]:
    return tuple((x, y, owner_index(o)) for (x, y), o in sorted(world.stakes.items()))
