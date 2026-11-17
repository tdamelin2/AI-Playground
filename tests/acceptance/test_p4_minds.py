"""Phase 4 acceptance tests: reply schemas, prompts, values (AC-2, AC-3, AC-11, AC-12)."""

from __future__ import annotations

import json
import re
import sqlite3

import pytest
from p4_helpers import (
    BANNED_RE,
    CFG,
    ROOT,
    clean,
    decisions,
    new_ai_sim,
    raise_int,
    shared_week,
)
from pydantic import ValidationError

from ai_island.llm.adapters import AnthropicAdapter
from ai_island.llm.fake import FakeAdapter
from ai_island.llm.schema_transform import provider_schema
from ai_island.llm.types import LLMRequest, PromptLayers
from ai_island.minds import prompts, schemas, values
from ai_island.minds.values import VALUE_IDS

LABEL = {"served": ["honesty"], "violated": [], "direction": "toward"}
ACTION = {"kind": "rest", "minutes": 5}
ALL_IDS = set(VALUE_IDS)


def option(**kw):
    base = {
        "action": ACTION, "serves": ["honesty"], "violates": [], "feel_now": 1, "feel_later": 2,
        "relationships": "fine", "villagers": "fine", "uncertainty": "low",
    }  # fmt: skip
    base.update(kw)
    return base


GOOD = {
    "fast": {
        "thought": "t", "action": ACTION, "self_label": LABEL, "expected_feel": 3,
        "needs_more_thought": False,
    },
    "slow": {
        "thought": "t", "options": [option(), option(feel_now=-2)], "choice_index": 0,
        "trade_off": "x", "self_label": LABEL,
    },
    "noticer": {"reads": [{"person": "Bo", "feeling": "calm", "intent": "trade", "uncertainty": "low"}]},  # noqa: E501
    "advisor": {"advice": "rest", "recommended_kind": "rest", "past_patterns": ["a"]},
    "ranking": {"entries": [{"value_id": v, "weight": 7.0} for v in VALUE_IDS]},
    "reflection": {
        "requested_changes": {"honesty": 2.0}, "cause_event_ids": [1],
        "invented_values": [], "identity": "I am Ada", "knowledge_updates": [],
        "rolling_summary": "a week", "insights": [],
    },
}  # fmt: skip


def parse_and_check(kind, data):
    reply = schemas.REPLY_TYPES[kind].model_validate(data)
    return schemas.check_reply(reply, ALL_IDS)


# --------------------------------------------------------------------------------- AC-2


@pytest.mark.parametrize("kind", sorted(GOOD))
def test_AC2_good_example_validates(kind):
    assert parse_and_check(kind, GOOD[kind]) == []


def bad_cases():
    bad = []

    def without(kind, key):
        d = dict(GOOD[kind])
        d.pop(key)
        return d

    def with_(kind, **kw):
        d = json.loads(json.dumps(GOOD[kind]))
        d.update(kw)
        return d

    bad.append(("fast_no_self_label", "fast", without("fast", "self_label")))
    bad.append(("slow_no_self_label", "slow", without("slow", "self_label")))
    bad.append(("fast_extra_field", "fast", with_("fast", surprise=1)))
    bad.append(("fast_feel_too_high", "fast", with_("fast", expected_feel=11)))
    bad.append(("fast_bad_action_kind", "fast", with_("fast", action={"kind": "teleport"})))
    bad.append(("slow_one_option", "slow", with_("slow", options=[option()])))
    bad.append(("slow_five_options", "slow", with_("slow", options=[option()] * 5)))
    bad.append(
        ("slow_bad_uncertainty", "slow", with_("slow", options=[option(uncertainty="x"), option()]))
    )
    bad.append(
        ("noticer_five_reads", "noticer", with_("noticer", reads=GOOD["noticer"]["reads"] * 5))
    )
    bad.append(("advisor_missing_advice", "advisor", without("advisor", "advice")))
    bad.append(("advisor_six_patterns", "advisor", with_("advisor", past_patterns=["a"] * 6)))
    bad.append(("ranking_not_a_list", "ranking", {"entries": "friendship"}))
    bad.append(("reflection_three_inventions", "reflection", with_("reflection", invented_values=[
        {"name": "n", "definition": "d", "priority": 1.0, "conflicts": [], "observable_behaviour": "b"}  # noqa: E501
    ] * 3)))  # fmt: skip
    bad.append(("reflection_zero_priority", "reflection", with_("reflection", invented_values=[
        {"name": "n", "definition": "d", "priority": 0, "conflicts": [], "observable_behaviour": "b"}  # noqa: E501
    ])))  # fmt: skip
    bad.append(("reflection_six_knowledge", "reflection", with_("reflection", knowledge_updates=[
        {"subject": "s", "claim": "c", "confidence": 0.5}
    ] * 6)))  # fmt: skip
    bad.append(("reflection_bad_confidence", "reflection", with_("reflection", knowledge_updates=[
        {"subject": "s", "claim": "c", "confidence": 1.5}
    ])))  # fmt: skip
    return bad


