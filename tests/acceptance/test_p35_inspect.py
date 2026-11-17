"""Phase 3.5 AC-9 .. AC-16: inspector, flashes, graphs, mini-map, help/screenshot, guide, safety.

Written from the Plan's acceptance criteria and Contract only. Every test uses the dummy video
driver; prefs and screenshots go to tmp_path.
"""

from __future__ import annotations

import dataclasses
import json
import sqlite3
import subprocess
import sys
import tomllib

import pytest

from ai_island.measure.series import relation_series, x_series
from ai_island.sim import Simulation
from ai_island.storage.db import RunDB, Snapshot
from ai_island.storage.events import Died, Event, Harm, LandClaimed, PlayerDay
from ai_island.world.view import frame_from_world
from conftest import ROOT, cli

PLAYERS = ("player_1", "player_2", "player_3", "player_4")


@pytest.fixture(autouse=True)
def _dummy_driver(monkeypatch):
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    yield
    import pygame

    pygame.quit()


@pytest.fixture(scope="module")
def world_pair(cfg):
    """A sim with four players and villagers, with set body/inventory values, and its frame."""
    sim = Simulation.new(cfg, 1, players="dummy")
    sim.run(600)
    w = sim.world
    p = w.players["player_1"]
    p.body.hunger, p.body.thirst, p.body.cold, p.body.fatigue = 37.4, 12.6, 5.2, 61.8
    p.body.health, p.body.pain = 88.4, 3.6
    p.inventory.add("wood", 5, w.tick)
    p.inventory.add("stone", 2, w.tick)
    alive = [v for _, v in sorted(w.villagers.items()) if v.alive]
    led = next(v for v in alive if v.leader == "player_2")
    led.loyalty = 63.4
    led.body.hunger = 21.2
    free = next(v for v in alive if v.leader != "player_2")
    free.leader = None
    return sim, frame_from_world(sim), led.id, free.id


def make_obs(cfg, db=None, controls=None, **kw):
    import pygame

    pygame.quit()
    from ai_island.observer import Observer

    return Observer(cfg.assets, cfg.run.view, ROOT, db, controls, **kw)


@pytest.fixture
def file_db(tmp_path):
    db = RunDB.create(tmp_path / "run.db")
    yield db
    db.close()


def key(k):
    import pygame

    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=k, mod=0, unicode="", scancode=0))
    pygame.event.post(pygame.event.Event(pygame.KEYUP, key=k, mod=0, scancode=0))


def click(pos, button=1):
    import pygame

    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=button))
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=pos, button=button))


def rgb(hex_text):
    h = hex_text.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


# ------------------------------------------------------------------ AC-9: inspector


def rows_dict(obs):
    rows = obs.inspector_rows()
    labels = [k for k, _ in rows]
    assert len(labels) == len(set(labels)), labels
    return dict(rows)


def test_AC9_inspector_is_empty_without_a_selection(cfg, world_pair):
    _, frame, *_ = world_pair
    obs = make_obs(cfg)
    obs.draw(frame, 0.0)
    assert obs.inspector_rows() == []


def test_AC9_selected_player_shows_every_listed_field_matching_the_world(cfg, world_pair):
    sim, frame, *_ = world_pair
    w = sim.world
    p = w.players["player_1"]
    obs = make_obs(cfg)
    obs.draw(frame, 0.0)
    obs.select("player_1")
    obs.draw(frame, 0.0)
    d = rows_dict(obs)
    for label in (
        "Name", "Village", "Activity", "Progress", "Hunger", "Thirst", "Cold", "Rest",
        "Health", "Pain", "Sickness", "Feeling", "X", "Hooked", "Items", "Tools",
    ):  # fmt: skip
        assert label in d, (label, d)
    assert d["Name"] == p.name
    assert d["Village"] == f"{p.name}'s village"
    assert d["Hunger"] == "37" and d["Thirst"] == "13" and d["Cold"] == "5"
    assert d["Rest"] == "62" and d["Health"] == "88" and d["Pain"] == "4"
    assert d["Sickness"] == (p.body.sickness or "none")
    assert d["Items"] == ", ".join(f"{k} {n}" for k, n in sorted(p.inventory.counts().items()))
    assert d["Items"] != "none" and f"stone {p.inventory.count('stone')}" in d["Items"]
    tools = ", ".join(
        f"{t.kind} {t.tier} ({t.durability})" for t in sorted(p.inventory.tools, key=lambda t: t.id)
    )
    assert d["Tools"] == (tools or "none")
    panel = next(x for x in frame.panels if x.id == "player_1")
    assert d["Feeling"] == panel.feeling
    assert d["X"] == f"{panel.x:.1f}"
    assert d["Hooked"] == ("yes" if panel.hooked else "no")
    me = next(a for a in frame.players if a.id == "player_1")
    assert d["Activity"].startswith(me.activity)
    assert d["Progress"] == f"{round(me.activity_progress * 100)}%"
    for label in ("Job", "Work level", "Loyalty", "Bond with leader"):
        assert label not in d


