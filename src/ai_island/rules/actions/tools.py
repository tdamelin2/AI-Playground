"""Tools and loose items: craft, repair, drop, pick_up."""

from __future__ import annotations

import math

from ai_island.rules.actions import core
from ai_island.rules.actions.core import Plan, Spec, register
from ai_island.rules.actions.request import ActionRequest
from ai_island.world.agents import (
    TOOL_KINDS,
    TOOL_TIERS,
    ActiveAction,
    Inventory,
    Player,
    transfer_items,
)
from ai_island.world.state import World


def has_workshop(world: World, p: Player) -> bool:
    radius = world.cfg.balance.actions.store_radius
    return any(
        s.kind == "workshop" and s.complete and core.manhattan((s.x, s.y), (p.x, p.y)) <= radius
        for s in world.structures.values()
        if s.owner == p.id or s.owner in p.allies
    )


def _craft_begin(world: World, p: Player, req: ActionRequest, tick: int):
    cfg = world.cfg.balance
    n = req.amount or 1
    if req.item == "stake":
        cost = {"wood": cfg.tools.stake_wood * n}
        if not core.pay(world, p, cost):
            return "missing_materials"
        return Plan(
            data={
                "stake": True,
                "units": n,
                "reserved": cost,
                "unit_cost": {"wood": cfg.tools.stake_wood},
            }
        )
    kind = req.tool
    tier = req.tier or "basic"
    if kind not in TOOL_KINDS:
        return "unknown_tool"
    if tier not in TOOL_TIERS:
        return "unknown_tier"
    if tier == "better" and not has_workshop(world, p):
        return "needs_workshop"
    unit_cost = dict(cfg.tools.recipes[kind][tier])
    cost = {k: v * n for k, v in unit_cost.items()}
    if not core.pay(world, p, cost):
        return "missing_materials"
    return Plan(
        data={"kind": kind, "tier": tier, "units": n, "reserved": cost, "unit_cost": unit_cost}
    )


def _craft_minutes(act: ActiveAction) -> str:
    return "craft_better" if act.data.get("tier") == "better" else "craft"


def _craft_unit(world: World, p: Player, act: ActiveAction, tick: int) -> str:
    cfg = world.cfg.balance.tools
    reserved = act.data["reserved"]
    for k, v in act.data["unit_cost"].items():
        reserved[k] = reserved.get(k, 0) - v
    act.data["reserved"] = {k: v for k, v in reserved.items() if v > 0}
    if act.data.get("stake"):
        p.inventory.add("stake", 1, tick)
    else:
        p.inventory.add_tool(act.data["kind"], act.data["tier"], cfg.durability[act.data["tier"]])
    act.data["units"] -= 1
    return "done" if act.data["units"] <= 0 else "more"


def _repair_begin(world: World, p: Player, req: ActionRequest, tick: int):
    cfg = world.cfg.balance
    if req.structure is not None:
        s = world.structures.get(int(req.structure)) if req.structure.isdigit() else None
        if s is None or not s.complete:
            return "no_structure"
        if s.owner != p.id and s.owner not in p.allies:
            return "not_yours"
        if s.hp >= s.max_hp:
            return "not_damaged"
        cost = {
            k: max(1, math.ceil(v * cfg.tools.repair_share))
            for k, v in cfg.buildings.costs[s.kind].items()
        }
        if not core.pay(world, p, cost):
            return "missing_materials"
        return Plan(
            goal=(s.x, s.y),
            data={"structure": s.id, "reserved": cost},
        )
    tool = None
    if req.tool is not None:
        worn = [t for t in p.inventory.tools if t.kind == req.tool]
        worn.sort(key=lambda t: (t.durability, t.id))
        tool = worn[0] if worn else None
    if tool is None:
        return "no_tool"
    full = cfg.tools.durability[tool.tier]
    if tool.durability >= full:
        return "not_worn"
    cost = {
        k: max(1, math.ceil(v * cfg.tools.repair_share))
        for k, v in cfg.tools.recipes[tool.kind][tool.tier].items()
    }
    if not core.pay(world, p, cost):
        return "missing_materials"
    return Plan(data={"tool_id": tool.id, "reserved": cost})


