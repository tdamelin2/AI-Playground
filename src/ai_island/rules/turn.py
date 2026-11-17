"""The per-minute turn: bodies, fires, senses, decisions, actions, villagers, dogs, chat.

``run_turn`` is called every tick by the recurring ``turn`` scheduler job (through
``world.turn_handler``). ``decide`` maps a DecisionContext to an ActionRequest or None.
"""

from __future__ import annotations

import importlib
import statistics
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ai_island.rules import body, interrupts, land, wellbeing
from ai_island.rules.actions import core as actions_core
from ai_island.rules.actions import fire as fire_mod
from ai_island.rules.actions import social
from ai_island.rules.actions.build import storm_damage
from ai_island.rules.actions.core import cancel_action, player_order, resolve, start_action
from ai_island.rules.actions.request import ActionRequest
from ai_island.storage.events import PlayerDay
from ai_island.world import dogs as dogs_mod
from ai_island.world import villagers
from ai_island.world.agents import Interrupt
from ai_island.world.state import Pos, World

ORDER_TURN = 8


@dataclass
class OwnView:
    """What a player knows about itself: nothing exact, no raw poison kinds."""

    position: Pos
    inventory: dict[str, int]
    tools: list[dict[str, Any]]
    task_stage: int
    own_tasks: list[str]
    body_words: list[str]
    known_places: list[tuple[str, int, int]]
    villagers: list[str] = field(default_factory=list)


@dataclass
class DecisionContext:
    tick: int
    player_id: str
    reason: str  # idle | finished | interrupt | check
    interrupts: list[Interrupt]
    report: Any
    own: OwnView
    trigger: str = "finished"  # finished | spoken_to | interrupt | check
    x: float = 0.0  # the player's wellbeing now
    hooked: bool = False
    feeling: str = ""


Decide = Callable[[DecisionContext], ActionRequest | None]
DecideMany = Callable[[list[DecisionContext]], dict[str, ActionRequest | None]]


def trigger_of(reason: str, taken: list[Interrupt]) -> str:
    """The contract's four triggers: idle maps to finished; spoken_to wins among interrupts."""
    if reason == "interrupt":
        return "spoken_to" if any(i.kind == "spoken_to" for i in taken) else "interrupt"
    return "check" if reason == "check" else "finished"


_HOOKS: dict[tuple[str, str], Callable[..., Any] | None] = {}


def _hook(module: str, name: str) -> Callable[..., Any] | None:
    """A function from coder B's modules, or None while that module does not exist yet."""
    key = (module, name)
    if key not in _HOOKS:
        try:
            _HOOKS[key] = getattr(importlib.import_module(module), name, None)
        except ImportError:
            _HOOKS[key] = None
    return _HOOKS[key]


def body_words(world: World, pid: str) -> list[str]:
    b = world.players[pid].body
    words: list[str] = []
    if b.hunger >= 85:
        words.append("starving")
    elif b.hunger >= 60:
        words.append("hungry")
    if b.thirst >= 85:
        words.append("parched")
    elif b.thirst >= 60:
        words.append("thirsty")
    if b.cold >= 70:
        words.append("freezing")
    elif b.cold >= 45:
        words.append("cold")
    if b.fatigue >= 80:
        words.append("exhausted")
    elif b.fatigue >= 55:
        words.append("tired")
    if b.pain >= 50:
        words.append("in pain")
    elif b.pain >= 20:
        words.append("sore")
    if b.sickness is not None:
        words.append("sick")
    if b.health < 40:
        words.append("badly hurt")
    return words


def own_view(world: World, pid: str, tick: int) -> OwnView:
    p = world.players[pid]
    lines = _hook("ai_island.rules.tasks", "task_lines")
    home = world.homes[p.index - 1].anchor
    places = [("home", home[0], home[1])]
    places += [
        (s.kind, s.x, s.y)
        for s in sorted(world.structures.values(), key=lambda q: q.id)
        if s.owner == pid
    ]
    return OwnView(
        position=(p.x, p.y),
        inventory=p.inventory.counts(),
        tools=[
            {"id": t.id, "kind": t.kind, "tier": t.tier, "durability": t.durability}
            for t in p.inventory.tools
        ],
        task_stage=p.task_stage,
        own_tasks=list(lines(world, pid)) if lines else [],
        body_words=body_words(world, pid),
        known_places=places,
        villagers=sorted(v.id for v in world.villagers.values() if v.leader == pid),
    )


def update_fire_zone(world: World, tick: int) -> None:
    r = world.cfg.balance.fire.dog_scare_radius
    zone: set[Pos] = set()
    for s in fire_mod.burning_fires(world, tick):
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                if dx * dx + dy * dy <= r * r:
                    zone.add((s.x + dx, s.y + dy))
    world.fire_zone = zone