def test_AC9_selected_villager_shows_every_listed_field_matching_the_world(cfg, world_pair):
    sim, frame, led_id, free_id = world_pair
    w = sim.world
    v = w.villagers[led_id]
    obs = make_obs(cfg)
    obs.draw(frame, 0.0)
    obs.select(led_id)
    obs.draw(frame, 0.0)
    d = rows_dict(obs)
    for label in (
        "Name", "Village", "Activity", "Progress", "Hunger", "Thirst", "Cold", "Rest",
        "Health", "Pain", "Sickness", "Job", "Work level", "Loyalty", "Bond with leader",
    ):  # fmt: skip
        assert label in d, (label, d)
    assert d["Name"] == v.name
    assert d["Village"] == f"{w.players['player_2'].name}'s village"
    assert d["Loyalty"] == "63"
    assert d["Hunger"] == "21"
    assert d["Job"] == (v.job or "none")
    assert d["Work level"] == v.work_level
    bond = v.bond.get("player_2", cfg.balance.villagers.bond_start_other)
    assert d["Bond with leader"] == str(round(bond))
    for label in ("Feeling", "Hooked"):
        assert label not in d


def test_AC9_wanderer_village_and_bond(cfg, world_pair):
    _, frame, _, free_id = world_pair
    obs = make_obs(cfg)
    obs.draw(frame, 0.0)
    obs.select(free_id)
    obs.draw(frame, 0.0)
    d = rows_dict(obs)
    assert d["Village"] == "wanderer"
    assert d["Bond with leader"] == "none"


def test_AC9_an_extra_section_appears_with_no_layout_change(cfg, world_pair):
    from ai_island.observer.inspector import DEFAULT_SECTIONS, Section

    _, frame, *_ = world_pair
    obs = make_obs(cfg)
    obs.draw(frame, 0.0)
    obs.select("player_3")
    obs.draw(frame, 0.0)
    before = rows_dict(obs)
    rects = (obs.layout.top_bar.copy(), obs.layout.map.copy(), obs.layout.panel.copy())
    assert "Zed" not in before
    seen = []

    def rows(f, db, ident):
        seen.append(ident)
        return [("Zed", "42")]

    obs.inspector_sections.append(Section("Extra", rows))
    obs.draw(frame, 0.0)
    after = rows_dict(obs)
    assert after["Zed"] == "42" and seen and seen[-1] == "player_3"
    assert {k: v for k, v in after.items() if k != "Zed"} == before
    assert rects == (obs.layout.top_bar, obs.layout.map, obs.layout.panel)
    # the list is a per-instance copy: another observer has no extra section
    other = make_obs(cfg)
    assert len(other.inspector_sections) == len(DEFAULT_SECTIONS)


# ------------------------------------------------------------------ AC-10: flashes and J


class Clock:
    def __init__(self, t=10.0):
        self.t = t

    def __call__(self):
        return self.t


def draw_n(obs, frame, n=2):
    for _ in range(n):
        obs.draw(frame, 0.0)


def flash_obs(cfg, file_db, frame, clock):
    obs = make_obs(cfg, file_db, clock=clock)
    draw_n(obs, frame)
    return obs


def test_AC10_old_events_do_not_flash_when_the_window_opens(cfg, world_pair, file_db):
    _, frame, *_ = world_pair
    file_db.append_events(
        [
            Event(
                tick=100,
                payload=Harm(id=1, kind="steal", actor="player_2", victim="player_1", x=12, y=7),
            )
        ]
    )
    obs = flash_obs(cfg, file_db, frame, Clock())
    assert obs.active_flashes() == []


def test_AC10_logged_theft_flashes_on_its_tile_and_expires(cfg, world_pair, file_db):
    _, frame, *_ = world_pair
    clock = Clock(10.0)
    obs = flash_obs(cfg, file_db, frame, clock)
    file_db.append_events(
        [
            Event(
                tick=600,
                payload=Harm(id=1, kind="steal", actor="player_2", victim="player_1", x=12, y=7),
            )
        ]
    )
    draw_n(obs, frame)
    fl = obs.active_flashes()
    assert [(f.kind, f.x, f.y) for f in fl] == [("theft", 12, 7)]
    assert fl[0].who[:2] == ("player_2", "player_1")
    assert fl[0].until == pytest.approx(10.0 + cfg.run.view.flash_seconds)
    assert cfg.run.view.flash_seconds == 4.0
    clock.t = 13.9
    assert len(obs.active_flashes()) == 1
    clock.t = 14.0
    assert obs.active_flashes() == []


