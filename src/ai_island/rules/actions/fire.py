"""Fire: campfires and hearths, fuel, cooking, spoilage, light and warmth sweeps."""

from __future__ import annotations

from ai_island.rules.actions import core
from ai_island.rules.actions.core import Plan, Spec, register
from ai_island.rules.actions.request import ActionRequest
from ai_island.storage.events import StructureBuilt
from ai_island.world.agents import ActiveAction, Player, Structure
from ai_island.world.state import Pos, World

FIRE_KINDS = ("campfire", "hearth")


def burning_fires(world: World, tick: int) -> list[Structure]:
    return sorted(
        (s for s in world.structures.values() if s.kind in FIRE_KINDS and s.burning(tick)),
        key=lambda s: s.id,
    )


def fire_near(world: World, pos: Pos, radius: int, tick: int) -> Structure | None:
    r2 = radius * radius
    for s in burning_fires(world, tick):
        if (s.x - pos[0]) ** 2 + (s.y - pos[1]) ** 2 <= r2:
            return s
    return None


def _existing_fire(world: World, p: Player, pos: Pos) -> Structure | None:
    best = None
    for s in sorted(world.structures.values(), key=lambda q: q.id):
        if s.kind in FIRE_KINDS and s.complete and core.manhattan((s.x, s.y), pos) <= 1:
            if s.owner == p.id or s.owner in p.allies:
                best = best or s
    return best


def _fire_begin(world: World, p: Player, req: ActionRequest, tick: int):
    cfg = world.cfg.balance.fire
    spot: Pos = (p.x, p.y) if req.x is None or req.y is None else (req.x, req.y)
    if not world.inside(*spot) or not world.passable(*spot):
        return "blocked"
    existing = _existing_fire(world, p, spot)
    if existing is not None:
        cost = {"wood": cfg.refuel_wood}
        if existing.kind == "campfire" and world.weather.flags.puts_out_campfires:
            return "too_wet"
        if not core.pay(world, p, cost):
            return "missing_wood"
        return Plan(goal=(existing.x, existing.y), data={"fire": existing.id, "reserved": cost})
    if world.weather.flags.puts_out_campfires:
        return "too_wet"
    if core.structure_at(world, spot) is not None:
        return "occupied"
    if not core.free_to_use(world, p, spot):
        return "not_your_land"
    cost = {"wood": cfg.campfire_wood}
    if not core.pay(world, p, cost):
        return "missing_wood"
    return Plan(goal=spot, reach=0, data={"spot": list(spot), "reserved": cost})


def _fire_unit(world: World, p: Player, act: ActiveAction, tick: int) -> str:
    cfg = world.cfg.balance
    if "fire" in act.data:
        fire = world.structures.get(act.data["fire"])
        if fire is None:
            return "fail:gone"
        fire.fuel_until = tick + cfg.fire.fuel_ticks
        act.data["reserved"] = {}
        return "done"
    x, y = act.data["spot"]
    if core.structure_at(world, (x, y)) is not None:
        return "fail:occupied"
    sid = world.next("structure")
    hp = cfg.buildings.hp["campfire"]
    s = Structure(sid, "campfire", x, y, p.id, hp, hp, True, 1.0, {p.id: 1}, None,
                  tick + cfg.fire.fuel_ticks)  # fmt: skip
    world.structures[sid] = s
    world.emit(StructureBuilt(id=sid, kind="campfire", owner=p.id, x=x, y=y), tick)
    act.data["reserved"] = {}
    return "done"


def _cook_begin(world: World, p: Player, req: ActionRequest, tick: int):
    if p.inventory.count("raw_meat") == 0:
        return "no_raw_meat"
    fires = burning_fires(world, tick)
    if not fires:
        return "no_fire"
    near = min(fires, key=lambda s: (core.manhattan((s.x, s.y), (p.x, p.y)), s.id))
    if core.manhattan((near.x, near.y), (p.x, p.y)) > 30:
        return "no_fire"
    want = req.amount or world.cfg.balance.actions.default_amount
    return Plan(goal=(near.x, near.y), reach=2, data={"left": want})


def _cook_unit(world: World, p: Player, act: ActiveAction, tick: int) -> str:
    if fire_near(world, (p.x, p.y), 2, tick) is None:
        return "fail:no_fire"
    if not p.inventory.remove("raw_meat", 1):
        return "fail:no_raw_meat"
    p.inventory.add("cooked_meat", 1, tick)
    act.data["left"] -= 1
    if act.data["left"] <= 0 or p.inventory.count("raw_meat") == 0:
        return "done"
    return "more"


register(Spec("make_fire", _fire_begin, _fire_unit, None, True, True))
register(Spec("cook", _cook_begin, _cook_unit, None, False, True))


# ------------------------------------------------------------------------------ sweeps


def sweep_fires(world: World, tick: int) -> None:
    """Rain and storms put out campfires (never hearths)."""
    if not world.weather.flags.puts_out_campfires:
        return
    for s in world.structures.values():
        if s.kind == "campfire" and s.fuel_until > tick:
            s.fuel_until = tick


def _all_inventories(world: World):
    for p in world.players.values():
        yield p.inventory
        yield p.home_store
    for v in world.villagers.values():
        yield v.inventory
    for s in world.structures.values():
        if s.store is not None:
            yield s.store
    yield from world.drops.values()


def sweep_spoilage(world: World, tick: int) -> None:
    for inv in _all_inventories(world):
        inv.spoil(tick)
