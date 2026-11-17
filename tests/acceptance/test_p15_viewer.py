"""Phase 1.5 AC-8 (viewer), AC-14 .. AC-16: sliding sprites, light curve, seasons, screenshots."""

from __future__ import annotations

import dataclasses
import re
import shutil
import subprocess
import sys

import pytest
from conftest import LOGS, ROOT, cli, fresh_run

from ai_island.sim import Simulation
from ai_island.world.clock import Clock, daylight_at, is_night_at
from ai_island.world.view import EntityView, WorldFrame, frame_from_world

DAY = 1440
NOON = 720
TEN_PM = 1320


# ---------------------------------------------------------------- helpers


def ev(**kw):
    base = dict(
        id=1,
        kind="rabbit",
        x=2,
        y=3,
        from_x=2,
        from_y=3,
        to_x=3,
        to_y=3,
        move_start_tick=10,
        move_end_tick=11,
        facing=1,
    )
    base.update(kw)
    return EntityView(**base)


def make_viewer(assets, view):
    import pygame

    pygame.quit()
    from ai_island.observer import Viewer

    return Viewer(assets, view, ROOT)


@pytest.fixture
def viewer(cfg, monkeypatch):
    import pygame

    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    v = make_viewer(cfg.assets, cfg.run.view)
    yield v
    pygame.quit()


@pytest.fixture(scope="module")
def frames(cfg):
    sim = Simulation.new(cfg, 1, players="none")
    sim.run(NOON)
    noon = frame_from_world(sim)
    sim.run(TEN_PM - NOON)
    night = frame_from_world(sim)
    return noon, night


def screen_copy():
    import pygame

    return pygame.display.get_surface().copy()


def brightness(surface):
    import pygame

    r, g, b, _a = pygame.transform.average_color(surface)
    return (r + g + b) / 3


def to_bytes(surface):
    import pygame

    return pygame.image.tobytes(surface, "RGB")


# ---------------------------------------------------------------- AC-8


def test_AC8_slide_position_contract_example():
    from ai_island.observer import slide_position

    e = ev()
    assert slide_position(e, 10, 0.0, 3) == (96, 144)
    assert slide_position(e, 10, 0.5, 3) == (120, 144)
    assert slide_position(e, 10, 1.0, 3) == (144, 144)


def test_AC8_slide_position_multi_tick_progress():
    from ai_island.observer import slide_position

    e = ev(move_start_tick=10, move_end_tick=13)
    assert slide_position(e, 11, 0.5, 3) == (120, 144)  # p = 0.5
    assert slide_position(e, 10, 0.0, 3) == (96, 144)
    assert slide_position(e, 12, 0.0, 1) == (2 * 16 + round(16 * 2 / 3), 3 * 16)
    assert slide_position(e, 12, 0.999, 1)[0] <= 3 * 16


def test_AC8_slide_position_clamps_and_handles_idle_and_directions():
    from ai_island.observer import slide_position

    e = ev()
    assert slide_position(e, 5, 0.0, 2) == (2 * 16 * 2, 3 * 16 * 2)  # before the start
    assert slide_position(e, 40, 0.0, 2) == (3 * 16 * 2, 3 * 16 * 2)  # after the end
    idle = ev(from_x=5, from_y=6, to_x=5, to_y=6, x=5, y=6, move_start_tick=7, move_end_tick=7)
    assert slide_position(idle, 7, 0.5, 4) == (5 * 16 * 4, 6 * 16 * 4)
    still = ev(from_x=5, from_y=6, to_x=5, to_y=6, x=5, y=6, move_start_tick=0, move_end_tick=0)
    assert slide_position(still, 300, 0.2, 1) == (80, 96)
    left = ev(from_x=2, from_y=3, to_x=1, to_y=3)
    assert slide_position(left, 10, 0.5, 3) == ((2 * 16 - 8) * 3, 3 * 16 * 3)
    down = ev(from_x=2, from_y=3, to_x=2, to_y=4)
    assert slide_position(down, 10, 0.5, 1) == (2 * 16, 3 * 16 + 8)
    up = ev(from_x=2, from_y=3, to_x=2, to_y=2)
    assert slide_position(up, 10, 1.0, 1) == (2 * 16, 2 * 16)


