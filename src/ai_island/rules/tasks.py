"""The five hidden task stages. Rewards are given only through the engine's reward API.

``check_tasks`` runs hourly. A stage is done when every requirement of ``[tasks.stage_N]`` in
balance.toml is met; each (player, stage) gives its reward once (a receipt is kept).
"""

from __future__ import annotations

from typing import Any

from ai_island.rules.senses.common import SettingError, emit, section, setting

LAST_STAGE = 5
STORE_KINDS = ("storehouse", "granary")
FOOD_STRUCTURES = frozenset(STORE_KINDS)


def _count_structures(world: Any, pid: str, kind: str) -> int:
    return sum(
        1 for s in world.structures.values() if s.owner == pid and s.kind == kind and s.complete
    )


def food_stored(world: Any, pid: str) -> int:
    """Food units in the player's home store and in the storehouses and granaries it owns."""
    player = world.players[pid]
    total = int(player.home_store.food_units())
    for s in world.structures.values():
        if s.owner == pid and s.kind in STORE_KINDS and s.complete and s.store is not None:
            total += int(s.store.food_units())
    return total


def measure(world: Any, pid: str, name: str) -> int:
    """How much of requirement ``name`` the player has now."""
    player = world.players[pid]
    if name in ("wood", "water", "stone"):
        return int(player.inventory.count(name) + player.home_store.count(name))
    if name == "food_stored":
        return food_stored(world, pid)
    if name == "villagers":
        return sum(1 for v in world.villagers.values() if v.alive and v.leader == pid)
    if name == "claimed_tiles":
        return sum(1 for owner in world.claims.values() if owner == pid)
    if name in ("house", "field", "workshop", "monument", "storehouse", "granary", "hearth"):
        return _count_structures(world, pid, name)
    raise SettingError(f"unknown task requirement '{name}'")


def stage_requirements(world: Any, stage: int) -> dict[str, int]:
    table = section(world, "tasks").get(f"stage_{stage}")
    if not isinstance(table, dict):
        raise SettingError(f"balance.toml [tasks] has no stage_{stage}")
    return {k: int(v) for k, v in table.items()}


def own_tasks(world: Any, pid: str) -> list[tuple[str, int, int]]:
    """The player's current stage as (requirement, have, need) rows; empty when all done."""
    stage = world.players[pid].task_stage
    if stage > LAST_STAGE:
        return []
    return [
        (name, min(measure(world, pid, name), need), need)
        for name, need in stage_requirements(world, stage).items()
    ]


def _reward(world: Any, pid: str, stage: int, tick: int) -> None:
    from ai_island.rules import actions as api

    if stage == 1:
        api.give_tools(world, pid, "basic", tick)
    elif stage == 2:
        api.join_villager(world, pid, tick)
    elif stage == 3:
        api.grant_claim(world, pid, int(setting(world, "land_reward")), tick)
        api.grant_structure(world, pid, "storehouse", tick)
    elif stage == 4:
        api.give_tools(world, pid, "better", tick)
        api.add_slots(
            world, pid, int(setting(world, "slots_stage_4") - setting(world, "slots_start"))
        )
    elif stage == 5:
        from ai_island.rules.wellbeing import add_gain

        add_gain(world, pid, float(setting(world, "legacy_reward")), "legacy", tick)


def check_tasks(world: Any, tick: int) -> None:
    """Hourly: finish every stage whose requirements are met and give its reward once."""
    if tick % int(setting(world, "check_interval_ticks")) != 0:
        return
    for pid in sorted(world.players):
        player = world.players[pid]
        if not player.alive:
            continue
        while player.task_stage <= LAST_STAGE:
            stage = player.task_stage
            needs = stage_requirements(world, stage)
            if any(measure(world, pid, name) < need for name, need in needs.items()):
                break
            if stage not in player.task_receipts:
                player.task_receipts.append(stage)
                _reward(world, pid, stage, tick)
            for name, need in needs.items():
                emit(world, "task_done", tick, player=pid, stage=stage, task=name, amount=need)
            player.task_stage = stage + 1
            emit(world, "stage_done", tick, player=pid, stage=stage)
