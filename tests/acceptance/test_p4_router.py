"""Phase 4 acceptance tests: triggers and the router (AC-9, AC-10), fake adapter only."""

from __future__ import annotations

import re

import pytest
from p4_helpers import clean, decisions, fast_reply, new_ai_sim, raise_int

from ai_island.llm.fake import FakeAdapter
from ai_island.rules.actions.core import start_action
from ai_island.rules.actions.request import ActionRequest

TRIGGERS = {"finished", "spoken_to", "interrupt", "check"}


def one_decision(sim, setup, pid="player_1"):
    """Run one tick after `setup(sim)`; return (new request keys, decisions, new broker rows)."""
    adapter = sim.adapters["fake"]
    clean(sim)
    setup(sim)
    before = set(adapter.calls)
    rows_before = len(sim._broker.rows)  # noqa: SLF001
    n = len(sim.events)
    sim.run(1)
    keys = sorted(k for k in adapter.calls if k not in before)
    return keys, [d for d in decisions(sim, n) if d.player == pid], sim._broker.rows[rows_before:]  # noqa: SLF001


def finished(sim, pid="player_1"):
    p = sim.world.players[pid]
    p.just_finished = True
    p.last_decision_tick = -1000


def count_embeds(sim):
    calls = []
    emb = sim._embedder  # noqa: SLF001
    original = emb.embed

    def counting(texts):
        calls.append(len(texts))
        return original(texts)

    emb.embed = counting
    return calls


def fresh(**kw):
    sim = new_ai_sim(**kw)
    sim.run(400)  # day-0 ranking done, a memory stream exists
    return sim


def remembered(row):
    text = row.prompt["current"]
    m = re.search(r"What you remember:\n(.*?)(?:\n\n|$)", text, re.S)
    assert m, text[:300]
    return [ln for ln in m.group(1).splitlines() if ln.startswith("- ")]


# --------------------------------------------------------------------------------- AC-9


def test_AC9_every_call_happens_on_a_decision_with_one_of_the_four_triggers():
    sim = new_ai_sim(seats=(1, 2), seed=2)
    adapter = sim.adapters["fake"]
    sim.run(1500)
    decided = {(d.player, int(d.decision_key.split("/")[0])) for d in decisions(sim)}
    assert decided
    for d in decisions(sim):
        assert d.trigger in TRIGGERS
    for key in adapter.calls:
        tick, pid, purpose, _ = key.split("/")
        if purpose in ("ranking", "reflection"):
            continue
        assert (pid, int(tick)) in decided, f"call {key} without a trigger decision"
    # most minutes need no call at all
    assert len(decided) < 1500 * 2 / 4


def test_AC9_a_running_action_continues_without_any_call():
    sim = fresh()
    adapter = sim.adapters["fake"]
    clean(sim)
    w = sim.world
    start_action(
        w,
        "player_1",
        ActionRequest(kind="gather", item="water", amount=60, x=11, y=16),
        w.tick,
    )
    before = set(adapter.calls)
    n = len(sim.events)
    start = w.tick
    sim.run(100)
    triggers = [d.trigger for d in decisions(sim, n) if d.player == "player_1"]
    new = [k for k in adapter.calls if k not in before]
    # every new call belongs to an interrupt-triggered decision; nothing else asked the player
    assert len(new) <= len(triggers) * 3
    assert "finished" not in triggers or w.players["player_1"].action is None
    assert w.tick == start + 100


def test_AC9_two_awake_hours_without_a_decision_trigger_a_fast_check():
    sim = fresh()
    clean(sim)
    w = sim.world
    start_action(
        w, "player_1", ActionRequest(kind="gather", item="water", amount=60, x=11, y=16), w.tick
    )
    p = w.players["player_1"]
    assert p.action is not None and not p.sleeping
    t0 = w.tick
    n = len(sim.events)
    last = t0
    checks = []
    for _ in range(300):
        sim.run(1)
        for d in decisions(sim, n):
            if d.player == "player_1":
                tick = int(d.decision_key.split("/")[0])
                if d.trigger == "check":
                    checks.append((tick, tick - last, d.tier))
                last = tick
        n = len(sim.events)
    assert checks, "no check decision in 300 awake minutes"
    for _tick, gap, tier in checks:
        assert gap >= 120
        assert tier == "fast"


def test_AC9_a_check_is_a_single_fast_call():
    sim = fresh()
    clean(sim)
    w = sim.world
    start_action(
        w, "player_1", ActionRequest(kind="gather", item="water", amount=60, x=11, y=16), w.tick
    )
    w.players["player_1"].last_decision_tick = w.tick - 119  # the next minute is the 2-hour mark
    keys, decs, _ = one_decision(sim, lambda s: None)
    # `clean` cancelled the action, so rebuild the situation explicitly instead
    start_action(
        w, "player_1", ActionRequest(kind="gather", item="water", amount=60, x=11, y=16), w.tick
    )
    w.players["player_1"].last_decision_tick = w.tick - 119
    adapter = sim.adapters["fake"]
    before = set(adapter.calls)
    n = len(sim.events)
    sim.run(1)
    new = sorted(k for k in adapter.calls if k not in before)
    ds = [d for d in decisions(sim, n) if d.player == "player_1"]
    assert ds and ds[0].trigger == "check" and ds[0].tier == "fast"
    assert len(new) == 1 and new[0].split("/")[2] == "fast"


