"""Social and belief actions: talk, trade, ally, gift, promise, recruit, teach, guard, pray..."""

from __future__ import annotations

from ai_island.rules import interrupts, wellbeing
from ai_island.rules.actions import core
from ai_island.rules.actions.core import Plan, Spec, register
from ai_island.rules.actions.request import ActionRequest
from ai_island.storage.events import (
    BeliefAct,
    PromiseBroken,
    PromiseKept,
    PromiseMade,
    TradeDone,
    TradeOffered,
    VillagerJoined,
)
from ai_island.world.agents import (
    ActiveAction,
    KnowledgeEntry,
    Offer,
    Player,
    Promise,
    Utterance,
    transfer_items,
)
from ai_island.world.state import World


def near(world: World, a, b, radius: int | None = None) -> bool:
    r = world.cfg.balance.senses.hearing_tiles if radius is None else radius
    return (a.x - b.x) ** 2 + (a.y - b.y) ** 2 <= r * r


def _person(world: World, ident: str | None):
    if ident is None:
        return None
    who = world.players.get(ident) or world.villagers.get(ident)
    return who if who is not None and who.alive else None


def note_transfer(world: World, giver: str, to: str, item: str, n: int) -> None:
    """Count a hand-over toward open "give" promises."""
    for pr in world.promises.values():
        if pr.status == "open" and pr.kind == "give" and pr.maker == giver and pr.to == to:
            if pr.item == item:
                pr.given += n


# ------------------------------------------------------------------------------- talking


def _talk_begin(world: World, p: Player, req: ActionRequest, tick: int):
    if not req.text:
        return "nothing_to_say"
    if req.target is not None and _person(world, req.target) is None:
        return "no_such_target"
    return Plan()


def _talk_unit(world: World, p: Player, act: ActiveAction, tick: int) -> str:
    req = act.request
    targets = [req.target] if req.target else []
    world.utterances.append(Utterance(p.id, targets, req.text or "", "talk"))
    if req.target in world.players:
        wellbeing.change_trust(world, req.target, p.id, world.cfg.balance.social.talk_trust_gain)
    return "done"


# ------------------------------------------------------------------------- offers (trade)


def _parse_side(side: dict[str, int] | None) -> tuple[dict[str, int], list[int]] | None:
    items: dict[str, int] = {}
    tools: list[int] = []
    for key, n in (side or {}).items():
        if key.startswith("tool:"):
            if not key[5:].isdigit():
                return None
            tools.append(int(key[5:]))
        elif n > 0:
            items[key] = n
        else:
            return None
    return items, tools


def _offer_begin(kind: str):
    def begin(world: World, p: Player, req: ActionRequest, tick: int):
        if req.accept is not None:
            offer = world.offers.get(req.accept)
            if offer is None or offer.kind != kind or offer.target != p.id:
                return "no_such_offer"
            if tick > offer.expires:
                world.offers.pop(offer.id, None)
                return "offer_expired"
            maker = world.players.get(offer.maker)
            if maker is None or not maker.alive or not near(world, p, maker):
                return "too_far"
            return Plan(data={"accept": offer.id})
        other = world.players.get(req.target or "")
        if other is None or other.id == p.id or not other.alive:
            return "no_such_target"
        if not near(world, p, other):
            return "too_far"
        give = _parse_side(req.offer)
        want = _parse_side(req.want)
        if give is None or want is None:
            return "bad_terms"
        if kind == "trade":
            if not (give[0] or give[1] or want[0] or want[1]):
                return "empty_offer"
            if any(p.inventory.count(k) < n for k, n in give[0].items()):
                return "missing_items"
            if any(p.inventory.tool_by_id(t) is None for t in give[1]):
                return "missing_items"
        elif len(p.allies) >= world.cfg.balance.social.max_allies:
            return "too_many_allies"
        return Plan(data={"make": True})

    return begin


def _offer_unit(kind: str):
    def unit(world: World, p: Player, act: ActiveAction, tick: int) -> str:
        req = act.request
        cfg = world.cfg.balance.social
        if "accept" in act.data:
            offer = world.offers.get(act.data["accept"])
            if offer is None or tick > offer.expires:
                return "fail:offer_gone"
            return _accept(world, p, offer, tick)
        give_items, give_tools = _parse_side(req.offer) or ({}, [])
        want_items, want_tools = _parse_side(req.want) or ({}, [])
        oid = world.next("offer")
        offer = Offer(oid, kind, p.id, req.target or "", give_items, want_items, tick,
                      tick + cfg.offer_expiry_minutes, give_tools, want_tools)  # fmt: skip
        world.offers[oid] = offer
        world.emit(
            TradeOffered(id=oid, kind=kind, maker=p.id, target=offer.target,
                         give=give_items, want=want_items),
            tick,
        )  # fmt: skip
        text = req.text or f"{kind} offer {oid}"
        world.utterances.append(Utterance(p.id, [offer.target], text, "trade", oid))
        interrupts.raise_interrupt(world, "spoken_to", offer.target, tick, source=p.id, detail=kind)
        return "done"

    return unit


