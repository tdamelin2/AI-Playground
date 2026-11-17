"""The action engine: starting, walking, timed units, cancelling and conflict resolution.

An action is a walk to a place (if needed) followed by timed work units. Side effects
happen when a unit completes. Competing claims on a scarce unit are grouped and decided by
the seeded ``actions.conflicts`` stream; losers spend nothing.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ai_island.rules import wellbeing
from ai_island.rules.actions.request import ActionRequest
from ai_island.storage.events import (
    ActionFailed,
    ActionFinished,
    ActionStarted,
    Helped,
    ToolBroken,
)
from ai_island.world import people
from ai_island.world.agents import ActiveAction, Player, Tool
from ai_island.world.movement import complete_step, is_stepping
from ai_island.world.state import Pos, World


@dataclass
class Plan:
    """What an action needs before it can start: where to go, how much to do."""

    goal: Pos | None = None  # stand within reach of this tile
    reach: int | None = None  # override of actions.reach_tiles
    data: dict[str, Any] = field(default_factory=dict)
    instant: bool = False  # no work units: finish on arrival


UnitFn = Callable[[World, Player, ActiveAction, int], str]
BeginFn = Callable[[World, Player, ActionRequest, int], "Plan | str"]
ClaimFn = Callable[[World, Player, ActiveAction, int], "str | None"]


@dataclass
class Spec:
    kind: str
    begin: BeginFn
    unit: UnitFn
    claim: ClaimFn | None = None
    outdoor: bool = False
    physical: bool = True
    tool: str | None = None  # tool kind that speeds this action up
    hand_slow: bool = False  # half speed without the tool
    minutes_key: Callable[[ActiveAction], str] | None = None


SPECS: dict[str, Spec] = {}


def register(spec: Spec) -> None:
    SPECS[spec.kind] = spec


# ------------------------------------------------------------------------------- helpers


def manhattan(a: Pos, b: Pos) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def fail(world: World, p: Player, kind: str, reason: str, tick: int) -> bool:
    world.emit(ActionFailed(player=p.id, kind=kind, reason=reason), tick)
    return False


def player_order(world: World, tick: int) -> list[str]:
    """Sorted player ids rotated by ``tick % 4``."""
    ids = sorted(world.players)
    if not ids:
        return ids
    shift = tick % len(ids)
    return ids[shift:] + ids[:shift]


def clear_action(world: World, p: Player) -> None:
    """Drop the current action without events (death, forced moves)."""
    p.action = None
    p.sleeping = False


def note_helped(world: World, p: Player, act: ActiveAction, target: str, kind: str, tick: int):
    """Emit one Helped event per action, at its first effect for someone else."""
    if target == p.id or act.data.get("helped"):
        return
    act.data["helped"] = True
    world.emit(Helped(actor=p.id, target=target, kind=kind, action_id=act.id), tick)  # type: ignore[arg-type]


def tile_owner(world: World, pos: Pos) -> str | None:
    """Who owns ``pos``: the home plot's player, or the claimant, else None."""
    zone = world.zone_at(*pos)
    if zone.startswith("home_"):
        return f"player_{int(zone.split('_')[1]) + 1}"
    return world.claims.get(pos)


def free_to_use(world: World, p: Player, pos: Pos) -> bool:
    """May ``p`` build or farm at ``pos``? Not on a rival's plot or claim."""
    owner = tile_owner(world, pos)
    return owner is None or owner == p.id or owner in p.allies


def structure_at(world: World, pos: Pos) -> Any:
    for s in world.structures.values():
        if (s.x, s.y) == pos:
            return s
    return None