def _moving_view(frame, entity, kind_group="animals"):
    return dataclasses.replace(
        frame, tick=10, animals=(entity,) if kind_group == "animals" else (), dogs=()
    )


def _bbox_left(with_entity, without):
    import pygame

    w, h = with_entity.get_size()
    left, top = w, h
    for x in range(w):
        for y in range(h):
            if with_entity.get_at((x, y)) != without.get_at((x, y)):
                left = min(left, x)
                top = min(top, y)
    assert left < w, "sprite not drawn at all"
    del pygame
    return left, top


def test_AC8_viewer_places_sprite_at_start_midpoint_and_end(cfg, frames, monkeypatch):
    import pygame

    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    noon, _night = frames
    entity = ev(kind="wild_dog", x=10, y=10, from_x=10, from_y=10, to_x=11, to_y=10)
    empty = dataclasses.replace(noon, tick=10, animals=(), dogs=())
    moving = _moving_view(noon, entity, "animals")
    shots = {}
    try:
        v = make_viewer(cfg.assets, cfg.run.view)
        v.draw(empty, 0.0)
        base = screen_copy()
        for sub in (0.0, 0.5, 1.0):
            v.draw(moving, sub)
            shots[sub] = _bbox_left(screen_copy(), base)
        full = shots[1.0][0] - shots[0.0][0]
        half = shots[0.5][0] - shots[0.0][0]
        assert full > 0 and full % 16 == 0, shots  # one tile = 16 * scale pixels
        assert half * 2 == full, shots  # whole-pixel midpoint
        assert shots[0.0][1] == shots[0.5][1] == shots[1.0][1]  # y does not change
    finally:
        pygame.quit()


def test_AC8_sprite_is_flipped_when_facing_left(cfg, frames, monkeypatch):
    import pygame

    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    noon, _ = frames
    idle = dict(from_x=10, from_y=10, to_x=10, to_y=10, x=10, y=10, move_start_tick=0)
    right = _moving_view(noon, ev(kind="wild_dog", facing=1, move_end_tick=0, **idle))
    left = _moving_view(noon, ev(kind="wild_dog", facing=-1, move_end_tick=0, **idle))
    try:
        v = make_viewer(cfg.assets, cfg.run.view)
        v.draw(right, 0.0)
        a = to_bytes(screen_copy())
        v.draw(left, 0.0)
        b = to_bytes(screen_copy())
        assert a != b
    finally:
        pygame.quit()


def test_AC8_worldframe_has_from_to_start_end_for_every_moving_entity(cfg):
    sim = Simulation.new(cfg, 5, players="none")
    w = sim.world
    for _ in range(1500):
        sim.step()
        if any(e.move_start_tick < w.tick < e.move_end_tick for e in w.dogs):
            break
    frame = frame_from_world(sim)
    assert isinstance(frame, WorldFrame)
    fields = {f.name for f in dataclasses.fields(EntityView)}
    assert {
        "id",
        "kind",
        "x",
        "y",
        "from_x",
        "from_y",
        "to_x",
        "to_y",
        "move_start_tick",
        "move_end_tick",
        "facing",
    } <= fields
    by_id = {a.id: a for k in w.animals for a in w.animals[k]}
    assert len(frame.animals) == len(by_id)
    mid = 0
    for view in frame.animals:
        a = by_id[view.id]
        assert view.kind == a.kind
        assert (view.x, view.y) == (a.x, a.y)
        if a.kind == "nest_eggs":
            assert (view.from_x, view.from_y, view.to_x, view.to_y) == (a.x, a.y, a.x, a.y)
            assert view.move_start_tick == view.move_end_tick == 0 and view.facing == 1
            continue
        assert (view.from_x, view.from_y, view.to_x, view.to_y) == (
            a.from_x,
            a.from_y,
            a.to_x,
            a.to_y,
        )
        assert (view.move_start_tick, view.move_end_tick, view.facing) == (
            a.move_start_tick,
            a.move_end_tick,
            a.facing,
        )
        assert view.facing in (-1, 1)
        if view.move_start_tick < frame.tick < view.move_end_tick:
            mid += 1
            assert (view.from_x, view.from_y) != (view.to_x, view.to_y)
            assert (view.x, view.y) == (view.from_x, view.from_y)
    assert mid > 0
    assert len(frame.dogs) == len(w.dogs)
    for view, d in zip(frame.dogs, sorted(w.dogs, key=lambda d: d.id), strict=True):
        assert (view.id, view.x, view.y) == (d.id, d.x, d.y)
        assert (view.from_x, view.from_y, view.to_x, view.to_y) == (
            d.from_x,
            d.from_y,
            d.to_x,
            d.to_y,
        )
        assert (view.move_start_tick, view.move_end_tick) == (d.move_start_tick, d.move_end_tick)
    for view in frame.plants:
        assert (view.from_x, view.from_y, view.to_x, view.to_y) == (view.x, view.y, view.x, view.y)
        assert view.move_start_tick == view.move_end_tick == 0 and view.facing == 1


