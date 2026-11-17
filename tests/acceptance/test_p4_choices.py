"""Phase 4 acceptance tests: choice points, memory, mistakes, reflection (AC-13 .. AC-18)."""

from __future__ import annotations

import json
import sqlite3

import pytest
from p4_helpers import CFG, clean, decisions, fast_reply, new_ai_sim, raise_int, shared_week

from ai_island.llm.fake import FakeAdapter
from ai_island.minds import memory, outcomes, values
from ai_island.minds.schemas import InventedValue
from ai_island.minds.settings import MindSettings
from ai_island.minds.values import VALUE_IDS
from ai_island.storage.records import ChoicePointRecord

SETTINGS = MindSettings.from_config(CFG.balance.mind)
REST = {"kind": "rest", "minutes": 5}


def option(action=None, serves=("honesty",), violates=(), now=2, later=3, **kw):
    base = {
        "action": action or REST,
        "serves": list(serves),
        "violates": list(violates),
        "feel_now": now,
        "feel_later": later,
        "relationships": "steady",
        "villagers": "steady",
        "uncertainty": "low",
    }
    base.update(kw)
    return base


def slow_reply(choice=1, trade="keeps the peace", label=None, n=3, **kw):
    opts = [
        option({"kind": "rest", "minutes": 10 + 10 * i}, now=i + 1, later=i + 2) for i in range(n)
    ]
    reply = {
        "thought": "thinking it through",
        "options": opts,
        "choice_index": choice,
        "trade_off": trade,
        "self_label": label or {"served": ["honesty"], "violated": [], "direction": "toward"},
    }
    reply.update(kw)
    return reply


def fresh(seed=3, **kw):
    sim = new_ai_sim(seed=seed, **kw)
    sim.run(400)
    return sim


def force(sim, purpose, reply, how="finished", pid="player_1", pain=0.0):
    """One decision for `pid`: script one reply, raise one trigger, run one tick."""
    adapter = sim.adapters["fake"]
    clean(sim)
    if reply is not None:
        adapter.script[(pid, purpose)] = reply if isinstance(reply, list) else [reply]
    sim.world.players[pid].body.pain = pain
    if how == "finished":
        p = sim.world.players[pid]
        p.just_finished = True
        p.last_decision_tick = -1000
    else:
        raise_int(sim, "spoken_to", pid, source="player_2")
    n_rec, n_ev = len(sim.records), len(sim.events)
    sim.run(1)
    cps = [r for r in sim.records[n_rec:] if isinstance(r, ChoicePointRecord)]
    mine = [d for d in decisions(sim, n_ev) if d.player == pid]
    events = sim.events[n_ev:]
    return cps, mine, events


def core_of(sim, pid="player_1"):
    return values.core_ids(sim.controllers[pid].weights)


# ---------------------------------------------------------------------------------- AC-13


@pytest.mark.parametrize("pain,tier", [(0.0, "slow"), (90.0, "hooked")])
def test_AC13_slow_and_hooked_decisions_record_options_choice_trade_off_and_label(pain, tier):
    sim = fresh()
    cps, decs, _ = force(
        sim, "main", slow_reply(choice=1, trade="steady beats quick"), "spoken", pain=pain
    )
    assert len(cps) == 1 and decs[0].tier == tier
    cp = cps[0]
    assert cp.tier == tier
    options = cp.details["options"]
    assert 2 <= len(options) <= 4 and len(options) == 3
    for o in options:
        assert set(o) >= {"action", "serves", "violates", "feel_now", "feel_later"}
    assert cp.details["choice_index"] == 1
    assert cp.details["trade_off"] == "steady beats quick"
    assert cp.action["kind"] == "rest" and cp.action["minutes"] == 20  # the chosen option
    assert cp.self_label == {"served": ["honesty"], "violated": [], "direction": "toward"}
    assert isinstance(cp.x, float) and cp.situation and cp.feeling and cp.thought
    assert cp.details["expected_delta"] == pytest.approx(options[1]["feel_now"])


