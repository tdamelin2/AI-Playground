"""Phase 1.5 AC-1, AC-9 .. AC-13, AC-17, AC-18: config shape, asset mapping, sprites, colours."""

from __future__ import annotations

import ast
import re
import shutil
import subprocess

import pytest
from conftest import ROOT, load_toml

from ai_island.config import TERRAIN_KEYS, ConfigError, load_config

MOVING = ["rabbit", "deer", "boar", "fish", "bird", "goat", "chicken"]
MOVE_KEYS = [
    "minutes_per_tile",
    "bout_min_tiles",
    "bout_max_tiles",
    "rest_min_minutes",
    "rest_max_minutes",
]
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _copy_config(tmp_path):
    d = tmp_path / "config"
    shutil.copytree(ROOT / "config", d)
    return d


def _edit(d, fname, old, new):
    p = d / fname
    text = p.read_text(encoding="utf-8-sig")
    assert old in text, f"test setup: {old!r} not in {fname}"
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


def _section_lines(fname, section):
    """Raw lines of one [section] of a toml file (up to the next header)."""
    lines = (ROOT / "config" / fname).read_text(encoding="utf-8-sig").splitlines()
    out, inside = [], False
    for line in lines:
        s = line.strip()
        if s.startswith("["):
            inside = s == f"[{section}]"
            continue
        if inside:
            out.append(line)
    return out


# ---------------------------------------------------------------- AC-1


@pytest.mark.parametrize("kind", MOVING + ["wild_dog"])
def test_AC1_moving_kind_has_movement_keys_with_reason_comments(kind):
    section = "dogs" if kind == "wild_dog" else f"animals.{kind}"
    lines = _section_lines("balance.toml", section)
    for key in MOVE_KEYS:
        match = [ln for ln in lines if re.match(rf"\s*{key}\s*=", ln)]
        assert len(match) == 1, (kind, key)
        assert "#" in match[0], f"{kind}.{key} has no reason comment"
    bal = load_toml(ROOT / "config" / "balance.toml")
    entry = bal["dogs"] if kind == "wild_dog" else bal["animals"][kind]
    assert entry["bout_min_tiles"] <= entry["bout_max_tiles"]
    assert entry["rest_min_minutes"] <= entry["rest_max_minutes"]
    assert "move_interval" not in entry and "move_chance" not in entry
    assert "base_move_chance" not in entry


@pytest.mark.parametrize("kind", ["rabbit", "deer", "goat", "chicken", "bird"])
def test_AC1_flee_key_with_comment_and_faster_than_wander(kind):
    lines = _section_lines("balance.toml", f"animals.{kind}")
    match = [ln for ln in lines if re.match(r"\s*flee_minutes_per_tile\s*=", ln)]
    assert len(match) == 1 and "#" in match[0]
    e = load_toml(ROOT / "config" / "balance.toml")["animals"][kind]
    assert e["flee_minutes_per_tile"] < e["minutes_per_tile"]


def test_AC1_nest_eggs_does_not_move(cfg):
    e = load_toml(ROOT / "config" / "balance.toml")["animals"]["nest_eggs"]
    assert e["moves"] is False
    assert not ({*MOVE_KEYS, "flee_minutes_per_tile"} & set(e))
    assert cfg.balance.animals["nest_eggs"].moves is False


@pytest.mark.parametrize("key", MOVE_KEYS)
@pytest.mark.parametrize("bad", ["0", "-3", '"x"'])
def test_AC1_bad_animal_movement_value_fails(tmp_path, key, bad):
    d = _copy_config(tmp_path)
    text = (d / "balance.toml").read_text(encoding="utf-8-sig")
    m = re.search(rf"(\[animals\.rabbit\].*?)({key}\s*=\s*)(\d+)", text, re.S)
    assert m
    new = text[: m.start(3)] + bad + text[m.end(3) :]
    (d / "balance.toml").write_text(new, encoding="utf-8")
    with pytest.raises(ConfigError) as ei:
        load_config(d)
    assert "balance.toml" in str(ei.value) and key in str(ei.value), str(ei.value)


