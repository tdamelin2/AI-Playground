"""The sense report a player gets before it decides: what it sees, hears and feels in words.

Nothing here shows another player's X, stores or tasks, an internal poison kind, or an exact
number for the player's own X. Structured extras (``seen``, ``places``, ``needs``...) carry the
same facts for rule-based players; they use appearance names only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ai_island.rules.senses.common import Pos, dist2, pos_of
from ai_island.rules.senses.memory import refresh_memory, remembered_positions, tiles_in_sight
from ai_island.rules.senses.ranges import sight_range
from ai_island.rules.senses.templates import (
    ANIMAL_NAMES,
    APPEARANCE,
    FEELING_WORDS,
    ITEM_NAMES,
    LEVEL_WORDS,
    STRUCTURE_NAMES,
    TERRAIN_NAMES,
    WEATHER_WORDS,
    render,
)

# Where a 0..100 need or pain value turns into the next word (ok, mild, strong, severe).
LEVEL_CUTS: tuple[int, int, int] = (25, 50, 75)
MAX_SIGHTS = 14
WATER_TERRAIN = frozenset({"spring", "lake"})
REMEMBERED_PLACES = 4


@dataclass(frozen=True)
class Seen:
    """One thing in sight. ``look`` is its appearance name; ``kind`` is the sort of thing."""

    kind: str  # plant | animal | dog | player | villager | structure | terrain | drop
    look: str
    x: int
    y: int
    ident: str = ""
    owner: str = ""


@dataclass(frozen=True)
class SenseReport:
    tick: int
    sights: tuple[str, ...]
    sounds: tuple[str, ...]
    body: tuple[str, ...]
    feeling: str
    text: str
    position: Pos = (0, 0)
    home: Pos = (0, 0)
    carried: dict[str, int] = field(default_factory=dict)
    needs: dict[str, int] = field(default_factory=dict)  # level 0..3 per need word
    sick: bool = False
    seen: tuple[Seen, ...] = ()
    places: dict[str, tuple[Pos, ...]] = field(default_factory=dict)  # remembered, e.g. "water"
    stored: dict[str, int] = field(default_factory=dict)  # the player's own home store


def _level(value: float) -> int:
    return sum(1 for cut in LEVEL_CUTS if value >= cut)


def feeling_words(world: Any, pid: str) -> str:
    """The felt band as words (design.md table), never the number."""
    from ai_island.rules.wellbeing import band_of, x_of
    from ai_island.world.agents import BAND_NAMES

    return FEELING_WORDS[BAND_NAMES.index(band_of(float(x_of(world, pid))))]


def body_words(body: Any) -> tuple[tuple[str, ...], dict[str, int], bool]:
    """Words for hunger, thirst, cold, tiredness, pain, sickness and hurt, plus levels."""
    needs = {
        "hunger": _level(body.hunger),
        "thirst": _level(body.thirst),
        "cold": _level(body.cold),
        "fatigue": _level(body.fatigue),
        "pain": _level(body.pain),
    }
    words = [LEVEL_WORDS[name][level] for name, level in needs.items() if level > 0]
    sick = body.sickness is not None
    if sick:
        words.append("Your stomach churns and you feel unwell.")
    if body.health < 50:
        words.append("You feel weak and hurt.")
    return tuple(words), needs, sick


def _gather_seen(world: Any, pid: str, tick: int) -> list[Seen]:
    me = world.players[pid]
    here = pos_of(me)
    radius = sight_range(world, pid, tick)
    r2 = radius * radius
    seen: list[Seen] = []
    for p in world.plants:
        if p.present and dist2(here, (p.x, p.y)) <= r2:
            seen.append(Seen("plant", APPEARANCE[p.kind], p.x, p.y))
    for group in world.animals.values():
        for a in group:
            if dist2(here, (a.x, a.y)) <= r2:
                seen.append(Seen("animal", ANIMAL_NAMES[a.kind], a.x, a.y, str(a.id)))
    for d in world.dogs:
        if dist2(here, (d.x, d.y)) <= r2:
            seen.append(Seen("dog", "a wild dog", d.x, d.y, f"dog_{d.id}"))
    for oid, other in world.players.items():
        if oid != pid and other.alive and dist2(here, pos_of(other)) <= r2:
            seen.append(Seen("player", other.name, other.x, other.y, oid))
    for vid, v in world.villagers.items():
        if v.alive and dist2(here, pos_of(v)) <= r2:
            seen.append(Seen("villager", "a villager", v.x, v.y, vid, v.leader or ""))
    for s in world.structures.values():
        if dist2(here, (s.x, s.y)) <= r2:
            name = STRUCTURE_NAMES.get(s.kind, "a building")
            if not s.complete:
                name = f"an unfinished {name.split(' ', 1)[-1]}"
            seen.append(Seen("structure", name, s.x, s.y, str(s.id), s.owner or ""))
    for pos in world.drops:
        if dist2(here, pos) <= r2:
            seen.append(Seen("drop", "things on the ground", pos[0], pos[1]))
    best: dict[str, tuple[int, Seen]] = {}
    for x, y in tiles_in_sight(world, here, radius):
        terrain = world.terrain[y][x]
        if terrain in TERRAIN_NAMES:
            d2 = dist2(here, (x, y))
            if terrain not in best or d2 < best[terrain][0]:
                best[terrain] = (d2, Seen("terrain", TERRAIN_NAMES[terrain], x, y, terrain))
    seen.extend(entry[1] for _, entry in sorted(best.items()))
    seen.sort(key=lambda s: (dist2(here, (s.x, s.y)), s.kind, s.look, s.ident))
    return seen


def build_report(world: Any, pid: str, tick: int) -> SenseReport:
    """The report for ``pid`` at ``tick``. Same seed and state give the same words."""
    me = world.players[pid]
    refresh_memory(world, pid, tick)
    seed = world.streams.seed
    seen = _gather_seen(world, pid, tick)
    sights: list[str] = []
    for item in seen[:MAX_SIGHTS]:
        what = item.look
        where = f"({item.x}, {item.y})"
        subject = f"{item.kind}:{item.ident or item.look}:{item.x},{item.y}"
        sights.append(
            render(seed, pid, tick, item.kind, subject, what=what, where=where, text=what)
        )
    weather = WEATHER_WORDS.get(world.weather.current, world.weather.current)
    sights.append(render(seed, pid, tick, "weather", world.weather.current, what=weather))

    memory = me.place_memory
    last = memory.get("last_report", -1)
    sounds = [
        render(seed, pid, t, "sound", f"{who}:{t}", who=who, text=text)
        for t, who, text in memory.get("heard", [])
        if t > last
    ]
    memory["last_report"] = tick

    words, needs, sick = body_words(me.body)
    body_lines = [render(seed, pid, tick, "body", w, text=w) for w in words]
    feeling = feeling_words(world, pid)
    feeling_line = render(seed, pid, tick, "feeling", feeling, text=feeling)

    water = remembered_positions(world, pid, WATER_TERRAIN)
    here = pos_of(me)
    water.sort(key=lambda p: (dist2(here, p), p))
    home = world.homes[me.index - 1].anchor
    carried = {kind: n for kind in ITEM_NAMES if (n := int(me.inventory.count(kind)))}
    for tool in me.inventory.tools:
        key = f"tool_{tool.kind}"
        carried[key] = carried.get(key, 0) + 1
    text = "\n".join([*sights, *sounds, *body_lines, feeling_line])
    return SenseReport(
        tick=tick,
        sights=tuple(sights),
        sounds=tuple(sounds),
        body=tuple(body_lines),
        feeling=feeling,
        text=text,
        position=here,
        home=(home[0], home[1]),
        carried=carried,
        needs=needs,
        sick=sick,
        seen=tuple(seen),
        places={"water": tuple(water[:REMEMBERED_PLACES])},
        stored=dict(me.home_store.counts()),
    )
