"""Helpers for the Phase 2 acceptance tests (built from the Plan contract only)."""

from __future__ import annotations

from conftest import ROOT

from ai_island.config import load_config
from ai_island.rules.actions import ActionRequest, start_action
from ai_island.world.agents import Structure
from ai_island.world.engine import advance_to
from ai_island.world.example import build_example_world
from ai_island.world.state import World


def make_cfg():
    return load_config(ROOT / "config")


def example(cfg, seed: int = 1) -> World:
    w = build_example_world(cfg, seed)
    w.weather.current = "clear"
    return w


def run(world: World, ticks: int) -> None:
    advance_to(world, world.tick + ticks)


def req(**kw) -> ActionRequest:
    return ActionRequest(**kw)


def act(world: World, pid: str, **kw) -> bool:
    return start_action(world, pid, req(**kw), world.tick)


def run_until_idle(world: World, pid: str, limit: int = 1500) -> int:
    """Advance tick by tick until the player has no action; returns the ticks used."""
    start = world.tick
    p = world.players[pid]
    for _ in range(limit):
        if p.action is None:
            break
        advance_to(world, world.tick + 1)
    return world.tick - start


def evs(world: World, etype: str, /, **match):
    out = []
    for e in world.events:
        if e.type != etype:
            continue
        if all(getattr(e.payload, k, None) == v for k, v in match.items()):
            out.append(e)
    return out


def teleport(world: World, pid: str, x: int, y: int) -> None:
    p = world.players[pid]
    p.x = p.from_x = p.to_x = x
    p.y = p.from_y = p.to_y = y
    p.action = None


def add_structure(world, kind, x, y, owner, complete=True, hp=None) -> Structure:
    cfgb = world.cfg.balance.buildings
    max_hp = cfgb.hp[kind]
    s = Structure(world.next("structure"), kind, x, y, owner, max_hp if hp is None else hp, max_hp)
    s.complete = complete
    if kind in ("storehouse", "granary"):
        s.store = world.new_inventory()
    world.structures[s.id] = s
    return s


def stock(world, pid, **items):
    p = world.players[pid]
    for k, n in items.items():
        p.inventory.add(k, n, world.tick)
