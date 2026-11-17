"""Command line: new, resume, headless, watch, view, report, measures and export."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from pathlib import Path

from ai_island.config import ConfigError, GameConfig, load_config, load_sim_config
from ai_island.llm.errors import LLMError, RealCallsBlocked
from ai_island.sim import Simulation, SnapshotError, ai_config, apply_profile
from ai_island.storage.db import DatabaseError, RunDB
from ai_island.storage.recovery import RecoveryError
from ai_island.storage.run_control import MemoryControls
from ai_island.storage.runlock import RunBusyError, RunLock

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
_RUN_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_MAX_FRAME_SECONDS = 1.0  # a laptop sleep or a stall never makes a catch-up burst
PLAYER_KINDS = ("dummy", "scripted", "none")
PAUSED_EXIT = 4  # a run that stopped because of money, network or sleep
FROZEN_NOTE = "Stored AI run: shown, not advanced"
END_MESSAGE = "This run has reached its planned end."


class CliError(Exception):
    """A user-facing command line error."""


def _run_db_path(config: GameConfig, run: str) -> Path:
    if not _RUN_NAME.match(run):
        raise CliError(f"'{run}' is not a valid run name (use letters, digits, - and _)")
    return ROOT / config.run.runs_dir / run / "run.db"


def _week_ticks(config: GameConfig) -> int:
    clock = config.world.clock
    return clock.ticks_per_day * clock.days_per_week


def _restore(db: RunDB, path: Path, seed: int | None, config: GameConfig) -> Simulation:
    """The run's simulation, recovered from its newest snapshot and the stored event tail."""
    from ai_island.storage.recovery import recover

    if db.latest_snapshot() is None:
        raise CliError(f"{path} has no snapshot")
    sim, info = recover(db, config.assets)
    if info.tail_events:
        print(
            f"Recovered run: snapshot at tick {info.snapshot_tick}, "
            f"{info.tail_events} stored events verified, now at tick {info.end_tick}."
        )
    if seed is not None and seed != sim.seed:
        db.close()
        raise CliError(f"the run was created with seed {sim.seed}; --seed {seed} conflicts")
    return sim


def _with_players(config: GameConfig, kind: str | None) -> GameConfig:
    """``config`` with the controller kind replaced by ``--players`` (unchanged if not given)."""
    if kind is None:
        return config
    players = config.run.players.model_copy(update={"controller": kind})
    return config.model_copy(update={"run": config.run.model_copy(update={"players": players})})


def _check_players(sim: Simulation, kind: str | None) -> None:
    """A saved run keeps the controller kind it was created with."""
    saved = getattr(sim.config.run.players, "controller", None)
    if kind is not None and saved is not None and kind != saved:
        raise CliError(f"the run uses players '{saved}'; --players {kind} conflicts")


def _create(
    config: GameConfig, path: Path, seed: int, players: str | None = None
) -> tuple[Simulation, RunDB]:
    sim = Simulation.new(config, seed, players)
    db = RunDB.create(path)
    sim.attach(db)
    sim.save()
    return sim, db


class Declined(CliError):
    """Tim did not type yes: nothing was spent."""


def _check_ai_flags(args: argparse.Namespace) -> int:
    """The number of AI seats asked for; refuses a bad combination before anything is made."""
    seats = int(args.ai_seats or 0)
    profile = getattr(args, "profile", None)
    backend = getattr(args, "backend", None)
    if profile is not None:
        if seats or args.cheap or args.players is not None:
            raise CliError("--profile cannot be combined with --ai-seats, --cheap or --players")
    elif seats == 0:
        if backend is not None:
            raise CliError("--backend needs --ai-seats or --profile")
        return 0
    dollars = args.max_dollars
    if dollars is None or not math.isfinite(dollars) or dollars <= 0:
        raise CliError("an AI run needs --max-dollars (a number above 0)")
    if profile is None and args.players not in (None, "dummy"):
        raise CliError(f"--ai-seats works only with --players dummy, not '{args.players}'")
    return seats


