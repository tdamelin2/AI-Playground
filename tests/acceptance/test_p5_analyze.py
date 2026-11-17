"""Phase 5 AC-7, AC-8, AC-9 and the AC-11 recovery check (written from the Contract C9)."""

from __future__ import annotations

import csv
import json
import shutil
import sqlite3
import subprocess
from collections import Counter

import pytest
from p4_helpers import CFG, new_ai_sim
from test_p5_tools import run_cli

from ai_island.llm.fake import FakeAdapter
from ai_island.measure.analyze import AnalysisReport
from ai_island.measure.launch_check import launch_checks
from ai_island.measure.tuning import propose_tuning
from ai_island.storage.db import RunDB
from ai_island.storage.recovery import recover
from conftest import ROOT, RUNS

RUN = "p5acc_analyze"
TPD = 1440


@pytest.fixture(scope="module")
def analyzed():
    shutil.rmtree(RUNS / RUN, ignore_errors=True)
    made = run_cli("new", RUN, "--ai-seats", "2", "--backend", "fake", "--max-dollars", "5",
                   "--ticks", "8640", "--seed", "3")  # fmt: skip
    assert made.returncode == 0, made.stdout + made.stderr
    done = run_cli("analyze", "--run", RUN)
    assert done.returncode == 0, done.stdout + done.stderr
    yield RUNS / RUN, done
    shutil.rmtree(RUNS / RUN, ignore_errors=True)


def read_csv(path):
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


# ------------------------------------------------------------------------------- AC-7

CSVS = ["deaths", "x_over_time", "resources", "decisions_per_day", "failures", "cost_by_week",
        "tuning_proposals", "value_changes", "judge_summaries"]  # fmt: skip


def test_AC7_analyze_writes_the_report_and_every_csv(analyzed):
    run, _ = analyzed
    assert (run / "analysis.md").is_file()
    for name in CSVS:
        assert (run / "analysis" / f"{name}.csv").is_file(), name


def test_AC7_the_report_has_a_number_for_every_metric(analyzed):
    text = (analyzed[0] / "analysis.md").read_text(encoding="utf-8").lower()
    for word in ["death", "extinction", "food", "refus", "schema", "cost"]:
        assert word in text, word
    for trig in ["finished", "spoken_to", "interrupt", "check"]:
        assert trig in text, trig
    for tier in ["reflex", "fast", "slow", "hooked"]:
        assert tier in text, tier
    assert "week 1" in text


def test_AC7_decisions_per_day_agree_with_the_event_log(analyzed):
    run, _ = analyzed
    rows = read_csv(run / "analysis" / "decisions_per_day.csv")
    got = {(r["player"], int(r["day"]), r["group"], r["key"]): int(float(r["count"])) for r in rows}
    con = sqlite3.connect(run / "run.db")
    want: Counter = Counter()
    query = "SELECT tick, payload_json FROM events WHERE type='decision_made'"
    for tick, payload in con.execute(query):
        p = json.loads(payload)
        day = max(0, tick - 1) // TPD + 1
        want[(p["player"], day, "trigger", p["trigger"])] += 1
        want[(p["player"], day, "tier", p["tier"])] += 1
    con.close()
    assert want
    for key, n in want.items():
        assert got.get(key) == n, key
    keys = {(r["group"], r["key"]) for r in rows}
    for trig in ["finished", "spoken_to", "interrupt", "check"]:
        assert ("trigger", trig) in keys
    for tier in ["reflex", "fast", "slow", "hooked"]:
        assert ("tier", tier) in keys


def test_AC7_deaths_csv_matches_the_event_log(analyzed):
    run, _ = analyzed
    con = sqlite3.connect(run / "run.db")
    n = con.execute(
        "SELECT COUNT(*) FROM events WHERE type IN ('died','villager_died')"
    ).fetchone()[0]
    con.close()
    rows = read_csv(run / "analysis" / "deaths.csv")
    assert len(rows) == n


def test_AC7_analyze_cli_on_a_missing_run_fails_cleanly():
    done = run_cli("analyze", "--run", "p5acc_no_such_run")
    assert done.returncode != 0
    assert "Traceback" not in done.stderr


# ------------------------------------------------------------------------------- AC-8


def report(days: int, check: float | None) -> AnalysisReport:
    r = AnalysisReport(days_covered=days, players=["player_1", "player_2", "player_3", "player_4"])
    if check is not None:
        r.per_player_by_trigger = {p: {"check": check} for p in r.players}
        r.decisions_per_day_by_trigger = {"check": check}
    return r


def test_AC8_checks_over_the_band_propose_a_longer_check_interval():
    props = propose_tuning(report(7, 9.5), CFG)
    hit = [p for p in props if p.key == "balance:turn.check_minutes"]
    assert len(hit) == 1
    p = hit[0]
    assert p.current == 120 and p.proposed == 150
    assert "9.5" in p.evidence and "8" in p.evidence


def test_AC8_no_proposal_when_a_metric_is_on_target():
    props = propose_tuning(report(7, 8.0), CFG)
    assert not [p for p in props if p.key == "balance:turn.check_minutes"]


def test_AC8_no_proposal_with_one_day_of_data():
    assert propose_tuning(report(1, 9.5), CFG) == []


def test_AC8_nothing_measured_gives_no_proposal():
    assert propose_tuning(report(7, None), CFG) == []


def test_AC8_every_proposal_names_key_current_proposed_and_evidence():
    props = propose_tuning(report(21, 9.5), CFG)
    assert props
    for p in props:
        assert ":" in p.key
        assert p.current is not None and p.proposed is not None
        assert p.evidence
        assert CFG.resolve_key(p.key) == p.current


