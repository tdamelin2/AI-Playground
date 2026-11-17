"""Phase 5 Round 3 tests: output_mode switch, prompt mode, JSON extraction, Google guard,
reservation bound and the calibrate Form check.

Written from the Contract change (2026-11-04 20:43) and the Plan note (2026-11-04 20:51).
Offline only: mocked SDK clients and fakes.
"""

from __future__ import annotations

import json
import shutil
from decimal import Decimal
from pathlib import Path

import pytest

from ai_island import cli
from ai_island.config import load_config
from ai_island.llm.adapters import (
    AnthropicAdapter,
    GoogleAdapter,
    MistralAdapter,
    OpenAIAdapter,
)
from ai_island.llm.broker import CallBroker
from ai_island.llm.errors import NetworkError, ProviderRequestError
from ai_island.llm.fake import FakeAdapter
from ai_island.llm.ledger import SpendLedger
from ai_island.llm.prices import upper_bound_usd
from ai_island.llm.schema_transform import from_wire, provider_schema
from ai_island.llm.types import LLMRequest, PromptLayers
from ai_island.measure.calibrate import DryRunAdapter, run_calibration
from ai_island.minds.schemas import FastReply, SlowReply

ROOT = Path(__file__).resolve().parents[2]
CFG = load_config(ROOT / "config")
ROLES = CFG.models.roles
HEAD = "Reply with only one JSON object, no other text, matching this JSON schema:"

PROVIDER_ROLE = {
    "anthropic": "player_1_main",
    "openai": "player_2_main",
    "google": "player_3_main",
    "xai": "player_4_main",
    "mistral": "judge",
}


class Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _role(provider, mode):
    return ROLES[PROVIDER_ROLE[provider]].model_copy(update={"output_mode": mode})


def _adapter(provider):
    client = Obj()
    if provider == "anthropic":
        return AnthropicAdapter(client)
    if provider in ("openai", "xai"):
        return OpenAIAdapter(client, provider)
    if provider == "google":
        return GoogleAdapter(client)
    return MistralAdapter(client)


def _request(schema=SlowReply, role="player_1_main", purpose="slow"):
    return LLMRequest(
        key=f"100/player_1/{purpose}/0", tick=100, player_id="player_1", role=role,
        purpose=purpose, layers=PromptLayers("FIXED " * 20, "SLOW " * 10, "CURRENT"),
        schema=schema, max_output_tokens=500, meta={"family": purpose},
    )  # fmt: skip


