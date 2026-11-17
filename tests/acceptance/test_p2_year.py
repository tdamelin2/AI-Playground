"""Phase 2 AC-29..AC-32: the dummy year, the scripted scenario, determinism, the screenshot."""

from __future__ import annotations

import json
import shutil
import sqlite3
import time

import pytest
from conftest import LOGS, ROOT, RUNS, cli, db_events
from p2_helpers import make_cfg

from ai_island.rules.actions import ACTION_KINDS
from ai_island.sim import Simulation

CFG = make_cfg()
YEAR = 80640


def _fresh(name):
    shutil.rmtree(RUNS / name, ignore_errors=True)
    return name


@pytest.fixture(scope="module")
def year_report():
    name = _fresh("acc_p2_year")
    t0 = time.time()
    r = cli("headless", "--run", name, "--ticks", str(YEAR), "--seed", "1", timeout=900)
    secs = time.time() - t0
    assert r.returncode == 0, r.stderr[-2000:]
    rep = cli("report", "--run", name)
    LOGS.mkdir(exist_ok=True)
    (LOGS / "p2_year_report.txt").write_text(
        f"headless seconds: {secs:.0f}\n{rep.stdout}\n{rep.stderr}", encoding="utf-8"
    )
    yield rep.stdout, secs, name
    shutil.rmtree(RUNS / name, ignore_errors=True)


@pytest.mark.slow
def test_AC29_report_runs_and_prints_the_four_targets(year_report):
    out, secs, _ = year_report
    low = out.lower()
    assert "week" in low and "median" in low
    assert "food" in low and "winter" in low and "depart" in low


@pytest.mark.slow
def test_AC29_all_targets_pass_and_none_is_insufficient(year_report):
    out, _, _ = year_report
    assert "insufficient data" not in out.lower(), out
    verdicts = [ln for ln in out.splitlines() if "PASS" in ln or "FAIL" in ln]
    assert len(verdicts) >= 4, out
    assert not [ln for ln in verdicts if "FAIL" in ln], out


@pytest.mark.slow
def test_AC29_year_runs_in_under_five_minutes(year_report):
    assert year_report[1] < 300


@pytest.mark.slow
def test_AC29_no_villager_leaves_before_three_adverse_days(year_report):
    _, _, name = year_report
    left = [json.loads(p) for _, t, p in db_events(name) if t == "villager_left"]
    assert left, "a full year with neglected homes should see departures"
    for e in left:
        assert e["hungry_days"] >= 3 or e["hard_days"] >= 3, e


@pytest.mark.slow
def test_AC29_players_exist_and_player_day_events_are_written(year_report):
    _, _, name = year_report
    days = [json.loads(p) for _, t, p in db_events(name) if t == "player_day"]
    assert {d["player"] for d in days} == {f"player_{i}" for i in range(1, 5)}
    assert len(days[0]["x_hourly"]) == 24


@pytest.fixture(scope="module")
def scripted():
    name = _fresh("acc_p2_scripted")
    t0 = time.time()
    r = cli("headless", "--players", "scripted", "--run", name, "--ticks", str(YEAR),
            "--seed", "1", timeout=900)  # fmt: skip
    secs = time.time() - t0
    assert r.returncode == 0, r.stderr[-2000:]
    events = db_events(name)
    yield events, secs
    shutil.rmtree(RUNS / name, ignore_errors=True)


@pytest.mark.slow
def test_AC30_every_action_is_used_at_least_once(scripted):
    events, _ = scripted
    used = {json.loads(p)["kind"] for _, t, p in events if t == "action_started"}
    assert not (set(ACTION_KINDS) - used), sorted(set(ACTION_KINDS) - used)


@pytest.mark.slow
def test_AC30_scripted_players_trade_steal_claim_fight_dogs_and_finish_five_stages(scripted):
    events, secs = scripted
    types = {}
    for _, t, p in events:
        types.setdefault(t, []).append(json.loads(p))
    assert types.get("trade_done"), "no trade"
    assert [h for h in types.get("harm", []) if h["kind"] == "steal"], "no steal"
    assert types.get("dog_scared") or types.get("dog_attack"), "no dog fight"
    assert [a for a in types.get("action_started", []) if a["kind"] == "claim_land"]
    stages = {}
    for e in types.get("stage_done", []):
        stages.setdefault(e["player"], set()).add(e["stage"])
    assert set(stages) == {f"player_{i}" for i in range(1, 5)}, stages
    for pid, s in stages.items():
        assert s >= {1, 2, 3, 4, 5}, (pid, sorted(s))
    assert secs < 180, f"scripted scenario took {secs:.0f} s"


# ----------------------------------------------------------------------------------- AC-31


def _log(sim):
    return [(e.tick, e.type, e.payload.model_dump(mode="json")) for e in sim.world.events]


def test_AC31_same_seed_gives_the_same_event_log_with_people():
    a, b = Simulation.new(CFG, 7, "dummy"), Simulation.new(CFG, 7, "dummy")
    a.run(2880)
    b.run(2880)
    la, lb = _log(a), _log(b)
    assert la == lb
    assert any(t == "action_started" for _, t, _ in la)
    c = Simulation.new(CFG, 8, "dummy")
    c.run(2880)
    assert _log(c) != la


def test_AC31_populated_mid_action_snapshot_round_trip_gives_the_same_log():
    a = Simulation.new(CFG, 3, "dummy")
    a.run(1500)
    assert any(p.action is not None for p in a.world.players.values()), "need a mid-action state"
    snap = a.snapshot()
    n = len(a.world.events)
    b = Simulation.from_snapshot(snap, CFG)
    a.run(1500)
    b.run(1500)
    assert _log(a)[n:] == _log(b)
    assert a.snapshot().state_json == b.snapshot().state_json
    assert a.snapshot().rng_json == b.snapshot().rng_json


def test_AC31_old_snapshot_versions_are_refused():
    a = Simulation.new(CFG, 3, "dummy")
    snap = a.snapshot()
    snap.schema_version = 2
    with pytest.raises(Exception, match="version"):
        Simulation.from_snapshot(snap, CFG)


def test_AC31_resume_a_saved_populated_run_from_the_cli(run_name):
    r = cli("headless", "--run", run_name, "--ticks", "600", "--seed", "1")
    assert r.returncode == 0, r.stderr[-1500:]
    r = cli("resume", run_name, "--ticks", "600")
    assert r.returncode == 0, r.stderr[-1500:]
    con = sqlite3.connect(RUNS / run_name / "run.db")
    try:
        ids = [row[0] for row in con.execute("SELECT id FROM events ORDER BY id")]
    finally:
        con.close()
    assert ids == sorted(set(ids))


# ----------------------------------------------------------------------------------- AC-32


def test_AC32_screenshot_works_on_a_run_with_players_and_villagers(run_name):
    r = cli("headless", "--run", run_name, "--ticks", "720", "--seed", "1")
    assert r.returncode == 0, r.stderr[-1500:]
    out = LOGS / "p2_people.png"
    out.unlink(missing_ok=True)
    LOGS.mkdir(exist_ok=True)
    r = cli("view", "--run", run_name, "--ticks", "60", "--screenshot", str(out))
    assert r.returncode == 0, r.stderr[-1500:]
    assert out.exists() and out.stat().st_size > 5000
    assert ROOT.exists()
