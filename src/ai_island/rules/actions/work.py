"""Work actions: gather, farm, fish, hunt, tame, assign_villager."""

from __future__ import annotations

import math

from ai_island.config import PLANT_KINDS
from ai_island.rules import body
from ai_island.rules.actions import core
from ai_island.rules.actions.core import Plan, Spec, register
from ai_island.rules.actions.request import ActionRequest
from ai_island.world import animals as animals_mod
from ai_island.world import movement, plants, resources
from ai_island.world.agents import JOBS, WORK_LEVELS, ActiveAction, Player
from ai_island.world.state import Animal, Pos, World

# ---------------------------------------------------------------------------------- gather


def _plant_at(world: World, pos: Pos):
    for site in world.plants:
        if site.present and (site.x, site.y) == pos:
            return site
    return None


def _tile_item(world: World, pos: Pos) -> str | None:
    x, y = pos
    t = world.terrain[y][x]
    if t == "tree":
        return "wood"
    if t in ("rocky", "quarry") and world.stone.get(pos, 0) > 0:
        return "stone"
    if t in ("spring", "lake"):
        return "water"
    site = _plant_at(world, pos)
    return None if site is None else site.kind


def _has_item(world: World, p: Player, item: str, pos: Pos) -> bool:
    x, y = pos
    if not world.inside(x, y):
        return False
    got = _tile_item(world, pos)
    if got != item:
        return False
    if item == "stone" and world.terrain[y][x] == "quarry":
        return p.inventory.find_tool("pickaxe") is not None
    return True


def _find_item(world: World, p: Player, item: str) -> Pos | None:
    if item in PLANT_KINDS:
        present = {(s.x, s.y) for s in world.plants if s.present and s.kind == item}
        return core.find_nearest(world, (p.x, p.y), lambda x, y: (x, y) in present, 40)
    return core.find_nearest(world, (p.x, p.y), lambda x, y: _has_item(world, p, item, (x, y)), 40)


_TOOL_FOR = {"wood": "axe", "stone": "pickaxe"}


def _gather_begin(world: World, p: Player, req: ActionRequest, tick: int):
    item = req.item
    spot: Pos | None = None
    if req.x is not None and req.y is not None:
        spot = (req.x, req.y)
        if not world.inside(*spot):
            return "off_map"
        found = _tile_item(world, spot)
        if found is None or (item is not None and item != found):
            return "nothing_there"
        item = found
    if item is None:
        return "needs_item"
    if item not in _TOOL_FOR and item not in PLANT_KINDS and item != "water":
        return "cannot_gather"
    if spot is None:
        spot = _find_item(world, p, item)
        if spot is None:
            if item == "stone" and p.inventory.find_tool("pickaxe") is None:
                if core.find_nearest(
                    world, (p.x, p.y), lambda x, y: world.terrain[y][x] == "quarry", 60
                ):
                    return "need_pickaxe"
            return "none_nearby"
    if item == "stone" and world.terrain[spot[1]][spot[0]] == "quarry":
        if p.inventory.find_tool("pickaxe") is None:
            return "need_pickaxe"
    want = req.amount or world.cfg.balance.actions.default_amount
    return Plan(
        goal=spot,
        data={
            "item": item,
            "target": list(spot),
            "want": want,
            "got": 0,
            "tool": _TOOL_FOR.get(item),
        },
    )


def _gather_claim(world: World, p: Player, act: ActiveAction, tick: int) -> str | None:
    if act.data["item"] == "water":
        return None
    return f"tile:{act.data['target'][0]},{act.data['target'][1]}"


def _gather_minutes_key(act: ActiveAction) -> str:
    key = f"gather_{act.data.get('item')}"
    return key