@pytest.mark.parametrize("key", MOVE_KEYS)
def test_AC1_missing_animal_movement_value_fails(tmp_path, key):
    d = _copy_config(tmp_path)
    text = (d / "balance.toml").read_text(encoding="utf-8-sig")
    m = re.search(rf"(\[animals\.goat\].*?)(^{key}\s*=.*?$)", text, re.S | re.M)
    assert m
    (d / "balance.toml").write_text(text[: m.start(2)] + text[m.end(2) :], encoding="utf-8")
    with pytest.raises(ConfigError) as ei:
        load_config(d)
    assert "balance.toml" in str(ei.value) and key in str(ei.value), str(ei.value)


@pytest.mark.parametrize("key", MOVE_KEYS)
def test_AC1_bad_dog_movement_value_fails(tmp_path, key):
    d = _copy_config(tmp_path)
    text = (d / "balance.toml").read_text(encoding="utf-8-sig")
    m = re.search(rf"(\[dogs\].*?)({key}\s*=\s*)(\d+)", text, re.S)
    assert m
    (d / "balance.toml").write_text(text[: m.start(3)] + "0" + text[m.end(3) :], encoding="utf-8")
    with pytest.raises(ConfigError) as ei:
        load_config(d)
    assert "balance.toml" in str(ei.value) and key in str(ei.value), str(ei.value)


def test_AC1_min_above_max_fails(tmp_path):
    d = _copy_config(tmp_path)
    _edit(d, "balance.toml", "rest_min_minutes = 20 ", "rest_min_minutes = 999 ")
    with pytest.raises(ConfigError) as ei:
        load_config(d)
    assert "balance.toml" in str(ei.value) and "rest_m" in str(ei.value), str(ei.value)


def test_AC1_flee_not_faster_fails(tmp_path):
    d = _copy_config(tmp_path)
    _edit(d, "balance.toml", "flee_minutes_per_tile = 1 ", "flee_minutes_per_tile = 9 ")
    with pytest.raises(ConfigError) as ei:
        load_config(d)
    assert "balance.toml" in str(ei.value) and "flee_minutes_per_tile" in str(ei.value)


def test_AC1_old_keys_rejected(tmp_path):
    d = _copy_config(tmp_path)
    _edit(d, "balance.toml", "[animals.rabbit]", "[animals.rabbit]\nmove_interval = 3")
    with pytest.raises(ConfigError) as ei:
        load_config(d)
    assert "balance.toml" in str(ei.value) and "move_interval" in str(ei.value)


def test_AC1_nest_eggs_with_movement_key_fails(tmp_path):
    d = _copy_config(tmp_path)
    _edit(d, "balance.toml", "moves = false ", "moves = false\nminutes_per_tile = 3 ")
    with pytest.raises(ConfigError) as ei:
        load_config(d)
    assert "balance.toml" in str(ei.value) and "minutes_per_tile" in str(ei.value)


def test_AC1_movement_step_ticks_must_be_one(tmp_path):
    d = _copy_config(tmp_path)
    _edit(d, "balance.toml", "movement_step_ticks = 1 ", "movement_step_ticks = 2 ")
    with pytest.raises(ConfigError) as ei:
        load_config(d)
    assert "balance.toml" in str(ei.value) and "movement_step_ticks" in str(ei.value)


def test_AC1_dog_multipliers_still_present_and_at_least_one(cfg):
    d = load_toml(ROOT / "config" / "balance.toml")["dogs"]
    assert d["night_multiplier"] >= 1 and d["winter_multiplier"] >= 1
    assert cfg.balance.dogs.night_multiplier == d["night_multiplier"]
    assert cfg.balance.movement.max_start_share == 0.25


def test_AC1_dawn_dusk_must_fit(tmp_path):
    d = _copy_config(tmp_path)
    _edit(d, "world.toml", "dawn_minutes = 60 ", "dawn_minutes = 900 ")
    with pytest.raises(ConfigError) as ei:
        load_config(d)
    assert "world.toml" in str(ei.value), str(ei.value)


# ---------------------------------------------------------------- AC-9


def _concept_items():
    from test_p1_assets_cli import CONCEPTS

    return CONCEPTS


def test_AC9_every_asset_list_item_has_an_entry_with_valid_source(cfg):
    raw = load_toml(ROOT / "config" / "assets.toml")
    items = raw["items"]
    assert len(items) >= 126
    for name, subs, minimum in _concept_items():
        keys = [k for k in items if all(s in k for s in subs)]
        assert len(keys) >= minimum, (name, keys)
    for key, item in items.items():
        assert item["source"] in ("kenney", "tiny_creatures", "code"), key


