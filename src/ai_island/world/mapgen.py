"""Map generation.

One home template is generated once from the ``map`` stream, with its resources, plants
and animals, then rotated into the four corners (template rotated clockwise by
``index * 90`` degrees). The centre and buffer are generated afterwards.
"""

from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass, field

from ai_island.config import ANIMAL_KINDS, PLANT_KINDS, GameConfig
from ai_island.rng import Streams
from ai_island.storage.events import WorldCreated
from ai_island.world import animals as animals_mod
from ai_island.world import dogs as dogs_mod
from ai_island.world import engine as engine_mod
from ai_island.world import movement as movement_mod
from ai_island.world import plants as plants_mod
from ai_island.world import weather as weather_mod
from ai_island.world.state import (
    NEIGHBOUR_STEPS,
    Animal,
    Dog,
    Home,
    Landmark,
    PlantSite,
    Pos,
    World,
)


def rotate_cw(x: int, y: int, size: int, turns: int) -> Pos:
    """Rotate a cell of a ``size`` x ``size`` square clockwise by ``turns`` quarter turns."""
    for _ in range(turns % 4):
        x, y = size - 1 - y, x
    return x, y


@dataclass
class HomeTemplate:
    size: int
    terrain: list[list[str]]
    stone: dict[Pos, int] = field(default_factory=dict)
    plants: list[tuple[str, int, int]] = field(default_factory=list)
    animals: list[tuple[str, int, int]] = field(default_factory=list)


def build_zone_grid(world: World) -> tuple[list[list[str]], list[str]]:
    """Zone id of every tile: home_0..home_3, centre or buffer."""
    grid = [["buffer"] * world.width for _ in range(world.height)]
    zones = [h.zone for h in world.homes] + ["centre", "buffer"]
    for home in world.homes:
        for y in range(home.y, home.y + home.size):
            for x in range(home.x, home.x + home.size):
                grid[y][x] = home.zone
    x0, y0, x1, y1 = world.zone_bounds("centre")
    for y in range(y0, y1):
        for x in range(x0, x1):
            grid[y][x] = "centre"
    return grid, zones


def _free_cell(rng: random.Random, x0: int, y0: int, x1: int, y1: int, taken: set[Pos]) -> Pos:
    for _ in range(2000):
        cell = (rng.randrange(x0, x1), rng.randrange(y0, y1))
        if cell not in taken:
            return cell
    for y in range(y0, y1):
        for x in range(x0, x1):
            if (x, y) not in taken:
                return x, y
    raise RuntimeError("map generation: no free cell left")


def _place_rect(
    rng: random.Random,
    region: tuple[int, int, int, int],
    w: int,
    h: int,
    taken: set[Pos],
    pad: int = 1,
) -> Pos:
    """Top-left of a free ``w`` x ``h`` rectangle inside ``region`` (end exclusive)."""
    x0, y0, x1, y1 = region

    def fits(px: int, py: int) -> bool:
        for yy in range(py - pad, py + h + pad):
            for xx in range(px - pad, px + w + pad):
                if (xx, yy) in taken:
                    return False
        return True

    for _ in range(500):
        px = rng.randrange(x0, x1 - w + 1)
        py = rng.randrange(y0, y1 - h + 1)
        if fits(px, py):
            return px, py
    for py in range(y0, y1 - h + 1):
        for px in range(x0, x1 - w + 1):
            if fits(px, py):
                return px, py
    raise RuntimeError("map generation: no room for a rectangle")


