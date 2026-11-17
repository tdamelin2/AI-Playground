"""The action request: what a player (or a dummy) asks to do. Strict and closed."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ai_island.world.agents import ACTION_KINDS, PromiseSpec

__all__ = ["ACTION_KINDS", "ActionRequest", "PromiseSpec"]


class ActionRequest(BaseModel):
    """One requested action. Each action validates its own fields when it starts."""

    model_config = ConfigDict(strict=True, extra="forbid")

    kind: Literal[
        "eat", "drink", "rest", "move", "gather", "farm", "fish", "hunt", "build", "store",
        "craft", "make_fire", "cook", "tame", "use_herb", "assign_villager", "talk", "trade",
        "gift", "promise", "ally", "recruit", "teach", "guard", "steal", "sabotage", "attack",
        "chase_off", "claim_land", "pull_stakes", "capture", "poach", "pray", "ceremony",
        "build_shrine", "offering", "repair", "drop", "pick_up",
    ]  # fmt: skip
    target: str | None = None
    x: int | None = None
    y: int | None = None
    item: str | None = None
    amount: int | None = Field(default=None, gt=0)
    until: Literal["morning", "rested", "sated"] | None = None
    minutes: int | None = Field(default=None, gt=0)
    structure: str | None = None
    tool: str | None = None
    tier: str | None = None
    offer: dict[str, int] | None = None
    want: dict[str, int] | None = None
    text: str | None = None
    job: str | None = None
    work_level: str | None = None
    accept: int | None = None
    promise: PromiseSpec | None = None