def test_AC9_each_trigger_kind_is_recorded_with_its_name():
    sim = fresh()
    _, decs, _ = one_decision(sim, lambda s: finished(s))
    assert decs and decs[0].trigger == "finished"
    _, decs, _ = one_decision(sim, lambda s: raise_int(s, "attacked", "player_1", "player_2"))
    assert decs[0].trigger == "interrupt"
    _, decs, _ = one_decision(sim, lambda s: raise_int(s, "spoken_to", "player_1", "player_2"))
    assert decs[0].trigger == "spoken_to"


# -------------------------------------------------------------------------------- AC-10


def test_AC10_urgent_need_goes_to_reflex_with_no_call():
    sim = fresh()

    def setup(s):
        finished(s)
        s.world.players["player_1"].body.fatigue = 100

    keys, decs, rows = one_decision(sim, setup)
    assert keys == [] and rows == []
    assert decs and decs[0].tier == "reflex" and decs[0].source == "code"


def test_AC10_routine_moment_is_fast_one_helper_call_hooked_or_not():
    sim = fresh()
    for hooked in (False, True):

        def setup(s, hooked=hooked):
            finished(s)
            s.world.players["player_1"].body.pain = 90.0 if hooked else 0.0

        keys, decs, rows = one_decision(sim, setup)
        assert len(keys) == 1 and keys[0].split("/")[2] == "fast", (hooked, keys)
        assert decs[0].tier == "fast"
        assert rows[0].role == "player_1_helper"


def test_AC10_unhooked_main_decision_is_noticer_advisor_main_in_that_order():
    sim = fresh()
    embeds = count_embeds(sim)
    keys, decs, rows = one_decision(
        sim, lambda s: raise_int(s, "spoken_to", "player_1", "player_2")
    )
    assert decs[0].tier == "slow"
    assert [r.details["purpose"] for r in rows] == ["noticer", "advisor", "main"]
    assert [r.role for r in rows] == ["player_1_helper", "player_1_helper", "player_1_main"]
    assert len(keys) == 3
    assert embeds, "a slow decision searches its memory"
    assert len(remembered(rows[2])) > 5


def test_AC10_hooked_main_decision_is_main_only_with_short_memory_and_no_search():
    sim = fresh()
    # the same moment unhooked first, to compare the main call's settings
    _, _, slow_rows = one_decision(sim, lambda s: raise_int(s, "spoken_to", "player_1", "player_2"))
    embeds = count_embeds(sim)

    def hooked(s):
        s.world.players["player_1"].body.pain = 90.0
        raise_int(s, "spoken_to", "player_1", "player_2")

    keys, decs, rows = one_decision(sim, hooked)
    assert decs[0].tier == "hooked"
    assert [r.details["purpose"] for r in rows] == ["main"]
    assert len(keys) == 1
    assert rows[0].role == slow_rows[2].role
    assert rows[0].details["settings"] == slow_rows[2].details["settings"]
    assert len(remembered(rows[0])) <= 5
    assert embeds == [], "hooked decisions make no memory search"


def test_AC10_a_villager_speaking_is_not_a_main_decision():
    sim = fresh()
    keys, decs, _ = one_decision(sim, lambda s: raise_int(s, "spoken_to", "player_1", "villager_1"))
    assert decs[0].tier == "fast"
    assert len(keys) == 1


@pytest.mark.parametrize("kind", ["attacked", "hurt", "storm_started", "player_in_sight"])
def test_AC10_main_interrupts_go_to_the_main_model(kind):
    sim = fresh()
    source = "player_2" if kind in ("attacked", "player_in_sight") else None
    _, decs, rows = one_decision(sim, lambda s: raise_int(s, kind, "player_1", source))
    assert decs[0].tier == "slow"
    assert rows[-1].details["purpose"] == "main"


def test_AC10_cheap_runs_use_the_helper_model_for_main():
    sim = fresh(cheap=True)
    _, _, rows = one_decision(sim, lambda s: raise_int(s, "spoken_to", "player_1", "player_2"))
    assert rows[-1].details["purpose"] == "main"
    assert rows[-1].role == "player_1_helper"


def test_AC10_fast_reply_asking_for_more_thought_escalates_to_a_main_decision():
    adapter = FakeAdapter(
        script={("player_1", "fast"): [fast_reply({"kind": "rest", "minutes": 5}, more=True)]}
    )
    sim = new_ai_sim(adapter=adapter)
    sim.run(3)
    tiers = [d.tier for d in decisions(sim) if d.player == "player_1"]
    assert tiers and tiers[0] in ("slow", "hooked")
    purposes = [k.split("/")[2] for k in adapter.calls]
    assert "fast" in purposes and "main" in purposes