def _png_info(path):
    import pygame

    pygame.init()
    if pygame.display.get_surface() is None:
        pygame.display.set_mode((1, 1))
    return pygame.image.load(str(path)).convert_alpha()


def _tile_rect(sheet, col, row):
    step = sheet["tile_size"] + sheet["gap"]
    return col * step, row * step, sheet["tile_size"], sheet["tile_size"]


@pytest.mark.parametrize("sheet_name", ["kenney", "tiny_creatures"])
def test_AC9_sheet_indices_inside_image_and_tiles_exist(sheet_name):
    raw = load_toml(ROOT / "config" / "assets.toml")
    sheet = raw["sheets"][sheet_name]
    path = ROOT / sheet["path"]
    assert path.is_file()
    img = _png_info(path)
    w, h = img.get_size()
    for key, item in raw["items"].items():
        if item["source"] != sheet_name:
            continue
        assert 0 <= item["col"] < sheet["columns"], key
        assert 0 <= item["row"] < sheet["rows"], key
        x, y, tw, th = _tile_rect(sheet, item["col"], item["row"])
        assert x + tw <= w and y + th <= h, (key, x, y, w, h)
        if sheet_name == "tiny_creatures":
            crop = img.subsurface((x, y, tw, th))
            assert any(crop.get_at((i, j))[3] > 0 for i in range(tw) for j in range(th)), (
                f"{key}: empty Tiny Creatures tile"
            )


def test_AC9_code_items_are_exactly_the_missing_list(cfg):
    raw = load_toml(ROOT / "config" / "assets.toml")
    code = {k for k, v in raw["items"].items() if v["source"] == "code"}
    assert set(raw["missing"]["items"]) == code
    assert set(cfg.assets.missing.items) == code


# ---------------------------------------------------------------- AC-10


@pytest.mark.parametrize(
    "key", ["rabbit", "deer", "boar", "goat", "chicken", "bird", "fish", "wild_dog"]
)
def test_AC10_animal_uses_tiny_creatures_or_has_a_comment(key):
    path = ROOT / "config" / "assets.toml"
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    raw = load_toml(path)
    if raw["items"][key]["source"] == "tiny_creatures":
        return
    idx = next(i for i, ln in enumerate(lines) if ln.strip() == f"[items.{key}]")
    block = lines[max(0, idx - 3) : idx + 6]
    assert any("#" in ln and len(ln.split("#", 1)[1].strip()) > 8 for ln in block), (
        f"{key} is not Tiny Creatures and has no comment saying why"
    )


# ---------------------------------------------------------------- AC-11


def test_AC11_colour_sheet_is_colored_transparent(cfg):
    assert cfg.assets.sheets.kenney.path.replace("\\", "/").endswith(
        "kenney_1bit/Tilesheet/colored-transparent.png"
    )


def test_AC11_kenney_shapes_equal_monochrome_shapes(cfg):
    colour = _png_info(ROOT / cfg.assets.sheets.kenney.path)
    mono = _png_info(ROOT / "assets/kenney_1bit/Tilesheet/monochrome-transparent.png")
    assert colour.get_size() == mono.get_size()
    sheet = load_toml(ROOT / "config" / "assets.toml")["sheets"]["kenney"]
    bad = []
    for key, item in cfg.assets.items.items():
        if item.source != "kenney":
            continue
        x, y, w, h = _tile_rect(sheet, item.col, item.row)
        c, m = colour.subsurface((x, y, w, h)), mono.subsurface((x, y, w, h))
        shape_c = {(i, j) for i in range(w) for j in range(h) if c.get_at((i, j))[3] > 0}
        shape_m = {(i, j) for i in range(w) for j in range(h) if m.get_at((i, j))[3] > 0}
        if shape_c != shape_m:
            bad.append(key)
    assert not bad, bad


# ---------------------------------------------------------------- AC-12


