"""Spawning players and villagers, and walking them along A* routes."""

from __future__ import annotations

from ai_island.world.agents import Player, Villager
from ai_island.world.movement import begin_step, complete_step, is_stepping, step_minutes
from ai_island.world.pathfinding import astar
from ai_island.world.state import NEIGHBOUR_STEPS, Pos, World

Walker = Player | Villager


def player_id(index: int) -> str:
    return f"player_{index}"


def free_tile_near(world: World, rng, centre: Pos, spread: int) -> Pos:
    """A passable tile within ``spread`` of ``centre`` (the centre itself if none)."""
    options = [
        (centre[0] + dx, centre[1] + dy)
        for dy in range(-spread, spread + 1)
        for dx in range(-spread, spread + 1)
        if world.inside(centre[0] + dx, centre[1] + dy)
        and world.passable(centre[0] + dx, centre[1] + dy)
    ]
    return options[rng.randrange(len(options))] if options else centre


def spawn_people(world: World, tick: int = 0) -> None:
    """Create the four players (with 3 villagers each) and the 38 wandering villagers."""
    cfg = world.cfg.balance
    rng = world.streams.get("people.spawn")
    names = cfg.turn.player_dummy_names
    for index in range(1, 5):
        pid = player_id(index)
        home = world.homes[index - 1]
        p = Player(pid, index, names[index - 1], home.anchor[0], home.anchor[1])
        p.inventory = world.new_inventory()
        p.home_store = world.new_inventory()
        p.slots = cfg.tasks.slots_start
        p.band = "all_right"
        world.players[pid] = p
    for p in world.players.values():
        for other in world.players:
            if other != p.id:
                p.trust[other] = cfg.wellbeing.start_trust
                p.anger[other] = cfg.wellbeing.anger_neutral
    vcfg = cfg.villagers
    jobs = ["gather", "farm", "gather"]
    counter = 0
    for index in range(1, 5):
        home = world.homes[index - 1]
        for slot in range(vcfg.per_player):
            pos = free_tile_near(world, rng, home.anchor, cfg.turn.start_anchor_spread)
            v = _new_villager(world, counter, pid=player_id(index), pos=pos)
            v.job = jobs[slot % len(jobs)]
            v.job_x, v.job_y = home.anchor
            counter += 1
    wild = vcfg.total - vcfg.per_player * 4
    for _ in range(wild):
        zone = "centre" if rng.random() < 0.4 else "buffer"
        pos = world.random_tile(rng, zone, ["grass", "sand"])
        if pos is None:
            pos = world.homes[0].anchor
        _new_villager(world, counter, pid=None, pos=pos)
        counter += 1


def _new_villager(world: World, counter: int, pid: str | None, pos: Pos) -> Villager:
    vcfg = world.cfg.balance.villagers
    vid = f"villager_{world.next('villager')}"
    v = Villager(vid, vcfg.names[counter % len(vcfg.names)], pid, pos[0], pos[1])
    v.inventory = world.new_inventory()
    v.loyalty = vcfg.start_loyalty
    if pid is not None:
        v.bond[pid] = vcfg.bond_start_leader
    world.villagers[vid] = v
    return v


# ---------------------------------------------------------------------------------- walking


def make_route(world: World, start: Pos, goal: Pos) -> list[Pos] | None:
    return astar(world.cost_grid(), start, goal)


def route_to_reach(world: World, start: Pos, target: Pos, reach: int) -> list[Pos] | None:
    """A route that ends within ``reach`` (Manhattan) of ``target``; [start] if already there."""
    if abs(start[0] - target[0]) + abs(start[1] - target[1]) <= reach:
        return [start]
    if world.inside(*target) and world.passable(*target):
        path = make_route(world, start, target)
        if path is not None:
            return _trim(path, target, reach)
    best: list[Pos] | None = None
    for dx, dy in NEIGHBOUR_STEPS:
        spot = (target[0] + dx, target[1] + dy)
        if not world.inside(*spot) or not world.passable(*spot):
            continue
        path = make_route(world, start, spot)
        if path is not None and (best is None or len(path) < len(best)):
            best = path
    return best


def _trim(path: list[Pos], target: Pos, reach: int) -> list[Pos]:
    for i, (x, y) in enumerate(path):
        if abs(x - target[0]) + abs(y - target[1]) <= reach:
            return path[: i + 1]
    return path


def step_duration(world: World, actor: Walker, dest: Pos, base: float) -> int:
    from ai_island.rules import wellbeing

    cost = world.cfg.world.terrain.cost.get(world.terrain[dest[1]][dest[0]], 1.0)
    if dest in world.bridges:
        cost = world.cfg.world.terrain.cost["grass"]
    speed = wellbeing.speed_mult(world, actor) if isinstance(actor, Player) else 1.0
    if actor.body.sickness:
        speed *= world.cfg.balance.body.sickness[actor.body.sickness].work_penalty
    return step_minutes(base * cost / speed)


def advance_walk(
    world: World, actor: Walker, route: list[Pos], index: int, tick: int, base: float
) -> tuple[str, int]:
    """Move one tick along ``route`` (route[index] is the current tile).

    Returns (state, new index) with state "walking" or "arrived".
    """
    if is_stepping(actor):
        if not complete_step(actor, tick):
            return "walking", index
        index += 1
    if index >= len(route) - 1:
        return "arrived", index
    dest = route[index + 1]
    if not world.passable(*dest):
        return "arrived", len(route) - 1
    begin_step(actor, dest, tick, step_duration(world, actor, dest, base))
    return "walking", index