def test_AC8_frame_daylight_matches_clock(cfg):
    sim = Simulation.new(cfg, 1, players="none")
    for target in (0, 400, 410, 425, NOON, 1150, 1170, 1190, TEN_PM, 1439):
        sim.run(target - sim.world.tick)
        frame = frame_from_world(sim)
        assert frame.daylight == pytest.approx(daylight_at(float(sim.world.tick), cfg.world.clock))
        assert frame.tick == sim.world.tick


# ---------------------------------------------------------------- AC-14


def test_AC14_daylight_curve_with_default_clock(cfg):
    ck = cfg.world.clock
    assert (ck.dawn_minutes, ck.dusk_minutes) == (60, 60)
    assert daylight_at(float(NOON), ck) == 1.0
    assert daylight_at(float(7 * 60), ck) == 1.0
    assert daylight_at(float(19 * 60), ck) == 1.0
    for t in range(20 * 60, DAY):
        assert daylight_at(float(t), ck) == 0.0, t
    for t in range(0, 6 * 60):
        assert daylight_at(float(t), ck) == 0.0, t
    assert daylight_at(float(6 * 60), ck) == pytest.approx(0.0)
    assert daylight_at(float(6 * 60 + 30), ck) == pytest.approx(0.5)
    assert daylight_at(float(6 * 60 + 15), ck) == pytest.approx(0.25)
    assert daylight_at(float(7 * 60), ck) == pytest.approx(1.0)
    assert daylight_at(float(19 * 60 + 30), ck) == pytest.approx(0.5)
    assert daylight_at(float(19 * 60 + 45), ck) == pytest.approx(0.25)
    assert daylight_at(float(20 * 60), ck) == pytest.approx(0.0)
    assert daylight_at(6 * 60 + 29.5, ck) == pytest.approx(29.5 / 60, abs=1e-6)


def test_AC14_dawn_rises_dusk_falls_steadily(cfg):
    ck = cfg.world.clock
    dawn = [daylight_at(float(t), ck) for t in range(6 * 60, 7 * 60 + 1)]
    dusk = [daylight_at(float(t), ck) for t in range(19 * 60, 20 * 60 + 1)]
    assert all(b > a for a, b in zip(dawn, dawn[1:], strict=False))
    assert all(b < a for a, b in zip(dusk, dusk[1:], strict=False))
    steps = [abs(b - a) for a, b in zip(dawn + dusk, (dawn + dusk)[1:], strict=False)]
    assert all(0 <= v < 0.05 for v in steps if v < 0.5)  # no jumps: one minute is 1/60
    for v in dawn + dusk:
        assert 0.0 <= v <= 1.0


def test_AC14_fractional_ticks_are_continuous(cfg):
    ck = cfg.world.clock
    a = daylight_at(6 * 60 + 10.25, ck)
    b = daylight_at(6 * 60 + 10.75, ck)
    assert daylight_at(6 * 60 + 10.0, ck) < a < b < daylight_at(6 * 60 + 11.0, ck)


def test_AC14_curve_follows_the_clock_config(cfg):
    ck = cfg.world.clock.model_copy(update={"dawn_minutes": 120, "dusk_minutes": 30})
    assert daylight_at(float(6 * 60 + 60), ck) == pytest.approx(0.5)
    assert daylight_at(float(7 * 60), ck) == pytest.approx(0.5)
    assert daylight_at(float(19 * 60 + 45), ck) == pytest.approx(0.5)
    assert daylight_at(float(19 * 60 + 29), ck) == 1.0
    assert daylight_at(float(8 * 60), ck) == pytest.approx(1.0)


