"""Phase 5 tool tests: AC-4 (limits), AC-5 (calibrate dry run), AC-6 (pilot) and AC-10 (launch).

Written from the Plan's acceptance criteria and Contract C4, C8, C9. Every AI command here is
fake or --dry-run; the offline switch is on, so a live path could not build a client anyway.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys

import pytest
from p4_helpers import CFG

from ai_island.config import ProfileConfig
from ai_island.measure.calibrate import (
    judge_week_cost,
    median_ratio,
    run_calibration,
    seat_week_cost,
)
from ai_island.measure.judge_check import run_judge_check
from ai_island.sim import apply_profile
from conftest import ROOT, RUNS

CAL = CFG.models.calibration


def run_cli(*args: str, timeout: int = 900):
    env = dict(os.environ, AI_ISLAND_OFFLINE="1", SDL_VIDEODRIVER="dummy")
    return subprocess.run(
        [sys.executable, "main.py", *args], cwd=ROOT, env=env, capture_output=True, text=True,
        input="", timeout=timeout,
    )  # fmt: skip


@pytest.fixture
def run_dir(request):
    name = "p5acc_" + request.node.name.replace("[", "_").replace("]", "")[:30]
    shutil.rmtree(RUNS / name, ignore_errors=True)
    yield name
    shutil.rmtree(RUNS / name, ignore_errors=True)


# ------------------------------------------------------------------------------- AC-4


@pytest.mark.parametrize("tool", ["judge-check", "calibrate"])
@pytest.mark.parametrize("extra", [[], ["--max-dollars", "0"], ["--max-dollars", "nan"]])
def test_AC4_tools_refuse_to_start_without_a_usable_limit(tool, extra):
    out = RUNS / ("judge-check" if tool == "judge-check" else "calibration") / "report.md"
    before = out.stat().st_mtime if out.exists() else None
    done = run_cli(tool, *extra)
    assert done.returncode == 2, done.stdout + done.stderr
    after = out.stat().st_mtime if out.exists() else None
    assert before == after, "a refused command must not write a report"
    assert "LIVE" not in done.stdout


@pytest.mark.parametrize("tool", ["judge-check", "calibrate"])
def test_AC4_a_tiny_limit_stops_before_any_call_that_could_pass_it(tool):
    done = run_cli(tool, "--dry-run", "--max-dollars", "0.0001")
    assert done.returncode == 4, done.stdout + done.stderr
    assert "Stopped: the next call could pass the $0.0001 limit." in done.stdout


def _assert_calls_stay_under(db_path, cap):
    con = sqlite3.connect(db_path)
    spent = con.execute("SELECT COALESCE(MAX(cumulative_usd), 0) FROM spend").fetchone()[0]
    total = con.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM ai_calls").fetchone()[0]
    con.close()
    assert spent <= cap + 1e-12 and total <= cap + 1e-12


@pytest.mark.parametrize("cap", [0.0005, 0.01, 0.05])
def test_AC4_calibration_never_spends_past_the_limit(tmp_path, cap):
    report = run_calibration(CFG, None, cap, tmp_path, dry_run=True)
    assert report.stopped and not report.complete
    assert report.spent_usd <= cap + 1e-12
    _assert_calls_stay_under(report.db_path, cap)
    assert (tmp_path / "report.md").exists()  # a partial report is still written


@pytest.mark.parametrize("cap", [0.0005, 0.0002])
def test_AC4_judge_check_never_spends_past_the_limit(tmp_path, cap):
    result = run_judge_check(CFG, None, cap, tmp_path, dry_run=True)
    assert result.stopped and not result.complete
    assert result.total_cost_usd <= cap + 1e-12
    _assert_calls_stay_under(result.db_path, cap)


# ------------------------------------------------------------------------------- AC-5


def test_AC5_calibrate_dry_run_writes_the_full_report():
    done = run_cli("calibrate", "--dry-run", "--max-dollars", "1")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "PRACTICE" in done.stdout
    text = (RUNS / "calibration" / "report.md").read_text(encoding="utf-8")
    assert "Practice estimate (pretend AI), not measured costs" in text
    low = text.lower()
    for phrase in (
        "version", "thinking", "cost per slow decision", "cost per hooked decision",
        "cost per game week", "per $100", "week 7", "cheap seat", "pilot",
    ):  # fmt: skip
        assert phrase in low, phrase
    data = json.loads((RUNS / "calibration" / "result.json").read_text(encoding="utf-8"))
    for key in (
        "versions", "settings", "thinking_tokens_by_model", "cost_per_slow_decision",
        "cost_per_hooked_decision", "cost_per_game_week", "weeks_per_100", "reaches_week_7",
        "cheap_seat_week_cost", "pilot_cost",
    ):  # fmt: skip
        assert key in data and data[key] is not None, key


@pytest.fixture(scope="module")
def dry_report(tmp_path_factory):
    return run_calibration(CFG, None, 1.0, tmp_path_factory.mktemp("cal"), dry_run=True)


def test_AC5_the_dry_run_finishes_and_matches_the_four_mains(dry_report):
    r = dry_report
    assert r.dry_run and r.complete and not r.stopped and r.matched
    assert r.spent_usd < 1.0
    tokens = [v for v in r.thinking_tokens_by_model.values() if v is not None]
    assert len(tokens) == 4 and all(t > 0 for t in tokens)
    assert max(tokens) / min(tokens) <= CAL.max_median_ratio
    assert len(r.versions) >= 4


def test_AC5_the_dry_run_numbers_agree_with_each_other(dry_report):
    r = dry_report
    assert r.cost_per_slow_decision > 0 and r.cost_per_hooked_decision > 0
    assert r.cost_per_game_week > 0
    assert r.weeks_per_100 == pytest.approx(100 / r.cost_per_game_week)
    assert r.reaches_week_7 == (CFG.run.spend_cap_usd >= 7 * r.cost_per_game_week)
    assert len(r.cheap_seat_week_costs) == 4
    assert r.cheap_seat_week_cost == pytest.approx(max(r.cheap_seat_week_costs.values()))
    expected_pilot = (
        CAL.pilot_weeks * sum(r.cheap_seat_week_costs.values()) * (1 + CAL.safety_share)
    )
    assert r.pilot_cost == pytest.approx(expected_pilot)


def test_AC5_cost_model_worked_example():
    assert seat_week_cost(0.03, 0.02, 0.001, 0.025, CAL) == pytest.approx(3.97)
    jl = 0.001
    assert judge_week_cost(jl, CAL) == pytest.approx((7 * 4 * 22 + 11 * 3) * jl)


def test_AC5_median_ratio_examples():
    assert median_ratio([1000, 1050, 1100, 1200]) == pytest.approx(1.2)
    assert median_ratio([1000, 1000, 1000, 1500]) == pytest.approx(1.5)
    assert median_ratio([1000, None, 1100, 1200]) is None
    assert median_ratio([1000, 0, 1100, 1200]) is None


def test_AC5_dry_run_and_apply_cannot_be_combined():
    done = run_cli("calibrate", "--dry-run", "--apply", "--max-dollars", "1")
    assert done.returncode == 2


# ------------------------------------------------------------------------------- AC-6 / AC-10


def test_AC6_pilot_pins_four_cheap_seats_and_a_three_week_end():
    ai = apply_profile(CFG, "pilot", 5.0, "fake")
    assert ai.run.ai.seats == [1, 2, 3, 4]
    assert ai.run.ai.cheap is True and ai.run.ai.backend == "fake"
    assert ai.run.ai.end_tick == 30240
    assert ai.run.spend_cap_usd == 5.0
    assert 2 <= CFG.run.profiles["pilot"].weeks <= 3


def test_AC6_pilot_length_is_two_or_three_weeks_only():
    ProfileConfig(seats=[1, 2, 3, 4], cheap=True, weeks=2)
    ProfileConfig(seats=[1, 2, 3, 4], cheap=True, weeks=3)
    for weeks in (1, 4):
        with pytest.raises(ValueError):
            ProfileConfig(seats=[1, 2, 3, 4], cheap=True, weeks=weeks)


def test_AC10_launch_profile_keeps_the_main_models_and_has_no_end():
    ai = apply_profile(CFG, "launch", 50.0, "fake")
    assert ai.run.ai.seats == [1, 2, 3, 4] and ai.run.ai.cheap is False
    assert ai.run.ai.end_tick is None
    assert ai.run.ai.new_ticks == CFG.run.ai.new_ticks


@pytest.mark.parametrize(
    "extra",
    [
        [],
        ["--max-dollars", "0"],
        ["--max-dollars", "-1"],
        ["--max-dollars", "nan"],
        ["--max-dollars", "inf"],
    ],
)
@pytest.mark.parametrize("profile", ["pilot", "launch"])
def test_AC6_a_profile_refuses_to_start_without_a_usable_limit(run_dir, profile, extra):
    done = run_cli("new", run_dir, "--profile", profile, "--backend", "fake", *extra)
    assert done.returncode == 2, done.stdout + done.stderr
    assert not (RUNS / run_dir).exists()


@pytest.mark.parametrize("clash", [["--ai-seats", "2"], ["--cheap"], ["--players", "dummy"]])
def test_AC6_a_profile_cannot_be_mixed_with_seat_flags(run_dir, clash):
    done = run_cli("new", run_dir, "--profile", "pilot", "--max-dollars", "5", *clash)
    assert done.returncode == 2
    assert not (RUNS / run_dir).exists()


def test_AC6_a_live_profile_asks_for_yes_and_declines_without_it(run_dir):
    done = run_cli("new", run_dir, "--profile", "pilot", "--max-dollars", "5")
    assert done.returncode == 2, done.stdout + done.stderr
    assert "LIVE: real AI, may spend up to $5" in done.stdout
    assert not (RUNS / run_dir).exists()


def _config_of(run: str) -> dict:
    con = sqlite3.connect(RUNS / run / "run.db")
    row = con.execute("SELECT config_json FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
    con.close()
    return json.loads(row[0])


def _roles_used(run: str) -> dict[str, set[str]]:
    con = sqlite3.connect(RUNS / run / "run.db")
    rows = con.execute(
        "SELECT DISTINCT role, json_extract(details_json, '$.model') FROM ai_calls"
    ).fetchall()
    con.close()
    out: dict[str, set[str]] = {}
    for role, ver in rows:
        out.setdefault(role, set()).add(ver)
    return out


def test_AC10_launch_profile_calls_the_four_main_models(run_dir):
    done = run_cli(
        "new", run_dir, "--profile", "launch", "--backend", "fake", "--max-dollars", "50",
        "--ticks", "2000",
    )  # fmt: skip
    assert done.returncode == 0, done.stdout + done.stderr
    ai = _config_of(run_dir)["run"]["ai"]
    assert ai["seats"] == [1, 2, 3, 4] and ai["cheap"] is False
    used = _roles_used(run_dir)
    mains = {r for r in used if r.endswith("_main")}
    assert mains == {f"player_{i}_main" for i in range(1, 5)}, used
    for i in range(1, 5):
        role = CFG.models.roles[f"player_{i}_main"]
        assert used[f"player_{i}_main"] == {role.model}


@pytest.mark.slow
def test_AC6_a_fake_pilot_run_completes_on_the_cheap_models(run_dir):
    done = run_cli("new", run_dir, "--profile", "pilot", "--backend", "fake", "--max-dollars", "5")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "This run has reached its planned end." in done.stdout
    ai = _config_of(run_dir)["run"]["ai"]
    assert ai["seats"] == [1, 2, 3, 4] and ai["cheap"] is True and ai["end_tick"] == 30240
    used = _roles_used(run_dir)
    assert not any(r.endswith("_main") for r in used), used  # cheap seats never use a main
    for i in range(1, 5):
        helper = CFG.models.roles[f"player_{i}_helper"]
        assert helper.model in used[f"player_{i}_helper"]
    con = sqlite3.connect(RUNS / run_dir / "run.db")
    last_tick = con.execute("SELECT MAX(tick) FROM events").fetchone()[0]
    calls = con.execute("SELECT COUNT(*) FROM ai_calls").fetchone()[0]
    con.close()
    assert last_tick <= 30240
    again = run_cli("resume", run_dir)
    assert again.returncode == 0
    assert "This run has reached its planned end." in again.stdout
    con = sqlite3.connect(RUNS / run_dir / "run.db")
    assert con.execute("SELECT COUNT(*) FROM ai_calls").fetchone()[0] == calls
    con.close()
