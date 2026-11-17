"""The pretend AI: a fake adapter and a fake embedder (Contract C5). No network, no cost."""

from __future__ import annotations

import json
import math
import threading
import time
import types
import typing
from collections.abc import Callable
from typing import Any, Literal, get_args, get_origin

import annotated_types
from pydantic import BaseModel
from pydantic.fields import FieldInfo

from ai_island.config import RoleConfig
from ai_island.llm.errors import NetworkError, RateLimitError
from ai_island.llm.types import LLMRequest, RawReply, Usage

FAKE_MODEL_VERSION = "fake-1"
_FIXED_TEXT = "ok"


def _constraint(info: FieldInfo | None, kind: type) -> Any:
    if info is None:
        return None
    for m in info.metadata:
        if isinstance(m, kind):
            return m
    return None


def _bound(info: FieldInfo | None) -> tuple[float | None, float | None]:
    lo = hi = None
    if info is not None:
        for m in info.metadata:
            if isinstance(m, annotated_types.Ge):
                lo = float(m.ge)  # type: ignore[arg-type]
            elif isinstance(m, annotated_types.Gt):
                lo = float(m.gt) + 1e-6  # type: ignore[arg-type]
            elif isinstance(m, annotated_types.Le):
                hi = float(m.le)  # type: ignore[arg-type]
            elif isinstance(m, annotated_types.Lt):
                hi = float(m.lt) - 1e-6  # type: ignore[arg-type]
    return lo, hi


def _sample(ann: Any, info: FieldInfo | None, fallback: dict[str, Any]) -> Any:
    """A valid value for ``ann``: the simplest one that satisfies the field's bounds."""
    origin = get_origin(ann)
    if origin is typing.Annotated:
        return _sample(get_args(ann)[0], info, fallback)
    if origin is Literal:
        return get_args(ann)[0]
    if origin in (typing.Union, types.UnionType):
        args = [a for a in get_args(ann) if a is not type(None)]
        if len(args) < len(get_args(ann)):
            return None
        return _sample(args[0], info, fallback)
    if origin is list:
        item = get_args(ann)[0] if get_args(ann) else str
        minlen = _constraint(info, annotated_types.MinLen)
        n = minlen.min_length if minlen else 0
        return [_sample(item, None, fallback) for _ in range(n)]
    if origin is dict:
        return {}
    if isinstance(ann, type) and issubclass(ann, BaseModel):
        return _build(ann, fallback)
    if ann is bool:
        return False
    lo, hi = _bound(info)
    if ann is int:
        v = 0 if lo is None else math.ceil(lo)
        if hi is not None and v > hi:
            v = math.floor(hi)
        return v
    if ann is float:
        v = 0.0 if lo is None else lo
        if hi is not None and v > hi:
            v = hi
        return v
    return _FIXED_TEXT


def _build(model: type[BaseModel], fallback: dict[str, Any]) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for name, info in model.model_fields.items():
        if name in fallback:
            data[name] = fallback[name]
        else:
            data[name] = _sample(info.annotation, info, fallback)
    return data


def auto_reply(request: LLMRequest) -> str:
    """A valid reply for ``request.schema`` built from ``meta["fallback"]`` and fixed text."""
    fallback = dict(request.meta.get("fallback") or {})
    return json.dumps(_build(request.schema, fallback), sort_keys=True)


class FakeAdapter:
    """Answers without any network. Deterministic and thread-safe.

    ``script[(player_id, purpose)]``: replies (dicts or raw strings) popped one per attempt.
    ``failures[(player_id, purpose)]``: "network" | "rate_limit" | "refusal" | "sleep", one per
    attempt. ``delays[(player_id, purpose)]``: seconds to wait. ``gate``: a Barrier or Event
    (or any callable) waited on inside ``generate`` so overlap tests can prove concurrency.
    ``on_sleep`` is called before a "sleep" failure so a test can advance its fake wall clock.
    """

    def __init__(
        self,
        script: dict[tuple[str | None, str], list[Any]] | None = None,
        delays: dict[tuple[str | None, str], float] | None = None,
        failures: dict[tuple[str | None, str], list[str]] | None = None,
        bill: bool = False,
        gate: Any = None,
        on_sleep: Callable[[], None] | None = None,
    ) -> None:
        self.script = {k: list(v) for k, v in (script or {}).items()}
        self.delays = dict(delays or {})
        self.failures = {k: list(v) for k, v in (failures or {}).items()}
        self.bill = bill
        self.gate = gate
        self.on_sleep = on_sleep
        self.calls: dict[str, int] = {}
        self.total_calls = 0
        self._sent_prefix: dict[tuple[str | None, str], str] = {}
        self._lock = threading.Lock()

    def generate(self, request: LLMRequest, role: RoleConfig) -> RawReply:
        slot = (request.player_id, request.purpose)
        family = str(request.meta.get("family", "player"))
        prefix = request.layers.fixed + request.layers.slow
        with self._lock:
            self.calls[request.key] = self.calls.get(request.key, 0) + 1
            self.total_calls += 1
            failure = self.failures[slot].pop(0) if self.failures.get(slot) else None
            scripted = self.script[slot].pop(0) if self.script.get(slot) else None
            seen = self._sent_prefix.get((request.player_id, family))
            self._sent_prefix[(request.player_id, family)] = prefix
            cached = seen == prefix
        started = time.perf_counter()
        if self.gate is not None:
            wait = getattr(self.gate, "wait", self.gate)
            wait()
        delay = self.delays.get(slot, 0.0)
        if delay:
            time.sleep(delay)
        if failure == "network":
            raise NetworkError("fake network failure")
        if failure == "rate_limit":
            raise RateLimitError("fake rate limit")
        if failure == "sleep":
            if self.on_sleep is not None:
                self.on_sleep()
            raise NetworkError("fake failure after the laptop slept")
        refused = failure == "refusal"
        if refused:
            text = ""
        elif scripted is None:
            text = auto_reply(request)
        elif isinstance(scripted, str):
            text = scripted
        else:
            text = json.dumps(scripted, sort_keys=True)
        total_in = math.ceil(request.layers.chars() / 4)
        cache_read = math.ceil(len(prefix) / 4) if cached else 0
        usage = Usage(
            input_tokens=max(0, total_in - cache_read),
            output_tokens=math.ceil(len(text) / 4),
            thinking_tokens=0,
            cache_read_tokens=cache_read,
            cache_write_tokens=0,
        )
        return RawReply(
            text=text,
            usage=usage,
            model_version=FAKE_MODEL_VERSION,
            refused=refused,
            duration_ms=(time.perf_counter() - started) * 1000.0,
        )


class FakeEmbedder:
    """Bag-of-words hashing embedder: same text, same vector; empty text, zero vector."""

    def __init__(self, dims: int = 64) -> None:
        self.dims = dims

    def _one(self, text: str) -> list[float]:
        import hashlib
        import re

        vec = [0.0] * self.dims
        for word in re.findall(r"\w+", text.lower()):
            digest = hashlib.sha256(word.encode("utf-8")).digest()
            vec[int.from_bytes(digest[:8], "big") % self.dims] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0.0:
            return vec
        return [v / norm for v in vec]

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]