def _gather_unit(world: World, p: Player, act: ActiveAction, tick: int) -> str:
    cfg = world.cfg.balance
    item = act.data["item"]
    spot = (act.data["target"][0], act.data["target"][1])
    if not _has_item(world, p, item, spot):
        return _gather_next(world, p, act, tick, missing=True)
    if core.manhattan((p.x, p.y), spot) > cfg.actions.reach_tiles:
        return _gather_next(world, p, act, tick, missing=False, goal=spot)
    amount = cfg.actions.gather_yield[item]
    if item == "wood":
        resources.cut_tree(world, spot, tick)
    elif item == "stone":
        amount = resources.take_stone(world, spot, amount)
    elif item in PLANT_KINDS:
        plants.remove_plant(world, spot, tick)
    gained = core.give_item(world, p, item, amount, tick)
    kind = _TOOL_FOR.get(item)
    if kind:
        core.wear_tool(world, p, p.inventory.find_tool(kind), tick)
    act.data["got"] += gained
    if gained == 0:
        return "fail:pack_full"
    if act.data["got"] >= act.data["want"]:
        return "done"
    return _gather_next(world, p, act, tick, missing=False)


def _gather_next(
    world: World,
    p: Player,
    act: ActiveAction,
    tick: int,
    missing: bool,
    goal: Pos | None = None,
) -> str:
    """Pick the next source after finishing one (or losing the first)."""
    item = act.data["item"]
    nxt = goal if goal is not None else _find_item(world, p, item)
    if nxt is None or (missing and act.data.get("retries", 0) >= 4):
        return "done" if act.data["got"] else "fail:none_left"
    if missing:
        act.data["retries"] = act.data.get("retries", 0) + 1
    act.data["target"] = list(nxt)
    if core.retarget(world, p, act, nxt, tick):
        return "retarget"
    return "done" if act.data["got"] else "fail:unreachable"


# ----------------------------------------------------------------------------------- farm


def _farm_wants(world: World, p: Player, mode: str | None):
    def ready(x: int, y: int) -> bool:
        return world.terrain[y][x] == "farmland_ready" and core.free_to_use(world, p, (x, y))

    def empty(x: int, y: int) -> bool:
        return world.terrain[y][x] == "farmland_empty" and core.free_to_use(world, p, (x, y))

    if mode == "harvest":
        return ready
    if mode == "sow":
        return empty
    return lambda x, y: ready(x, y) or empty(x, y)


def _farm_begin(world: World, p: Player, req: ActionRequest, tick: int):
    mode = req.item
    if mode not in (None, "sow", "harvest"):
        return "bad_mode"
    pred = _farm_wants(world, p, mode)
    if req.x is not None and req.y is not None:
        spot = (req.x, req.y) if world.inside(req.x, req.y) and pred(req.x, req.y) else None
    else:
        spot = core.find_nearest(world, (p.x, p.y), pred, 40)
    if spot is None:
        return "no_field"
    want = req.amount or world.cfg.balance.actions.default_amount
    return Plan(goal=spot, data={"mode": mode, "target": list(spot), "want": want, "done": 0})


def _farm_claim(world: World, p: Player, act: ActiveAction, tick: int) -> str | None:
    return f"tile:{act.data['target'][0]},{act.data['target'][1]}"


def _farm_unit(world: World, p: Player, act: ActiveAction, tick: int) -> str:
    cfg = world.cfg.balance.actions
    spot = (act.data["target"][0], act.data["target"][1])
    pred = _farm_wants(world, p, act.data["mode"])
    if not pred(*spot):
        return _farm_next(world, p, act, tick)
    if core.manhattan((p.x, p.y), spot) > cfg.reach_tiles:
        return _farm_next(world, p, act, tick, goal=spot)
    if world.terrain[spot[1]][spot[0]] == "farmland_ready":
        resources.harvest_crop(world, spot, tick)
        hoe = p.inventory.find_tool("hoe")
        bonus = 0 if hoe is None else cfg.hoe_yield_bonus * (2 if hoe.tier == "better" else 1)
        core.give_item(world, p, "crops", cfg.crop_yield + bonus, tick)
        core.wear_tool(world, p, hoe, tick)
    else:
        resources.plant_crop(world, spot, tick)
        core.wear_tool(world, p, p.inventory.find_tool("hoe"), tick)
    act.data["done"] += 1
    if act.data["done"] >= act.data["want"]:
        return "done"
    return _farm_next(world, p, act, tick)


