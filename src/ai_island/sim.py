"""The simulation session: owns the world, the random streams and the tick loop.

Headless runs are unpaced; live runs pass ``pace_seconds``. Rendering and wall-clock time
never enter the world, so the same seed always gives the same event log.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable
from typing import Any

from ai_island.config import PROVIDERS, AssetsConfig, GameConfig, RunConfig
from ai_island.llm.errors import ReplayMissingError, RunPaused
from ai_island.rng import Streams
from ai_island.rules.turn import DecisionContext, run_turn
from ai_island.storage.db import RunDB, Snapshot
from ai_island.storage.events import Event
from ai_island.storage.records import (
    ChoiceInsight,
    ChoiceOutcome,
    ChoicePointRecord,
    ValueHistoryRow,
)
from ai_island.world.clock import Clock
from ai_island.world.engine import advance_to, schedule_turn
from ai_island.world.mapgen import generate_world
from ai_island.world.people import spawn_people
from ai_island.world.state import World

SNAPSHOT_VERSION = 3  # the saved-state layout (the database layout, SCHEMA_VERSION, is separate)


class SnapshotError(Exception):
    """A snapshot cannot be restored (wrong version or damaged config)."""


class SimulationBroken(RuntimeError):
    """A run stopped in the middle of a tick (RunPaused); it can only continue via recover()."""


class _NoCallAdapter:
    """Stands in for a provider while a live run's stored tail is replayed: never sends."""

    def generate(self, request: Any, role: Any) -> Any:
        raise ReplayMissingError(f"replay never calls a provider ({request.key})")