def _kenney_palette_from_sheets():
    cols = set()
    ct = _png_info(ROOT / "assets/kenney_1bit/Tilesheet/colored-transparent.png")
    for i in range(ct.get_width()):
        for j in range(ct.get_height()):
            r, g, b, a = ct.get_at((i, j))
            if a > 0:
                assert a == 255
                cols.add(f"#{r:02x}{g:02x}{b:02x}")
    c = _png_info(ROOT / "assets/kenney_1bit/Tilesheet/colored.png")
    r, g, b, _a = c.get_at((0, 0))
    cols.add(f"#{r:02x}{g:02x}{b:02x}")
    return cols


def test_AC12_recorded_kenney_palette_equals_the_sheet_colours(cfg):
    recorded = [c.lower() for c in cfg.assets.colors.kenney_palette]
    assert len(recorded) == 8 and len(set(recorded)) == 8
    assert set(recorded) == _kenney_palette_from_sheets()


def _hex(px):
    return f"#{px[0]:02x}{px[1]:02x}{px[2]:02x}"


def _sprite_colours(surf):
    out = set()
    alphas = set()
    for i in range(surf.get_width()):
        for j in range(surf.get_height()):
            px = surf.get_at((i, j))
            alphas.add(px[3])
            if px[3] > 0:
                out.add(_hex(px))
    return out, alphas


def test_AC12_colour_sprites_16px_palette_only(cfg):
    import pygame

    from ai_island.observer import load_sprites

    pygame.init()
    sprites = load_sprites(cfg.assets, ROOT, "color")
    assert set(cfg.assets.items) <= set(sprites)
    palette = {c.lower() for c in cfg.assets.colors.kenney_palette}
    for key, surf in sprites.items():
        assert surf.get_size() == (16, 16), key
        base = key[: -len("_autumn")] if key.endswith("_autumn") else key
        source = cfg.assets.items[base].source
        colours, alphas = _sprite_colours(surf)
        assert alphas <= {0, 255}, (key, alphas)
        if source in ("kenney", "code"):
            assert colours <= palette, (key, colours - palette)


def test_AC12_mono_sprites_black_white_transparent(cfg):
    import pygame

    from ai_island.observer import load_sprites

    pygame.init()
    sprites = load_sprites(cfg.assets, ROOT, "mono")
    assert set(cfg.assets.items) <= set(sprites)
    for key, surf in sprites.items():
        assert surf.get_size() == (16, 16), key
        colours, alphas = _sprite_colours(surf)
        assert colours <= {"#000000", "#ffffff"}, (key, colours)
        assert alphas <= {0, 255}, (key, alphas)


def test_AC12_default_palette_is_colour_and_modes_differ(cfg):
    import pygame

    from ai_island.observer import load_sprites

    pygame.init()
    assert cfg.assets.palette == "color"
    default = load_sprites(cfg.assets, ROOT)
    colour = load_sprites(cfg.assets, ROOT, "color")
    mono = load_sprites(cfg.assets, ROOT, "mono")
    assert set(default) == set(colour)
    assert pygame.image.tobytes(default["tree"], "RGBA") == pygame.image.tobytes(
        colour["tree"], "RGBA"
    )
    assert pygame.image.tobytes(colour["tree"], "RGBA") != pygame.image.tobytes(
        mono["tree"], "RGBA"
    )


def test_AC12_autumn_variants_exist_for_every_autumn_item(cfg):
    import pygame

    from ai_island.observer import load_sprites

    pygame.init()
    assert "tree" in cfg.assets.colors.autumn_items
    for mode in ("color", "mono"):
        sprites = load_sprites(cfg.assets, ROOT, mode)
        for key in cfg.assets.colors.autumn_items:
            assert key in cfg.assets.items
            assert f"{key}_autumn" in sprites, (mode, key)


# ---------------------------------------------------------------- AC-13


def test_AC13_colours_cover_terrain_players_and_ink(cfg):
    c = cfg.assets.colors
    assert set(c.ground) == set(TERRAIN_KEYS)
    assert len(c.players) == 4 and len(set(c.players.values())) == 4
    assert set(c.players) == {"player_1", "player_2", "player_3", "player_4"}
    assert set(c.ink) == set(cfg.assets.missing.items)
    for value in [*c.ground.values(), *c.players.values(), *c.ink.values()]:
        assert HEX.match(value), value
    palette = {x.lower() for x in c.kenney_palette}
    for value in c.ink.values():
        assert value.lower() in palette, value
    assert c.code_light.lower() in palette
    for value in c.autumn:
        assert value.lower() in palette, value


