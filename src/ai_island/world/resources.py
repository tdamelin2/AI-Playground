"""Trees, stone, water and farmland: the world mutation API and its timers."""

from __future__ import annotations

from ai_island.config import SEASONS
from ai_island.storage.events import CropChanged, StoneTaken, TreeCut, TreeRegrown
from ai_island.world.clock import season_index_at
from ai_island.world.state import NEIGHBOUR_STEPS, Pos, World

ORDER_TREES = 2
ORDER_CROPS = 3

# farmland state -> (next state, ticks setting name, only grows outside winter)
_CROP_NEXT = {
    "farmland_planted": ("farmland_growing", "planted_ticks", True),
    "farmland_growing": ("farmland_ready", "growing_ticks", True),
    "farmland_ready": ("farmland_failed", "ready_spoil_ticks", False),
    "farmland_failed": ("farmland_empty", "failed_reset_ticks", False),
}


def cut_tree(world: World, pos: Pos, tick: int) -> bool:
    """Cut the tree at ``pos``: it becomes a stump and may regrow later."""
    x, y = pos
    if not world.inside(x, y) or world.terrain[y][x] != "tree":
        return False
    world.terrain[y][x] = "stump"
    zone = world.zone_at(x, y)
    world.trees_alive[zone] -= 1
    world.emit(TreeCut(x=x, y=y, area=zone, trees_left=world.trees_alive[zone]), tick)
    due = tick + world.cfg.balance.trees.regrow_ticks
    world.sched.push(due, ORDER_TREES, y * world.width + x, "tree_regrow", (x, y))
    return True


def run_tree_regrow(world: World, tick: int, args: tuple) -> None:
    x, y = args
    if world.terrain[y][x] != "stump":
        return
    zone = world.zone_at(x, y)
    initial = world.tree_initial.get(zone, 0)
    if initial == 0:
        return
    if world.trees_alive[zone] / initial < world.cfg.balance.trees.overcut_threshold:
        return  # over-cut: this area no longer regrows
    world.terrain[y][x] = "tree"
    world.trees_alive[zone] += 1
    world.emit(TreeRegrown(x=x, y=y, area=zone), tick)


def take_stone(world: World, pos: Pos, n: int) -> int:
    """Take up to ``n`` stone from the tile at ``pos``; returns what was taken."""
    stock = world.stone.get(pos, 0)
    taken = max(0, min(n, stock))
    if taken == 0:
        return 0
    world.stone[pos] = stock - taken
    x, y = pos
    if world.stone[pos] == 0:
        kind = world.terrain[y][x]
        if kind in ("rocky", "quarry"):
            world.terrain[y][x] = f"{kind}_depleted"
    world.emit(StoneTaken(x=x, y=y, taken=taken, remaining=world.stone[pos]))
    return taken


def water_output(world: World, pos: Pos) -> float:
    """Water a spring or lake tile gives now (a walkable tile beside water counts too)."""
    bal = world.cfg.balance.water
    x, y = pos
    if not world.inside(x, y):
        return 0.0
    kinds = [world.terrain[y][x]]
    kinds += [
        world.terrain[y + dy][x + dx] for dx, dy in NEIGHBOUR_STEPS if world.inside(x + dx, y + dy)
    ]
    base = 0.0
    for kind in kinds:
        if kind == "lake":
            base = max(base, bal.lake_output)
        elif kind == "spring":
            base = max(base, bal.spring_output)
    return base * world.weather.flags.water_multiplier


def _next_growing_start(world: World, tick: int) -> int:
    clock = world.cfg.world.clock
    allowed = world.cfg.balance.crops.growing_seasons
    start = (tick // clock.season_ticks + 1) * clock.season_ticks
    while SEASONS[season_index_at(start, clock)] not in allowed:
        start += clock.season_ticks
    return start


def _schedule_crop(world: World, x: int, y: int, state: str, tick: int, delay: int) -> None:
    world.sched.push(tick + delay, ORDER_CROPS, y * world.width + x, "crop", (x, y, state))


def plant_crop(world: World, pos: Pos, tick: int) -> bool:
    """Sow empty farmland at ``pos``."""
    x, y = pos
    if not world.inside(x, y) or world.terrain[y][x] != "farmland_empty":
        return False
    world.terrain[y][x] = "farmland_planted"
    world.emit(CropChanged(x=x, y=y, state="farmland_planted"), tick)
    _schedule_crop(world, x, y, "farmland_planted", tick, world.cfg.balance.crops.planted_ticks)
    return True


def harvest_crop(world: World, pos: Pos, tick: int) -> bool:
    """Harvest a ready crop: the field becomes empty again."""
    x, y = pos
    if not world.inside(x, y) or world.terrain[y][x] != "farmland_ready":
        return False
    world.terrain[y][x] = "farmland_empty"
    world.emit(CropChanged(x=x, y=y, state="farmland_empty"), tick)
    return True


def run_crop(world: World, tick: int, args: tuple) -> None:
    x, y, state = args
    if world.terrain[y][x] != state:
        return
    nxt, setting, seasonal = _CROP_NEXT[state]
    crops = world.cfg.balance.crops
    delay = getattr(crops, setting)
    if seasonal:
        season = SEASONS[season_index_at(tick, world.cfg.world.clock)]
        if season not in crops.growing_seasons:
            # nothing grows in winter: wait for the next growing season, then start over
            resume = _next_growing_start(world, tick)
            world.sched.push(resume + delay, ORDER_CROPS, y * world.width + x, "crop", args)
            return
    world.terrain[y][x] = nxt
    world.emit(CropChanged(x=x, y=y, state=nxt), tick)
    if nxt in _CROP_NEXT:
        _schedule_crop(world, x, y, nxt, tick, getattr(crops, _CROP_NEXT[nxt][1]))
