"""Body and care actions: eat, drink, rest, move, use_herb, store."""

from __future__ import annotations

from ai_island.rules import body
from ai_island.rules.actions import core
from ai_island.rules.actions.core import Plan, Spec, register
from ai_island.rules.actions.request import ActionRequest
from ai_island.storage.events import ItemsMoved
from ai_island.world.agents import ActiveAction, Player, transfer_items
from ai_island.world.state import World

SAFE_ORDER = (
    "cooked_meat", "fish", "crops", "eggs", "roots", "milk", "berries", "mushrooms", "herbs",
)  # fmt: skip


def _food_sources(world: World, p: Player):
    return [p.inventory, *core.reachable_stores(world, p)]


def _pick_food(world: World, p: Player, item: str | None) -> str | None:
    values = world.cfg.balance.food.values
    sources = _food_sources(world, p)
    kinds = [item] if item else list(SAFE_ORDER)
    for kind in kinds:
        if kind in values and any(s.count(kind) for s in sources):
            return kind
    return None


# ----------------------------------------------------------------------------------- eat


def _eat_begin(world: World, p: Player, req: ActionRequest, tick: int):
    values = world.cfg.balance.food.values
    if req.item is not None and req.item not in values:
        return "not_food"
    if _pick_food(world, p, req.item) is None:
        return "no_food"
    amount = req.amount or (
        None if req.until == "sated" else world.cfg.balance.actions.default_amount
    )
    return Plan(data={"item": req.item, "left": amount, "eaten": 0})


def _eat_unit(world: World, p: Player, act: ActiveAction, tick: int) -> str:
    cfg = world.cfg.balance
    item = _pick_food(world, p, act.data["item"])
    if item is None:
        return "no_food" if act.data["eaten"] == 0 else "done"
    for src in _food_sources(world, p):
        if src.count(item):
            src.remove(item, 1)
            break
    value = cfg.food.values[item]
    p.body.hunger = max(0.0, p.body.hunger - value * cfg.body.hunger_per_food_unit)
    act.data["eaten"] += 1
    sick = cfg.food.sick_on_eat.get(item)
    if sick is not None:
        body.apply_sickness(world, p, sick, tick)
    left = act.data["left"]
    if left is not None:
        act.data["left"] = left - 1
        if act.data["left"] <= 0:
            return "done"
    if act.request.until == "sated" and p.body.hunger <= cfg.body.sated_level:
        return "done"
    if _pick_food(world, p, act.data["item"]) is None:
        return "done"
    return "more"


# --------------------------------------------------------------------------------- drink


def _is_water(world: World, x: int, y: int) -> bool:
    return world.terrain[y][x] in ("spring", "lake")


def _drink_begin(world: World, p: Player, req: ActionRequest, tick: int):
    amount = req.amount or (
        None if req.until == "sated" else world.cfg.balance.actions.default_amount
    )
    data = {"left": amount, "drunk": 0}
    if req.x is None and p.inventory.count("water") > 0:
        return Plan(data={**data, "source": "pack"})
    if req.x is not None and req.y is not None:
        if not world.inside(req.x, req.y) or not _is_water(world, req.x, req.y):
            return "no_water_there"
        spot = (req.x, req.y)
    else:
        spot = core.find_nearest(world, (p.x, p.y), lambda x, y: _is_water(world, x, y), 40)
        if spot is None:
            return "no_water"
    return Plan(goal=spot, data={**data, "source": "spring"})


def _drink_unit(world: World, p: Player, act: ActiveAction, tick: int) -> str:
    cfg = world.cfg.balance
    if act.data["source"] == "pack":
        if p.inventory.count("water") == 0:
            return "done" if act.data["drunk"] else "fail:no_water"
        p.inventory.remove("water", 1)
        p.body.thirst = max(0.0, p.body.thirst - cfg.body.thirst_per_water)
    else:
        mult = world.weather.flags.water_multiplier
        p.body.thirst = max(0.0, p.body.thirst - 2 * cfg.body.thirst_per_water * mult)
    act.data["drunk"] += 1
    left = act.data["left"]
    if left is not None:
        act.data["left"] = left - 1
        if act.data["left"] <= 0:
            return "done"
    if act.request.until == "sated" and p.body.thirst <= cfg.body.sated_level:
        return "done"
    if act.data["source"] == "pack" and p.inventory.count("water") == 0:
        return "done"
    return "more"


# ------------------------------------------------------------------------------ rest, move


def _rest_begin(world: World, p: Player, req: ActionRequest, tick: int):
    minutes = req.minutes
    if minutes is None and req.until is None:
        minutes = 60
    return Plan(data={"minutes": minutes, "until": req.until, "slept": 0})