def _make_template(cfg: GameConfig, rng: random.Random) -> HomeTemplate:
    n = cfg.world.map.home_size
    hc = cfg.world.home
    terrain = [["grass"] * n for _ in range(n)]
    taken: set[Pos] = set()
    tpl = HomeTemplate(size=n, terrain=terrain)
    for _ in range(hc.spring_tiles):
        x, y = _free_cell(rng, 2, 2, n - 2, n - 2, taken)
        terrain[y][x] = "spring"
        taken.add((x, y))
    fx, fy = _place_rect(rng, (1, 1, n - 1, n - 1), hc.farmland_width, hc.farmland_height, taken)
    for yy in range(fy, fy + hc.farmland_height):
        for xx in range(fx, fx + hc.farmland_width):
            terrain[yy][xx] = "farmland_empty"
            taken.add((xx, yy))
    # the small forest: a blob grown from one seed tile
    blob: list[Pos] = [_free_cell(rng, 1, 1, n - 1, n - 1, taken)]
    blob_set = set(blob)
    attempts = 0
    while len(blob) < hc.tree_tiles and attempts < 20000:
        attempts += 1
        bx, by = blob[rng.randrange(len(blob))]
        dx, dy = NEIGHBOUR_STEPS[rng.randrange(4)]
        cx, cy = bx + dx, by + dy
        if 0 <= cx < n and 0 <= cy < n and (cx, cy) not in taken and (cx, cy) not in blob_set:
            blob.append((cx, cy))
            blob_set.add((cx, cy))
    for x, y in blob:
        terrain[y][x] = "tree"
    taken |= blob_set
    for _ in range(hc.rocky_tiles):
        x, y = _free_cell(rng, 0, 0, n, n, taken)
        terrain[y][x] = "rocky"
        tpl.stone[(x, y)] = cfg.balance.stone.rocky_stone
        taken.add((x, y))
    # plants on plain grass
    used: set[Pos] = set()
    for kind in sorted(PLANT_KINDS):
        for _ in range(cfg.world.plants[kind].per_home):
            cell = _grass_cell(rng, terrain, used)
            if cell is not None:
                used.add(cell)
                tpl.plants.append((kind, cell[0], cell[1]))
    # animals on their habitat
    for kind in ANIMAL_KINDS:
        spec = cfg.world.animals[kind]
        for _ in range(spec.initial.home):
            cell = _habitat_cell(rng, terrain, spec.habitat)
            if cell is not None:
                tpl.animals.append((kind, cell[0], cell[1]))
    return tpl


def _grass_cell(rng: random.Random, terrain: list[list[str]], used: set[Pos]) -> Pos | None:
    n = len(terrain)
    for _ in range(1000):
        x, y = rng.randrange(n), rng.randrange(n)
        if terrain[y][x] == "grass" and (x, y) not in used:
            return x, y
    return None


def _habitat_cell(rng: random.Random, terrain: list[list[str]], habitat: list[str]) -> Pos | None:
    n = len(terrain)
    for _ in range(1000):
        x, y = rng.randrange(n), rng.randrange(n)
        if terrain[y][x] in habitat:
            return x, y
    return None


def _nearest_walkable(world: World, cx: int, cy: int) -> Pos:
    best: Pos | None = None
    best_d = 10**9
    for y in range(world.height):
        for x in range(world.width):
            if world.passable(x, y) and world.terrain[y][x] in ("grass", "sand"):
                d = abs(x - cx) + abs(y - cy)
                if d < best_d:
                    best, best_d = (x, y), d
    assert best is not None
    return best


def _reachable(world: World, start: Pos) -> set[Pos]:
    seen = {start}
    queue = deque([start])
    while queue:
        x, y = queue.popleft()
        for dx, dy in NEIGHBOUR_STEPS:
            nx, ny = x + dx, y + dy
            if world.inside(nx, ny) and (nx, ny) not in seen and world.passable(nx, ny):
                seen.add((nx, ny))
                queue.append((nx, ny))
    return seen


def _carve(world: World, a: Pos, b: Pos) -> None:
    """Turn water tiles on an L-shaped line from a to b into grass."""
    x, y = a
    while x != b[0]:
        x += 1 if b[0] > x else -1
        if not world.passable(x, y):
            world.terrain[y][x] = "grass"
    while y != b[1]:
        y += 1 if b[1] > y else -1
        if not world.passable(x, y):
            world.terrain[y][x] = "grass"


def _ensure_corridors(world: World, targets: list[Pos]) -> None:
    origin = targets[0]
    for _ in range(len(targets) + 1):
        reach = _reachable(world, origin)
        missing = [t for t in targets if t not in reach]
        if not missing:
            return
        _carve(world, origin, missing[0])
    raise RuntimeError("map generation: could not connect the map")


