"""Villagers: needs, jobs, work levels, loyalty and bond, leaving, and daily bookkeeping.

Villagers are simple rule-driven people (no AI). 50 exist from tick 0; nothing creates more.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ai_island.storage.events import VillagerLeft
from ai_island.world import movement, people, plants, resources
from ai_island.world.agents import Villager
from ai_island.world.clock import is_night_at
from ai_island.world.state import Pos, World

if TYPE_CHECKING:
    from ai_island.rules.body import Env

SAFE_FOOD = ("cooked_meat", "fish", "crops", "eggs", "roots", "milk", "berries", "mushrooms")
FORAGE_KINDS = ("berries", "mushrooms", "roots", "herbs")
WORK_FOOD_PLANTS = ("berries", "mushrooms", "roots", "herbs")


def home_anchor(world: World, v: Villager) -> Pos | None:
    if v.leader is None:
        return None
    return world.homes[world.players[v.leader].index - 1].anchor


def _near_home(world: World, v: Villager) -> bool:
    anchor = home_anchor(world, v)
    if anchor is None:
        return False
    r = world.cfg.balance.villagers.home_radius
    return abs(v.x - anchor[0]) + abs(v.y - anchor[1]) <= r


def eat_from(world: World, v: Villager, inv, floor: float = 20.0) -> None:
    cfg = world.cfg.balance
    for kind in SAFE_FOOD:
        while v.body.hunger > floor and inv.count(kind):
            inv.remove(kind, 1)
            v.body.hunger = max(
                0.0, v.body.hunger - cfg.food.values[kind] * cfg.body.hunger_per_food_unit
            )


def forage(world: World, v: Villager, tick: int, zone: str | None = None) -> None:
    """A villager eats a plant nearby (an attached one only in its leader's home zone)."""
    cfg = world.cfg.balance
    r = cfg.villagers.forage_radius
    best = None
    for s in world.plants:
        if (
            s.present
            and s.kind in FORAGE_KINDS
            and (zone is None or world.zone_at(s.x, s.y) == zone)
        ):
            d = abs(s.x - v.x) + abs(s.y - v.y)
            if d <= r and (best is None or (d, s.id) < best[0]):
                best = ((d, s.id), s)
    if best is None:
        if zone is not None:
            _hunt_for_food(world, v, zone, tick)
        return
    site = best[1]
    plants.remove_plant(world, (site.x, site.y), tick)
    v.body.hunger = max(
        0.0, v.body.hunger - cfg.food.values[site.kind] * 2 * cfg.body.hunger_per_food_unit
    )


def _hunt_for_food(world: World, v: Villager, zone: str, tick: int) -> None:
    """With no plants left, an attached villager takes a small wild animal from the home zone."""
    from ai_island.world import animals as animals_mod

    cfg = world.cfg.balance
    best = None
    for kind, group in world.animals.items():
        if kind == "fish" or kind not in cfg.actions.hunt_yield:
            continue
        for a in group:
            if a.zone == zone and not a.pen:
                key = (cfg.actions.hunt_yield[kind], a.id)
                if best is None or key < best[0]:
                    best = (key, a)
    if best is None:
        return
    animals_mod.remove_animal(world, best[1], tick)
    units = cfg.food.values["raw_meat"] * best[0][0]
    v.body.hunger = max(0.0, v.body.hunger - units * cfg.body.hunger_per_food_unit)


def update_villager_body(world: World, env: Env, v: Villager, tick: int, dt: int) -> None:
    from ai_island.rules import body

    cfg = world.cfg.balance
    vc = cfg.villagers
    cause = body.step_needs(world, env, v, tick, dt)
    if cause is not None:
        body.kill_villager(world, v, cause, tick)
        return
    b = v.body
    day = world.cfg.world.clock.ticks_per_day
    f = dt / day
    leader = world.players.get(v.leader or "")
    if v.leader is None:
        b.hunger = max(0.0, b.hunger - vc.wanderer_land_food_per_day * f)
        if b.hunger > 45:
            forage(world, v, tick)
    else:
        if b.thirst > 40 and _near_home(world, v):
            b.thirst = max(0.0, b.thirst - 20 * world.weather.flags.water_multiplier)
        if b.hunger > 40 and leader is not None and _near_home(world, v):
            eat_from(world, v, leader.home_store)
        if b.hunger > 40:
            eat_from(world, v, v.inventory)
        if b.hunger > 45 and leader is not None and _near_home(world, v):
            forage(world, v, tick, f"home_{leader.index - 1}")
    hungry = max(b.hunger, b.thirst, b.cold) >= vc.comfort_level
    if hungry:
        v.hungry_minutes += dt
    working_hard = v.work_level == "hard" and v.job is not None and v.leader is not None
    if working_hard:
        v.hard_minutes += dt
        b.health = max(0.0, b.health - vc.hard_health_loss_per_hour * dt / 60)
        if b.health <= 0:
            body.kill_villager(world, v, "overwork", tick)
            return
    if v.leader is None:
        return
    comfortable = not hungry and b.health > 50
    if v.captive:
        v.loyalty -= vc.captive_loyalty_loss_per_day * f
    elif not comfortable:
        v.loyalty -= vc.unfed_loyalty_loss_per_day * f
    elif not working_hard:
        v.loyalty += vc.fed_loyalty_gain_per_day * f
        if v.work_level == "light":
            v.loyalty += vc.light_loyalty_gain_per_day * f
    if working_hard:
        v.loyalty -= vc.hard_loyalty_loss_per_day * f
    v.loyalty = min(100.0, max(0.0, v.loyalty))
    if leader is not None:
        cur = v.bond.get(v.leader, vc.bond_start_other)
        delta = vc.bond_gain_per_day * f if comfortable else -vc.bond_loss_per_day * f
        v.bond[v.leader] = min(100.0, max(0.0, cur + delta))
    if v.loyalty < vc.leave_below:
        leave(world, v, tick)


def leave(world: World, v: Villager, tick: int) -> None:
    """A villager with low loyalty goes to the player it likes best, or wanders off."""
    from ai_island.rules.actions import social

    vc = world.cfg.balance.villagers
    old = v.leader
    best: str | None = None
    best_bond = max(vc.bond_start_other + 20, v.bond.get(old or "", 0.0))
    for pid in sorted(world.players):
        if pid == old or not world.players[pid].alive:
            continue
        attached = sum(1 for q in world.villagers.values() if q.leader == pid)
        if attached >= world.players[pid].slots:
            continue
        bond = v.bond.get(pid, vc.bond_start_other)
        if bond > best_bond:
            best, best_bond = pid, bond
    world.emit(
        VillagerLeft(
            villager=v.id, leader=old or "", to=best, reason="low_loyalty",
            hungry_days=v.adverse_days.get("hunger", 0), hard_days=v.adverse_days.get("hard", 0),
        ),
        tick,
    )  # fmt: skip
    v.adverse_days = {}
    v.hungry_minutes = v.hard_minutes = 0
    if best is not None:
        social.attach(world, v, best, tick, "left", vc.recruit_loyalty)
    else:
        v.leader = None
        v.loyalty = vc.start_loyalty
        v.job = None
        v.work_level = "normal"
        v.captive = False
        v.captor = None
        v.route, v.route_index = [], 0


# ------------------------------------------------------------------------------- the phase


def _walk(world: World, v: Villager, tick: int) -> None:
    if not v.route:
        if movement.is_stepping(v):
            movement.complete_step(v, tick)
        return
    state, v.route_index = people.advance_walk(
        world, v, v.route, v.route_index, tick, world.cfg.balance.villagers.walk_minutes_per_tile
    )
    if state == "arrived":
        v.route, v.route_index = [], 0


def _go(world: World, v: Villager, goal: Pos) -> bool:
    if (v.x, v.y) == goal:
        return True
    route = people.route_to_reach(world, (v.x, v.y), goal, 0)
    if route is None or len(route) < 2:
        return False
    v.route, v.route_index = route, 0
    return False


def run_villagers(world: World, tick: int) -> None:
    """Walk every villager one tick; every ``think_ticks`` let each one decide."""
    vc = world.cfg.balance.villagers
    for v in sorted(world.villagers.values(), key=lambda q: q.id):
        if not v.alive:
            continue
        _walk(world, v, tick)
        if tick >= v.next_think and not v.route and not movement.is_stepping(v):
            v.next_think = tick + vc.think_ticks
            think(world, v, tick)


def think(world: World, v: Villager, tick: int) -> None:
    vc = world.cfg.balance.villagers
    rng = world.streams.get("villagers")
    if v.leader is None:
        if rng.random() < vc.wander_chance:
            dx, dy = (
                rng.randint(-vc.wander_radius, vc.wander_radius),
                rng.randint(-vc.wander_radius, vc.wander_radius),
            )
            goal = (v.x + dx, v.y + dy)
            if (
                world.inside(*goal)
                and world.passable(*goal)
                and world.zone_type(world.zone_at(*goal)) != "home"
            ):
                _go(world, v, goal)
        return
    leader = world.players.get(v.leader)
    if leader is None:
        return
    anchor = world.homes[leader.index - 1].anchor
    if v.captive:
        _go(world, v, anchor)
        return
    clock = world.cfg.world.clock
    if is_night_at(tick, clock) or v.job is None:
        if abs(v.x - anchor[0]) + abs(v.y - anchor[1]) > 2:
            _go(world, v, anchor)
        return
    produce(world, v, leader, tick)


def produce(world: World, v: Villager, leader, tick: int) -> None:
    """One think step of a working villager: walk to the job, output once per cycle."""
    vc = world.cfg.balance.villagers
    acts = world.cfg.balance.actions
    mult = vc.output_mult[v.work_level]
    from ai_island.rules import wellbeing

    sick = world.cfg.balance.body.sickness[v.body.sickness].work_penalty if v.body.sickness else 1.0
    v.work_acc += vc.think_ticks * mult * sick
    if v.work_acc < vc.cycle_ticks:
        if v.job == "guard":
            return
        center = (v.job_x, v.job_y) if v.job_x >= 0 else home_anchor(world, v)
        if center is not None and abs(v.x - center[0]) + abs(v.y - center[1]) > vc.job_radius:
            _go(world, v, center)
        return
    v.work_acc -= vc.cycle_ticks
    anchor = world.homes[leader.index - 1].anchor
    r = vc.job_radius
    home_zone = f"home_{leader.index - 1}"
    store = leader.home_store

    def near_home(x: int, y: int) -> bool:
        return abs(x - anchor[0]) + abs(y - anchor[1]) <= r and world.zone_at(x, y) == home_zone

    if v.job == "gather":
        best = None
        for s in world.plants:
            if s.present and s.kind in WORK_FOOD_PLANTS and near_home(s.x, s.y):
                d = abs(s.x - v.x) + abs(s.y - v.y)
                if best is None or (d, s.id) < best[0]:
                    best = ((d, s.id), s)
        if best is not None:
            s = best[1]
            plants.remove_plant(world, (s.x, s.y), tick)
            store.add(s.kind, acts.gather_yield[s.kind], tick)
            _step_near(world, v, (s.x, s.y))
            return
        tree = _nearest_tile(
            world, anchor, r, lambda x, y: world.terrain[y][x] == "tree" and near_home(x, y), v
        )
        if tree is not None:
            resources.cut_tree(world, tree, tick)
            store.add("wood", acts.gather_yield["wood"], tick)
            _step_near(world, v, tree)
    elif v.job == "farm":
        spot = _nearest_tile(
            world,
            anchor,
            r,
            lambda x, y: world.terrain[y][x] == "farmland_ready" and near_home(x, y),
            v,
        )
        if spot is not None:
            resources.harvest_crop(world, spot, tick)
            store.add("crops", acts.crop_yield, tick)
        else:
            spot = _nearest_tile(
                world,
                anchor,
                r,
                lambda x, y: world.terrain[y][x] == "farmland_empty" and near_home(x, y),
                v,
            )
            if spot is not None:
                resources.plant_crop(world, spot, tick)
        if spot is not None:
            _step_near(world, v, spot)
    elif v.job == "build":
        from ai_island.rules.actions import build as build_mod

        todo = sorted(
            (s for s in world.structures.values() if not s.complete and s.owner == leader.id),
            key=lambda s: s.id,
        )
        if todo:
            s = todo[0]
            build_mod.contribute(world, s, leader.id, tick, acts.unit_minutes["build"] * mult)
            _step_near(world, v, (s.x, s.y))
    _ = wellbeing


def _nearest_tile(world: World, centre: Pos, radius: int, pred, v: Villager) -> Pos | None:
    best = None
    for y in range(max(0, centre[1] - radius), min(world.height, centre[1] + radius + 1)):
        for x in range(max(0, centre[0] - radius), min(world.width, centre[0] + radius + 1)):
            if pred(x, y):
                d = abs(x - v.x) + abs(y - v.y)
                if best is None or (d, y, x) < best:
                    best = (d, y, x)
    return None if best is None else (best[2], best[1])


def _step_near(world: World, v: Villager, goal: Pos) -> None:
    """Walk toward the place just worked (a short, cheap route)."""
    if abs(v.x - goal[0]) + abs(v.y - goal[1]) > 1:
        route = people.route_to_reach(world, (v.x, v.y), goal, 1)
        if route is not None and len(route) > 1:
            v.route, v.route_index = route, 0


# ------------------------------------------------------------------------------- daily


def consume_food(inv, units: float, values: dict[str, float]) -> bool:
    """Remove roughly ``units`` of food value from ``inv``; False if there is not enough."""
    need = units
    if inv.food_units(values) < units:
        return False
    for kind in SAFE_FOOD:
        while need > 0 and inv.count(kind):
            inv.remove(kind, 1)
            need -= values[kind]
    return True


def daily(world: World, tick: int) -> None:
    """Once per game day: adverse-day tallies, pen upkeep, eggs and milk."""
    vc = world.cfg.balance.villagers
    acts = world.cfg.balance.actions
    for v in sorted(world.villagers.values(), key=lambda q: q.id):
        if v.hungry_minutes >= 360:
            v.adverse_days["hunger"] = v.adverse_days.get("hunger", 0) + 1
        if v.hard_minutes >= 360:
            v.adverse_days["hard"] = v.adverse_days.get("hard", 0) + 1
        v.hungry_minutes = v.hard_minutes = 0
        _ = vc
    missed = world.counters.setdefault("pen_missed", {})
    for kind in acts.tame_kinds:
        for a in list(world.animals[kind]):
            if not a.pen:
                continue
            owner = world.players.get(a.owner)
            if owner is None:
                continue
            if consume_food(owner.home_store, acts.pen_upkeep_food, world.cfg.balance.food.values):
                missed.pop(str(a.id), None)
                tender = any(
                    v.leader == owner.id and v.job == "tend_animals"
                    for v in world.villagers.values()
                )
                if tender and a.kind == "chicken":
                    owner.home_store.add("eggs", acts.egg_per_day, tick)
                elif tender and a.kind == "goat":
                    owner.home_store.add("milk", acts.milk_per_day, tick)
            else:
                missed[str(a.id)] = missed.get(str(a.id), 0) + 1
                if missed[str(a.id)] >= acts.pen_missed_days:
                    a.owner, a.pen = "", 0
                    a.next_move_tick = tick + 1
                    movement._push(world, a)
                    missed.pop(str(a.id), None)
