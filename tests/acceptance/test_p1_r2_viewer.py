"""Phase 1 Round 2 checks: viewer speed, window sizing, grass sprite, new [view] keys."""

from __future__ import annotations

import shutil

import pytest
from conftest import ROOT, load_toml

from ai_island.config import ConfigError, load_config


def _copy_config(tmp_path):
    d = tmp_path / "config"
    shutil.copytree(ROOT / "config", d)
    return d


# ---------------------------------------------------------------- config keys


def test_AC4_run_toml_view_has_round2_keys(cfg):
    view = cfg.run.view
    assert view.min_visible_tiles > 0
    assert view.max_speed >= view.speed
    assert view.window_margin >= 0
    raw = load_toml(ROOT / "config" / "run.toml")["view"]
    for key in ("min_visible_tiles", "max_speed", "window_margin"):
        assert key in raw, key


BAD_VIEW = [
    ("min_visible_tiles = 36", 'min_visible_tiles = "36"', "min_visible_tiles"),
    ("min_visible_tiles = 36", "min_visible_tiles = 0", "min_visible_tiles"),
    ("max_speed = 512.0", 'max_speed = "fast"', "max_speed"),
    ("max_speed = 512.0", "max_speed = 0.5", "max_speed"),
    ("window_margin = 80", 'window_margin = "80"', "window_margin"),
    ("window_margin = 80", "window_margin = -1", "window_margin"),
]


@pytest.mark.parametrize("old,new,key", BAD_VIEW)
def test_AC4_bad_view_value_fails_naming_file_and_key(tmp_path, old, new, key):
    d = _copy_config(tmp_path)
    p = d / "run.toml"
    text = p.read_text(encoding="utf-8-sig")
    assert old in text, old
    p.write_text(text.replace(old, new, 1), encoding="utf-8")
    with pytest.raises(ConfigError) as ei:
        load_config(d)
    msg = str(ei.value)
    assert "run.toml" in msg and key in msg, msg


# ---------------------------------------------------------------- viewer


@pytest.fixture
def viewer(cfg, monkeypatch):
    import pygame

    monkeypatch.setenv("SDL_VIDEODRIVER", "dummy")
    pygame.quit()
    from ai_island.observer import Viewer

    v = Viewer(cfg.assets, cfg.run.view, ROOT)
    yield v
    pygame.quit()


def _press(key):
    import pygame

    pygame.event.clear()
    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=key, mod=0, unicode=""))


def test_AC21_viewer_speed_starts_at_config(viewer, cfg):
    assert viewer.speed == cfg.run.view.speed


def test_AC21_viewer_plus_doubles_minus_halves(viewer, cfg):
    import pygame

    start = viewer.speed
    _press(pygame.K_PLUS)
    assert viewer.pump()
    assert viewer.speed == start * 2
    _press(pygame.K_EQUALS)
    viewer.pump()
    assert viewer.speed == start * 4
    _press(pygame.K_KP_PLUS)
    viewer.pump()
    assert viewer.speed == start * 8
    _press(pygame.K_MINUS)
    viewer.pump()
    assert viewer.speed == start * 4
    _press(pygame.K_KP_MINUS)
    viewer.pump()
    assert viewer.speed == start * 2


def test_AC21_viewer_speed_clamped(viewer, cfg):
    import pygame

    v = cfg.run.view
    for _ in range(40):
        _press(pygame.K_PLUS)
        viewer.pump()
    assert viewer.speed == v.max_speed
    for _ in range(60):
        _press(pygame.K_MINUS)
        viewer.pump()
    assert viewer.speed == pytest.approx(v.speed / 8)


def test_AC21_title_shows_speed_and_dummy_window_fallback(viewer, cfg, sim):
    import pygame

    from ai_island.world.view import frame_from_world

    viewer.draw(frame_from_world(sim))
    assert "speed x" in pygame.display.get_caption()[0]
    assert pygame.display.get_surface().get_size() == (
        cfg.run.view.window_width,
        cfg.run.view.window_height,
    )
    scale = viewer._scale  # no public accessor in the contract
    assert isinstance(scale, int) and scale >= 1


# ---------------------------------------------------------------- grass


def test_AC20_grass_mostly_white_and_listed_missing(cfg):
    import pygame

    from ai_island.observer import load_sprites

    pygame.init()
    sprites = load_sprites(cfg.assets, ROOT, "mono")
    s = sprites["grass"]
    black = sum(
        1 for x in range(16) for y in range(16) if tuple(s.get_at((x, y))) == (0, 0, 0, 255)
    )
    assert black <= 16, black
    assert "grass" in load_toml(ROOT / "config" / "assets.toml")["missing"]["items"]
