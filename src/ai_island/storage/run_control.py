"""Run control: the small surface the observer may use to steer a run.

The observer calls only ``toggle_pause``, ``set_speed`` and (while waiting for AI replies)
``request_close``, and reads the listed attributes.
"""

from __future__ import annotations

import atexit
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, runtime_checkable

from ai_island.config import AssetsConfig, GameConfig, RunConfig
from ai_island.llm.errors import RunPaused
from ai_island.sim import Simulation
from ai_island.storage.db import DatabaseError, RunDB
from ai_island.storage.power import KeepAwake
from ai_island.storage.recovery import RecoveryInfo, recover
from ai_island.storage.runlock import RunLock

EXIT_PAUSED = 4  # headless/resume exit code when an AI run paused itself

PAUSE_TEXT = {
    "spend_cap": "Paused: spending limit reached",
    "network": "Paused: no internet connection",
    "sleep": "Paused: the laptop slept",
    "provider_error": "Paused: an AI company rejected a request (see the message above)",
}


def paused_notice(run: str, exc: RunPaused) -> str:
    """The one line headless/resume print when an AI run pauses itself."""
    return f"Run paused: {exc.reason}. Continue with: uv run python main.py resume {run}"


def exit_paused(run: str, exc: RunPaused) -> int:
    """Print the pause notice and return the exit code (4) for headless/resume to return."""
    print(paused_notice(run, exc))
    return EXIT_PAUSED


@runtime_checkable
class Controls(Protocol):
    paused: bool
    speed: float
    last_autosave_tick: int | None
    preview: bool  # True for view (in-memory preview, nothing is saved)
    spend_usd: float
    spend_cap_usd: float

    def toggle_pause(self) -> None: ...

    def set_speed(self, speed: float) -> None: ...


def clamp_speed(config: RunConfig, speed: float) -> float:
    """``speed`` limited to [view.speed / 8, view.max_speed]."""
    view = config.view
    return min(view.max_speed, max(view.speed / 8, float(speed)))


