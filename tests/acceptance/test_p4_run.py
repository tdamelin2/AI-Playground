"""Phase 4 acceptance tests: pause and recovery, observer, week, config, CLI (AC-19 .. AC-24)."""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import tomllib
from pathlib import Path

import pytest
from p4_helpers import CFG, ROOT, clean, new_ai_sim, raise_int
from test_p4_choices import slow_reply  # noqa: I001

from ai_island.config import ConfigError, load_config
from ai_island.llm.errors import RunPaused
from ai_island.llm.fake import FakeAdapter
from ai_island.sim import Simulation, SimulationBroken, ai_config
from ai_island.storage.db import RunDB
from ai_island.storage.power import KeepAwake
from ai_island.storage.recovery import recover
from ai_island.storage.run_control import LiveRun, exit_paused
from ai_island.world.view import frame_from_world
from conftest import RUNS, cli


def event_log(sim):
    return [(e.tick, e.type, e.payload_json()) for e in sim.events]


def open_live(path, adapter, clock=None):
    def setup(s):
        s.adapters = {"fake": adapter}
        s.ai_sleep = lambda _x: None
        if clock is not None:
            s.ai_wall = lambda: clock[0]

    return LiveRun.open(CFG, path, keep_awake=KeepAwake(lambda _f: 1), setup=setup)


def make_db(tmp_path, seats=(1,), seed=2):
    sim = new_ai_sim(seats=seats, seed=seed, db_path=tmp_path / "run.db")
    sim.db.close()
    return tmp_path / "run.db"


# ---------------------------------------------------------------------------------- AC-19


def test_AC19_pause_during_a_delayed_reply_lets_it_finish_then_saves_a_snapshot(tmp_path):
    path = make_db(tmp_path)
    adapter = FakeAdapter(delays={("player_1", "ranking"): 0.4})
    live = open_live(path, adapter)
    hits = []

    def hook():
        if not hits:
            hits.append(1)
            live.toggle_pause()  # P pressed while the reply is still on its way

    live.wait_hook = hook
    try:
        live.run_ticks(6)
        assert hits, "the wait hook was never called"
        assert live.paused and live.pause_reason is None
        assert live.sim.world.tick == 6
        assert live.sim.controllers["player_1"].day0_done  # the late reply was applied
        snap = live.db.latest_snapshot()
        assert snap.tick == 6
    finally:
        live.close()
    rows = (
        sqlite3.connect(path)
        .execute("SELECT COUNT(*) FROM value_history WHERE player_id = 'player_1'")
        .fetchone()
    )
    assert rows[0] == 14


def test_AC19_closing_the_window_during_a_reply_also_finishes_the_tick_and_saves(tmp_path):
    path = make_db(tmp_path)
    live = open_live(path, FakeAdapter(delays={("player_1", "ranking"): 0.3}))
    hits = []

    def hook():
        if not hits:
            hits.append(1)
            live.request_close()

    live.wait_hook = hook
    try:
        live.run_ticks(6)
        assert live.pending_close or live.paused
        assert live.sim.world.tick == 6 and live.db.latest_snapshot().tick == 6
    finally:
        live.close()


def test_AC19_crash_recovery_gives_the_same_event_log_and_no_call_is_repeated(tmp_path):
    ref = new_ai_sim(seats=(1, 2), seed=4)
    ref.run(700)
    ref_log = event_log(ref)

    first = FakeAdapter()
    sim = new_ai_sim(seats=(1, 2), seed=4, adapter=first, db_path=tmp_path / "run.db")
    sim.run(300)
    sim.save()
    sim.run(300)
    sim.flush()  # events and replies are on disk, but no snapshot after tick 300
    sim.db.close()  # the "crash"
    stored = {
        json.loads(r[0])["key"]
        for r in sqlite3.connect(tmp_path / "run.db").execute("SELECT details_json FROM ai_calls")
    }
    assert stored

    second = FakeAdapter()
    db = RunDB.open(tmp_path / "run.db")
    sim2, info = recover(db, CFG.assets, lambda s: setattr(s, "adapters", {"fake": second}))
    assert info.tail_events > 0 and sim2.world.tick == 600
    assert second.total_calls == 0, "recovery asked the AI again"
    log = event_log(sim2)
    ref600 = [r for r in ref_log if r[0] <= 600]
    assert log == ref600[-len(log) :]
    sim2.run(100)
    log = event_log(sim2)
    assert sim2.world.tick == 700 and log == ref_log[-len(log) :]
    assert second.total_calls > 0
    assert not (set(second.calls) & stored), "a stored reply was requested again"
    sim2.save()
    sim2.db.close()


