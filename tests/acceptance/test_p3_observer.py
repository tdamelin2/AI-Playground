"""Phase 3 AC-1 .. AC-9: the observer window, its tabs and the pause controls.

Written from the Plan's acceptance criteria and Contract only.
"""

from __future__ import annotations

import dataclasses
import json
import re
import shutil
import sqlite3
import time
import tomllib
from pathlib import Path

import pytest

from ai_island.sim import Simulation
from ai_island.storage.db import RunDB
from ai_island.storage.events import (
    Died,
    Event,
    Harm,
    LandClaimed,
    SeasonChanged,
    WeatherChanged,
)
from ai_island.world.view import (
    AgentView,
    PlayerPanel,
    StructureView,
    frame_from_world,
)
from conftest import ROOT, RUNS, cli, fresh_run

TAB_NAMES = ("Chats", "Choice points", "World history", "Players", "Spend")
ELEMENT_KEYS = (
    "tab_chats",
    "tab_choice_points",
    "tab_world_history",
    "tab_players",
    "tab_spend",
    "top_clock",
    "top_day_season",
    "top_pause",
    "top_speed_down",
    "top_speed_label",
    "top_speed_up",
    "top_spend_warning",
    "top_autosave",
    "page_older",
    "page_newer",
)


# ------------------------------------------------------------------ helpers


def when(tick: int) -> str:
    day = tick // 1440 + 1
    rem = tick % 1440
    return f"D{day} {rem // 60:02d}:{rem % 60:02d}"


def make_obs(cfg, db=None, controls=None, view=None):
    import pygame

    pygame.quit()
    from ai_island.observer import Observer

    return Observer(cfg.assets, view or cfg.run.view, ROOT, db, controls)


def memory_controls(cfg):
    from ai_island.storage.run_control import MemoryControls

    return MemoryControls(cfg.run)


def sql(db: RunDB, query: str, params: tuple = ()):
    con = sqlite3.connect(db.path, timeout=10)
    try:
        con.execute(query, params)
        con.commit()
    finally:
        con.close()


@pytest.fixture(autouse=True)
def _dummy_driver(monkeypatch):
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    yield
    import pygame

    pygame.quit()


@pytest.fixture(scope="module")
def base_frame(cfg):
    sim = Simulation.new(cfg, 1, players="none")
    return frame_from_world(sim)


@pytest.fixture(scope="module")
def dummy_run(cfg):
    """A short run with four rule-based players on an in-memory database."""
    sim = Simulation.new(cfg, 1, players="dummy")
    db = RunDB.memory()
    sim.attach(db)
    sim.save()
    sim.run(2000)
    sim.flush()
    frame = frame_from_world(sim)
    yield sim, db, frame
    db.close()


@pytest.fixture
def file_db(tmp_path):
    db = RunDB.create(tmp_path / "run.db")
    yield db
    db.close()


def lines(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.strip()]


def all_page_text(obs, tab: str) -> list[str]:
    out: list[str] = []
    for idx in range(obs.page_count(tab) - 1, -1, -1):
        obs.show_page(tab, idx)
        out += lines(obs.tab_text(tab))
    obs.show_page(tab, 0)
    return out


# ------------------------------------------------------------------ AC-1


def test_AC1_five_tabs_and_every_top_bar_element(cfg, base_frame):
    obs = make_obs(cfg, RunDB.memory(), memory_controls(cfg))
    assert tuple(obs.tab_names) == TAB_NAMES
    for key in ELEMENT_KEYS:
        assert key in obs.elements, key
    obs.draw(base_frame, 0.0)
    assert obs.top_bar_rect.width > 0 and obs.panel_rect.width > 0 and obs.map_rect.width > 0


def test_AC1_top_bar_initial_texts(cfg, base_frame):
    obs = make_obs(cfg, RunDB.memory(), memory_controls(cfg))
    obs.draw(base_frame, 0.0)
    el = obs.elements
    assert el["top_clock"].text == "00:00"
    assert el["top_day_season"].text == "Year 1, Spring, week 1, day 1"
    assert el["top_pause"].text == "Pause"
    assert el["top_speed_label"].text == "x1"
    assert el["top_spend_warning"].text == "Spend OK"
    assert el["top_autosave"].text.startswith("Not saved yet")