def _with_ai(
    config: GameConfig,
    seats: int,
    cheap: bool,
    max_dollars: float,
    backend: str | None = None,
) -> GameConfig:
    """`config` with seats 1..seats on the AI, the cheap flag and the pinned money limit."""
    return ai_config(
        config,
        list(range(1, seats + 1)),
        cheap,
        max_dollars,
        backend or config.run.ai.backend,
    )


def _dollars(amount: float) -> str:
    return f"${amount:g}"


def banner_text(backend: str, dollars: float) -> str:
    """The one-line reminder of whether this run uses real AI and real money."""
    if backend == "live":
        return f"LIVE: real AI, may spend up to {_dollars(dollars)}"
    return "PRACTICE: pretend AI, $0"


def confirm_spend(dollars: float, what: str) -> None:
    """Read one line from stdin; go on only when it is "yes" (EOF or anything else declines)."""
    print(f"This will {what} and may spend up to {_dollars(dollars)}. Type yes to go on: ", end="")
    sys.stdout.flush()
    try:
        answer = sys.stdin.readline()
    except (OSError, ValueError, EOFError):
        answer = ""
    if answer.strip().lower() != "yes":
        print()
        raise Declined("Nothing was spent.")


def _live_gate(config: GameConfig, what: str, show_practice: bool = True) -> None:
    """Banner, then (for a live run) the Ollama check and the typed yes."""
    ai = config.run.ai
    dollars = float(config.run.spend_cap_usd)
    if ai.backend != "live":
        if show_practice:
            print(banner_text("fake", dollars))
        return
    from ai_island.llm import factory

    print(banner_text("live", dollars))
    problem = factory.check_ollama(config.models.embedding.model)
    if problem:
        raise CliError(problem)
    confirm_spend(dollars, what)


def _paused_message(run: str, exc: BaseException) -> str:
    reasons = {
        "spend_cap": "the spending limit was reached",
        "network": "there is no internet connection",
        "sleep": "the laptop went to sleep",
        "provider_error": "an AI company rejected a request (see the message above)",
    }
    reason = getattr(exc, "reason", "")
    return (
        f"Run paused: {reasons.get(reason, reason)}. "
        f"Continue with: uv run python main.py resume {run}"
    )


def _cmd_new(args: argparse.Namespace) -> int:
    seats = _check_ai_flags(args)
    config = _with_players(load_sim_config(CONFIG_DIR), args.players)
    profile = getattr(args, "profile", None)
    backend = getattr(args, "backend", None)
    if profile is not None:
        config = apply_profile(config, profile, float(args.max_dollars), backend or "live")
    elif seats:
        config = _with_ai(config, seats, bool(args.cheap), float(args.max_dollars), backend)
    ai_run = bool(profile or seats)
    path = _run_db_path(config, args.run)
    if path.exists():
        raise CliError(f"run '{args.run}' already exists at {path}")
    if ai_run:
        _live_gate(config, "start this run")
    seed = config.run.seed if args.seed is None else args.seed
    sim, db = _create(config, path, seed, "mixed" if ai_run else None)
    if not ai_run:
        db.close()
        print(f"Created run '{args.run}' with seed {seed}: {path}")
        return 0
    from ai_island.llm.errors import RunPaused

    ticks = config.run.ai.new_ticks if args.ticks is None else args.ticks
    print(f"Created run '{args.run}' with seed {seed}: {path}")
    try:
        sim.run(ticks)
        sim.save()
    except RunPaused as exc:
        db.close()
        print(_paused_message(args.run, exc))
        return PAUSED_EXIT
    db.close()
    print(sim.format_time())
    _print_end(sim)
    return 0


def _print_end(sim: Simulation) -> None:
    end = sim.config.run.ai.end_tick
    if end is not None and sim.world.tick >= end:
        print(END_MESSAGE)


