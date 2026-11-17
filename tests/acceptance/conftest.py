"""Shared helpers for the Phase 1 acceptance tests (from the Plan AC list and Contract)."""

from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "runs"
LOGS = ROOT / "logs"

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")


def cli(*args: str, env_extra: dict | None = None, timeout: int = 600):
    env = dict(os.environ)
    env["SDL_VIDEODRIVER"] = "dummy"
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, "main.py", *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def db_events(run: str):
    con = sqlite3.connect(RUNS / run / "run.db")
    try:
        return con.execute("SELECT tick, type, payload_json FROM events ORDER BY id").fetchall()
    finally:
        con.close()


def fresh_run(name: str) -> str:
    shutil.rmtree(RUNS / name, ignore_errors=True)
    return name


@pytest.fixture
def run_name(request):
    name = "acc_" + request.node.name.replace("[", "_").replace("]", "")[:40]
    shutil.rmtree(RUNS / name, ignore_errors=True)
    yield name
    shutil.rmtree(RUNS / name, ignore_errors=True)


@pytest.fixture(scope="session")
def cfg():
    from ai_island.config import load_config

    return load_config(ROOT / "config")


@pytest.fixture
def sim(cfg):
    from ai_island.sim import Simulation

    return Simulation.new(cfg, 1, players="none")


def home_rects(world):
    return [(h.x, h.y, h.size) for h in world.homes]


def in_rect(x, y, rect):
    rx, ry, size = rect
    return rx <= x < rx + size and ry <= y < ry + size


def centre_rect(cfg):
    m = cfg.world.map
    size = cfg.world.map.centre_size
    return ((m.width - size) // 2, (m.height - size) // 2, size)


def find_tiles(world, key):
    return [
        (x, y)
        for y in range(world.height)
        for x in range(world.width)
        if world.terrain[y][x] == key
    ]


def load_toml(path):
    import tomllib

    return tomllib.loads(Path(path).read_text(encoding="utf-8-sig"))
