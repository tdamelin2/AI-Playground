"""Phase 5 Round 6: forced-thinking step, budget validation, overshoot, refusal.

Written from the Contract change (2026-11-04 22:54). Offline only.
"""

from __future__ import annotations

import dataclasses
import shutil
import tempfile
import tomllib
from pathlib import Path

import pytest

from ai_island.config import load_config
from ai_island.llm.adapters import AnthropicAdapter
from ai_island.llm.errors import ProviderRequestError
from ai_island.llm.types import LLMRequest, PromptLayers
from ai_island.measure.calibrate import DryRunAdapter, apply_calibration, run_calibration
from ai_island.minds.schemas import SlowReply

ROOT = Path(__file__).resolve().parents[2]
CFG = load_config(ROOT / "config")
FORCE = {"type": "enabled", "budget_tokens": 1024}
LABEL = "type=enabled, budget_tokens=1024"
FIXED = {"player_2_main": 100, "player_3_main": 110, "player_4_main": 105}


class Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _request():
    return LLMRequest(
        key="100/player_1/slow/0", tick=100, player_id="player_1", role="player_1_main",
        purpose="slow", layers=PromptLayers("FIXED " * 20, "SLOW " * 10, "CURRENT"),
        schema=SlowReply, max_output_tokens=4000, meta={"family": "slow"},
    )  # fmt: skip


def _cfg_edit(tmp_path, edit):
    dst = tmp_path / "config"
    shutil.copytree(ROOT / "config", dst)
    path = dst / "models.toml"
    text = path.read_text(encoding="utf-8-sig")
    new = edit(text)
    assert new != text
    path.write_bytes(b"\xef\xbb\xbf" + new.encode("utf-8"))
    return dst


STEPS_LINE = 'steps = ["low", "medium", "high", "xhigh", "max"]'


def _forced_config(budget=1024, dest=None):
    """Default config plus an explicit anthropic force table (Round 7 removed it by default)."""
    dst = Path(dest or tempfile.mkdtemp(prefix="p5r6cfg_")) / "config"
    shutil.copytree(ROOT / "config", dst)
    path = dst / "models.toml"
    text = path.read_text(encoding="utf-8-sig")
    assert STEPS_LINE in text
    line = f'force = {{ type = "enabled", budget_tokens = {budget} }}'
    text = text.replace(STEPS_LINE, STEPS_LINE + "\n" + line, 1)
    path.write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))
    return dst


CFGF = load_config(_forced_config())


# ------------------------------------------------------------------ config


def test_R7_config_new_defaults():
    cal = CFG.models.calibration
    assert cal.ladders["anthropic"].steps == ["low", "medium", "high", "xhigh", "max"]
    assert cal.ladders["anthropic"].force is None
    assert cal.ladders["openai"].steps == ["low", "medium", "high", "xhigh"]
    assert cal.ladders["google"].steps == ["low", "medium", "high"]
    assert cal.max_rounds == 6
    for p in ("openai", "google", "xai"):
        assert cal.ladders[p].force is None


def test_R6_config_force_table_loads_when_set():
    cal = CFGF.models.calibration
    assert cal.ladders["anthropic"].force == FORCE
    assert cal.max_rounds == 6


@pytest.mark.parametrize("budget", [512, 1023, 2048, 9000])
def test_R6_config_bad_budget_fails_loading(tmp_path, budget):
    dst = _forced_config(budget, tmp_path)
    with pytest.raises(Exception, match="(?i)budget"):
        load_config(dst)


def test_R6_config_role_thinking_with_bad_budget_fails(tmp_path):
    import re

    dst = _cfg_edit(
        tmp_path,
        lambda t: re.sub(
            r"(\[roles\.player_1_main\][^\[]*?\n)thinking = \{[^}]*\}",
            r'\1thinking = { type = "enabled", budget_tokens = 100 }',
            t,
            count=1,
        ),
    )
    with pytest.raises(Exception, match="(?i)budget"):
        load_config(dst)


def test_R8_default_main_thinking_settings_and_claude_request():
    roles = CFG.models.roles
    assert dict(roles["player_1_main"].thinking) == {"type": "adaptive", "effort": "xhigh"}
    assert dict(roles["player_2_main"].thinking) == {"effort": "xhigh"}
    assert dict(roles["player_3_main"].thinking) == {"thinking_level": "medium"}
    assert dict(roles["player_4_main"].thinking) == {"effort": "medium"}
    kw = AnthropicAdapter(Obj()).build_kwargs(_request(), roles["player_1_main"])
    assert kw["output_config"]["effort"] == "xhigh"
    assert kw["thinking"]["type"] == "adaptive"


def test_R6_config_valid_budget_loads(tmp_path):
    dst = _forced_config(1500, tmp_path)
    assert load_config(dst).models.calibration.ladders["anthropic"].force["budget_tokens"] == 1500


# ------------------------------------------------------------------ adapter


def _role(thinking):
    return CFG.models.roles["player_1_main"].model_copy(update={"thinking": thinking})


def test_R6_adapter_enabled_sends_type_and_budget_and_no_effort():
    kw = AnthropicAdapter(Obj()).build_kwargs(_request(), _role(dict(FORCE)))
    assert kw["thinking"]["type"] == "enabled"
    assert kw["thinking"]["budget_tokens"] == 1024
    assert "effort" not in (kw.get("output_config") or {})
    assert kw["max_tokens"] > 1024