@pytest.mark.parametrize("name,kind,data", bad_cases(), ids=[c[0] for c in bad_cases()])
def test_AC2_bad_example_rejected(name, kind, data):
    try:
        problems = parse_and_check(kind, data)
    except ValidationError:
        return
    assert problems, f"{name} was accepted"


def test_AC2_unknown_value_id_in_label_is_a_problem():
    data = json.loads(json.dumps(GOOD["fast"]))
    data["self_label"]["served"] = ["not_a_value"]
    assert parse_and_check("fast", data)


def test_AC2_unknown_value_id_in_option_is_a_problem():
    data = json.loads(json.dumps(GOOD["slow"]))
    data["options"][0]["violates"] = ["nonsense"]
    assert parse_and_check("slow", data)


def test_AC2_choice_index_outside_options_is_a_problem():
    data = json.loads(json.dumps(GOOD["slow"]))
    data["choice_index"] = 5
    assert parse_and_check("slow", data)


def test_AC2_overlong_text_is_a_problem():
    data = json.loads(json.dumps(GOOD["fast"]))
    data["thought"] = "x" * (CFG.balance.mind.text_max_chars + 1)
    assert parse_and_check("fast", data)


def test_AC2_a_fast_reply_without_self_label_becomes_a_logged_fallback():
    # in a running game: the reply is a format error twice, the player rests, the failure is logged
    bad = {k: v for k, v in GOOD["fast"].items() if k != "self_label"}
    adapter = FakeAdapter(script={("player_1", "fast"): [bad, bad]})
    sim = new_ai_sim(adapter=adapter)
    sim.run(2)
    d = [p for p in decisions(sim) if p.player == "player_1" and p.tier == "fast"]
    assert d and d[0].source == "fallback" and d[0].failure == "format"
    assert json.loads(d[0].action)["kind"] == "rest"


# --------------------------------------------------------------------------------- AC-3


def _small_ai_week(tmp_path):
    sim = new_ai_sim(seats=(1, 2), seed=3, db_path=tmp_path / "run.db")
    for i, mark in enumerate((400, 900, 1400)):
        sim.run(mark - sim.world.tick)
        clean(sim)
        raise_int(sim, "spoken_to", f"player_{1 + i % 2}", source=f"player_{2 - i % 2}")
    sim.run(200)
    sim.save()
    db_path = tmp_path / "run.db"
    sim.db.close()
    return db_path


def _rows(db_path):
    con = sqlite3.connect(db_path)
    rows = con.execute(
        "SELECT id, tick, player_id, role, prompt_json, details_json FROM ai_calls ORDER BY id"
    ).fetchall()
    con.close()
    return [(i, t, p, r, json.loads(pj), json.loads(dj)) for i, t, p, r, pj, dj in rows]