def _rest_unit(world: World, p: Player, act: ActiveAction, tick: int) -> str:
    chunk = world.cfg.balance.actions.rest_chunk_minutes
    act.data["slept"] += chunk
    clock = world.cfg.world.clock
    hour = (tick % clock.ticks_per_day) * 24 // clock.ticks_per_day
    p.sleeping = hour >= clock.night_start_hour or hour < clock.night_end_hour
    until = act.data["until"]
    if until == "rested" and p.body.fatigue <= 5:
        return "done"
    if until == "morning" and hour == clock.night_end_hour and act.data["slept"] > chunk:
        return "done"
    minutes = act.data["minutes"]
    if minutes is not None and act.data["slept"] >= minutes:
        return "done"
    if until == "sated":
        return "done"
    return "more"


def _move_begin(world: World, p: Player, req: ActionRequest, tick: int):
    if req.x is None or req.y is None:
        return "needs_destination"
    if not world.inside(req.x, req.y) or not world.passable(req.x, req.y):
        return "blocked"
    return Plan(goal=(req.x, req.y), reach=0, instant=True)


def _never(world: World, p: Player, act: ActiveAction, tick: int) -> str:
    return "done"


# ---------------------------------------------------------------------------- herbs, store


def _herb_begin(world: World, p: Player, req: ActionRequest, tick: int):
    item = req.item or ("healing_herbs" if p.inventory.count("healing_herbs") else "herbs")
    if item not in ("herbs", "healing_herbs") or p.inventory.count(item) == 0:
        return "no_herbs"
    target = req.target or p.id
    who = world.players.get(target) or world.villagers.get(target)
    if who is None or not who.alive:
        return "no_such_target"
    plan = Plan(data={"item": item, "target": target})
    if target != p.id:
        plan.goal = (who.x, who.y)
        plan.reach = 1
    return plan


def _herb_unit(world: World, p: Player, act: ActiveAction, tick: int) -> str:
    cfg = world.cfg.balance.body
    who = world.players.get(act.data["target"]) or world.villagers.get(act.data["target"])
    if who is None or not who.alive:
        return "fail:no_such_target"
    if core.manhattan((p.x, p.y), (who.x, who.y)) > 1 and who.id != p.id:
        return "fail:too_far"
    item = act.data["item"]
    if not p.inventory.remove(item, 1):
        return "fail:no_herbs"
    before = (who.body.health, who.body.pain, who.body.sickness)
    if item == "healing_herbs":
        body.cure_sickness(who)
        who.body.pain = max(0.0, who.body.pain - cfg.healing_herb_pain_relief)
    else:
        who.body.pain = max(0.0, who.body.pain - cfg.herb_pain_relief)
    who.body.health = min(100.0, who.body.health + cfg.herb_health)
    if who.id != p.id and (
        who.body.health > before[0] or who.body.pain < before[1] or who.body.sickness != before[2]
    ):
        core.note_helped(world, p, act, who.id, "use_herb", tick)
    return "done"


def _store_begin(world: World, p: Player, req: ActionRequest, tick: int):
    stores = core.storage_points(world, p)
    target = None
    if req.structure is not None:
        stores = [(pos, inv) for pos, inv in stores if _structure_id(world, pos) == req.structure]
    if not stores:
        return "no_store"
    best = min(stores, key=lambda s: core.manhattan(s[0], (p.x, p.y)))
    target = best[0]
    if req.item is not None and p.inventory.count(req.item) == 0:
        return "nothing_to_store"
    if req.item is None and p.inventory.total_items() == 0:
        return "nothing_to_store"
    return Plan(
        goal=target, reach=world.cfg.balance.actions.store_radius, data={"store": list(target)}
    )


def _structure_id(world: World, pos) -> str:
    s = core.structure_at(world, pos)
    return "home_store" if s is None else str(s.id)


def _store_unit(world: World, p: Player, act: ActiveAction, tick: int) -> str:
    req = act.request
    pos = tuple(act.data["store"])
    dst = None
    for spos, inv in core.storage_points(world, p):
        if spos == pos:
            dst = inv
    if dst is None:
        return "fail:no_store"
    if core.manhattan((p.x, p.y), pos) > world.cfg.balance.actions.store_radius:
        return "fail:too_far"
    items = (
        {req.item: min(req.amount or 10**6, p.inventory.count(req.item))}
        if req.item
        else p.inventory.counts()
    )
    items = {k: n for k, n in items.items() if n > 0}
    if not items:
        return "fail:nothing_to_store"
    if not transfer_items(world, p.inventory, dst, items, []):
        return "fail:blocked"
    world.emit(ItemsMoved(kind="store", src=p.id, dst=_structure_id(world, pos), items=items), tick)
    return "done"


register(Spec("eat", _eat_begin, _eat_unit, physical=False))
register(Spec("drink", _drink_begin, _drink_unit, physical=False))
register(Spec("rest", _rest_begin, _rest_unit, physical=False))
register(Spec("move", _move_begin, _never, physical=False))
register(Spec("use_herb", _herb_begin, _herb_unit, physical=False))
register(Spec("store", _store_begin, _store_unit, physical=False))