def _farm_next(
    world: World, p: Player, act: ActiveAction, tick: int, goal: Pos | None = None
) -> str:
    nxt = goal or core.find_nearest(world, (p.x, p.y), _farm_wants(world, p, act.data["mode"]), 40)
    if nxt is None:
        return "done" if act.data["done"] else "fail:no_field"
    act.data["target"] = list(nxt)
    if core.retarget(world, p, act, nxt, tick):
        return "retarget"
    return "done" if act.data["done"] else "fail:unreachable"


# ----------------------------------------------------------------------------------- fish


def _animal_by_id(world: World, ident: int) -> Animal | None:
    for group in world.animals.values():
        for a in group:
            if a.id == ident:
                return a
    return None


def _nearest_animal(
    world: World, origin: Pos, kinds: list[str], radius: int, wild_only: bool = True
) -> Animal | None:
    best: tuple[int, int] | None = None
    found: Animal | None = None
    for kind in kinds:
        for a in world.animals[kind]:
            if wild_only and a.pen:
                continue
            d = abs(a.x - origin[0]) + abs(a.y - origin[1])
            if d <= radius and (best is None or (d, a.id) < best):
                best, found = (d, a.id), a
    return found


def _fish_begin(world: World, p: Player, req: ActionRequest, tick: int):
    fish = _nearest_animal(world, (p.x, p.y), ["fish"], 60)
    if fish is None:
        return "no_fish"
    want = req.amount or world.cfg.balance.actions.default_amount
    return Plan(
        goal=(fish.x, fish.y),
        reach=2,
        data={"want": want, "caught": 0, "tries": 0, "tool": "fishing", "fish": fish.id},
    )


def _fish_target(world: World, p: Player, act: ActiveAction) -> Animal | None:
    return _nearest_animal(world, (p.x, p.y), ["fish"], 4)


def _fish_claim(world: World, p: Player, act: ActiveAction, tick: int) -> str | None:
    cfg = world.cfg.balance.actions
    target = _fish_target(world, p, act)
    act.data["claim_ok"] = False
    if target is None:
        return None
    rod = p.inventory.find_tool("fishing")
    chance = cfg.fish_chance + (cfg.fishing_bonus if rod is not None else 0.0)
    if world.streams.get("actions.fish").random() >= chance:
        return None
    act.data["claim_ok"] = True
    act.data["fish"] = target.id
    return f"animal:{target.id}"


def _fish_unit(world: World, p: Player, act: ActiveAction, tick: int) -> str:
    act.data["tries"] += 1
    if act.data.get("claim_ok"):
        fish = _animal_by_id(world, act.data["fish"])
        if fish is not None and animals_mod.remove_animal(world, fish, tick):
            core.give_item(world, p, "fish", world.cfg.balance.actions.fish_yield, tick)
            act.data["caught"] += 1
            core.wear_tool(world, p, p.inventory.find_tool("fishing"), tick)
    if act.data["caught"] >= act.data["want"]:
        return "done"
    if act.data["tries"] >= act.data["want"] * 4 + 2:
        return "done" if act.data["caught"] else "fail:no_luck"
    if _fish_target(world, p, act) is None:
        other = _nearest_animal(world, (p.x, p.y), ["fish"], 60)
        if other is None:
            return "done" if act.data["caught"] else "fail:no_fish"
        if core.retarget(world, p, act, (other.x, other.y), tick):
            return "retarget"
        return "done" if act.data["caught"] else "fail:unreachable"
    return "more"


# ----------------------------------------------------------------------------------- hunt


def _hunt_kinds(world: World) -> list[str]:
    return [k for k in world.cfg.balance.actions.hunt_chance]