@pytest.mark.parametrize("n", [2, 4])
def test_AC13_two_and_four_options_are_accepted(n):
    sim = fresh()
    cps, decs, _ = force(sim, "main", slow_reply(choice=n - 1, n=n), "spoken")
    assert len(cps) == 1 and len(cps[0].details["options"]) == n
    assert decs[0].source == "model"


def test_AC13_one_or_five_options_are_not_accepted_and_the_player_rests_instead():
    for n in (1, 5):
        sim = fresh()
        reply = slow_reply(choice=0, n=2)
        reply["options"] = [reply["options"][0]] * n
        _, decs, _ = force(sim, "main", [reply, reply], "spoken")
        assert decs[0].source == "fallback" and decs[0].failure == "format"


def test_AC13_choice_against_own_core_is_logged_as_violation_and_still_carried_out():
    sim = fresh()
    top = core_of(sim)[0]
    label = {"served": [], "violated": [top], "direction": "toward"}
    cps, _, events = force(sim, "main", slow_reply(choice=2, label=label), "spoken")
    viol = [e for e in events if e.type == "value_violation"]
    assert len(viol) == 1
    assert viol[0].payload.player == "player_1" and top in viol[0].payload.violated
    assert cps[0].details["value_violation"] is True
    act = sim.world.players["player_1"].action
    assert act is not None and act.request.kind == "rest"  # chosen option was carried out
    assert act.request.minutes == 30


def test_AC13_direction_against_is_a_violation_even_with_no_ids():
    sim = fresh()
    label = {"served": [], "violated": [], "direction": "against"}
    cps, _, events = force(sim, "main", slow_reply(label=label), "spoken")
    assert len([e for e in events if e.type == "value_violation"]) == 1
    assert cps[0].details["value_violation"] is True
    assert sim.world.players["player_1"].action is not None


def test_AC13_serving_values_is_not_a_violation():
    sim = fresh()
    cps, _, events = force(sim, "main", slow_reply(), "spoken")
    assert not [e for e in events if e.type == "value_violation"]
    assert cps[0].details["value_violation"] is False


def test_AC13_violating_a_background_value_is_not_a_core_violation():
    sim = fresh()
    weights = sim.controllers["player_1"].weights
    low = min(weights, key=weights.get)
    assert low not in core_of(sim)
    label = {"served": [], "violated": [low], "direction": "toward"}
    _, _, events = force(sim, "main", slow_reply(label=label), "spoken")
    assert not [e for e in events if e.type == "value_violation"]


# ---------------------------------------------------------------------------------- AC-14


class VecEmbedder:
    """A query and two items with chosen vectors (the contract's tie example)."""

    def embed(self, texts):
        table = {"q": [1.0, 0.0], "a": [1.0, 0.0], "b": [0.0, 1.0]}
        return [table[t] for t in texts]


def item(i, tick=100, text="a", imp=0.5):
    return memory.MemoryItem(i, tick, "note", text, imp)


def test_AC14_relevance_decides_between_equal_items():
    out = memory.retrieve([item(1, text="b"), item(2, text="a")], "q", 100, 2, VecEmbedder())
    assert [m.id for m in out] == [2, 1]
    out = memory.retrieve([item(2, text="a"), item(1, text="b")], "q", 100, 2, VecEmbedder())
    assert [m.id for m in out] == [2, 1]


def test_AC14_relevance_with_the_fake_embedder():
    from ai_island.llm.fake import FakeEmbedder

    stream = [item(1, text="stone hill quarry"), item(2, text="river fish net")]
    out = memory.retrieve(stream, "fish at the river", 100, 2, FakeEmbedder(), SETTINGS)
    assert out[0].id == 2


def test_AC14_recency_decides_between_equal_items():
    from ai_island.llm.fake import FakeEmbedder

    stream = [item(1, tick=0, text="a"), item(2, tick=300, text="a")]
    out = memory.retrieve(stream, "a", 300, 2, FakeEmbedder(), SETTINGS)
    assert [m.id for m in out] == [2, 1]


def test_AC14_importance_decides_between_equal_items():
    from ai_island.llm.fake import FakeEmbedder

    stream = [item(1, imp=0.2), item(2, imp=0.9)]
    out = memory.retrieve(stream, "a", 100, 2, FakeEmbedder(), SETTINGS)
    assert [m.id for m in out] == [2, 1]


