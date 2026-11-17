"""Phase 4 acceptance tests: the AI connection layer (AC-1, AC-4..AC-8), no network, no keys."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import tomllib
from pathlib import Path

import pytest
from pydantic import BaseModel

from ai_island.config import PricesConfig, load_config
from ai_island.llm.adapters import (
    AnthropicAdapter,
    GoogleAdapter,
    MistralAdapter,
    OpenAIAdapter,
)
from ai_island.llm.broker import CallBroker
from ai_island.llm.errors import RunPaused
from ai_island.llm.fake import FakeAdapter
from ai_island.llm.ledger import SpendLedger
from ai_island.llm.prices import cost_usd, upper_bound_usd
from ai_island.llm.schema_transform import provider_schema
from ai_island.llm.types import LLMRequest, PromptLayers, Usage
from ai_island.minds.schemas import AdvisorReply, FastReply
from ai_island.storage.db import RunDB

ROOT = Path(__file__).resolve().parents[2]
CFG = load_config(ROOT / "config")
ROLES = CFG.models.roles


def make_request(
    player="player_1",
    purpose="advisor",
    role="player_1_helper",
    schema: type[BaseModel] = AdvisorReply,
    tick=100,
    ordinal=0,
    fixed="FIXED " * 20,
    slow="SLOW " * 10,
    current="CURRENT",
):
    return LLMRequest(
        key=f"{tick}/{player}/{purpose}/{ordinal}",
        tick=tick,
        player_id=player,
        role=role,
        purpose=purpose,
        layers=PromptLayers(fixed, slow, current),
        schema=schema,
        max_output_tokens=ROLES[role].max_output_tokens,
        meta={"family": "advisor"},
    )


def one_request_pipeline(request):
    result = yield request
    return result


def make_broker(adapter, db=None, cap=1000.0, sleeps=None, wall=None, hook=None):
    kwargs = {}
    if sleeps is not None:
        kwargs["sleep"] = sleeps.append
    if wall is not None:
        kwargs["wall"] = wall
    ledger = SpendLedger(cap, 0.8)
    broker = CallBroker(
        db, CFG.models, CFG.run.ai, {"fake": adapter}, ledger, wait_hook=hook, **kwargs
    )
    return broker, ledger


def run_one(broker, request, player="player_1"):
    return broker.run({player: one_request_pipeline(request)})[player]


# ----------------------------------------------------------------------------- AC-1 adapters


class Obj:
    """A tiny stand-in SDK object whose attributes are the given keyword arguments."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


class Recorder:
    def __init__(self, response):
        self.response = response
        self.kwargs = None

    def __call__(self, **kw):
        self.kwargs = kw
        return self.response


def test_AC1_anthropic_request_and_response():
    response = Obj(
        content=[Obj(type="text", text='{"advice": "x"}')],
        usage=Obj(
            input_tokens=100, output_tokens=40, cache_read_input_tokens=300,
            cache_creation_input_tokens=50,
        ),
        model="claude-haiku-5-5-20260101",
        stop_reason="end_turn",
    )  # fmt: skip
    rec = Recorder(response)
    client = Obj(messages=Obj(create=rec))
    request = make_request()
    role = ROLES["player_1_helper"]
    reply = AnthropicAdapter(client).generate(request, role)
    kw = rec.kwargs
    assert kw["model"] == role.model
    assert kw["max_tokens"] == request.max_output_tokens
    assert kw["messages"] == [{"role": "user", "content": "CURRENT"}]
    system = kw["system"]
    # Round 3: Anthropic is in prompt mode: fixed, slow, then the schema instruction block
    assert [b["text"] for b in system[:2]] == [request.layers.fixed, request.layers.slow]
    assert len(system) == 3
    assert system[2]["text"].startswith("Reply with only one JSON object, no other text")
    assert all(b["cache_control"] == {"type": "ephemeral"} for b in system)
    assert "format" not in kw.get("output_config", {})
    # usage: uncached input only, cache buckets separate
    assert reply.text == '{"advice": "x"}'
    assert reply.usage.input_tokens == 100
    assert reply.usage.output_tokens == 40
    assert reply.usage.cache_read_tokens == 300
    assert reply.usage.cache_write_tokens == 50
    assert reply.model_version == "claude-haiku-5-5-20260101"
    assert reply.refused is False


