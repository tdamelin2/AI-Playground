"""Who saw or heard a harm, and who learns the culprit.

A victim learns who harmed it only if it saw or heard the harm itself, or is later told (gossip
or a teach entry with subject ``culprit:<id>``).
"""

from __future__ import annotations

from typing import Any

from ai_island.rules.senses.common import dist2, emit, pos_of
from ai_island.rules.senses.ranges import can_hear, sight_range


def _watchers(world: Any, record: Any, tick: int) -> tuple[list[str], list[str]]:
    spot = (record.x, record.y)
    saw: list[str] = []
    heard: list[str] = []
    people: list[tuple[str, Any]] = [(pid, p) for pid, p in world.players.items()]
    people.extend((vid, v) for vid, v in world.villagers.items())
    for ident, who in people:
        if ident == record.actor or not who.alive:
            continue
        radius = sight_range(world, ident, tick)
        if dist2(pos_of(who), spot) <= radius * radius:
            saw.append(ident)
        elif can_hear(world, spot, pos_of(who)):
            heard.append(ident)
    return sorted(saw), sorted(heard)


def record_witnesses(world: Any, tick: int) -> None:
    """Fill saw/heard of new harm records, let villagers remember, and set victim culprits."""
    for record in world.harm_log:
        if record.processed:
            continue
        record.saw, record.heard = _watchers(world, record, tick)
        record.processed = True
        for ident in (*record.saw, *record.heard):
            villager = world.villagers.get(ident)
            if villager is not None and record.id not in villager.witnessed:
                villager.witnessed.append(record.id)
        victim = world.players.get(record.victim)
        if victim is not None and record.victim in (*record.saw, *record.heard):
            victim.known_culprits[record.id] = record.actor
            emit(
                world,
                "culprit_learned",
                tick,
                player=record.victim,
                harm=record.id,
                harm_id=record.id,
                culprit=record.actor,
                actor=record.actor,
                how="witnessed",
                source="self",
            )
        emit(world, "witnessed", tick, id=record.id, saw=record.saw, heard=record.heard)
    _learn_from_teaching(world, tick)


def _learn_from_teaching(world: Any, tick: int) -> None:
    """Taught entries with subject ``culprit:<harm id>`` tell a player who did it."""
    for pid in sorted(world.players):
        player = world.players[pid]
        for entry in player.knowledge:
            if not entry.subject.startswith("culprit:"):
                continue
            try:
                harm_id = int(entry.subject.split(":", 1)[1])
            except ValueError:
                continue
            if harm_id in player.known_culprits or not entry.claim.startswith("player_"):
                continue
            player.known_culprits[harm_id] = entry.claim
            emit(
                world,
                "culprit_learned",
                tick,
                player=pid,
                harm=harm_id,
                harm_id=harm_id,
                culprit=entry.claim,
                actor=entry.claim,
                how="told",
                source=entry.source,
            )
