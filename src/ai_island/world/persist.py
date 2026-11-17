"""Saving and loading the people-related parts of the world (snapshot v3)."""

from __future__ import annotations

from typing import Any

from ai_island.world.agents import (
    ActiveAction,
    Body,
    HarmRecord,
    Interrupt,
    Inventory,
    KnowledgeEntry,
    Offer,
    Player,
    Promise,
    Structure,
    Utterance,
    Villager,
)


def _mover(e: Player | Villager) -> list[int]:
    return [e.from_x, e.from_y, e.to_x, e.to_y, e.move_start_tick, e.move_end_tick, e.facing]


def player_to_state(p: Player) -> dict[str, Any]:
    return {
        "id": p.id,
        "index": p.index,
        "name": p.name,
        "pos": [p.x, p.y],
        "mover": _mover(p),
        "body": p.body.to_state(),
        "inv": p.inventory.to_state(),
        "store": p.home_store.to_state(),
        "b": p.b,
        "b_tick": p.b_tick,
        "band": p.band,
        "hooked": p.hooked,
        "trust": p.trust,
        "anger": p.anger,
        "action": None if p.action is None else p.action.to_state(),
        "last_decision": p.last_decision_tick,
        "knowledge": [
            [k.id, k.subject, k.claim, k.confidence, k.source, k.learned_tick, k.true]
            for k in p.knowledge
        ],
        "allies": p.allies,
        "stage": p.task_stage,
        "receipts": p.task_receipts,
        "slots": p.slots,
        "place_memory": p.place_memory,
        "seen_ids": p.seen_ids,
        "culprits": {str(k): v for k, v in p.known_culprits.items()},
        "alive": p.alive,
        "x_acc": [p.x_minute_sum, p.x_minutes, p.x_hourly, p.x_hour_sum, p.x_hour_n],
        "sleeping": p.sleeping,
        "last_harm": p.last_harm_tick,
        "ach": p.achievements,
        "pending": p.pending_rewards,
        "just_finished": p.just_finished,
    }


def player_from_state(ids: dict[str, int], s: dict[str, Any]) -> Player:
    m = s["mover"]
    p = Player(
        s["id"], s["index"], s["name"], s["pos"][0], s["pos"][1],
        m[0], m[1], m[2], m[3], m[4], m[5], m[6],
    )  # fmt: skip
    p.body = Body.from_state(s["body"])
    p.inventory = Inventory.from_state(ids, s["inv"])
    p.home_store = Inventory.from_state(ids, s["store"])
    p.b = s["b"]
    p.b_tick = s["b_tick"]
    p.band = s["band"]
    p.hooked = s["hooked"]
    p.trust = dict(s["trust"])
    p.anger = dict(s["anger"])
    p.action = None if s["action"] is None else ActiveAction.from_state(s["action"])
    p.last_decision_tick = s["last_decision"]
    p.knowledge = [KnowledgeEntry(*row) for row in s["knowledge"]]
    p.allies = list(s["allies"])
    p.task_stage = s["stage"]
    p.task_receipts = list(s["receipts"])
    p.slots = s["slots"]
    p.place_memory = s["place_memory"]
    p.seen_ids = list(s["seen_ids"])
    p.known_culprits = {int(k): v for k, v in s["culprits"].items()}
    p.alive = s["alive"]
    p.x_minute_sum, p.x_minutes, p.x_hourly, p.x_hour_sum, p.x_hour_n = s["x_acc"]
    p.x_hourly = list(p.x_hourly)
    p.sleeping = s["sleeping"]
    p.last_harm_tick = s["last_harm"]
    p.achievements = s["ach"]
    p.pending_rewards = list(s["pending"])
    p.just_finished = s["just_finished"]
    return p


def villager_to_state(v: Villager) -> dict[str, Any]:
    return {
        "id": v.id,
        "name": v.name,
        "leader": v.leader,
        "pos": [v.x, v.y],
        "mover": _mover(v),
        "body": v.body.to_state(),
        "inv": v.inventory.to_state(),
        "loyalty": v.loyalty,
        "bond": v.bond,
        "job": v.job,
        "level": v.work_level,
        "job_pos": [v.job_x, v.job_y],
        "hungry": v.hungry_minutes,
        "hard": v.hard_minutes,
        "adverse": v.adverse_days,
        "witnessed": v.witnessed,
        "alive": v.alive,
        "captive": v.captive,
        "captor": v.captor,
        "route": [list(q) for q in v.route],
        "ri": v.route_index,
        "think": v.next_think,
        "acc": v.work_acc,
        "line": v.last_line_tick,
    }


def villager_from_state(ids: dict[str, int], s: dict[str, Any]) -> Villager:
    m = s["mover"]
    v = Villager(
        s["id"], s["name"], s["leader"], s["pos"][0], s["pos"][1],
        m[0], m[1], m[2], m[3], m[4], m[5], m[6],
    )  # fmt: skip
    v.body = Body.from_state(s["body"])
    v.inventory = Inventory.from_state(ids, s["inv"])
    v.loyalty = s["loyalty"]
    v.bond = dict(s["bond"])
    v.job = s["job"]
    v.work_level = s["level"]
    v.job_x, v.job_y = s["job_pos"]
    v.hungry_minutes = s["hungry"]
    v.hard_minutes = s["hard"]
    v.adverse_days = dict(s["adverse"])
    v.witnessed = list(s["witnessed"])
    v.alive = s["alive"]
    v.captive = s["captive"]
    v.captor = s["captor"]
    v.route = [(q[0], q[1]) for q in s["route"]]
    v.route_index = s["ri"]
    v.next_think = s["think"]
    v.work_acc = s["acc"]
    v.last_line_tick = s["line"]
    return v


def harm_to_state(h: HarmRecord) -> list[Any]:
    return [h.id, h.tick, h.kind, h.actor, h.victim, h.x, h.y, h.saw, h.heard, h.processed]


def harm_from_state(row: list[Any]) -> HarmRecord:
    return HarmRecord(*row)


def interrupt_to_state(i: Interrupt) -> list[Any]:
    return [i.id, i.kind, i.player, i.tick, i.source, i.detail]


def offer_to_state(o: Offer) -> list[Any]:
    return [o.id, o.kind, o.maker, o.target, o.give, o.want, o.tick, o.expires,
            o.give_tools, o.want_tools]  # fmt: skip


def promise_to_state(p: Promise) -> list[Any]:
    return [p.id, p.maker, p.to, p.kind, p.item, p.amount, p.due_tick, p.text, p.made_tick,
            p.status, p.given]  # fmt: skip


def utterance_to_state(u: Utterance) -> list[Any]:
    return [u.speaker, u.targets, u.text, u.kind, u.ref]


def structure_to_state(s: Structure) -> list[Any]:
    return s.to_state()