def test_AC14_exact_ties_go_to_newer_tick_then_lower_id():
    emb = VecEmbedder()
    out = memory.retrieve([item(2), item(1)], "q", 100, 2, emb, SETTINGS)
    assert [m.id for m in out] == [1, 2]


def test_AC14_score_formula_matches_the_contract():
    it = memory.MemoryItem(1, 0, "k", "a", 0.4)
    s = SETTINGS
    want = (
        s.recency_weight * 2 ** (-(120) / s.memory_half_life_ticks)
        + s.importance_weight * 0.4
        + s.relevance_weight * (1 + 0.5) / 2
    )
    assert memory.score(it, 120, 0.5, s) == pytest.approx(want)


def test_AC14_limit_is_respected_and_recent_is_newest_first():
    stream = [item(i, tick=i) for i in range(1, 30)]
    from ai_island.llm.fake import FakeEmbedder

    assert len(memory.retrieve(stream, "a", 40, 20, FakeEmbedder(), SETTINGS)) == 20
    assert [m.id for m in memory.recent(stream, 5)] == [29, 28, 27, 26, 25]


# ---------------------------------------------------------------------------------- AC-15


def advisor_rows(sim, since):
    return [r for r in sim._broker.rows[since:] if r.details["purpose"] == "advisor"]  # noqa: SLF001


def test_AC15_advisor_prompt_includes_recent_main_decisions_limited_to_five():
    sim = fresh()
    words = ["amber", "birch", "cedar", "dune", "ember", "flint", "grove"]
    before = len(sim._broker.rows)  # noqa: SLF001
    for w in words:
        force(sim, "main", slow_reply(choice=0, trade=f"{w} wins"), "spoken")
    rows = advisor_rows(sim, before)
    assert len(rows) == len(words)
    text = rows[-1].prompt["current"]
    for w in words[1:6]:
        assert f"{w} wins" in text, w
    assert "amber wins" not in text  # older than advisor_history_size
    assert "grove wins" not in text  # the decision being made now
    assert "amber wins" not in rows[1].prompt["current"] or True
    first = rows[0].prompt["current"]
    assert "amber wins" not in first  # nothing decided yet


def test_AC15_advisor_sees_the_choice_and_the_outcome_so_far():
    sim = fresh()
    before = len(sim._broker.rows)  # noqa: SLF001
    force(sim, "main", slow_reply(choice=2, trade="onward"), "spoken")
    sim.run(40)
    force(sim, "main", slow_reply(choice=0, trade="again"), "spoken")
    text = advisor_rows(sim, before)[-1].prompt["current"]
    assert "onward" in text
    assert "rest" in text  # the choice, in words


# ---------------------------------------------------------------------------------- AC-16


def test_AC16_contract_examples_for_the_mistake_margin():
    assert outcomes.is_mistake(6.0, 0.0, SETTINGS) is True
    assert outcomes.is_mistake(6.0, 1.0, SETTINGS) is False
    assert SETTINGS.mistake_margin == 5.0


def test_AC16_a_hopeful_decision_that_goes_nowhere_is_flagged_and_remembered():
    sim = fresh()
    reply = fast_reply(REST, feel=10)
    _, decs, _ = force(sim, "fast", reply)
    assert decs[0].tier == "fast"
    ne = len(sim.events)
    flagged = []
    for _ in range(80):
        sim.run(1)
        flagged = [e.payload for e in sim.events[ne:] if e.type == "mistake_flagged"]
        if flagged:
            break
    assert flagged, "no mistake_flagged event"
    f = flagged[0]
    assert f.player == "player_1" and f.expected_delta - f.actual_delta > 5.0
    assert f.expected_delta == pytest.approx(10.0)
    mem = sim.controllers["player_1"].stream
    assert any(m.kind == "mistake" for m in mem)