def _cmd_decisions(args: argparse.Namespace) -> int:
    from ai_island.measure.decisions import format_decisions

    config = load_sim_config(CONFIG_DIR)
    path = _existing_run_path(config, args.run)
    pid = None
    if args.player is not None:
        pid = f"player_{args.player}"
    names = dict(
        zip(
            (f"player_{n}" for n in range(1, 5)),
            config.balance.turn.player_dummy_names,
            strict=False,
        )
    )
    db = RunDB.open_readonly(path)
    try:
        text = format_decisions(db.decision_events(pid), db.choice_details(pid), names)
    finally:
        db.close()
    print(text if text else "No decisions recorded.")
    return 0


def _print_scenario(sim: Simulation) -> None:
    """After a scripted run, list the action kinds it started and the stages it finished."""
    if sim.world.controller_kind != "scripted":
        return
    from ai_island.minds.scripted import scenario_summary

    for line in scenario_summary(sim.controllers, sim.world):
        print(line)


def _run_guarded(sim: Simulation, db: RunDB, run: str, ticks: int) -> bool:
    """Run and save; False (after printing how to continue) when an AI run paused itself."""
    from ai_island.llm.errors import RunPaused

    try:
        sim.run(ticks)
        sim.save()
    except RunPaused as exc:
        db.close()
        print(_paused_message(run, exc))
        return False
    db.close()
    return True


def _cmd_headless(args: argparse.Namespace) -> int:
    config = _with_players(load_sim_config(CONFIG_DIR), args.players)
    seed = config.run.seed if args.seed is None else args.seed
    if args.run is None:
        sim = Simulation.new(config, seed)
        sim.run(args.ticks)
        print(sim.format_time())
        return 0
    path = _run_db_path(config, args.run)
    with RunLock(path):
        if path.exists():
            db = RunDB.open(path)
            sim = _restore(db, path, args.seed, config)
            _check_players(sim, args.players)
            _gate_stored(sim, db, "continue this run", show_practice=False)
        else:
            sim, db = _create(config, path, seed)
        sim.crash_after_tick = args.crash_after_tick
        if not _run_guarded(sim, db, args.run, args.ticks):
            return PAUSED_EXIT
    _print_scenario(sim)
    print(sim.format_time())
    return 0


def _cmd_resume(args: argparse.Namespace) -> int:
    config = load_sim_config(CONFIG_DIR)
    path = _run_db_path(config, args.run)
    if not path.is_file():
        raise CliError(f"run '{args.run}' does not exist (looked for {path})")
    with RunLock(path):
        db = RunDB.open(path)
        sim = _restore(db, path, None, config)
        _check_players(sim, args.players)
        end = sim.config.run.ai.end_tick
        if end is not None and sim.world.tick >= end:
            db.close()
            print(END_MESSAGE)
            return 0
        _gate_stored(sim, db, "continue this run")
        sim.crash_after_tick = args.crash_after_tick
        ticks = sim.config.run.resume_ticks if args.ticks is None else args.ticks
        if end is not None:
            ticks = min(ticks, end - sim.world.tick)
        if not _run_guarded(sim, db, args.run, ticks):
            return PAUSED_EXIT
    print(sim.format_time())
    _print_end(sim)
    return 0


def _gate_stored(sim: Simulation, db: RunDB, what: str, show_practice: bool = True) -> None:
    """The banner and typed yes for a stored run with AI seats (the db is closed if declined)."""
    if not sim.config.run.ai.seats:
        return
    try:
        _live_gate(sim.config, what, show_practice)
    except BaseException:
        db.close()
        raise


def _existing_run_path(config: GameConfig, run: str) -> Path:
    path = _run_db_path(config, run)
    if not path.is_file():
        raise CliError(f"run '{run}' does not exist (looked for {path})")
    return path