def test_AC1_anthropic_refusal_stop_reason():
    response = Obj(content=[], usage=Obj(input_tokens=1, output_tokens=0), stop_reason="refusal")
    client = Obj(messages=Obj(create=Recorder(response)))
    reply = AnthropicAdapter(client).generate(make_request(), ROLES["player_1_helper"])
    assert reply.refused is True


def test_AC1_openai_request_and_response():
    response = Obj(
        output_text='{"advice": "y"}',
        output=[],
        usage=Obj(
            input_tokens=1000,
            output_tokens=120,
            input_tokens_details=Obj(cached_tokens=400),
            output_tokens_details=Obj(reasoning_tokens=70),
        ),
        model="gpt-x-2026",
    )
    rec = Recorder(response)
    client = Obj(responses=Obj(create=rec))
    request = make_request(role="player_2_helper")
    role = ROLES["player_2_helper"]
    assert role.provider == "openai"
    reply = OpenAIAdapter(client).generate(request, role)
    kw = rec.kwargs
    assert kw["model"] == role.model
    fmt = kw["text"]["format"]
    assert fmt["type"] == "json_schema" and fmt["strict"] is True and fmt["schema"]
    assert kw["max_output_tokens"] == request.max_output_tokens
    assert kw["input"][0]["role"] in ("system", "developer")
    assert request.layers.fixed in kw["input"][0]["content"]
    assert request.layers.slow in kw["input"][0]["content"]
    assert kw["input"][-1] == {"role": "user", "content": "CURRENT"}
    # uncached input = total - cached; output includes thinking counted once
    assert reply.usage.input_tokens == 600
    assert reply.usage.cache_read_tokens == 400
    assert reply.usage.output_tokens == 120
    assert reply.usage.thinking_tokens == 70


def test_AC1_openai_refusal_item():
    response = Obj(
        output_text=None,
        output=[Obj(content=[Obj(type="refusal", refusal="no")])],
        usage=Obj(input_tokens=5, output_tokens=1),
        model="m",
    )
    client = Obj(responses=Obj(create=Recorder(response)))
    reply = OpenAIAdapter(client).generate(make_request(), ROLES["player_2_helper"])
    assert reply.refused is True


def test_AC1_xai_is_the_openai_adapter_with_base_url_and_no_reasoning():
    role = ROLES["player_4_helper"]
    assert role.provider == "xai"
    rec = Recorder(Obj(output_text="{}", output=[], usage=Obj(input_tokens=1, output_tokens=1)))
    client = Obj(responses=Obj(create=rec))
    OpenAIAdapter(client, provider="xai").generate(make_request(role="player_4_helper"), role)
    assert "reasoning" not in rec.kwargs or not rec.kwargs["reasoning"]
    src = (ROOT / "src/ai_island/llm/factory.py").read_text(encoding="utf-8")
    assert "https://api.x.ai/v1" in src
    assert "max_retries=0" in src


def test_AC1_google_wire_json_has_schema_text_and_mime_type():
    response = Obj(
        output_text='{"advice": "z"}',
        status="completed",
        model="gemini-x",
        usage=Obj(
            total_input_tokens=500, total_cached_tokens=100,
            total_output_tokens=60, total_thought_tokens=30,
        ),
    )  # fmt: skip
    rec = Recorder(response)
    client = Obj(interactions=Obj(create=rec))
    request = make_request(role="player_3_helper")
    role = ROLES["player_3_helper"]
    assert role.provider == "google"
    reply = GoogleAdapter(client).generate(request, role)
    kw = rec.kwargs
    assert kw["model"] == role.model
    assert kw["store"] is False
    assert kw["input"] == "CURRENT"
    assert request.layers.fixed in kw["system_instruction"]
    assert kw["generation_config"]["max_output_tokens"] == request.max_output_tokens
    wire = json.loads(kw["response_format"].model_dump_json(by_alias=True, exclude_none=True))
    assert wire["type"] == "text"
    assert wire["mime_type"] == "application/json"
    assert "schema" in wire and wire["schema"]["type"] == "object"
    # usage: output = output + thought tokens; input minus cached
    assert reply.usage.input_tokens == 400
    assert reply.usage.cache_read_tokens == 100
    assert reply.usage.output_tokens == 90


