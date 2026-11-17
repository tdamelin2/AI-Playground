"""Choice points: which decisions are recorded in detail, and what a record holds (C9)."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ai_island.rules.actions.request import ActionRequest

HARM_KINDS: frozenset[str] = frozenset(
    {"steal", "sabotage", "attack", "chase_off", "pull_stakes", "capture", "poach"}
)


def wants_choice_point(tier: str, action_kind: str, direction: str | None) -> bool:
    """Every slow and hooked decision; a fast one only if it harms, promises or goes against."""
    if tier in ("slow", "hooked"):
        return True
    if tier != "fast":
        return False
    return action_kind in HARM_KINDS or action_kind == "promise" or direction == "against"


def action_dict(req: ActionRequest) -> dict[str, Any]:
    return req.model_dump(mode="json", exclude_none=True)


def describe_action(req: ActionRequest | dict[str, Any]) -> str:
    """A short plain description, for prompts and the decisions text: kind plus its main fields."""
    data = req if isinstance(req, dict) else action_dict(req)
    bits = [str(data.get("kind", "?")).replace("_", " ")]
    for key in ("target", "item", "structure", "tool"):
        if data.get(key):
            bits.append(str(data[key]))
    if data.get("amount"):
        bits.append(f"x{data['amount']}")
    if data.get("x") is not None and data.get("y") is not None:
        bits.append(f"at ({data['x']}, {data['y']})")
    if data.get("text"):
        bits.append(f'"{str(data["text"])[:60]}"')
    return " ".join(bits)


def violated_core(violated: Iterable[str], core: Iterable[str]) -> list[str]:
    core_set = set(core)
    return [v for v in violated if v in core_set]


def is_violation(direction: str | None, violated: Iterable[str], core: Iterable[str]) -> bool:
    """A choice against the player's own top values (direction against, or a core value broken)."""
    return direction == "against" or bool(violated_core(violated, core))