def test_AC1_uses_the_monogram_font(cfg):
    obs = make_obs(cfg)
    assert isinstance(obs.font_path, Path)
    assert obs.font_path.name == "monogram.ttf"
    assert obs.font_path.is_file()
    assert obs.font_path.read_bytes()[:4] in (b"\x00\x01\x00\x00", b"true", b"OTTO")


def test_AC1_missing_font_names_the_path(cfg):
    bad = "assets/fonts/nope/missing_font_xyz.ttf"
    view = cfg.run.view.model_copy(update={"font_path": bad})
    with pytest.raises(Exception) as exc:
        make_obs(cfg, view=view)
    assert "missing_font_xyz.ttf" in str(exc.value)


def test_AC1_layout_at_ui_scale_1(cfg):
    obs = make_obs(cfg)
    if obs.map_rect.top != 48:
        pytest.skip("ui scale is not 1 on this desktop")
    assert tuple(obs.top_bar_rect) == (0, 0, 1280, 48)
    assert tuple(obs.panel_rect) == (800, 48, 480, 752)
    assert tuple(obs.map_rect) == (0, 48, 800, 752)


def test_AC1_page_count_is_one_for_empty_tabs(cfg, base_frame):
    obs = make_obs(cfg, RunDB.memory(), memory_controls(cfg))
    obs.draw(base_frame, 0.0)
    assert obs.page_count("Chats") == 1
    with pytest.raises((ValueError, KeyError)):
        obs.select_tab("Nonsense")


# ------------------------------------------------------------------ AC-2


def _live_run(cfg, name):
    from ai_island.storage.run_control import LiveRun

    fresh_run(name)
    r = cli("new", name, "--players", "dummy")
    assert r.returncode == 0, r.stderr
    return LiveRun.open(cfg, RUNS / name / "run.db")


def _frame_loop(cfg, live, obs, seconds):
    view = cfg.run.view
    frame_s = 1.0 / view.fps
    start = last = time.monotonic()
    frames = 0
    while time.monotonic() - start < seconds:
        t0 = time.monotonic()
        assert obs.pump()
        live.advance(min(t0 - last, 0.1))
        last = t0
        live.flush()
        obs.draw(frame_from_world(live.sim), live.sub_tick)
        frames += 1
        time.sleep(max(0.0, frame_s - (time.monotonic() - t0)))
    return frames / (time.monotonic() - start)


def test_AC2_frame_rate_about_30_at_x1_and_at_max_speed(cfg):
    name = "acc_p3_ac2_fps"
    live = _live_run(cfg, name)
    obs = make_obs(cfg, live.db, live)
    try:
        slow = _frame_loop(cfg, live, obs, 2.0)
        assert slow >= 24, slow
        assert obs.fps >= 24, obs.fps
        live.set_speed(cfg.run.view.max_speed)
        t_before = live.sim.world.tick
        fast = _frame_loop(cfg, live, obs, 2.0)
        assert live.sim.world.tick > t_before
        assert fast >= 24, fast
        assert obs.fps >= 24, obs.fps
    finally:
        obs.close()
        live.close()
        shutil.rmtree(RUNS / name, ignore_errors=True)


def test_AC2_observer_code_calls_no_world_changing_function():
    src_dir = ROOT / "src" / "ai_island" / "observer"
    forbidden = re.compile(
        r"\.(run|step|save|save_checkpoint|append_events|save_snapshot|flush|attach|emit|"
        r"execute|executemany|executescript|commit|advance|run_ticks|pause|resume|close_run)\s*\("
        r"|\b(INSERT|UPDATE|DELETE)\s+(INTO|FROM)?|sim\.\w+\s*=[^=]|world\.\w+\s*=[^=]"
    )
    hits = []
    ctl_calls: set[str] = set()
    for path in src_dir.glob("*.py"):
        for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#")[0].replace("pygame.image.save(", "")
            m = forbidden.search(code)
            if m and "close()" not in code:
                hits.append(f"{path.name}:{no}: {line.strip()}")
            for call in re.findall(r"(?:ctl|controls|_controls)\.(\w+)\s*\(", code):
                ctl_calls.add(call)
    assert not hits, hits
    assert ctl_calls <= {"toggle_pause", "set_speed"}, ctl_calls
    assert ctl_calls, "the observer should call controls.toggle_pause / set_speed"


