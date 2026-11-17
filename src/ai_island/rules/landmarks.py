"""Landmark holding and the weekly dominance bonus.

A minute is exclusive when every live person within ``landmark_radius`` of a landmark belongs to
one player (the player, or its villagers with loyalty >= 30). At the end of each fixed game-week
window the sole owner of more than ``hold_share`` of the window's minutes gets
``dominance_bonus`` once for that landmark. The tallies live in the first player's
``place_memory`` so they survive a save.
"""

from __future__ import annotations

from typing import Any

from ai_island.rules.senses.common import emit, setting

KEY = "_landmarks"


def _belongs_to(world: Any, villager: Any, min_loyalty: float) -> str | None:
    if villager.leader is not None and villager.loyalty >= min_loyalty:
        return villager.leader
    return None


def _state(world: Any) -> dict[str, Any] | None:
    if not world.players:
        return None
    first = world.players[sorted(world.players)[0]]
    return first.place_memory.setdefault(KEY, {"window": 0, "minutes": {}})


def window_ticks(world: Any) -> int:
    return int(setting(world, "window_ticks"))


def _tally_minute(world: Any, state: dict[str, Any]) -> None:
    radius = int(setting(world, "landmark_radius"))
    r2 = radius * radius
    min_loyalty = float(setting(world, "loyal_threshold"))
    people: list[tuple[int, int, str | None]] = []
    for pid, p in world.players.items():
        if p.alive:
            people.append((p.x, p.y, pid))
    for v in world.villagers.values():
        if v.alive:
            people.append((v.x, v.y, _belongs_to(world, v, min_loyalty)))
    for mark in world.landmarks:
        owners: set[str | None] = set()
        for x, y, owner in people:
            if (x - mark.x) ** 2 + (y - mark.y) ** 2 <= r2:
                owners.add(owner)
                if len(owners) > 1:
                    break
        if len(owners) == 1:
            (owner,) = owners
            if owner is not None:
                per = state["minutes"].setdefault(mark.kind, {})
                per[owner] = per.get(owner, 0) + 1


def _close_window(world: Any, state: dict[str, Any], tick: int) -> None:
    total = window_ticks(world)
    share = float(setting(world, "hold_share"))
    bonus = float(setting(world, "dominance_bonus"))
    from ai_island.rules.wellbeing import add_gain

    for kind in sorted(state["minutes"]):
        for pid, minutes in sorted(state["minutes"][kind].items()):
            if minutes > share * total and pid in world.players:
                add_gain(world, pid, bonus, f"dominance:{kind}", tick)
                emit(
                    world,
                    "dominance_bonus",
                    tick,
                    player=pid,
                    landmark=kind,
                    kind=kind,
                    week=state["window"],
                    minutes=minutes,
                    amount=bonus,
                )
    state["minutes"] = {}


def check_landmarks(world: Any, tick: int) -> None:
    """Count this minute; at a window boundary pay out the finished week."""
    state = _state(world)
    if state is None:
        return
    window = tick // window_ticks(world)
    if window != state["window"]:
        _close_window(world, state, tick)
        state["window"] = window
    _tally_minute(world, state)


def landmark_holder(world: Any, kind: str) -> str | None:
    """The player leading the current week's tally for ``kind`` (None if nobody)."""
    state = _state(world)
    if state is None:
        return None
    per = state["minutes"].get(kind, {})
    return max(sorted(per), key=lambda p: per[p]) if per else None


__all__ = ["check_landmarks", "landmark_holder", "window_ticks"]