def test_AC10_attack_death_and_land_claim_each_flash_on_their_tile(cfg, world_pair, file_db):
    _, frame, *_ = world_pair
    clock = Clock()
    obs = flash_obs(cfg, file_db, frame, clock)
    file_db.append_events(
        [
            Event(
                tick=601,
                payload=Harm(id=2, kind="attack", actor="player_3", victim="player_4", x=20, y=21),
            ),
            Event(tick=602, payload=Died(player="player_4", cause="attack", x=22, y=23)),
            Event(tick=603, payload=LandClaimed(player="player_1", x=30, y=31, tiles=4)),
        ]
    )
    draw_n(obs, frame)
    got = {(f.kind, f.x, f.y) for f in obs.active_flashes()}
    assert got == {("attack", 20, 21), ("death", 22, 23), ("land_claim", 30, 31)}


def test_AC10_marker_is_drawn_on_the_tile_in_the_flash_colour(cfg, world_pair, file_db):
    import pygame

    _, frame, *_ = world_pair
    clock = Clock()
    obs = flash_obs(cfg, file_db, frame, clock)
    file_db.append_events(
        [
            Event(
                tick=600,
                payload=Harm(id=1, kind="steal", actor="player_2", victim="player_1", x=12, y=7),
            )
        ]
    )
    draw_n(obs, frame)
    obs.camera.center_on(12, 7)
    colour = rgb(cfg.assets.colors.flash)
    hits = 0
    for step in range(40):  # the frame blinks, so look over a second of clock time
        clock.t = 10.0 + step * 0.05
        obs.draw(frame, 0.0)
        sx, sy = obs.camera.world_to_screen(12, 7)
        tile = obs.camera.tile
        surf = pygame.display.get_surface()
        found = any(
            surf.get_at((x, y))[:3] == colour
            for x in range(sx, sx + tile)
            for y in (sy, sy + tile - 1, sy + 1, sy + tile - 2)
        )
        hits += found
    assert hits >= 5, hits
    clock.t = 20.0
    obs.draw(frame, 0.0)
    sx, sy = obs.camera.world_to_screen(12, 7)
    surf = pygame.display.get_surface()
    assert not any(surf.get_at((x, sy))[:3] == colour for x in range(sx, sx + obs.camera.tile)), (
        "an expired marker must not be drawn"
    )


def test_AC10_j_centres_on_the_latest_event_and_selects_who_was_involved(cfg, world_pair, file_db):
    import pygame

    _, frame, *_ = world_pair
    clock = Clock()
    obs = flash_obs(cfg, file_db, frame, clock)
    file_db.append_events(
        [
            Event(
                tick=601,
                payload=Harm(id=1, kind="steal", actor="player_2", victim="player_1", x=12, y=7),
            ),
        ]
    )
    draw_n(obs, frame)
    assert obs.selected is None
    key(pygame.K_j)
    assert obs.pump()
    assert obs.selected == "player_2"
    assert obs.following is True
    vx, vy, vw, vh = obs.camera.visible_tiles()
    assert vx <= 12 < vx + vw and vy <= 7 < vy + vh
    # after the marker expired J still works, and it picks the latest by (tick, id)
    file_db.append_events(
        [
            Event(
                tick=700,
                payload=Harm(id=2, kind="attack", actor="player_3", victim="player_4", x=40, y=41),
            )
        ]
    )
    draw_n(obs, frame)
    clock.t = 99.0
    assert obs.active_flashes() == []
    obs.clear_selection()
    key(pygame.K_j)
    assert obs.pump()
    assert obs.selected == "player_3"
    vx, vy, vw, vh = obs.camera.visible_tiles()
    assert vx <= 40 < vx + vw and vy <= 41 < vy + vh


def test_AC10_j_with_no_events_does_not_crash(cfg, world_pair, file_db):
    import pygame

    _, frame, *_ = world_pair
    obs = flash_obs(cfg, file_db, frame, Clock())
    key(pygame.K_j)
    assert obs.pump()
    assert obs.selected is None


# ------------------------------------------------------------------ AC-11: graphs


def player_day(player, tick_day, hourly):
    return Event(
        tick=tick_day * 1440,
        payload=PlayerDay(
            player=player, day=tick_day, x_hourly=hourly, x_mean=0.0, x_median=0.0, band="ok",
            home_food_units=0.0, household_need=0.0, food_stored=0.0, villagers=0, alive=True,
        ),
    )  # fmt: skip


def state(trust_anger):
    """state_json with world.people.players as a list, trust_anger: {holder: {other: (t, a)}}"""
    players = []
    for holder, rel in trust_anger.items():
        players.append(
            {
                "id": holder,
                "trust": {o: t for o, (t, a) in rel.items()},
                "anger": {o: a for o, (t, a) in rel.items()},
            }
        )
    return json.dumps({"world": {"people": {"players": players}}})


def add_snapshot(db, tick, rel, interval=360):
    snap = Snapshot(
        tick=tick, last_event_id=None, schema_version=1,
        config_json=json.dumps({"run": {"autosave_interval": interval}}),
        config_hash="h", state_json=state(rel), rng_json="{}",
    )  # fmt: skip
    return db.save_snapshot(snap)