FAMILY = {"fast": "player", "main": "player", "noticer": "noticer", "advisor": "advisor"}


def test_AC3_layer1_identical_per_player_and_family_and_two_cache_markers(tmp_path):
    rows = _rows(_small_ai_week(tmp_path))
    fixed = {}
    purposes = set()
    for _i, _t, pid, _role, prompt, details in rows:
        purpose = details["purpose"]
        purposes.add(purpose)
        if purpose in ("ranking", "judge"):  # Phase 5: the blind judge has its own prompts
            continue  # the day-0 ranking has its own prompt; the rule starts after it
        fixed.setdefault((pid, FAMILY[purpose]), set()).add(prompt["fixed"])
    assert {"fast", "main", "noticer", "advisor"} <= purposes
    assert fixed
    for key, variants in fixed.items():
        assert len(variants) == 1, f"layer 1 changed for {key}"
    # three layers present and layer 2 / layer 3 not empty for decisions
    main = next(r for r in rows if r[5]["purpose"] == "main")
    assert main[4]["slow"] and main[4]["current"]
    # the three layers differ between players (names differ)
    p1 = fixed[("player_1", "player")].copy().pop()
    p2 = fixed[("player_2", "player")].copy().pop()
    assert p1 != p2
    # Anthropic: exactly two cache markers, one after layer 1 and one after layer 2
    request = LLMRequest(
        key="k", tick=1, player_id="player_1", role="player_1_main", purpose="main",
        layers=PromptLayers(main[4]["fixed"], main[4]["slow"], main[4]["current"]),
        schema=schemas.SlowReply, max_output_tokens=8192, meta={},
    )  # fmt: skip
    kwargs = AnthropicAdapter(object()).build_kwargs(request, CFG.models.roles["player_1_main"])
    marked = [b for b in kwargs["system"] if "cache_control" in b]
    # Round 3: a third marked block holds the schema instruction (prompt mode), after both layers
    assert len(marked) == 3
    assert kwargs["system"][2]["text"].startswith("Reply with only one JSON object")
    assert kwargs["system"][0]["text"] == request.layers.fixed
    assert kwargs["system"][1]["text"] == request.layers.slow
    assert all("cache_control" not in m for m in kwargs["messages"])


def test_AC3_prompt_digest_helper_is_deterministic():
    a = prompts.fixed_layer("player", "Ada", ["A", "B", "C"])
    b = prompts.fixed_layer("player", "Ada", ["A", "B", "C"])
    assert a == b and prompts.fixed_digest(a) == prompts.fixed_digest(b)
    assert prompts.fixed_layer("noticer", "Ada", ["A", "B", "C"]) != a


# -------------------------------------------------------------------------------- AC-11


def _expected_guide(name, villagers):
    text = (ROOT / "docs/gameplay.md").read_text(encoding="utf-8")
    lines = []
    started = False
    for line in text.splitlines():
        if line.startswith("> You are **[Name]**"):
            started = True
        if started:
            if not line.startswith(">"):
                break
            lines.append(line[1:].lstrip(" ") if line != ">" else "")
    guide = "\n".join(lines)
    return guide.replace("[Name]", name).replace("[names]", ", ".join(villagers))


def _norm(text):
    return re.sub(r"\s+", " ", text).strip()


def test_AC11_opening_guide_matches_gameplay_md_with_names():
    got = prompts.opening_guide("Ada", ["Eli", "Fay", "Gus"])
    assert _norm(got) == _norm(_expected_guide("Ada", ["Eli", "Fay", "Gus"]))