def _centre_features(world: World, rng: random.Random) -> list[Pos]:
    """Lake, quarry, best farmland, great tree, dock and the large forest."""
    cfg = world.cfg
    cc = cfg.world.centre
    bal = cfg.balance
    x0, y0, x1, y1 = world.zone_bounds("centre")
    inner = (x0 + 2, y0 + 2, x1 - 2, y1 - 2)
    taken: set[Pos] = set()
    lx, ly = _place_rect(rng, inner, cc.lake_width, cc.lake_height, taken, pad=2)
    lake: set[Pos] = set()
    for yy in range(ly, ly + cc.lake_height):
        for xx in range(lx, lx + cc.lake_width):
            corner = xx in (lx, lx + cc.lake_width - 1) and yy in (ly, ly + cc.lake_height - 1)
            if not corner:
                world.terrain[yy][xx] = "lake"
                lake.add((xx, yy))
            taken.add((xx, yy))
    q = cc.quarry_size
    qx, qy = _place_rect(rng, inner, q, q, taken, pad=1)
    for yy in range(qy, qy + q):
        for xx in range(qx, qx + q):
            world.terrain[yy][xx] = "quarry"
            world.stone[(xx, yy)] = bal.stone.quarry_stone
            taken.add((xx, yy))
    world.landmarks.append(Landmark("quarry", qx + q // 2, qy + q // 2))
    fx, fy = _place_rect(rng, inner, cc.farmland_width, cc.farmland_height, taken, pad=1)
    for yy in range(fy, fy + cc.farmland_height):
        for xx in range(fx, fx + cc.farmland_width):
            world.terrain[yy][xx] = "farmland_empty"
            taken.add((xx, yy))
    # the great tree: the free grass tile closest to the middle of the centre
    mx, my = (x0 + x1) // 2, (y0 + y1) // 2
    candidates = sorted(
        (abs(xx - mx) + abs(yy - my), yy, xx)
        for yy in range(y0, y1)
        for xx in range(x0, x1)
        if (xx, yy) not in taken
    )
    gx, gy = candidates[0][2], candidates[0][1]
    taken.add((gx, gy))
    world.landmarks.append(Landmark("great_tree", gx, gy))
    # the dock: the first free tile (top to bottom, left to right) beside the lake
    dock: Pos | None = None
    for yy in range(y0, y1):
        for xx in range(x0, x1):
            if (xx, yy) in taken:
                continue
            if any((xx + dx, yy + dy) in lake for dx, dy in NEIGHBOUR_STEPS):
                dock = (xx, yy)
                break
        if dock:
            break
    assert dock is not None
    taken.add(dock)
    world.landmarks.append(Landmark("lake_dock", dock[0], dock[1]))
    # the large forest
    for _ in range(cc.forest_clumps):
        cx = rng.randrange(x0 + 2, x1 - 2)
        cy = rng.randrange(y0 + 2, y1 - 2)
        r = cc.forest_radius
        for yy in range(cy - r, cy + r + 1):
            for xx in range(cx - r, cx + r + 1):
                if not (x0 <= xx < x1 and y0 <= yy < y1):
                    continue
                if (xx - cx) ** 2 + (yy - cy) ** 2 > r * r:
                    continue
                if world.terrain[yy][xx] == "grass" and (xx, yy) not in taken:
                    if rng.random() < cc.forest_density:
                        world.terrain[yy][xx] = "tree"
    for _ in range(cc.rocky_tiles):
        pos = world.random_tile(rng, "centre", ["grass"])
        if pos and pos not in taken:
            world.terrain[pos[1]][pos[0]] = "rocky"
            world.stone[pos] = bal.stone.rocky_stone
    return [(m.x, m.y) for m in world.landmarks]


def _buffer_features(world: World, rng: random.Random) -> None:
    mc = world.cfg.world.map
    for _ in range(mc.buffer_forest_clumps):
        centre = world.random_tile(rng, "buffer", ["grass"])
        if centre is None:
            break
        r = mc.buffer_forest_radius
        for yy in range(centre[1] - r, centre[1] + r + 1):
            for xx in range(centre[0] - r, centre[0] + r + 1):
                if not world.inside(xx, yy) or world.zone_at(xx, yy) != "buffer":
                    continue
                if (xx - centre[0]) ** 2 + (yy - centre[1]) ** 2 > r * r:
                    continue
                if world.terrain[yy][xx] == "grass" and rng.random() < mc.buffer_forest_density:
                    world.terrain[yy][xx] = "tree"
    for _ in range(mc.buffer_rocky_tiles):
        pos = world.random_tile(rng, "buffer", ["grass"])
        if pos:
            world.terrain[pos[1]][pos[0]] = "rocky"
            world.stone[pos] = world.cfg.balance.stone.rocky_stone
    for _ in range(mc.buffer_stray_trees):
        pos = world.random_tile(rng, "buffer", ["grass"])
        if pos:
            world.terrain[pos[1]][pos[0]] = "tree"


def unclaimed_pool(world: World) -> list[tuple[int, int]]:
    """Passable, non-landmark tiles of the configured pool zones, sorted by y then x.

    Computed from the generated map; the live pool is ``world.unclaimed``.
    """
    zones = set(world.cfg.world.land.pool_zones)
    marks = {(m.x, m.y) for m in world.landmarks}
    return [
        (x, y)
        for y in range(world.height)
        for x in range(world.width)
        if world.zone_grid[y][x] in zones and world.passable(x, y) and (x, y) not in marks
    ]


def generate_world(cfg: GameConfig, streams: Streams) -> World:
    """Create the island at tick 0 and schedule its first work."""
    world = World(cfg, streams)
    rng = streams.get("map")
    mc = cfg.world.map
    w, h = world.width, world.height
    # the water ring and the beach
    for y in range(h):
        for x in range(w):
            d = min(x, y, w - 1 - x, h - 1 - y)
            if d < mc.coast_width:
                world.terrain[y][x] = "coast"
            elif d < mc.coast_width + mc.sand_width:
                world.terrain[y][x] = "sand"
    # four homes from one template
    template = _make_template(cfg, rng)
    n, m = mc.home_size, mc.home_margin
    origins = [(m, m), (w - m - n, m), (w - m - n, h - m - n), (m, h - m - n)]
    for index, (ox, oy) in enumerate(origins):
        world.homes.append(Home(index, ox, oy, n, index, (ox, oy)))
        for ty in range(n):
            for tx in range(n):
                rx, ry = rotate_cw(tx, ty, n, index)
                world.terrain[oy + ry][ox + rx] = template.terrain[ty][tx]
        for (tx, ty), amount in sorted(template.stone.items()):
            rx, ry = rotate_cw(tx, ty, n, index)
            world.stone[(ox + rx, oy + ry)] = amount
    world.zone_grid, world.zones = build_zone_grid(world)
    _centre_features(world, rng)
    _buffer_features(world, rng)
    for home in world.homes:
        home.anchor = _nearest_walkable(world, home.x + n // 2, home.y + n // 2)
    targets = [home.anchor for home in world.homes] + [(m_.x, m_.y) for m_ in world.landmarks]
    _ensure_corridors(world, targets)
    world.unclaimed = unclaimed_pool(world)
    # tree counts per area, for the over-cut rule
    for zone in world.zones:
        world.trees_alive[zone] = 0
    for y in range(h):
        for x in range(w):
            if world.terrain[y][x] == "tree":
                world.trees_alive[world.zone_at(x, y)] += 1
    world.tree_initial = dict(world.trees_alive)
    # plants and animals: home ones come from the rotated template
    for index, home in enumerate(world.homes):
        for kind, tx, ty in template.plants:
            rx, ry = rotate_cw(tx, ty, n, index)
            world.plants.append(
                PlantSite(world.new_id(), kind, home.x + rx, home.y + ry, True, None)
            )
        for kind, tx, ty in template.animals:
            rx, ry = rotate_cw(tx, ty, n, index)
            world.animals[kind].append(
                Animal(world.new_id(), kind, home.x + rx, home.y + ry, home.zone)
            )
    for zone, attr in (("centre", "per_centre"), ("buffer", "per_buffer")):
        used = {(p.x, p.y) for p in world.plants}
        for kind in sorted(PLANT_KINDS):
            for _ in range(getattr(cfg.world.plants[kind], attr)):
                pos = world.random_tile(rng, zone, ["grass"])
                if pos and pos not in used:
                    used.add(pos)
                    world.plants.append(PlantSite(world.new_id(), kind, pos[0], pos[1], True, None))
    for zone, attr in (("centre", "centre"), ("buffer", "buffer")):
        for kind in ANIMAL_KINDS:
            spec = cfg.world.animals[kind]
            for _ in range(getattr(spec.initial, attr)):
                pos = world.random_tile(rng, zone, spec.habitat)
                if pos:
                    world.animals[kind].append(Animal(world.new_id(), kind, pos[0], pos[1], zone))
    # dog packs only in buffer and centre forests
    dc = cfg.world.dogs
    for zone, count in (("centre", dc.initial_packs_centre), ("buffer", dc.initial_packs_buffer)):
        for _ in range(count):
            pos = world.random_tile(streams.get("dogs"), zone, ["tree"])
            if pos is None:
                continue
            pack = world.next_pack
            world.next_pack += 1
            size = streams.get("dogs").randint(dc.pack_min, dc.pack_max)
            for _ in range(size):
                world.dogs.append(Dog(world.new_id(), pack, pos[0], pos[1]))
    # stagger the first move of every mover, then schedule the first work and log the start
    for mover in movement_mod.moving_entities(world):
        movement_mod.register(world, mover, 0)
    world.emit(WorldCreated(seed=streams.seed, width=w, height=h))
    weather_mod.update_weather(world, 0)
    engine_mod.schedule_core(world)
    plants_mod.schedule_initial(world)
    animals_mod.schedule_initial(world)
    dogs_mod.schedule_initial(world)
    movement_mod.schedule_initial(world)
    return world