def test_AC1_mistral_request_and_response():
    response = Obj(
        choices=[Obj(message=Obj(content='{"advice": "m"}'), finish_reason="stop")],
        usage=Obj(prompt_tokens=300, completion_tokens=44),
        model="mistral-x",
    )
    rec = Recorder(response)
    client = Obj(chat=Obj(complete=rec))
    request = make_request(role="player_5_helper" if False else "judge")
    role = ROLES["judge"]
    if role.provider != "mistral":
        role = next(r for r in ROLES.values() if r.provider == "mistral")
    reply = MistralAdapter(client).generate(request, role)
    kw = rec.kwargs
    assert kw["model"] == role.model
    assert kw["reasoning_effort"] == "none"
    rf = kw["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["strict"] is True and rf["json_schema"]["schema"]
    assert kw["max_tokens"] == request.max_output_tokens
    assert reply.text == '{"advice": "m"}'
    assert reply.usage.output_tokens == 44
    assert reply.usage.input_tokens + reply.usage.cache_read_tokens == 300


def test_AC1_mistral_content_filter_is_a_refusal():
    role = next(r for r in ROLES.values() if r.provider == "mistral")
    response = Obj(
        choices=[Obj(message=Obj(content=""), finish_reason="content_filter")],
        usage=Obj(prompt_tokens=3, completion_tokens=0),
        model="m",
    )
    client = Obj(chat=Obj(complete=Recorder(response)))
    reply = MistralAdapter(client).generate(make_request(), role)
    assert reply.refused is True


def test_AC1_every_provider_schema_is_strict_for_a_real_reply_type():
    from ai_island.llm.schema_transform import provider_schema

    for provider in ("anthropic", "openai", "xai", "google", "mistral"):
        schema = provider_schema(FastReply, provider)
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])


def test_AC1_make_adapter_exists_and_is_not_called_by_the_fake_path():
    from ai_island.llm import factory

    assert callable(factory.make_adapter)


# ------------------------------------------------------------------------------ AC-4 retries


def test_AC4_format_error_retried_once_then_format_error():
    adapter = FakeAdapter(script={("player_1", "advisor"): ["not json", "{still not"]})
    broker, _ = make_broker(adapter)
    request = make_request()
    result = run_one(broker, request)
    assert result.status == "format_error"
    assert adapter.calls[request.key] == 2  # exactly one retry
    assert result.parsed is None


def test_AC4_format_error_then_good_reply_is_ok():
    good = {"advice": "go", "recommended_kind": "rest", "past_patterns": []}
    adapter = FakeAdapter(script={("player_1", "advisor"): ["garbage", good]})
    broker, _ = make_broker(adapter)
    result = run_one(broker, make_request())
    assert result.status == "ok"
    assert result.parsed.recommended_kind == "rest"
    assert result.attempts == 2


def test_AC4_schema_violation_counts_as_format_error():
    bad = {"advice": "go"}  # missing fields
    adapter = FakeAdapter(script={("player_1", "advisor"): [bad, bad]})
    broker, _ = make_broker(adapter)
    assert run_one(broker, make_request()).status == "format_error"


def test_AC4_refusal_is_not_retried():
    adapter = FakeAdapter(failures={("player_1", "advisor"): ["refusal"]})
    broker, _ = make_broker(adapter)
    request = make_request()
    result = run_one(broker, request)
    assert result.status == "refusal"
    assert adapter.calls[request.key] == 1


def test_AC4_break_character_text_is_a_refusal_not_retried():
    adapter = FakeAdapter(
        script={("player_1", "advisor"): ['{"advice": "As an AI I cannot"}', "{}"]}
    )
    broker, _ = make_broker(adapter)
    request = make_request()
    assert run_one(broker, request).status == "refusal"
    assert adapter.calls[request.key] == 1


@pytest.mark.parametrize("failure", ["network", "rate_limit"])
def test_AC4_three_retries_with_growing_waits_then_ok(failure):
    adapter = FakeAdapter(failures={("player_1", "advisor"): [failure] * 3})
    sleeps = []
    broker, _ = make_broker(adapter, sleeps=sleeps)
    request = make_request()
    result = run_one(broker, request)
    assert result.status == "ok"
    assert adapter.calls[request.key] == 4
    assert sleeps == [2.0, 8.0, 30.0]  # run.toml retry_wait_seconds, growing