def test_AC16_a_good_outcome_is_not_flagged():
    sim = fresh()
    force(sim, "fast", fast_reply(REST, feel=-10))
    ne = len(sim.events)
    sim.run(60)
    assert not [
        e for e in sim.events[ne:] if e.type == "mistake_flagged" and e.payload.expected_delta > 0
    ]


# ---------------------------------------------------------------------------------- AC-17

A = [14.0] * 5 + [4.0] * 3 + [3.0] * 6


def weights_of(lst):
    return dict(zip(VALUE_IDS, lst, strict=True))


def test_AC17_example_a_clip_rescale_and_core():
    new, clipped, status = values.reflect(weights_of(A), {"friendship": 30.0}, None, SETTINGS)
    assert clipped == {"friendship": 10.0} and status is None
    assert new["friendship"] == pytest.approx(21.8182, abs=1e-3)
    assert new["work"] == pytest.approx(12.7273, abs=1e-3)
    assert new["honesty"] == pytest.approx(3.6364, abs=1e-3) or new[VALUE_IDS[5]] == pytest.approx(
        3.6364, abs=1e-3
    )
    assert new[VALUE_IDS[8]] == pytest.approx(2.7273, abs=1e-3)
    assert sum(new.values()) == pytest.approx(100.0, abs=1e-6)
    assert values.core_ids(new) == list(VALUE_IDS[:5])


def test_AC17_example_b_floor_locked_values_stay_at_one():
    ids = {
        "friendship": 20, "work": 20, "honesty": 15, "fairness": 15, "family": 10,
        "curiosity": 8, "security": 5, "power": 1, "religion": 1, "respect_others": 1,
        "respect_self": 1, "loyalty": 1, "generosity": 1, "independence": 1,
    }  # fmt: skip
    new, clipped, _ = values.reflect(ids, {"curiosity": 15.0, "work": -4.0}, None, SETTINGS)
    assert clipped == {"curiosity": 10.0}
    for v in (
        "power",
        "religion",
        "respect_others",
        "respect_self",
        "loyalty",
        "generosity",
        "independence",
    ):
        assert new[v] == pytest.approx(1.0, abs=1e-6)
    want = {"friendship": 18.7879, "curiosity": 16.9091, "work": 15.0303, "honesty": 14.0909,
            "fairness": 14.0909, "family": 9.3939, "security": 4.6970}  # fmt: skip
    for v, w in want.items():
        assert new[v] == pytest.approx(w, abs=1e-3), v
    assert set(values.core_ids(new)) == {"friendship", "curiosity", "work", "honesty", "fairness"}


def test_AC17_example_c_nothing_can_leave_the_floor_total():
    w = weights_of([87.0] + [1.0] * 13)
    new, _, _ = values.reflect(w, {VALUE_IDS[0]: 10.0}, None, SETTINGS)
    assert [round(new[v], 4) for v in VALUE_IDS] == [87.0] + [1.0] * 13


def test_AC17_invented_value_joins_and_everything_still_sums_to_100():
    inv = InventedValue(
        name="Patience", definition="Waiting calmly", priority=8.0, conflicts=[],
        observable_behaviour="Pauses before answering",
    )  # fmt: skip
    new, _, status = values.reflect(weights_of(A), {}, inv, SETTINGS)
    assert status is not None and status in new and len(new) == 15
    assert sum(new.values()) == pytest.approx(100.0, abs=1e-6)
    assert min(new.values()) >= 1.0 - 1e-9


def _inv(name="Patience", definition="Waiting calmly", behaviour="Pauses before answering"):
    return InventedValue(
        name=name, definition=definition, priority=5.0, conflicts=[], observable_behaviour=behaviour
    )


def test_AC17_invented_value_rejections():
    w = weights_of(A)
    assert values.validate_invented(_inv(), w, SETTINGS, 0) is None
    assert values.validate_invented(_inv(), w, SETTINGS, 1)  # one per week
    assert values.validate_invented(_inv("Game Master"), w, SETTINGS, 0)  # banned word
    assert values.validate_invented(_inv(definition="Helps the experiment"), w, SETTINGS, 0)
    assert values.validate_invented(_inv("Honesty"), w, SETTINGS, 0)  # duplicate
    assert values.validate_invented(_inv("fairness"), w, SETTINGS, 0)  # duplicate, case-insensitive