def _accept(world: World, p: Player, offer: Offer, tick: int) -> str:
    cfg = world.cfg.balance
    maker = world.players.get(offer.maker)
    if maker is None or not maker.alive or not near(world, p, maker):
        return "fail:too_far"
    if offer.kind == "ally":
        if len(p.allies) >= cfg.social.max_allies or len(maker.allies) >= cfg.social.max_allies:
            return "fail:too_many_allies"
        for a, b in ((p, maker), (maker, p)):
            if b.id not in a.allies:
                a.allies.append(b.id)
            wellbeing.change_trust(world, a.id, b.id, cfg.social.ally_trust_gain)
            wellbeing.add_gain(world, a.id, cfg.wellbeing.ally_gain, "ally", tick)
    else:
        ok_give = all(maker.inventory.count(k) >= n for k, n in offer.give.items()) and all(
            maker.inventory.tool_by_id(t) is not None for t in offer.give_tools
        )
        ok_want = all(p.inventory.count(k) >= n for k, n in offer.want.items()) and all(
            p.inventory.tool_by_id(t) is not None for t in offer.want_tools
        )
        if not (ok_give and ok_want):
            return "fail:terms_changed"
        transfer_items(world, maker.inventory, p.inventory, offer.give, offer.give_tools)
        transfer_items(world, p.inventory, maker.inventory, offer.want, offer.want_tools)
        for k, n in offer.give.items():
            note_transfer(world, maker.id, p.id, k, n)
        for k, n in offer.want.items():
            note_transfer(world, p.id, maker.id, k, n)
        for a, b in ((p, maker), (maker, p)):
            wellbeing.change_trust(world, a.id, b.id, cfg.social.trade_trust_gain)
            wellbeing.add_gain(world, a.id, cfg.wellbeing.trade_gain, "trade", tick)
    world.offers.pop(offer.id, None)
    world.emit(
        TradeDone(id=offer.id, kind=offer.kind, maker=offer.maker, target=offer.target), tick
    )
    return "done"


def expire_offers(world: World, tick: int) -> None:
    for oid in [o.id for o in world.offers.values() if tick > o.expires]:
        del world.offers[oid]


# ------------------------------------------------------------------------------------ gift


def _gift_begin(world: World, p: Player, req: ActionRequest, tick: int):
    who = _person(world, req.target)
    if who is None or who.id == p.id:
        return "no_such_target"
    if req.tool is not None:
        if not any(t.kind == req.tool for t in p.inventory.tools):
            return "missing_items"
    elif req.item is None or p.inventory.count(req.item) == 0:
        return "missing_items"
    return Plan(goal=(who.x, who.y), reach=1)


def _gift_unit(world: World, p: Player, act: ActiveAction, tick: int) -> str:
    req = act.request
    who = _person(world, req.target)
    if who is None:
        return "fail:no_such_target"
    if core.manhattan((p.x, p.y), (who.x, who.y)) > 2:
        return "fail:too_far"
    cfg = world.cfg.balance
    if req.tool is not None:
        tool = next((t for t in p.inventory.tools if t.kind == req.tool), None)
        if tool is None or not transfer_items(world, p.inventory, who.inventory, {}, [tool.id]):
            return "fail:missing_items"
    else:
        assert req.item is not None
        n = min(req.amount or 1, p.inventory.count(req.item))
        if n <= 0 or not transfer_items(world, p.inventory, who.inventory, {req.item: n}, []):
            return "fail:missing_items"
        note_transfer(world, p.id, who.id, req.item, n)
    core.note_helped(world, p, act, who.id, "gift", tick)
    if who.id in world.players:
        wellbeing.change_trust(world, who.id, p.id, cfg.social.gift_trust_gain)
        wellbeing.add_gain(world, who.id, cfg.wellbeing.gift_gain, "gift", tick)
    else:
        who.bond[p.id] = min(100.0, who.bond.get(p.id, cfg.villagers.bond_start_other) + 5)
        who.loyalty = min(100.0, who.loyalty + 2) if who.leader == p.id else who.loyalty
    return "done"


# ---------------------------------------------------------------------------------- promise