def _texts(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _texts(v)
    elif isinstance(node, (list, tuple)):
        for v in node:
            yield from _texts(v)


def _has_key(node, name):
    if isinstance(node, dict):
        return name in node or any(_has_key(v, name) for v in node.values())
    if isinstance(node, (list, tuple)):
        return any(_has_key(v, name) for v in node)
    return False


def _nodes(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _nodes(v)
    elif isinstance(node, list):
        for v in node:
            yield from _nodes(v)


# ------------------------------------------------------------------------- output_mode config


def test_R3_defaults_anthropic_prompt_others_schema():
    for name, role in ROLES.items():
        expected = "prompt" if role.provider == "anthropic" else "schema"
        assert role.output_mode == expected, name


def _config_with(tmp_path, edit):
    dst = tmp_path / "config"
    shutil.copytree(ROOT / "config", dst)
    path = dst / "models.toml"
    text = path.read_text(encoding="utf-8-sig")
    new = edit(text)
    assert new != text
    path.write_bytes(b"\xef\xbb\xbf" + new.encode("utf-8"))
    return load_config(dst)


def test_R3_llm_output_mode_table_entry_switches_a_provider(tmp_path):
    cfg = _config_with(tmp_path, lambda t: t.replace('google = "schema"', 'google = "prompt"'))
    assert cfg.models.roles["player_3_main"].output_mode == "prompt"
    assert cfg.models.roles["player_3_helper"].output_mode == "prompt"
    assert cfg.models.roles["player_2_main"].output_mode == "schema"
    cfg2 = _config_with(
        tmp_path / "b", lambda t: t.replace('anthropic = "prompt"', 'anthropic = "schema"')
    )
    assert cfg2.models.roles["player_1_main"].output_mode == "schema"


def test_R3_explicit_schema_role_keeps_it_when_table_says_prompt(tmp_path):
    def edit(t):
        t = t.replace('google = "schema"', 'google = "prompt"')
        i = t.index("[roles.player_3_helper]")
        j = t.index("\n", t.index("model =", i))
        return t[:j] + '\noutput_mode = "schema"' + t[j:]

    cfg = _config_with(tmp_path, edit)
    assert cfg.models.roles["player_3_helper"].output_mode == "schema"
    assert cfg.models.roles["player_3_main"].output_mode == "prompt"


def test_R3_per_role_value_overrides_the_table(tmp_path):
    cfg = _config_with(
        tmp_path,
        lambda t: t.replace('model = "gpt-6-luna"', 'model = "gpt-6-luna"\noutput_mode = "prompt"'),
    )
    assert cfg.models.roles["player_2_helper"].output_mode == "prompt"
    assert cfg.models.roles["player_2_main"].output_mode == "schema"


# ------------------------------------------------------------------------------ prompt mode


@pytest.mark.parametrize("provider", list(PROVIDER_ROLE))
def test_R3_prompt_mode_has_no_structured_output_parameter_and_has_the_instruction(provider):
    kw = _adapter(provider).build_kwargs(_request(), _role(provider, "prompt"))
    assert not _has_key(kw, "json_schema")
    assert not _has_key(kw, "response_format")
    assert not _has_key(kw, "response_schema")
    assert not _has_key(kw, "response_mime_type")
    assert "text" not in kw  # OpenAI/xAI text.format
    blob = "\n".join(_texts(kw))
    assert HEAD in blob
    assert json.dumps(provider_schema(SlowReply, provider)) in blob
    assert "SLOW SLOW" in blob and "CURRENT" in blob  # the prompt layers are still all there


def test_R3_anthropic_prompt_mode_blocks_and_output_config():
    role = _role("anthropic", "prompt")
    kw = AnthropicAdapter(Obj()).build_kwargs(_request(), role)
    system = kw["system"]
    assert len(system) == 3
    assert system[0]["text"] == _request().layers.fixed
    assert system[1]["text"] == _request().layers.slow
    assert system[2]["text"].startswith(HEAD)
    assert all(b["cache_control"] == {"type": "ephemeral"} for b in system)
    # the cached fixed prefix is the same as in schema mode
    schema_kw = AnthropicAdapter(Obj()).build_kwargs(_request(), _role("anthropic", "schema"))
    assert schema_kw["system"][0] == system[0] and schema_kw["system"][1] == system[1]
    # effort kept, no format
    if "effort" in role.thinking:
        assert kw["output_config"] == {"effort": role.thinking["effort"]}
    else:
        assert "output_config" not in kw


def test_R3_anthropic_output_config_absent_when_empty():
    role = _role("anthropic", "prompt").model_copy(update={"thinking": {}})
    kw = AnthropicAdapter(Obj()).build_kwargs(_request(), role)
    assert "output_config" not in kw


def test_R3_anthropic_output_config_keeps_effort_without_format():
    role = _role("anthropic", "prompt").model_copy(update={"thinking": {"effort": "low"}})
    kw = AnthropicAdapter(Obj()).build_kwargs(_request(), role)
    assert kw["output_config"] == {"effort": "low"}


def test_R3_anthropic_without_slow_layer_still_gets_instruction_last():
    req = LLMRequest(
        key="k", tick=1, player_id="player_1", role="player_1_main", purpose="fast",
        layers=PromptLayers("F", "", "C"), schema=FastReply, max_output_tokens=100, meta={},
    )  # fmt: skip
    kw = AnthropicAdapter(Obj()).build_kwargs(req, _role("anthropic", "prompt"))
    assert kw["system"][0]["text"] == "F"
    assert kw["system"][-1]["text"].startswith(HEAD)


@pytest.mark.parametrize("provider", ["openai", "xai", "mistral"])
def test_R3_schema_mode_unchanged_for_openai_style_providers(provider):
    kw = _adapter(provider).build_kwargs(_request(), _role(provider, "schema"))
    blob = "\n".join(_texts(kw))
    assert HEAD not in blob
    expected = provider_schema(SlowReply, provider)
    if provider == "mistral":
        fmt = kw["response_format"]
        assert fmt["type"] == "json_schema" and fmt["json_schema"]["schema"] == expected
        assert fmt["json_schema"]["strict"] is True
    else:
        fmt = kw["text"]["format"]
        assert fmt["type"] == "json_schema" and fmt["schema"] == expected
        assert fmt["strict"] is True


def test_R3_schema_mode_unchanged_for_google_and_anthropic():
    kw = GoogleAdapter(Obj()).build_kwargs(_request(), _role("google", "schema"))
    assert "response_format" in kw
    assert HEAD not in "\n".join(_texts({"s": kw["system_instruction"]}))
    akw = AnthropicAdapter(Obj()).build_kwargs(_request(), _role("anthropic", "schema"))
    assert akw["output_config"]["format"]["type"] == "json_schema"
    assert akw["output_config"]["format"]["schema"] == provider_schema(SlowReply, "anthropic")
    assert len(akw["system"]) == 2


# -------------------------------------------------------------------------- JSON extraction


def _anthropic_with(text):
    resp = Obj(
        content=[Obj(type="text", text=text)],
        usage=Obj(input_tokens=1, output_tokens=1),
        model="m",
        stop_reason="end_turn",
    )
    return AnthropicAdapter(Obj(messages=Obj(create=lambda **kw: resp)))


PLAIN = '{"a": 1, "b": [1, 2]}'


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (PLAIN, PLAIN),
        ("  \n" + PLAIN + "\n ", PLAIN),
        ("```json\n" + PLAIN + "\n```", PLAIN),
        ("```\n" + PLAIN + "\n```", PLAIN),
        ("Here is my answer:\n" + PLAIN + "\nHope that helps!", PLAIN),
    ],
)
def test_R3_prompt_mode_extracts_the_json_object(text, expected):
    reply = _anthropic_with(text).generate(_request(), _role("anthropic", "prompt"))
    assert json.loads(reply.text) == json.loads(expected)


