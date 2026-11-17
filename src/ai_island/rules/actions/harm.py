"""Harm actions: steal, sabotage, attack, chase_off, claim_land, pull_stakes, capture, poach."""

from __future__ import annotations

from ai_island.rules import body, interrupts, land, wellbeing
from ai_island.rules.actions import core, social
from ai_island.rules.actions.core import Plan, Spec, register
from ai_island.rules.actions.request import ActionRequest
from ai_island.storage.events import Harm, VillagerLeft
from ai_island.world import people
from ai_island.world.agents import ActiveAction, HarmRecord, Player, transfer_items
from ai_island.world.state import World


def record_harm(world: World, kind: str, actor: str, victim: str, pos, tick: int,
                notice: str | None = None) -> HarmRecord:  # fmt: skip
    """Append a HarmRecord and event; the victim player notices a loss (never the culprit)."""
    hid = world.next("harm")
    rec = HarmRecord(hid, tick, kind, actor, victim, pos[0], pos[1])
    world.harm_log.append(rec)
    world.emit(Harm(id=hid, kind=kind, actor=actor, victim=victim, x=pos[0], y=pos[1]), tick)
    social.on_harm(world, actor, victim, tick)
    target = world.players.get(victim)
    if target is not None:
        target.last_harm_tick = tick
        if notice:
            interrupts.raise_interrupt(world, "loss_noticed", victim, tick, detail=notice)
    return rec


def _blow(world: World, victim: str, amount: float, reason: str, tick: int) -> None:
    if victim in world.players:
        wellbeing.add_gain(world, victim, -amount, reason, tick)


def _owner_player(world: World, ident: str) -> str | None:
    """The player a person belongs to (itself, or a villager's leader)."""
    if ident in world.players:
        return ident
    v = world.villagers.get(ident)
    return None if v is None else v.leader


def _target_person(world: World, p: Player, ident: str | None):
    who = world.players.get(ident or "") or world.villagers.get(ident or "")
    if who is None or not who.alive or who.id == p.id:
        return None
    return who


def _reach(world: World) -> int:
    return world.cfg.balance.harm.reach_tiles


# ----------------------------------------------------------------------------------- steal


def _steal_begin(world: World, p: Player, req: ActionRequest, tick: int):
    cfg = world.cfg.balance
    if req.structure is not None and req.structure.isdigit():
        s = world.structures.get(int(req.structure))
        if s is None or s.store is None or s.owner == p.id:
            return "no_store"
        return Plan(goal=(s.x, s.y), reach=_reach(world), data={"store": s.id})
    victim = _target_person(world, p, req.target)
    if victim is None:
        return "no_such_target"
    if req.structure == "store":
        if victim.id not in world.players:
            return "no_store"
        anchor = world.homes[victim.index - 1].anchor
        return Plan(goal=anchor, reach=cfg.actions.store_radius, data={"home_store": victim.id})
    return Plan(goal=(victim.x, victim.y), reach=_reach(world), data={"victim": victim.id})


def _steal_unit(world: World, p: Player, act: ActiveAction, tick: int) -> str:
    cfg = world.cfg.balance
    req = act.request
    data = act.data
    if "store" in data:
        s = world.structures.get(data["store"])
        if s is None or s.store is None:
            return "fail:no_store"
        src, owner, pos = s.store, s.owner, (s.x, s.y)
    elif "home_store" in data:
        victim = world.players.get(data["home_store"])
        if victim is None:
            return "fail:no_store"
        src, owner, pos = victim.home_store, victim.id, world.homes[victim.index - 1].anchor
    else:
        victim = _target_person(world, p, data["victim"])
        if victim is None:
            return "fail:no_such_target"
        if core.manhattan((p.x, p.y), (victim.x, victim.y)) > _reach(world) + 1:
            return "fail:too_far"
        src, owner, pos = (
            victim.inventory,
            _owner_player(world, victim.id) or victim.id,
            (victim.x, victim.y),
        )
    if src.is_empty():
        return "fail:nothing_to_steal"
    item = req.item
    if item is None or src.count(item) == 0:
        counts = src.counts()
        if not counts:
            return "fail:nothing_to_steal"
        item = max(counts, key=lambda k: (counts[k], k))
    chance = cfg.harm.steal_chance
    if social.guards_near(world, pos, 5, tick, exclude=p.id):
        chance *= 1.0 - cfg.harm.guard_reduction
    if world.streams.get("actions.harm").random() >= chance:
        return "caught_off_guard"
    n = min(req.amount or cfg.harm.steal_max_items, src.count(item), cfg.harm.steal_max_items)
    n = min(n, core.carry_room(world, p))
    if n <= 0 or not transfer_items(world, src, p.inventory, {item: n}, []):
        return "fail:blocked"
    record_harm(world, "steal", p.id, owner, pos, tick, notice="goods")
    _blow(world, owner, cfg.wellbeing.theft_blow, "theft", tick)
    return "done"