def test_AC11_x_series_example_from_the_contract(file_db):
    file_db.append_events([player_day("player_1", 1, [50.0] * 23 + [61.5])])
    points, last = x_series(file_db, "player_1")
    assert len(points) == 24
    assert points[0] == (60, 50.0) and points[-1] == (1440, 61.5)
    assert last >= 1
    assert x_series(file_db, "player_1", last) == ([], last)
    assert x_series(file_db, "player_2")[0] == []


def test_AC11_relation_series_example_from_the_contract(file_db):
    rel = lambda t, a: {"player_1": {"player_2": (t, a)}}  # noqa: E731
    add_snapshot(file_db, 0, rel(10, 1))
    add_snapshot(file_db, 360, rel(20, 2))
    add_snapshot(file_db, 361, rel(30, 3))
    add_snapshot(file_db, 720, rel(40, 4))
    pts, last = relation_series(file_db)
    assert [(p.tick, p.holder, p.other, p.trust, p.anger) for p in pts] == [
        (360, "player_1", "player_2", 20.0, 2.0),
        (720, "player_1", "player_2", 40.0, 4.0),
    ]
    add_snapshot(file_db, 720, rel(45, 5))
    pts, last2 = relation_series(file_db)
    assert [(p.tick, p.trust) for p in pts] == [(360, 20.0), (720, 45.0)]
    assert last2 > last
    # missing relation omitted, never invented
    add_snapshot(file_db, 1080, {"player_1": {}})
    pts, _ = relation_series(file_db)
    assert all(p.tick != 1080 for p in pts)


def test_AC11_observer_graph_data_equals_x_hourly_and_stored_snapshots(cfg, world_pair, file_db):
    _, frame, *_ = world_pair
    hourly1 = [40.0 + h * 0.5 for h in range(24)]
    hourly2 = [55.25 - h * 0.25 for h in range(24)]
    file_db.append_events(
        [
            player_day("player_1", 1, hourly1),
            player_day("player_2", 1, [10.0] * 24),
            player_day("player_1", 2, hourly2),
        ]
    )
    both = lambda t, a: {  # noqa: E731
        "player_1": {"player_2": (t, a), "player_3": (t + 1, a + 1)},
        "player_2": {"player_1": (t + 2, a + 2)},
    }
    add_snapshot(file_db, 0, both(1, 1))
    add_snapshot(file_db, 360, both(20, 2))
    add_snapshot(file_db, 361, both(30, 3))
    add_snapshot(file_db, 720, both(40, 4))
    add_snapshot(file_db, 720, both(45, 5))
    obs = make_obs(cfg, file_db)
    draw_n(obs, frame, 3)
    g = obs.graph_data("player_1")
    expect_x = tuple((60 * (h + 1), hourly1[h]) for h in range(24)) + tuple(
        (1440 + 60 * (h + 1), hourly2[h]) for h in range(24)
    )
    assert tuple(g.x) == expect_x
    assert tuple(g.x) == tuple(x_series(file_db, "player_1")[0])
    assert tuple(g.trust["player_2"]) == ((360, 20.0), (720, 45.0))
    assert tuple(g.anger["player_2"]) == ((360, 2.0), (720, 5.0))
    assert tuple(g.trust["player_3"]) == ((360, 21.0), (720, 46.0))
    assert tuple(obs.graph_data("player_2").trust["player_1"]) == ((360, 22.0), (720, 47.0))
    pts = relation_series(file_db)[0]
    flat = [
        (p.tick, p.trust, p.anger) for p in pts if p.holder == "player_1" and p.other == "player_2"
    ]
    assert flat == [
        (t, a, b) for (t, a), (_, b) in zip(g.trust["player_2"], g.anger["player_2"], strict=True)
    ]


def test_AC11_graphs_pick_up_rows_added_while_watching(cfg, world_pair, file_db):
    _, frame, *_ = world_pair
    obs = make_obs(cfg, file_db)
    draw_n(obs, frame)
    assert tuple(obs.graph_data("player_1").x) == ()
    file_db.append_events([player_day("player_1", 1, [70.0] * 24)])
    draw_n(obs, frame, 3)
    assert len(obs.graph_data("player_1").x) == 24


def test_AC11_graphs_draw_empty_one_point_and_flat_series_without_error(cfg, world_pair, file_db):
    _, frame, _, _ = world_pair
    obs = make_obs(cfg, file_db)
    obs.select_tab("Players")
    draw_n(obs, frame)  # empty: "no data yet"
    file_db.append_events([player_day("player_1", 1, [50.0] * 24)])
    add_snapshot(file_db, 360, {"player_1": {"player_2": (50, 0)}})
    draw_n(obs, frame, 3)
    obs.select("player_1")
    draw_n(obs, frame)
    obs.relayout(1280, 720)
    draw_n(obs, frame)
    assert obs.graph_data("player_1").x[0] == (60, 50.0)