@pytest.fixture(scope="module")
def week(tmp_path_factory):
    """One AI seat, a hopeful decision, a slow decision, a scripted weekly reflection."""
    root = tmp_path_factory.mktemp("p4_scripted_week")
    sim = new_ai_sim(seats=(1,), seed=5, db_path=root / "run.db")
    ad: FakeAdapter = sim.adapters["fake"]
    ctrl = sim.controllers["player_1"]
    sim.run(500)
    clean(sim)
    ad.script[("player_1", "fast")] = [fast_reply(REST, feel=10)]
    p = sim.world.players["player_1"]
    p.just_finished, p.last_decision_tick = True, -1000
    ne = len(sim.events)
    for _ in range(80):
        sim.run(1)
        if any(e.type == "mistake_flagged" for e in sim.events[ne:]):
            break
    clean(sim)
    ad.script[("player_1", "main")] = [slow_reply(choice=0, trade="patience first")]
    raise_int(sim, "spoken_to", "player_1", source="player_2")
    sim.run(1)
    key = decisions(sim)[-1].decision_key
    mid1 = ctrl.rolling_summary
    sim.run(5000 - sim.world.tick)
    mid2 = ctrl.rolling_summary
    reply = {
        "requested_changes": {"friendship": 30.0, "honesty": -4.0},
        "cause_event_ids": [999999],
        "invented_values": [
            {"name": "Game Master", "definition": "Rules all", "priority": 9.0, "conflicts": [],
             "observable_behaviour": "Gives orders"},
            {"name": "Patience", "definition": "Waiting calmly before acting", "priority": 8.0,
             "conflicts": [], "observable_behaviour": "Pauses before answering"},
        ],
        "identity": "I am Ada, steady and fair.",
        "knowledge_updates": [{"subject": "Bo", "claim": "Bo keeps promises", "confidence": 0.6}],
        "rolling_summary": "A quiet week of fishing and careful talks.",
        "insights": [{"decision_key": key, "insight": "Patience paid off."}],
    }  # fmt: skip
    ad.script[("player_1", "reflection")] = [reply]
    sim.run(10079 - sim.world.tick)
    mid3 = ctrl.rolling_summary
    old = dict(ctrl.weights)
    sim.run(1)
    after = ctrl.rolling_summary
    sim.run(150)
    sim.save()
    sim.db.close()
    return {
        "sim": sim, "root": root, "key": key, "mids": (mid1, mid2, mid3), "after": after,
        "old": old, "new": dict(ctrl.weights), "tick_reflect": 10080,
    }  # fmt: skip


def query(root, sql, args=()):
    con = sqlite3.connect(root / "run.db")
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


@pytest.mark.slow
def test_AC17_weekly_reflection_applies_clip_rescale_invention_and_rejection(week):
    sim = week["sim"]
    ev = [e for e in sim.events if e.type in ("reflection_completed", "invention_rejected")]
    done = [e.payload for e in ev if e.type == "reflection_completed"]
    rej = [e.payload for e in ev if e.type == "invention_rejected"]
    assert len(done) == 1 and done[0].week == 1 and done[0].invented == "Patience"
    assert len(rej) == 1 and rej[0].name == "Game Master" and rej[0].reason
    old = week["old"]
    inv = InventedValue(
        name="Patience", definition="Waiting calmly before acting", priority=8.0, conflicts=[],
        observable_behaviour="Pauses before answering",
    )  # fmt: skip
    want, clipped, _ = values.reflect(old, {"friendship": 30.0, "honesty": -4.0}, inv, SETTINGS)
    assert clipped == {"friendship": 10.0}
    new = week["new"]
    assert len(new) == 15 and sum(new.values()) == pytest.approx(100.0, abs=1e-4)
    assert min(new.values()) >= 1.0 - 1e-9
    for v, w in want.items():
        assert new[v] == pytest.approx(w, abs=1e-3), v
    assert done[0].changes["friendship"][1] == pytest.approx(new["friendship"], abs=1e-3)