def _repair_unit(world: World, p: Player, act: ActiveAction, tick: int) -> str:
    cfg = world.cfg.balance
    if "structure" in act.data:
        s = world.structures.get(act.data["structure"])
        if s is None:
            return "fail:no_structure"
        old_hp = s.hp
        s.hp = min(s.max_hp, s.hp + cfg.buildings.repair_hp_per_unit)
        if s.hp > old_hp and s.owner != p.id and s.owner in world.players:
            core.note_helped(world, p, act, s.owner, "repair", tick)
        if s.hp < s.max_hp:
            return "more"
        act.data["reserved"] = {}
        return "done"
    tool = p.inventory.tool_by_id(act.data["tool_id"])
    if tool is None:
        return "fail:no_tool"
    tool.durability = cfg.tools.durability[tool.tier]
    act.data["reserved"] = {}
    return "done"


def _drop_begin(world: World, p: Player, req: ActionRequest, tick: int):
    if req.tool is not None:
        found = [t for t in p.inventory.tools if t.kind == req.tool]
        if not found:
            return "no_tool"
        return Plan(data={"tool_id": sorted(found, key=lambda t: t.id)[0].id})
    if req.item is None or p.inventory.count(req.item) == 0:
        return "nothing_to_drop"
    return Plan(data={})


def _drop_unit(world: World, p: Player, act: ActiveAction, tick: int) -> str:
    pos = (p.x, p.y)
    inv = world.drops.get(pos)
    if inv is None:
        inv = world.drops[pos] = world.new_inventory()
    if "tool_id" in act.data:
        ok = transfer_items(world, p.inventory, inv, {}, [act.data["tool_id"]])
    else:
        item = act.request.item
        assert item is not None
        n = min(act.request.amount or p.inventory.count(item), p.inventory.count(item))
        ok = transfer_items(world, p.inventory, inv, {item: n}, [])
    if not ok:
        return "fail:blocked"
    return "done"


def drops_near(world: World, p: Player) -> list[tuple[tuple[int, int], Inventory]]:
    return [
        (pos, inv)
        for pos, inv in sorted(world.drops.items())
        if core.manhattan(pos, (p.x, p.y)) <= world.cfg.balance.actions.reach_tiles
    ]


def _pickup_begin(world: World, p: Player, req: ActionRequest, tick: int):
    if req.x is not None and req.y is not None:
        spot = (req.x, req.y)
        inv = world.drops.get(spot)
        if inv is None or inv.is_empty():
            return "nothing_there"
        return Plan(goal=spot, reach=1)
    near = [(pos, inv) for pos, inv in drops_near(world, p) if not inv.is_empty()]
    if not near:
        return "nothing_there"
    return Plan()


def _pickup_unit(world: World, p: Player, act: ActiveAction, tick: int) -> str:
    req = act.request
    for pos, inv in drops_near(world, p):
        if req.x is not None and (req.x, req.y) != pos:
            continue
        items = (
            {req.item: min(req.amount or 10**6, inv.count(req.item))} if req.item else inv.counts()
        )
        items = {k: min(n, core.carry_room(world, p)) for k, n in items.items() if n > 0}
        items = {k: n for k, n in items.items() if n > 0}
        tools = [] if req.item else [t.id for t in inv.tools]
        if (items or tools) and transfer_items(world, inv, p.inventory, items, tools):
            if inv.is_empty():
                world.drops.pop(pos, None)
            return "done"
    return "fail:nothing_there"


register(Spec("craft", _craft_begin, _craft_unit, None, False, True, None, False, _craft_minutes))
register(Spec("repair", _repair_begin, _repair_unit, None, True, True))
register(Spec("drop", _drop_begin, _drop_unit, None, False, False))
register(Spec("pick_up", _pickup_begin, _pickup_unit, None, False, False))
