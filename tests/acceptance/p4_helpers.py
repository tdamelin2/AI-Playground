"""Shared helpers for the Phase 4 acceptance tests (fake adapter only, no network)."""

from __future__ import annotations

import functools
import re
import shutil
import tempfile
from pathlib import Path

from ai_island.config import GameConfig, load_config
from ai_island.llm.fake import FakeAdapter
from ai_island.rules import interrupts
from ai_island.rules.actions.core import cancel_action
from ai_island.sim import Simulation, ai_config
from ai_island.storage.db import RunDB

ROOT = Path(__file__).resolve().parents[2]
CFG: GameConfig = load_config(ROOT / "config")

BANNED = [
    "AI", "model", "Claude", "GPT", "Gemini", "Grok", "Anthropic", "OpenAI", "Google", "xAI",
    "Mistral", "game", "experiment", "observer",
]  # fmt: skip
BANNED_RE = re.compile(r"\b(" + "|".join(re.escape(w) for w in BANNED) + r")\b", re.IGNORECASE)

LABEL = {"served": [], "violated": [], "direction": "toward"}


def fast_reply(action: dict, direction="toward", served=(), violated=(), more=False, feel=0):
    return {
        "thought": "thinking",
        "action": action,
        "self_label": {"served": list(served), "violated": list(violated), "direction": direction},
        "expected_feel": feel,
        "needs_more_thought": more,
    }


def new_ai_sim(seats=(1,), cheap=False, seed=1, adapter=None, db_path: Path | None = None):
    cfg = ai_config(CFG, list(seats), cheap=cheap, max_dollars=1.0)
    sim = Simulation.new(cfg, seed)
    sim.adapters = {"fake": adapter or FakeAdapter()}
    if db_path is not None:
        db = RunDB.create(db_path)
        sim.attach(db)
        sim.save()
    return sim


def clean(sim: Simulation) -> None:
    """Stop every player's action and drop pending interrupts so one trigger can be tested."""
    w = sim.world
    for pid, p in w.players.items():
        interrupts.clear_for(w, pid)
        cancel_action(w, pid, w.tick, "test")
        p.last_decision_tick = w.tick
        p.just_finished = False


def raise_int(sim: Simulation, kind: str, pid: str, source: str | None = None) -> None:
    interrupts.raise_interrupt(sim.world, kind, pid, sim.world.tick + 1, source=source)


def decisions(sim: Simulation, start: int = 0):
    return [e.payload for e in sim.events[start:] if e.type == "decision_made"]


@functools.cache
def shared_week() -> tuple[Path, int]:
    """A 4-seat fake-adapter game week with a database, built once per test session."""
    root = Path(tempfile.mkdtemp(prefix="p4_week_"))
    sim = new_ai_sim(seats=(1, 2, 3, 4), seed=7, db_path=root / "run.db")
    week = sim.week_ticks
    # a few forced moments so slow and hooked decisions happen too
    marks = [900, 2000, 3500, 5000, 8000]
    done = 0
    for i, mark in enumerate(marks):
        sim.run(mark - sim.world.tick)
        pid = f"player_{(i % 4) + 1}"
        other = f"player_{((i + 1) % 4) + 1}"
        clean(sim)
        if i == 3:
            sim.world.players[pid].body.pain = 90.0  # hooked
        raise_int(sim, "spoken_to", pid, source=other)
        done += 1
    sim.run(week - sim.world.tick)
    sim.save()
    sim.db.close()
    return root, sim.world.tick


def cleanup_shared() -> None:
    shared_week.cache_clear()


def rmtree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