@pytest.mark.parametrize(
    "failure,reason,text",
    [
        (["network"] * 4, "network", "Paused: no internet connection"),
        (["rate_limit"] * 4, "network", "Paused: no internet connection"),
        (["sleep"], "sleep", "Paused: the laptop slept"),
    ],
)
def test_AC19_network_and_sleep_failures_pause_the_run_and_resume_continues(
    tmp_path, failure, reason, text
):
    path = make_db(tmp_path)
    clock = [1000.0]
    adapter = FakeAdapter(
        failures={("player_1", "ranking"): list(failure)},
        on_sleep=lambda: clock.__setitem__(0, clock[0] + 400.0),
    )
    live = open_live(path, adapter, clock)
    try:
        for _ in range(60):
            live.advance(1000.0)
            if live.paused:
                break
        assert live.paused and live.pause_reason == text
        assert live.sim.broken
        assert all(
            e.tick < live.sim.world.tick for e in live.sim.events
        )  # the half tick left nothing
        with pytest.raises(SimulationBroken):
            live.sim.run(1)
        live.resume()
        assert not live.paused and live.pause_reason is None
        start = live.sim.world.tick
        live.run_ticks(3)
        assert live.sim.world.tick == start + 3
        assert live.sim.controllers["player_1"].day0_done
    finally:
        live.close()
    _ = reason


def test_AC19_sleep_failure_raises_a_sleep_pause_on_the_simulation():
    clock = [0.0]
    adapter = FakeAdapter(
        failures={("player_1", "ranking"): ["sleep"]},
        on_sleep=lambda: clock.__setitem__(0, clock[0] + 400.0),
    )
    sim = new_ai_sim(adapter=adapter)
    sim.ai_wall = lambda: clock[0]
    sim.ai_sleep = lambda _x: None
    with pytest.raises(RunPaused) as err:
        sim.run(8)
    assert err.value.reason == "sleep" and sim.broken


def test_AC19_headless_and_resume_print_the_notice_and_exit_4(capsys):
    code = exit_paused("t4", RunPaused("network"))
    out = capsys.readouterr().out
    assert code == 4
    assert "Run paused: network. Continue with: uv run python main.py resume t4" in out


# ---------------------------------------------------------------------------------- AC-20


@pytest.fixture(autouse=False)
def dummy_driver(monkeypatch):
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    yield
    import pygame

    pygame.quit()


def make_obs(db, controls):
    import pygame

    pygame.quit()
    from ai_island.observer import Observer

    return Observer(CFG.assets, CFG.run.view, ROOT, db, controls)


def lines(text):
    return [ln for ln in text.splitlines() if ln.strip()]


def test_AC20_players_choice_points_and_spend_tabs_of_a_fake_run(tmp_path, dummy_driver):
    from ai_island.storage.run_control import MemoryControls

    sim = new_ai_sim(seats=(1, 2), seed=6, db_path=tmp_path / "run.db")
    sim.run(400)
    clean(sim)
    sim.adapters["fake"].script[("player_1", "main")] = [slow_reply(choice=1)]
    raise_int(sim, "spoken_to", "player_1", source="player_2")
    sim.run(1)
    sim.save()
    frame = frame_from_world(sim)
    ctl = MemoryControls(CFG.run)
    obs = make_obs(sim.db, ctl)
    obs.draw(frame, 0.0)
    text = obs.tab_text("Players")
    value_lines = re.findall(r"values \(\* = core\):[^\n]*", text)
    assert len(value_lines) == 2  # the two AI players
    for ln in value_lines:
        assert ln.count("*") - 1 == 5  # the legend star is not a core mark
        assert len(re.findall(r"[a-z_]+\*? \d+(?:\.\d+)?", ln.split(":", 1)[1])) == 14
    assert text.count("values: none (no value table)") == 2  # dummies keep "none"
    rows = lines(obs.tab_text("Choice points"))
    slow = [r for r in rows if "[slow]" in r]
    assert slow, rows
    assert re.search(r"served: .*; violated: .*; (toward|against)", slow[0])
    assert "rest" in slow[0]
    spend = lines(obs.tab_text("Spend"))
    assert spend[0].startswith("Spent $0.00 of $")
    sim.db.close()


def test_AC20_waiting_and_pause_reason_show_in_the_top_bar(tmp_path, dummy_driver):
    from ai_island.storage.run_control import MemoryControls

    sim = new_ai_sim(seats=(1,), seed=6, db_path=tmp_path / "run.db")
    sim.run(5)
    sim.save()
    frame = frame_from_world(sim)
    ctl = MemoryControls(CFG.run)
    obs = make_obs(sim.db, ctl)
    obs.draw(frame, 0.0)
    tick = sim.world.tick
    obs.waiting_frame()
    assert obs.elements["top_status"].text == "Waiting for replies..."
    assert sim.world.tick == tick  # drawing never advances the run
    ctl.paused = True
    ctl.pause_reason = "Paused: spending limit reached"
    obs.draw(frame, 0.0)
    assert obs.elements["top_status"].text == "Paused: spending limit reached"
    sim.db.close()