class LiveRun:
    """A persisted run being watched: owns the lock, the database, the simulation and the clock.

    The frame loop is: pump -> advance(dt) -> flush -> draw -> sleep the rest of the frame.

    With AI seats a tick can wait for replies. During that wait ``wait_hook`` (set by the
    caller, normally ``observer.waiting_frame``) keeps the window alive; P or closing the
    window then only sets ``pending_pause`` / ``pending_close``: the tick (and a reflection
    already started) finishes, one snapshot is saved and the run is paused. When the broker
    stops the run (spending limit, no internet, laptop slept) the run pauses itself with a
    ``pause_reason``; resuming it re-opens the run through ``recover()``.
    """

    def __init__(
        self,
        config: GameConfig,
        sim: Simulation,
        db: RunDB,
        lock: RunLock,
        recovery: RecoveryInfo,
        keep_awake: KeepAwake,
        setup: Callable[[Simulation], None] | None = None,
    ) -> None:
        self._config = config.run
        self._assets: AssetsConfig | None = config.assets
        self._user_setup = setup
        self.sim = sim
        self.db = db
        self.recovery = recovery
        self._lock = lock
        self._keep_awake = keep_awake
        self.paused = False
        self.pause_reason: str | None = None
        self.pending_pause = False
        self.pending_close = False
        self.wait_hook: Callable[[], None] | None = None
        self.speed = float(self._config.view.speed)
        self.preview = False
        self._owed = 0.0
        self._closed = False
        self._busy = False
        self._wire(sim)
        atexit.register(self.close)

    @classmethod
    def open(
        cls,
        config: GameConfig,
        path: Path,
        keep_awake: KeepAwake | None = None,
        crash_after_tick: int | None = None,
        setup: Callable[[Simulation], None] | None = None,
    ) -> LiveRun:
        path = Path(path)
        if not path.is_file():
            name = path.parent.name
            raise DatabaseError(
                f"run '{name}' does not exist; create it with: "
                f"uv run python main.py new {name} --players dummy"
            )
        lock = RunLock(path)
        db: RunDB | None = None
        try:
            db = RunDB.open(path)
            sim, info = recover(db, config.assets, setup)
            sim.crash_after_tick = crash_after_tick
            awake = keep_awake if keep_awake is not None else KeepAwake()
            awake.acquire()
            return cls(config, sim, db, lock, info, awake, setup)
        except BaseException:
            if db is not None:
                db.close()
            lock.release()
            raise

    def _wire(self, sim: Simulation) -> None:
        sim.wait_hook = self._on_wait
        sim.defer_reflection = lambda: self.pending_pause or self.pending_close

    def _on_wait(self) -> None:
        if self.wait_hook is not None:
            self.wait_hook()

    # ----------------------------------------------------------------------- read-only state

    @property
    def last_autosave_tick(self) -> int | None:
        return self.sim.last_autosave_tick

    @property
    def spend_usd(self) -> float:
        return self.sim.spend_usd

    @property
    def spend_cap_usd(self) -> float:
        """The run's pinned limit (``new --max-dollars``), not today's run.toml."""
        return float(self.sim.config.run.spend_cap_usd)

    @property
    def sub_tick(self) -> float:
        """How far into the next game minute the clock is (0..1), for smooth drawing."""
        return 0.0 if self.paused else min(max(self._owed, 0.0), 0.999999)

    @property
    def waiting(self) -> bool:
        """True while a tick is running (it may be waiting for AI replies)."""
        return self._busy

    # -------------------------------------------------------------------------------- ticks

    def _run(self, n: int) -> bool:
        """Run ``n`` ticks; False when the run paused itself. Applies a pending pause/close."""
        waits = self.sim.waits
        self._busy = True
        try:
            self.sim.run(n)
        except RunPaused as exc:
            self._auto_pause(exc)
            return False
        finally:
            self._busy = False
            if self.sim.waits != waits:
                self._owed = 0.0  # time spent waiting never turns into catch-up ticks
        self._apply_pending()
        return True

    def advance(self, real_seconds: float) -> int:
        """Run the ticks owed for ``real_seconds`` of watching; returns how many were run.

        Ticks run one by one until the debt is paid or ``max_tick_work_ms`` is used up; the
        unpaid debt is kept for the next call. Returns 0 while paused.
        """
        if self.paused or self._closed:
            return 0
        self._owed += max(0.0, real_seconds) * self.speed / self._config.view.seconds_per_tick
        budget = self._config.view.max_tick_work_ms / 1000.0
        started = time.perf_counter()
        done = 0
        while self._owed >= 1.0:
            if not self._run(1):
                break
            self._owed = max(0.0, self._owed - 1.0)
            done += 1
            if self.paused or time.perf_counter() - started >= budget:
                break
        return done

    def run_ticks(self, n: int) -> None:
        """Run exactly ``n`` ticks now (no time budget). Raises RunPaused if the AI stops it."""
        self._busy = True
        try:
            self.sim.run(n)
        finally:
            self._busy = False
        self._apply_pending()

    def flush(self) -> None:
        """Write the pending whole ticks' events to the database."""
        if not self.sim.broken:
            self.sim.flush()

    # ------------------------------------------------------------------------------ control

    def _apply_pending(self) -> None:
        if self.pending_pause or self.pending_close:
            self.pending_pause = False
            self.pause()

    def _auto_pause(self, exc: RunPaused) -> None:
        """The broker stopped the run: pause, say why, release keep-awake; no snapshot (the
        interrupted tick was discarded; resume rebuilds it through recover())."""
        self.pending_pause = False
        self.paused = True
        self.pause_reason = PAUSE_TEXT.get(exc.reason, f"Paused: {exc.reason}")
        self._owed = 0.0
        self._keep_awake.release()

    def pause(self) -> None:
        if self.paused:
            return
        self.paused = True
        self._save()
        self._keep_awake.release()

    def resume(self) -> None:
        if not self.paused:
            return
        if self.sim.broken:
            self._reopen()
        if self.sim.judge_pending:  # the judge's owed work goes first, before any new tick
            self._busy = True
            try:
                self.sim.drain_judge()
            except RunPaused as exc:
                self._auto_pause(exc)
                return
            finally:
                self._busy = False
        self.paused = False
        self.pause_reason = None
        self._owed = 0.0  # paused or asleep time makes no catch-up ticks
        self._keep_awake.acquire()

    def _reopen(self) -> None:
        """Rebuild the simulation from the last snapshot and the stored replies."""
        old = self.sim

        def setup(sim: Simulation) -> None:
            if self._user_setup is not None:
                self._user_setup(sim)
            sim.adapters = old.adapters
            sim.ai_sleep = old.ai_sleep
            sim.ai_wall = old.ai_wall
            sim.crash_after_tick = old.crash_after_tick

        sim, info = recover(self.db, self._assets, setup)
        self._wire(sim)
        self.sim = sim
        self.recovery = info

    def toggle_pause(self) -> None:
        if self._busy:  # mid-tick (waiting for replies): finish the tick first
            self.pending_pause = not self.pending_pause
        elif self.paused:
            self.resume()
        else:
            self.pause()

    def request_close(self) -> None:
        """The window was closed while a tick was running: finish it, save, then stop."""
        if self._busy:
            self.pending_close = True

    def set_speed(self, speed: float) -> None:
        self.speed = clamp_speed(self._config, speed)

    def _save(self) -> None:
        if self.sim.broken:
            return  # a half-run tick is never saved
        if self.sim.last_autosave_tick == self.sim.world.tick and not self.sim.pending_events:
            return  # a checkpoint of this very tick already exists
        self.sim.save()

    def close(self) -> None:
        """Checkpoint at the current tick, release keep-awake, unlock, close the database."""
        if self._busy:
            self.pending_close = True  # not in the middle of a tick
            return
        if self._closed:
            return
        self._closed = True
        atexit.unregister(self.close)
        try:
            self._save()
        finally:
            self._keep_awake.release()
            self.db.close()
            self._lock.release()


class MemoryControls:
    """Controls for ``view``: pause stops only the in-memory preview."""

    def __init__(self, config: RunConfig) -> None:
        self._config = config
        self.paused = False
        self.speed = float(config.view.speed)
        self.last_autosave_tick: int | None = None
        self.preview = True
        self.spend_usd = 0.0
        self.spend_cap_usd = float(config.spend_cap_usd)

    def toggle_pause(self) -> None:
        self.paused = not self.paused

    def set_speed(self, speed: float) -> None:
        self.speed = clamp_speed(self._config, speed)
