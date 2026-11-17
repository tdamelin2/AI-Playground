"""Wellbeing X: concave comforts, an adapting gain/blow term B, bands and multipliers.

X = clamp(sum(w_i * f(c_i, k)) + B, 0, 100) where f(c, k) = log(1 + k*c) / log(1 + k) and
B halves every ``half_life_ticks``. Players never see the number, only the band words.
"""

from __future__ import annotations

import math

from ai_island.storage.events import XGain
from ai_island.world.agents import BAND_EDGES, BAND_NAMES, Player
from ai_island.world.state import World

COMFORT_KEYS: tuple[str, ...] = (
    "food",
    "water",
    "warmth",
    "rest",
    "health",
    "shelter",
    "safety",
    "achievement",
    "belonging",
)


def f(c: float, k: float) -> float:
    """Concave comfort curve: f(0) = 0, f(1) = 1, rising ever more slowly."""
    c = min(1.0, max(0.0, c))
    return math.log(1.0 + k * c) / math.log(1.0 + k)


def band_index(x: float, edges: list[float] | None = None) -> int:
    edges = BAND_EDGES if edges is None else edges
    for i, edge in enumerate(edges):
        if x >= edge:
            return i
    return len(edges)


def band_of(x: float) -> str:
    """The band name for an X value (design.md bands: 80+, 60+, 40+, 20+, below)."""
    return BAND_NAMES[band_index(x)]


def b_now(world: World, p: Player, tick: int | None = None) -> float:
    """B after fading by its half-life since it was last touched."""
    now = world.tick if tick is None else tick
    half = world.cfg.balance.wellbeing.half_life_ticks
    return p.b * 2.0 ** (-(max(0, now - p.b_tick)) / half)


def _settle(world: World, p: Player, tick: int) -> None:
    p.b = b_now(world, p, tick)
    p.b_tick = tick


def house_count(world: World, pid: str) -> int:
    return sum(
        1 for s in world.structures.values() if s.kind == "house" and s.complete and s.owner == pid
    )


def household(world: World, pid: str) -> list:
    return [v for v in world.villagers.values() if v.leader == pid and v.alive]


def comforts(world: World, pid: str, tick: int | None = None) -> dict[str, float]:
    now = world.tick if tick is None else tick
    p = world.players[pid]
    wb = world.cfg.balance.wellbeing
    b = p.body
    mates = household(world, pid)
    loyalty = sum(v.loyalty for v in mates) / len(mates) if mates else 0.0
    others = [t for key, t in p.trust.items() if key != pid]
    trust = sum(others) / len(others) if others else wb.start_trust
    belong = 0.5 * min(1.0, len(mates) / 3.0) * loyalty / 100.0 + 0.5 * trust / 100.0
    shelter = wb.shelter_base + (1.0 - wb.shelter_base) * (1.0 if house_count(world, pid) else 0.0)
    danger = 0.5 * b.pain / 100.0 + (0.4 if now - p.last_harm_tick < 1440 else 0.0)
    for dog in world.dogs:
        if abs(dog.x - p.x) + abs(dog.y - p.y) <= 6:
            danger += 0.2
            break
    sick = 0.1 if b.sickness else 0.0
    return {
        "food": 1.0 - b.hunger / 100.0,
        "water": 1.0 - b.thirst / 100.0,
        "warmth": 1.0 - b.cold / 100.0,
        "rest": 1.0 - b.fatigue / 100.0,
        "health": max(0.0, b.health / 100.0 * (1.0 - 0.5 * b.pain / 100.0) - sick),
        "shelter": shelter,
        "safety": max(0.0, 1.0 - danger),
        "achievement": min(1.0, max(0, p.task_stage - 1) / wb.achievement_stages),
        "belonging": min(1.0, max(0.0, belong)),
    }


def x_core(world: World, pid: str, tick: int | None = None) -> float:
    """The weighted sum of concave comforts, without B."""
    wb = world.cfg.balance.wellbeing
    c = comforts(world, pid, tick)
    return sum(wb.weights[key] * f(c[key], wb.k) for key in COMFORT_KEYS)


def x_of(world: World, pid: str, tick: int | None = None) -> float:
    """The player's hidden wellbeing, 0 to 100."""
    p = world.players[pid]
    x = x_core(world, pid, tick) + b_now(world, p, tick)
    return min(100.0, max(0.0, x))


def add_gain(world: World, pid: str, amount: float, reason: str, tick: int) -> None:
    """Add a gain (positive) or a blow (negative) to B after fading it to ``tick``."""
    p = world.players.get(pid)
    if p is None or not p.alive or amount == 0:
        return
    _settle(world, p, tick)
    p.b = min(100.0, max(-100.0, p.b + amount))
    world.emit(XGain(player=pid, amount=round(amount, 3), reason=reason), tick)


def speed_mult(world: World, who: Player | str) -> float:
    p = world.players[who] if isinstance(who, str) else who
    return world.cfg.balance.wellbeing.speed_mult[band_index(x_of(world, p.id))]


def work_mult(world: World, who: Player | str) -> float:
    p = world.players[who] if isinstance(who, str) else who
    mult = world.cfg.balance.wellbeing.work_mult[band_index(x_of(world, p.id))]
    if p.body.sickness:
        mult *= world.cfg.balance.body.sickness[p.body.sickness].work_penalty
    return mult


def is_hooked(world: World, pid: str) -> bool:
    wb = world.cfg.balance.wellbeing
    return x_of(world, pid) < wb.hooked_x or world.players[pid].body.pain >= wb.hooked_pain


def fade_relationships(world: World, dt_ticks: int) -> None:
    """Trust and anger drift toward neutral."""
    wb = world.cfg.balance.wellbeing
    day = world.cfg.world.clock.ticks_per_day
    t_step = wb.trust_fade_per_day * dt_ticks / day
    a_step = wb.anger_fade_per_day * dt_ticks / day
    for p in world.players.values():
        for key, value in p.trust.items():
            if value > wb.trust_neutral:
                p.trust[key] = max(wb.trust_neutral, value - t_step)
            elif value < wb.trust_neutral:
                p.trust[key] = min(wb.trust_neutral, value + t_step)
        for key, value in p.anger.items():
            if value > wb.anger_neutral:
                p.anger[key] = max(wb.anger_neutral, value - a_step)
            elif value < wb.anger_neutral:
                p.anger[key] = min(wb.anger_neutral, value + a_step)


def change_trust(world: World, pid: str, other: str, delta: float) -> None:
    p = world.players.get(pid)
    if p is None or other == pid or other not in p.trust:
        return
    p.trust[other] = min(100.0, max(0.0, p.trust[other] + delta))


def change_anger(world: World, pid: str, other: str, delta: float) -> None:
    p = world.players.get(pid)
    if p is None or other == pid or other not in p.anger:
        return
    p.anger[other] = min(100.0, max(0.0, p.anger[other] + delta))