def _cmd_report(args: argparse.Namespace) -> int:
    from ai_island.measure.report import run_report

    config = load_sim_config(CONFIG_DIR)
    print(run_report(_existing_run_path(config, args.run)).text())
    return 0


def _cmd_measures(args: argparse.Namespace) -> int:
    from ai_island.measure.weekly import format_table, weekly_measures

    config = load_sim_config(CONFIG_DIR)
    path = _existing_run_path(config, args.run)
    db = RunDB.open_readonly(path)
    try:
        rows = weekly_measures(db, _week_ticks(config))
    finally:
        db.close()
    print(format_table(rows))
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    from ai_island.measure.export import export_run

    config = load_sim_config(CONFIG_DIR)
    path = _existing_run_path(config, args.run)
    out = Path(args.out) if args.out else path.parent / "export"
    counts = export_run(path, out, _week_ticks(config))
    for name, rows in counts.items():
        print(f"{out / name}: {rows} rows")
    return 0


def _prefs_path(config: GameConfig) -> Path:
    return ROOT / config.run.runs_dir / "observer_prefs.json"


def _cmd_guide(args: argparse.Namespace) -> int:
    from ai_island.guide import render_guide

    out = Path(args.out) if args.out else ROOT / "docs" / "guide.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_guide(ROOT), encoding="utf-8", newline="\n")
    print(out)
    return 0


def _gate_watch(path: Path) -> None:
    """Banner and typed yes before a window opens on a stored run with AI seats."""
    if not path.is_file():
        return  # LiveRun.open gives the "run does not exist" message
    from ai_island.measure.analyze import _pinned_config

    db = RunDB.open_readonly(path)
    try:
        pinned = _pinned_config(db)
    finally:
        db.close()
    if pinned.run.ai.seats:
        _live_gate(pinned, "watch and continue this run")


def _cmd_analyze(args: argparse.Namespace) -> int:
    from ai_island.measure.analyze import analyze_run

    config = load_sim_config(CONFIG_DIR)
    path = _existing_run_path(config, args.run)
    report = analyze_run(path)
    print(report.text())
    print(f"Wrote {path.parent / 'analysis.md'} and the CSV files in {path.parent / 'analysis'}")
    return 0


def _cmd_launch_check(args: argparse.Namespace) -> int:
    from ai_island.measure.launch_check import run_launch_check

    if args.root is None:
        return run_launch_check(ROOT, CONFIG_DIR)
    root = Path(args.root)
    return run_launch_check(root, root / "config")


def _tool_dollars(args: argparse.Namespace) -> float:
    dollars = args.max_dollars
    if dollars is None or not math.isfinite(dollars) or dollars <= 0:
        raise CliError("this command needs --max-dollars (a number above 0)")
    return float(dollars)


def _live_adapters(config: GameConfig, providers: list[str]) -> dict:
    """Real adapters for ``providers`` (refused while the offline switch is on)."""
    from ai_island.llm import factory

    timeout = config.run.ai.call_timeout_seconds
    return {p: factory.make_adapter(p, timeout) for p in dict.fromkeys(providers)}


def _cmd_judge_check(args: argparse.Namespace) -> int:
    from ai_island.measure.judge_check import run_judge_check, stop_text

    dollars = _tool_dollars(args)
    config = load_sim_config(CONFIG_DIR)
    out_dir = ROOT / config.run.runs_dir / "judge-check"
    adapters = None
    if args.dry_run:
        print(banner_text("fake", dollars))
    else:
        print(banner_text("live", dollars))
        confirm_spend(dollars, "run the judge check")
        adapters = _live_adapters(config, [config.models.roles["judge"].provider])
    result = run_judge_check(config, adapters, dollars, out_dir, dry_run=args.dry_run)
    print(f"Report: {result.report_path}")
    if result.stopped:
        print(stop_text(result.stop_reason, result.stop_detail, f"{dollars:g}"))
        return PAUSED_EXIT
    return 0