def test_AC14_is_night_unchanged_from_phase_1(cfg):
    ck = cfg.world.clock
    start, end = ck.night_start_hour, ck.night_end_hour
    for t in range(0, DAY, 7):
        hour = t // 60
        expected = (hour >= start) or (hour < end)
        assert is_night_at(t, ck) == expected, t
        assert Clock.at(t, ck).is_night == expected
    assert is_night_at(19 * 60 + 59, ck) is False  # dusk is not night
    assert is_night_at(20 * 60, ck) is True
    assert is_night_at(6 * 60, ck) is False


def test_AC14_light_alpha_values(cfg):
    from ai_island.observer import light_alpha

    light = cfg.assets.light
    assert light_alpha(1.0, "clear", light) == 0
    assert light_alpha(1.0, "drought", light) == 0
    assert light_alpha(0.0, "clear", light) == light.night_alpha
    assert light_alpha(0.5, "clear", light) == round(light.night_alpha * 0.5)
    assert light_alpha(1.0, "rain", light) == light.rain_alpha
    assert light_alpha(1.0, "storm", light) == light.storm_alpha
    assert light_alpha(0.0, "storm", light) == light.night_alpha + light.storm_alpha
    loud = light.model_copy(update={"night_alpha": 250, "storm_alpha": 60})
    assert light_alpha(0.0, "storm", loud) == 255


def test_AC14_light_layer_clear_at_noon_darkest_at_night_steady_between(cfg):
    from ai_island.observer import light_alpha

    ck, light = cfg.world.clock, cfg.assets.light
    alpha = [light_alpha(daylight_at(float(t), ck), "clear", light) for t in range(DAY)]
    assert alpha[NOON] == 0
    assert max(alpha) == light.night_alpha
    for t in list(range(20 * 60, DAY)) + list(range(0, 6 * 60)):
        assert alpha[t] == light.night_alpha, t
    dawn = alpha[6 * 60 : 7 * 60 + 1]
    dusk = alpha[19 * 60 : 20 * 60 + 1]
    assert all(b <= a for a, b in zip(dawn, dawn[1:], strict=False))
    assert all(b >= a for a, b in zip(dusk, dusk[1:], strict=False))
    assert dawn[0] == light.night_alpha and dawn[-1] == 0
    assert dusk[0] == 0 and dusk[-1] == light.night_alpha
    assert max(abs(b - a) for a, b in zip(dawn, dawn[1:], strict=False)) <= 5


# ---------------------------------------------------------------- AC-15


def test_AC15_autumn_tree_layer_and_colours(viewer, cfg):
    assert viewer.terrain_layers("tree", "autumn", "clear") == ("tree_autumn",)
    assert viewer.terrain_layers("tree", "summer", "clear") == ("tree",)
    assert viewer.terrain_layers("tree", "spring", "clear") == ("tree",)
    sprites = viewer.sprites
    green = "#38d973"  # the Kenney green
    autumn = {c.lower() for c in cfg.assets.colors.autumn}

    def cols(s):
        out = set()
        for x in range(16):
            for y in range(16):
                p = s.get_at((x, y))
                if p[3]:
                    out.add(f"#{p[0]:02x}{p[1]:02x}{p[2]:02x}")
        return out

    tree, tree_autumn = cols(sprites["tree"]), cols(sprites["tree_autumn"])
    assert green.lower() in tree
    assert green.lower() not in tree_autumn
    assert tree_autumn & autumn
    for key in cfg.assets.colors.autumn_items:
        assert f"{key}_autumn" in sprites, key


def test_AC15_winter_shows_snow(viewer):
    for terrain in ("grass", "tree"):
        assert "snow" in viewer.terrain_layers(terrain, "winter", "clear"), terrain
        assert "snow" not in viewer.terrain_layers(terrain, "summer", "clear")
        assert "snow" not in viewer.terrain_layers(terrain, "autumn", "clear")
    assert viewer.terrain_layers("tree", "winter", "clear")[0] == "tree"
    assert "snow" in viewer.sprites