# ---------------------------------------------------------------------------------- AC-21


def week_run(seed):
    adapter = FakeAdapter()
    sim = new_ai_sim(seats=(1, 2, 3, 4), seed=seed, adapter=adapter)
    sim.run(sim.week_ticks)
    return sim, adapter


@pytest.mark.slow
def test_AC21_a_week_with_four_fake_players_completes_and_repeats_exactly():
    a, ad_a = week_run(11)
    b, ad_b = week_run(11)
    assert a.world.tick == 10080
    done = [e.payload for e in a.events if e.type == "reflection_completed"]
    assert sorted(d.player for d in done) == [f"player_{i}" for i in range(1, 5)]
    assert event_log(a) == event_log(b)
    assert ad_a.calls == ad_b.calls
    assert a.records and len(a.records) == len(b.records)
    c, _ = week_run(12)
    assert event_log(c) != event_log(a)  # a different seed is a different week


# ---------------------------------------------------------------------------------- AC-22


def test_AC22_models_toml_has_nine_filled_roles_with_sources_and_no_banned_model():
    models = CFG.models
    assert sorted(models.roles) == sorted(
        [f"player_{i}_{k}" for i in range(1, 5) for k in ("main", "helper")] + ["judge"]
    )
    banned = models.llm.banned_model_words
    for rid, role in models.roles.items():
        assert role.source_url.startswith("https://"), rid
        assert role.provider in {"anthropic", "openai", "google", "xai", "mistral"}
        assert role.model and not any(w in role.model.lower() for w in banned), rid
        p = role.prices
        assert p.input > 0 and p.output > 0
    text = (ROOT / "config" / "models.toml").read_text(encoding="utf-8-sig")
    assert len(re.findall(r"(?m)^# source: https://", text)) >= 9
    raw = tomllib.loads(text)
    assert set(raw["roles"]) == set(models.roles)
    assert {"deepseek", "qwen", "kimi", "glm", "minimax", "yi-"} <= set(banned)
    ai_config(CFG, [1, 2, 3, 4], max_dollars=1.0)  # loads for a four-seat AI run


def tampered(tmp_path, edit):
    dest = tmp_path / "config"
    shutil.copytree(ROOT / "config", dest)
    path = dest / "models.toml"
    path.write_text(edit(path.read_text(encoding="utf-8-sig")), encoding="utf-8")
    return dest


def test_AC22_a_banned_model_name_is_refused(tmp_path):
    def edit(text):
        i = text.index("[roles.player_1_main]")
        tail = re.sub(r'(?m)^model = "[^"]+"', 'model = "Qwen3-max"', text[i:], count=1)
        return text[:i] + tail

    with pytest.raises(ConfigError, match=r"(?i)banned"):
        load_config(tampered(tmp_path, edit))


def test_AC22_a_role_without_a_source_url_is_refused(tmp_path):
    def edit(text):
        return re.sub(r'(?m)^source_url = ".*"\n', "", text, count=1)

    with pytest.raises(ConfigError):
        load_config(tampered(tmp_path, edit))


def test_AC22_an_unknown_provider_is_refused(tmp_path):
    def edit(text):
        return re.sub(r'(?m)^provider = "[^"]+"', 'provider = "deepseek"', text, count=1)

    with pytest.raises(ConfigError):
        load_config(tampered(tmp_path, edit))


# ---------------------------------------------------------------------------------- AC-23

HEAD = re.compile(
    r"^Day \d+ \d\d:\d\d \| (\w+) \| (reflex|fast|slow|hooked) \| (finished|spoken_to|interrupt|check)$"  # noqa: E501
)


def run_cli(name, *extra):
    shutil.rmtree(RUNS / name, ignore_errors=True)
    done = cli("new", name, "--ai-seats", "1", "--cheap", "--max-dollars", "1", *extra)
    return done