def _cmd_calibrate(args: argparse.Namespace) -> int:
    from ai_island.measure.calibrate import CalibrationError, apply_calibration, run_calibration
    from ai_island.measure.judge_check import stop_text

    if args.dry_run and args.apply:
        raise CliError("--apply needs a real calibration; it cannot be combined with --dry-run")
    dollars = _tool_dollars(args)
    config = load_sim_config(CONFIG_DIR)
    out_dir = ROOT / config.run.runs_dir / "calibration"
    adapters = None
    if args.dry_run:
        print(banner_text("fake", dollars))
    else:
        print(banner_text("live", dollars))
        confirm_spend(dollars, "measure the AI models")
        adapters = _live_adapters(config, [r.provider for r in config.models.roles.values()])
    report = run_calibration(config, adapters, dollars, out_dir, dry_run=args.dry_run)
    print(report.text())
    print(f"Report: {report.report_path}")
    if report.stopped:
        print(stop_text(report.stop_reason, report.stop_detail, f"{dollars:g}"))
        return PAUSED_EXIT
    if args.apply:
        try:
            apply_calibration(CONFIG_DIR / "models.toml", report)
        except CalibrationError as exc:
            print(f"Not applied: {exc}")
            return 1
        print(f"Updated {CONFIG_DIR / 'models.toml'}")
    return 0


def _cmd_watch(args: argparse.Namespace) -> int:
    from ai_island.observer import Observer
    from ai_island.storage.run_control import LiveRun
    from ai_island.world.view import frame_from_world

    config = load_config(CONFIG_DIR)
    path = _run_db_path(config, args.run)
    assert config.assets is not None
    _gate_watch(path)
    live = LiveRun.open(config, path, crash_after_tick=args.crash_after_tick)
    view = config.run.view
    observer = None
    try:
        if live.recovery.tail_events:
            print(
                f"Recovered run: snapshot at tick {live.recovery.snapshot_tick}, "
                f"{live.recovery.tail_events} stored events verified, "
                f"now at tick {live.recovery.end_tick}."
            )
        observer = Observer(
            config.assets,
            view,
            ROOT,
            live.db,
            live,
            spend_warning_share=config.run.spend_warning_share,
            week_ticks=_week_ticks(config),
            run_name=args.run,
            prefs_path=_prefs_path(config),
            screenshot_dir=path.parent / "screenshots",
        )
        live.wait_hook = getattr(observer, "waiting_frame", None)
        last = time.monotonic()
        frame_seconds = 1.0 / view.fps
        while observer.pump():
            started = time.monotonic()
            live.advance(min(started - last, _MAX_FRAME_SECONDS))
            last = started
            live.flush()
            observer.draw(frame_from_world(live.sim), live.sub_tick)
            time.sleep(max(0.0, frame_seconds - (time.monotonic() - started)))
    finally:
        if observer is not None:
            observer.close()
        live.close()
    return 0


def _preview_sim(args: argparse.Namespace, config: GameConfig) -> tuple[Simulation, RunDB]:
    """The island to show on an in-memory database: the run's copy or a fresh seeded world."""
    seed = config.run.seed if args.seed is None else args.seed
    if args.run is None:
        sim = Simulation.new(config, seed)
        db = RunDB.memory()
        sim.attach(db)
        sim.save()
        return sim, db
    path = _existing_run_path(config, args.run)
    db = RunDB.copy_to_memory(path)
    try:
        sim = _restore(db, path, args.seed, config)
    except BaseException:
        db.close()
        raise
    return sim, db


def _advance_preview(sim: Simulation, controls, view, real_seconds: float, owed: float) -> float:
    """Run the preview ticks owed for ``real_seconds`` (within the work budget); new debt."""
    if controls.paused:
        return 0.0
    owed += max(0.0, real_seconds) * controls.speed / view.seconds_per_tick
    budget = view.max_tick_work_ms / 1000.0
    started = time.perf_counter()
    while owed >= 1.0:
        sim.run(1)
        owed -= 1.0
        if time.perf_counter() - started >= budget:
            break
    return owed