# ------------------------------------------------------------------ AC-3


def test_AC3_chats_tab_shows_every_chat_row_with_hearers(cfg, dummy_run):
    sim, db, frame = dummy_run
    rows = db.chats_page(None, 100000)
    assert len(rows) >= 5, "the dummy run should chat"
    assert db.count("chats") == len(rows)
    obs = make_obs(cfg, db, memory_controls(cfg))
    obs.draw(frame, 0.0)
    names = dict(frame.names)
    shown = all_page_text(obs, "Chats")
    assert len(shown) == len(rows)
    for row, line in zip(rows, shown, strict=True):
        assert line.startswith(when(row.tick)), line
        assert row.text in line
        who = ", ".join(names.get(h, h) for h in row.hearers) or "nobody"
        assert line.endswith(f"| heard: {who}"), (line, who)


def test_AC3_chat_line_format_with_and_without_targets(cfg, base_frame, file_db):
    sql(
        file_db,
        "INSERT INTO chats (tick, speaker_id, target_ids_json, hearer_ids_json, text) "
        "VALUES (495, 'player_1', '[\"player_2\"]', "
        "'[\"player_2\", \"player_3\"]', 'Good morning')",
    )
    sql(
        file_db,
        "INSERT INTO chats (tick, speaker_id, target_ids_json, hearer_ids_json, text) "
        "VALUES (500, 'player_2', '[]', '[]', 'Shalom, \"quoted\" & <b>')",
    )
    obs = make_obs(cfg, file_db, memory_controls(cfg))
    obs.draw(base_frame, 0.0)
    got = lines(obs.tab_text("Chats"))
    assert got == [
        "D1 08:15 player_1 -> player_2: Good morning | heard: player_2, player_3",
        'D1 08:20 player_2: Shalom, "quoted" & <b> | heard: nobody',
    ]


def test_AC3_chats_use_names_and_page_through_every_line(cfg, base_frame, file_db):
    for i in range(250):
        sql(
            file_db,
            "INSERT INTO chats (tick, speaker_id, target_ids_json, hearer_ids_json, text) "
            "VALUES (?, 'player_1', '[]', '[\"player_2\"]', ?)",
            (i, f"line number {i}"),
        )
    frame = dataclasses.replace(base_frame, names=(("player_1", "Ana"), ("player_2", "Ben")))
    obs = make_obs(cfg, file_db, memory_controls(cfg))
    obs.draw(frame, 0.0)
    assert obs.page_count("Chats") >= 3
    shown = all_page_text(obs, "Chats")
    assert len(shown) == 250
    assert shown[0].endswith("Ana: line number 0 | heard: Ben")
    assert shown[-1].endswith("Ana: line number 249 | heard: Ben")
    obs.show_page("Chats", 0)
    assert "line number 249" in obs.tab_text("Chats")


def test_AC3_new_chats_appear_while_drawing(cfg, base_frame, file_db):
    obs = make_obs(cfg, file_db, memory_controls(cfg))
    obs.draw(base_frame, 0.0)
    assert lines(obs.tab_text("Chats")) == []
    sql(
        file_db,
        "INSERT INTO chats (tick, speaker_id, target_ids_json, hearer_ids_json, text) "
        "VALUES (10, 'player_1', '[]', '[]', 'later line')",
    )
    obs.draw(base_frame, 0.0)
    assert any("later line" in ln for ln in lines(obs.tab_text("Chats")))


# ------------------------------------------------------------------ AC-4


def _harm(i, kind="steal"):
    return Harm(id=i, kind=kind, actor="player_1", victim="player_2", x=1, y=1)