def _promise_begin(world: World, p: Player, req: ActionRequest, tick: int):
    spec = req.promise
    if spec is None:
        return "needs_promise"
    if spec.to not in world.players or spec.to == p.id:
        return "no_such_target"
    if spec.kind == "give" and (spec.item is None or spec.amount is None):
        return "bad_promise"
    if spec.due_tick <= tick:
        return "due_in_past"
    return Plan()


def _promise_unit(world: World, p: Player, act: ActiveAction, tick: int) -> str:
    spec = act.request.promise
    assert spec is not None
    pid = world.next("promise")
    world.promises[pid] = Promise(pid, p.id, spec.to, spec.kind, spec.item, spec.amount,
                                  spec.due_tick, act.request.text or "", tick)  # fmt: skip
    world.emit(
        PromiseMade(id=pid, maker=p.id, to=spec.to, kind=spec.kind, text=act.request.text or ""),
        tick,
    )
    if act.request.text:
        world.utterances.append(Utterance(p.id, [spec.to], act.request.text, "talk", pid))
    return "done"


def _close_promise(world: World, pr: Promise, kept: bool, tick: int, reason: str = "") -> None:
    cfg = world.cfg.balance
    pr.status = "kept" if kept else "broken"
    if kept:
        world.emit(PromiseKept(id=pr.id, maker=pr.maker, to=pr.to), tick)
        wellbeing.change_trust(world, pr.to, pr.maker, cfg.social.promise_kept_trust)
        wellbeing.add_gain(world, pr.to, cfg.wellbeing.promise_kept_gain, "promise_kept", tick)
    else:
        world.emit(PromiseBroken(id=pr.id, maker=pr.maker, to=pr.to, reason=reason), tick)
        wellbeing.change_trust(world, pr.to, pr.maker, -cfg.social.promise_broken_trust)
        wellbeing.add_gain(world, pr.to, -cfg.wellbeing.promise_broken_blow, "promise_broken", tick)


def check_promises(world: World, tick: int) -> None:
    """At the due tick a promise is kept or broken."""
    for pr in sorted(world.promises.values(), key=lambda q: q.id):
        if pr.status != "open" or tick < pr.due_tick:
            continue
        if pr.kind == "give":
            _close_promise(world, pr, pr.given >= (pr.amount or 0), tick, "not_given")
        else:
            _close_promise(world, pr, True, tick)


def on_harm(world: World, actor: str, victim: str, tick: int) -> None:
    """A harm by the promiser breaks an open "not_harm" promise to the victim."""
    for pr in sorted(world.promises.values(), key=lambda q: q.id):
        if pr.status == "open" and pr.kind == "not_harm" and pr.maker == actor and pr.to == victim:
            _close_promise(world, pr, False, tick, "harmed")


# ------------------------------------------------------------------------ recruit, teach


def _recruit_begin(world: World, p: Player, req: ActionRequest, tick: int):
    v = world.villagers.get(req.target or "")
    if v is None or not v.alive or v.leader is not None:
        return "not_a_wanderer"
    attached = sum(1 for q in world.villagers.values() if q.leader == p.id)
    if attached >= p.slots:
        return "no_free_slot"
    return Plan(goal=(v.x, v.y), reach=1)


def attach(world: World, v, pid: str, tick: int, source: str, loyalty: float) -> None:
    v.leader = pid
    v.loyalty = loyalty
    v.captive = False
    v.captor = None
    v.job = None
    v.route, v.route_index = [], 0
    v.bond.setdefault(pid, world.cfg.balance.villagers.bond_start_other)
    world.emit(VillagerJoined(villager=v.id, leader=pid, source=source), tick)


def _recruit_unit(world: World, p: Player, act: ActiveAction, tick: int) -> str:
    v = world.villagers.get(act.request.target or "")
    if v is None or v.leader is not None:
        return "fail:not_a_wanderer"
    if core.manhattan((p.x, p.y), (v.x, v.y)) > 2:
        return "fail:too_far"
    if world.streams.get("actions.social").random() < world.cfg.balance.social.recruit_chance:
        attach(world, v, p.id, tick, "recruit", world.cfg.balance.villagers.recruit_loyalty)
        return "done"
    return "refused"


def add_knowledge(world: World, who: Player, subject: str, claim: str, conf: float,
                  source: str, tick: int, true: bool | None) -> KnowledgeEntry:  # fmt: skip
    entry = KnowledgeEntry(world.next("knowledge"), subject, claim, conf, source, tick, true)
    who.knowledge.append(entry)
    return entry


def _teach_begin(world: World, p: Player, req: ActionRequest, tick: int):
    other = world.players.get(req.target or "")
    if other is None or other.id == p.id or not other.alive:
        return "no_such_target"
    if not near(world, p, other):
        return "too_far"
    if req.amount is not None:
        if not any(k.id == req.amount for k in p.knowledge):
            return "unknown_entry"
    elif not req.text:
        return "nothing_to_teach"
    return Plan()