def find_nearest(
    world: World, origin: Pos, predicate: Callable[[int, int], bool], radius: int = 30
) -> Pos | None:
    """Nearest tile (Manhattan, then y, then x) within ``radius`` that satisfies ``predicate``."""
    best: tuple[int, int, int] | None = None
    ox, oy = origin
    for y in range(max(0, oy - radius), min(world.height, oy + radius + 1)):
        for x in range(max(0, ox - radius), min(world.width, ox + radius + 1)):
            d = abs(x - ox) + abs(y - oy)
            if best is not None and (d, y, x) >= best:
                continue
            if predicate(x, y):
                best = (d, y, x)
    return None if best is None else (best[2], best[1])


def carry_room(world: World, p: Player) -> int:
    return world.cfg.balance.actions.carry_limit - p.inventory.total_items()


def give_item(world: World, p: Player, kind: str, n: int, tick: int) -> int:
    """Add up to ``n`` to the player's pack (limited by the carry limit); returns the amount."""
    n = min(n, carry_room(world, p))
    if n > 0:
        p.inventory.add(kind, n, tick)
    return max(0, n)


def storage_points(world: World, p: Player) -> list[tuple[Pos, Any]]:
    """(position, inventory) of the player's own stores: home store plus storehouses."""
    home = world.homes[p.index - 1]
    out: list[tuple[Pos, Any]] = [(home.anchor, p.home_store)]
    for s in sorted(world.structures.values(), key=lambda q: q.id):
        if s.owner == p.id and s.complete and s.store is not None:
            out.append(((s.x, s.y), s.store))
    return out


def reachable_stores(world: World, p: Player) -> list[Any]:
    """Own stores within ``store_radius`` of the player (inventory first)."""
    radius = world.cfg.balance.actions.store_radius
    return [inv for pos, inv in storage_points(world, p) if manhattan(pos, (p.x, p.y)) <= radius]


def have_items(world: World, p: Player, cost: dict[str, int]) -> bool:
    sources = [p.inventory, *reachable_stores(world, p)]
    return all(sum(s.count(k) for s in sources) >= n for k, n in cost.items())


def pay(world: World, p: Player, cost: dict[str, int]) -> bool:
    """Take ``cost`` from the pack, then from own stores close by. All or nothing."""
    if not have_items(world, p, cost):
        return False
    sources = [p.inventory, *reachable_stores(world, p)]
    for kind, n in cost.items():
        need = n
        for src in sources:
            take = min(need, src.count(kind))
            if take:
                src.remove(kind, take)
                need -= take
    return True


def refund(world: World, p: Player, cost: dict[str, int], tick: int) -> None:
    for kind, n in cost.items():
        p.inventory.add(kind, n, tick)


def tool_speed(world: World, p: Player, kind: str | None) -> tuple[float, Tool | None]:
    if kind is None:
        return 1.0, None
    tool = p.inventory.find_tool(kind)
    if tool is None:
        return 1.0, None
    return world.cfg.balance.tools.speed[kind][tool.tier], tool


def wear_tool(world: World, p: Player, tool: Tool | None, tick: int) -> None:
    if tool is None:
        return
    tool.durability -= world.cfg.balance.tools.wear_per_unit
    if tool.durability <= 0:
        p.inventory.tools.remove(tool)
        world.emit(ToolBroken(player=p.id, tool=tool.kind, tier=tool.tier), tick)


def unit_minutes(world: World, p: Player, act: ActiveAction) -> int:
    """Effective minutes for the next unit: base / (tool x work x weather)."""
    spec = SPECS[act.request.kind]
    acts = world.cfg.balance.actions
    key = spec.minutes_key(act) if spec.minutes_key else act.request.kind
    base = acts.unit_minutes.get(key, acts.unit_minutes[act.request.kind])
    mult = 1.0
    tool_kind = act.data.get("tool") if spec.tool == "dynamic" else spec.tool
    if tool_kind:
        speed, tool = tool_speed(world, p, tool_kind)
        mult *= speed if tool is not None else (acts.hand_mult if spec.hand_slow else 1.0)
    if spec.physical:
        mult *= wellbeing.work_mult(world, p)
    if spec.outdoor and world.weather.current == "rain":
        mult *= acts.rain_work_mult
    return max(1, math.ceil(base / max(mult, 0.01) - 1e-9))