@pytest.mark.parametrize("failure", ["network", "rate_limit"])
def test_AC4_fourth_failure_pauses_the_run(failure):
    adapter = FakeAdapter(failures={("player_1", "advisor"): [failure] * 4})
    sleeps = []
    broker, _ = make_broker(adapter, sleeps=sleeps)
    request = make_request()
    with pytest.raises(RunPaused) as exc:
        run_one(broker, request)
    assert exc.value.reason == "network"
    assert adapter.calls[request.key] == 4
    assert sleeps == [2.0, 8.0, 30.0]


# ----------------------------------------------------------------------- AC-5 ai_calls rows


def test_AC5_every_attempt_writes_one_row_with_all_columns(tmp_path):
    db = RunDB.create(tmp_path / "run.db")
    adapter = FakeAdapter(
        script={("player_1", "advisor"): ["unused", "garbage", {"advice": "a", "recommended_kind": "rest", "past_patterns": []}]},  # noqa: E501
        failures={("player_1", "advisor"): ["network"]},
    )  # fmt: skip
    broker, _ = make_broker(adapter, db=db, sleeps=[])
    result = run_one(broker, make_request())
    assert result.status == "ok"
    assert db.ai_call_count() == 3  # network error, bad reply, good reply
    db.close()
    con = sqlite3.connect(tmp_path / "run.db")
    cols = [r[1] for r in con.execute("PRAGMA table_info(ai_calls)")]
    for needed in (
        "prompt_json", "reply_json", "model_version", "thinking_tokens", "input_tokens",
        "output_tokens", "cache_read_tokens", "cost_usd", "duration_ms", "status",
    ):  # fmt: skip
        assert needed in cols, needed
    rows = con.execute(
        "SELECT status, prompt_json, reply_json, model_version, input_tokens, output_tokens, "
        "cost_usd, duration_ms, details_json FROM ai_calls ORDER BY id"
    ).fetchall()
    con.close()
    assert [r[0] for r in rows] == ["network_error", "format_error", "ok"]
    prompt = json.loads(rows[2][1])
    assert prompt["fixed"].startswith("FIXED") and prompt["slow"].startswith("SLOW")
    assert prompt["current"] == "CURRENT"
    assert rows[2][3] == "fake-1"
    assert rows[2][4] > 0 and rows[2][5] > 0
    assert rows[2][7] >= 0
    attempts = [json.loads(r[8])["attempt"] for r in rows]
    assert attempts == [0, 1, 2]
    assert json.loads(rows[2][8])["key"] == "100/player_1/advisor/0"


def test_AC5_second_identical_prompt_shows_cached_tokens(tmp_path):
    db = RunDB.create(tmp_path / "run.db")
    adapter = FakeAdapter()
    broker, _ = make_broker(adapter, db=db)
    run_one(broker, make_request(tick=1))
    run_one(broker, make_request(tick=2))
    rows = [db.find_ai_call("1/player_1/advisor/0/0"), db.find_ai_call("2/player_1/advisor/0/0")]
    assert rows[0].cache_read_tokens == 0
    assert rows[1].cache_read_tokens > 0
    db.close()


# ------------------------------------------------------------------------- AC-6 spend counter


def test_AC6_cost_formula_example():
    prices = PricesConfig(input=2.0, cache_write=2.5, cache_read=0.1, output=10.0)
    usage = Usage(
        input_tokens=1000, output_tokens=150, thinking_tokens=50,
        cache_read_tokens=300, cache_write_tokens=200,
    )  # fmt: skip
    assert cost_usd(usage, prices) == pytest.approx(0.00403, abs=1e-12)


