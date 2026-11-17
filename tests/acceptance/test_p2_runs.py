"""Phase 2 AC-29 .. AC-32: the balance year, the scripted scenario, determinism, screenshot."""

from __future__ import annotations

import json
import shutil
from collections import Counter

import pytest
from conftest import LOGS, ROOT, RUNS, cli, db_events, fresh_run
from p2_helpers import make_cfg

from ai_island.rules.actions import ACTION_KINDS
from ai_island.sim import Simulation

CFG = make_cfg()
YEAR = 80640


# --------------------------------------------------------------------------------- AC-29


@pytest.fixture(scope="module")
def year_run():
    name = fresh_run("acc_p2_year")
    r = cli("headless", "--run", name, "--ticks", str(YEAR), "--seed", "1", "--players", "dummy",
            timeout=3000)  # fmt: skip
    assert r.returncode == 0, r.stderr[-2000:]
    rep = cli("report", "--run", name, timeout=600)
    assert rep.returncode == 0, rep.stderr[-2000:]
    LOGS.mkdir(exist_ok=True)
    (LOGS / "p2_report_output.txt").write_text(rep.stdout, encoding="utf-8")
    yield name, rep.stdout
    shutil.rmtree(RUNS / name, ignore_errors=True)


@pytest.mark.slow
def test_AC29_report_has_no_failing_or_insufficient_target(year_run):
    _, out = year_run
    assert "PASS" in out
    assert "FAIL" not in out, out
    assert "insufficient data" not in out.lower(), out


@pytest.mark.slow
def test_AC29_events_show_week1_median_x_and_no_early_departures(year_run):
    name, _ = year_run
    rows = db_events(name)
    days = [json.loads(p) for _, t, p in rows if t == "player_day"]
    assert days, "no player_day events"
    week1 = sorted(d["x_median"] for d in days if d["day"] <= 7)
    assert week1
    med = week1[len(week1) // 2]
    assert 60 <= med <= 79, med
    for _, t, p in rows:
        if t == "villager_left":
            d = json.loads(p)
            assert d["hungry_days"] + d["hard_days"] >= 3, d


# --------------------------------------------------------------------------------- AC-30


@pytest.fixture(scope="module")
def scripted_run():
    name = fresh_run("acc_p2_scripted")
    r = cli("headless", "--run", name, "--players", "scripted", "--ticks", "80640", "--seed", "1",
            timeout=1200)  # fmt: skip
    assert r.returncode == 0, r.stderr[-2000:]
    yield name
    shutil.rmtree(RUNS / name, ignore_errors=True)


@pytest.mark.slow
def test_AC30_every_action_kind_is_used_at_least_once(scripted_run):
    used = set()
    for _, t, p in db_events(scripted_run):
        if t == "action_started":
            used.add(json.loads(p)["kind"])
    assert set(ACTION_KINDS) - used == set(), sorted(set(ACTION_KINDS) - used)


@pytest.mark.slow
def test_AC30_scripted_players_trade_steal_claim_fight_dogs_and_finish_all_stages(scripted_run):
    types = Counter()
    harm = Counter()
    stages = set()
    for _, t, p in db_events(scripted_run):
        types[t] += 1
        d = json.loads(p)
        if t == "harm":
            harm[d["kind"]] += 1
        if t == "stage_done":
            stages.add((d.get("player"), d.get("stage")))
    assert types["trade_done"] >= 1
    assert harm["steal"] >= 1
    assert harm["pull_stakes"] + types["task_done"] >= 1
    assert types["dog_attack"] + types["dog_scared"] >= 1
    done = {s for _, s in stages}
    assert {1, 2, 3, 4, 5} <= done, sorted(done)
    claims = [
        1 for _, t, p in db_events(scripted_run) if t == "action_started" and '"claim_land"' in p
    ]
    assert claims


# --------------------------------------------------------------------------------- AC-31


def _log(sim):
    return [repr(e) for e in sim.events]


def test_AC31_same_seed_gives_the_same_event_log_with_people():
    a = Simulation.new(CFG, 3, "dummy")
    b = Simulation.new(CFG, 3, "dummy")
    a.run(2000)
    b.run(2000)
    assert _log(a) == _log(b) and len(_log(a)) > 50
    c = Simulation.new(CFG, 4, "dummy")
    c.run(2000)
    assert _log(c) != _log(a)


def test_AC31_populated_mid_action_snapshot_round_trip_gives_the_same_log():
    a = Simulation.new(CFG, 5, "dummy")
    mid = False
    for _ in range(4000):
        a.step()
        busy = [p for p in a.world.players.values() if p.action is not None]
        if a.world.tick > 600 and busy and a.world.pending_interrupts is not None:
            mid = True
            break
    assert mid, "no player was ever mid-action"
    snap = a.snapshot()
    b = Simulation.from_snapshot(snap, CFG)
    assert [p.action is not None for p in b.world.players.values()] == [
        p.action is not None for p in a.world.players.values()
    ]
    a.run(1500)
    b.run(1500)
    assert _log(a)[-200:] == _log(b)[-200:]
    assert a.snapshot().state_json == b.snapshot().state_json


def test_AC31_old_snapshot_versions_are_refused():
    from ai_island.sim import SnapshotError

    sim = Simulation.new(CFG, 1, "dummy")
    snap = sim.snapshot()
    assert snap.schema_version == 3
    with pytest.raises(SnapshotError):
        Simulation.from_snapshot(snap.model_copy(update={"schema_version": 2}), CFG)


# --------------------------------------------------------------------------------- AC-32


def test_AC32_screenshot_of_a_run_with_players_and_villagers(run_name):
    assert cli("new", run_name, "--seed", "1", "--players", "dummy").returncode == 0
    r = cli("headless", "--run", run_name, "--ticks", "400", "--players", "dummy")
    assert r.returncode == 0, r.stderr[-1500:]
    out = ROOT / "logs" / "p2_people_test.png"
    LOGS.mkdir(exist_ok=True)
    out.unlink(missing_ok=True)
    r = cli("view", "--run", run_name, "--ticks", "60", "--screenshot", "logs/p2_people_test.png")
    assert r.returncode == 0, r.stderr[-1500:]
    assert out.exists() and out.stat().st_size > 5000
