"""Buildings: build, build_shrine, joint projects, storm damage, completion effects."""

from __future__ import annotations

from ai_island.rules import wellbeing
from ai_island.rules.actions import core
from ai_island.rules.actions.core import Plan, Spec, register
from ai_island.rules.actions.request import ActionRequest
from ai_island.storage.events import (
    BeliefAct,
    CoopBonus,
    StructureBuilt,
    StructureDamaged,
)
from ai_island.world.agents import ActiveAction, Inventory, Player, Structure
from ai_island.world.state import Pos, World

FLAT_TERRAIN = ("grass", "sand", "stump")
WATER_TERRAIN = ("spring", "lake", "coast")


def site_ok(
    world: World, p: Player | None, kind: str, pos: Pos, owner: str | None = None
) -> str | None:
    """None if ``kind`` may be built at ``pos``, else the reason it cannot."""
    x, y = pos
    if not world.inside(x, y):
        return "off_map"
    terrain = world.terrain[y][x]
    if kind == "bridge":
        if terrain not in WATER_TERRAIN or pos in world.bridges:
            return "not_water"
        if not any(
            world.inside(x + dx, y + dy) and world.passable(x + dx, y + dy)
            for dx, dy in ((1, 0), (0, 1), (-1, 0), (0, -1))
        ):
            return "no_shore"
    elif terrain not in FLAT_TERRAIN:
        return "bad_ground"
    if core.structure_at(world, pos) is not None:
        return "occupied"
    if p is not None and not core.free_to_use(world, p, pos):
        return "not_your_land"
    if kind == "hearth":
        who = owner or (p.id if p else None)
        if not any(
            s.kind == "house"
            and s.complete
            and s.owner == who
            and core.manhattan((s.x, s.y), pos) <= 2
            for s in world.structures.values()
        ):
            return "needs_house"
    return None


def find_site(world: World, p: Player, kind: str) -> Pos | None:
    anchor = world.homes[p.index - 1].anchor
    return core.find_nearest(
        world, anchor, lambda x, y: site_ok(world, p, kind, (x, y)) is None, 12
    )


def _build_begin(world: World, p: Player, req: ActionRequest, tick: int, belief: bool = False):
    cfg = world.cfg.balance.buildings
    if req.target is not None and req.target.isdigit():
        s = world.structures.get(int(req.target))
        if s is None or s.complete:
            return "no_such_project"
        if s.owner != p.id and s.owner not in p.allies and s.kind not in cfg.joint_kinds:
            return "not_yours"
        return Plan(goal=(s.x, s.y), reach=1, data={"structure": s.id})
    kind = "shrine" if belief else req.structure
    if kind is None or kind not in cfg.costs or kind == "campfire":
        return "unknown_structure"
    spot = (req.x, req.y) if req.x is not None and req.y is not None else find_site(world, p, kind)
    if spot is None:
        return "no_site"
    problem = site_ok(world, p, kind, spot)
    if problem:
        return problem
    cost = dict(cfg.costs[kind])
    if not core.pay(world, p, cost):
        return "missing_materials"
    sid = world.next("structure")
    hp = cfg.hp[kind]
    s = Structure(sid, kind, spot[0], spot[1], p.id, max(1, hp // 4), hp, False, 0.0, {}, None, 0,
                  belief)  # fmt: skip
    world.structures[sid] = s
    return Plan(goal=spot, reach=1, data={"structure": sid, "site_cost": cost, "fresh": True})


def _build_shrine_begin(world: World, p: Player, req: ActionRequest, tick: int):
    return _build_begin(world, p, req, tick, belief=True)


def _complete(world: World, s: Structure, tick: int) -> None:
    cfg = world.cfg.balance.buildings
    s.complete = True
    s.hp = s.max_hp
    if s.kind in cfg.store_kinds:
        s.store = Inventory(world.ids)
    if s.kind == "field":
        world.terrain[s.y][s.x] = "farmland_empty"
    if s.kind == "bridge":
        world.bridges.add((s.x, s.y))
        world.invalidate_costs()
    world.emit(StructureBuilt(id=s.id, kind=s.kind, owner=s.owner, x=s.x, y=s.y), tick)
    if s.belief:
        world.emit(BeliefAct(player=s.owner, kind="build_shrine", x=s.x, y=s.y), tick)
    if s.kind in cfg.joint_kinds:
        coop = len(s.contributors) >= cfg.min_contributors_joint
        amount = cfg.coop_reward if coop else cfg.solo_reward
        for pid in sorted(s.contributors):
            if pid in world.players:
                world.emit(CoopBonus(player=pid, structure=s.id, kind=s.kind, amount=amount), tick)
                wellbeing.add_gain(world, pid, amount, f"joint:{s.kind}", tick)


def contribute(world: World, s: Structure, who: str, tick: int, amount: float) -> bool:
    """Add one work chunk; returns True if the structure was completed by it."""
    s.progress += amount
    s.contributors[who] = s.contributors.get(who, 0) + 1
    if s.progress >= world.cfg.balance.buildings.work_minutes[s.kind] and not s.complete:
        _complete(world, s, tick)
        return True
    return False


def _build_unit(world: World, p: Player, act: ActiveAction, tick: int) -> str:
    s = world.structures.get(act.data["structure"])
    if s is None:
        return "fail:no_such_project"
    if s.complete:
        return "done"
    act.data.pop("fresh", None)
    act.data.pop("site_cost", None)
    chunk = world.cfg.balance.actions.unit_minutes["build"]
    if s.owner != p.id and s.owner in world.players:
        core.note_helped(world, p, act, s.owner, "build_shrine" if s.belief else "build", tick)
    if contribute(world, s, p.id, tick, chunk):
        return "done"
    return "more"


def refund_unstarted(world: World, p: Player, act: ActiveAction, tick: int) -> None:
    """A build cancelled before any work leaves no site behind and returns its materials."""
    cost = act.data.get("site_cost")
    sid = act.data.get("structure")
    if not cost or sid is None:
        return
    s = world.structures.get(sid)
    if s is not None and not s.complete and s.progress == 0:
        del world.structures[sid]
        core.refund(world, p, {k: int(v) for k, v in cost.items()}, tick)


register(Spec("build", _build_begin, _build_unit, None, True, True))
register(Spec("build_shrine", _build_shrine_begin, _build_unit, None, True, True))


# ------------------------------------------------------------------------- storm damage


def storm_damage(world: World, tick: int) -> None:
    """Called hourly during a storm: buildings may be hit; owners lose a little X."""
    if world.weather.current != "storm":
        return
    cfg = world.cfg.balance
    rng = world.streams.get("buildings.storm")
    for s in sorted(world.structures.values(), key=lambda q: q.id):
        if not s.complete or s.kind == "campfire":
            continue
        if rng.random() < cfg.buildings.storm_damage_chance:
            s.hp = max(1, s.hp - cfg.buildings.storm_damage_hp)
            world.emit(StructureDamaged(id=s.id, kind=s.kind, hp=s.hp), tick)
            wellbeing.add_gain(world, s.owner, -cfg.actions.storm_damage_blow, "storm_damage", tick)
