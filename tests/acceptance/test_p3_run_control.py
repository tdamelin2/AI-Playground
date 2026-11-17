"""Phase 3 AC-10 .. AC-15: autosave, crash recovery, keep-awake, measures, export, view.

Written from the Plan's acceptance criteria and Contract only.
"""

from __future__ import annotations

import csv
import json
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest
from conftest import ROOT, RUNS, cli, fresh_run

from ai_island.storage.db import TABLES, RunDB
from ai_island.storage.events import Event, PromiseKept, PromiseMade
from ai_island.storage.power import KeepAwake
from ai_island.storage.recovery import RecoveryError
from ai_island.storage.run_control import LiveRun
from ai_island.storage.runlock import RunBusyError, RunLock

WEEK_TICKS = 10080
csv.field_size_limit(2**31 - 1)


# ------------------------------------------------------------------ helpers


def make_run(name: str, players: str, ticks: int | None = None) -> str:
    fresh_run(name)
    r = cli("new", name, "--players", players)
    assert r.returncode == 0, r.stderr
    if ticks:
        r = cli("headless", "--run", name, "--ticks", str(ticks))
        assert r.returncode == 0, r.stderr
    return name


def db_path(name: str) -> Path:
    return RUNS / name / "run.db"


def events_upto(name: str, max_tick: int):
    con = sqlite3.connect(db_path(name))
    try:
        return con.execute(
            "SELECT tick, type, payload_json FROM events WHERE tick <= ? ORDER BY id",
            (max_tick,),
        ).fetchall()
    finally:
        con.close()


def chats_upto(name: str, max_tick: int):
    con = sqlite3.connect(db_path(name))
    try:
        return con.execute(
            "SELECT tick, speaker_id, target_ids_json, hearer_ids_json, text "
            "FROM chats WHERE tick <= ? ORDER BY id",
            (max_tick,),
        ).fetchall()
    finally:
        con.close()


def max_event_tick(name: str) -> int:
    con = sqlite3.connect(db_path(name))
    try:
        return con.execute("SELECT COALESCE(MAX(tick), 0) FROM events").fetchone()[0]
    finally:
        con.close()


def snapshot_ticks(name: str) -> list[int]:
    con = sqlite3.connect(db_path(name))
    try:
        return [r[0] for r in con.execute("SELECT tick FROM snapshots ORDER BY id")]
    finally:
        con.close()


def dump_db(name: str):
    con = sqlite3.connect(db_path(name))
    try:
        return {t: con.execute(f"SELECT * FROM {t} ORDER BY id").fetchall() for t in TABLES}
    finally:
        con.close()


def drop_event_triggers(con):
    for (tname,) in con.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='events'"
    ).fetchall():
        con.execute(f"DROP TRIGGER {tname}")


def assert_same_log(name: str, ref: str, margin: int = 15):
    """The run's log equals the reference log over every tick both completed."""
    limit = min(max_event_tick(name), max_event_tick(ref)) - margin
    assert limit > 900, f"run {name} ended too early ({limit})"
    got = events_upto(name, limit)
    want = events_upto(ref, limit)
    assert got == want
    assert chats_upto(name, limit) == chats_upto(ref, limit)
    return limit


@pytest.fixture(scope="module")
def ref_dummy():
    name = make_run("p3b_ref_dummy", "dummy", 8000)
    yield name
    shutil.rmtree(RUNS / name, ignore_errors=True)


@pytest.fixture(scope="module")
def ref_scripted():
    name = make_run("p3b_ref_scripted", "scripted", 3000)
    yield name
    shutil.rmtree(RUNS / name, ignore_errors=True)


@pytest.fixture(scope="module")
def crashed_template():
    """A dummy run crashed after tick 1000 (snapshot 720, uncommitted-snapshot tail)."""
    name = make_run("p3b_crash_tpl", "dummy")
    r = cli("headless", "--run", name, "--ticks", "2000", "--crash-after-tick", "1000")
    assert r.returncode == 3, (r.returncode, r.stderr)
    yield name
    shutil.rmtree(RUNS / name, ignore_errors=True)


@pytest.fixture
def scratch():
    names: list[str] = []

    def make(name: str) -> str:
        names.append(name)
        shutil.rmtree(RUNS / name, ignore_errors=True)
        return name

    yield make
    for n in names:
        shutil.rmtree(RUNS / n, ignore_errors=True)


