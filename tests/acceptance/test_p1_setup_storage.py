"""P1 AC-1 .. AC-6: install, lint, imports, config strictness, CLI new, append-only events."""

from __future__ import annotations

import ast
import re
import shutil
import sqlite3
import subprocess

import pytest
from conftest import ROOT, RUNS, cli, fresh_run

from ai_island.config import ConfigError, load_config


def test_AC1_uv_sync_and_imports():
    r = subprocess.run(["uv", "sync"], cwd=ROOT, capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stderr
    code = (
        "import pygame, pygame_gui, pydantic, dotenv, anthropic, openai, "
        "google.genai, mistralai, ollama; assert pygame.IS_CE"
    )
    r = subprocess.run(
        ["uv", "run", "python", "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=300
    )
    assert r.returncode == 0, r.stderr


def test_AC2_ruff_clean():
    r = subprocess.run(["uv", "run", "ruff", "check"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    r = subprocess.run(
        ["uv", "run", "ruff", "format", "--check"], cwd=ROOT, capture_output=True, text=True
    )
    assert r.returncode == 0, r.stdout + r.stderr


PACKAGES = ["world", "rules", "minds", "llm", "measure", "observer", "storage"]
FORBIDDEN = {"pygame", "pygame_gui", "anthropic", "openai", "google", "mistralai", "ollama"}


@pytest.mark.parametrize("pkg", PACKAGES)
def test_AC3_package_imports(pkg):
    import importlib

    importlib.import_module(f"ai_island.{pkg}")


def _imported_roots(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                yield a.name.split(".")[0], a.name
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module.split(".")[0], node.module
        elif isinstance(node, ast.Call) and getattr(node.func, "id", "") == "__import__":
            if node.args and isinstance(node.args[0], ast.Constant):
                yield str(node.args[0].value).split(".")[0], str(node.args[0].value)


def test_AC3_no_pygame_or_ai_sdk_in_world_and_rules():
    files = []
    for pkg in ("world", "rules"):
        files += list((ROOT / "src" / "ai_island" / pkg).rglob("*.py"))
    assert files
    bad = []
    for f in files:
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for root, full in _imported_roots(tree):
            if root in FORBIDDEN:
                bad.append((f.name, full))
    assert not bad, bad


def _copy_config(tmp_path):
    d = tmp_path / "config"
    shutil.copytree(ROOT / "config", d)
    return d


def test_AC4_all_configs_load(cfg):
    assert cfg.world and cfg.balance and cfg.models and cfg.run and cfg.assets


# (file, text to replace, replacement, key that must be named)
BAD_TYPES = [
    ("world.toml", "ticks_per_day = 1440", 'ticks_per_day = "1440"', "ticks_per_day"),
    ("world.toml", "ticks_per_day = 1440", "ticks_per_day = true", "ticks_per_day"),
    ("world.toml", "width = 80", "width = 80.5", "width"),
    (
        "balance.toml",
        "extinction_delay_ticks = 20160",
        'extinction_delay_ticks = "x"',
        "extinction_delay_ticks",
    ),
    (
        "balance.toml",
        "extinction_delay_ticks = 20160",
        "extinction_delay_ticks = true",
        "extinction_delay_ticks",
    ),
    ("models.toml", 'model = "nomic-embed-text"', "model = 5", "model"),
    ("run.toml", "resume_ticks = 1440", 'resume_ticks = "1440"', "resume_ticks"),
    ("run.toml", "resume_ticks = 1440", "resume_ticks = true", "resume_ticks"),
    ("assets.toml", "tile_size = 16", 'tile_size = "16"', "tile_size"),
    ("assets.toml", "tile_size = 16", "tile_size = true", "tile_size"),
]


@pytest.mark.parametrize("fname,old,new,key", BAD_TYPES)
def test_AC4_wrong_type_fails_naming_file_and_key(tmp_path, fname, old, new, key):
    d = _copy_config(tmp_path)
    p = d / fname
    text = p.read_text(encoding="utf-8-sig")
    assert old in text, f"test setup: {old!r} not in {fname}"
    p.write_text(text.replace(old, new, 1), encoding="utf-8")
    with pytest.raises(ConfigError) as ei:
        load_config(d)
    msg = str(ei.value)
    assert fname in msg and key in msg, msg


@pytest.mark.parametrize(
    "bad",
    ["[]", '["buffer", "buffer"]', '["buffer", "moon"]'],
    ids=["empty", "duplicate", "unknown_zone"],
)
def test_AC4_bad_land_pool_zones_fails(tmp_path, bad):
    d = _copy_config(tmp_path)
    p = d / "world.toml"
    text = p.read_text(encoding="utf-8-sig")
    old = 'pool_zones = ["buffer", "centre"]'
    assert old in text
    p.write_text(text.replace(old, f"pool_zones = {bad}", 1), encoding="utf-8")
    with pytest.raises(ConfigError) as ei:
        load_config(d)
    msg = str(ei.value)
    assert "world.toml" in msg and "land.pool_zones" in msg, msg


@pytest.mark.parametrize(
    "fname", ["world.toml", "balance.toml", "models.toml", "run.toml", "assets.toml"]
)
def test_AC4_unknown_top_level_key_fails(tmp_path, fname):
    d = _copy_config(tmp_path)
    p = d / fname
    p.write_text("bogus_key_zz = 1\n" + p.read_text(encoding="utf-8-sig"), encoding="utf-8")
    with pytest.raises(ConfigError) as ei:
        load_config(d)
    msg = str(ei.value)
    assert fname in msg and "bogus_key_zz" in msg, msg


@pytest.mark.parametrize(
    "fname,header",
    [
        ("world.toml", "[clock]"),
        ("balance.toml", "[trees]"),
        ("run.toml", "[view]"),
        ("models.toml", "[embedding]"),
        ("assets.toml", "[sheets.kenney]"),
    ],
)
def test_AC4_unknown_nested_key_fails(tmp_path, fname, header):
    d = _copy_config(tmp_path)
    p = d / fname
    text = p.read_text(encoding="utf-8-sig")
    assert header in text
    p.write_text(text.replace(header, header + "\nbogus_nested_zz = 1", 1), encoding="utf-8")
    with pytest.raises(ConfigError) as ei:
        load_config(d)
    msg = str(ei.value)
    assert fname in msg and "bogus_nested_zz" in msg, msg


TABLES = {
    "events",
    "ai_calls",
    "choice_points",
    "judge_labels",
    "chats",
    "value_history",
    "spend",
    "snapshots",
}


def test_AC5_new_creates_db_with_tables():
    fresh_run("t1")
    r = cli("new", "t1", "--seed", "1")
    assert r.returncode == 0, r.stderr
    db = RUNS / "t1" / "run.db"
    assert db.exists()
    con = sqlite3.connect(db)
    names = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    assert TABLES <= names, TABLES - names
    # a second `new` with the same name is refused
    r2 = cli("new", "t1", "--seed", "1")
    assert r2.returncode != 0


def test_AC6_events_are_append_only(run_name):
    r = cli("headless", "--run", run_name, "--ticks", "3000", "--seed", "2")
    assert r.returncode == 0, r.stderr
    con = sqlite3.connect(RUNS / run_name / "run.db")
    n = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert n > 0
    with pytest.raises(sqlite3.DatabaseError):
        con.execute("UPDATE events SET tick = tick + 1")
    with pytest.raises(sqlite3.DatabaseError):
        con.execute("DELETE FROM events")
    first_id = con.execute("SELECT id FROM events ORDER BY id LIMIT 1").fetchone()[0]
    row = con.execute(
        "SELECT tick, type, payload_json FROM events WHERE id=?", (first_id,)
    ).fetchone()
    with pytest.raises(sqlite3.DatabaseError):
        con.execute(
            "INSERT OR REPLACE INTO events(id, tick, type, payload_json) VALUES (?,?,?,?)",
            (first_id, row[0], row[1], row[2]),
        )
    assert con.execute("SELECT COUNT(*) FROM events").fetchone()[0] == n
    con.close()


def test_AC6_storage_api_has_no_event_mutation():
    from ai_island.storage.db import RunDB

    public = [m for m in dir(RunDB) if not m.startswith("_")]
    # Phase 4 (approved): update_choice_outcome / update_choice_insight only touch choice_points
    allowed = {"update_choice_outcome", "update_choice_insight"}
    bad = [
        m
        for m in public
        if m not in allowed and re.search(r"(update|delete|remove|replace|drop|truncate|clear)", m)
    ]
    assert not bad, bad