def test_R3_prompt_mode_text_without_json_is_returned_unchanged():
    text = "I cannot answer that."
    reply = _anthropic_with(text).generate(_request(), _role("anthropic", "prompt"))
    assert reply.text == text


def test_R3_schema_mode_does_not_touch_the_reply_text():
    text = "```json\n" + PLAIN + "\n```"
    reply = _anthropic_with(text).generate(_request(), _role("anthropic", "schema"))
    assert reply.text == text


def test_R3_extraction_works_for_openai_and_mistral_in_prompt_mode():
    fenced = "```json\n" + PLAIN + "\n```"
    resp = Obj(output_text=fenced, output=[], usage=Obj(input_tokens=1, output_tokens=1), model="m")
    oa = OpenAIAdapter(Obj(responses=Obj(create=lambda **kw: resp)), "openai")
    assert json.loads(oa.generate(_request(), _role("openai", "prompt")).text) == json.loads(PLAIN)
    mresp = Obj(
        choices=[Obj(message=Obj(content="prose " + PLAIN), finish_reason="stop")],
        usage=Obj(prompt_tokens=1, completion_tokens=1),
        model="m",
    )
    ma = MistralAdapter(Obj(chat=Obj(complete=lambda **kw: mresp)))
    assert json.loads(ma.generate(_request(), _role("mistral", "prompt")).text) == json.loads(PLAIN)


def _trade_slow_reply():
    action = {
        "kind": "trade", "target": "player_2",
        "offer": [{"key": "wood", "value": 3}], "want": [{"key": "stone", "value": 1}],
    }  # fmt: skip
    opt = {
        "action": action, "serves": [], "violates": [], "feel_now": 0, "feel_later": 0,
        "relationships": "r", "villagers": "v", "uncertainty": "low",
    }  # fmt: skip
    return {
        "thought": "t", "options": [opt, opt], "choice_index": 0, "trade_off": "x",
        "self_label": {"served": [], "violated": [], "direction": "toward"},
    }  # fmt: skip


def _one(request):
    return (yield request)


def _broker(adapter):
    ledger = SpendLedger(1000.0, 0.8)
    return CallBroker(None, CFG.models, CFG.run.ai, {"fake": adapter}, ledger, sleep=lambda s: None)


class CountingClient:
    def __init__(self, texts):
        self.texts = list(texts)
        self.calls = 0
        self.messages = Obj(create=self._create)

    def _create(self, **kw):
        self.calls += 1
        text = self.texts.pop(0) if self.texts else "no json"
        return Obj(
            content=[Obj(type="text", text=text)],
            usage=Obj(input_tokens=1, output_tokens=1),
            model="m",
            stop_reason="end_turn",
        )