def test_AC15_drought_changes_grass_ground_colour(viewer, cfg):
    normal = viewer.ground_color("grass", "clear")
    dry = viewer.ground_color("grass", "drought")
    assert normal is not None and dry is not None and normal != dry
    h = cfg.assets.colors.drought_ground
    assert dry == tuple(int(h[i : i + 2], 16) for i in (1, 3, 5))
    assert viewer.ground_color("grass", "rain") == normal
    assert viewer.ground_color("lake", "drought") == viewer.ground_color("lake", "clear")


def test_AC15_mono_has_no_ground_colour(cfg, monkeypatch):
    import pygame

    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    try:
        v = make_viewer(cfg.assets.model_copy(update={"palette": "mono"}), cfg.run.view)
        assert v.ground_color("grass", "clear") is None
        assert v.ground_color("grass", "drought") is None
        assert v.terrain_layers("tree", "autumn", "clear") == ("tree_autumn",)
    finally:
        pygame.quit()


def test_AC15_season_and_weather_visibly_change_the_drawn_map(viewer, frames):
    noon, _ = frames
    shots = {}
    for name, season, weather in (
        ("summer", "summer", "clear"),
        ("autumn", "autumn", "clear"),
        ("winter", "winter", "clear"),
        ("drought", "summer", "drought"),
    ):
        viewer.draw(dataclasses.replace(noon, season=season, weather=weather), 0.0)
        shots[name] = to_bytes(screen_copy())
    assert len(set(shots.values())) == 4


def test_AC15_cached_terrain_is_never_stale(cfg, frames, monkeypatch):
    """A viewer that already drew other frames and scrolled shows what a fresh viewer shows."""
    import pygame

    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    noon, _ = frames
    changed_row = tuple("sand" if i % 2 else "lake" for i in range(noon.width))
    terrain = tuple(changed_row if y == 12 else row for y, row in enumerate(noon.terrain))
    sequence = [
        noon,
        dataclasses.replace(noon, season="autumn"),
        dataclasses.replace(noon, season="winter", terrain=terrain),
        dataclasses.replace(noon, weather="drought", terrain=terrain),
        dataclasses.replace(noon, weather="clear", terrain=noon.terrain),
    ]

    def press(key):
        pygame.event.clear()
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=key, mod=0, unicode=""))

    try:
        cached = make_viewer(cfg.assets, cfg.run.view)
        got = []
        for i, f in enumerate(sequence):
            cached.draw(f, 0.0)
            if i == 2:
                press(pygame.K_DOWN)
                cached.pump()
                press(pygame.K_RIGHT)
                cached.pump()
            cached.draw(f, 0.0)
            got.append(to_bytes(screen_copy()))
        for i, f in enumerate(sequence):
            fresh = make_viewer(cfg.assets, cfg.run.view)
            if i >= 2:
                for key in (pygame.K_DOWN, pygame.K_RIGHT):
                    press(key)
                    fresh.pump()
            fresh.draw(f, 0.0)
            assert to_bytes(screen_copy()) == got[i], f"frame {i} differs from a fresh render"
    finally:
        pygame.quit()


# ---------------------------------------------------------------- AC-16 / title / fps / sprites


def test_AC16_title_format_and_fps(viewer, frames):
    import pygame

    noon, _ = frames
    for _ in range(6):
        viewer.draw(noon, 0.0)
    title = pygame.display.get_caption()[0]
    assert re.fullmatch(r"AI Island - .+ - speed x[0-9.]+ - [0-9]+(\.[0-9]+)? fps", title), title
    assert isinstance(viewer.fps, float) and viewer.fps > 0


def test_AC16_viewer_sprites_scale_one_and_all_loaded(viewer, cfg):
    sprites = viewer.sprites
    assert set(cfg.assets.items) <= set(sprites)
    assert all(s.get_size() == (16, 16) for s in sprites.values())


