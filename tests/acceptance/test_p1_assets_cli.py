"""P1 AC-19 .. AC-22: asset mapping, sprites, view screenshot, CLI headless/resume."""

from __future__ import annotations

import re

import pytest
from conftest import LOGS, ROOT, cli, fresh_run, load_toml

# docs/gameplay.md "Asset list": concept -> (required substrings in one key, min number of keys)
CONCEPTS = [
    ("grass", ["grass"], 1),
    ("tree", ["tree"], 1),
    ("stump", ["stump"], 1),
    ("spring", ["spring"], 1),
    ("lake", ["lake"], 1),
    ("coast", ["coast"], 1),
    ("farmland empty", ["farmland", "empty"], 1),
    ("farmland planted", ["farmland", "planted"], 1),
    ("farmland growing", ["farmland", "growing"], 1),
    ("farmland ready", ["farmland", "ready"], 1),
    ("farmland failed", ["farmland", "failed"], 1),
    ("quarry", ["quarry"], 1),
    ("rocky", ["rocky"], 1),
    ("depleted", ["depleted"], 2),
    ("claim borders x4", ["border"], 4),
    ("boundary stake", ["stake"], 1),
    ("snow", ["snow"], 1),
    ("drought", ["drought"], 1),
    ("night overlay", ["night"], 1),
    ("rain overlay", ["rain"], 1),
    ("storm overlay", ["storm"], 1),
    ("berries", ["berries"], 1),
    ("mushrooms", ["mushroom"], 1),
    ("roots", ["roots"], 1),
    ("herbs", ["herbs"], 1),
    ("healing herbs", ["healing"], 1),
    ("mild poison", ["mild_poison"], 1),
    ("strong poison", ["strong_poison"], 1),
    ("rabbit", ["rabbit"], 1),
    ("deer", ["deer"], 1),
    ("boar", ["boar"], 1),
    ("fish", ["fish"], 1),
    ("bird", ["bird"], 1),
    ("nest", ["nest"], 1),
    ("goat", ["goat"], 1),
    ("chicken", ["chicken"], 1),
    ("wild dog", ["dog"], 1),
    ("pen", ["pen"], 1),
    ("4 players", ["player"], 4),
    ("villagers", ["villager"], 2),
    ("marker sick", ["sick"], 1),
    ("marker injured", ["injured"], 1),
    ("marker sleeping", ["sleeping"], 1),
    ("marker grave", ["grave"], 1),
    ("house", ["house"], 1),
    ("hearth", ["hearth"], 1),
    ("field", ["field"], 1),
    ("storehouse", ["storehouse"], 1),
    ("workshop", ["workshop"], 1),
    ("campfire", ["campfire"], 1),
    ("shrine", ["shrine"], 1),
    ("offering spot", ["offering"], 1),
    ("granary", ["granary"], 1),
    ("bridge", ["bridge"], 1),
    ("monument", ["monument"], 1),
    ("great tree", ["great_tree"], 1),
    ("lake dock", ["dock"], 1),
    ("damaged versions", ["damaged"], 10),
    ("wood", ["wood"], 1),
    ("stone", ["stone"], 1),
    ("water", ["water"], 1),
    ("raw meat", ["raw_meat"], 1),
    ("cooked meat", ["cooked"], 1),
    ("spoiled meat", ["spoiled"], 1),
    ("eggs", ["eggs"], 1),
    ("milk", ["milk"], 1),
    ("crops", ["crop"], 1),
    ("tools axe", ["axe"], 2),
    ("tools pickaxe", ["pickaxe"], 2),
    ("tools hoe", ["hoe"], 2),
    ("tools fishing", ["fishing"], 1),
    ("tools spear", ["spear"], 2),
    ("offerings icon", ["offering"], 2),
    ("ui map", ["map"], 1),
    ("ui clock", ["clock"], 1),
    ("ui season", ["season"], 1),
    ("ui pause/resume", ["pause"], 1),
    ("ui resume", ["resume"], 1),
    ("ui speed", ["speed"], 1),
    ("tab chats", ["chats"], 1),
    ("tab choice points", ["choice"], 1),
    ("tab world history", ["history"], 1),
    ("tab players", ["players"], 1),
    ("tab spend", ["spend"], 2),
    ("paused indicator", ["paused"], 1),
    ("autosave indicator", ["autosave"], 1),
    ("pixel font", ["font"], 1),
]

CONTRACT_KEYS = (
    "grass sand tree stump spring lake coast farmland_empty farmland_planted farmland_growing "
    "farmland_ready farmland_failed rocky rocky_depleted quarry quarry_depleted berries mushrooms "
    "roots herbs healing_herbs mild_poison strong_poison rabbit deer boar fish bird nest_eggs goat "
    "chicken wild_dog great_tree lake_dock"
).split()


@pytest.fixture(scope="module")
def raw_assets():
    return load_toml(ROOT / "config" / "assets.toml")


@pytest.mark.parametrize("name,subs,minimum", CONCEPTS, ids=[c[0] for c in CONCEPTS])
def test_AC19_asset_list_item_mapped(raw_assets, name, subs, minimum):
    keys = [k for k in raw_assets["items"] if all(s in k for s in subs)]
    assert len(keys) >= minimum, f"{name}: found {keys}"


def test_AC19_contract_keys_present(raw_assets):
    missing = [k for k in CONTRACT_KEYS if k not in raw_assets["items"]]
    assert not missing, missing