def test_AC4_history_tab_lists_major_kinds_in_time_order(cfg, base_frame, file_db):
    from ai_island.measure.history import HISTORY_TYPES, history_entries

    events = [
        Event(tick=100, payload=SeasonChanged(season="summer", year=1)),
        Event(tick=3255, payload=_harm(1)),
        Event(tick=3300, payload=Died(player="player_1", cause="hunger", x=3, y=4)),
        Event(tick=3400, payload=WeatherChanged(weather="clear", previous="rain", season="spring")),
        Event(
            tick=3500, payload=WeatherChanged(weather="storm", previous="clear", season="spring")
        ),
        Event(tick=3600, payload=LandClaimed(player="player_2", x=5, y=6, tiles=4)),
        Event(tick=3700, payload=_harm(2, "attack")),
        Event(tick=3800, payload=_harm(3, "sabotage")),
    ]
    file_db.append_events(events)
    names = {"player_1": "Ana", "player_2": "Ben"}
    expected = history_entries(file_db.events_after(0, tuple(HISTORY_TYPES)), names)
    kinds = [r.kind for r in expected]
    assert kinds == [
        "season_change",
        "theft",
        "death",
        "storm",
        "land_claim",
        "attack",
    ]
    frame = dataclasses.replace(base_frame, names=tuple(names.items()))
    obs = make_obs(cfg, file_db, memory_controls(cfg))
    obs.draw(frame, 0.0)
    shown = all_page_text(obs, "World history")
    assert shown == [f"{when(r.tick)} {r.kind}: {r.text}" for r in expected]
    assert [s.split()[2] for s in shown] == [f"{k}:" for k in kinds]


def test_AC4_history_contract_examples():
    from ai_island.measure.history import HistoryRow, history_entries

    ev = Event(tick=3255, payload=_harm(1))
    got = history_entries([(7, ev)], {"player_1": "Ana", "player_2": "Ben"})
    # Phase 3.5 added defaulted who / x / y to HistoryRow (kind, text and order are unchanged).
    assert got == [
        HistoryRow(7, 3255, "theft", "Ana stole from Ben", who=("player_1", "player_2"), x=1, y=1)
    ]
    assert [(r.event_id, r.tick, r.kind, r.text) for r in got] == [
        (7, 3255, "theft", "Ana stole from Ben")
    ]
    assert HistoryRow(1, 2, "storm", "t") == HistoryRow(1, 2, "storm", "t", (), -1, -1)
    evs = [
        (10, Event(tick=5, payload=Died(player="player_1", cause="x", x=1, y=1))),
        (
            11,
            Event(tick=6, payload=WeatherChanged(weather="clear", previous=None, season="spring")),
        ),
        (
            12,
            Event(
                tick=7, payload=WeatherChanged(weather="storm", previous="clear", season="spring")
            ),
        ),
        (13, Event(tick=8, payload=LandClaimed(player="player_1", x=1, y=1, tiles=1))),
    ]
    assert [r.event_id for r in history_entries(evs, {})] == [10, 12, 13]


def test_AC4_history_tab_matches_event_log_of_a_real_run(cfg, dummy_run):
    from ai_island.measure.history import HISTORY_TYPES

    sim, db, frame = dummy_run
    obs = make_obs(cfg, db, memory_controls(cfg))
    obs.draw(frame, 0.0)
    shown = all_page_text(obs, "World history")
    wanted = [
        (i, e)
        for i, e in db.events_after(0, tuple(HISTORY_TYPES))
        if not (e.type == "weather_changed" and e.payload.weather in ("clear", "rain"))
        and not (e.type == "harm" and e.payload.kind not in ("steal", "attack"))
    ]
    assert len(shown) == len(wanted)
    ticks = [e.tick for _i, e in wanted]
    assert ticks == sorted(ticks)
    for line, (_i, e) in zip(shown, wanted, strict=True):
        assert line.startswith(when(e.tick)), line


# ------------------------------------------------------------------ AC-5


def _panels():
    p1 = PlayerPanel(
        id="player_1",
        name="Ana",
        index=1,
        alive=True,
        feeling="You feel all right",
        x=72.44,
        hooked=False,
        trust=(("player_2", 65.0),),
        anger=(("player_2", 10.0),),
    )
    p2 = PlayerPanel(
        id="player_2",
        name="Ben",
        index=2,
        alive=True,
        feeling="You feel hungry",
        x=40.0,
        hooked=True,
        trust=(("player_1", 30.4),),
        anger=(("player_1", 2.6),),
    )
    return (p1, p2)