def begin_unit(world: World, p: Player, act: ActiveAction) -> None:
    act.work_done = 0.0
    act.data["need"] = unit_minutes(world, p, act)


# ----------------------------------------------------------------------- start and finish


def start_action(world: World, pid: str, request: ActionRequest, tick: int) -> bool:
    """Start ``request`` for player ``pid``. Failures emit ``action_failed`` and never raise."""
    p = world.players.get(pid)
    if p is None or not p.alive:
        return False
    spec = SPECS.get(request.kind)
    if spec is None:
        return False
    if p.action is not None:
        cancel_action(world, pid, tick, "replaced")
    try:
        plan = spec.begin(world, p, request, tick)
    except (KeyError, ValueError, TypeError):
        return fail(world, p, request.kind, "invalid_request", tick)
    if isinstance(plan, str):
        return fail(world, p, request.kind, plan, tick)
    act = ActiveAction(world.next("action"), request, tick, data=dict(plan.data))
    reach = plan.reach if plan.reach is not None else world.cfg.balance.actions.reach_tiles
    if plan.goal is not None:
        route = people.route_to_reach(world, (p.x, p.y), plan.goal, reach)
        if route is None:
            cleanup(world, p, act, tick)
            return fail(world, p, request.kind, "unreachable", tick)
        act.route = route
        act.route_index = 0
    act.data["goal"] = list(plan.goal) if plan.goal else None
    act.data["reach"] = reach
    act.data["instant"] = plan.instant
    p.action = act
    p.just_finished = False
    p.sleeping = False
    world.emit(ActionStarted(player=p.id, kind=request.kind), tick)
    if len(act.route) <= 1:
        arrive(world, p, act, tick)
    else:
        act.status = "walking"
    return True


def arrive(world: World, p: Player, act: ActiveAction, tick: int) -> None:
    act.status = "working"
    if act.data.get("instant"):
        finish_action(world, p, tick, "arrived")
        return
    begin_unit(world, p, act)


def finish_action(world: World, p: Player, tick: int, result: str) -> None:
    act = p.action
    if act is None:
        return
    world.emit(
        ActionFinished(player=p.id, kind=act.request.kind, units=act.units_done, result=result),
        tick,
    )
    p.action = None
    p.just_finished = True
    p.sleeping = False
    cleanup(world, p, act, tick)


def cleanup(world: World, p: Player, act: ActiveAction, tick: int) -> None:
    """Return anything reserved for work that did not happen."""
    if act.data.get("site_cost"):
        from ai_island.rules.actions import build as build_mod

        build_mod.refund_unstarted(world, p, act, tick)
    reserved = act.data.get("reserved")
    if reserved:
        refund(world, p, {k: int(v) for k, v in reserved.items()}, tick)
        act.data["reserved"] = {}


def cancel_action(world: World, pid: str, tick: int, reason: str) -> None:
    """Stop the current action. Completed units stay done; reservations come back."""
    p = world.players.get(pid)
    if p is None or p.action is None:
        return
    act = p.action
    world.emit(
        ActionFinished(
            player=p.id, kind=act.request.kind, units=act.units_done, result=f"cancelled:{reason}"
        ),
        tick,
    )
    p.action = None
    p.sleeping = False
    cleanup(world, p, act, tick)


def retarget(world: World, p: Player, act: ActiveAction, goal: Pos, tick: int) -> bool:
    """Re-aim the current action at a new tile (walk there if needed)."""
    reach = act.data.get("reach", world.cfg.balance.actions.reach_tiles)
    route = people.route_to_reach(world, (p.x, p.y), goal, reach)
    if route is None:
        return False
    act.data["goal"] = list(goal)
    act.route = route
    act.route_index = 0
    if len(route) <= 1:
        act.status = "working"
        begin_unit(world, p, act)
    else:
        act.status = "walking"
    return True