def test_R3_fenced_anthropic_reply_with_trade_key_value_lists_validates_to_slowreply():
    text = "Sure:\n```json\n" + json.dumps(_trade_slow_reply()) + "\n```"
    client = CountingClient([text])
    res = _broker(AnthropicAdapter(client)).run({"p": _one(_request(role="player_1_helper"))})["p"]
    assert res.status == "ok", res
    assert isinstance(res.parsed, SlowReply)
    action = res.parsed.options[0].action
    assert action.kind == "trade" and action.offer == {"wood": 3} and action.want == {"stone": 1}


def test_R3_reply_with_no_json_is_a_format_error_after_one_retry():
    client = CountingClient(["not json at all", "still not json"])
    res = _broker(AnthropicAdapter(client)).run({"p": _one(_request(role="player_1_helper"))})["p"]
    assert res.status == "format_error"
    assert client.calls == 2


def test_R3_format_retry_can_recover():
    good = json.dumps(_trade_slow_reply())
    client = CountingClient(["nope", good])
    res = _broker(AnthropicAdapter(client)).run({"p": _one(_request(role="player_1_helper"))})["p"]
    assert res.status == "ok" and client.calls == 2


def test_R3_from_wire_accepts_the_prompt_text_form():
    got = SlowReply.model_validate(from_wire(_trade_slow_reply(), SlowReply))
    assert got.options[1].action.offer == {"wood": 3}


# ----------------------------------------------------------------------------- Google guard


def test_R3_google_schema_has_no_exclusive_bounds_or_multipleof_and_ints_use_minimum_1():
    for cls in (FastReply, SlowReply):
        schema = provider_schema(cls, "google")
        saw_minimum_1 = False
        for node in _nodes(schema):
            for banned in ("exclusiveMinimum", "exclusiveMaximum", "multipleOf"):
                assert banned not in node, (cls.__name__, banned, node)
            if node.get("type") == "integer" and node.get("minimum") == 1:
                saw_minimum_1 = True
        assert saw_minimum_1, cls.__name__


def test_R3_google_guard_keeps_other_bounds_and_leaves_other_providers_bound_free():
    google = json.dumps(provider_schema(SlowReply, "google"))
    assert '"minimum"' in google and '"maximum"' in google
    for provider in ("openai", "xai", "mistral", "anthropic"):
        dump = json.dumps(provider_schema(SlowReply, provider))
        assert "exclusiveMinimum" not in dump and "minimum" not in dump


def test_R3_local_validation_still_rejects_a_zero_amount():
    reply = _trade_slow_reply()
    reply["options"][0]["action"]["amount"] = 0
    with pytest.raises(ValueError):
        SlowReply.model_validate(from_wire(reply, SlowReply))


# -------------------------------------------------------------------- reservation bound


def _wire_bytes(kw):
    return sum(len(t.encode("utf-8")) for t in _texts(kw))