def test_AC5_players_tab_text_grid_and_no_value_table(cfg, base_frame, file_db):
    frame = dataclasses.replace(
        base_frame,
        names=(("player_1", "Ana"), ("player_2", "Ben")),
        panels=_panels(),
    )
    obs = make_obs(cfg, file_db, memory_controls(cfg))
    obs.draw(frame, 0.0)
    text = obs.tab_text("Players")
    assert "Ana (player_1) alive | You feel all right | X 72.4 | hooked: no" in text
    assert "Ben (player_2) alive | You feel hungry | X 40.0 | hooked: yes" in text
    assert text.count("values: none (no value table)") == 2
    assert "65/10" in text
    assert "30/3" in text
    rows = [ln for ln in lines(text) if ln.startswith("Ana:") or ln.startswith("Ben:")]
    assert len(rows) == 2
    assert "-" in rows[0] and "65/10" in rows[0]
    assert "-" in rows[1] and "30/3" in rows[1]


def test_AC5_player_with_a_value_table_is_not_shown_as_none(cfg, base_frame, file_db):
    sql(
        file_db,
        "INSERT INTO value_history (tick, player_id, game_week, value_id, old_weight, "
        "new_weight, cause_event_ids_json) VALUES (10, 'player_2', 1, 'honesty', NULL, 0.75, '[]')",
    )
    frame = dataclasses.replace(
        base_frame, names=(("player_1", "Ana"), ("player_2", "Ben")), panels=_panels()
    )
    obs = make_obs(cfg, file_db, memory_controls(cfg))
    obs.draw(frame, 0.0)
    text = obs.tab_text("Players")
    assert text.count("values: none (no value table)") == 1
    assert re.search(r"values \(\* = core\): honesty\* 0\.75", text)


def test_AC5_players_tab_on_a_real_run_has_all_four_players(cfg, dummy_run):
    sim, db, frame = dummy_run
    obs = make_obs(cfg, db, memory_controls(cfg))
    obs.draw(frame, 0.0)
    text = obs.tab_text("Players")
    for i in range(1, 5):
        assert f"(player_{i})" in text
    assert text.count("hooked:") == 4
    assert text.count("values: none (no value table)") == 4


# ------------------------------------------------------------------ AC-6


def _insert_choice(db, tick=495, player="player_1", sit="Hungry at the lake"):
    sql(
        db,
        "INSERT INTO choice_points (tick, player_id, situation, x, feeling, tier, thought, "
        "action_json, self_label_json) VALUES (?, ?, ?, 50.0, 'ok', 'routine', 'hmm', "
        '\'{"kind": "eat"}\', '
        '\'{"served": ["honesty"], "violated": [], "direction": "toward"}\')',
        (tick, player, sit),
    )


def test_AC6_choice_points_tab_shows_rows_with_pending_judge(cfg, base_frame, file_db):
    _insert_choice(file_db)
    frame = dataclasses.replace(base_frame, names=(("player_1", "Ana"),))
    obs = make_obs(cfg, file_db, memory_controls(cfg))
    obs.draw(frame, 0.0)
    rows = lines(obs.tab_text("Choice points"))
    assert len(rows) == 1
    # Phase 4 shape: action in words, self-label once as "served: ..; violated: ..; direction"
    assert re.fullmatch(
        r"D1 08:15 Ana \[routine\] Hungry at the lake \| eat \| "
        r"served: honesty; violated: \w+; toward \| feeling: ok \| judge: pending",
        rows[0],
    ), rows[0]


def test_AC6_empty_for_a_rule_based_run(cfg, dummy_run):
    sim, db, frame = dummy_run
    obs = make_obs(cfg, db, memory_controls(cfg))
    obs.draw(frame, 0.0)
    assert obs.tab_text("Choice points") == "No choice points yet."