def test_AC11_real_run_x_graph_matches_player_day_events(cfg, tmp_path):
    db = RunDB.create(tmp_path / "real.db")
    sim = Simulation.new(cfg, 1, players="dummy")
    sim.attach(db)
    sim.run(1500)
    sim.flush()
    frame = frame_from_world(sim)
    con = sqlite3.connect(db.path)
    rows = con.execute(
        "SELECT payload_json FROM events WHERE type='player_day' ORDER BY id"
    ).fetchall()
    con.close()
    assert rows, "a day passed, so player_day events must exist"
    obs = make_obs(cfg, db)
    draw_n(obs, frame, 3)
    for pid in PLAYERS:
        expect = []
        for (raw,) in rows:
            p = json.loads(raw)
            if p["player"] == pid:
                expect += [
                    ((p["day"] - 1) * 1440 + 60 * (h + 1), v) for h, v in enumerate(p["x_hourly"])
                ]
        assert list(obs.graph_data(pid).x) == expect
    db.close()


# ------------------------------------------------------------------ AC-12: mini-map


def test_AC12_one_dot_per_person_in_their_village_colour(cfg, world_pair):
    import pygame

    _, frame, led_id, free_id = world_pair
    obs = make_obs(cfg)
    obs.draw(frame, 0.0)
    dots = obs.minimap_dots()
    ids = [d[0] for d in dots]
    people = [a for a in (*frame.players, *frame.villagers)]
    assert sorted(ids) == sorted(a.id for a in people)
    rect = obs.minimap_rect
    colours = cfg.assets.colors
    by_id = {d[0]: d for d in dots}
    for a in people:
        owner = a.id if a.kind == "player" else a.leader
        want = rgb(colours.players[owner]) if owner else rgb(colours.wanderer)
        _, px, py, got = by_id[a.id]
        assert tuple(got) == want, (a.id, got, want)
        assert rect.collidepoint(px, py)
    surf = pygame.display.get_surface()
    last: dict[tuple[int, int], tuple[int, int, int]] = {}
    for _, px, py, c in dots:
        last[(px, py)] = tuple(c)
    ok = sum(surf.get_at(pos)[:3] == c for pos, c in last.items())
    assert ok >= 0.8 * len(last), (ok, len(last))
    assert tuple(by_id[free_id][3]) == rgb(colours.wanderer)


def test_AC12_visible_area_frame_follows_the_camera(cfg, world_pair):
    import pygame

    _, frame, *_ = world_pair
    obs = make_obs(cfg)
    obs.draw(frame, 0.0)
    rect = obs.minimap_rect.copy()
    surf = pygame.display.get_surface()
    first = pygame.image.tobytes(surf.subsurface(rect), "RGB")
    vis1 = obs.camera.visible_tiles()
    obs.camera.center_on(5, 5)
    obs.draw(frame, 0.0)
    vis2 = obs.camera.visible_tiles()
    second = pygame.image.tobytes(surf.subsurface(rect), "RGB")
    if vis1 != vis2:
        assert first != second, "the frame in the mini-map must move with the view"
    assert vis1[2] < frame.width or vis1[3] < frame.height or vis1 == vis2


def test_AC12_click_moves_the_view_and_keeps_the_selection(cfg, world_pair):
    _, frame, *_ = world_pair
    obs = make_obs(cfg)
    obs.draw(frame, 0.0)
    obs.select("player_1")
    assert obs.following
    rect = obs.minimap_rect
    px, py = rect.x + rect.w * 3 // 4, rect.y + rect.h * 3 // 4
    tx = (px - rect.x) * frame.width // rect.w
    ty = (py - rect.y) * frame.height // rect.h
    click((px, py))
    assert obs.pump()
    obs.draw(frame, 0.0)
    assert obs.following is False
    assert obs.selected == "player_1"
    vx, vy, vw, vh = obs.camera.visible_tiles()
    cx, cy = vx + vw // 2, vy + vh // 2
    at_right = vx + vw >= frame.width
    at_bottom = vy + vh >= frame.height
    assert abs(cx - tx) <= 1 or at_right, (cx, tx, obs.camera.visible_tiles())
    assert abs(cy - ty) <= 1 or at_bottom, (cy, ty, obs.camera.visible_tiles())
    # a click far in the other corner moves the view away again
    px, py = rect.x + 2, rect.y + 2
    click((px, py))
    assert obs.pump()
    obs.draw(frame, 0.0)
    assert obs.camera.visible_tiles()[0] <= vx


def test_AC12_m_hides_and_shows_the_minimap(cfg, world_pair):
    import pygame

    _, frame, *_ = world_pair
    obs = make_obs(cfg)
    obs.draw(frame, 0.0)
    assert obs.minimap_visible and obs.minimap_dots()
    key(pygame.K_m)
    assert obs.pump()
    obs.draw(frame, 0.0)
    assert obs.minimap_visible is False
    assert obs.minimap_dots() == []
    assert obs.layout.minimap.w == 0 or obs.layout.minimap.h == 0
    key(pygame.K_m)
    assert obs.pump()
    obs.draw(frame, 0.0)
    assert obs.minimap_visible and obs.minimap_dots()
    assert obs.layout.map.contains(obs.minimap_rect)


