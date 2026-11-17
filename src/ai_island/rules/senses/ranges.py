"""What an observer can see and hear. Distance is Euclidean (dx*dx + dy*dy <= r*r), no occlusion."""

from __future__ import annotations

from typing import Any

from ai_island.rules.senses.common import Pos, actor, dist2, pos_of, setting
from ai_island.world.clock import is_night_at


def burning_fires(world: Any, tick: int) -> list[Pos]:
    """Tiles of finished fires (campfire or hearth) that still have fuel."""
    return [
        (s.x, s.y)
        for s in world.structures.values()
        if s.kind in ("campfire", "hearth") and s.complete and s.fuel_until > tick
    ]


def sight_range(world: Any, observer_id: str, tick: int) -> int:
    """How many tiles ``observer_id`` can see now: less at night and in a storm."""
    base = int(setting(world, "sight_tiles"))
    who = actor(world, observer_id)
    night = is_night_at(tick, world.cfg.world.clock)
    if world.weather.current == "storm":
        base = min(base, int(setting(world, "storm_sight_tiles")))
    if night:
        base = min(base, int(setting(world, "night_sight_tiles")))
        if who is not None:
            radius = int(setting(world, "fire_light_radius"))
            here = pos_of(who)
            if any(dist2(here, fire) <= radius * radius for fire in burning_fires(world, tick)):
                base = max(base, int(setting(world, "fire_night_sight")))
    return base


def can_see(world: Any, observer_id: str, pos: Pos, tick: int) -> bool:
    who = actor(world, observer_id)
    if who is None:
        return False
    r = sight_range(world, observer_id, tick)
    return dist2(pos_of(who), pos) <= r * r


def can_hear(world: Any, speaker_pos: Pos, listener_pos: Pos) -> bool:
    r = int(setting(world, "hearing_tiles"))
    return dist2(speaker_pos, listener_pos) <= r * r