# ------------------------------------------------------------------------------ the tick


def walk_players(world: World, tick: int) -> None:
    """Advance every walking player one tick along its route."""
    base = world.cfg.balance.actions.walk_minutes_per_tile
    for pid in sorted(world.players):
        p = world.players[pid]
        act = p.action
        if p.alive and act is None and is_stepping(p):
            complete_step(p, tick)  # finish a step left over from a cancelled walk
            continue
        if not p.alive or act is None or act.status != "walking":
            continue
        state, act.route_index = people.advance_walk(
            world, p, act.route, act.route_index, tick, base
        )
        if state == "arrived":
            goal = act.data.get("goal")
            reach = act.data.get("reach", 1)
            if goal is not None and manhattan((p.x, p.y), (goal[0], goal[1])) > reach:
                if act.data.get("walk_retry", 0) >= 3:
                    fail(world, p, act.request.kind, "unreachable", tick)
                    p.action = None
                    p.just_finished = True
                    cleanup(world, p, act, tick)
                    continue
                act.data["walk_retry"] = act.data.get("walk_retry", 0) + 1
                if not retarget(world, p, act, (goal[0], goal[1]), tick):
                    fail(world, p, act.request.kind, "unreachable", tick)
                    p.action = None
                    p.just_finished = True
                    cleanup(world, p, act, tick)
                continue
            arrive(world, p, act, tick)


def resolve(world: World, tick: int) -> None:
    """Advance work on all working actions; settle competing claims first."""
    storm = world.weather.flags.stops_outdoor_work
    ready: list[str] = []
    for pid in player_order(world, tick):
        p = world.players[pid]
        act = p.action
        if not p.alive or act is None or act.status != "working":
            continue
        spec = SPECS[act.request.kind]
        if storm and act.request.kind in world.cfg.balance.actions.storm_pauses_outdoor:
            continue
        act.work_done += 1.0
        if act.work_done >= act.data.get("need", 1):
            ready.append(pid)
    if not ready:
        return
    groups: dict[str, list[str]] = {}
    for pid in ready:
        p = world.players[pid]
        act = p.action
        assert act is not None
        spec = SPECS[act.request.kind]
        if spec.claim is not None:
            key = spec.claim(world, p, act, tick)
            if key is not None:
                groups.setdefault(key, []).append(pid)
    losers: set[str] = set()
    rng = world.streams.get("actions.conflicts")
    for key in sorted(groups):
        members = groups[key]
        if len(members) > 1:
            winner = members[rng.randrange(len(members))]
            losers.update(m for m in members if m != winner)
    for pid in ready:
        p = world.players[pid]
        act = p.action
        if act is None or not p.alive:
            continue
        if pid in losers:
            act.data["lost"] = act.data.get("lost", 0) + 1
            fail(world, p, act.request.kind, "lost_race", tick)
            act.data.pop("claim_ok", None)
            begin_unit(world, p, act)
            if act.data["lost"] >= 3:
                finish_action(world, p, tick, "lost_race")
            continue
        run_unit(world, p, act, tick)


def run_unit(world: World, p: Player, act: ActiveAction, tick: int) -> None:
    spec = SPECS[act.request.kind]
    outcome = spec.unit(world, p, act, tick)
    if p.action is not act:  # the handler finished or replaced the action itself
        return
    act.data.pop("claim_ok", None)
    if outcome == "more":
        act.units_done += 1
        if act.status == "working":
            begin_unit(world, p, act)
    elif outcome == "done":
        act.units_done += 1
        finish_action(world, p, tick, "done")
    elif outcome == "retarget":
        pass  # the handler already re-aimed the action
    elif outcome.startswith("fail:"):
        fail(world, p, act.request.kind, outcome[5:], tick)
        finish_action(world, p, tick, outcome[5:])
    else:
        finish_action(world, p, tick, outcome)