def _pick_prey(world: World, p: Player, req: ActionRequest) -> Animal | None:
    if req.target is not None and req.target.isdigit():
        a = _animal_by_id(world, int(req.target))
        return a if a is not None and not a.pen else None
    kinds = [req.item] if req.item in _hunt_kinds(world) else _hunt_kinds(world)
    return _nearest_animal(world, (p.x, p.y), kinds, 60)


def _hunt_begin(world: World, p: Player, req: ActionRequest, tick: int):
    prey = _pick_prey(world, p, req)
    if prey is None:
        return "no_prey"
    want = req.amount or world.cfg.balance.actions.default_amount
    return Plan(
        goal=(prey.x, prey.y),
        reach=1,
        data={"animal": prey.id, "kind": prey.kind, "want": want, "got": 0, "attempts": 0,
              "chases": 0, "req_item": req.item},
    )  # fmt: skip


def _hunt_claim(world: World, p: Player, act: ActiveAction, tick: int) -> str | None:
    cfg = world.cfg.balance.actions
    act.data["claim_ok"] = False
    act.data["far"] = False
    prey = _animal_by_id(world, act.data["animal"])
    if prey is None:
        return None
    if core.manhattan((p.x, p.y), (prey.x, prey.y)) > 2:
        act.data["far"] = True
        return None
    spear = p.inventory.find_tool("spear")
    chance = cfg.hunt_chance[prey.kind] + (cfg.spear_hunt_bonus if spear else 0.0)
    if world.streams.get("actions.hunt").random() >= min(1.0, chance):
        return None
    act.data["claim_ok"] = True
    return f"animal:{prey.id}"


def _hunt_unit(world: World, p: Player, act: ActiveAction, tick: int) -> str:
    cfg = world.cfg.balance.actions
    prey = _animal_by_id(world, act.data["animal"])
    if prey is None:
        return _hunt_next(world, p, act, tick)
    if act.data.get("far"):
        act.data["chases"] += 1
        if act.data["chases"] > cfg.hunt_retries:
            return "done" if act.data["got"] else "fail:escaped"
        if core.retarget(world, p, act, (prey.x, prey.y), tick):
            return "retarget"
        return "fail:unreachable"
    act.data["attempts"] += 1
    spear = p.inventory.find_tool("spear")
    if prey.kind == "boar":
        chance = cfg.boar_injury_chance * (0.5 if spear else 1.0)
        if world.streams.get("actions.hunt").random() < chance:
            body.hurt(world, p, cfg.boar_injury_health, cfg.boar_injury_pain, "boar", tick)
            if not p.alive or p.action is not act:
                return "retarget"
    if act.data.get("claim_ok") and animals_mod.remove_animal(world, prey, tick):
        n = cfg.hunt_yield[prey.kind]
        core.give_item(world, p, "eggs" if prey.kind == "nest_eggs" else "raw_meat", n, tick)
        core.wear_tool(world, p, spear, tick)
        act.data["got"] += 1
        if act.data["got"] >= act.data["want"]:
            return "done"
        return _hunt_next(world, p, act, tick)
    if act.data["attempts"] >= 6:
        return "done" if act.data["got"] else "fail:missed"
    return "more"


def _hunt_next(world: World, p: Player, act: ActiveAction, tick: int) -> str:
    kinds = [act.data["kind"]]
    prey = _nearest_animal(world, (p.x, p.y), kinds, 60)
    if prey is None:
        return "done" if act.data["got"] else "fail:no_prey"
    act.data["animal"] = prey.id
    act.data["attempts"] = 0
    act.data["chases"] = 0
    if core.retarget(world, p, act, (prey.x, prey.y), tick):
        return "retarget"
    return "done" if act.data["got"] else "fail:unreachable"


# ----------------------------------------------------------------------------------- tame


def _own_pen(world: World, p: Player):
    pens = [
        s for s in world.structures.values() if s.kind == "pen" and s.complete and s.owner == p.id
    ]
    return sorted(pens, key=lambda s: s.id)