def test_AC11_prompt_text_and_schemas_have_no_banned_word():
    parts = [
        prompts.opening_guide("Ada", ["Eli", "Fay", "Gus"]),
        prompts.value_library_text(),
        prompts.action_list_text(),
    ]
    for family in ("player", "noticer", "advisor"):
        parts.append(prompts.fixed_layer(family, "Ada", ["Eli", "Fay", "Gus"]))
    for cls in schemas.REPLY_TYPES.values():
        for provider in ("anthropic", "openai", "google", "mistral"):
            parts.append(json.dumps(provider_schema(cls, provider)))
    for text in parts:
        assert not BANNED_RE.search(text), BANNED_RE.search(text).group(0)


def test_AC11_check_clean_raises_on_banned_word():
    for word in ("AI", "model", "Claude", "game", "experiment", "observer", "Google"):
        with pytest.raises(prompts.PromptLeakError):
            prompts.check_clean(f"this is a {word} here")
    prompts.check_clean("The villagers gather wood. Mainly plain words.")


def test_AC11_guide_in_a_run_begins_with_the_players_name(tmp_path):
    rows = _rows(_small_ai_week(tmp_path))
    for _i, _t, pid, _role, prompt, details in rows:
        if details["purpose"] == "fast":
            name = {"player_1": "Ada", "player_2": "Bo"}[pid]
            assert prompt["fixed"].startswith(f"You are **{name}**")
            break
    else:
        pytest.fail("no fast call recorded")


@pytest.mark.slow
def test_AC11_no_prompt_of_a_fake_game_week_contains_a_banned_word():
    root, tick = shared_week()
    assert tick >= 10080
    con = sqlite3.connect(root / "run.db")
    rows = con.execute("SELECT id, prompt_json, details_json FROM ai_calls").fetchall()
    con.close()
    assert len(rows) > 500
    purposes = set()
    for rid, pj, dj in rows:
        prompt = json.loads(pj)
        purposes.add(json.loads(dj)["purpose"])
        for layer in ("fixed", "slow", "current"):
            hit = BANNED_RE.search(prompt[layer])
            assert hit is None, f"call {rid} layer {layer} has banned word {hit.group(0)!r}"
    assert {"fast", "main", "ranking", "reflection"} <= purposes


# -------------------------------------------------------------------------------- AC-12


def sum_close(w, total=100.0):
    return abs(sum(w.values()) - total) < 1e-6


def test_AC12_valid_ranking_is_unchanged():
    entries = [(v, 14.0 if i < 5 else (4.0 if i < 8 else 3.0)) for i, v in enumerate(VALUE_IDS)]
    weights, problems = values.repair_initial_weights(entries)
    assert problems == []
    assert [weights[v] for v in VALUE_IDS] == [e[1] for e in entries]


def test_AC12_equal_weights_are_repaired_and_reported():
    entries = [(v, 100.0 / 14) for v in VALUE_IDS]
    weights, problems = values.repair_initial_weights(entries)
    assert "core_below_min" in problems
    for v in VALUE_IDS[:5]:
        assert weights[v] == pytest.approx(10.0, abs=1e-6)
    for v in VALUE_IDS[5:]:
        assert weights[v] == pytest.approx(5.5556, abs=1e-3)
    assert sum_close(weights)


def test_AC12_garbage_ranking_is_repaired_to_a_valid_one():
    entries = [("nonsense", 50), ("honesty", -3), ("honesty", 4), ("work", float("nan"))]
    weights, problems = values.repair_initial_weights(entries)
    assert problems
    assert set(weights) == set(VALUE_IDS)
    assert sum_close(weights)
    ranked = sorted(weights.values(), reverse=True)
    assert all(10.0 - 1e-6 <= w <= 25.0 + 1e-6 for w in ranked[:5])
    assert all(w >= 1.0 - 1e-6 for w in ranked[5:])


def test_AC12_empty_ranking_uses_the_fallback():
    weights, problems = values.repair_initial_weights([])
    assert sum_close(weights)
    assert sorted(weights.values(), reverse=True)[0] == pytest.approx(10.0)
    assert problems