# ------------------------------------------------------------------------------- sabotage


def _sabotage_begin(world: World, p: Player, req: ActionRequest, tick: int):
    s = (
        world.structures.get(int(req.structure))
        if req.structure and req.structure.isdigit()
        else None
    )
    if s is None:
        return "no_structure"
    if s.owner == p.id:
        return "own_building"
    return Plan(goal=(s.x, s.y), reach=_reach(world), data={"structure": s.id})


def destroy_structure(world: World, sid: int, tick: int) -> None:
    s = world.structures.pop(sid, None)
    if s is None:
        return
    if s.kind == "bridge":
        world.bridges.discard((s.x, s.y))
        world.invalidate_costs()
    if s.store is not None and not s.store.is_empty():
        inv = world.drops.setdefault((s.x, s.y), world.new_inventory())
        from ai_island.world.agents import transfer_all

        transfer_all(s.store, inv)


def _sabotage_unit(world: World, p: Player, act: ActiveAction, tick: int) -> str:
    cfg = world.cfg.balance
    s = world.structures.get(act.data["structure"])
    if s is None:
        return "fail:no_structure"
    if core.manhattan((p.x, p.y), (s.x, s.y)) > _reach(world) + 1:
        return "fail:too_far"
    s.hp -= cfg.harm.sabotage_hp
    owner = s.owner
    pos = (s.x, s.y)
    if s.hp <= 0:
        destroy_structure(world, s.id, tick)
    record_harm(world, "sabotage", p.id, owner, pos, tick, notice="building")
    _blow(world, owner, cfg.wellbeing.sabotage_blow, "sabotage", tick)
    return "done"


# --------------------------------------------------------------------------------- attack


def _attack_begin(world: World, p: Player, req: ActionRequest, tick: int):
    victim = _target_person(world, p, req.target)
    if victim is None:
        return "no_such_target"
    return Plan(goal=(victim.x, victim.y), reach=_reach(world), data={"victim": victim.id})


def drop_carried(world: World, victim, tick: int) -> None:
    cfg = world.cfg.balance.harm
    inv = victim.inventory
    items: dict[str, int] = {}
    for kind in cfg.attack_drop_items:
        n = int(inv.count(kind) * cfg.attack_drop_share)
        if n > 0:
            items[kind] = n
    if not items:
        return
    pile = world.drops.setdefault((victim.x, victim.y), world.new_inventory())
    transfer_items(world, inv, pile, items, [])


def _attack_unit(world: World, p: Player, act: ActiveAction, tick: int) -> str:
    cfg = world.cfg.balance
    victim = _target_person(world, p, act.data["victim"])
    if victim is None:
        return "fail:no_such_target"
    if core.manhattan((p.x, p.y), (victim.x, victim.y)) > _reach(world):
        if core.retarget(world, p, act, (victim.x, victim.y), tick):
            return "retarget"
        return "fail:too_far"
    owner = victim.id
    pos = (victim.x, victim.y)
    drop_carried(world, victim, tick)
    if victim.id in world.players:
        core.cancel_action(world, victim.id, tick, "attacked")
        interrupts.raise_interrupt(world, "attacked", victim.id, tick, source=None, detail="")
        wellbeing.change_trust(world, victim.id, p.id, -cfg.harm.victim_trust_loss)
        wellbeing.change_anger(world, victim.id, p.id, cfg.harm.victim_anger_gain)
    record_harm(world, "attack", p.id, owner, pos, tick)
    _blow(world, owner, cfg.wellbeing.attack_blow, "attacked", tick)
    body.hurt(world, victim, cfg.harm.attack_health, cfg.harm.attack_pain, "attack", tick)
    return "done"


# ------------------------------------------------------------------------------ chase off


def _chase_begin(world: World, p: Player, req: ActionRequest, tick: int):
    return _attack_begin(world, p, req, tick)


