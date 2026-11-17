"""The chat phase: who is spoken to, who overhears, villager lines and gossip.

A target must be in the speaker's sight and in hearing; everyone within hearing range of the
speaker receives the words and nobody else. Gossip is only about players and only from a
villager's own witnessed records.
"""

from __future__ import annotations

from typing import Any

from ai_island.rules.senses.common import (
    actor,
    emit,
    interrupt,
    pos_of,
    setting,
    stable_index,
)
from ai_island.rules.senses.ranges import can_hear, can_see

HEARD_KEEP = 8
LINES: dict[str, tuple[str, ...]] = {
    "hungry": (
        "I am hungry.",
        "There is not enough to eat.",
        "My stomach is empty, please feed us.",
    ),
    "tired": (
        "This work is wearing me out.",
        "I need to rest.",
        "I cannot keep going like this.",
    ),
    "leaving": (
        "I am thinking of leaving.",
        "Maybe life is better somewhere else.",
        "I do not know how long I can stay.",
    ),
    "content": (
        "All is well here.",
        "I am glad to work for you.",
        "The village is in good shape.",
    ),
}
GOSSIP: dict[str, tuple[str, ...]] = {
    "steal": (
        "I saw {actor} steal from {victim}.",
        "{actor} took things that were not theirs from {victim}.",
        "I watched {actor} rob {victim}.",
    ),
    "sabotage": (
        "I saw {actor} damage a building of {victim}.",
        "{actor} wrecked something that belonged to {victim}.",
        "{actor} sabotaged {victim}.",
    ),
    "attack": (
        "I saw {actor} attack {victim}.",
        "{actor} struck {victim}.",
        "{actor} hurt {victim}.",
    ),
    "default": (
        "I saw {actor} do something to {victim}.",
        "{actor} wronged {victim}.",
        "I heard about {actor} and {victim}.",
    ),
}


def _utterance(**kw: Any) -> Any:
    from ai_island.world.agents import Utterance

    return Utterance(**kw)


def _line_for(world: Any, tick: int, vid: str, villager: Any) -> str | None:
    if villager.loyalty < float(setting(world, "leave_below")):
        key = "leaving"
    elif villager.hungry_minutes > 0:
        key = "hungry"
    elif villager.hard_minutes > 0:
        key = "tired"
    elif villager.loyalty >= 70:
        key = "content"
    else:
        return None
    options = LINES[key]
    return options[stable_index(len(options), world.streams.seed, vid, tick, key)]


def _gossip_for(world: Any, tick: int, vid: str, villager: Any) -> tuple[str, int] | None:
    """One thing the villager itself saw or heard about a player, as words, and the harm id."""
    by_id = {h.id: h for h in world.harm_log}
    for harm_id in list(villager.witnessed):
        record = by_id.get(harm_id)
        villager.witnessed.remove(harm_id)
        if record is None or not record.actor.startswith("player_"):
            continue
        options = GOSSIP.get(record.kind, GOSSIP["default"])
        names = {pid: world.players[pid].name for pid in world.players}
        template = options[stable_index(len(options), world.streams.seed, vid, tick, harm_id)]
        text = template.format(
            actor=names.get(record.actor, record.actor),
            victim=names.get(record.victim, record.victim),
        )
        return text, harm_id
    return None


def _add_villager_speech(world: Any, tick: int) -> None:
    cooldown = int(setting(world, "line_cooldown_ticks"))
    for vid in sorted(world.villagers):
        v = world.villagers[vid]
        if not v.alive or v.leader is None or v.captive or tick - v.last_line_tick < cooldown:
            continue
        leader = world.players.get(v.leader)
        if leader is None or not leader.alive:
            continue
        if not (
            can_see(world, vid, pos_of(leader), tick) and can_hear(world, pos_of(v), pos_of(leader))
        ):
            continue
        told = _gossip_for(world, tick, vid, v)
        if told is not None:
            v.last_line_tick = tick
            text, harm_id = told
            world.utterances.append(
                _utterance(speaker=vid, targets=[v.leader], text=text, kind="gossip", ref=harm_id)
            )
            continue
        line = _line_for(world, tick, vid, v)
        if line is not None:
            v.last_line_tick = tick
            world.utterances.append(
                _utterance(speaker=vid, targets=[v.leader], text=line, kind="line", ref=None)
            )


def _hearers(world: Any, speaker_id: str, here: tuple[int, int]) -> list[str]:
    found = [
        ident
        for ident, who in world.players.items()
        if ident != speaker_id and who.alive and can_hear(world, here, pos_of(who))
    ]
    found.extend(
        ident
        for ident, who in world.villagers.items()
        if ident != speaker_id and who.alive and can_hear(world, here, pos_of(who))
    )
    return sorted(found)


def run_chat_phase(world: Any, tick: int) -> None:
    """Deliver this tick's speech, add villager lines and gossip, then clear the speech list."""
    _add_villager_speech(world, tick)
    for u in world.utterances:
        speaker = actor(world, u.speaker)
        if speaker is None or not speaker.alive:
            continue
        here = pos_of(speaker)
        valid: list[str] = []
        for tid in u.targets:
            target = actor(world, tid)
            if (
                target is not None
                and target.alive
                and can_see(world, u.speaker, pos_of(target), tick)
                and can_hear(world, here, pos_of(target))
            ):
                valid.append(tid)
        if u.targets and not valid:
            if u.speaker in world.players:
                emit(
                    world,
                    "action_failed",
                    tick,
                    player=u.speaker,
                    kind=u.kind,
                    reason="target_not_in_sight",
                )
            continue
        hearers = _hearers(world, u.speaker, here)
        emit(
            world,
            "chat_spoken",
            tick,
            speaker=u.speaker,
            targets=valid,
            hearers=hearers,
            text=u.text,
            kind=u.kind,
        )
        speaker_name = getattr(speaker, "name", u.speaker)
        for hid in hearers:
            if hid in world.players:
                heard = world.players[hid].place_memory.setdefault("heard", [])
                heard.append([tick, speaker_name, u.text])
                del heard[:-HEARD_KEEP]
        for tid in valid:
            if tid in world.players:
                interrupt(world, "spoken_to", tid, tick, source=u.speaker)
                if u.kind == "gossip" and u.ref is not None:
                    _learn_from_gossip(world, tid, u.ref, tick)
    world.utterances.clear()


def _learn_from_gossip(world: Any, listener: str, harm_id: int, tick: int) -> None:
    for record in world.harm_log:
        if record.id == harm_id and record.actor.startswith("player_"):
            if harm_id not in world.players[listener].known_culprits:
                world.players[listener].known_culprits[harm_id] = record.actor
                emit(
                    world,
                    "culprit_learned",
                    tick,
                    player=listener,
                    harm=harm_id,
                    harm_id=harm_id,
                    culprit=record.actor,
                    actor=record.actor,
                    how="told",
                    source="gossip",
                )
            return