@pytest.mark.parametrize("provider", list(PROVIDER_ROLE))
@pytest.mark.parametrize("mode", ["prompt", "schema"])
def test_R3_upper_bound_covers_the_actual_request_in_both_modes(provider, mode):
    role = _role(provider, mode)
    request = _request(role=PROVIDER_ROLE[provider])
    kw = _adapter(provider).build_kwargs(request, role)
    p = role.prices
    rate = max(Decimal(str(p.input)), Decimal(str(p.cache_write)))
    actual_floor = float(
        (
            Decimal(_wire_bytes(kw) // 4) * rate
            + Decimal(request.max_output_tokens) * Decimal(str(p.output))
        )
        / Decimal(1_000_000)
    )  # even at one token per four bytes
    bound = upper_bound_usd(request, role)
    assert bound >= actual_floor
    # a token is at least one byte: the bound must cover all text bytes at one token per byte
    all_bytes = float(
        (
            Decimal(_wire_bytes(kw)) * rate
            + Decimal(request.max_output_tokens) * Decimal(str(p.output))
        )
        / Decimal(1_000_000)
    )
    if provider in ("anthropic", "openai", "xai", "mistral"):
        assert bound >= all_bytes - 1e-12


def test_R3_prompt_mode_bound_is_not_below_schema_mode_bound():
    request = _request()
    assert upper_bound_usd(request, _role("anthropic", "prompt")) > upper_bound_usd(
        request, _role("anthropic", "schema")
    )


# ------------------------------------------------------------------- calibrate Form check


class RefuseProviders(DryRunAdapter):
    def __init__(self, config, providers, message="schema is far too complex"):
        super().__init__(config)
        self.providers = set(providers)
        self.message = message
        self.sent: list[tuple[str, str]] = []

    def generate(self, request, role):
        self.sent.append((request.key, role.provider))
        if role.provider in self.providers:
            raise ProviderRequestError(role.provider, 400, self.message, "req_x")
        return super().generate(request, role)


def test_R3_form_check_dry_run_reports_all_models_accepted(tmp_path):
    report = run_calibration(CFG, None, 5.0, tmp_path, dry_run=True)
    assert not report.stopped
    text = (tmp_path / "report.md").read_text(encoding="utf-8")
    distinct = {(r.provider, r.model) for r in ROLES.values()}
    assert f"Form check: all {len(distinct)} models accepted" in text


def test_R3_form_check_lists_every_refused_company_at_once_and_measures_nothing(tmp_path):
    adapter = RefuseProviders(CFG, ["google", "xai"])
    report = run_calibration(CFG, {"fake": adapter}, 5.0, tmp_path, dry_run=True)
    assert report.stopped and not report.complete
    assert report.stop_reason == "provider_error"
    text = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "Form check" in text
    for role in ROLES.values():
        if role.provider in ("google", "xai"):
            assert role.model in text, role.model
    assert text.count("schema is far too complex") >= 4
    assert "[llm.output_mode]" in text
    assert 'google = "prompt"' in text and 'xai = "prompt"' in text
    assert 'openai = "prompt"' not in text and 'anthropic = "prompt"' not in text
    # only form-check requests were sent; nothing from the measuring part
    assert adapter.sent
    assert all(key.startswith("cal/form/") for key, _ in adapter.sent), adapter.sent
    # the accepted companies were still checked (the check continues past a refusal)
    assert {p for _, p in adapter.sent} == {"anthropic", "openai", "google", "xai", "mistral"}


def test_R3_form_check_one_request_per_distinct_model(tmp_path):
    adapter = RefuseProviders(CFG, [])
    run_calibration(CFG, {"fake": adapter}, 5.0, tmp_path, dry_run=True)
    form = [k for k, _ in adapter.sent if k.startswith("cal/form/")]
    distinct = {(r.provider, r.model) for r in ROLES.values()}
    assert len(form) == len(set(form)) == len(distinct)
    assert adapter.sent[: len(form)] == [(k, p) for k, p in adapter.sent[: len(form)]]
    # the form requests come first: every later request is a measuring sample
    assert all(k.startswith("cal/form/") for k, _ in adapter.sent[: len(form)])


def test_R3_form_check_refusal_result_json_names_the_models(tmp_path):
    adapter = RefuseProviders(CFG, ["anthropic"])
    run_calibration(CFG, {"fake": adapter}, 5.0, tmp_path, dry_run=True)
    data = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert data["stop_reason"] == "provider_error"
    assert "claude-sonnet-5-5" in json.dumps(data) and "claude-haiku-5-5" in json.dumps(data)


def test_R3_form_check_network_pause_stops_as_before(tmp_path):
    class Offline(DryRunAdapter):
        def generate(self, request, role):
            raise NetworkError("down")

    ai = CFG.run.ai.model_copy(update={"retry_wait_seconds": [0.0, 0.0, 0.0]})
    cfg = CFG.model_copy(update={"run": CFG.run.model_copy(update={"ai": ai})})
    report = run_calibration(cfg, {"fake": Offline(cfg)}, 5.0, tmp_path, dry_run=True)
    assert report.stopped and report.stop_reason == "network"
    assert not report.form_refused


def test_R3_cli_calibrate_refusals_exit_4_and_name_the_fix(monkeypatch, capsys):
    original = DryRunAdapter.generate

    def generate(self, request, role):
        if role.provider in ("google", "xai"):
            raise ProviderRequestError(role.provider, 400, "schema is far too complex", "req_x")
        return original(self, request, role)

    monkeypatch.setattr(DryRunAdapter, "generate", generate)
    code = cli.main(["calibrate", "--dry-run", "--max-dollars", "5"])
    out = capsys.readouterr()
    assert code == 4, out.out + out.err
    assert "Traceback" not in out.out + out.err
    assert "schema is far too complex" in out.out


def test_R3_cli_calibrate_dry_run_all_accepted_exits_0(capsys):
    code = cli.main(["calibrate", "--dry-run", "--max-dollars", "5"])
    out = capsys.readouterr()
    assert code == 0, out.out + out.err


def test_R3_fake_adapter_and_dryrun_adapter_still_importable():
    assert issubclass(DryRunAdapter, FakeAdapter)
