"""A player's memory stream: scoring, retrieval and the short "recent" list for hooked players.

Score = recency_weight * 2**(-(now - tick) / half_life)
      + importance_weight * importance
      + relevance_weight * (1 + cos) / 2
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any, Protocol

from ai_island.minds.settings import DEFAULT_SETTINGS, MindSettings


@dataclass(frozen=True)
class MemoryItem:
    id: int
    tick: int
    kind: str
    text: str
    importance: float  # 0..1

    def to_state(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_state(cls, state: dict[str, Any]) -> MemoryItem:
        return cls(
            int(state["id"]),
            int(state["tick"]),
            str(state["kind"]),
            str(state["text"]),
            float(state["importance"]),
        )


class _Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine of two vectors; 0.0 when either is the zero vector."""
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return sum(x * y for x, y in zip(a, b, strict=False)) / (na * nb)


def score(
    item: MemoryItem, now: int, cos: float, settings: MindSettings = DEFAULT_SETTINGS
) -> float:
    """The retrieval score of one item given its cosine similarity to the query."""
    age = max(0, now - item.tick)
    recency = 2.0 ** (-age / settings.memory_half_life_ticks)
    return (
        settings.recency_weight * recency
        + settings.importance_weight * item.importance
        + settings.relevance_weight * (1.0 + cos) / 2.0
    )


def retrieve(
    stream: Sequence[MemoryItem],
    query: str,
    now: int,
    limit: int,
    embedder: _Embedder,
    settings: MindSettings = DEFAULT_SETTINGS,
) -> list[MemoryItem]:
    """The ``limit`` best items for ``query``: score descending, ties newest tick then lowest id."""
    if not stream or limit <= 0:
        return []
    vectors = embedder.embed([query, *[m.text for m in stream]])
    q = vectors[0]
    scored = [(score(m, now, cosine(q, vectors[i + 1]), settings), m) for i, m in enumerate(stream)]
    scored.sort(key=lambda sm: (-sm[0], -sm[1].tick, sm[1].id))
    return [m for _, m in scored[:limit]]


def recent(stream: Sequence[MemoryItem], n: int) -> list[MemoryItem]:
    """The newest ``n`` items, newest first (no embedding, no search)."""
    if n <= 0:
        return []
    ordered = sorted(stream, key=lambda m: (-m.tick, -m.id))
    return ordered[:n]


def append(
    stream: list[MemoryItem], item: MemoryItem, settings: MindSettings = DEFAULT_SETTINGS
) -> None:
    """Add an item; when the stream passes ``stream_max`` the oldest, least important go first."""
    stream.append(item)
    excess = len(stream) - settings.stream_max
    if excess > 0:
        drop = sorted(stream, key=lambda m: (m.importance, m.tick, m.id))[:excess]
        ids = {m.id for m in drop}
        stream[:] = [m for m in stream if m.id not in ids]