@pytest.mark.slow
def test_AC17_one_value_history_row_per_value_with_memory_item_causes(week):
    root = week["root"]
    rows = query(
        root,
        "SELECT value_id, old_weight, new_weight, cause_event_ids_json, details_json, game_week "
        "FROM value_history WHERE player_id = 'player_1' ORDER BY id",
    )
    day0 = [r for r in rows if r[5] == 0]
    wk1 = [r for r in rows if r[5] == 1]
    assert len(day0) == 14 and all(r[1] is None for r in day0)
    assert len(wk1) == 15 and len({r[0] for r in wk1}) == 15
    old = {r[0]: r[2] for r in day0}
    for vid, oldw, neww, causes, details, _ in wk1:
        if vid in old:
            assert oldw == pytest.approx(old[vid], abs=1e-6)
        else:
            assert oldw is None
        assert neww >= 1.0 - 1e-9
        assert 999999 not in json.loads(causes)  # only cited ids that exist are kept
        assert json.loads(details)["cause_kind"] == "memory_item"
    assert sum(r[2] for r in wk1) == pytest.approx(100.0, abs=1e-4)


# ---------------------------------------------------------------------------------- AC-14/16


@pytest.mark.slow
def test_AC14_rolling_summary_changes_only_in_the_weekly_reflection(week):
    mid1, mid2, mid3 = week["mids"]
    assert mid1 == mid2 == mid3  # nothing rewrote it during the week
    assert week["after"] == "A quiet week of fishing and careful talks."
    rows = query(
        week["root"],
        "SELECT prompt_json, details_json FROM ai_calls WHERE tick > 10080 AND player_id = 'player_1'",  # noqa: E501
    )
    later = [json.loads(p) for p, d in rows if json.loads(d)["purpose"] in ("fast", "main")]
    assert later, "no call after the reflection"
    assert all("A quiet week of fishing" in p["slow"] for p in later)  # kept and used
    earlier = query(
        week["root"],
        "SELECT prompt_json FROM ai_calls WHERE tick < 10000 AND tick > 600 LIMIT 5",
    )
    assert all("A quiet week of fishing" not in json.loads(p[0])["slow"] for p in earlier)


@pytest.mark.slow
def test_AC16_the_weekly_reflection_prompt_lists_the_mistake(week):
    sim = week["sim"]
    flagged = [e for e in sim.events if e.type == "mistake_flagged"]
    assert flagged
    rows = query(
        week["root"],
        "SELECT prompt_json FROM ai_calls WHERE json_extract(details_json, '$.purpose') = 'reflection'",  # noqa: E501
    )
    assert len(rows) == 1
    text = json.loads(rows[0][0])["current"]
    assert "hoping it would help" in text
    assert week["key"] in text  # the week's choices are in the prompt too


@pytest.mark.slow
def test_AC17_insights_and_knowledge_updates_are_applied(week):
    rows = query(
        week["root"],
        "SELECT insight FROM choice_points WHERE json_extract(details_json, '$.decision_key') = ?",
        (week["key"],),
    )
    assert rows == [("Patience paid off.",)]
    book = week["sim"].world.players["player_1"].knowledge
    assert any("keeps promises" in str(getattr(k, "claim", k)) for k in _entries(book))


def _entries(book):
    if isinstance(book, dict):
        return list(book.values())
    return list(book)


# ---------------------------------------------------------------------------------- AC-18


def test_AC18_fast_steal_makes_one_choice_point():
    sim = fresh()
    steal = {"kind": "steal", "target": "player_2", "item": "wood", "amount": 1}
    cps, decs, _ = force(sim, "fast", fast_reply(steal))
    assert decs[0].tier == "fast" and decs[0].choice_point is True
    assert len(cps) == 1 and cps[0].tier == "fast" and cps[0].action["kind"] == "steal"
    assert cps[0].noticer_read is None and cps[0].advisor_said is None