def test_AC6_later_judge_label_appears_on_an_existing_row_while_paused(cfg, base_frame, file_db):
    _insert_choice(file_db)
    ctl = memory_controls(cfg)
    ctl.toggle_pause()
    assert ctl.paused
    obs = make_obs(cfg, file_db, ctl)
    obs.draw(base_frame, 0.0)
    assert lines(obs.tab_text("Choice points"))[0].endswith("judge: pending")
    sql(
        file_db,
        "INSERT INTO judge_labels (tick, choice_point_id, detail_level, label_json) "
        "VALUES (600, 1, 'full', '{\"verdict\": \"fine\"}')",
    )
    obs.draw(base_frame, 0.0)
    assert lines(obs.tab_text("Choice points"))[0].count("judge (full):") == 1
    assert "served nothing" in lines(obs.tab_text("Choice points"))[0]
    sql(
        file_db,
        "INSERT INTO judge_labels (tick, choice_point_id, detail_level, label_json) "
        "VALUES (700, 1, 'full', ?)",
        (json.dumps({"served": ["family"], "violated": [], "direction": "toward"}),),
    )
    obs.draw(base_frame, 0.0)
    newest = lines(obs.tab_text("Choice points"))[0]
    assert "judge (full):" in newest and "served Family" in newest


# ------------------------------------------------------------------ AC-7


def _spend(db, tick, cost, cumulative):
    sql(
        db,
        "INSERT INTO spend (tick, role, cost_usd, cumulative_usd) VALUES (?, 'player', ?, ?)",
        (tick, cost, cumulative),
    )


def test_AC7_spend_tab_shows_table_total_and_cap(cfg, base_frame, file_db):
    _spend(file_db, 100, 0.1, 0.1)
    _spend(file_db, 200, 0.2, 0.3)
    cap = cfg.run.spend_cap_usd
    obs = make_obs(cfg, file_db, memory_controls(cfg))
    obs.draw(base_frame, 0.0)
    got = lines(obs.tab_text("Spend"))
    assert got[0] == f"Spent $0.30 of ${cap:.2f} cap ({100 * 0.3 / cap:.1f}%)"
    assert got[1] == f"Remaining ${cap - 0.3:.2f}"
    assert "Week 1: $0.30" in got


def test_AC7_spend_tab_weeks_split(cfg, base_frame, file_db):
    _spend(file_db, 100, 0.1, 0.1)
    _spend(file_db, 10081, 0.25, 0.35)
    obs = make_obs(cfg, file_db, memory_controls(cfg))
    obs.draw(base_frame, 0.0)
    got = lines(obs.tab_text("Spend"))
    assert "Week 1: $0.10" in got
    assert "Week 2: $0.25" in got


def test_AC7_rule_based_run_shows_zero_dollars(cfg, dummy_run):
    sim, db, frame = dummy_run
    obs = make_obs(cfg, db, memory_controls(cfg))
    obs.draw(frame, 0.0)
    first = lines(obs.tab_text("Spend"))[0]
    assert first.startswith("Spent $0.00 of $")
    assert first.endswith("(0.0%)")
    assert f"${cfg.run.spend_cap_usd:.2f} cap" in first


def test_AC7_cap_comes_from_run_toml():
    raw = (ROOT / "config" / "run.toml").read_text(encoding="utf-8-sig")
    assert tomllib.loads(raw)["spend_cap_usd"] == 100.0


@pytest.mark.parametrize(
    "spent,text",
    [
        (80.0, "SPEND WARNING: 80% of cap"),
        (79.99, "Spend OK"),
        (100.0, "SPEND WARNING: 80% of cap"),
        (0.0, "Spend OK"),
    ],
)
def test_AC7_top_bar_spend_warning_threshold(cfg, base_frame, spent, text):
    ctl = memory_controls(cfg)
    ctl.spend_cap_usd = 100.0
    ctl.spend_usd = spent
    obs = make_obs(cfg, RunDB.memory(), ctl)
    obs.draw(base_frame, 0.0)
    assert obs.elements["top_spend_warning"].text == text


# ------------------------------------------------------------------ AC-8


def _kinds():
    raw = (ROOT / "config" / "assets.toml").read_text(encoding="utf-8-sig")
    items = tomllib.loads(raw)["items"]
    return sorted(
        k[len("damaged_") :] for k in items if k.startswith("damaged_") and k[8:] in items
    )


def _grid(frame, step=4):
    return [(x, y) for y in range(0, frame.height, step) for x in range(0, frame.width, step)]


def _shot(obs, frame):
    import pygame

    obs.draw(frame, 0.0)
    return pygame.image.tobytes(pygame.display.get_surface().subsurface(obs.map_rect).copy(), "RGB")


