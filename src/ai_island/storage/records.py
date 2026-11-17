"""Record DTOs passed from the minds to the database (Contract C1/C8).

The minds build these; ``Simulation`` drains and writes them on the simulation's thread.
JSON columns are plain dicts here; the database layer serialises them. The ``decision_key``
of a choice point is stored inside its ``details_json``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChoicePointRecord:
    """One choice_points row (every column except ``id``) plus its decision key."""

    decision_key: str
    tick: int
    player_id: str
    situation: str
    x: float
    feeling: str
    tier: str
    thought: str
    action: dict[str, Any]
    self_label: dict[str, Any]
    noticer_read: str | None = None
    advisor_said: str | None = None
    advisor_followed: bool | None = None
    outcome: dict[str, Any] | None = None
    insight: str | None = None
    ai_call_id: int | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChoiceOutcome:
    decision_key: str
    outcome: dict[str, Any]


@dataclass
class ChoiceInsight:
    decision_key: str
    insight: str


@dataclass
class ValueHistoryRow:
    tick: int
    player_id: str
    game_week: int
    value_id: str
    old_weight: float | None
    new_weight: float
    cause_event_ids: list[int] = field(default_factory=list)
    reflection_key: str | None = None
    cause_items: list[dict[str, Any]] = field(default_factory=list)