def _decide_players(
    world: World, tick: int, decide: Decide | None, decide_many: DecideMany | None = None
) -> None:
    if decide is None and decide_many is None:
        return
    cfg = world.cfg.balance.turn
    build_report = _hook("ai_island.rules.senses", "build_report")
    contexts: list[DecisionContext] = []
    for pid in player_order(world, tick):
        p = world.players[pid]
        if not p.alive:
            continue
        pending = interrupts.pending(world, pid)
        if pending:
            reason = "interrupt"
        elif p.action is None:
            if tick - p.last_decision_tick < cfg.idle_retry_ticks and not p.just_finished:
                continue
            reason = "finished" if p.just_finished else "idle"
        elif tick - p.last_decision_tick >= cfg.check_minutes and not p.sleeping:
            reason = "check"
        else:
            continue
        taken = interrupts.take_interrupts(world, pid)
        report = build_report(world, pid, tick) if build_report else None
        ctx = DecisionContext(
            tick,
            pid,
            reason,
            taken,
            report,
            own_view(world, pid, tick),
            trigger=trigger_of(reason, taken),
            x=float(wellbeing.x_of(world, pid, tick)),
            hooked=wellbeing.is_hooked(world, pid),
            feeling=str(getattr(report, "feeling", "") or ""),
        )
        p.last_decision_tick = tick
        p.just_finished = False
        if decide_many is not None:
            contexts.append(ctx)
            continue
        assert decide is not None
        request = decide(ctx)
        if request is not None:
            start_action(world, pid, request, tick)
    if decide_many is not None and contexts:
        requests = decide_many(contexts)
        for ctx in contexts:  # player_order, never completion order
            request = requests.get(ctx.player_id)
            if request is not None:
                start_action(world, ctx.player_id, request, tick)


def _storm_transition(world: World, tick: int) -> None:
    now = world.weather.current
    if now != world.last_weather_flags:
        world.last_weather_flags = now
        if now == "storm":
            for pid in sorted(world.players):
                interrupts.raise_interrupt(world, "storm_started", pid, tick)


def food_in_zone(world: World, zone: str) -> float:
    """Obtainable safe food (food units) in a home zone: plants, animals, ready crops."""
    cfg = world.cfg.balance
    vals = cfg.food.values
    total = 0.0
    for s in world.plants:
        if s.present and s.kind in villagers.WORK_FOOD_PLANTS and world.zone_at(s.x, s.y) == zone:
            total += vals[s.kind]
    for kind, group in world.animals.items():
        if kind == "fish" or kind not in cfg.actions.hunt_yield:
            continue
        unit = vals["eggs"] if kind == "nest_eggs" else vals["raw_meat"]
        total += sum(
            cfg.actions.hunt_yield[kind] * unit for a in group if a.zone == zone and not a.pen
        )
    ready = sum(
        1
        for y, row in enumerate(world.terrain)
        for x, t in enumerate(row)
        if t == "farmland_ready" and world.zone_at(x, y) == zone
    )
    return total + ready * cfg.actions.crop_yield * vals["crops"]


def _daily(world: World, tick: int) -> None:
    cfg = world.cfg.balance
    clock = world.cfg.world.clock
    day = tick // clock.ticks_per_day
    villagers.daily(world, tick)
    for pid in sorted(world.players):
        p = world.players[pid]
        hourly = list(p.x_hourly)
        if not hourly:
            hourly = [round(wellbeing.x_of(world, pid, tick), 3)]
        while len(hourly) < 24:
            hourly.append(hourly[-1])
        hourly = hourly[:24]
        mean = p.x_minute_sum / p.x_minutes if p.x_minutes else hourly[-1]
        mates = [v for v in world.villagers.values() if v.leader == pid]
        stored = p.home_store.food_units() + sum(
            s.store.food_units() for s in world.structures.values() if s.owner == pid and s.store
        )
        zone = f"home_{p.index - 1}"
        world.emit(
            PlayerDay(
                player=pid,
                day=day,
                x_hourly=hourly,
                x_mean=round(mean, 3),
                x_median=round(statistics.median(hourly), 3),
                band=p.band,
                home_food_units=round(food_in_zone(world, zone) + stored, 3),
                household_need=round((1 + len(mates)) * cfg.food.food_per_day, 3),
                food_stored=round(stored, 3),
                villagers=len(mates),
                alive=p.alive,
            ),
            tick,
        )
        p.x_minute_sum, p.x_minutes, p.x_hourly = 0.0, 0, []
        p.x_hour_sum, p.x_hour_n = 0.0, 0


def run_turn(
    world: World,
    tick: int,
    decide: Decide | None,
    decide_many: DecideMany | None = None,
) -> None:
    """One game minute for all people."""
    cfg = world.cfg.balance
    actions_core.walk_players(world, tick)
    if tick % cfg.body.interval_ticks == 0:
        body.update_bodies(world, tick)
    if tick % cfg.fire.sweep_interval_ticks == 0:
        fire_mod.sweep_fires(world, tick)
        update_fire_zone(world, tick)
    if tick % cfg.fire.spoil_sweep_ticks == 0:
        fire_mod.sweep_spoilage(world, tick)
        storm_damage(world, tick)
        social.expire_offers(world, tick)
        social.check_promises(world, tick)
    _storm_transition(world, tick)
    detect = _hook("ai_island.rules.senses", "detect_sight_interrupts")
    if detect:
        detect(world, tick)
    _decide_players(world, tick, decide, decide_many)
    resolve(world, tick)
    villagers.run_villagers(world, tick)
    if tick % cfg.dog_attack.interval_ticks == 0:
        dogs_mod.run_dog_attacks(world, tick)
    for name, module in (
        ("run_chat_phase", "ai_island.rules.senses"),
        ("record_witnesses", "ai_island.rules.senses"),
    ):
        fn = _hook(module, name)
        if fn:
            fn(world, tick)
    world.utterances.clear()
    if tick % cfg.tasks.check_interval_ticks == 0:
        fn = _hook("ai_island.rules.tasks", "check_tasks")
        if fn:
            fn(world, tick)
    fn = _hook("ai_island.rules.landmarks", "check_landmarks")
    if fn:
        fn(world, tick)
    if tick % world.cfg.world.clock.ticks_per_day == 0 and tick > 0:
        _daily(world, tick)


__all__ = [
    "DecisionContext",
    "OwnView",
    "cancel_action",
    "land",
    "run_turn",
]