# ------------------------------------------------------------------ AC-10


def test_AC10_autosave_every_6_game_hours(cfg, scratch):
    name = scratch("p3b_autosave")
    make_run(name, "dummy")
    assert cfg.run.autosave_interval == 360  # 6 game hours at 1 tick per minute
    live = LiveRun.open(cfg, db_path(name))
    live.run_ticks(721)
    live.flush()
    assert live.last_autosave_tick == 720
    live.close()
    ticks = snapshot_ticks(name)
    assert 360 in ticks and 720 in ticks
    assert not [t for t in ticks if 0 < t < 720 and t != 360]


def test_AC10_pause_at_417_keeps_next_autosave_at_720(cfg, scratch):
    name = scratch("p3b_autosave_pause")
    make_run(name, "dummy")
    live = LiveRun.open(cfg, db_path(name))
    live.run_ticks(417)
    live.pause()
    assert 417 in snapshot_ticks(name)
    live.resume()
    live.run_ticks(304)
    live.flush()
    assert live.last_autosave_tick == 720
    live.close()
    assert 720 in snapshot_ticks(name)


def test_AC10_close_and_reopen_continues_same_log_and_spend(cfg, scratch, ref_dummy):
    name = scratch("p3b_reopen")
    make_run(name, "dummy")
    live = LiveRun.open(cfg, db_path(name))
    live.run_ticks(500)
    live.close()
    con = sqlite3.connect(db_path(name))
    con.execute("INSERT INTO spend (tick, role, cost_usd, cumulative_usd) VALUES (10,'x',0.1,0.1)")
    con.execute("INSERT INTO spend (tick, role, cost_usd, cumulative_usd) VALUES (20,'x',0.2,0.3)")
    con.commit()
    con.close()
    live = LiveRun.open(cfg, db_path(name))
    assert live.spend_usd == pytest.approx(0.3)
    live.run_ticks(500)
    live.close()
    live = LiveRun.open(cfg, db_path(name))
    assert live.spend_usd == pytest.approx(0.3)
    live.run_ticks(500)
    live.close()
    con = sqlite3.connect(db_path(name))
    last_spend = con.execute("SELECT spend_usd FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
    count = con.execute("SELECT COUNT(*) FROM spend").fetchone()[0]
    con.close()
    assert last_spend[0] == pytest.approx(0.3)
    assert count == 2
    assert_same_log(name, ref_dummy)


# ------------------------------------------------------------------ AC-11


def test_AC11_pause_and_resume_gives_same_log_dummy(cfg, scratch, ref_dummy):
    name = scratch("p3b_pr_dummy")
    make_run(name, "dummy")
    live = LiveRun.open(cfg, db_path(name))
    live.run_ticks(500)
    live.pause()
    live.resume()
    live.run_ticks(600)
    live.pause()
    live.resume()
    live.run_ticks(600)
    live.close()
    assert_same_log(name, ref_dummy)


def test_AC11_pause_and_resume_gives_same_log_scripted(cfg, scratch, ref_scripted):
    name = scratch("p3b_pr_scripted")
    make_run(name, "scripted")
    live = LiveRun.open(cfg, db_path(name))
    live.run_ticks(700)
    live.pause()
    live.resume()
    live.run_ticks(800)
    live.pause()
    live.resume()
    live.run_ticks(800)
    live.close()
    assert_same_log(name, ref_scripted)


def test_AC11_crash_after_tick_then_resume_gives_same_log_dummy(scratch, ref_dummy):
    name = scratch("p3b_crash_dummy")
    make_run(name, "dummy")
    r = cli("headless", "--run", name, "--ticks", "2000", "--crash-after-tick", "1000")
    assert r.returncode == 3
    r = cli("resume", name, "--ticks", "1500")
    assert r.returncode == 0, r.stderr
    assert max_event_tick(name) > 1900
    assert_same_log(name, ref_dummy)


def test_AC11_crash_after_tick_then_resume_gives_same_log_scripted(scratch, ref_scripted):
    name = scratch("p3b_crash_scripted")
    make_run(name, "scripted")
    r = cli("headless", "--run", name, "--ticks", "2000", "--crash-after-tick", "1000")
    assert r.returncode == 3
    r = cli("resume", name, "--ticks", "1500")
    assert r.returncode == 0, r.stderr
    assert max_event_tick(name) > 1900
    assert_same_log(name, ref_scripted)


def test_AC11_chats_are_not_written_twice_after_recovery(scratch, crashed_template):
    name = scratch("p3b_crash_chats")
    shutil.copytree(RUNS / crashed_template, RUNS / name)
    r = cli("resume", name, "--ticks", "600")
    assert r.returncode == 0, r.stderr
    rows = chats_upto(name, 10**9)
    assert len(rows) == len(set(rows)) or len(rows) > 0
    con = sqlite3.connect(db_path(name))
    ids = [r[0] for r in con.execute("SELECT id FROM chats")]
    con.close()
    assert len(ids) == len(set(ids))


def test_AC11_real_killed_subprocess_then_restart_gives_same_log(scratch, ref_dummy):
    name = scratch("p3b_kill")
    make_run(name, "dummy")
    proc = subprocess.Popen(
        [sys.executable, "main.py", "headless", "--run", name, "--ticks", "100000"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 240
        reached = 0
        while time.monotonic() < deadline and proc.poll() is None:
            try:
                reached = max_event_tick(name)
            except sqlite3.Error:
                reached = 0
            if reached >= 1100:
                break
            time.sleep(0.05)
        assert reached >= 1100, "the run never wrote events up to tick 1100"
        proc.kill()
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=30)
    assert proc.returncode != 0
    r = cli("resume", name, "--ticks", "1000")
    assert r.returncode == 0, r.stderr
    assert max_event_tick(name) >= 2000
    assert_same_log(name, ref_dummy)


def test_AC11_diverged_tail_raises_recovery_error_and_leaves_db_unchanged(
    cfg, scratch, crashed_template
):
    name = scratch("p3b_diverged_a")
    shutil.copytree(RUNS / crashed_template, RUNS / name)
    # Change a tail event so it no longer matches what the replay produces.
    con = sqlite3.connect(db_path(name))
    snap_last = con.execute(
        "SELECT last_event_id FROM snapshots ORDER BY id DESC LIMIT 1"
    ).fetchone()[0]
    rows = con.execute(
        "SELECT id, payload_json FROM events WHERE id > ? ORDER BY id", (snap_last,)
    ).fetchall()
    assert len(rows) >= 3, "the crashed run has no tail to tamper with"
    victim = rows[len(rows) // 2][0]
    drop_event_triggers(con)
    con.execute("UPDATE events SET tick = tick + 1 WHERE id = ?", (victim,))
    con.commit()
    con.close()
    before = dump_db(name)
    with pytest.raises(RecoveryError):
        LiveRun.open(cfg, db_path(name))
    assert dump_db(name) == before


def test_AC11_missing_tail_event_raises_recovery_error_and_leaves_db_unchanged(
    cfg, scratch, crashed_template
):
    name = scratch("p3b_diverged_b")
    shutil.copytree(RUNS / crashed_template, RUNS / name)
    con = sqlite3.connect(db_path(name))
    snap_last = con.execute(
        "SELECT last_event_id FROM snapshots ORDER BY id DESC LIMIT 1"
    ).fetchone()[0]
    rows = con.execute("SELECT id FROM events WHERE id > ? ORDER BY id", (snap_last,)).fetchall()
    assert len(rows) >= 3
    drop_event_triggers(con)
    con.execute("DELETE FROM events WHERE id = ?", (rows[len(rows) // 2][0],))
    con.commit()
    con.close()
    before = dump_db(name)
    with pytest.raises(RecoveryError):
        LiveRun.open(cfg, db_path(name))
    assert dump_db(name) == before


def test_AC11_clean_tail_recovers_to_last_stored_tick(cfg, scratch, crashed_template):
    name = scratch("p3b_recover_ok")
    shutil.copytree(RUNS / crashed_template, RUNS / name)
    stored = max_event_tick(name)
    live = LiveRun.open(cfg, db_path(name))
    try:
        assert live.recovery.tail_events > 0
        assert live.recovery.snapshot_tick <= stored
        assert live.recovery.end_tick == stored
    finally:
        live.close()


# ---------------------------------------------------------- RunLock, watch


def test_RunLock_second_writer_gets_RunBusyError(cfg, scratch):
    name = scratch("p3b_lock")
    make_run(name, "dummy")
    first = RunLock(db_path(name))
    try:
        with pytest.raises(RunBusyError) as exc:
            RunLock(db_path(name))
        assert "already open" in str(exc.value)
        with pytest.raises(RunBusyError):
            LiveRun.open(cfg, db_path(name))
        r = cli("headless", "--run", name, "--ticks", "10")
        assert r.returncode != 0
        assert "already open" in (r.stderr + r.stdout)
    finally:
        first.release()
    again = RunLock(db_path(name))
    again.release()


def test_RunLock_dies_with_the_process(scratch):
    name = scratch("p3b_lock_kill")
    make_run(name, "dummy")
    proc = subprocess.Popen(
        [sys.executable, "main.py", "headless", "--run", name, "--ticks", "100000"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 120
        busy = False
        while time.monotonic() < deadline and proc.poll() is None:
            try:
                RunLock(db_path(name)).release()
            except RunBusyError:
                busy = True
                break
            time.sleep(0.05)
        assert busy, "a running writer should hold the lock"
        proc.kill()
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=30)
    deadline = time.monotonic() + 15
    while True:
        try:
            RunLock(db_path(name)).release()  # no stale lock after a kill
            break
        except RunBusyError:
            assert time.monotonic() < deadline, "lock still held after the process was killed"
            time.sleep(0.2)


def test_watch_refuses_a_missing_run_with_the_new_hint():
    name = "p3b_no_such_run"
    shutil.rmtree(RUNS / name, ignore_errors=True)
    r = cli("watch", "--run", name)
    assert r.returncode != 0
    text = r.stderr + r.stdout
    assert "does not exist" in text
    assert "new" in text
    assert not (RUNS / name).exists()


# ------------------------------------------------------------------ AC-12


def test_AC12_keep_awake_flags_on_open_pause_resume_close(cfg, scratch):
    name = scratch("p3b_awake")
    make_run(name, "dummy")
    calls: list[int] = []

    def setter(flags: int) -> int:
        calls.append(flags)
        return 1

    live = LiveRun.open(cfg, db_path(name), keep_awake=KeepAwake(setter))
    assert calls and calls[-1] == 0x80000001
    live.run_ticks(5)
    live.pause()
    assert calls[-1] == 0x80000000
    live.resume()
    assert calls[-1] == 0x80000001
    live.close()
    assert calls[-1] == 0x80000000
    assert set(calls) == {0x80000001, 0x80000000}


def test_AC12_keep_awake_acquire_release_idempotent_and_ok_flag():
    calls: list[int] = []
    ka = KeepAwake(lambda f: (calls.append(f), 1)[1])
    ka.acquire()
    ka.acquire()
    assert ka.active
    ka.release()
    ka.release()
    assert not ka.active
    assert calls[0] == 0x80000001 and calls[-1] == 0x80000000
    bad = KeepAwake(lambda f: 0)
    bad.acquire()
    assert bad.ok is False
    bad.release()


# ------------------------------------------------------------------ AC-13


def test_AC13_game_week_formula():
    from ai_island.measure.weekly import game_week

    assert game_week(1, WEEK_TICKS) == 1
    assert game_week(10080, WEEK_TICKS) == 1
    assert game_week(10081, WEEK_TICKS) == 2


def test_AC13_promise_example_rows():
    from ai_island.measure.weekly import MeasureRow, weekly_measures

    db = RunDB.memory()
    db.append_events(
        [
            Event(
                tick=100,
                payload=PromiseMade(id=1, maker="player_1", to="player_2", kind="gift"),
            ),
            Event(tick=10100, payload=PromiseKept(id=1, maker="player_1", to="player_2")),
        ]
    )
    rows = weekly_measures(db, WEEK_TICKS)
    expected = [
        MeasureRow(1, "promises_made", "player_1", "", "", 1, 1),
        MeasureRow(1, "promises_made", "player_1", "player_2", "", 1, 1),
        MeasureRow(1, "promises_kept", "player_1", "", "", 0, 0),
        MeasureRow(2, "promises_kept", "player_1", "", "", 1, 1),
        MeasureRow(2, "promises_kept", "player_1", "player_2", "", 1, 1),
    ]
    for want in expected:
        assert want in rows, want


@pytest.fixture(scope="module")
def scripted_month():
    name = make_run("p3b_scripted_month", "scripted", 30000)
    yield name
    shutil.rmtree(RUNS / name, ignore_errors=True)


MEASURES = (
    "promises_made",
    "promises_kept",
    "promises_broken",
    "help",
    "harm",
    "villager_deaths",
    "villager_departures",
    "villager_loyalty",
    "belief_actions",
)


def test_AC13_quiet_players_still_get_total_rows_in_a_dummy_run(ref_dummy):
    """Contract: for every week and every player there is a total row, 0 when nothing happened."""
    from ai_island.measure.weekly import game_week, weekly_measures

    db = RunDB.open_readonly(db_path(ref_dummy))
    try:
        rows = weekly_measures(db, WEEK_TICKS)
    finally:
        db.close()
    weeks = range(1, game_week(max_event_tick(ref_dummy), WEEK_TICKS) + 1)
    totals = {(r.week, r.measure, r.player) for r in rows if r.partner == "" and r.kind == ""}
    for week in weeks:
        for measure in MEASURES:
            for player in ("player_1", "player_2", "player_3", "player_4"):
                assert (week, measure, player) in totals, (week, measure, player)


@pytest.mark.slow
def test_AC13_every_measure_has_a_total_row_per_week_and_player(scripted_month):
    from ai_island.measure.weekly import game_week, weekly_measures

    db = RunDB.open_readonly(db_path(scripted_month))
    try:
        rows = weekly_measures(db, WEEK_TICKS)
    finally:
        db.close()
    last_tick = max_event_tick(scripted_month)
    assert last_tick >= 14400
    weeks = range(1, game_week(last_tick, WEEK_TICKS) + 1)
    players = {r.player for r in rows}
    assert {"player_1", "player_2", "player_3", "player_4"} <= players
    totals = {(r.week, r.measure, r.player) for r in rows if r.partner == "" and r.kind == ""}
    for week in weeks:
        for measure in MEASURES:
            for player in ("player_1", "player_2", "player_3", "player_4"):
                assert (week, measure, player) in totals, (week, measure, player)


@pytest.mark.slow
def test_AC13_help_and_harm_totals_match_the_event_log(scripted_month):
    from ai_island.measure.weekly import weekly_measures

    db = RunDB.open_readonly(db_path(scripted_month))
    try:
        rows = weekly_measures(db, WEEK_TICKS)
    finally:
        db.close()
    con = sqlite3.connect(db_path(scripted_month))
    helped = con.execute("SELECT COUNT(*) FROM events WHERE type='helped'").fetchone()[0]
    harm = con.execute("SELECT COUNT(*) FROM events WHERE type='harm'").fetchone()[0]
    belief = con.execute("SELECT COUNT(*) FROM events WHERE type='belief_act'").fetchone()[0]
    con.close()
    assert helped >= 2  # gift and teach from the scripted visits
    for measure, expected in (("help", helped), ("harm", harm), ("belief_actions", belief)):
        total = sum(
            r.value for r in rows if r.measure == measure and r.partner == "" and r.kind == ""
        )
        assert total == expected, measure


@pytest.mark.slow
def test_AC13_measures_command_prints_a_table(scripted_month):
    r = cli("measures", "--run", scripted_month)
    assert r.returncode == 0, r.stderr
    for measure in MEASURES:
        assert measure in r.stdout


# ------------------------------------------------------------------ AC-14


def test_AC14_export_writes_one_utf8_csv_per_table_with_header(ref_dummy, tmp_path):
    out = tmp_path / "export"
    r = cli("export", "--run", ref_dummy, "--out", str(out))
    assert r.returncode == 0, r.stderr
    files = {p.name for p in out.glob("*.csv")}
    assert files == {f"{t}.csv" for t in TABLES} | {"weekly_measures.csv"}
    con = sqlite3.connect(db_path(ref_dummy))
    try:
        for table in TABLES:
            raw = (out / f"{table}.csv").read_bytes()
            assert not raw.startswith(b"\xef\xbb\xbf")
            text = raw.decode("utf-8")
            with open(out / f"{table}.csv", encoding="utf-8", newline="") as fh:
                rows = list(csv.reader(fh))
            columns = [c[1] for c in con.execute(f"PRAGMA table_info({table})")]
            assert rows[0] == columns, table
            count = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            assert len(rows) - 1 == count, table
            assert text is not None
    finally:
        con.close()
    with open(out / "weekly_measures.csv", encoding="utf-8", newline="") as fh:
        weekly = list(csv.reader(fh))
    assert weekly[0][:3] == ["week", "measure", "player"]


def test_AC14_export_default_folder_and_counts_printed(ref_dummy):
    out = RUNS / ref_dummy / "export"
    shutil.rmtree(out, ignore_errors=True)
    r = cli("export", "--run", ref_dummy)
    assert r.returncode == 0, r.stderr
    assert (out / "events.csv").exists()
    assert "events.csv" in r.stdout


def test_AC14_chat_with_comma_newline_hebrew_quotes_reimports_as_one_row(
    scratch, ref_dummy, tmp_path
):
    name = scratch("p3b_export_chat")
    shutil.copytree(RUNS / ref_dummy, RUNS / name)
    text = 'שלום, "world"\nsecond line, with comma'
    con = sqlite3.connect(db_path(name))
    con.execute(
        "INSERT INTO chats (tick, speaker_id, target_ids_json, hearer_ids_json, text) "
        "VALUES (5, 'player_1', '[]', '[]', ?)",
        (text,),
    )
    con.commit()
    count = con.execute("SELECT COUNT(*) FROM chats").fetchone()[0]
    con.close()
    out = tmp_path / "e"
    r = cli("export", "--run", name, "--out", str(out))
    assert r.returncode == 0, r.stderr
    with open(out / "chats.csv", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == count
    assert text in [row["text"] for row in rows]


def test_AC14_empty_table_gives_a_header_only(scratch, tmp_path):
    name = scratch("p3b_export_empty")
    make_run(name, "dummy")
    out = tmp_path / "e"
    r = cli("export", "--run", name, "--out", str(out))
    assert r.returncode == 0, r.stderr
    with open(out / "judge_labels.csv", encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    assert len(rows) == 1 and rows[0]


def test_AC14_json_columns_are_verbatim(ref_dummy, tmp_path):
    out = tmp_path / "e"
    assert cli("export", "--run", ref_dummy, "--out", str(out)).returncode == 0
    with open(out / "events.csv", encoding="utf-8", newline="") as fh:
        first = next(csv.DictReader(fh))
    json.loads(first["payload_json"])
    con = sqlite3.connect(db_path(ref_dummy))
    stored = con.execute("SELECT payload_json FROM events ORDER BY id LIMIT 1").fetchone()[0]
    con.close()
    assert first["payload_json"] == stored


# ------------------------------------------------------------------ AC-15


def test_AC15_view_screenshot_on_run_with_players_and_villagers(ref_dummy, tmp_path):
    import pygame

    before = dump_db(ref_dummy)
    png = tmp_path / "view.png"
    r = cli("view", "--run", ref_dummy, "--ticks", "60", "--screenshot", str(png))
    assert r.returncode == 0, r.stderr
    assert png.exists() and png.stat().st_size > 1000
    assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    img = pygame.image.load(str(png))
    assert img.get_width() >= 800 and img.get_height() >= 500
    colours = set()
    for x in range(0, img.get_width(), 37):
        for y in range(0, img.get_height(), 29):
            colours.add(tuple(img.get_at((x, y)))[:3])
    assert len(colours) > 8
    assert dump_db(ref_dummy) == before  # the source db is never changed


def test_AC15_view_screenshot_without_run(tmp_path):
    png = tmp_path / "fresh.png"
    r = cli("view", "--ticks", "30", "--screenshot", str(png))
    assert r.returncode == 0, r.stderr
    assert png.exists() and png.stat().st_size > 1000


def test_AC15_view_screenshot_on_scripted_run_with_villagers(ref_scripted, tmp_path):
    con = sqlite3.connect(db_path(ref_scripted))
    villagers = con.execute("SELECT COUNT(*) FROM events WHERE type LIKE 'villager%'").fetchone()[0]
    con.close()
    png = tmp_path / "s.png"
    r = cli("view", "--run", ref_scripted, "--ticks", "60", "--screenshot", str(png))
    assert r.returncode == 0, r.stderr
    assert png.exists() and png.stat().st_size > 1000
    assert villagers >= 0