def _structs(frame, kind, key=None, complete=True, progress=1.0, hp=100):
    return tuple(
        StructureView(
            id=i,
            kind=kind,
            x=x,
            y=y,
            owner_index=1,
            complete=complete,
            progress=progress,
            hp=hp,
            max_hp=100,
            sprite_key=key or kind,
        )
        for i, (x, y) in enumerate(_grid(frame), 1)
    )


def test_AC8_sprite_key_threshold_from_a_real_world(cfg):
    from ai_island.world.agents import Structure

    sim = Simulation.new(cfg, 1, players="dummy")
    share = cfg.balance.buildings.damaged_share
    assert share == 0.5
    for sid, hp, complete, _expect in [
        (9001, 49, True, "damaged_house"),
        (9002, 50, True, "house"),
        (9003, 100, True, "house"),
        (9004, 10, False, "house"),
    ]:
        sim.world.structures[sid] = Structure(
            id=sid, kind="house", x=3, y=3, owner="player_1", hp=hp, max_hp=100, complete=complete
        )
    views = {v.id: v for v in frame_from_world(sim).structures}
    for sid, hp, complete, expect in [
        (9001, 49, True, "damaged_house"),
        (9002, 50, True, "house"),
        (9003, 100, True, "house"),
        (9004, 10, False, "house"),
    ]:
        assert views[sid].sprite_key == expect, (sid, hp)
        assert views[sid].complete is complete
    ids = [v.id for v in frame_from_world(sim).structures]
    assert ids == sorted(ids)


def test_AC8_every_building_kind_is_drawn_and_has_a_damaged_look(cfg, base_frame):
    kinds = _kinds()
    assert len(kinds) >= 8, kinds
    obs = make_obs(cfg, RunDB.memory(), memory_controls(cfg))
    blank = _shot(obs, base_frame)
    for kind in kinds:
        whole = _shot(obs, dataclasses.replace(base_frame, structures=_structs(base_frame, kind)))
        assert whole != blank, f"{kind} is not drawn"
        hurt = _shot(
            obs,
            dataclasses.replace(
                base_frame,
                structures=_structs(base_frame, kind, key=f"damaged_{kind}", hp=49),
            ),
        )
        assert hurt != whole, f"damaged_{kind} looks like {kind}"
        assert hurt != blank, f"damaged_{kind} is not drawn"


def test_AC8_unfinished_building_looks_different_from_a_finished_one(cfg, base_frame):
    obs = make_obs(cfg, RunDB.memory(), memory_controls(cfg))
    done = _shot(obs, dataclasses.replace(base_frame, structures=_structs(base_frame, "house")))
    part = _shot(
        obs,
        dataclasses.replace(
            base_frame,
            structures=_structs(base_frame, "house", complete=False, progress=0.5),
        ),
    )
    blank = _shot(obs, base_frame)
    assert part != done
    assert part != blank


def test_AC8_land_borders_are_drawn(cfg, base_frame):
    obs = make_obs(cfg, RunDB.memory(), memory_controls(cfg))
    blank = _shot(obs, base_frame)
    for owner in (1, 2, 3, 4):
        borders = tuple((x, y, owner) for x, y in _grid(base_frame))
        shot = _shot(obs, dataclasses.replace(base_frame, borders=borders))
        assert shot != blank, f"border of owner {owner} not drawn"


@pytest.mark.parametrize("marker", ["sick", "injured", "sleeping"])
def test_AC8_state_markers_are_drawn(cfg, base_frame, marker):
    def agents(markers):
        return tuple(
            AgentView(
                id=f"villager_{i}",
                kind="villager",
                owner_index=1,
                x=x,
                y=y,
                from_x=x,
                from_y=y,
                to_x=x,
                to_y=y,
                move_start_tick=0,
                move_end_tick=0,
                facing=1,
                markers=markers,
            )
            for i, (x, y) in enumerate(_grid(base_frame), 1)
        )

    obs = make_obs(cfg, RunDB.memory(), memory_controls(cfg))
    plain = _shot(obs, dataclasses.replace(base_frame, villagers=agents(())))
    marked = _shot(obs, dataclasses.replace(base_frame, villagers=agents((marker,))))
    assert marked != plain