class _NoCallEmbedder:
    """Stands in for the embedder during a live replay: only cached vectors may be used."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise ReplayMissingError("replay never embeds text that is not in the embedding cache")


def _with_ai(
    config: GameConfig,
    seats: list[int],
    cheap: bool,
    max_dollars: float | None,
    backend: str,
    end_tick: int | None,
    new_ticks: int | None = None,
) -> GameConfig:
    data = config.run.model_dump(mode="json")
    data["ai"]["seats"] = sorted(set(seats))
    data["ai"]["cheap"] = bool(cheap)
    data["ai"]["backend"] = backend
    data["ai"]["end_tick"] = end_tick
    if new_ticks is not None:
        data["ai"]["new_ticks"] = new_ticks
    if seats:
        if max_dollars is None or not (0 < max_dollars < float("inf")):
            raise ValueError("an AI seat needs --max-dollars (a number above 0)")
        data["spend_cap_usd"] = min(float(max_dollars), float(config.run.spend_cap_usd))
    run = RunConfig.model_validate(data)
    return GameConfig(
        world=config.world,
        balance=config.balance,
        models=config.models,
        run=run,
        assets=config.assets,
    )


def ai_config(
    config: GameConfig,
    seats: list[int],
    cheap: bool = False,
    max_dollars: float | None = None,
    backend: str = "fake",
    end_tick: int | None = None,
) -> GameConfig:
    """``config`` with the AI seats, cheap flag, backend and the spending limit pinned in run.ai.

    The pinned limit is ``min(max_dollars, run.toml spend_cap_usd)``; LiveRun and the broker
    always use it. ``end_tick`` (optional) is a planned last tick the run never passes.
    Raises ValueError for a missing or non-positive limit when seats are given.
    """
    return _with_ai(config, seats, cheap, max_dollars, backend, end_tick)


def apply_profile(
    config: GameConfig, name: str, max_dollars: float, backend: str = "live"
) -> GameConfig:
    """``config`` set up for a run.toml profile (``pilot`` or ``launch``).

    The pilot runs ``weeks`` game weeks: ``end_tick`` is pinned and ``new_ticks`` equals it. The
    launch profile has no end tick and keeps run.toml's ``new_ticks``.
    """
    profile = config.run.profiles.get(name)
    if profile is None:
        raise ValueError(f"unknown profile '{name}' (known: {sorted(config.run.profiles)})")
    clock = config.world.clock
    end_tick = None
    if profile.weeks is not None:
        end_tick = profile.weeks * clock.ticks_per_day * clock.days_per_week
    return _with_ai(
        config, list(profile.seats), profile.cheap, max_dollars, backend, end_tick, end_tick
    )


class Simulation:
    """One running island."""

    def __init__(
        self,
        config: GameConfig,
        seed: int,
        streams: Streams,
        world: World,
        controllers: dict[str, Any] | None = None,
    ) -> None:
        self.config = config
        self.seed = seed
        self.streams = streams
        self.world = world
        self.controllers: dict[str, Any] = controllers or {}
        self.db: RunDB | None = None
        self._flushed = 0
        self.spend_usd = 0.0  # written to every snapshot; on attach it becomes db.spend_total()
        self.last_autosave_tick: int | None = None  # tick of the newest checkpoint written
        self.crash_after_tick: int | None = None  # test hook: flush, then os._exit(3)
        # Phase 4 hook: while True the mind layer must take AI replies from the stored ai_calls
        # rows keyed by (tick, player_id, call order) and must never make a call.
        self.replaying = False
        # Phase 4 (AI seats). Everything below is idle for rule-based runs.
        self.broken = False  # True after RunPaused: only recover() can continue the run
        self.records: list[Any] = []  # choice records kept while there is no database
        self.adapters: dict[str, Any] | None = None  # provider -> Adapter (default: fake)
        self.ai_sleep: Callable[[float], None] = time.sleep  # test hooks for the broker
        self.ai_wall: Callable[[], float] = time.time
        self.wait_hook: Callable[[], None] | None = None  # called while replies are awaited
        self.waits = 0  # how many times wait_hook ran (LiveRun resets its clock debt)
        self.defer_reflection: Callable[[], bool] | None = None  # True: do not start one now
        self.reflect_tick = -1  # tick of the newest week-end reflection round that was started
        self.replay_db: RunDB | None = None  # read-only source of stored replies during recover()
        self._ledger: Any = None
        self._broker: Any = None
        self._embedder: Any = None
        self.inner_embedder: Any = None  # test hook / cache: the embedder under the cache
        self._ai_ready = False
        # Phase 5: the blind judge. judge_pending means a drain was interrupted (or must catch up
        # after attach); the next _ai_step, LiveRun.resume or attach drains before any new tick.
        self.judge_pending = False
        self._judge: Any = None
        world.turn_handler = self._turn if world.players else None

    # ---------------------------------------------------------------------------- people

    @property
    def mixed(self) -> bool:
        """True when some seat is an AI (the two-pass turn and the broker are in use)."""
        return self.world.controller_kind == "mixed"

    def _turn(self, world: World, tick: int) -> None:
        if self.mixed:
            run_turn(world, tick, None, self._decide_many)
            return
        run_turn(world, tick, self._decide if self.controllers else None)

    def _decide(self, ctx: DecisionContext) -> Any:
        ctrl = self.controllers.get(ctx.player_id)
        return None if ctrl is None else ctrl.decide(ctx)

    def add_people(self, kind: str) -> None:
        """Spawn players and villagers and start the per-minute turn (kind 'none' adds nothing)."""
        if kind == "none":
            return
        from ai_island.minds import make_controllers

        if kind == "dummy" and self.config.run.ai.seats:
            kind = "mixed"
        spawn_people(self.world)
        schedule_turn(self.world)
        self.world.controller_kind = kind
        self.controllers = make_controllers(kind, self.world)
        self.world.turn_handler = self._turn

    # -------------------------------------------------------------------------- creation

    @classmethod
    def new(cls, config: GameConfig, seed: int, players: str | None = None) -> Simulation:
        """A fresh island at tick 0. `players` is dummy, scripted or none (default: run.toml).

        With ``config.run.ai.seats`` (see ``ai_config``) the run is mixed: those seats are AI
        players on the fake backend and the others are dummies.
        """
        streams = Streams(seed)
        world = generate_world(config, streams)
        sim = cls(config, seed, streams, world)
        sim.add_people(config.run.players.controller if players is None else players)
        return sim

    # ------------------------------------------------------------------------------- AI seats

    def ai_controllers(self) -> dict[str, Any]:
        """The AI seats' controllers (those with a broker pipeline), in player id order."""
        return {pid: c for pid, c in sorted(self.controllers.items()) if hasattr(c, "pipeline")}

    def _ensure_ai(self) -> None:
        """Build the ledger, embedder and broker on first use and bind the AI controllers."""
        if self._ai_ready:
            return
        from ai_island.llm.broker import CallBroker
        from ai_island.llm.embeddings import CachedEmbedder
        from ai_island.llm.factory import make_ollama_embedder, make_runtime
        from ai_island.llm.fake import FakeEmbedder
        from ai_island.llm.ledger import SpendLedger
        from ai_island.minds.runtime import MindsRuntime

        cfg = self.config
        live = cfg.run.ai.backend == "live"
        if (
            self.db is not None
        ):  # repair a paid call whose spend row was lost, then trust the ledger
            self.db.reconcile_spend()
            self.spend_usd = self.db.spend_total()
        adapters = self.adapters
        if live and self.replaying:
            # a replay only reads stored replies: build no real client and never reach the network
            adapters = {p: _NoCallAdapter() for p in PROVIDERS}
            inner: Any = _NoCallEmbedder()
        elif adapters is None:
            providers = [r.provider for r in cfg.models.roles.values()]
            adapters, inner = make_runtime(
                cfg.run.ai.backend,
                providers,
                cfg.models.embedding.model,
                cfg.run.ai.call_timeout_seconds,
            )
            self.adapters = adapters
            self.inner_embedder = inner
        elif self.inner_embedder is not None:
            inner = self.inner_embedder
        else:
            inner = make_ollama_embedder(cfg.models.embedding.model) if live else FakeEmbedder()
            self.inner_embedder = inner
        self._ledger = SpendLedger(
            cfg.run.spend_cap_usd, cfg.run.spend_warning_share, self.spend_usd
        )
        path = None
        if self.db is not None and self.db.path is not None:
            path = self.db.path.parent / "embeddings.sqlite"
        if self._embedder is not None:
            self._embedder.close()
        self._embedder = CachedEmbedder(inner, cfg.models.embedding.model, path)
        self._broker = CallBroker(
            self.db,
            cfg.models,
            cfg.run.ai,
            adapters,
            self._ledger,
            sleep=self.ai_sleep,
            wall=self.ai_wall,
            replay=self.replaying,
            wait_hook=self._wait,
        )
        runtime = MindsRuntime(
            self._embedder, cfg.models, cfg.balance, cfg.run.ai, cfg.run.ai.cheap
        )
        for ctrl in self.ai_controllers().values():
            ctrl.bind(runtime)
        self._ai_ready = True

    def _wait(self) -> None:
        self.waits += 1
        if self.wait_hook is not None:
            self.wait_hook()

    def _broker_run(self, pipelines: dict[str, Any]) -> dict[str, Any]:
        """Run AI pipelines through the broker; keeps spend_usd equal to the ledger."""
        self._ensure_ai()
        # while a tail is replayed (no db attached yet) stored replies are read from replay_db
        self._broker.db = self.db if self.db is not None else self.replay_db
        self._broker.replay = self.replaying
        try:
            return self._broker.run(pipelines)
        finally:
            self.spend_usd = self._ledger.total_usd

    @property
    def spend_warning(self) -> bool:
        """True once the spend has reached the warning share of the pinned cap."""
        share = self.config.run.spend_warning_share
        return self.spend_usd >= share * self.config.run.spend_cap_usd

    def _decide_many(self, contexts: list[DecisionContext]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        pipelines: dict[str, Any] = {}
        for ctx in contexts:
            ctrl = self.controllers.get(ctx.player_id)
            if ctrl is None:
                out[ctx.player_id] = None
            elif hasattr(ctrl, "pipeline"):
                pipelines[ctx.player_id] = ctrl.pipeline(ctx)
            else:
                out[ctx.player_id] = ctrl.decide(ctx)
        if pipelines:
            out.update(self._broker_run(pipelines))
        return out

    @property
    def week_ticks(self) -> int:
        clock = self.config.world.clock
        return clock.ticks_per_day * clock.days_per_week

    def _reflect(self, pre: bool) -> None:
        """Weekly reflection for living AI seats at a week-end tick (after the whole tick)."""
        tick = self.world.tick
        if tick <= 0 or tick % self.week_ticks:
            return
        if pre and self.reflect_tick == tick:
            return  # already attempted after this tick (a failed one waits for next week)
        if not pre and self.defer_reflection is not None and self.defer_reflection():
            return  # a pause was asked for: the reflection runs before the next tick
        week = tick // self.week_ticks
        pipelines = {
            pid: ctrl.reflect_pipeline(week, tick)
            for pid, ctrl in self.ai_controllers().items()
            if ctrl.reflection_due(week)
        }
        self.reflect_tick = tick
        if pipelines:
            self._broker_run(pipelines)

    def _ai_step(self) -> None:
        """One tick of a mixed run, with after_tick, reflection and the record commit."""
        if self.broken:
            raise SimulationBroken("the run stopped mid-tick; continue it with recover()")
        if self.judge_pending:
            self.drain_judge()  # a RunPaused here leaves the (complete) tick and the sim intact
        mark = len(self.world.events)
        try:
            self._reflect(pre=True)
            advance_to(self.world, self.world.tick + 1)
            for ctrl in self.ai_controllers().values():
                ctrl.after_tick(self.world, self.world.tick)
            self._reflect(pre=False)
        except RunPaused:
            del self.world.events[mark:]  # the partial tick leaves no event at all
            self.broken = True
            raise
        self._commit_ai()

    def _commit_ai(self) -> None:
        """After a complete tick: drain the controllers' records and write them with the events."""
        records: list[Any] = []
        for ctrl in self.ai_controllers().values():
            records.extend(ctrl.drain_records())
        if self.db is None:
            self.records.extend(records)
            return
        self.flush()
        self._write_records(records)
        self.drain_judge()

    def drain_judge(self) -> None:
        """Run the blind judge's owed work (labels, revisions, summaries, profiles) for this tick.

        Only with a database attached, never while replaying, only for runs with AI seats. A
        RunPaused (spending limit, no connection, sleep) propagates; ``judge_pending`` then stays
        True and the same work is retried first thing after the next resume or attach.
        """
        if self.db is None or self.replaying or not self.mixed:
            return
        if self._judge is None:
            from ai_island.measure.judge import JudgeService

            self._judge = JudgeService()
        self.judge_pending = True
        self._judge.drain(self)
        self.judge_pending = False

    def _write_records(self, records: list[Any]) -> None:
        """Store choice points, outcomes, insights and value rows (all safe to repeat)."""
        assert self.db is not None
        batch: list[ValueHistoryRow] = []
        for rec in records:
            if isinstance(rec, ValueHistoryRow):
                batch.append(rec)
                continue
            if batch:
                self.db.insert_value_history(batch)
                batch = []
            if isinstance(rec, ChoicePointRecord):
                self.db.insert_choice_point(rec)
            elif isinstance(rec, ChoiceOutcome):
                self.db.update_choice_outcome(rec.decision_key, rec.outcome)
            elif isinstance(rec, ChoiceInsight):
                self.db.update_choice_insight(rec.decision_key, rec.insight)
        if batch:
            self.db.insert_value_history(batch)

    @classmethod
    def from_snapshot(
        cls,
        snapshot: Snapshot,
        config: GameConfig | None = None,
        assets: AssetsConfig | None = None,
    ) -> Simulation:
        """Restore a saved island. Without ``config`` the snapshot's pinned config is used."""
        if snapshot.schema_version != SNAPSHOT_VERSION:
            raise SnapshotError(
                f"snapshot version {snapshot.schema_version} is not supported; "
                f"this program needs version {SNAPSHOT_VERSION}. Create a new run with 'new'."
            )
        digest = hashlib.sha256(snapshot.config_json.encode("utf-8")).hexdigest()
        if digest != snapshot.config_hash:
            raise SnapshotError("snapshot config does not match its hash")
        if config is None:
            config = GameConfig.from_pinned(snapshot.config_json, assets)
        state = json.loads(snapshot.state_json)
        streams = Streams.from_state(json.loads(snapshot.rng_json))
        world = World.from_state(config, streams, state["world"])
        controllers: dict[str, Any] = {}
        if world.controller_kind != "none":
            from ai_island.minds import make_controllers

            controllers = make_controllers(world.controller_kind, world)
            for pid, ctrl_state in state.get("controllers", {}).items():
                try:
                    controllers[pid].from_state(ctrl_state)
                except (ValueError, KeyError) as exc:
                    if not hasattr(controllers[pid], "pipeline"):
                        raise
                    raise SnapshotError(f"cannot restore {pid}: {exc}") from exc
        sim = cls(config, int(state["seed"]), streams, world, controllers)
        sim.reflect_tick = int(state.get("ai", {}).get("reflect_tick", -1))
        sim.spend_usd = float(snapshot.spend_usd)
        sim.last_autosave_tick = snapshot.tick
        return sim

    # ----------------------------------------------------------------------------- state

    @property
    def events(self) -> list[Event]:
        """Events emitted since this object was created or restored (oldest first)."""
        return self.world.events

    @property
    def clock(self) -> Clock:
        return Clock.at(self.world.tick, self.config.world.clock)

    def snapshot(self) -> Snapshot:
        """The complete state at the current tick. Adds no event."""
        body: dict[str, Any] = {
            "schema": SNAPSHOT_VERSION,
            "seed": self.seed,
            "world": self.world.to_state(),
            "controllers": {pid: c.to_state() for pid, c in sorted(self.controllers.items())},
        }
        if self.mixed:  # additive: rule-based snapshots are unchanged
            body["ai"] = {"reflect_tick": self.reflect_tick}
        state = json.dumps(body, sort_keys=True, separators=(",", ":"))
        config_json = self.config.pinned_json()
        return Snapshot(
            tick=self.world.tick,
            last_event_id=None,
            schema_version=SNAPSHOT_VERSION,
            config_json=config_json,
            config_hash=hashlib.sha256(config_json.encode("utf-8")).hexdigest(),
            state_json=state,
            rng_json=json.dumps(self.streams.state(), sort_keys=True, separators=(",", ":")),
            spend_usd=self.spend_usd,
        )

    # ------------------------------------------------------------------------ persistence

    def attach(self, db: RunDB, already_stored: bool = False) -> None:
        """Send events to ``db``. ``already_stored`` skips events emitted so far."""
        self.db = db
        self._flushed = len(self.world.events) if already_stored else 0
        db.reconcile_spend()  # a paid call without its spend row is repaired before the ledger
        self.spend_usd = db.spend_total()  # the ledger is the truth, never snapshot plus ledger
        self._ai_ready = False  # the broker, ledger and embedder cache are rebuilt for this db
        self._judge = None  # a new database: the judge reloads its finished keys
        self.judge_pending = self.mixed  # catch up on anything the judge still owes
        if self.records:  # choice records of a replayed tail: store them (repeats are skipped)
            self._write_records(self.records)
            self.records = []

    @property
    def pending_events(self) -> int:
        """Events emitted but not yet written to the database."""
        return len(self.world.events) - self._flushed

    def flush(self) -> None:
        """Write the pending whole ticks' events to the database (no snapshot)."""
        if self.db is not None and len(self.world.events) > self._flushed:
            self.db.append_events(self.world.events[self._flushed :])
            self._flushed = len(self.world.events)

    _flush = flush

    def save(self) -> None:
        """Write pending events and a snapshot of the current tick in one transaction."""
        if self.db is None:
            raise RuntimeError("no database attached")
        if self.broken:
            raise SimulationBroken("the run stopped mid-tick; it cannot be saved, use recover()")
        self.db.save_checkpoint(self.world.events[self._flushed :], self.snapshot())
        self._flushed = len(self.world.events)
        self.last_autosave_tick = self.world.tick

    def _next_stop(self, end: int, step: int) -> int:
        """The tick a chunk of at most ``step`` ticks must end on (autosave and crash ticks)."""
        stop = min(end, self.world.tick + step)
        if self.db is not None:
            every = self.config.run.autosave_interval
            stop = min(stop, (self.world.tick // every + 1) * every)
        crash = self.crash_after_tick
        if crash is not None and self.world.tick < crash:
            stop = min(stop, crash)
        return stop

    def _after_chunk(self) -> None:
        """Autosave on positive multiples of autosave_interval; the crash hook."""
        tick = self.world.tick
        if self.db is not None and tick > 0 and tick % self.config.run.autosave_interval == 0:
            if self.last_autosave_tick != tick:
                self.save()
        if self.crash_after_tick is not None and tick >= self.crash_after_tick:
            self.flush()
            os._exit(3)

    # -------------------------------------------------------------------------- the loop

    def run(self, ticks: int, pace_seconds: float | None = None) -> None:
        """Advance the world by ``ticks`` game minutes.

        Unpaced (default): as fast as possible. With ``pace_seconds``, one tick takes about
        that many real seconds.
        """
        if ticks < 0:
            raise ValueError("ticks must not be negative")
        batch = self.config.run.event_batch
        end = self.world.tick + ticks
        planned_end = self.config.run.ai.end_tick
        if planned_end is not None:
            end = min(end, max(planned_end, self.world.tick))  # never step past the planned end
        if self.mixed:  # AI runs advance one tick per step and flush after every tick
            next_time = time.monotonic()
            while self.world.tick < end:
                self._ai_step()
                self._after_chunk()
                if pace_seconds is not None:
                    next_time += pace_seconds
                    delay = next_time - time.monotonic()
                    if delay > 0:
                        time.sleep(delay)
            return
        if pace_seconds is None:
            # advance in chunks so events reach the database in bounded batches
            chunk = self.config.world.clock.ticks_per_day
            while self.world.tick < end:
                advance_to(self.world, self._next_stop(end, chunk))
                self._after_chunk()
                if len(self.world.events) - self._flushed >= batch:
                    self._flush()
            return
        next_time = time.monotonic()
        while self.world.tick < end:
            advance_to(self.world, self.world.tick + 1)
            self._after_chunk()
            next_time += pace_seconds
            delay = next_time - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            if len(self.world.events) - self._flushed >= batch:
                self._flush()

    def step(self) -> None:
        """Advance exactly one tick (nothing at the planned end tick)."""
        planned_end = self.config.run.ai.end_tick
        if planned_end is not None and self.world.tick >= planned_end:
            return
        if self.mixed:
            self._ai_step()
            return
        advance_to(self.world, self.world.tick + 1)

    def format_time(self) -> str:
        """``Year Y, <Season>, week W, day D, HH:MM`` for the current tick."""
        return self.clock.format()
