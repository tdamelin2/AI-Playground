"""Phase 5 money-safety tests (AC-4, offline guard), from the Plan's Contract C2/C3."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import types
from unittest import mock

import pytest
from p4_helpers import CFG

from ai_island.llm import factory
from ai_island.llm.broker import CallBroker
from ai_island.llm.errors import RealCallsBlocked
from ai_island.llm.fake import FakeAdapter
from ai_island.llm.ledger import SpendLedger
from ai_island.llm.prices import upper_bound_usd
from ai_island.llm.schema_transform import provider_schema
from ai_island.llm.types import LLMRequest, PromptLayers
from ai_island.minds.schemas import FastReply
from ai_island.storage.db import AiCallRow, RunDB


def test_offline_switch_is_on_for_the_whole_test_session():
    assert os.environ.get("AI_ISLAND_OFFLINE") == "1"


@pytest.mark.parametrize("provider", ["mistral", "anthropic", "openai", "google", "xai"])
def test_offline_guard_blocks_every_real_adapter(provider):
    with pytest.raises(RealCallsBlocked):
        factory.make_adapter(provider)


def test_offline_guard_blocks_the_live_runtime():
    with pytest.raises(RealCallsBlocked):
        factory.make_runtime("live", ["mistral"], "nomic-embed-text", 30.0)


def test_fake_runtime_builds_with_no_real_client():
    adapters, embedder = factory.make_runtime("fake", ["anthropic"], "nomic-embed-text", 30.0)
    assert adapters and embedder is not None


def test_mistral_client_gets_key_timeout_and_no_retries(monkeypatch):
    monkeypatch.delenv("AI_ISLAND_OFFLINE")
    monkeypatch.setenv("MISTRAL_API_KEY", "not-a-real-key-for-tests")
    fake_dotenv = types.ModuleType("dotenv")
    fake_dotenv.load_dotenv = lambda *a, **k: False  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "dotenv", fake_dotenv)
    import mistralai.client as mclient

    ctor = mock.MagicMock()
    monkeypatch.setattr(mclient, "Mistral", ctor)
    factory.make_adapter("mistral", 45.0)
    assert ctor.call_count == 1
    kwargs = ctor.call_args.kwargs
    assert kwargs.get("api_key") == "not-a-real-key-for-tests"
    assert kwargs.get("timeout_ms") == 45000
    retry = kwargs.get("retry_config")
    assert retry is not None, "SDK retries must be configured off, not left at the default"
    flags = [v for k, v in vars(retry).items() if "connection" in k]
    assert all(f is False for f in flags)


def _request(layers: PromptLayers, max_out: int = 8192, role="player_1_main") -> LLMRequest:
    return LLMRequest(
        key="1/player_1/main/0", tick=1, player_id="player_1", role=role, purpose="main",
        layers=layers, schema=FastReply, max_output_tokens=max_out,
    )  # fmt: skip


def test_AC4_reservation_bound_is_bytes_plus_schema_plus_framing():
    role = CFG.models.roles["player_1_main"]
    prices = role.prices.model_copy(
        update={"input": 2.0, "cache_write": 2.5, "cache_read": 0.2, "output": 10.0}
    )
    role = role.model_copy(update={"prices": prices})
    # multi-byte characters: a character count would underestimate
    layers = PromptLayers(fixed="é" * 1000, slow="x" * 500, current="日" * 100)
    layer_bytes = 2000 + 500 + 300
    schema_bytes = len(json.dumps(provider_schema(FastReply, role.provider)).encode("utf-8"))
    head = len(b"Reply with only one JSON object, no other text, matching this JSON schema:\n")
    assert role.output_mode == "prompt"  # Round 3: the instruction head is counted too
    expected = ((layer_bytes + schema_bytes + head + 256) * 2.5 + 8192 * 10.0) / 1e6
    got = upper_bound_usd(_request(layers), role, 256)
    assert got == pytest.approx(expected, rel=1e-9)
    bigger = upper_bound_usd(_request(layers), role, 356)
    assert bigger == pytest.approx(expected + 100 * 2.5 / 1e6, rel=1e-9)


def test_AC4_ledger_refuses_a_call_that_could_pass_the_cap_and_allows_equal():
    led = SpendLedger(0.10, 0.8, total_usd=0.07)
    assert led.reserve("a", 0.02)
    assert not led.reserve("b", 0.02)  # 0.07 + 0.02 + 0.02 > 0.10
    assert led.reserve("b", 0.01)  # equal to the cap is allowed
    assert not led.reserve("c", 0.0001)


def test_AC4_record_attempt_writes_the_call_and_its_spend_together():
    db = RunDB.memory()
    row = AiCallRow(
        tick=5, player_id="player_1", role="player_1_main", provider="fake", model_version="m",
        prompt={"fixed": "a"}, reply_text="{}", thinking_tokens=None, input_tokens=10,
        output_tokens=5, cache_read_tokens=0, cache_write_tokens=0, cost_usd=0.25,
        duration_ms=1.0, status="ok", details={},
    )  # fmt: skip
    call_id = db.record_attempt(row, 0.25)
    assert isinstance(call_id, int)
    assert db.spend_total() == pytest.approx(0.25)
    db.close()


def test_AC4_reconcile_spend_adds_missing_spend_rows_once(tmp_path):
    db = RunDB.create(tmp_path / "r.db")
    db.close()
    con = sqlite3.connect(tmp_path / "r.db")
    con.execute(
        "INSERT INTO ai_calls (tick, player_id, role, provider, model_version, prompt_json, "
        "input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, cache_hit, cost_usd, "
        "duration_ms, status) VALUES (3, NULL, 'judge', 'mistral', 'm', '{}', 1, 1, 0, 0, 0, "
        "0.5, 1.0, 'ok')"
    )
    con.commit()
    con.close()
    db = RunDB.open(tmp_path / "r.db")
    assert db.spend_total() == 0.0
    assert db.reconcile_spend() == 1
    assert db.spend_total() == pytest.approx(0.5)
    assert db.reconcile_spend() == 0  # idempotent
    assert db.spend_total() == pytest.approx(0.5)
    db.close()


def test_AC4_live_backend_never_falls_back_to_the_fake_adapter():
    ai = CFG.run.ai.model_copy(update={"backend": "live"})

    def pipeline():
        yield _request(PromptLayers(fixed="f", slow="", current="c"))

    broker = CallBroker(
        None, CFG.models, ai, {"fake": FakeAdapter()}, SpendLedger(10.0, 0.8),
        sleep=lambda _s: None,
    )  # fmt: skip
    with pytest.raises(KeyError):
        broker.run({"a": pipeline()})