def check_run(name, expect_ticks=None):
    db = sqlite3.connect(RUNS / name / "run.db")
    try:
        roles = {
            r[0] for r in db.execute("SELECT DISTINCT role FROM ai_calls WHERE role != 'judge'")
        }
        players = {
            r[0]
            for r in db.execute("SELECT DISTINCT player_id FROM ai_calls WHERE role != 'judge'")
        }
        judge_players = {
            r[0] for r in db.execute("SELECT DISTINCT player_id FROM ai_calls WHERE role = 'judge'")
        }
        decided = {
            json.loads(r[0])["player"]
            for r in db.execute("SELECT payload_json FROM events WHERE type = 'decision_made'")
        }
        last = db.execute("SELECT MAX(tick) FROM events").fetchone()[0]
        snap = db.execute("SELECT MAX(tick) FROM snapshots").fetchone()[0]
        n_dec = db.execute(
            "SELECT COUNT(*) FROM events WHERE type = 'decision_made' "
            "AND json_extract(payload_json, '$.player') = 'player_1'"
        ).fetchone()[0]
    finally:
        db.close()
    assert roles == {"player_1_helper"}, roles  # cheap: the helper model everywhere
    assert players == {"player_1"} and decided == {"player_1"}  # dummies in seats 2-4
    assert judge_players <= {None}  # judge rows (Contract C6) belong to no player
    if expect_ticks:
        assert last is not None and snap == expect_ticks
    return n_dec


def check_decisions(name, n_dec):
    out = cli("decisions", "--run", name, "--player", "1")
    assert out.returncode == 0, out.stderr
    ls = out.stdout.splitlines()
    heads = [ln for ln in ls if HEAD.match(ln)]
    assert len(heads) == n_dec > 0
    assert {HEAD.match(h).group(1) for h in heads} == {"Ada"}
    assert len([ln for ln in ls if ln.startswith("Situation: ")]) == n_dec
    assert len([ln for ln in ls if ln.startswith("Self-label: ")]) == n_dec
    for ln in ls:
        if ln.startswith("Self-label: "):
            assert ln == "Self-label: none (reflex)" or re.fullmatch(
                r"Self-label: served .*; violated .*; (toward|against)", ln
            ), ln
    if any("| slow |" in h or "| hooked |" in h for h in heads):
        assert any(ln.startswith("Options:") for ln in ls)
        assert any(ln.startswith("Chose:") for ln in ls)
        assert any(ln.startswith("Trade-off:") for ln in ls)
    other = cli("decisions", "--run", name, "--player", "2")
    assert other.returncode == 0 and "| Ada |" not in other.stdout


def test_AC23_short_ai_run_and_decisions_listing():
    name = "acc_p4_cli_short"
    try:
        done = run_cli(name, "--ticks", "700")
        assert done.returncode == 0, done.stderr
        n = check_run(name, 700)
        check_decisions(name, n)
    finally:
        shutil.rmtree(RUNS / name, ignore_errors=True)


@pytest.mark.slow
def test_AC23_default_new_runs_a_whole_game_week():
    name = "acc_p4_cli_week"
    try:
        done = run_cli(name)
        assert done.returncode == 0, done.stderr
        n = check_run(name, 10080)
        check_decisions(name, n)
        db = sqlite3.connect(RUNS / name / "run.db")
        try:
            assert (
                db.execute(
                    "SELECT COUNT(*) FROM events WHERE type = 'reflection_completed'"
                ).fetchone()[0]
                == 1
            )
        finally:
            db.close()
    finally:
        shutil.rmtree(RUNS / name, ignore_errors=True)


def test_AC23_no_ai_new_stays_create_only():
    name = "acc_p4_cli_plain"
    shutil.rmtree(RUNS / name, ignore_errors=True)
    try:
        done = cli("new", name, "--players", "dummy")
        assert done.returncode == 0, done.stderr
        db = sqlite3.connect(RUNS / name / "run.db")
        try:
            assert db.execute("SELECT COUNT(*) FROM ai_calls").fetchone()[0] == 0
            assert (db.execute("SELECT MAX(tick) FROM events").fetchone()[0] or 0) == 0
        finally:
            db.close()
    finally:
        shutil.rmtree(RUNS / name, ignore_errors=True)


# ---------------------------------------------------------------------------------- AC-24


def test_AC24_rule_based_runs_are_unchanged_and_deterministic():
    logs = []
    for _ in range(2):
        sim = Simulation.new(CFG, 1)
        assert sim.world.controller_kind == "dummy" and not sim.mixed
        sim.run(1440)
        logs.append(event_log(sim))
    assert logs[0] == logs[1] and logs[0]
    phase4 = {"decision_made", "value_repaired", "value_violation", "mistake_flagged",
              "reflection_completed", "invention_rejected"}  # fmt: skip
    assert not {t for _, t, _ in logs[0]} & phase4


def test_AC24_the_old_suites_are_still_collected():
    names = {p.name for p in Path(__file__).parent.glob("test_p*.py")}
    assert {"test_p1_setup_storage.py", "test_p3_observer.py", "test_p4_llm.py"} <= names