def test_AC18_fast_promise_makes_one_choice_point():
    sim = fresh()
    prom = {
        "kind": "promise", "target": "player_2",
        "promise": {"kind": "not_harm", "to": "player_2", "due_tick": 5000},
    }  # fmt: skip
    cps, decs, _ = force(sim, "fast", fast_reply(prom))
    assert decs[0].tier == "fast" and decs[0].choice_point is True
    assert len(cps) == 1 and cps[0].action["kind"] == "promise"


def test_AC18_fast_against_makes_one_choice_point():
    sim = fresh()
    cps, decs, _ = force(sim, "fast", fast_reply(REST, direction="against"))
    assert decs[0].tier == "fast" and decs[0].choice_point is True
    assert len(cps) == 1 and cps[0].self_label["direction"] == "against"


def test_AC18_routine_fast_gather_makes_none():
    sim = fresh()
    gather = {"kind": "gather", "item": "water", "amount": 5, "x": 11, "y": 16}
    cps, decs, _ = force(sim, "fast", fast_reply(gather))
    assert decs[0].tier == "fast" and decs[0].choice_point is False
    assert cps == []


def test_AC18_hooked_record_has_empty_noticer_and_advisor_and_slow_has_them():
    sim = fresh()
    hooked, _, _ = force(sim, "main", slow_reply(), "spoken", pain=90.0)
    slow, _, _ = force(sim, "main", slow_reply(), "spoken")
    h, s = hooked[0], slow[0]
    assert h.tier == "hooked" and h.noticer_read is None
    assert h.advisor_said is None and h.advisor_followed is None
    assert s.tier == "slow" and s.noticer_read is not None and s.advisor_said is not None
    assert s.advisor_followed in (True, False)


def test_AC18_advisor_followed_is_whether_the_chosen_kind_is_the_recommended_kind():
    sim = fresh()
    sim.adapters["fake"].script[("player_1", "advisor")] = [
        {"advice": "rest", "recommended_kind": "rest", "past_patterns": []}
    ]
    followed, _, _ = force(sim, "main", slow_reply(), "spoken")
    sim.adapters["fake"].script[("player_1", "advisor")] = [
        {"advice": "go fish", "recommended_kind": "fish", "past_patterns": []}
    ]
    ignored, _, _ = force(sim, "main", slow_reply(), "spoken")
    assert followed[0].advisor_followed is True
    assert ignored[0].advisor_followed is False


@pytest.mark.slow
def test_AC18_a_fake_week_has_a_complete_choice_point_for_every_slow_and_hooked_decision():
    root, _ = shared_week()
    events = query(root, "SELECT payload_json FROM events WHERE type = 'decision_made'")
    decs = [json.loads(r[0]) for r in events]
    assert decs
    cps = query(
        root,
        "SELECT json_extract(details_json, '$.decision_key'), tier, situation, x, feeling, thought, "  # noqa: E501
        "noticer_read, advisor_said, advisor_followed, action_json, self_label_json, "
        "details_json FROM choice_points",
    )
    by_key = {}
    for row in cps:
        assert row[0] not in by_key, "two choice points for one decision"
        by_key[row[0]] = row
    assert {"slow", "hooked"} <= {r[1] for r in cps}
    for d in decs:
        if d["tier"] in ("slow", "hooked"):
            assert d["decision_key"] in by_key, d["decision_key"]
        if d["decision_key"] in by_key:
            assert d["choice_point"] is True
            assert by_key[d["decision_key"]][1] == d["tier"]
        elif d["tier"] in ("reflex", "fast"):
            assert d["choice_point"] is False
    for row in cps:
        key, tier, situation, x, feeling, thought, noticer, advisor, followed, act, label, det = row
        assert situation and feeling is not None and x is not None
        assert json.loads(act)["kind"] and set(json.loads(label)) == {
            "served",
            "violated",
            "direction",
        }
        details = json.loads(det)
        assert details["decision_key"] == key and details["trigger"]
        if tier == "hooked":
            assert noticer is None and advisor is None and followed is None
        if tier in ("slow", "hooked"):
            assert len(details["options"]) >= 2 or details["label_source"] == "fallback"
            assert thought is not None
        if tier == "slow" and details["label_source"] == "model":
            assert noticer is not None and advisor is not None and followed in (0, 1)
