"""Phase 3.5 AC-3 (bubbles) and AC-4 .. AC-8: chats, panel, layout, prefs, selection.

Written from the Plan's acceptance criteria and Contract only. Every test uses the dummy video
driver; prefs and screenshots go to tmp_path.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3

import pytest
from conftest import ROOT

from ai_island.measure.history import history_entries
from ai_island.sim import Simulation
from ai_island.storage.db import RunDB
from ai_island.storage.events import Event, Harm
from ai_island.world.view import frame_from_world

TOP_KEYS_EXTRA = ("display_size", "display_ui_scale")


# ------------------------------------------------------------------ helpers


@pytest.fixture(autouse=True)
def _dummy_driver(monkeypatch):
    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    yield
    import pygame

    pygame.quit()


@pytest.fixture(scope="module")
def people(cfg):
    """A frame with four players and their villagers, a short way into the first day."""
    sim = Simulation.new(cfg, 1, players="dummy")
    sim.run(600)
    return frame_from_world(sim)


@pytest.fixture
def file_db(tmp_path):
    db = RunDB.create(tmp_path / "run.db")
    yield db
    db.close()


def make_obs(cfg, db=None, controls=None, **kw):
    import pygame

    pygame.quit()
    from ai_island.observer import Observer

    return Observer(cfg.assets, cfg.run.view, ROOT, db, controls, **kw)


def sql(db: RunDB, query: str, params: tuple = ()):
    con = sqlite3.connect(db.path, timeout=10)
    try:
        con.execute(query, params)
        con.commit()
    finally:
        con.close()


def add_chat(db, tick, speaker, targets, hearers, text):
    sql(
        db,
        "INSERT INTO chats (tick, speaker_id, target_ids_json, hearer_ids_json, text) "
        "VALUES (?, ?, ?, ?, ?)",
        (tick, speaker, json.dumps(targets), json.dumps(hearers), text),
    )


def key(k, repeat_up=True):
    import pygame

    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=k, mod=0, unicode="", scancode=0))
    if repeat_up:
        pygame.event.post(pygame.event.Event(pygame.KEYUP, key=k, mod=0, scancode=0))


def click(pos, button=1):
    import pygame

    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=button))
    pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=pos, button=button))


def link(target):
    import pygame
    import pygame_gui

    pygame.event.post(pygame.event.Event(pygame_gui.UI_TEXT_BOX_LINK_CLICKED, link_target=target))


def button(obs, name):
    import pygame
    import pygame_gui

    pygame.event.post(
        pygame.event.Event(pygame_gui.UI_BUTTON_PRESSED, ui_element=obs.elements[name])
    )


def lines(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.strip()]


def all_page_text(obs, tab: str) -> list[str]:
    out: list[str] = []
    for idx in range(obs.page_count(tab)):
        obs.show_page(tab, idx)
        out += lines(obs.tab_text(tab))
    obs.show_page(tab, 0)
    return out


def rgb(hex_text: str) -> tuple[int, int, int]:
    h = hex_text.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def disjoint(*rects):
    live = [r for r in rects if r.w > 0 and r.h > 0]
    for i, a in enumerate(live):
        for b in live[i + 1 :]:
            assert not a.colliderect(b), (a, b)


def window_size():
    import pygame

    return pygame.display.get_surface().get_size()


def assert_fits(obs, win_w, win_h):
    import pygame

    window = pygame.Rect(0, 0, win_w, win_h)
    lay = obs.layout
    for r in (lay.top_bar, lay.map, lay.panel):
        assert window.contains(r), (r, window)
    disjoint(lay.top_bar, lay.map, lay.panel)
    if lay.minimap.w > 0:
        assert lay.map.contains(lay.minimap)
    assert obs.camera.scale >= 1 and isinstance(obs.camera.scale, int)
    bar = lay.top_bar
    rects = []
    for name, el in obs.elements.items():
        if name.startswith("top_") or name in TOP_KEYS_EXTRA:
            rects.append((name, el.get_abs_rect()))
    assert len(rects) >= 10
    for name, r in rects:
        assert bar.contains(r), (name, r, bar)
    for i, (na, a) in enumerate(rects):
        for nb, b in rects[i + 1 :]:
            assert not a.colliderect(b), (na, nb, a, b)


# ------------------------------------------------------------------ AC-3: bubbles


def expected_label(cfg, activity):
    icon = cfg.assets.activity_icons[activity]
    if icon == "word":
        return f"word:{cfg.assets.activity_words[activity]}"
    return icon


def test_AC3_each_visible_person_gets_one_bubble_with_the_mapped_icon_or_word(cfg, people):
    obs = make_obs(cfg)
    obs.draw(people, 0.0)
    assert obs.bubble_mode == "all"
    rects = obs.bubble_rects()
    ids = [r[0] for r in rects]
    assert len(ids) == len(set(ids)), "one bubble per person"
    by_id = {a.id: a for a in (*people.players, *people.villagers)}
    assert set(ids) <= set(by_id)
    assert rects, "something must be visible"
    for ident, _rect, label in rects:
        assert label == expected_label(cfg, by_id[ident].activity), (ident, label)
    visible = []
    for ident in by_id:
        pos = obs.screen_pos_of(ident)
        if pos is None:
            continue
        if not obs.map_rect.collidepoint(pos):
            continue
        if obs.minimap_visible and obs.minimap_rect.collidepoint(pos):
            continue
        visible.append(ident)
    assert visible
    missing = [i for i in visible if i not in ids]
    assert not missing, f"visible people without a bubble: {missing}"


def test_AC3_word_entries_show_the_configured_word(cfg, people):
    obs = make_obs(cfg)
    obs.draw(people, 0.0)
    labels = {label for _i, _r, label in obs.bubble_rects()}
    words = [x for x in labels if x.startswith("word:")]
    for w in words:
        assert w[5:] in cfg.assets.activity_words.values()
    for x in labels - set(words):
        assert x in cfg.assets.items


def test_AC3_b_cycles_all_players_off_and_back(cfg, people):
    import pygame

    obs = make_obs(cfg)
    obs.draw(people, 0.0)
    all_n = len(obs.bubble_rects())
    assert obs.bubble_mode == "all"
    key(pygame.K_b)
    assert obs.pump()
    obs.draw(people, 0.0)
    assert obs.bubble_mode == "players"
    rects = obs.bubble_rects()
    assert all(i.startswith("player_") for i, _r, _l in rects)
    assert len(rects) <= 4 and len(rects) <= all_n
    key(pygame.K_b)
    assert obs.pump()
    obs.draw(people, 0.0)
    assert obs.bubble_mode == "off"
    assert obs.bubble_rects() == []
    key(pygame.K_b)
    assert obs.pump()
    obs.draw(people, 0.0)
    assert obs.bubble_mode == "all"
    assert len(obs.bubble_rects()) == all_n


def test_AC3_no_bubble_touches_the_top_bar_panel_or_minimap(cfg, people):
    obs = make_obs(cfg)
    for _step in range(3):
        obs.draw(people, 0.0)
        for ident, rect, _label in obs.bubble_rects():
            assert not rect.colliderect(obs.top_bar_rect), (ident, rect)
            assert not rect.colliderect(obs.panel_rect), (ident, rect)
            if obs.minimap_visible:
                assert not rect.colliderect(obs.minimap_rect), (ident, rect)
            assert obs.map_rect.contains(rect), (ident, rect)
        obs.cycle_bubbles()
    # also after a scroll to the island corners
    obs = make_obs(cfg)
    obs.draw(people, 0.0)
    for tx, ty in ((0, 0), (people.width, 0), (0, people.height), (people.width, people.height)):
        obs.camera.center_on(tx, ty)
        obs.draw(people, 0.0)
        for _i, rect, _label in obs.bubble_rects():
            assert not rect.colliderect(obs.top_bar_rect)
            assert not rect.colliderect(obs.panel_rect)
            assert not rect.colliderect(obs.minimap_rect)


# ------------------------------------------------------------------ AC-4: chats guide and filters


def guide_lines_expected(frame):
    out = []
    for e in frame.village_guide:
        names = ", ".join(n for _i, n in e.members) or "nobody"
        out.append(f"{e.leader_name}: {names}")
    return out


def test_AC4_chats_tab_starts_with_the_village_guide(cfg, people, file_db):
    obs = make_obs(cfg, file_db)
    obs.draw(people, 0.0)
    assert obs.active_tab == "Chats"
    assert "chat_guide" in obs.elements and "guide_toggle" in obs.elements
    assert obs.guide_text().splitlines() == guide_lines_expected(people)
    assert obs.guide_text().splitlines()[-1].startswith("Wanderers: ")
    # the guide is its own element: it never appears in the tab text of the chat list
    add_chat(file_db, 10, "player_1", [], [], "hello there")
    obs.draw(people, 0.0)
    assert lines(obs.tab_text("Chats")) == [
        ln for ln in lines(obs.tab_text("Chats")) if "hello there" in ln
    ]
    html = obs.elements["chat_guide"].html_text
    colours = cfg.assets.colors.players
    for e in people.village_guide[:-1]:
        assert colours[e.leader_id].lower() in html.lower()
    assert cfg.assets.colors.wanderer.lower() in html.lower()


def test_AC4_guide_toggle_button_collapses_it(cfg, people, file_db):
    obs = make_obs(cfg, file_db)
    obs.draw(people, 0.0)
    start = obs.guide_collapsed
    button(obs, "guide_toggle")
    assert obs.pump()
    assert obs.guide_collapsed is (not start)
    button(obs, "guide_toggle")
    assert obs.pump()
    assert obs.guide_collapsed is start


def test_AC4_chat_names_use_their_village_colour(cfg, people, file_db):
    colours = {k: v.lower() for k, v in cfg.assets.colors.players.items()}
    v1 = next(v for v in people.villagers if v.leader == "player_1")
    wanderer = next(v for v in people.villagers if v.leader == "")
    names = dict(people.names)
    add_chat(file_db, 5, "player_2", [v1.id], [], "colour line one")
    add_chat(file_db, 6, wanderer.id, [], [], "colour line two")
    obs = make_obs(cfg, file_db)
    obs.draw(people, 0.0)
    html = obs.elements["text_box"].html_text.lower()
    assert f'color="{colours["player_2"]}">{names["player_2"]}'.lower() in html
    assert f'color="{colours["player_1"]}">{names[v1.id]}'.lower() in html
    assert f'color="{cfg.assets.colors.wanderer.lower()}">{names[wanderer.id]}'.lower() in html


def build_chat_world(cfg, people, file_db):
    v1 = next(v.id for v in people.villagers if v.leader == "player_1")
    v2 = next(v.id for v in people.villagers if v.leader == "player_2")
    w1 = next(v.id for v in people.villagers if v.leader == "")
    rows = [
        (1, v1, ["player_2"], ["player_3"], "m_a"),
        (2, "player_3", [], [w1], "m_b"),
        (3, w1, [], ["player_1"], "m_c"),
        (4, "player_4", [v2], [], "m_d"),
        (5, "player_1", [v1], ["player_2", "player_3"], "m_e"),
        (6, v2, ["player_3"], ["player_1"], "m_f"),
        (7, w1, [v1], [], "m_g"),
        (8, "player_2", [], ["player_4"], "m_h"),
    ]
    for tick, spk, tg, hr, text in rows:
        add_chat(file_db, tick, spk, tg, hr, text)
    return rows


def expected_rows(frame, rows, kind, ident=None, selected=None):
    members = {e.leader_id: {m for m, _n in e.members} for e in frame.village_guide}
    out = []
    for _t, spk, tg, hr, text in rows:
        if kind == "all":
            ok = True
        elif kind == "village":
            ids = ({ident} - {""}) | members.get(ident, set())
            ok = spk in ids or any(t in ids for t in tg)
        elif kind == "person":
            ok = spk == ident or ident in tg
        else:
            ok = selected is not None and selected in hr
        if ok:
            out.append(text)
    return out


def shown_texts(obs, texts):
    got = []
    for ln in all_page_text(obs, "Chats"):
        for t in texts:
            if f": {t} |" in ln or f"{t} |" in ln:
                got.append(t)
    return got


def test_AC4_every_filter_shows_exactly_the_matching_rows(cfg, people, file_db):
    rows = build_chat_world(cfg, people, file_db)
    all_texts = [r[4] for r in rows]
    obs = make_obs(cfg, file_db)
    obs.draw(people, 0.0)
    assert obs.chat_filter[0] == "all"
    assert shown_texts(obs, all_texts) == all_texts
    cases = [
        ("village", "player_1"),
        ("village", "player_2"),
        ("village", "player_3"),
        ("village", ""),
        ("person", "player_2"),
        ("person", "player_3"),
    ]
    for kind, ident in cases:
        obs.set_chat_filter(kind, ident)
        obs.draw(people, 0.0)
        assert obs.chat_filter == (kind, ident)
        want = expected_rows(people, rows, kind, ident)
        assert shown_texts(obs, all_texts) == want, (kind, ident)
        assert len(all_page_text(obs, "Chats")) == len(want), (kind, ident)
    obs.set_chat_filter("all")
    obs.draw(people, 0.0)
    assert shown_texts(obs, all_texts) == all_texts


def test_AC4_spec_example_village_person_heard(cfg, people, file_db):
    v1 = next(v.id for v in people.villagers if v.leader == "player_1")
    add_chat(file_db, 1, v1, ["player_2"], ["player_3"], "the_example")
    obs = make_obs(cfg, file_db)
    obs.draw(people, 0.0)

    def count(kind, ident=None):
        obs.set_chat_filter(kind, ident)
        obs.draw(people, 0.0)
        return len(all_page_text(obs, "Chats"))

    assert count("village", "player_1") == 1
    assert count("village", "player_2") == 1
    assert count("village", "player_3") == 0  # hearing alone does not count
    assert count("person", "player_2") == 1
    obs.select("player_3")
    assert count("heard") == 1
    obs.select("player_2")
    assert count("heard") == 0


def test_AC4_heard_with_nothing_selected_shows_a_hint_and_no_rows(cfg, people, file_db):
    add_chat(file_db, 1, "player_1", [], ["player_2"], "someone listens")
    obs = make_obs(cfg, file_db)
    obs.draw(people, 0.0)
    assert obs.selected is None
    obs.set_chat_filter("heard")
    obs.draw(people, 0.0)
    assert obs.tab_text("Chats") == "Select someone to see what they heard."


def test_AC4_filtering_happens_before_paging_and_resets_to_page_zero(cfg, people, file_db):
    for i in range(201):
        add_chat(file_db, i, "player_1", [], ["player_2"], f"bulk {i}")
    for i in range(30):
        add_chat(file_db, 300 + i, "player_3", [], [], f"other {i}")
    obs = make_obs(cfg, file_db)
    obs.draw(people, 0.0)
    obs.set_chat_filter("person", "player_1")
    obs.draw(people, 0.0)
    assert obs.page_count("Chats") == 3
    obs.show_page("Chats", 2)
    assert len(lines(obs.tab_text("Chats"))) == 1
    obs.set_chat_filter("person", "player_3")
    obs.draw(people, 0.0)
    assert obs.page_count("Chats") == 1
    assert len(lines(obs.tab_text("Chats"))) == 30
    obs.show_page("Chats", 0)
    assert all("other" in ln for ln in lines(obs.tab_text("Chats")))
    obs.set_chat_filter("person", "player_1")
    obs.draw(people, 0.0)
    assert len(lines(obs.tab_text("Chats"))) == 100  # back on page 0 of the new filter


# ------------------------------------------------------------------ AC-5: hide the panel


def test_AC5_tab_key_hides_and_shows_the_panel_and_the_map_spans_the_window(cfg, people):
    import pygame

    obs = make_obs(cfg)
    obs.draw(people, 0.0)
    assert obs.panel_visible
    shown_map = obs.map_rect.copy()
    assert tuple(obs.map_rect) == (0, 48, 800, 752)
    assert tuple(obs.panel_rect) == (800, 48, 480, 752)
    key(pygame.K_TAB)
    assert obs.pump()
    obs.draw(people, 0.0)
    assert not obs.panel_visible
    assert tuple(obs.map_rect) == (0, 48, 1280, 752)
    assert obs.panel_rect.w == 0 or obs.panel_rect.h == 0
    key(pygame.K_TAB)
    assert obs.pump()
    obs.draw(people, 0.0)
    assert obs.panel_visible
    assert obs.map_rect == shown_map


def test_AC5_hide_button_hides_and_shows_the_panel(cfg, people):
    obs = make_obs(cfg)
    obs.draw(people, 0.0)
    button(obs, "top_panel")
    assert obs.pump()
    obs.draw(people, 0.0)
    assert not obs.panel_visible
    assert obs.map_rect.w == 1280
    button(obs, "top_panel")
    assert obs.pump()
    obs.draw(people, 0.0)
    assert obs.panel_visible
    assert obs.map_rect.w == 800


def test_AC5_a_held_tab_key_is_one_toggle_not_many(cfg, people):
    import pygame

    obs = make_obs(cfg)
    obs.draw(people, 0.0)
    for _ in range(5):
        key(pygame.K_TAB, repeat_up=False)
    assert obs.pump()
    assert not obs.panel_visible  # five repeats = one toggle


# ------------------------------------------------------------------ AC-6: layout


SIZES = [(1280, 720), (1600, 1000), (1920, 1080), (3200, 2000)]


@pytest.mark.parametrize("panel", [True, False])
@pytest.mark.parametrize(("w", "h"), SIZES)
def test_AC6_compute_layout_fits_without_overlap(cfg, w, h, panel):
    import pygame

    from ai_island.observer.layout import compute_layout

    view = cfg.run.view
    for choice in (0, 1, 2, 3):
        lay = compute_layout(w, h, choice, panel, True, view)
        window = pygame.Rect(0, 0, w, h)
        assert lay.ui_scale >= 1
        for r in (lay.top_bar, lay.map, lay.panel):
            if r.w > 0 and r.h > 0:
                assert window.contains(r), (r, window)
        disjoint(lay.top_bar, lay.map, lay.panel)
        assert lay.map.contains(lay.minimap)
        if not panel:
            assert lay.map.w == w
            assert lay.panel.w == 0 or lay.panel.h == 0
        if choice:
            assert lay.ui_scale <= choice


def test_AC6_contract_layout_examples(cfg):
    from ai_island.observer.layout import compute_layout

    view = cfg.run.view
    lay = compute_layout(1280, 800, 0, True, True, view)
    assert lay.ui_scale == 1
    assert tuple(lay.top_bar) == (0, 0, 1280, 48)
    assert tuple(lay.panel) == (800, 48, 480, 752)
    assert tuple(lay.map) == (0, 48, 800, 752)
    assert tuple(lay.minimap) == (8, 632, 160, 160)
    assert tuple(compute_layout(1280, 800, 0, False, True, view).map) == (0, 48, 1280, 752)
    assert tuple(compute_layout(1280, 720, 0, True, True, view).map) == (0, 48, 800, 672)
    big = compute_layout(3200, 2000, 0, True, True, view)
    assert big.ui_scale == 2
    assert tuple(big.top_bar) == (0, 0, 3200, 96)
    assert tuple(big.panel) == (2240, 96, 960, 1904)
    assert tuple(big.map) == (0, 96, 2240, 1904)
    assert compute_layout(1280, 720, 3, True, True, view).ui_scale == 1
    assert compute_layout(3200, 2000, 3, True, True, view).ui_scale == 3


def test_AC6_camera_contract_examples():
    import pygame

    from ai_island.observer.camera import MapCamera

    cam = MapCamera()
    cam.map_rect = pygame.Rect(0, 48, 800, 752)
    cam.scale = 1
    cam.map_w = cam.map_h = 80
    assert cam.world_to_screen(10, 20) == (160, 368)
    assert cam.screen_to_tile(168, 376) == (10, 20)
    cam.offset_x = 4
    assert cam.world_to_screen(10, 20) == (96, 368)
    assert cam.screen_to_tile(104, 376) == (10, 20)


@pytest.mark.parametrize(("w", "h"), SIZES)
def test_AC6_real_observer_after_a_video_resize_event(cfg, people, w, h):
    import pygame

    obs = make_obs(cfg)
    obs.draw(people, 0.0)
    pygame.event.post(pygame.event.Event(pygame.VIDEORESIZE, size=(w, h), w=w, h=h))
    assert obs.pump()
    obs.draw(people, 0.0)
    assert window_size() == (w, h)
    assert_fits(obs, w, h)
    # and back to the start size
    pygame.event.post(pygame.event.Event(pygame.VIDEORESIZE, size=(1280, 800), w=1280, h=800))
    assert obs.pump()
    obs.draw(people, 0.0)
    assert_fits(obs, 1280, 800)
    assert tuple(obs.map_rect) == (0, 48, 800, 752)


@pytest.mark.parametrize(("w", "h"), SIZES)
def test_AC6_real_observer_after_a_window_size_changed_event(cfg, people, w, h):
    import pygame

    obs = make_obs(cfg)
    obs.draw(people, 0.0)
    pygame.event.post(pygame.event.Event(pygame.WINDOWSIZECHANGED, x=w, y=h))
    assert obs.pump()
    obs.draw(people, 0.0)
    assert_fits(obs, w, h)


@pytest.mark.parametrize(("w", "h"), [(1280, 720), (3200, 2000)])
def test_AC6_each_tab_state_survives_a_resize(cfg, people, file_db, w, h):
    import pygame

    add_chat(file_db, 1, "player_1", [], [], "persist me")
    obs = make_obs(cfg, file_db)
    obs.draw(people, 0.0)
    obs.select_tab("Players")
    obs.select("player_2")
    obs.draw(people, 0.0)
    pygame.event.post(pygame.event.Event(pygame.VIDEORESIZE, size=(w, h), w=w, h=h))
    assert obs.pump()
    obs.draw(people, 0.0)
    assert obs.active_tab == "Players"
    assert obs.selected == "player_2"
    assert_fits(obs, w, h)
    obs.select_tab("Chats")
    obs.draw(people, 0.0)
    assert any("persist me" in ln for ln in lines(obs.tab_text("Chats")))


def test_AC6_f11_toggles_full_screen_and_restores_the_window_size(cfg, people):
    import pygame

    obs = make_obs(cfg)
    obs.draw(people, 0.0)
    assert obs.fullscreen is False
    windowed = window_size()
    key(pygame.K_F11)
    assert obs.pump()
    obs.draw(people, 0.0)
    assert obs.fullscreen is True
    w, h = window_size()
    assert_fits(obs, w, h)
    key(pygame.K_F11)
    assert obs.pump()
    obs.draw(people, 0.0)
    assert obs.fullscreen is False
    assert window_size() == windowed
    assert_fits(obs, *windowed)


# ------------------------------------------------------------------ AC-7: display menu and prefs


def config_hash():
    h = hashlib.sha256()
    for p in sorted((ROOT / "config").rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(ROOT)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def test_AC7_display_choice_changes_layout_at_once_writes_prefs_and_is_read_back(
    cfg, people, tmp_path
):
    prefs = tmp_path / "observer_prefs.json"
    before = config_hash()
    obs = make_obs(cfg, prefs_path=prefs)
    obs.draw(people, 0.0)
    assert "display_size" in obs.elements and "display_ui_scale" in obs.elements
    assert not prefs.exists()
    obs.apply_display("1920x1080", 2)
    obs.draw(people, 0.0)
    assert window_size() == (1920, 1080)
    assert obs.layout.ui_scale == 2
    assert tuple(obs.top_bar_rect) == (0, 0, 1920, 96)
    assert_fits(obs, 1920, 1080)
    data = json.loads(prefs.read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert data["display_size"] == "1920x1080"
    assert data["ui_scale"] == 2
    assert data["panel_visible"] is True and data["minimap_visible"] is True
    assert data["bubbles"] == "all"
    obs2 = make_obs(cfg, prefs_path=prefs)
    obs2.draw(people, 0.0)
    assert obs2.display_size == "1920x1080"
    assert obs2.ui_choice == 2
    assert obs2.layout.ui_scale == 2
    assert window_size() == (1920, 1080)
    assert config_hash() == before


def test_AC7_toggles_are_saved_and_read_back(cfg, people, tmp_path):
    import pygame

    prefs = tmp_path / "observer_prefs.json"
    obs = make_obs(cfg, prefs_path=prefs)
    obs.draw(people, 0.0)
    for k in (pygame.K_TAB, pygame.K_b, pygame.K_m):
        key(k)
        assert obs.pump()
    data = json.loads(prefs.read_text(encoding="utf-8"))
    assert data["panel_visible"] is False
    assert data["bubbles"] == "players"
    assert data["minimap_visible"] is False
    obs2 = make_obs(cfg, prefs_path=prefs)
    obs2.draw(people, 0.0)
    assert obs2.panel_visible is False
    assert obs2.bubble_mode == "players"
    assert obs2.minimap_visible is False


def test_AC7_no_prefs_path_means_nothing_is_read_or_written(cfg, people, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    obs = make_obs(cfg)
    obs.draw(people, 0.0)
    obs.apply_display("1600x1000", 1)
    obs.toggle_panel()
    assert obs.prefs_path is None
    assert list(tmp_path.rglob("*.json")) == []


@pytest.mark.parametrize(
    "content",
    ["{not json", "[]", '{"version": 1, "display_size": "99x99", "ui_scale": 9, "bubbles": "x"}'],
)
def test_AC7_corrupt_or_invalid_prefs_fall_back_to_the_defaults(cfg, people, tmp_path, content):
    prefs = tmp_path / "observer_prefs.json"
    prefs.write_text(content, encoding="utf-8")
    obs = make_obs(cfg, prefs_path=prefs)
    obs.draw(people, 0.0)
    assert obs.bubble_mode == "all"
    assert obs.panel_visible is True
    assert obs.display_size == cfg.run.view.display_size
    assert obs.ui_choice == cfg.run.view.ui_scale


def test_AC7_unwritable_prefs_give_a_note_not_a_crash(cfg, people, tmp_path):
    blocker = tmp_path / "afile"
    blocker.write_text("x", encoding="utf-8")
    obs = make_obs(cfg, prefs_path=blocker / "observer_prefs.json")
    obs.draw(people, 0.0)
    obs.apply_display("1600x1000", 1)
    obs.draw(people, 0.0)
    assert obs.status_text.strip() != ""


def test_AC7_a_drag_resize_is_not_saved(cfg, people, tmp_path):
    import pygame

    prefs = tmp_path / "observer_prefs.json"
    obs = make_obs(cfg, prefs_path=prefs)
    obs.draw(people, 0.0)
    pygame.event.post(pygame.event.Event(pygame.VIDEORESIZE, size=(1600, 1000), w=1600, h=1000))
    assert obs.pump()
    assert not prefs.exists()


# ------------------------------------------------------------------ AC-8: selection


def pick(obs, frame, kind):
    """A person of ``kind`` whose sprite is on the visible map, alone on its tile."""
    people_list = frame.players if kind == "player" else frame.villagers
    taken = {}
    for a in (*frame.players, *frame.villagers):
        taken[(a.x, a.y)] = taken.get((a.x, a.y), 0) + 1
    for a in people_list:
        pos = obs.screen_pos_of(a.id)
        if pos is None or taken[(a.x, a.y)] != 1:
            continue
        inner = obs.map_rect.inflate(-40, -40)
        if inner.collidepoint(pos) and not obs.minimap_rect.inflate(20, 20).collidepoint(pos):
            return a.id
    return None


def visible_or_scroll(obs, frame, kind):
    ident = pick(obs, frame, kind)
    if ident is None:
        a = (frame.players if kind == "player" else frame.villagers)[0]
        obs.camera.center_on(a.x, a.y)
        obs.camera.offset_x += 3
        obs.camera.clamp()
        obs.draw(frame, 0.0)
        ident = pick(obs, frame, kind)
    assert ident is not None, f"no {kind} visible"
    return ident


def count_ring_pixels(obs, frame, ident, colour):
    import pygame

    a = next(x for x in (*frame.players, *frame.villagers) if x.id == ident)
    rect = obs.camera.agent_rect(a, frame, 0.0)
    surf = pygame.display.get_surface()
    n = 0
    for x in range(rect.left, rect.right):
        for y in (rect.top, rect.bottom - 1):
            n += surf.get_at((x, y))[:3] == colour
    for y in range(rect.top + 1, rect.bottom - 1):
        for x in (rect.left, rect.right - 1):
            n += surf.get_at((x, y))[:3] == colour
    return n


def village_colour(cfg, frame, ident):
    a = next(x for x in (*frame.players, *frame.villagers) if x.id == ident)
    owner = ident if a.kind == "player" else a.leader
    if owner:
        return rgb(cfg.assets.colors.players[owner])
    return rgb(cfg.assets.colors.wanderer)


def assert_selected_centred_and_ringed(cfg, obs, frame, ident):
    assert obs.selected == ident
    assert obs.following is True
    obs.draw(frame, 0.0)
    pos = obs.screen_pos_of(ident)
    assert pos is not None
    tile = obs.camera.tile
    centre = obs.map_rect.center
    vx, vy, vw, vh = obs.camera.visible_tiles()
    for axis, (p, c, start, size, limit) in enumerate(
        ((pos[0], centre[0], vx, vw, frame.width), (pos[1], centre[1], vy, vh, frame.height))
    ):
        off = abs(p - c)
        at_edge = start == 0 or start + size >= limit
        assert off <= 2 * tile or at_edge, (axis, pos, centre)
    colour = village_colour(cfg, frame, ident)
    with_ring = count_ring_pixels(obs, frame, ident, colour)
    obs.following = False
    obs.clear_selection()
    obs.draw(frame, 0.0)
    without = count_ring_pixels(obs, frame, ident, colour)
    assert with_ring > without, (with_ring, without)


def test_AC8_chat_line_click_selects_the_speaker_centres_and_rings(cfg, people, file_db):
    ident = next(a.id for a in people.players if a.id == "player_2")
    add_chat(file_db, 5, ident, [], [], "click this chat")
    obs = make_obs(cfg, file_db)
    obs.draw(people, 0.0)
    html = obs.elements["text_box"].html_text
    assert f'href="select:{ident}"' in html
    link(f"select:{ident}")
    assert obs.pump()
    obs.draw(people, 0.0)
    assert_selected_centred_and_ringed(cfg, obs, people, ident)


def test_AC8_choice_point_row_click_selects_the_player(cfg, people, file_db):
    sql(
        file_db,
        "INSERT INTO choice_points (tick, player_id, situation, x, feeling, tier, thought, "
        "action_json, self_label_json) VALUES (495, 'player_3', 'Hungry', 50.0, 'ok', "
        "'routine', 'hmm', '{\"kind\": \"eat\"}', '{\"label\": \"good\"}')",
    )
    obs = make_obs(cfg, file_db)
    obs.draw(people, 0.0)
    obs.select_tab("Choice points")
    obs.draw(people, 0.0)
    assert 'href="select:player_3"' in obs.elements["text_box"].html_text
    link("select:player_3")
    assert obs.pump()
    obs.draw(people, 0.0)
    assert_selected_centred_and_ringed(cfg, obs, people, "player_3")


def test_AC8_history_row_click_selects_the_first_person_involved(cfg, people, file_db):
    ev = Event(
        tick=3255, payload=Harm(id=1, kind="steal", actor="player_4", victim="player_1", x=9, y=9)
    )
    file_db.append_events([ev])
    rows = history_entries(file_db.events_after(0, ("harm",)), dict(people.names))
    assert rows and rows[0].who[:2] == ("player_4", "player_1")
    obs = make_obs(cfg, file_db)
    obs.draw(people, 0.0)
    obs.select_tab("World history")
    obs.draw(people, 0.0)
    assert 'href="select:player_4"' in obs.elements["text_box"].html_text
    link("select:player_4")
    assert obs.pump()
    obs.draw(people, 0.0)
    assert_selected_centred_and_ringed(cfg, obs, people, "player_4")


def test_AC8_history_row_with_nobody_present_selects_nothing(cfg, people, file_db):
    from ai_island.storage.events import SeasonChanged

    file_db.append_events([Event(tick=100, payload=SeasonChanged(season="summer", year=1))])
    obs = make_obs(cfg, file_db)
    obs.draw(people, 0.0)
    obs.select_tab("World history")
    obs.draw(people, 0.0)
    assert "select:" not in obs.elements["text_box"].html_text
    assert obs.selected is None


@pytest.mark.parametrize("kind", ["player", "villager"])
def test_AC8_map_sprite_left_click_selects_centres_and_rings(cfg, people, kind):
    obs = make_obs(cfg)
    obs.draw(people, 0.0)
    ident = visible_or_scroll(obs, people, kind)
    assert obs.selected is None
    click(obs.screen_pos_of(ident))
    assert obs.pump()
    obs.draw(people, 0.0)
    assert_selected_centred_and_ringed(cfg, obs, people, ident)


def test_AC8_right_click_and_empty_click_clear_the_selection(cfg, people):
    obs = make_obs(cfg)
    obs.draw(people, 0.0)
    ident = visible_or_scroll(obs, people, "player")
    obs.select(ident)
    obs.draw(people, 0.0)
    assert obs.selected == ident
    click(obs.map_rect.center, button=3)
    assert obs.pump()
    assert obs.selected is None
    obs.select(ident)
    obs.draw(people, 0.0)
    empty = None
    for dx in range(-300, 300, 17):
        for dy in range(-300, 300, 19):
            p = (obs.map_rect.centerx + dx, obs.map_rect.centery + dy)
            if (
                obs.person_at(*p) is None
                and obs.map_rect.collidepoint(p)
                and not obs.minimap_rect.collidepoint(p)
            ):
                empty = p
                break
        if empty:
            break
    assert empty
    click(empty)
    assert obs.pump()
    assert obs.selected is None


def test_AC8_arrow_keys_stop_following_but_keep_the_selection(cfg, people):
    import pygame

    obs = make_obs(cfg)
    obs.draw(people, 0.0)
    ident = visible_or_scroll(obs, people, "player")
    obs.select(ident)
    assert obs.following
    key(pygame.K_LEFT)
    assert obs.pump()
    assert obs.following is False
    assert obs.selected == ident


def test_AC8_escape_still_quits_with_or_without_a_selection(cfg, people):
    import pygame

    obs = make_obs(cfg)
    obs.draw(people, 0.0)
    obs.select("player_1")
    key(pygame.K_h)
    assert obs.pump()
    key(pygame.K_ESCAPE)
    assert obs.pump() is False
    obs = make_obs(cfg)
    obs.draw(people, 0.0)
    key(pygame.K_ESCAPE)
    assert obs.pump() is False


def test_AC8_selected_id_not_on_the_map_keeps_the_inspector_and_has_no_ring(cfg, people):
    import dataclasses

    obs = make_obs(cfg)
    obs.draw(people, 0.0)
    victim = people.villagers[0]
    obs.select(victim.id)
    gone = dataclasses.replace(
        people, villagers=tuple(v for v in people.villagers if v.id != victim.id)
    )
    obs.draw(gone, 0.0)
    assert obs.selected == victim.id
    assert obs.screen_pos_of(victim.id) is None
    assert any("not on the map now" in f"{k} {v}" for k, v in obs.inspector_rows())