# ------------------------------------------------------------------ AC-13: help and screenshots


def test_AC13_h_shows_the_overlay_listing_every_table_entry(cfg, world_pair):
    import pygame

    from ai_island.observer.keys import KEY_TABLE

    _, frame, *_ = world_pair
    obs = make_obs(cfg)
    obs.draw(frame, 0.0)
    assert obs.help_visible is False
    key(pygame.K_h)
    assert obs.pump()
    obs.draw(frame, 0.0)
    assert obs.help_visible is True
    text = obs.help_text().splitlines()
    for b in KEY_TABLE:
        assert f"{b.name}: {b.action}" in text, b
    assert len([ln for ln in text if ln.strip()]) == len(KEY_TABLE)
    names = {b.name for b in KEY_TABLE}
    for must in ("P", "Tab", "B", "M", "J", "H", "F11", "F12", "Esc", "Chats", "Players", "Spend"):
        assert must in names, must
    key(pygame.K_h)
    assert obs.pump()
    assert obs.help_visible is False


def test_AC13_the_table_covers_the_keys_the_observer_actually_binds(cfg, world_pair):
    import pygame

    from ai_island.observer.keys import KEY_TABLE

    names = {b.name for b in KEY_TABLE if b.kind == "key"}
    assert {"Left", "Right", "Up", "Down", "Tab", "Esc"} <= names
    _, frame, *_ = world_pair
    obs = make_obs(cfg)
    obs.draw(frame, 0.0)
    # bound keys really act: each of these toggles something visible in state
    before = (obs.panel_visible, obs.bubble_mode, obs.minimap_visible, obs.help_visible)
    for k in (pygame.K_TAB, pygame.K_b, pygame.K_m, pygame.K_h):
        key(k)
        assert obs.pump()
    after = (obs.panel_visible, obs.bubble_mode, obs.minimap_visible, obs.help_visible)
    assert all(a != b for a, b in zip(before, after, strict=True))


def test_AC13_f12_writes_a_png_named_with_run_and_game_time(cfg, world_pair, tmp_path):
    import pygame

    _, frame, *_ = world_pair
    shots = tmp_path / "runs" / "p35" / "screenshots"
    obs = make_obs(cfg, run_name="p35", screenshot_dir=shots)
    f = dataclasses.replace(frame, tick=13805, year=1, week=2, day=10, hour=14, minute=5)
    obs.draw(f, 0.0)
    key(pygame.K_F12)
    assert obs.pump()
    assert (shots / "p35_y1_w2_d3_14-05.png").is_file()
    assert "Saved p35_y1_w2_d3_14-05.png" in obs.status_text
    key(pygame.K_F12)
    assert obs.pump()
    assert (shots / "p35_y1_w2_d3_14-05_2.png").is_file()
    key(pygame.K_F12)
    assert obs.pump()
    assert (shots / "p35_y1_w2_d3_14-05_3.png").is_file()
    img = pygame.image.load(str(shots / "p35_y1_w2_d3_14-05.png"))
    assert img.get_size() == pygame.display.get_surface().get_size()


def test_AC13_default_screenshot_folder_is_under_runs_run_name(cfg, world_pair):
    _, frame, *_ = world_pair
    obs = make_obs(cfg, run_name="p35")
    assert obs.screenshot_folder() == ROOT / "runs" / "p35" / "screenshots"


def test_AC13_screenshot_status_expires_after_status_seconds(cfg, world_pair, tmp_path):
    _, frame, *_ = world_pair
    clock = Clock(0.0)
    obs = make_obs(cfg, run_name="p35", screenshot_dir=tmp_path / "s", clock=clock)
    obs.draw(frame, 0.0)
    path = obs.save_screenshot()
    assert path is not None and path.is_file()
    assert obs.status_text == f"Saved {path.name}"
    clock.t = cfg.run.view.status_seconds + 0.1
    assert obs.status_text == ""


def test_AC13_no_run_name_writes_nothing_and_says_why(cfg, world_pair, tmp_path, monkeypatch):
    import pygame

    _, frame, *_ = world_pair
    monkeypatch.chdir(tmp_path)
    obs = make_obs(cfg)
    obs.draw(frame, 0.0)
    key(pygame.K_F12)
    assert obs.pump()
    assert obs.save_screenshot() is None
    assert "Open a named run to save screenshots" in obs.status_text
    assert not list(tmp_path.rglob("*.png"))


def test_AC13_a_failed_write_is_a_note_not_a_crash(cfg, world_pair, tmp_path):
    _, frame, *_ = world_pair
    blocker = tmp_path / "blocked"
    blocker.write_text("a file, not a folder")
    obs = make_obs(cfg, run_name="p35", screenshot_dir=blocker / "inside")
    obs.draw(frame, 0.0)
    assert obs.save_screenshot() is None
    assert obs.status_text


# ------------------------------------------------------------------ AC-14: the guide