def test_AC8_graves_are_drawn_from_died_and_villager_died_events(cfg, base_frame):
    from ai_island.storage.events import VillagerDied

    grid = _grid(base_frame)
    half = len(grid) // 2

    def with_graves(events):
        db = RunDB.memory()
        db.append_events(events)
        obs = make_obs(cfg, db, memory_controls(cfg))
        return _shot(obs, base_frame)

    none = with_graves([])
    players = with_graves(
        [
            Event(tick=5, payload=Died(player="player_1", cause="x", x=x, y=y))
            for x, y in grid[:half]
        ]
    )
    villagers = with_graves(
        [
            Event(
                tick=5,
                payload=VillagerDied(villager="villager_1", leader="player_1", cause="x", x=x, y=y),
            )
            for x, y in grid[half:]
        ]
    )
    assert players != none
    assert villagers != none


# ------------------------------------------------------------------ AC-9


def _press(key):
    import pygame

    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=key, mod=0, unicode="p", scancode=0))
    pygame.event.post(pygame.event.Event(pygame.KEYUP, key=key, mod=0, scancode=0))


def _click(obs, key):
    import pygame
    import pygame_gui

    pygame.event.post(
        pygame.event.Event(pygame_gui.UI_BUTTON_PRESSED, ui_element=obs.elements[key])
    )


def test_AC9_p_key_pauses_and_resumes_and_saves_a_snapshot(cfg):
    name = "acc_p3_ac9_key"
    live = _live_run(cfg, name)
    obs = make_obs(cfg, live.db, live)
    try:
        live.run_ticks(50)
        live.flush()
        assert live.paused is False
        _press(__import__("pygame").K_p)
        assert obs.pump()
        assert live.paused is True
        tick = live.sim.world.tick
        assert tick == 50
        assert live.db.latest_snapshot().tick == tick
        assert live.advance(30.0) == 0
        assert live.sim.world.tick == tick
        live.flush()
        assert (live.db.last_event_tick() or 0) <= tick
        obs.draw(frame_from_world(live.sim), 0.0)
        assert obs.elements["top_pause"].text == "Resume"
        _press(__import__("pygame").K_p)
        assert obs.pump()
        assert live.paused is False
        assert live.advance(5.0) > 0
        assert live.sim.world.tick > tick
        obs.draw(frame_from_world(live.sim), 0.0)
        assert obs.elements["top_pause"].text == "Pause"
    finally:
        obs.close()
        live.close()
        shutil.rmtree(RUNS / name, ignore_errors=True)


def test_AC9_pause_button_pauses_and_resumes(cfg):
    name = "acc_p3_ac9_button"
    live = _live_run(cfg, name)
    obs = make_obs(cfg, live.db, live)
    try:
        live.run_ticks(30)
        _click(obs, "top_pause")
        assert obs.pump()
        assert live.paused is True
        assert live.db.latest_snapshot().tick == live.sim.world.tick == 30
        assert live.advance(30.0) == 0
        _click(obs, "top_pause")
        assert obs.pump()
        assert live.paused is False
        assert live.advance(5.0) > 0
    finally:
        obs.close()
        live.close()
        shutil.rmtree(RUNS / name, ignore_errors=True)


def test_AC9_speed_keys_and_buttons_go_through_controls(cfg):
    import pygame

    ctl = memory_controls(cfg)
    obs = make_obs(cfg, RunDB.memory(), ctl)
    assert ctl.speed == 1
    pygame.event.post(
        pygame.event.Event(pygame.KEYDOWN, key=pygame.K_EQUALS, mod=0, unicode="=", scancode=0)
    )
    obs.pump()
    assert ctl.speed == 2
    _click(obs, "top_speed_down")
    obs.pump()
    _click(obs, "top_speed_down")
    obs.pump()
    assert ctl.speed == 0.5


def test_AC9_pause_in_view_preview_stops_only_the_preview(cfg):
    import pygame

    ctl = memory_controls(cfg)
    assert ctl.preview is True
    obs = make_obs(cfg, RunDB.memory(), ctl)
    _press(pygame.K_p)
    obs.pump()
    assert ctl.paused is True
    _press(pygame.K_p)
    obs.pump()
    assert ctl.paused is False
