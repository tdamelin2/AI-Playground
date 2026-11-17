"""Phase 5 Round 2 tests: strict schemas (map wire form), rejected requests, tool stops.

Written from the Contract change (2026-11-04 18:52). Offline only: mocked SDK clients and fakes.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import anthropic
import httpx
import pytest
from pydantic import BaseModel

from ai_island import cli
from ai_island.config import load_config
from ai_island.llm.adapters import AnthropicAdapter, map_error
from ai_island.llm.broker import CallBroker
from ai_island.llm.errors import NetworkError, ProviderRequestError, RunPaused
from ai_island.llm.fake import FakeAdapter
from ai_island.llm.ledger import SpendLedger
from ai_island.llm.schema_transform import PROVIDERS, from_wire, provider_schema
from ai_island.llm.types import LLMRequest, PromptLayers
from ai_island.measure.calibrate import run_calibration
from ai_island.measure.judge_check import run_judge_check
from ai_island.measure.judge_schemas import JUDGE_SCHEMAS
from ai_island.minds.schemas import REPLY_TYPES, FastReply, ReflectionReply, SlowReply
from ai_island.storage.db import RunDB

ROOT = Path(__file__).resolve().parents[2]
CFG = load_config(ROOT / "config")
ROLES = CFG.models.roles

ALL_SCHEMAS: dict[str, type[BaseModel]] = {**REPLY_TYPES, **JUDGE_SCHEMAS}
CASES = [(n, p) for n in ALL_SCHEMAS for p in PROVIDERS]


def _nodes(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _nodes(v)
    elif isinstance(node, list):
        for v in node:
            yield from _nodes(v)


def _action(**kw):
    base = {"kind": "trade", "target": "player_2"}
    base.update(kw)
    return base


def _fast(action):
    return {
        "thought": "t",
        "action": action,
        "self_label": {"served": [], "violated": [], "direction": "toward"},
        "expected_feel": 0,
        "needs_more_thought": False,
    }


# --------------------------------------------------------------------- strict schema rules


@pytest.mark.parametrize(("name", "provider"), CASES)
def test_R2_every_object_is_closed_with_properties_and_no_map_form(name, provider):
    schema = provider_schema(ALL_SCHEMAS[name], provider)
    for node in _nodes(schema):
        if node.get("type") == "object":
            assert "properties" in node, (name, provider, node)
            assert node.get("additionalProperties") is False, (name, provider, node)
        if "additionalProperties" in node:
            assert node["additionalProperties"] is False


@pytest.mark.parametrize("name", list(ALL_SCHEMAS))
def test_R2_anthropic_has_at_most_16_anyof_and_optionals_not_required(name):
    schema = provider_schema(ALL_SCHEMAS[name], "anthropic")
    assert sum(1 for n in _nodes(schema) if "anyOf" in n) <= 16
    for node in _nodes(schema):
        props = node.get("properties")
        if isinstance(props, dict) and "kind" in props and "feeling" not in props:
            # the action request: only the kind is mandatory
            if "target" in props:
                assert "target" in props and "target" not in node["required"]
                assert "offer" in props and "offer" not in node["required"]
                assert "kind" in node["required"]


@pytest.mark.parametrize("provider", ["openai", "xai"])
@pytest.mark.parametrize("name", list(ALL_SCHEMAS))
def test_R2_openai_and_xai_require_every_property(name, provider):
    schema = provider_schema(ALL_SCHEMAS[name], provider)
    for node in _nodes(schema):
        props = node.get("properties")
        if isinstance(props, dict):
            assert set(node["required"]) == set(props), (name, set(props) - set(node["required"]))


@pytest.mark.parametrize("provider", PROVIDERS)
def test_R2_map_fields_are_key_value_lists_on_the_wire(provider):
    schema = provider_schema(SlowReply, provider)
    dump = json.dumps(schema)
    assert '"key"' in dump and '"value"' in dump
    found = False
    for node in _nodes(schema):
        props = node.get("properties")
        if isinstance(props, dict) and "offer" in props:
            found = True
            text = json.dumps(props["offer"])
            assert '"array"' in text and '"key"' in text and '"value"' in text
    assert found


class Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _slow_request():
    return LLMRequest(
        key="100/player_1/slow/0", tick=100, player_id="player_1", role="player_1_helper",
        purpose="slow", layers=PromptLayers("F", "S", "C"), schema=SlowReply,
        max_output_tokens=500, meta={"family": "slow"},
    )  # fmt: skip


def test_R2_anthropic_request_kwargs_carry_the_closed_wire_schema():
    adapter = AnthropicAdapter(Obj(messages=Obj(create=lambda **kw: None)))
    role = ROLES["player_1_helper"].model_copy(update={"output_mode": "schema"})  # Round 3
    kw = adapter.build_kwargs(_slow_request(), role)
    schema = kw["output_config"]["format"]["schema"]
    for node in _nodes(schema):
        if node.get("type") == "object":
            assert "properties" in node and node["additionalProperties"] is False
    assert sum(1 for n in _nodes(schema) if "anyOf" in n) <= 16


# ------------------------------------------------------------------------------ round trip


def test_R2_from_wire_turns_entry_lists_into_dicts_in_fast_and_slow():
    action = _action(offer=[{"key": "wood", "value": 3}], want=[{"key": "stone", "value": 1}])
    fast = FastReply.model_validate(from_wire(_fast(action), FastReply))
    assert fast.action.offer == {"wood": 3} and fast.action.want == {"stone": 1}
    opt = {
        "action": action, "serves": [], "violates": [], "feel_now": 0, "feel_later": 0,
        "relationships": "r", "villagers": "v", "uncertainty": "low",
    }  # fmt: skip
    slow = {
        "thought": "t", "options": [opt, opt], "choice_index": 0, "trade_off": "x",
        "self_label": {"served": [], "violated": [], "direction": "toward"},
    }  # fmt: skip
    got = SlowReply.model_validate(from_wire(slow, SlowReply))
    assert got.options[1].action.offer == {"wood": 3}


def test_R2_from_wire_plain_dicts_pass_and_missing_optional_is_none():
    fast = FastReply.model_validate(from_wire(_fast(_action(offer={"wood": 3})), FastReply))
    assert fast.action.offer == {"wood": 3}
    bare = FastReply.model_validate(from_wire(_fast({"kind": "rest"}), FastReply))
    assert bare.action.offer is None and bare.action.target is None


def test_R2_repeated_key_is_an_error():
    action = _action(offer=[{"key": "wood", "value": 1}, {"key": "wood", "value": 2}])
    with pytest.raises(ValueError):
        from_wire(_fast(action), FastReply)


def test_R2_reflection_list_and_legacy_forms_parse():
    base = {
        "cause_event_ids": [], "invented_values": [], "identity": "i",
        "knowledge_updates": [], "rolling_summary": "s", "insights": [],
    }  # fmt: skip
    new = {**base, "requested_changes": [{"key": "courage", "value": 0.5}]}
    old = {**base, "requested_changes": [{"value_id": "courage", "delta": 0.5}]}
    for data in (new, old):
        got = ReflectionReply.model_validate(from_wire(data, ReflectionReply))
        assert got.requested_changes == {"courage": 0.5}


def _request(schema: type[BaseModel] = FastReply, purpose="fast"):
    return LLMRequest(
        key=f"100/player_1/{purpose}/0", tick=100, player_id="player_1",
        role="player_1_helper", purpose=purpose, layers=PromptLayers("F " * 20, "S", "C"),
        schema=schema, max_output_tokens=ROLES["player_1_helper"].max_output_tokens,
        meta={"family": "fast"},
    )  # fmt: skip


def _one(request):
    return (yield request)


def _broker(adapter, db=None, ledger=None):
    ledger = ledger or SpendLedger(1000.0, 0.8)
    broker = CallBroker(db, CFG.models, CFG.run.ai, {"fake": adapter}, ledger, sleep=lambda s: None)
    return broker, ledger


def test_R2_broker_converts_wire_lists_and_formats_errors_on_repeat():
    ok = _fast(_action(offer=[{"key": "wood", "value": 3}]))
    broker, _ = _broker(FakeAdapter(script={("player_1", "fast"): [ok]}))
    res = broker.run({"p": _one(_request())})["p"]
    assert res.status == "ok" and res.parsed.action.offer == {"wood": 3}
    dup = _fast(_action(offer=[{"key": "wood", "value": 1}, {"key": "wood", "value": 1}]))
    adapter = FakeAdapter(script={("player_1", "fast"): [dup, dup]})
    broker, _ = _broker(adapter)
    res = broker.run({"p": _one(_request())})["p"]
    assert res.status == "format_error" and adapter.calls[_request().key] == 2


# ------------------------------------------------------------------------- rejected request


def _bad_request_error(status=400):
    req = httpx.Request("POST", "https://example.invalid/v1/messages")
    resp = httpx.Response(status, request=req, json={"error": {"message": "bad schema"}})
    cls = anthropic.BadRequestError if status == 400 else anthropic.NotFoundError
    return cls("bad schema", response=resp, body=None)


def test_R2_map_error_makes_4xx_a_provider_request_error_but_429_is_not():
    err = map_error(_bad_request_error(400))
    assert isinstance(err, ProviderRequestError) and err.status_code == 400
    assert isinstance(map_error(_bad_request_error(404)), ProviderRequestError)
    req = httpx.Request("POST", "https://example.invalid")
    rate = anthropic.RateLimitError("slow", response=httpx.Response(429, request=req), body=None)
    assert not isinstance(map_error(rate), ProviderRequestError)


class RejectingClient:
    def __init__(self, error):
        self.error = error
        self.calls = 0
        self.messages = Obj(create=self._create)

    def _create(self, **kw):
        self.calls += 1
        raise self.error


def test_R2_rejected_request_pauses_with_provider_error_and_writes_a_zero_cost_row(tmp_path):
    client = RejectingClient(_bad_request_error())
    db = RunDB.create(tmp_path / "run.db")
    broker, ledger = _broker(AnthropicAdapter(client), db=db)
    with pytest.raises(RunPaused) as exc:
        broker.run({"p": _one(_request())})
    assert exc.value.reason == "provider_error"
    assert "400" in str(exc.value)
    assert client.calls == 1  # not retried
    assert ledger.reserved_usd == 0.0 and ledger.total_usd == 0.0
    db.close()
    con = sqlite3.connect(tmp_path / "run.db")
    rows = con.execute("SELECT status, cost_usd FROM ai_calls").fetchall()
    spend = con.execute("SELECT COUNT(*) FROM spend").fetchone()[0]
    con.close()
    assert rows == [("request_error", 0.0)]
    assert spend == 0


def test_R2_resumed_broker_asks_again_instead_of_reusing_a_rejected_attempt(tmp_path):
    db = RunDB.create(tmp_path / "run.db")
    broker, _ = _broker(AnthropicAdapter(RejectingClient(_bad_request_error())), db=db)
    with pytest.raises(RunPaused):
        broker.run({"p": _one(_request())})
    good = _fast({"kind": "rest"})
    adapter = FakeAdapter(script={("player_1", "fast"): [good]})
    broker2, _ = _broker(adapter, db=db)
    res = broker2.run({"p": _one(_request())})["p"]
    assert res.status == "ok"
    assert adapter.calls[_request().key] == 1
    db.close()


# --------------------------------------------------------------------- calibrate / judge-check


class Rejecting(FakeAdapter):
    def generate(self, request, role):
        raise ProviderRequestError("anthropic", 400, "bad schema thing", "req_1")


class Offline(FakeAdapter):
    def generate(self, request, role):
        raise NetworkError("down")


def _no_wait_config():
    ai = CFG.run.ai.model_copy(update={"retry_wait_seconds": [0.0, 0.0, 0.0]})
    return CFG.model_copy(update={"run": CFG.run.model_copy(update={"ai": ai})})


def test_R2_judge_check_stops_with_report_on_a_rejected_request(tmp_path):
    result = run_judge_check(CFG, {"fake": Rejecting()}, 1.0, tmp_path, dry_run=True, emit=str)
    assert result.stopped and not result.complete
    assert result.stop_reason == "provider_error"
    assert "bad schema thing" in result.stop_detail
    assert (tmp_path / "report.md").exists()
    assert result.total_cost_usd == 0.0


def test_R2_calibrate_stops_with_report_on_a_rejected_request(tmp_path):
    report = run_calibration(CFG, {"fake": Rejecting()}, 1.0, tmp_path, dry_run=True)
    assert report.stopped and not report.complete
    assert report.stop_reason == "provider_error"
    text = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "bad schema thing" in text or "rejected" in text.lower()
    assert report.spent_usd == 0.0


def test_R2_network_pause_stops_the_tools_with_a_report(tmp_path):
    cfg = _no_wait_config()
    jc = run_judge_check(cfg, {"fake": Offline()}, 1.0, tmp_path / "j", dry_run=True, emit=str)
    assert jc.stopped and jc.stop_reason == "network"
    assert (tmp_path / "j" / "report.md").exists()
    cal = run_calibration(cfg, {"fake": Offline()}, 1.0, tmp_path / "c", dry_run=True)
    assert cal.stopped and cal.stop_reason == "network"
    assert (tmp_path / "c" / "report.md").exists()


@pytest.mark.parametrize("tool", ["calibrate", "judge-check"])
def test_R2_cli_rejected_request_exits_4_without_a_traceback(tool, monkeypatch, capsys):
    monkeypatch.setattr(FakeAdapter, "generate", Rejecting.generate)
    code = cli.main([tool, "--dry-run", "--max-dollars", "1"])
    out = capsys.readouterr()
    assert code == 4, out.out + out.err
    assert "Traceback" not in out.out + out.err
    assert "rejected a request" in out.out
    assert "bad schema thing" in out.out


@pytest.mark.parametrize("tool", ["calibrate", "judge-check"])
def test_R2_cli_network_pause_exits_4_without_a_traceback(tool, monkeypatch, capsys):
    monkeypatch.setattr(FakeAdapter, "generate", Offline.generate)
    cfg = _no_wait_config()
    monkeypatch.setattr(cli, "load_sim_config", lambda *a, **k: cfg)
    code = cli.main([tool, "--dry-run", "--max-dollars", "1"])
    out = capsys.readouterr()
    assert code == 4, out.out + out.err
    assert "Traceback" not in out.out + out.err
    assert "internet" in out.out.lower()


def test_R2_cli_main_catches_any_llm_error_in_one_plain_line(monkeypatch, capsys):
    def boom(args):
        raise ProviderRequestError("anthropic", 400, "bad schema thing")

    monkeypatch.setattr(cli, "_cmd_judge_check", boom)
    code = cli.main(["judge-check", "--dry-run", "--max-dollars", "1"])
    out = capsys.readouterr()
    assert code == 2
    assert "Traceback" not in out.out + out.err
    assert "bad schema thing" in out.err