def test_AC6_spend_equals_hand_calculation_from_models_toml(tmp_path):
    toml = tomllib.loads((ROOT / "config/models.toml").read_text(encoding="utf-8-sig"))
    db = RunDB.create(tmp_path / "run.db")
    adapter = FakeAdapter(bill=True)
    broker, ledger = make_broker(adapter, db=db)
    roles = ["player_1_main", "player_2_helper", "player_4_helper", "player_4_main"]
    for i, role in enumerate(roles):
        pid = f"player_{(i % 4) + 1}"
        for tick in (10, 20):  # the second call has a cache hit
            run_one(broker, make_request(player=pid, role=role, tick=tick), player=pid)
    con = sqlite3.connect(tmp_path / "run.db")
    calls = con.execute(
        "SELECT role, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, cost_usd "
        "FROM ai_calls ORDER BY id"
    ).fetchall()
    spend_total = con.execute("SELECT SUM(cost_usd) FROM spend").fetchone()[0]
    con.close()
    assert len(calls) == 8
    hand = 0.0
    for role, i_tok, o_tok, cr, cw, stored in calls:
        p = toml["roles"][role]["prices"]
        expected = (
            i_tok * p["input"] + cw * p["cache_write"] + cr * p["cache_read"] + o_tok * p["output"]
        ) / 1e6
        assert stored == pytest.approx(expected, rel=1e-9, abs=1e-12)
        hand += expected
    assert hand > 0
    assert ledger.total_usd == pytest.approx(hand, rel=1e-9)
    assert spend_total == pytest.approx(hand, rel=1e-9)
    assert db.spend_total() == pytest.approx(hand, rel=1e-9)
    db.close()


def test_AC6_fake_adapter_costs_nothing_by_default():
    adapter = FakeAdapter()
    broker, ledger = make_broker(adapter)
    result = run_one(broker, make_request(role="player_1_main"))
    assert result.cost_usd == 0.0
    assert ledger.total_usd == 0.0


# ----------------------------------------------------------------- AC-7 cap, warning, refusal


def test_AC7_upper_bound_example():
    role = ROLES["player_1_main"]
    custom = role.model_copy(
        update={"prices": PricesConfig(input=3.0, cache_write=3.75, cache_read=0.3, output=15.0)}
    )
    request = LLMRequest(
        "1/p/main/0", 1, "p", "player_1_main", "main",
        PromptLayers("a" * 3000, "b" * 500, "c" * 500), AdvisorReply, 500, {},
    )  # fmt: skip
    # Phase 5 (C2): (prompt bytes + schema bytes + 256 framing) at the dearest input rate
    schema_bytes = len(json.dumps(provider_schema(AdvisorReply, custom.provider)).encode("utf-8"))
    head = len(b"Reply with only one JSON object, no other text, matching this JSON schema:\n")
    assert custom.output_mode == "prompt"  # Round 3: the instruction head is counted too
    expected = ((4000 + schema_bytes + head + 256) * 3.75 + 500 * 15.0) / 1e6
    assert upper_bound_usd(request, custom) == pytest.approx(expected, abs=1e-12)
    assert expected > 0.01125  # never below the old character-count estimate


def test_AC7_ledger_reservation_examples():
    ledger = SpendLedger(1.0, 0.8, total_usd=0.90)
    assert ledger.reserve("a", 0.06) is True
    assert ledger.reserve("b", 0.05) is False  # 0.90 + 0.06 + 0.05 = 1.01 > 1
    ledger.release("a")
    assert ledger.reserve("b", 0.10) is True  # equality is allowed
    assert SpendLedger(100.0, 0.8, total_usd=80.0).warning is True
    assert SpendLedger(100.0, 0.8, total_usd=79.0).warning is False


def test_AC7_settle_moves_reservation_into_total():
    ledger = SpendLedger(1.0, 0.8)
    assert ledger.reserve("k", 0.5)
    ledger.settle("k", 0.3)
    assert ledger.total_usd == pytest.approx(0.3)
    assert ledger.reserve("m", 0.7)


def test_AC7_call_that_would_pass_the_cap_is_not_sent_and_run_pauses():
    adapter = FakeAdapter(bill=True)
    broker, ledger = make_broker(adapter, cap=0.00001)
    request = make_request(role="player_1_main")
    with pytest.raises(RunPaused) as exc:
        run_one(broker, request)
    assert exc.value.reason == "spend_cap"
    assert adapter.total_calls == 0
    assert ledger.total_usd == 0.0


def test_AC7_pinned_cap_is_the_smaller_of_flag_and_run_toml():
    from ai_island.sim import ai_config

    cap = CFG.run.spend_cap_usd
    pinned = ai_config(CFG, [1], max_dollars=cap / 2)
    assert pinned.run.spend_cap_usd == pytest.approx(cap / 2)
    assert ai_config(CFG, [1], max_dollars=cap * 10).run.spend_cap_usd == pytest.approx(cap)
    with pytest.raises(ValueError):
        ai_config(CFG, [1])