BAD_HEX = [
    ('grass = "#2f6b3f"', 'grass = "2f6b3f"', "colors.ground.grass"),
    ('grass = "#2f6b3f"', 'grass = "#2f6b3"', "colors.ground.grass"),
    ('player_1 = "#e6482e"', 'player_1 = "red"', "colors.players.player_1"),
    ('night_color = "#0b1030"', 'night_color = "#0b10zz"', "light.night_color"),
    ('background = "#472d3c"', 'background = "#xyz"', "colors.background"),
    ('drought_ground = "#a39a4a"', "drought_ground = 5", "colors.drought_ground"),
]


@pytest.mark.parametrize("old,new,key", BAD_HEX)
def test_AC13_bad_hex_fails_naming_file_and_key(tmp_path, old, new, key):
    d = _copy_config(tmp_path)
    _edit(d, "assets.toml", old, new)
    with pytest.raises(ConfigError) as ei:
        load_config(d)
    msg = str(ei.value)
    assert "assets.toml" in msg and key in msg, msg


def test_AC13_missing_ground_colour_fails(tmp_path):
    d = _copy_config(tmp_path)
    _edit(d, "assets.toml", 'sand = "#d9c68f"\n', "")
    with pytest.raises(ConfigError) as ei:
        load_config(d)
    assert "assets.toml" in str(ei.value) and "colors.ground" in str(ei.value)


def test_AC13_duplicate_player_colours_fail(tmp_path):
    d = _copy_config(tmp_path)
    _edit(d, "assets.toml", 'player_2 = "#3cacd7"', 'player_2 = "#e6482e"')
    with pytest.raises(ConfigError) as ei:
        load_config(d)
    assert "assets.toml" in str(ei.value) and "player" in str(ei.value)


def test_AC13_missing_ink_for_missing_item_fails(tmp_path):
    d = _copy_config(tmp_path)
    _edit(d, "assets.toml", 'snow = "#cfc6b8"\n', "")
    with pytest.raises(ConfigError) as ei:
        load_config(d)
    assert "assets.toml" in str(ei.value) and "colors.ink" in str(ei.value)


def test_AC13_missing_list_must_equal_code_items(tmp_path):
    d = _copy_config(tmp_path)
    _edit(d, "assets.toml", '    "ui_font",\n', "")
    with pytest.raises(ConfigError) as ei:
        load_config(d)
    assert "assets.toml" in str(ei.value)


def test_AC13_tiny_creatures_tile_outside_sheet_fails(tmp_path):
    d = _copy_config(tmp_path)
    _edit(d, "assets.toml", "col = 7\nrow = 17", "col = 7\nrow = 18")
    with pytest.raises(ConfigError) as ei:
        load_config(d)
    assert "assets.toml" in str(ei.value)


# ---------------------------------------------------------------- AC-17 / AC-18


def test_AC17_nothing_reads_urizen():
    hits = []
    for f in list((ROOT / "src").rglob("*.py")) + [ROOT / "main.py"]:
        for n, line in enumerate(f.read_text(encoding="utf-8").lower().splitlines(), 1):
            guard = "raise" in line or "may not use" in line or "in raw" in line
            if "urizen" in line and not guard:
                hits.append(f"{f.name}:{n}: {line.strip()}")
    assert not hits, hits
    assert "urizen" not in (ROOT / "config" / "assets.toml").read_text(encoding="utf-8-sig").lower()


def test_AC17_assets_folder_unchanged_since_phase_start():
    r = subprocess.run(
        ["git", "diff", "--name-only", "phase-1.5-start", "--", "assets/"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "", r.stdout


def test_AC18_movement_module_exists_and_world_rules_import_no_pygame():
    movement = ROOT / "src" / "ai_island" / "world" / "movement.py"
    assert movement.is_file()
    forbidden = {"pygame", "pygame_gui", "anthropic", "openai", "google", "mistralai", "ollama"}
    files = []
    for pkg in ("world", "rules"):
        files += list((ROOT / "src" / "ai_island" / pkg).rglob("*.py"))
    bad = []
    for f in files:
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            for n in names:
                if n.split(".")[0] in forbidden:
                    bad.append((f.name, n))
    assert not bad, bad