def test_AC8_proposals_never_edit_the_config():
    before = (ROOT / "config" / "balance.toml").read_bytes()
    propose_tuning(report(21, 9.5), CFG)
    assert (ROOT / "config" / "balance.toml").read_bytes() == before


def test_AC8_csv_rows_have_key_current_proposed_and_evidence(analyzed):
    run, _ = analyzed
    path = run / "analysis" / "tuning_proposals.csv"
    header = path.read_text(encoding="utf-8").splitlines()[0].split(",")
    for col in ["key", "current", "proposed", "evidence"]:
        assert col in header
    for row in read_csv(path):
        assert row["key"] and row["current"] != "" and row["proposed"] != "" and row["evidence"]


# ------------------------------------------------------------------------------- AC-9

GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]


def git(cwd, *args):
    subprocess.run([*GIT, *args], cwd=cwd, check=True, capture_output=True, text=True)


def strip_keys(text: str) -> str:
    out = []
    for line in text.splitlines():
        if line.split("=")[0].strip() in ("seed", "spend_cap_usd"):
            continue
        out.append(line)
    return "\n".join(out) + "\n"


def set_run(root, head: str):
    path = root / "config" / "run.toml"
    body = strip_keys(path.read_text(encoding="utf-8-sig"))
    path.write_bytes((head + body).encode("utf-8"))
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "edit")


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(ROOT / "config", root / "config")
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    return root


def checks(root):
    return {c.name: c for c in launch_checks(root, root / "config")}


def good(repo):
    set_run(repo, "seed = 5\nspend_cap_usd = 100.0\n")


def test_AC9_passes_when_all_three_are_in_order(repo):
    good(repo)
    res = checks(repo)
    assert set(res) >= {"config_clean", "spend_cap", "seed"}
    assert all(c.passed for c in res.values()), {k: v.detail for k, v in res.items()}


def test_AC9_fails_with_uncommitted_change_in_config(repo):
    good(repo)
    bal = repo / "config" / "balance.toml"
    bal.write_bytes(bal.read_bytes() + b"\n# edit\n")
    res = checks(repo)
    assert not res["config_clean"].passed
    assert res["seed"].passed and res["spend_cap"].passed


def test_AC9_fails_with_an_untracked_file_in_config(repo):
    good(repo)
    (repo / "config" / "extra.toml").write_text("a = 1\n", encoding="utf-8")
    assert not checks(repo)["config_clean"].passed


def test_AC9_fails_without_a_spend_cap(repo):
    set_run(repo, "seed = 5\n")
    res = checks(repo)
    assert not res["spend_cap"].passed
    assert res["seed"].passed and res["config_clean"].passed


@pytest.mark.parametrize("cap", ["0", "-3.0", "true", "'lots'"])
def test_AC9_a_bad_spend_cap_fails(repo, cap):
    set_run(repo, f"seed = 5\nspend_cap_usd = {cap}\n")
    assert not checks(repo)["spend_cap"].passed


def test_AC9_fails_without_a_seed(repo):
    set_run(repo, "spend_cap_usd = 50.0\n")
    res = checks(repo)
    assert not res["seed"].passed
    assert res["spend_cap"].passed


def test_AC9_seed_zero_is_a_valid_seed(repo):
    set_run(repo, "seed = 0\nspend_cap_usd = 50.0\n")
    assert checks(repo)["seed"].passed


def test_AC9_a_boolean_seed_fails(repo):
    set_run(repo, "seed = true\nspend_cap_usd = 50.0\n")
    assert not checks(repo)["seed"].passed


def test_AC9_cli_exit_codes(repo):
    good(repo)
    ok = run_cli("launch-check", "--root", str(repo))
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert "[PASS]" in ok.stdout and "[FAIL]" not in ok.stdout
    (repo / "config" / "extra.toml").write_text("a = 1\n", encoding="utf-8")
    bad = run_cli("launch-check", "--root", str(repo))
    assert bad.returncode == 1
    assert "[FAIL] config_clean" in bad.stdout


def test_AC9_the_check_leaves_the_real_config_alone():
    before = (ROOT / "config" / "run.toml").read_bytes()
    launch_checks(ROOT, ROOT / "config")
    assert (ROOT / "config" / "run.toml").read_bytes() == before


# --------------------------------------------------------------------------- AC-11 recovery


def test_AC11_recovery_of_a_judged_run_makes_no_new_judge_call_for_stored_keys(tmp_path):
    first = FakeAdapter()
    sim = new_ai_sim(seats=(1, 2), seed=5, adapter=first, db_path=tmp_path / "run.db")
    sim.run(1500)
    sim.save()
    sim.run(100)
    sim.flush()  # replies on disk, no snapshot after tick 700
    sim.db.close()  # the "crash"
    con = sqlite3.connect(tmp_path / "run.db")
    stored = {json.loads(r[0])["key"] for r in con.execute("SELECT details_json FROM ai_calls")}
    con.close()
    assert any(k.startswith("judge/") for k in stored), "the run made no judge calls"

    second = FakeAdapter()
    db = RunDB.open(tmp_path / "run.db")
    sim2, info = recover(db, CFG.assets, lambda s: setattr(s, "adapters", {"fake": second}))
    assert sim2.world.tick == 1600 and info.tail_events > 0
    assert not (set(second.calls) & stored), "a stored call was asked again"
    sim2.run(60)
    assert not (set(second.calls) & stored)
    sim2.db.close()
