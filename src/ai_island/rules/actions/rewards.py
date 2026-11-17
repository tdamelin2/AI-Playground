"""The reward API used by tasks and landmarks: tools, buildings, villagers, land, slots."""

from __future__ import annotations

from ai_island.rules import land
from ai_island.rules.actions import build as build_mod
from ai_island.rules.actions import social
from ai_island.storage.events import RewardPending, StructureBuilt
from ai_island.world.agents import TOOL_KINDS, Structure
from ai_island.world.state import World


def give_tools(world: World, pid: str, tier: str, tick: int) -> int:
    """One set of tools (one of each kind) of ``tier``. Returns how many were given."""
    p = world.players[pid]
    dur = world.cfg.balance.tools.durability[tier]
    for kind in TOOL_KINDS:
        p.inventory.add_tool(kind, tier, dur)
    return len(TOOL_KINDS)


def grant_structure(world: World, pid: str, kind: str, tick: int) -> int | None:
    """Place a finished building near the player's home; None (recorded) if there is no room."""
    p = world.players[pid]
    spot = build_mod.find_site(world, p, kind)
    if spot is None:
        p.pending_rewards.append(f"structure:{kind}")
        world.emit(RewardPending(player=pid, kind=f"structure:{kind}"), tick)
        return None
    cfg = world.cfg.balance.buildings
    sid = world.next("structure")
    s = Structure(
        sid, kind, spot[0], spot[1], pid, cfg.hp[kind], cfg.hp[kind], False, 0.0, {}, None, 0
    )
    world.structures[sid] = s
    build_mod._complete(world, s, tick)
    return sid


def join_villager(world: World, pid: str, tick: int) -> str | None:
    """A wanderer joins the player. None means none was free (recorded as pending)."""
    p = world.players[pid]
    attached = sum(1 for v in world.villagers.values() if v.leader == pid)
    anchor = world.homes[p.index - 1].anchor
    wanderers = sorted(
        (v for v in world.villagers.values() if v.leader is None and v.alive and not v.captive),
        key=lambda v: (abs(v.x - anchor[0]) + abs(v.y - anchor[1]), v.id),
    )
    if attached >= p.slots or not wanderers:
        p.pending_rewards.append("villager")
        world.emit(RewardPending(player=pid, kind="villager"), tick)
        return None
    v = wanderers[0]
    social.attach(world, v, pid, tick, "reward", world.cfg.balance.villagers.recruit_loyalty)
    return v.id


def grant_claim(world: World, pid: str, n_tiles: int, tick: int) -> int:
    """Claim ``n_tiles`` free land tiles near home. Returns how many were claimed."""
    got = land.grant_tiles(world, pid, n_tiles, tick)
    if got < n_tiles:
        world.players[pid].pending_rewards.append(f"claim:{n_tiles - got}")
        world.emit(RewardPending(player=pid, kind=f"claim:{n_tiles - got}"), tick)
    return got


def add_slots(world: World, pid: str, n: int) -> int:
    p = world.players[pid]
    p.slots += n
    return p.slots


_ = StructureBuilt
