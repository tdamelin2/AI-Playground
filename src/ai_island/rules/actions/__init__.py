"""Every action a player can take, with its duration and effects."""

from ai_island.rules.actions import bodyact, build, fire, harm, social, tools, work  # noqa: F401
from ai_island.rules.actions.core import (
    SPECS,
    cancel_action,
    player_order,
    resolve,
    start_action,
)
from ai_island.rules.actions.request import ACTION_KINDS, ActionRequest, PromiseSpec
from ai_island.rules.actions.rewards import (
    add_slots,
    give_tools,
    grant_claim,
    grant_structure,
    join_villager,
)

missing = [k for k in ACTION_KINDS if k not in SPECS]
if missing:  # a safety net for developers: every action kind must have a handler
    raise ImportError(f"actions without a handler: {missing}")

__all__ = [
    "ACTION_KINDS",
    "ActionRequest",
    "PromiseSpec",
    "add_slots",
    "cancel_action",
    "give_tools",
    "grant_claim",
    "grant_structure",
    "join_villager",
    "player_order",
    "resolve",
    "start_action",
]