class _FrozenControls(MemoryControls):
    """``view`` of a run with AI seats: the stored state is shown and never advanced."""

    def __init__(self, config) -> None:
        super().__init__(config)
        self.paused = True
        self.pause_reason = FROZEN_NOTE

    def toggle_pause(self) -> None:
        return None


def _cmd_view(args: argparse.Namespace) -> int:
    from ai_island.observer import Observer
    from ai_island.world.view import frame_from_world

    if args.screenshot is not None and args.ticks is None:
        raise CliError("--screenshot needs --ticks")
    if args.ticks is not None and args.screenshot is None:
        raise CliError("--ticks for view needs --screenshot")
    config = load_config(CONFIG_DIR)
    sim, db = _preview_sim(args, config)
    view = config.run.view
    assert config.assets is not None
    frozen = bool(sim.config.run.ai.seats)
    controls = _FrozenControls(config.run) if frozen else MemoryControls(config.run)
    observer = None
    try:
        observer = Observer(
            config.assets,
            view,
            ROOT,
            db,
            controls,
            spend_warning_share=config.run.spend_warning_share,
            week_ticks=_week_ticks(config),
            run_name=args.run,
            prefs_path=_prefs_path(config),
            screenshot_dir=(
                ROOT / config.run.runs_dir / args.run / "screenshots"
                if args.run is not None
                else None
            ),
        )

        def sync() -> None:
            controls.spend_usd = sim.spend_usd
            controls.last_autosave_tick = sim.last_autosave_tick

        if args.screenshot is not None:
            if not frozen:
                sim.run(args.ticks)
            sim.flush()
            sync()
            observer.pump()
            observer.draw(frame_from_world(sim), 0.0)
            observer.save_png(Path(args.screenshot))
            return 0
        last = time.monotonic()
        owed = 0.0
        frame_seconds = 1.0 / view.fps
        while observer.pump():
            started = time.monotonic()
            owed = _advance_preview(
                sim, controls, view, min(started - last, _MAX_FRAME_SECONDS), owed
            )
            last = started
            sim.flush()
            sync()
            observer.draw(frame_from_world(sim), min(owed, 0.999999))
            time.sleep(max(0.0, frame_seconds - (time.monotonic() - started)))
    finally:
        if observer is not None:
            observer.close()
        db.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="main.py", description="AI Island")
    sub = parser.add_subparsers(dest="command", required=True)

    p_new = sub.add_parser("new", help="create a new run")
    p_new.add_argument("run")
    p_new.add_argument("--seed", type=int)
    p_new.add_argument("--players", choices=PLAYER_KINDS)
    p_new.add_argument("--ai-seats", type=int, choices=range(0, 5), metavar="N")
    p_new.add_argument("--cheap", action="store_true")
    p_new.add_argument(
        "--profile",
        choices=("pilot", "launch"),
        help="a ready-made AI setup: pilot (cheap AIs, 3 game weeks) or launch (the real run)",
    )
    p_new.add_argument(
        "--backend",
        choices=("fake", "live"),
        help="live = real AI that costs money; fake = pretend AI. Profiles default to live",
    )
    p_new.add_argument("--max-dollars", type=float)
    p_new.add_argument("--ticks", type=int)
    p_new.set_defaults(func=_cmd_new)

    p_head = sub.add_parser("headless", help="run without a window")
    p_head.add_argument("--ticks", type=int, required=True)
    p_head.add_argument("--run")
    p_head.add_argument("--seed", type=int)
    p_head.add_argument("--players", choices=PLAYER_KINDS)
    p_head.add_argument("--crash-after-tick", type=int, help=argparse.SUPPRESS)
    p_head.set_defaults(func=_cmd_headless)

    p_resume = sub.add_parser("resume", help="continue a saved run without a window")
    p_resume.add_argument("run")
    p_resume.add_argument("--ticks", type=int)
    p_resume.add_argument("--players", choices=PLAYER_KINDS)
    p_resume.add_argument("--crash-after-tick", type=int, help=argparse.SUPPRESS)
    p_resume.set_defaults(func=_cmd_resume)

    p_report = sub.add_parser("report", help="print the balance report of a run")
    p_report.add_argument("--run", required=True)
    p_report.set_defaults(func=_cmd_report)

    p_measures = sub.add_parser("measures", help="print the weekly measures of a run")
    p_measures.add_argument("--run", required=True)
    p_measures.set_defaults(func=_cmd_measures)

    p_export = sub.add_parser("export", help="write every table of a run as CSV files")
    p_export.add_argument("--run", required=True)
    p_export.add_argument("--out")
    p_export.set_defaults(func=_cmd_export)

    p_watch = sub.add_parser("watch", help="watch a saved run in a window (saves as it goes)")
    p_watch.add_argument("--run", required=True)
    p_watch.add_argument("--crash-after-tick", type=int, help=argparse.SUPPRESS)
    p_watch.set_defaults(func=_cmd_watch)

    p_view = sub.add_parser("view", help="preview the island in a window (nothing is saved)")
    p_view.add_argument("--run")
    p_view.add_argument("--seed", type=int)
    p_view.add_argument("--ticks", type=int)
    p_view.add_argument("--screenshot")
    p_view.set_defaults(func=_cmd_view)

    p_dec = sub.add_parser("decisions", help="print every decision of a run, one block each")
    p_dec.add_argument("--run", required=True)
    p_dec.add_argument("--player", type=int, choices=range(1, 5), metavar="N")
    p_dec.set_defaults(func=_cmd_decisions)

    p_analyze = sub.add_parser(
        "analyze", help="report on a finished run, CSV files and suggested setting changes"
    )
    p_analyze.add_argument("--run", required=True)
    p_analyze.set_defaults(func=_cmd_analyze)

    p_launch = sub.add_parser(
        "launch-check", help="final safety check before the real run (changes nothing)"
    )
    p_launch.add_argument("--root", help=argparse.SUPPRESS)
    p_launch.set_defaults(func=_cmd_launch_check)

    p_check = sub.add_parser(
        "judge-check",
        help="Tim only (spends money): try the blind judge on a few sample choices",
    )
    p_check.add_argument("--max-dollars", type=float, help="the most it may spend (needed)")
    p_check.add_argument("--dry-run", action="store_true", help="pretend AI, no money")
    p_check.set_defaults(func=_cmd_judge_check)

    p_cal = sub.add_parser(
        "calibrate",
        help="Tim only (spends money): measure the AI models' cost and match their thinking",
    )
    p_cal.add_argument("--max-dollars", type=float, help="the most it may spend (needed)")
    p_cal.add_argument("--dry-run", action="store_true", help="pretend AI, no money")
    p_cal.add_argument(
        "--apply", action="store_true", help="after a good real run, save the result in models.toml"
    )
    p_cal.set_defaults(func=_cmd_calibrate)

    p_guide = sub.add_parser("guide", help="write the player guide (docs/guide.md)")
    p_guide.add_argument("--out")
    p_guide.set_defaults(func=_cmd_guide)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "ticks", None) is not None and args.ticks < 0:
        parser.error("--ticks must not be negative")
    try:
        return int(args.func(args))
    except Declined as exc:
        print(str(exc))
        return 2
    except (
        CliError,
        RealCallsBlocked,
        ConfigError,
        DatabaseError,
        SnapshotError,
        RecoveryError,
        RunBusyError,
        json.JSONDecodeError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except LLMError as exc:
        print(f"error: the AI call failed: {exc}", file=sys.stderr)
        return 2
