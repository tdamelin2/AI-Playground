"""Reply schemas for the AI players (contract C9). All closed (extra="forbid") and strict.

Pydantic checks the shape. Checks that need the player's own data (value ids, text lengths) are
done by ``check_reply``, which returns a list of problems; any problem counts as a format error.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ai_island.minds.settings import DEFAULT_SETTINGS, MindSettings
from ai_island.rules.actions.request import ActionRequest

Direction = Literal["toward", "against"]
Uncertainty = Literal["low", "medium", "high"]


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


VALUE_LIST_LIMIT = 4


def _cut_values(value: Any) -> Any:
    """Keep the first VALUE_LIST_LIMIT items of a value-id list (most important first)."""
    if isinstance(value, list) and len(value) > VALUE_LIST_LIMIT:
        return value[:VALUE_LIST_LIMIT]
    return value


class SelfLabel(_Closed):
    """How the player itself says a choice relates to its values."""

    served: list[str] = Field(max_length=4)
    violated: list[str] = Field(max_length=4)
    direction: Direction

    _cut = field_validator("served", "violated", mode="before")(_cut_values)


class FastReply(_Closed):
    thought: str
    action: ActionRequest
    self_label: SelfLabel
    expected_feel: int = Field(ge=-10, le=10)
    needs_more_thought: bool


class Option(_Closed):
    action: ActionRequest
    serves: list[str] = Field(max_length=4)
    violates: list[str] = Field(max_length=4)
    feel_now: int = Field(ge=-10, le=10)
    feel_later: int = Field(ge=-10, le=10)
    relationships: str
    villagers: str
    uncertainty: Uncertainty

    _cut = field_validator("serves", "violates", mode="before")(_cut_values)


class SlowReply(_Closed):
    thought: str
    options: list[Option] = Field(min_length=2, max_length=4)
    choice_index: int = Field(ge=0)
    trade_off: str
    self_label: SelfLabel


class Read(_Closed):
    person: str
    feeling: str
    intent: str
    uncertainty: Uncertainty


class NoticerReply(_Closed):
    reads: list[Read] = Field(max_length=4)


class AdvisorReply(_Closed):
    advice: str
    recommended_kind: str
    past_patterns: list[str] = Field(max_length=5)


class RankingEntry(_Closed):
    value_id: str
    weight: float


class RankingReply(_Closed):
    entries: list[RankingEntry]


class InventedValue(_Closed):
    name: str
    definition: str
    priority: float = Field(gt=0)
    conflicts: list[str]
    observable_behaviour: str


class KnowledgeUpdate(_Closed):
    subject: str
    claim: str
    confidence: float = Field(ge=0.0, le=1.0)


class Insight(_Closed):
    decision_key: str
    insight: str


class ReflectionReply(_Closed):
    requested_changes: dict[str, float]  # sent to providers as a [{key, value}] list
    cause_event_ids: list[int]
    invented_values: list[InventedValue] = Field(max_length=2)
    identity: str
    knowledge_updates: list[KnowledgeUpdate] = Field(max_length=5)
    rolling_summary: str
    insights: list[Insight]


REPLY_TYPES: dict[str, type[BaseModel]] = {
    "fast": FastReply,
    "slow": SlowReply,
    "noticer": NoticerReply,
    "advisor": AdvisorReply,
    "ranking": RankingReply,
    "reflection": ReflectionReply,
}


def _texts(reply: BaseModel) -> list[tuple[str, str]]:
    """Every free-text field of a reply as (where, text)."""
    found: list[tuple[str, str]] = []

    def walk(obj: Any, path: str) -> None:
        if isinstance(obj, BaseModel):
            for name in type(obj).model_fields:
                if isinstance(obj, ActionRequest) and name != "text":
                    continue
                walk(getattr(obj, name), f"{path}.{name}" if path else name)
        elif isinstance(obj, str):
            found.append((path, obj))
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                walk(item, f"{path}[{i}]")

    walk(reply, "")
    return found


def _label_problems(label: SelfLabel, ids: set[str], where: str) -> list[str]:
    return [
        f"{where}: unknown value '{v}'" for v in [*label.served, *label.violated] if v not in ids
    ]


def check_reply(
    reply: BaseModel,
    value_ids: set[str] | frozenset[str] | list[str],
    settings: MindSettings = DEFAULT_SETTINGS,
) -> list[str]:
    """Problems that Pydantic cannot see: unknown value ids, over-long texts, bad choice index.

    An empty list means the reply is acceptable. The caller treats any problem as a format error.
    """
    ids = set(value_ids)
    problems: list[str] = []
    limit = settings.text_max_chars
    for where, text in _texts(reply):
        cap = settings.summary_max_chars if where == "rolling_summary" else limit
        if len(text) > cap:
            problems.append(f"{where}: {len(text)} characters (limit {cap})")
    if isinstance(reply, FastReply):
        problems += _label_problems(reply.self_label, ids, "self_label")
    elif isinstance(reply, SlowReply):
        problems += _label_problems(reply.self_label, ids, "self_label")
        if not settings.options_min <= len(reply.options) <= settings.options_max:
            problems.append(f"options: {len(reply.options)} given")
        if reply.choice_index >= len(reply.options):
            problems.append(f"choice_index {reply.choice_index} is outside the options")
        for i, opt in enumerate(reply.options):
            for v in [*opt.serves, *opt.violates]:
                if v not in ids:
                    problems.append(f"options[{i}]: unknown value '{v}'")
    elif isinstance(reply, RankingReply):
        pass  # repaired by code (repair_initial_weights), never rejected
    elif isinstance(reply, ReflectionReply):
        for v in reply.requested_changes:
            if v not in ids:
                problems.append(f"requested_changes: unknown value '{v}'")
    return problems