def test_AC14_docs_guide_equals_the_generated_guide():
    from ai_island.guide import render_guide

    on_disk = (ROOT / "docs" / "guide.md").read_text(encoding="utf-8")
    assert on_disk == render_guide(ROOT)


def test_AC14_every_subcommand_of_the_parser_is_in_the_guide():
    import argparse

    from ai_island.cli import build_parser

    text = (ROOT / "docs" / "guide.md").read_text(encoding="utf-8")
    parser = build_parser()
    subs = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    assert set(subs.choices) >= {
        "new", "headless", "resume", "report", "measures", "export", "watch", "view", "guide",
    }  # fmt: skip
    for name in subs.choices:
        assert f"uv run python main.py {name}" in text, name
    for example in (
        "new p35 --players scripted",
        "watch --run p35",
        "headless --ticks 1440 --seed 1",
        "resume p35 --ticks 1440",
        "report --run p35",
        "measures --run p35",
        "export --run p35",
        "view --run p35 --ticks 60 --screenshot runs/p35/preview.png",
    ):
        assert f"uv run python main.py {example}" in text, example
    assert "--crash-after-tick" not in text


def test_AC14_every_key_in_the_key_table_is_in_the_guide():
    from ai_island.observer.keys import KEY_TABLE

    text = (ROOT / "docs" / "guide.md").read_text(encoding="utf-8")
    for b in KEY_TABLE:
        assert b.name in text, b
        assert b.action in text, b


def test_AC14_every_building_and_item_with_its_sprite_source():
    raw = (ROOT / "config" / "assets.toml").read_text(encoding="utf-8-sig")
    assets = tomllib.loads(raw)
    bal = tomllib.loads((ROOT / "config" / "balance.toml").read_text(encoding="utf-8-sig"))
    text = (ROOT / "docs" / "guide.md").read_text(encoding="utf-8")
    table_lines = [ln for ln in text.splitlines() if ln.startswith("|")]
    for item in (k for k in assets["items"] if not k.startswith("damaged_")):  # own table
        row = [ln for ln in table_lines if ln.startswith(f"| `{item}` |")]
        assert row, f"{item} missing from the guide"
        assert any(s in row[0] for s in ("kenney", "tiny_creatures", "code", "drawn")), row[0]
    for kind in bal["buildings"]["work_minutes"]:
        rows = [ln for ln in table_lines if ln.startswith(f"| `{kind}` |")]
        assert rows, kind
        assert any(s in rows[0] for s in ("kenney", "tiny_creatures", "code")), rows[0]
    damaged = [k.removeprefix("damaged_") for k in assets["items"] if k.startswith("damaged_")]
    assert damaged
    for kind in damaged:
        assert any(
            ln.startswith(f"| `{kind}` |") and "normal sprite faded with a progress bar" in ln
            for ln in table_lines
        ), kind


def test_AC14_every_activity_kind_has_its_icon_or_word_in_the_guide(cfg):
    from ai_island.world.view import ACTIVITY_KINDS

    text = (ROOT / "docs" / "guide.md").read_text(encoding="utf-8")
    for kind in ACTIVITY_KINDS:
        assert f"`{kind}`" in text, kind


def test_AC14_the_guide_subcommand_regenerates_the_file(tmp_path):
    out = tmp_path / "guide.md"
    r = cli("guide", "--out", str(out))
    assert r.returncode == 0, r.stderr
    assert str(out) in r.stdout
    assert out.read_text(encoding="utf-8") == (ROOT / "docs" / "guide.md").read_text(
        encoding="utf-8"
    )


def test_AC14_the_guide_lists_no_paid_command():
    text = (ROOT / "docs" / "guide.md").read_text(encoding="utf-8").lower()
    # Phase 5: every subcommand is listed, and the paid ones are marked as Tim's to run
    for word in ("calibrate", "judge-check"):
        assert word in text, word
        block = text[text.index(f"### `{word}`") :]
        assert "tim only" in block[:700], word


# ------------------------------------------------------------------ CLI wiring (Contract "CLI")


class FakeObserver:
    instances: list = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        FakeObserver.instances.append(self)

    def pump(self):
        return False

    def draw(self, *a, **k):
        pass

    def save_png(self, *a, **k):
        pass

    def close(self):
        pass


@pytest.fixture
def fake_observer(monkeypatch):
    import ai_island.observer as pkg

    FakeObserver.instances = []
    monkeypatch.setattr(pkg, "Observer", FakeObserver)
    return FakeObserver