def test_R6_adapter_enabled_with_effort_key_sends_effort():
    kw = AnthropicAdapter(Obj()).build_kwargs(_request(), _role({**FORCE, "effort": "low"}))
    assert kw["thinking"]["type"] == "enabled"
    assert kw["output_config"]["effort"] == "low"


def test_R6_adapter_adaptive_with_effort_unchanged():
    kw = AnthropicAdapter(Obj()).build_kwargs(
        _request(), _role({"type": "adaptive", "effort": "high"})
    )
    assert kw["thinking"]["type"] == "adaptive"
    assert "budget_tokens" not in kw["thinking"]
    assert kw["output_config"]["effort"] == "high"


# ------------------------------------------------------------------ search


class Scripted(DryRunAdapter):
    """Thinking counts per main role: table[role](level) -> int; level is 'force' when forced."""

    def __init__(self, config, table, refuse_force=False):
        super().__init__(config)
        self.table = table
        self.refuse_force = refuse_force
        self.forced_calls = 0

    def generate(self, request, role):
        forced = role.thinking.get("type") == "enabled"
        if forced and request.role == "player_1_main":
            self.forced_calls += 1
            if self.refuse_force:
                raise ProviderRequestError(role.provider, 400, "thinking enabled not allowed", "r")
        reply = super().generate(request, role)
        if not request.role.endswith("_main") or request.role not in self.table:
            return reply
        ladder = CFG.models.calibration.ladders[role.provider]
        level = "force" if forced else role.thinking.get(ladder.key, "medium")
        usage = dataclasses.replace(reply.usage, thinking_tokens=self.table[request.role](level))
        return dataclasses.replace(reply, usage=usage)


def _table(p1):
    t = {r: (lambda lvl, v=v: v) for r, v in FIXED.items()}
    t["player_1_main"] = p1
    return t


def _texts(report):
    return " | ".join(r["text"] for r in report.rounds)


def _force_zero_then(value):
    return lambda lvl: value if lvl == "force" else 0


def test_R6_force_round_nonzero_is_matched_with_the_force_table(tmp_path):
    adapter = Scripted(CFGF, _table(_force_zero_then(105)))
    report = run_calibration(CFGF, {"fake": adapter}, 50.0, tmp_path, dry_run=True)
    assert adapter.forced_calls > 0
    assert LABEL in _texts(report)
    assert not any("did not think" in w or "refused" in w for w in report.warnings), report.warnings
    assert report.matched
    assert report.settings["player_1_main"] == FORCE
    assert "effort" not in report.settings["player_1_main"]


def test_R6_force_round_only_once_when_still_zero_warns_and_matches_others(tmp_path):
    adapter = Scripted(CFGF, _table(lambda lvl: 0))
    report = run_calibration(CFGF, {"fake": adapter}, 50.0, tmp_path, dry_run=True)
    name = CFGF.models.roles["player_1_main"].model
    assert f"{name} did not think even with thinking forced on; its thinking is not matched." in (
        report.warnings
    )
    assert report.matched
    assert _texts(report).count(LABEL) == 1


def test_R6_apply_writes_force_table_without_leftover_effort(tmp_path):
    adapter = Scripted(CFGF, _table(_force_zero_then(105)))
    out = tmp_path / "out"
    report = run_calibration(CFGF, {"fake": adapter}, 50.0, out, dry_run=True)
    assert report.matched
    # a dry run cannot be applied; make it a pretend finished real report
    real = dataclasses.replace(report, dry_run=False, complete=True, stopped=False)
    dst = tmp_path / "models.toml"
    shutil.copyfile(_forced_config(dest=tmp_path / "src") / "models.toml", dst)
    apply_calibration(dst, real)
    data = tomllib.loads(dst.read_text(encoding="utf-8-sig"))
    assert data["roles"]["player_1_main"]["thinking"] == FORCE
    assert data["calibration"]["measured"]["thinking"]["player_1_main"] == FORCE


def test_R6_force_refused_warns_plainly_and_calibrate_finishes(tmp_path):
    adapter = Scripted(CFGF, _table(lambda lvl: 0), refuse_force=True)
    report = run_calibration(CFGF, {"fake": adapter}, 50.0, tmp_path, dry_run=True)
    assert adapter.forced_calls > 0
    assert any("anthropic refused forced thinking" in w for w in report.warnings), report.warnings
    assert report.complete and not report.stopped
    assert report.matched
    assert report.median_ratio == pytest.approx(110 / 100)


def test_R6_cli_style_dry_run_exits_zero(capsys):
    from ai_island import cli

    assert cli.main(["calibrate", "--dry-run", "--max-dollars", "5"]) == 0


def test_R6_down_move_to_zero_is_an_overshoot(tmp_path):
    # claude thinks a lot at medium (and high) but nothing at low; the others sit at ~100
    def p1(lvl):
        return 0 if lvl == "low" else 1000

    adapter = Scripted(CFG, _table(p1))
    report = run_calibration(CFG, {"fake": adapter}, 50.0, tmp_path, dry_run=True)
    name = CFG.models.roles["player_1_main"].model
    texts = _texts(report)
    assert "player_1_main -> low" in texts
    assert "unusable" in texts
    assert not any(name in w and "highest setting" in w for w in report.warnings), report.warnings
    # the model stays at a step that thinks, never the zero step
    assert report.settings["player_1_main"].get("effort") != "low"
    assert report.thinking_tokens_by_model[name] == 1000
