"""Outcomes of decisions: what happened to the player's wellbeing after the chosen action.

Each decision that came from a model reply has a ``Pending`` outcome. It is settled once, when the
action finishes, fails, is cancelled, the player dies, the next decision interrupts it, or
``outcome_window_ticks`` pass. A decision is a mistake when the wellbeing change fell short of what
the player expected by more than ``mistake_margin``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from ai_island.minds.settings import DEFAULT_SETTINGS, MindSettings


@dataclass
class Pending:
    decision_key: str
    tick: int
    kind: str
    expected_delta: float
    x_before: float
    tier: str
    choice_point: bool
    started: bool = False

    def to_state(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_state(cls, s: dict[str, Any]) -> Pending:
        return cls(
            str(s["decision_key"]),
            int(s["tick"]),
            str(s["kind"]),
            float(s["expected_delta"]),
            float(s["x_before"]),
            str(s["tier"]),
            bool(s["choice_point"]),
            bool(s.get("started", False)),
        )


def is_mistake(
    expected_delta: float, actual_delta: float, settings: MindSettings = DEFAULT_SETTINGS
) -> bool:
    """Expected +6, actual 0 -> 6 > 5 is a mistake; actual +1 -> 5 is not."""
    return expected_delta - actual_delta > settings.mistake_margin


def outcome_dict(result: str, x_before: float, x_after: float) -> dict[str, Any]:
    return {
        "result": result,
        "x_before": round(x_before, 3),
        "x_after": round(x_after, 3),
        "x_delta": round(x_after - x_before, 3),
    }


def result_from_events(pending: Pending, events: list[Any], pid: str) -> str | None:
    """Scan one tick's events (oldest first); update ``pending.started``; return the result of
    the pending action if it ended in these events, else None."""
    for e in events:
        pl = e.payload
        if getattr(pl, "player", None) != pid:
            continue
        if e.type == "died":
            return "died"
        if e.type == "action_started" and not pending.started and pl.kind == pending.kind:
            pending.started = True
        elif e.type == "action_failed" and not pending.started and pl.kind == pending.kind:
            return f"failed:{pl.reason}"
        elif e.type == "action_finished" and pending.started and pl.kind == pending.kind:
            return str(pl.result)
    return None


def word_for_delta(x_delta: float, settings: MindSettings = DEFAULT_SETTINGS) -> str:
    """Plain words for how wellbeing moved (never the number); one feel point is the unit."""
    unit = settings.x_per_feel_point
    if x_delta > unit:
        return "felt better"
    if x_delta < -unit:
        return "felt worse"
    return "felt about the same"