def _tame_begin(world: World, p: Player, req: ActionRequest, tick: int):
    cfg = world.cfg.balance.actions
    pens = _own_pen(world, p)
    if not pens:
        return "no_pen"
    if not any(p.inventory.count(b) for b in cfg.tame_bait_items):
        return "no_bait"
    if req.target is not None and req.target.isdigit():
        prey = _animal_by_id(world, int(req.target))
    else:
        kinds = [req.item] if req.item in cfg.tame_kinds else cfg.tame_kinds
        prey = _nearest_animal(world, (pens[0].x, pens[0].y), kinds, cfg.pen_radius + 20)
    if prey is None or prey.pen or prey.kind not in cfg.tame_kinds:
        return "no_prey"
    pen = min(pens, key=lambda s: (core.manhattan((s.x, s.y), (prey.x, prey.y)), s.id))
    if core.manhattan((pen.x, pen.y), (prey.x, prey.y)) > cfg.pen_radius + 20:
        return "pen_too_far"
    return Plan(goal=(prey.x, prey.y), reach=1, data={"animal": prey.id, "pen": pen.id, "wins": 0})


def _tame_unit(world: World, p: Player, act: ActiveAction, tick: int) -> str:
    cfg = world.cfg.balance.actions
    prey = _animal_by_id(world, act.data["animal"])
    pen = world.structures.get(act.data["pen"])
    if prey is None or pen is None or prey.pen:
        return "fail:lost_animal"
    if core.manhattan((p.x, p.y), (prey.x, prey.y)) > 2:
        if core.retarget(world, p, act, (prey.x, prey.y), tick):
            return "retarget"
        return "fail:unreachable"
    bait = next((b for b in cfg.tame_bait_items if p.inventory.count(b)), None)
    if bait is None:
        return "fail:no_bait"
    p.inventory.remove(bait, 1)
    if world.streams.get("actions.tame").random() < cfg.tame_chance:
        act.data["wins"] += 1
    if act.data["wins"] >= cfg.tame_tries:
        prey.owner = p.id
        prey.pen = pen.id
        prey.x, prey.y = pen.x, pen.y
        movement.freeze(world, prey)
        return "done"
    return "more"


# -------------------------------------------------------------------------- assign villager


def _assign_begin(world: World, p: Player, req: ActionRequest, tick: int):
    v = world.villagers.get(req.target or "")
    if v is None or v.leader != p.id:
        return "not_your_villager"
    if req.job is not None and req.job not in JOBS:
        return "bad_job"
    if req.work_level is not None and req.work_level not in WORK_LEVELS:
        return "bad_level"
    if req.job is None and req.work_level is None:
        return "nothing_to_assign"
    hear = world.cfg.balance.senses.hearing_tiles
    if (v.x - p.x) ** 2 + (v.y - p.y) ** 2 > hear * hear:
        return "too_far"
    return Plan(data={"villager": v.id})


def _assign_unit(world: World, p: Player, act: ActiveAction, tick: int) -> str:
    v = world.villagers.get(act.data["villager"])
    if v is None or v.leader != p.id:
        return "fail:not_your_villager"
    req = act.request
    if req.job is not None:
        v.job = req.job
        v.route, v.route_index = [], 0
        home = world.homes[p.index - 1].anchor
        v.job_x, v.job_y = (req.x, req.y) if req.x is not None and req.y is not None else home
    if req.work_level is not None:
        v.work_level = req.work_level
    return "done"


register(
    Spec(
        "gather",
        _gather_begin,
        _gather_unit,
        _gather_claim,
        True,
        True,
        "dynamic",
        True,
        _gather_minutes_key,
    )
)
register(Spec("farm", _farm_begin, _farm_unit, _farm_claim, True, True, "hoe", True))
register(Spec("fish", _fish_begin, _fish_unit, _fish_claim, True, True, "fishing", True))
register(Spec("hunt", _hunt_begin, _hunt_unit, _hunt_claim, True, True))
register(Spec("tame", _tame_begin, _tame_unit, None, True, True))
register(Spec("assign_villager", _assign_begin, _assign_unit, None, False, False))

_ = math  # keep the import used by tools that share this module