def push_away(world: World, victim, from_pos, tick: int) -> bool:
    """Give ``victim`` a walking route away from ``from_pos`` (never a teleport)."""
    tiles = world.cfg.balance.harm.chase_tiles
    dx = (victim.x > from_pos[0]) - (victim.x < from_pos[0])
    dy = (victim.y > from_pos[1]) - (victim.y < from_pos[1])
    if dx == 0 and dy == 0:
        dx = 1
    dest = None
    for step in range(tiles, 0, -1):
        for sx, sy in ((dx, dy), (dx, 0), (0, dy)):
            if sx == 0 and sy == 0:
                continue
            tx, ty = victim.x + sx * step, victim.y + sy * step
            if world.inside(tx, ty) and world.passable(tx, ty):
                dest = (tx, ty)
                break
        if dest:
            break
    if dest is None:
        return False
    route = people.make_route(world, (victim.x, victim.y), dest)
    if route is None:
        return False
    if victim.id in world.players:
        core.cancel_action(world, victim.id, tick, "chased")
        act = ActiveAction(
            world.next("action"), ActionRequest(kind="move", x=dest[0], y=dest[1]), tick,
            route=route, status="walking",
            data={"goal": list(dest), "reach": 0, "instant": True, "forced": True},
        )  # fmt: skip
        victim.action = act
        victim.just_finished = False
    else:
        victim.route, victim.route_index = route, 0
    return True


def _chase_unit(world: World, p: Player, act: ActiveAction, tick: int) -> str:
    cfg = world.cfg.balance
    victim = _target_person(world, p, act.data["victim"])
    if victim is None:
        return "fail:no_such_target"
    if core.manhattan((p.x, p.y), (victim.x, victim.y)) > _reach(world):
        if core.retarget(world, p, act, (victim.x, victim.y), tick):
            return "retarget"
        return "fail:too_far"
    pos = (victim.x, victim.y)
    if not push_away(world, victim, (p.x, p.y), tick):
        return "fail:blocked"
    if victim.id in world.players:
        interrupts.raise_interrupt(world, "attacked", victim.id, tick, detail="chased")
        wellbeing.change_anger(world, victim.id, p.id, cfg.harm.victim_anger_gain / 2)
    record_harm(world, "chase_off", p.id, victim.id, pos, tick)
    _blow(world, victim.id, cfg.wellbeing.chase_blow, "chased_off", tick)
    return "done"


# ----------------------------------------------------------------------------- land, stakes


def _claim_begin(world: World, p: Player, req: ActionRequest, tick: int):
    cfg = world.cfg.balance.claims
    spot = (p.x, p.y) if req.x is None or req.y is None else (req.x, req.y)
    if not world.inside(*spot) or not world.passable(*spot):
        return "blocked"
    owner = land.owner_of(world, spot)
    if owner is not None and owner != p.id:
        return "owned_by_other"
    if spot in world.stakes:
        return "already_staked"
    if p.inventory.count("stake") < cfg.stake_item_cost:
        return "no_stake"
    return Plan(goal=spot, reach=0, data={"spot": list(spot)})


def _claim_unit(world: World, p: Player, act: ActiveAction, tick: int) -> str:
    cfg = world.cfg.balance.claims
    spot = (act.data["spot"][0], act.data["spot"][1])
    if not p.inventory.remove("stake", cfg.stake_item_cost):
        return "fail:no_stake"
    land.place_stake(world, p.id, spot, tick)
    return "done"


def _pull_begin(world: World, p: Player, req: ActionRequest, tick: int):
    if req.x is None or req.y is None:
        return "needs_position"
    spot = (req.x, req.y)
    owner = world.stakes.get(spot)
    if owner is None or owner == p.id:
        return "no_rival_stake"
    return Plan(goal=spot, reach=_reach(world), data={"spot": list(spot)})


def _pull_unit(world: World, p: Player, act: ActiveAction, tick: int) -> str:
    cfg = world.cfg.balance
    spot = (act.data["spot"][0], act.data["spot"][1])
    owner = world.stakes.get(spot)
    if owner is None or owner == p.id:
        return "fail:no_rival_stake"
    if core.manhattan((p.x, p.y), spot) > _reach(world) + 1:
        return "fail:too_far"
    land.pull_stake(world, spot, tick)
    p.inventory.add("stake", 1, tick)
    record_harm(world, "pull_stakes", p.id, owner, spot, tick, notice="land")
    _blow(world, owner, cfg.wellbeing.stakes_blow, "stakes_pulled", tick)
    return "done"