def _teach_unit(world: World, p: Player, act: ActiveAction, tick: int) -> str:
    req = act.request
    cfg = world.cfg.balance.social
    other = world.players.get(req.target or "")
    if other is None or not other.alive or not near(world, p, other):
        return "fail:too_far"
    entry = next((k for k in p.knowledge if k.id == req.amount), None) if req.amount else None
    if entry is not None:
        subject, claim, conf, true = entry.subject, entry.claim, entry.confidence, entry.true
    else:
        subject, claim = req.item or "claim", req.text or ""
        conf, true = cfg.default_confidence, False
    taught = add_knowledge(world, other, subject, claim, conf * cfg.teach_confidence_factor,
                           f"taught:{p.id}", tick, true)  # fmt: skip
    core.note_helped(world, p, act, other.id, "teach", tick)
    for q in sorted(world.players.values(), key=lambda z: z.id):
        if q.id in (p.id, other.id) or not q.alive or not near(world, p, q):
            continue
        add_knowledge(world, q, subject, claim, conf * cfg.overheard_confidence_factor,
                      f"overheard:{p.id}", tick, true)  # fmt: skip
    world.utterances.append(Utterance(p.id, [other.id], f"{subject}: {claim}", "teach", taught.id))
    return "done"


# -------------------------------------------------------------------------------- guard


def _guard_begin(world: World, p: Player, req: ActionRequest, tick: int):
    plan = Plan(data={"minutes": req.minutes or 120, "watched": 0})
    if req.x is not None and req.y is not None:
        if not world.inside(req.x, req.y):
            return "off_map"
        plan.goal = (req.x, req.y)
        plan.reach = 0
    return plan


def _guard_unit(world: World, p: Player, act: ActiveAction, tick: int) -> str:
    act.data["watched"] += 60
    return "done" if act.data["watched"] >= act.data["minutes"] else "more"


def guards_near(world: World, pos, radius: int, tick: int, exclude: str | None = None) -> bool:
    """Is anyone (a guarding player or a guarding villager) watching within ``radius``?"""
    r2 = radius * radius
    for q in world.players.values():
        a = q.action
        if q.alive and q.id != exclude and a is not None and a.request.kind == "guard":
            if a.status == "working" and (q.x - pos[0]) ** 2 + (q.y - pos[1]) ** 2 <= r2:
                return True
    for v in world.villagers.values():
        if v.alive and v.job == "guard" and v.leader != exclude and v.leader is not None:
            if (v.x - pos[0]) ** 2 + (v.y - pos[1]) ** 2 <= r2:
                return True
    return False


# --------------------------------------------------------------------------------- belief


def _belief_begin(world: World, p: Player, req: ActionRequest, tick: int):
    return Plan()


def _belief_unit(kind: str):
    def unit(world: World, p: Player, act: ActiveAction, tick: int) -> str:
        world.emit(
            BeliefAct(player=p.id, kind=kind, text=act.request.text or "", x=p.x, y=p.y), tick
        )
        return "done"

    return unit


def _offering_begin(world: World, p: Player, req: ActionRequest, tick: int):
    if req.item is None or p.inventory.count(req.item) == 0:
        return "missing_items"
    return Plan()


def _offering_unit(world: World, p: Player, act: ActiveAction, tick: int) -> str:
    item = act.request.item
    assert item is not None
    n = min(act.request.amount or 1, p.inventory.count(item))
    if n <= 0 or not p.inventory.remove(item, n):
        return "fail:missing_items"
    world.emit(BeliefAct(player=p.id, kind="offering", text=f"{item} x{n}", x=p.x, y=p.y), tick)
    return "done"


register(Spec("talk", _talk_begin, _talk_unit, physical=False))
register(Spec("trade", _offer_begin("trade"), _offer_unit("trade"), physical=False))
register(Spec("ally", _offer_begin("ally"), _offer_unit("ally"), physical=False))
register(Spec("gift", _gift_begin, _gift_unit, physical=False))
register(Spec("promise", _promise_begin, _promise_unit, physical=False))
register(Spec("recruit", _recruit_begin, _recruit_unit, physical=False))
register(Spec("teach", _teach_begin, _teach_unit, physical=False))
register(Spec("guard", _guard_begin, _guard_unit, outdoor=True, physical=False))
register(Spec("pray", _belief_begin, _belief_unit("pray"), physical=False))
register(Spec("ceremony", _belief_begin, _belief_unit("ceremony"), physical=False))
register(Spec("offering", _offering_begin, _offering_unit, physical=False))