@pytest.mark.parametrize("palette", ["color", "mono"])
def test_AC16_night_is_darker_than_noon_same_frame(cfg, frames, monkeypatch, palette):
    import pygame

    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    noon, _ = frames
    day = dataclasses.replace(noon, daylight=1.0, hour=12, minute=0, is_night=False)
    dark = dataclasses.replace(noon, daylight=0.0, hour=22, minute=0, is_night=True)
    try:
        v = make_viewer(cfg.assets.model_copy(update={"palette": palette}), cfg.run.view)
        v.draw(day, 0.0)
        b_day = brightness(screen_copy())
        v.draw(dark, 0.0)
        b_night = brightness(screen_copy())
    finally:
        pygame.quit()
    LOGS.mkdir(exist_ok=True)
    with (LOGS / "p15_ac16_brightness.txt").open("a", encoding="utf-8") as fh:
        ratio = b_night / b_day
        fh.write(f"viewer API {palette}: noon {b_day:.1f} night {b_night:.1f} ratio {ratio:.2f}\n")
    assert b_night <= 0.8 * b_day, (b_night, b_day)
    assert b_night > 0


def test_AC16_dusk_is_between_noon_and_night(cfg, frames, monkeypatch):
    import pygame

    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    noon, _ = frames
    try:
        v = make_viewer(cfg.assets, cfg.run.view)
        vals = []
        for daylight in (1.0, 0.75, 0.5, 0.25, 0.0):
            v.draw(dataclasses.replace(noon, daylight=daylight), 0.0)
            vals.append(brightness(screen_copy()))
    finally:
        pygame.quit()
    assert all(b < a for a, b in zip(vals, vals[1:], strict=False)), vals


def _shot_brightness(path):
    import pygame

    pygame.init()
    return brightness(pygame.image.load(str(path)))


def _mono_config(tmp_path):
    d = tmp_path / "config_mono"
    shutil.copytree(ROOT / "config", d)
    p = d / "assets.toml"
    text = p.read_text(encoding="utf-8-sig")
    assert 'palette = "color"' in text
    p.write_text(text.replace('palette = "color"', 'palette = "mono"', 1), encoding="utf-8")
    return d


_MONO_RUNNER = (
    "import sys, pathlib; import ai_island.cli as c; "
    "c.CONFIG_DIR = pathlib.Path(sys.argv[1]); sys.exit(c.main(sys.argv[2:]))"
)


def _view_mono(cfgdir, run, ticks, out):
    import os

    env = dict(os.environ, SDL_VIDEODRIVER="dummy")
    return subprocess.run(
        [sys.executable, "-c", _MONO_RUNNER, str(cfgdir), "view", "--run", run]
        + ["--ticks", str(ticks), "--screenshot", out],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )


def test_AC16_cli_screenshots_colour_and_mono_noon_vs_night(tmp_path):
    run = "acc_p15_shots"
    fresh_run(run)
    try:
        assert cli("new", run, "--seed", "1").returncode == 0
        results = {}
        for ticks, label in ((NOON, "noon"), (TEN_PM, "night")):
            out = f"logs/p15_color_{label}.png"
            (ROOT / out).unlink(missing_ok=True)
            r = cli("view", "--run", run, "--ticks", str(ticks), "--screenshot", out)
            assert r.returncode == 0, r.stderr
            assert (ROOT / out).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
            results[("color", label)] = _shot_brightness(ROOT / out)
        mono_cfg = _mono_config(tmp_path)
        for ticks, label in ((NOON, "noon"), (TEN_PM, "night")):
            out = f"logs/p15_mono_{label}.png"
            (ROOT / out).unlink(missing_ok=True)
            r = _view_mono(mono_cfg, run, ticks, out)
            assert r.returncode == 0, r.stderr
            assert (ROOT / out).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
            results[("mono", label)] = _shot_brightness(ROOT / out)
        r = cli("view", "--run", run, "--ticks", "600", "--screenshot", "logs/view.png")
        assert r.returncode == 0, r.stderr
        r = _view_mono(mono_cfg, run, 600, "logs/view_mono.png")
        assert r.returncode == 0, r.stderr
        with (LOGS / "p15_ac16_brightness.txt").open("a", encoding="utf-8") as fh:
            for pal in ("color", "mono"):
                n, d = results[(pal, "night")], results[(pal, "noon")]
                fh.write(f"cli screenshots {pal}: noon {d:.1f} night {n:.1f} ratio {n / d:.2f}\n")
        for pal in ("color", "mono"):
            assert results[(pal, "night")] <= 0.8 * results[(pal, "noon")], (pal, results)
        # the two palettes really look different
        assert results[("color", "noon")] != results[("mono", "noon")]
    finally:
        shutil.rmtree(ROOT / "runs" / run, ignore_errors=True)
