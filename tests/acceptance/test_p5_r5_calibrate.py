"""Phase 5 Round 5: value lists cut to their limit, prompt wording, zero-thinking search."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_island.config import load_config
from ai_island.measure.calibrate import DryRunAdapter, run_calibration
from ai_island.measure.judge_schemas import FullJudgeLabel, ShortJudgeLabel
from ai_island.minds.prompts import format_text
from ai_island.minds.schemas import FastReply, SlowReply

ROOT = Path(__file__).resolve().parents[2]
CFG = load_config(ROOT / "config")
IDS = ["v1", "v2", "v3", "v4", "v5", "v6"]


def _slow(serves, violates, served, n_options=2):
    action = {"kind": "rest"}
    opt = {
        "action": action, "serves": serves, "violates": violates, "feel_now": 0,
        "feel_later": 0, "relationships": "r", "villagers": "v", "uncertainty": "low",
    }  # fmt: skip
    return {
        "thought": "t", "options": [opt] * n_options, "choice_index": 0, "trade_off": "x",
        "self_label": {"served": served, "violated": [], "direction": "toward"},
    }  # fmt: skip


def test_AC_R5_slow_reply_value_lists_cut_to_first_four_in_order():
    r = SlowReply.model_validate(_slow(IDS, IDS[::-1], IDS[:5]))
    for o in r.options:
        assert o.serves == IDS[:4]
        assert o.violates == IDS[::-1][:4]
    assert r.self_label.served == IDS[:4]


def test_AC_R5_self_label_violated_cut_in_fast_reply():
    data = {
        "thought": "t", "action": {"kind": "rest"}, "expected_feel": 0,
        "needs_more_thought": False,
        "self_label": {"served": IDS, "violated": IDS, "direction": "toward"},
    }  # fmt: skip
    r = FastReply.model_validate(data)
    assert r.self_label.served == IDS[:4] and r.self_label.violated == IDS[:4]


def test_AC_R5_four_values_are_untouched():
    r = SlowReply.model_validate(_slow(IDS[:4], [], IDS[:3]))
    assert r.options[0].serves == IDS[:4]


def test_AC_R5_five_options_still_fails():
    with pytest.raises(ValidationError):
        SlowReply.model_validate(_slow([], [], [], n_options=5))


def test_AC_R5_full_judge_label_cut_to_four():
    r = FullJudgeLabel.model_validate(
        {
            "served": IDS, "violated": IDS[::-1], "direction": "toward", "harm": False,
            "promise": "none", "betrayal": False, "superstition": False, "new_belief": "",
            "rationale": "because", "evidence": ["e"],
        }
    )  # fmt: skip
    assert r.served == IDS[:4] and r.violated == IDS[::-1][:4]


def test_AC_R5_short_judge_label_cut_to_two():
    r = ShortJudgeLabel.model_validate({"served": IDS, "violated": IDS, "direction": "toward"})
    assert r.served == IDS[:2] and r.violated == IDS[:2]


def test_AC_R5_prompt_states_at_most_4():
    assert "at most 4" in format_text("player")


# ------------------------------------------------------------------ calibrate search

FIXED = {
    "player_2_main": 100,
    "player_3_main": 110,
    "player_4_main": 105,
}


class Scripted(DryRunAdapter):
    """Thinking counts scripted per role and ladder setting: table[role] is a callable/None."""

    def __init__(self, config, table):
        super().__init__(config)
        self.table = table

    def generate(self, request, role):
        reply = super().generate(request, role)
        if not request.role.endswith("_main") or request.role not in self.table:
            return reply
        ladder = CFG.models.calibration.ladders[role.provider]
        level = role.thinking.get(ladder.key, "medium")
        value = self.table[request.role](level)
        usage = dataclasses.replace(reply.usage, thinking_tokens=value)
        return dataclasses.replace(reply, usage=usage)


def _table(p1):
    t = {r: (lambda lvl, v=v: v) for r, v in FIXED.items()}
    t["player_1_main"] = p1
    return t


def _run(tmp_path, p1):
    adapter = Scripted(CFG, _table(p1))
    return run_calibration(CFG, {"fake": adapter}, 50.0, tmp_path, dry_run=True)


def test_AC_R5_zero_main_is_moved_up_its_ladder_first(tmp_path):
    report = _run(tmp_path, lambda lvl: 0 if lvl in ("low", "medium") else 105)
    rounds = " ".join(r["text"] for r in report.rounds)
    assert "player_1_main -> high" in rounds
    assert not any("did not think even" in w for w in report.warnings), report.warnings
    assert report.matched


def test_AC_R5_zero_at_top_warns_by_name_and_matches_the_others(tmp_path):
    report = _run(tmp_path, lambda lvl: 0)
    # Round 7: Anthropic has no `force` table by default; the ladder runs up to "max"
    name = CFG.models.roles["player_1_main"].model
    expected = f"{name} did not think even at its highest setting; its thinking is not matched."
    assert expected in report.warnings, report.warnings
    assert report.matched
    assert report.median_ratio == pytest.approx(110 / 100)
    texts = " ".join(r["text"] for r in report.rounds)
    assert "player_1_main -> high" in texts
    assert "player_1_main -> xhigh" in texts
    assert "player_1_main -> max" in texts
    assert texts.index("-> high") < texts.index("-> xhigh") < texts.index("-> max")


def test_AC_R7_zero_main_climbs_high_xhigh_max_and_stops_when_it_thinks(tmp_path):
    report = _run(tmp_path, lambda lvl: 105 if lvl == "xhigh" else 0)
    texts = " ".join(r["text"] for r in report.rounds)
    assert "player_1_main -> xhigh" in texts
    assert "player_1_main -> max" not in texts
    assert not any("did not think even" in w for w in report.warnings), report.warnings
    assert report.matched
    assert report.settings["player_1_main"].get("effort") == "xhigh"


def test_AC_R5_zero_at_top_without_force_keeps_the_highest_setting_wording(tmp_path):
    import shutil

    from ai_island.config import load_config as load

    dst = tmp_path / "config"
    shutil.copytree(ROOT / "config", dst)
    path = dst / "models.toml"
    text = path.read_text(encoding="utf-8-sig")
    lines = [ln for ln in text.splitlines() if not ln.startswith("force = ")]
    path.write_bytes(b"\xef\xbb\xbf" + "\n".join(lines).encode("utf-8"))
    cfg = load(dst)
    assert cfg.models.calibration.ladders["anthropic"].force is None
    adapter = Scripted(cfg, _table(lambda lvl: 0))
    report = run_calibration(cfg, {"fake": adapter}, 50.0, tmp_path / "out", dry_run=True)
    name = cfg.models.roles["player_1_main"].model
    expected = f"{name} did not think even at its highest setting; its thinking is not matched."
    assert expected in report.warnings, report.warnings
    assert report.matched


def test_AC_R5_zero_at_top_others_too_far_apart_not_matched(tmp_path):
    adapter = Scripted(CFG, {**_table(lambda lvl: 0), "player_3_main": lambda lvl: 300})
    report = run_calibration(CFG, {"fake": adapter}, 50.0, tmp_path, dry_run=True)
    assert not report.matched


def test_AC_R5_all_mains_zero_keeps_the_old_stop_warning(tmp_path):
    table = {r: (lambda lvl: 0) for r in [*FIXED, "player_1_main"]}
    report = run_calibration(CFG, {"fake": Scripted(CFG, table)}, 50.0, tmp_path, dry_run=True)
    assert any("cannot be matched" in w for w in report.warnings), report.warnings
    assert not report.matched


def test_AC_R5_missing_count_keeps_the_old_stop_warning(tmp_path):
    report = _run(tmp_path, lambda lvl: None)
    assert (
        "A main model reported no thinking tokens, so the effort cannot be matched."
        in report.warnings
    )
    assert not report.matched
