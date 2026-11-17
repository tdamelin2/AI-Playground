"""The CallBroker: drives the players' request generators through the AI adapters (Contract C5).

Every pipeline is a generator that yields ``LLMRequest`` objects and receives ``LLMResult``
objects. The broker keeps them all moving at once (one worker thread per call in flight, up to
``max_parallel``), but everything that touches the database, the money ledger or a generator
happens on the calling thread. Workers only see a detached request and role.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Generator
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from typing import Any

from ai_island.config import AiRun, ModelsConfig, RoleConfig
from ai_island.llm.errors import (
    NetworkError,
    ProviderRequestError,
    RateLimitError,
    ReplayMissingError,
    RunPaused,
)
from ai_island.llm.fake import FakeAdapter
from ai_island.llm.ledger import SpendLedger
from ai_island.llm.prices import cost_usd, upper_bound_usd
from ai_island.llm.schema_transform import from_wire
from ai_island.llm.types import (
    Adapter,
    LLMRequest,
    LLMResult,
    RawReply,
    Usage,
    attempt_key,
)
from ai_island.storage.db import AiCallRow, RunDB

_NETWORK_STATUSES = ("network_error", "rate_limit", "sleep_error", "request_error")
# request.meta keys copied into an ai_calls row's details (the judge's summaries need them)
_META_KEYS = ("judge_kind", "period", "subject_id")


@dataclass
class _Job:
    order: int
    pid: str
    gen: Generator[LLMRequest, LLMResult, Any]
    request: LLMRequest | None = None
    role: RoleConfig | None = None
    adapter: Adapter | None = None
    attempt: int = 0
    net_fail: int = 0
    fmt_fail: int = 0
    ids: list[int] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    cache_read: int = 0
    cache_write: int = 0
    thinking: int | None = None
    cost: float = 0.0
    duration_ms: float = 0.0
    model_version: str = ""
    reserved_key: str | None = None
    last_text: str | None = None


@dataclass
class _Attempt:
    """What a worker brings back: a reply or the error it hit, and the wall seconds it took."""

    reply: RawReply | None
    error: Exception | None
    seconds: float


class CallBroker:
    def __init__(
        self,
        db: RunDB | None,
        models: ModelsConfig,
        ai_cfg: AiRun,
        adapters: dict[str, Adapter],
        ledger: SpendLedger,
        sleep: Callable[[float], None] = time.sleep,
        wall: Callable[[], float] = time.time,
        replay: bool = False,
        wait_hook: Callable[[], None] | None = None,
    ) -> None:
        self.db = db
        self.models = models
        self.cfg = ai_cfg
        self.adapters = adapters
        self.ledger = ledger
        self.sleep = sleep
        self.wall = wall
        self.replay = replay
        self.wait_hook = wait_hook
        self.rows: list[AiCallRow] = []  # kept when there is no database (tests)
        self._pause: RunPaused | None = None
        self._ready: dict[int, tuple[_Job, LLMResult | None]] = {}

    # ------------------------------------------------------------------------------ public

    def run(self, pipelines: dict[str, Generator[LLMRequest, LLMResult, Any]]) -> dict[str, Any]:
        """Run every pipeline to its end; returns ``{player: return value}``."""
        self._pause = None
        results: dict[str, Any] = {}
        pending: dict[Future[_Attempt], _Job] = {}
        # Generators only advance in rounds, in pipeline order: whatever a pipeline does between
        # two requests (events, memory) therefore never depends on which reply came back first.
        # The calls of one round still run at the same time.
        ready: dict[int, tuple[_Job, LLMResult | None]] = {}
        self._ready = ready
        executor = ThreadPoolExecutor(max_workers=max(1, self.cfg.max_parallel))
        try:
            for order, (pid, gen) in enumerate(pipelines.items()):
                ready[order] = (_Job(order, pid, gen), None)
            last_hook = time.monotonic()
            while ready:
                batch = [ready.pop(o) for o in sorted(ready)]
                for job, result in batch:
                    if self._pause is not None:
                        job.gen.close()
                    else:
                        self._feed(job, result, results, pending, executor)
                while pending:
                    done, _ = wait(
                        list(pending),
                        timeout=self.cfg.wait_hook_seconds,
                        return_when=FIRST_COMPLETED,
                    )
                    for fut in sorted(done, key=lambda f: pending[f].order):
                        job = pending.pop(fut)
                        self._finish_attempt(job, fut.result(), results, pending, executor)
                    if self.wait_hook is not None and pending:
                        now = time.monotonic()
                        if now - last_hook >= self.cfg.wait_hook_seconds:
                            self.wait_hook()
                            last_hook = now
        finally:
            executor.shutdown(wait=True)
        if self._pause is not None:
            raise self._pause
        return {pid: results[pid] for pid in pipelines if pid in results}

    # ------------------------------------------------------------------- generator plumbing

    def _feed(
        self,
        job: _Job,
        result: LLMResult | None,
        results: dict[str, Any],
        pending: dict[Future[_Attempt], _Job],
        executor: ThreadPoolExecutor,
    ) -> None:
        """Send a result into the generator (None starts it) and handle what it yields next."""
        try:
            request = next(job.gen) if result is None else job.gen.send(result)
        except StopIteration as stop:
            results[job.pid] = stop.value
            return
        if self._pause is not None:
            job.gen.close()
            return
        self._begin(job, request, results, pending, executor)

    def _begin(
        self,
        job: _Job,
        request: LLMRequest,
        results: dict[str, Any],
        pending: dict[Future[_Attempt], _Job],
        executor: ThreadPoolExecutor,
    ) -> None:
        role = self.models.roles[request.role]
        adapter = self.adapters.get(role.provider)
        if adapter is None and self.cfg.backend != "live":
            adapter = self.adapters.get("fake")  # practice runs only: never in a live run
        if adapter is None:
            raise KeyError(f"no adapter for provider '{role.provider}'")
        job.request, job.role, job.adapter = request, role, adapter
        job.attempt = job.net_fail = job.fmt_fail = 0
        job.ids = []
        job.tokens_in = job.tokens_out = job.cache_read = job.cache_write = 0
        job.thinking = None
        job.cost = job.duration_ms = 0.0
        job.model_version = ""
        job.last_text = None
        self._step(job, results, pending, executor, delay=0.0)

    def _step(
        self,
        job: _Job,
        results: dict[str, Any],
        pending: dict[Future[_Attempt], _Job],
        executor: ThreadPoolExecutor,
        delay: float,
    ) -> None:
        """Move a request forward: reuse stored attempts, else reserve money and send."""
        assert job.request is not None and job.role is not None and job.adapter is not None
        request, role = job.request, job.role
        while True:
            akey = attempt_key(request.key, job.attempt)
            stored = self.db.find_ai_call(akey) if self.db is not None else None
            if stored is not None and stored.status in _NETWORK_STATUSES:
                later = self.db.find_ai_call(attempt_key(request.key, job.attempt + 1))  # type: ignore[union-attr]
                if later is not None:
                    job.attempt += 1
                    continue
                stored = None  # the last stored try failed: ask again (a resumed run)
                job.net_fail = 0
            if stored is not None:
                self._count(job, stored)
                job.ids.append(stored.id or 0)
                outcome = self._judge(request, stored.reply_text or "", stored.status == "refusal")
                if self._after_reply(job, outcome, reused=True, results=results):
                    self._deliver(job, outcome, reused=True, results=results, pending=pending,
                                  executor=executor)  # fmt: skip
                    return
                job.attempt += 1
                continue
            if self.replay:
                raise ReplayMissingError(f"no stored reply for {akey}")
            bound = upper_bound_usd(request, role, self.cfg.framing_tokens)
            if not self.ledger.reserve(akey, bound):
                self._set_pause(RunPaused("spend_cap", "the spending limit was reached"))
                job.gen.close()
                return
            job.reserved_key = akey
            fut = executor.submit(self._send, job.adapter, request, role, delay)
            pending[fut] = job
            return

    def _set_pause(self, pause: RunPaused) -> None:
        if self._pause is None:
            self._pause = pause

    # --------------------------------------------------------------------------- the worker

    def _send(self, adapter: Adapter, request: LLMRequest, role: RoleConfig, delay: float):
        if delay > 0:
            self.sleep(delay)
        started = self.wall()
        try:
            reply = adapter.generate(request, role)
            return _Attempt(reply, None, self.wall() - started)
        except (NetworkError, RateLimitError, ProviderRequestError) as exc:
            return _Attempt(None, exc, self.wall() - started)

    # ----------------------------------------------------------------------- after a worker

    def _finish_attempt(
        self,
        job: _Job,
        att: _Attempt,
        results: dict[str, Any],
        pending: dict[Future[_Attempt], _Job],
        executor: ThreadPoolExecutor,
    ) -> None:
        assert job.request is not None and job.role is not None and job.adapter is not None
        request, role = job.request, job.role
        akey = job.reserved_key or attempt_key(request.key, job.attempt)
        if att.error is not None:
            self.ledger.release(akey)
            if isinstance(att.error, ProviderRequestError):
                err = att.error
                self._write(job, "request_error", None, Usage(), "", 0.0, att.seconds * 1000.0,
                            {"type": type(err).__name__, "status": err.status_code,
                             "message": err.message, "request_id": err.request_id,
                             "provider": role.provider})  # fmt: skip
                self._set_pause(
                    RunPaused(
                        "provider_error",
                        f"{role.provider} rejected the request (HTTP {err.status_code}): "
                        f"{err.message}",
                    )
                )
                job.gen.close()
                return
            slept = isinstance(att.error, NetworkError) and att.seconds > self.cfg.sleep_gap_seconds
            if slept:
                status = "sleep_error"
            elif isinstance(att.error, RateLimitError):
                status = "rate_limit"
            else:
                status = "network_error"
            self._write(job, status, None, Usage(), "", 0.0, att.seconds * 1000.0,
                        {"type": type(att.error).__name__, "message": str(att.error)})  # fmt: skip
            if slept:
                self._set_pause(RunPaused("sleep", "the laptop went to sleep during a call"))
                job.gen.close()
                return
            job.net_fail += 1
            if job.net_fail > self.cfg.network_retries or self._pause is not None:
                self._set_pause(RunPaused("network", "no connection to the AI provider"))
                job.gen.close()
                return
            wait_s = self.cfg.retry_wait_seconds[job.net_fail - 1]
            job.attempt += 1
            # the wait happens inside the worker, so the other players keep going
            self._step(job, results, pending, executor, delay=wait_s)
            return
        reply = att.reply
        assert reply is not None
        priced = not isinstance(job.adapter, FakeAdapter) or job.adapter.bill
        cost = cost_usd(reply.usage, role.prices) if priced else 0.0
        outcome = self._judge(request, reply.text, reply.refused)
        status = outcome[0]
        duration_ms = reply.duration_ms or att.seconds * 1000.0
        call_id = self._write(job, status, reply.text, reply.usage, reply.model_version, cost,
                              duration_ms, None, spend=True)  # fmt: skip
        self.ledger.settle(akey, cost)
        job.ids.append(call_id)
        job.cost += cost
        self._count_usage(job, reply.usage, reply.model_version, reply.duration_ms)
        if self._after_reply(job, outcome, reused=False, results=results):
            self._deliver(job, outcome, reused=False, results=results, pending=pending,
                          executor=executor)  # fmt: skip
            return
        job.attempt += 1
        self._step(job, results, pending, executor, delay=0.0)

    # ------------------------------------------------------------------------ judging replies

    def _judge(self, request: LLMRequest, text: str, refused: bool):
        """(status, parsed): refusal, format_error or ok."""
        low = text.lower()
        # the judge writes analytical text: only the provider's own refusal flag counts for it
        phrases = () if request.purpose == "judge" else self.cfg.break_character_phrases
        if refused or any(p.lower() in low for p in phrases):
            return ("refusal", None)
        try:
            return (
                "ok",
                request.schema.model_validate(from_wire(json.loads(text), request.schema)),
            )
        except (ValueError, TypeError):
            return ("format_error", None)

    def _after_reply(self, job: _Job, outcome, reused: bool, results) -> bool:
        """True when the request is finished (deliver it); False to try another attempt."""
        status = outcome[0]
        if status == "format_error" and job.fmt_fail < self.cfg.format_retries:
            job.fmt_fail += 1
            return False
        return True

    def _deliver(self, job, outcome, reused, results, pending, executor) -> None:
        assert job.request is not None
        status, parsed = outcome
        result = LLMResult(
            key=job.request.key,
            status=status,
            parsed=parsed,
            raw_reply=job.last_text,
            usage=Usage(
                job.tokens_in, job.tokens_out, job.thinking, job.cache_read, job.cache_write
            ),
            model_version=job.model_version,
            cost_usd=job.cost,
            duration_ms=job.duration_ms,
            attempts=job.attempt + 1,
            ai_call_ids=list(job.ids),
            reused=reused,
        )
        self._ready[job.order] = (job, result)  # fed in the next round, in pipeline order

    # ----------------------------------------------------------------------------- bookkeeping

    def _count(self, job: _Job, row: AiCallRow) -> None:
        usage = Usage(
            row.input_tokens,
            row.output_tokens,
            row.thinking_tokens,
            row.cache_read_tokens,
            row.cache_write_tokens,
        )
        job.last_text = row.reply_text
        self._count_usage(job, usage, row.model_version, row.duration_ms)

    def _count_usage(self, job: _Job, usage: Usage, model_version: str, duration_ms: float) -> None:
        job.tokens_in += usage.input_tokens
        job.tokens_out += usage.output_tokens
        job.cache_read += usage.cache_read_tokens
        job.cache_write += usage.cache_write_tokens
        if usage.thinking_tokens is not None:
            job.thinking = (job.thinking or 0) + usage.thinking_tokens
        job.model_version = model_version
        job.duration_ms += duration_ms

    def _write(
        self,
        job: _Job,
        status: str,
        text: str | None,
        usage: Usage,
        model_version: str,
        cost: float,
        duration_ms: float,
        error: dict | None,
        spend: bool = False,
    ) -> int:
        request, role = job.request, job.role
        assert request is not None and role is not None
        if text is not None:
            job.last_text = text
        row = AiCallRow(
            tick=request.tick,
            player_id=request.player_id,
            role=request.role,
            provider=role.provider,
            model_version=model_version,
            prompt={
                "fixed": request.layers.fixed,
                "slow": request.layers.slow,
                "current": request.layers.current,
                "schema": request.schema.__name__,
            },
            reply_text=text,
            thinking_tokens=usage.thinking_tokens,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_tokens,
            cache_write_tokens=usage.cache_write_tokens,
            cost_usd=cost,
            duration_ms=duration_ms,
            status=status,
            details={
                "key": request.key,
                "attempt": job.attempt,
                "purpose": request.purpose,
                "role": request.role,
                "model": role.model,
                "settings": dict(role.thinking),
                **{k: request.meta[k] for k in _META_KEYS if k in request.meta},
            },
            error=error,
        )
        if self.db is None:
            self.rows.append(row)
            row.id = len(self.rows)
            return row.id
        if spend:  # the call row and its spend row are stored in one transaction
            row.id = self.db.record_attempt(row, cost)
        else:
            row.id = self.db.insert_ai_call(row)
        return row.id