# ------------------------------------------------------------------------ capture, poach


def _rival_villager(world: World, p: Player, ident: str | None):
    v = world.villagers.get(ident or "")
    if v is None or not v.alive or v.leader == p.id:
        return None
    return v


def _capture_begin(world: World, p: Player, req: ActionRequest, tick: int):
    v = _rival_villager(world, p, req.target)
    if v is None:
        return "no_such_villager"
    return Plan(goal=(v.x, v.y), reach=_reach(world), data={"villager": v.id})


def _leave(world: World, v, to: str | None, reason: str, tick: int) -> None:
    world.emit(
        VillagerLeft(villager=v.id, leader=v.leader or "", to=to, reason=reason,
                     hungry_days=v.adverse_days.get("hunger", 0),
                     hard_days=v.adverse_days.get("hard", 0)),
        tick,
    )  # fmt: skip


def _capture_unit(world: World, p: Player, act: ActiveAction, tick: int) -> str:
    cfg = world.cfg.balance
    v = _rival_villager(world, p, act.data["villager"])
    if v is None:
        return "fail:no_such_villager"
    if core.manhattan((p.x, p.y), (v.x, v.y)) > _reach(world) + 1:
        if core.retarget(world, p, act, (v.x, v.y), tick):
            return "retarget"
        return "fail:too_far"
    if world.streams.get("actions.harm").random() >= cfg.harm.capture_chance:
        return "escaped"
    old = v.leader
    _leave(world, v, p.id, "captured", tick)
    v.leader = p.id
    v.captive = True
    v.captor = p.id
    v.job = None
    v.route, v.route_index = [], 0
    v.loyalty = min(v.loyalty, cfg.villagers.leave_below + 10)
    if old is not None:
        record_harm(world, "capture", p.id, old, (v.x, v.y), tick, notice="villager")
        _blow(world, old, cfg.wellbeing.capture_blow, "captured_villager", tick)
    return "done"


def _poach_begin(world: World, p: Player, req: ActionRequest, tick: int):
    v = _rival_villager(world, p, req.target)
    if v is None:
        return "no_such_villager"
    attached = sum(1 for q in world.villagers.values() if q.leader == p.id)
    if attached >= p.slots:
        return "no_free_slot"
    return Plan(goal=(v.x, v.y), reach=_reach(world), data={"villager": v.id})


def _poach_unit(world: World, p: Player, act: ActiveAction, tick: int) -> str:
    cfg = world.cfg.balance
    v = _rival_villager(world, p, act.data["villager"])
    if v is None:
        return "fail:no_such_villager"
    if core.manhattan((p.x, p.y), (v.x, v.y)) > _reach(world) + 1:
        if core.retarget(world, p, act, (v.x, v.y), tick):
            return "retarget"
        return "fail:too_far"
    old = v.leader
    willing = v.loyalty < cfg.villagers.poach_loyalty or v.bond.get(
        p.id, cfg.villagers.bond_start_other
    ) > (v.bond.get(old, cfg.villagers.bond_start_other) if old else 0.0)
    if not willing:
        return "refused"
    if world.streams.get("actions.harm").random() >= cfg.harm.poach_chance:
        return "refused"
    _leave(world, v, p.id, "poached", tick)
    social.attach(world, v, p.id, tick, "poach", v.loyalty)
    if old is not None:
        record_harm(world, "poach", p.id, old, (v.x, v.y), tick, notice="villager")
        _blow(world, old, cfg.wellbeing.poach_blow, "poached_villager", tick)
    return "done"


register(Spec("steal", _steal_begin, _steal_unit, physical=True))
register(Spec("sabotage", _sabotage_begin, _sabotage_unit, physical=True))
register(Spec("attack", _attack_begin, _attack_unit, physical=True))
register(Spec("chase_off", _chase_begin, _chase_unit, physical=True))
register(Spec("claim_land", _claim_begin, _claim_unit, outdoor=True, physical=True))
register(Spec("pull_stakes", _pull_begin, _pull_unit, outdoor=True, physical=True))
register(Spec("capture", _capture_begin, _capture_unit, physical=True))
register(Spec("poach", _poach_begin, _poach_unit, physical=False))