def test_AC12_core_is_top_five_and_background_not_above_core_min():
    entries = [
        (v, float(w))
        for v, w in zip(VALUE_IDS, [20, 18, 16, 14, 12, 4, 4, 3, 3, 2, 2, 1, 1, 0], strict=False)
    ]
    weights, _ = values.repair_initial_weights(entries)
    assert sum_close(weights)
    core = values.core_ids(weights)
    assert core == list(VALUE_IDS[:5])
    assert min(weights[c] for c in core) >= 10.0 - 1e-6
    assert max(weights[v] for v in weights if v not in core) <= min(weights[c] for c in core) + 1e-6
    assert min(weights.values()) >= 1.0 - 1e-6


def _value_rows(db_path, pid):
    con = sqlite3.connect(db_path)
    rows = con.execute(
        "SELECT game_week, value_id, old_weight, new_weight FROM value_history "
        "WHERE player_id = ? ORDER BY id",
        (pid,),
    ).fetchall()
    con.close()
    return rows


def test_AC12_day0_ranking_writes_14_history_rows(tmp_path):
    sim = new_ai_sim(seats=(1, 2), db_path=tmp_path / "run.db")
    sim.run(5)
    sim.save()
    sim.db.close()
    for pid in ("player_1", "player_2"):
        rows = _value_rows(tmp_path / "run.db", pid)
        assert len(rows) == 14
        assert all(r[0] == 0 and r[2] is None for r in rows)
        weights = {r[1]: r[3] for r in rows}
        assert set(weights) == set(VALUE_IDS)
        assert sum_close(weights)
        ranked = sorted(weights.values(), reverse=True)
        assert all(10.0 - 1e-6 <= w <= 25.0 + 1e-6 for w in ranked[:5])
        assert all(w >= 1.0 - 1e-6 for w in ranked)


def test_AC12_bad_ranking_from_the_model_is_repaired_and_logged(tmp_path):
    flat = {"entries": [{"value_id": v, "weight": 100.0 / 14} for v in VALUE_IDS]}
    adapter = FakeAdapter(script={("player_1", "ranking"): [flat]})
    sim = new_ai_sim(adapter=adapter, db_path=tmp_path / "run.db")
    sim.run(3)
    repaired = [e.payload for e in sim.events if e.type == "value_repaired"]
    assert repaired and repaired[0].player == "player_1"
    assert "core_below_min" in repaired[0].problems
    sim.save()
    sim.db.close()
    weights = {r[1]: r[3] for r in _value_rows(tmp_path / "run.db", "player_1")}
    for v in VALUE_IDS[:5]:
        assert weights[v] == pytest.approx(10.0, abs=1e-6)
    assert sum_close(weights)


def test_AC12_a_good_ranking_is_accepted_without_a_repair_event(tmp_path):
    good = [20.0, 16.0, 14.0, 12.0, 10.0, 6.0, 5.0, 4.0, 3.0, 3.0, 2.0, 2.0, 2.0, 1.0]
    reply = {
        "entries": [{"value_id": v, "weight": w} for v, w in zip(VALUE_IDS, good, strict=False)]
    }
    assert sum(good) == 100.0
    adapter = FakeAdapter(script={("player_1", "ranking"): [reply]})
    sim = new_ai_sim(adapter=adapter, db_path=tmp_path / "run.db")
    sim.run(3)
    assert not [e for e in sim.events if e.type == "value_repaired"]
    sim.save()
    sim.db.close()
    weights = {r[1]: r[3] for r in _value_rows(tmp_path / "run.db", "player_1")}
    assert [weights[v] for v in VALUE_IDS] == pytest.approx(good)


def test_AC12_ranking_happens_before_the_first_action():
    sim = new_ai_sim()
    adapter = sim.adapters["fake"]
    sim.run(3)
    keys = list(adapter.calls)
    assert keys[0].split("/")[2] == "ranking"
    first_action_tick = min(e.tick for e in sim.events if e.type == "action_started")
    assert first_action_tick >= int(keys[0].split("/")[0])
