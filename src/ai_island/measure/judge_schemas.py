"""Reply schemas of the blind judge (Contract C5). All closed (extra="forbid") and strict.

The shapes are fixed here. Checks that need run data (a player's value ids, the text limits from
balance.toml) are added by ``bind_schema``, which returns a subclass with the same class name (so
stored prompts and provider schemas are unchanged) whose validator fails the broker's format check.
"""

from __future__ import annotations

from collections.abc import Collection
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator, model_validator

Direction = Literal["toward", "against"]
Promise = Literal["none", "made", "kept", "broken"]
FlagKind = Literal["betrayal", "death", "new_belief"]


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def _cut_to(limit: int):
    """A before-validator keeping the first `limit` value ids (most important first)."""

    def cut(value: object) -> object:
        if isinstance(value, list) and len(value) > limit:
            return value[:limit]
        return value

    return cut


class FullJudgeLabel(_Closed):
    """The judge's full reading of a flagged choice."""

    served: list[str] = Field(max_length=4)
    violated: list[str] = Field(max_length=4)
    direction: Direction
    harm: bool
    promise: Promise
    betrayal: bool
    superstition: bool
    new_belief: str
    rationale: str = Field(min_length=1)
    evidence: list[str] = Field(min_length=1, max_length=3)

    _cut = field_validator("served", "violated", mode="before")(_cut_to(4))


class ShortJudgeLabel(_Closed):
    """The judge's short reading of a routine choice."""

    served: list[str] = Field(max_length=2)
    violated: list[str] = Field(max_length=2)
    direction: Direction

    _cut = field_validator("served", "violated", mode="before")(_cut_to(2))


class FlagItem(_Closed):
    kind: FlagKind
    who: list[str]
    what: str


class DailySummaryReply(_Closed):
    summary: str
    flags: list[FlagItem] = Field(max_length=5)


class ProfileReply(_Closed):
    profile: str
    values_seen: list[str] = Field(max_length=5)
    change: str


JUDGE_SCHEMAS: dict[str, type[BaseModel]] = {
    "full": FullJudgeLabel,
    "short": ShortJudgeLabel,
    "daily_summary": DailySummaryReply,
    "weekly_profile": ProfileReply,
}


def schema_problems(
    reply: BaseModel,
    value_ids: Collection[str] | None,
    text_limit: int | None,
) -> list[str]:
    """Problems Pydantic cannot see: unknown value ids and over-long texts."""
    problems: list[str] = []
    if value_ids is not None:
        for field in ("served", "violated", "values_seen"):
            for v in getattr(reply, field, ()):
                if v not in value_ids:
                    problems.append(f"{field}: unknown value '{v}'")
    if text_limit is not None:
        for field in ("rationale", "summary", "profile", "change", "new_belief"):
            text = getattr(reply, field, None)
            if isinstance(text, str) and len(text) > text_limit:
                problems.append(f"{field}: {len(text)} characters (limit {text_limit})")
    return problems


_BOUND: dict[tuple[type[BaseModel], frozenset[str] | None, int | None], type[BaseModel]] = {}


def bind_schema(
    base: type[BaseModel],
    value_ids: Collection[str] | None = None,
    text_limit: int | None = None,
) -> type[BaseModel]:
    """``base`` plus the run's checks: value ids must be in ``value_ids``, texts at most
    ``text_limit`` characters. Any problem is a validation error, so the broker's one format
    retry applies. The class keeps the base class name."""
    ids = None if value_ids is None else frozenset(value_ids)
    key = (base, ids, text_limit)
    if key in _BOUND:
        return _BOUND[key]

    def _check(self: BaseModel) -> BaseModel:
        problems = schema_problems(self, ids, text_limit)
        if problems:
            raise ValueError("; ".join(problems))
        return self

    bound = create_model(
        base.__name__,
        __base__=base,
        __module__=base.__module__,
        __doc__=base.__doc__,
        __validators__={"_run_checks": model_validator(mode="after")(_check)},
    )
    _BOUND[key] = bound
    return bound