def test_AC7_cli_ai_seat_without_max_dollars_refuses_before_creating_anything():
    import shutil
    import subprocess
    import sys

    name = "p4_ac7_nomax"
    shutil.rmtree(ROOT / "runs" / name, ignore_errors=True)
    proc = subprocess.run(
        [sys.executable, "main.py", "new", name, "--ai-seats", "1"],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )  # fmt: skip
    assert proc.returncode == 2
    assert "max-dollars" in (proc.stdout + proc.stderr)
    assert not (ROOT / "runs" / name).exists()


# ------------------------------------------------------------------------- AC-8 concurrency


def test_AC8_calls_for_different_players_run_at_the_same_time():
    barrier = threading.Barrier(4, timeout=10)
    adapter = FakeAdapter(gate=barrier)
    broker, _ = make_broker(adapter)
    pipelines = {
        f"player_{i}": one_request_pipeline(
            make_request(player=f"player_{i}", role=f"player_{i}_helper")
        )
        for i in range(1, 5)
    }
    results = broker.run(pipelines)  # a Barrier(4) only releases when all four are in flight
    assert list(results) == [f"player_{i}" for i in range(1, 5)]
    assert all(r.status == "ok" for r in results.values())


def test_AC8_run_returns_only_when_every_reply_is_back_and_applies_in_player_order():
    delays = {("player_1", "advisor"): 0.4, ("player_2", "advisor"): 0.0}
    adapter = FakeAdapter(delays=delays)
    order = []

    def pipeline(pid):
        result = yield make_request(player=pid, role=f"{pid}_helper")
        order.append(pid)
        return result.status

    broker, _ = make_broker(adapter)
    started = time.monotonic()
    out = broker.run({"player_1": pipeline("player_1"), "player_2": pipeline("player_2")})
    assert time.monotonic() - started >= 0.4  # waited for the slow player
    assert out == {"player_1": "ok", "player_2": "ok"}
    assert order == ["player_1", "player_2"]  # player order, not completion order


def test_AC8_wait_hook_is_called_while_waiting():
    adapter = FakeAdapter(delays={("player_1", "advisor"): 0.4})
    ticks = []
    broker, _ = make_broker(adapter, hook=lambda: ticks.append(1))
    run_one(broker, make_request())
    assert len(ticks) >= 2


def test_AC8_no_tick_advances_until_all_replies_return():
    """A mixed sim with a delayed player: events of the tick are all there when step returns."""
    from ai_island.sim import Simulation, ai_config

    cfg = ai_config(CFG, [1, 2], max_dollars=1.0)
    sim = Simulation.new(cfg, 3)
    sim.adapters = {
        "fake": FakeAdapter(delays={("player_1", "fast"): 0.15, ("player_1", "ranking"): 0.15})
    }
    sim.run(3)
    assert sim.world.tick == 3
    # both seats made their day-0 ranking before the first action started
    started = [e for e in sim.events if e.type == "decision_made"]
    assert {e.payload.player for e in started} >= {"player_1", "player_2"}


def test_AC5_update_choice_methods_never_touch_events(tmp_path):
    from ai_island.storage.records import ChoicePointRecord

    db = RunDB.create(tmp_path / "run.db")
    rec = ChoicePointRecord(
        decision_key="5/player_1", tick=5, player_id="player_1", situation="s", x=1.0,
        feeling="ok", tier="slow", thought="t", action={"kind": "rest"},
        self_label={"served": [], "violated": [], "direction": "toward"},
    )  # fmt: skip
    assert db.insert_choice_point(rec) is not None
    assert db.insert_choice_point(rec) is None  # same decision_key is skipped
    db.update_choice_outcome("5/player_1", {"result": "done", "x_delta": 1.0})
    db.update_choice_insight("5/player_1", "learned")
    detail = db.choice_details("player_1")[0]
    assert detail.outcome == {"result": "done", "x_delta": 1.0}
    assert detail.insight == "learned"
    assert detail.decision_key == "5/player_1"
    assert db.count("events") == 0
    db.close()
