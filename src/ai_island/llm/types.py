"""Common request and reply objects of the AI layer (Contract C1).

``Usage.input_tokens`` is the UNCACHED input only; ``output_tokens`` is all billable output
including thinking, counted once; ``thinking_tokens`` is informational (None when the
provider does not report it, never estimated).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from ai_island.config import RoleConfig

Purpose = Literal["fast", "noticer", "advisor", "main", "ranking", "reflection", "judge"]
Status = Literal[
    "ok",
    "format_error",
    "refusal",
    "network_error",
    "rate_limit",
    "sleep_error",
    "request_error",
    "budget_blocked",
]


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int | None = None
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass(frozen=True)
class PromptLayers:
    fixed: str
    slow: str
    current: str

    def chars(self) -> int:
        return len(self.fixed) + len(self.slow) + len(self.current)


@dataclass(frozen=True)
class LLMRequest:
    key: str
    tick: int
    player_id: str | None
    role: str
    purpose: Purpose
    layers: PromptLayers
    schema: type[BaseModel]
    max_output_tokens: int
    meta: dict[str, Any] = field(default_factory=dict)


def request_key(tick: int, player_id: str | None, purpose: str, ordinal: int) -> str:
    """The durable identity of a request: ``tick/player/purpose/ordinal``."""
    return f"{tick}/{player_id}/{purpose}/{ordinal}"


def attempt_key(key: str, attempt: int) -> str:
    """The identity of the n-th (0-based) physical attempt of a request."""
    return f"{key}/{attempt}"


@dataclass
class LLMResult:
    key: str
    status: Status
    parsed: BaseModel | None = None
    raw_reply: str | None = None
    usage: Usage = field(default_factory=Usage)
    model_version: str = ""
    cost_usd: float = 0.0
    duration_ms: float = 0.0
    attempts: int = 1
    ai_call_ids: list[int] = field(default_factory=list)
    reused: bool = False


@dataclass(frozen=True)
class RawReply:
    text: str
    usage: Usage
    model_version: str
    refused: bool = False
    duration_ms: float = 0.0


class Adapter(Protocol):
    """One provider. Raises NetworkError / RateLimitError (llm/errors.py)."""

    def generate(self, request: LLMRequest, role: RoleConfig) -> RawReply: ...


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...