def test_CLI_watch_and_view_pass_prefs_path_and_screenshot_dir(cfg, run_name, fake_observer):
    from ai_island import cli as cli_mod

    r = cli("new", run_name, "--players", "none")
    assert r.returncode == 0, r.stderr
    runs = ROOT / cfg.run.runs_dir
    prefs = runs / "observer_prefs.json"
    shots = runs / run_name / "screenshots"
    assert cli_mod.main(["watch", "--run", run_name]) == 0
    assert cli_mod.main(["view", "--run", run_name]) == 0
    assert cli_mod.main(["view", "--seed", "1"]) == 0
    watch, view_run, view_none = fake_observer.instances
    for obs in (watch, view_run):
        assert obs.kwargs["run_name"] == run_name
        assert obs.kwargs["prefs_path"] == prefs
        assert obs.kwargs["screenshot_dir"] == shots
    assert view_none.kwargs["run_name"] is None
    assert view_none.kwargs["prefs_path"] == prefs
    assert not view_none.kwargs.get("screenshot_dir")


# ------------------------------------------------------------------ AC-15: read-only observer


class SpyControls:
    """Records every method call and attribute write made on it by the observer."""

    def __init__(self, inner):
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "calls", [])
        object.__setattr__(self, "writes", [])

    def __getattr__(self, name):
        value = getattr(self._inner, name)
        if callable(value):

            def wrapper(*a, **k):
                self.calls.append(name)
                return value(*a, **k)

            return wrapper
        return value

    def __setattr__(self, name, value):
        self.writes.append(name)
        setattr(self._inner, name, value)


def test_AC15_observer_only_calls_pause_and_speed_on_the_controls(cfg, world_pair, tmp_path):
    import pygame

    from ai_island.storage.run_control import MemoryControls

    _, frame, *_ = world_pair
    spy = SpyControls(MemoryControls(cfg.run))
    obs = make_obs(
        cfg, RunDB.memory(), spy, run_name="p35", screenshot_dir=tmp_path / "s",
        prefs_path=tmp_path / "prefs.json",
    )  # fmt: skip
    obs.draw(frame, 0.0)
    for k in (
        pygame.K_p, pygame.K_PLUS, pygame.K_MINUS, pygame.K_b, pygame.K_m, pygame.K_h,
        pygame.K_j, pygame.K_TAB, pygame.K_TAB, pygame.K_F12, pygame.K_LEFT, pygame.K_p,
    ):  # fmt: skip
        key(k)
        assert obs.pump()
        obs.draw(frame, 0.0)
    obs.select("player_1")
    click(obs.map_rect.center, button=3)
    obs.pump()
    for tab in ("Chats", "Choice points", "World history", "Players", "Spend"):
        obs.select_tab(tab)
        obs.draw(frame, 0.0)
    assert set(spy.calls) <= {"toggle_pause", "set_speed"}, spy.calls
    assert spy.calls, "P and +/- should reach the controls"
    assert set(spy.writes) <= set(), spy.writes


def test_AC15_a_watched_run_has_the_same_event_log_as_a_headless_run(cfg, tmp_path):
    ticks = 900

    def events(db):
        con = sqlite3.connect(db.path)
        try:
            return con.execute("SELECT tick, type, payload_json FROM events ORDER BY id").fetchall()
        finally:
            con.close()

    plain_db = RunDB.create(tmp_path / "plain.db")
    plain = Simulation.new(cfg, 1, players="dummy")
    plain.attach(plain_db)
    plain.run(ticks)
    plain.flush()

    import pygame

    watched_db = RunDB.create(tmp_path / "watched.db")
    watched = Simulation.new(cfg, 1, players="dummy")
    watched.attach(watched_db)
    obs = make_obs(
        cfg, watched_db, None, run_name="w", screenshot_dir=tmp_path / "s",
        prefs_path=tmp_path / "p.json",
    )  # fmt: skip
    for i in range(ticks // 30):
        watched.run(30)
        watched.flush()
        obs.draw(frame_from_world(watched), 0.0)
        if i % 5 == 0:
            key(pygame.K_F12)
            key(pygame.K_b)
            key(pygame.K_j)
            obs.pump()
        if i == 3:
            obs.select("player_2")
    assert watched.world.tick == plain.world.tick == ticks
    assert events(watched_db) == events(plain_db)
    plain_db.close()
    watched_db.close()


# ------------------------------------------------------------------ AC-16: lint and earlier phases


def test_AC16_ruff_check_and_format_are_clean():
    for args in (["ruff", "check"], ["ruff", "format", "--check"]):
        r = subprocess.run(
            [sys.executable, "-m", *args], cwd=ROOT, capture_output=True, text=True, timeout=300
        )
        assert r.returncode == 0, (args, r.stdout[-1500:], r.stderr[-500:])


def test_AC16_phase_3_tabs_and_snapshot_versions_are_unchanged(cfg, world_pair):
    from ai_island.storage.db import SCHEMA_VERSION

    assert SCHEMA_VERSION == 1
    _, frame, *_ = world_pair
    obs = make_obs(cfg, RunDB.memory())
    obs.draw(frame, 0.0)
    for tab in ("Chats", "Choice points", "World history", "Players", "Spend"):
        obs.select_tab(tab)
        obs.draw(frame, 0.0)
        assert isinstance(obs.tab_text(tab), str)
    from ai_island.sim import SNAPSHOT_VERSION

    assert SNAPSHOT_VERSION == 3