def test_AC19_indices_in_sheet_and_missing_section(raw_assets):
    sheets = raw_assets["sheets"]
    assert set(sheets) == {"kenney", "tiny_creatures"}
    assert "sheet" not in raw_assets  # the old [sheet] table is removed (no alias)
    dims = {}
    for name, sheet in sheets.items():
        assert sheet["tile_size"] == 16 and sheet["gap"] == 1, name
        dims[name] = (sheet["columns"], sheet["rows"])
    assert dims == {"kenney": (49, 22), "tiny_creatures": (10, 18)}
    for key, item in raw_assets["items"].items():
        assert item["source"] in ("kenney", "tiny_creatures", "code"), key
        if item["source"] == "code":
            assert not {"col", "row", "flip"} & set(item), key
        else:
            cols, rows = dims[item["source"]]
            assert 0 <= item["col"] < cols and 0 <= item["row"] < rows, key
    missing = raw_assets["missing"]["items"]
    code_keys = {k for k, v in raw_assets["items"].items() if v["source"] == "code"}
    assert set(missing) == code_keys and len(missing) == len(set(missing))
    # items Kenney does not have (documented as drawn in code) are listed
    for k in ("snow", "drought", "overlay_night", "overlay_rain", "overlay_storm"):
        assert k in missing
    assert "urizen" not in (ROOT / "config" / "assets.toml").read_text(encoding="utf-8-sig").lower()


def test_AC19_sheet_file_exists(raw_assets):
    for name, sheet in raw_assets["sheets"].items():
        assert (ROOT / sheet["path"]).is_file(), name


# ---------------------------------------------------------------- AC-20


def test_AC20_every_sprite_is_16px_black_white_transparent_in_mono(cfg):
    import pygame

    from ai_island.observer import load_sprites

    pygame.init()
    sprites = load_sprites(cfg.assets, ROOT, "mono")
    assert set(cfg.assets.items) <= set(sprites)
    allowed_opaque = {(0, 0, 0, 255), (255, 255, 255, 255)}
    for key, surf in sprites.items():
        assert surf.get_size() == (16, 16), key
        for x in range(16):
            for y in range(16):
                r, g, b, a = surf.get_at((x, y))
                assert a == 0 or (r, g, b, a) in allowed_opaque, (key, x, y, (r, g, b, a))


def test_AC20_every_sprite_not_blank_for_kenney_items(cfg):
    import pygame

    from ai_island.observer import load_sprites

    pygame.init()
    sprites = load_sprites(cfg.assets, ROOT, "mono")
    blank = []
    for key, item in cfg.assets.items.items():
        if item.source == "code":
            continue
        s = sprites[key]
        if not any(s.get_at((x, y))[3] > 0 for x in range(16) for y in range(16)):
            blank.append(key)
    assert not blank, blank


def test_AC20_nothing_reads_urizen():
    hits = []
    for f in list((ROOT / "src").rglob("*.py")) + [ROOT / "main.py"]:
        for n, line in enumerate(f.read_text(encoding="utf-8").lower().splitlines(), 1):
            # The AC forbids READING assets/urizen/. A guard that rejects the word is allowed
            # (observer/sprites.py raises on it); any path-like use is not.
            guard = "raise" in line or "may not use" in line or "in raw" in line
            if "urizen" in line and not guard:
                hits.append(f"{f.name}:{n}: {line.strip()}")
    assert not hits, hits


# ---------------------------------------------------------------- AC-21 / AC-22


def test_AC21_view_screenshot():
    fresh_run("t1")
    assert cli("new", "t1", "--seed", "1").returncode == 0
    shot = LOGS / "view.png"
    shot.unlink(missing_ok=True)
    r = cli("view", "--run", "t1", "--ticks", "600", "--screenshot", "logs/view.png")
    assert r.returncode == 0, r.stderr
    data = shot.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) > 1000


def test_AC21_view_does_not_write_to_run_db():
    import sqlite3

    from conftest import RUNS

    fresh_run("t1")
    assert cli("new", "t1", "--seed", "1").returncode == 0

    def count():
        con = sqlite3.connect(RUNS / "t1" / "run.db")
        try:
            return con.execute("SELECT COUNT(*) FROM events").fetchone()[0], con.execute(
                "SELECT COUNT(*) FROM snapshots"
            ).fetchone()[0]
        finally:
            con.close()

    before = count()
    assert (
        cli("view", "--run", "t1", "--ticks", "300", "--screenshot", "logs/view2.png").returncode
        == 0
    )
    assert count() == before


TIME_RE = re.compile(
    r"Year (\d+), (Spring|Summer|Autumn|Winter), week (\d+), day (\d+), (\d\d):(\d\d)"
)


def test_AC22_headless_prints_final_time():
    r = cli("headless", "--ticks", "1440", "--seed", "1")
    assert r.returncode == 0, r.stderr
    m = TIME_RE.search(r.stdout)
    assert m, r.stdout
    assert m.groups() == ("1", "Spring", "1", "2", "00", "00")


def test_AC22_resume_continues_from_latest_snapshot():
    fresh_run("t1")
    assert cli("new", "t1", "--seed", "1").returncode == 0
    r = cli("resume", "t1")  # default resume_ticks = 1440, exits by itself
    assert r.returncode == 0, r.stderr
    m = TIME_RE.search(r.stdout)
    assert m and m.group(4) == "2" and m.group(5) == "00", r.stdout
    r = cli("resume", "t1")
    assert r.returncode == 0, r.stderr
    m = TIME_RE.search(r.stdout)
    assert m and m.group(4) == "3", r.stdout


def test_AC22_resume_missing_run_errors():
    fresh_run("acc_nonexistent")
    assert cli("resume", "acc_nonexistent").returncode != 0
