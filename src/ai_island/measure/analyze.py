"""The ``analyze`` command: a read-only report on a finished run, plus CSV files.

Everything is read from the run database with the run's own pinned config. Nothing is changed,
so the same database always gives the same report.
"""

from __future__ import annotations

import csv
import json
import statistics
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ai_island.config import GameConfig
from ai_island.measure.weekly import game_week, ok_labels, value_rows
from ai_island.storage.db import DatabaseError, RunDB

TRIGGERS = ("finished", "spoken_to", "interrupt", "check")
TIERS = ("reflex", "fast", "slow", "hooked")
_TYPES = (
    "died",
    "villager_died",
    "player_day",
    "local_extinction",
    "decision_made",
)
CSV_FILES = (
    "deaths",
    "x_over_time",
    "resources",
    "decisions_per_day",
    "failures",
    "cost_by_week",
    "tuning_proposals",
    "value_changes",
    "judge_summaries",
)
PROPOSAL_COLUMNS = (
    "area",
    "key",
    "current",
    "proposed",
    "metric",
    "measured",
    "target_min",
    "target_max",
    "samples",
    "evidence",
    "related",
)


def game_day(tick: int, ticks_per_day: int) -> int:
    """The game day of ``tick`` (end-of-day events belong to the day just ended)."""
    return max(0, tick - 1) // ticks_per_day + 1


@dataclass
class AnalysisReport:
    run: str = ""
    ticks_per_day: int = 1440
    days_per_week: int = 7
    last_tick: int = 0
    days_covered: int = 0  # complete game days
    players: list[str] = field(default_factory=list)
    # deaths
    player_deaths: int = 0
    player_deaths_by_cause: dict[str, int] = field(default_factory=dict)
    villager_deaths: int = 0
    villager_deaths_by_cause: dict[str, int] = field(default_factory=dict)
    death_rows: list[dict[str, Any]] = field(default_factory=list)
    # wellbeing
    x_by_player_day: dict[str, dict[int, float]] = field(default_factory=dict)
    x_week_mean: dict[str, dict[int, float]] = field(default_factory=dict)
    week1_median_x: float | None = None
    mean_villager_loyalty: float | None = None
    loyalty_samples: int = 0
    # food
    resource_rows: list[dict[str, Any]] = field(default_factory=list)
    first_food_short_day: dict[str, int | None] = field(default_factory=dict)
    first_food_short_text: dict[str, str] = field(default_factory=dict)
    food_short_days: dict[str, int] = field(default_factory=dict)
    earliest_food_short_day: int | None = None
    extinction_events: int = 0
    extinction_rows: list[dict[str, Any]] = field(default_factory=list)
    # decisions: per player per complete game day
    decisions_per_day_by_trigger: dict[str, float | None] = field(default_factory=dict)
    decisions_per_day_by_tier: dict[str, float | None] = field(default_factory=dict)
    per_player_by_trigger: dict[str, dict[str, float | None]] = field(default_factory=dict)
    per_player_by_tier: dict[str, dict[str, float | None]] = field(default_factory=dict)
    decision_day_rows: list[dict[str, Any]] = field(default_factory=list)
    main_decisions_per_player_day: float | None = None
    player_in_sight_share: float | None = None
    main_choice_points: int = 0
    # failures
    attempts_by_role: dict[str, dict[str, int]] = field(default_factory=dict)
    refusal_attempts: int = 0
    schema_failure_attempts: int = 0
    refusal_decisions: int = 0
    schema_failure_decisions: int = 0
    judge_failed_labels: int = 0
    # cost
    cost_by_week: list[tuple[int, float]] = field(default_factory=list)
    total_cost: float = 0.0
    # judge and values
    value_change_rows: list[dict[str, Any]] = field(default_factory=list)
    judge_summary_rows: list[dict[str, Any]] = field(default_factory=list)
    judge_labels: int = 0
    proposals: list[Any] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def text(self) -> str:
        return render_markdown(self)


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _rate_means(per_player: dict[str, dict[str, float | None]], keys: tuple[str, ...]) -> dict:
    out: dict[str, float | None] = {}
    for key in keys:
        found = [v[key] for v in per_player.values() if v.get(key) is not None]
        out[key] = _mean([float(x) for x in found])
    return out


def _pinned_config(db: RunDB) -> GameConfig:
    snapshot = db.latest_snapshot()
    if snapshot is None:
        raise DatabaseError(f"{db.path} has no snapshot, so its settings are unknown")
    return GameConfig.from_pinned(snapshot.config_json, None)


def _summaries(db: RunDB) -> list[dict[str, Any]]:
    """Daily summaries and weekly profiles: tick, kind, period, player, text, flags."""
    reader = getattr(db, "judge_summaries", None)
    if reader is not None:
        return [
            {
                "tick": s.tick,
                "kind": s.kind,
                "period": s.period,
                "player": s.player_id or "",
                "text": s.text,
                "flags": json.dumps(s.flags, sort_keys=True),
            }
            for s in reader()
        ]
    found: dict[tuple, dict[str, Any]] = {}
    rows = db._conn.execute(
        "SELECT tick, reply_json, details_json FROM ai_calls "
        "WHERE role = 'judge' AND status = 'ok' ORDER BY id"
    ).fetchall()
    for tick, reply, details_json in rows:
        details = json.loads(details_json) if details_json else {}
        kind = details.get("judge_kind")
        if kind not in ("daily_summary", "weekly_profile") or reply is None:
            continue
        try:
            data = json.loads(json.loads(reply))
        except (ValueError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        period = details.get("period")
        who = details.get("subject_id") or ""
        found[(kind, period, who)] = {
            "tick": tick,
            "kind": kind,
            "period": period,
            "player": who,
            "text": str(data.get("summary", data.get("profile", ""))),
            "flags": json.dumps(data.get("flags", []), sort_keys=True),
        }
    return sorted(found.values(), key=lambda r: (r["tick"], r["kind"], r["player"]))


def build_report(db: RunDB, config: GameConfig, run: str = "") -> AnalysisReport:
    """All analysis numbers from an open database and the run's config."""
    tpd = config.world.clock.ticks_per_day
    dpw = config.world.clock.days_per_week
    week_ticks = tpd * dpw
    rep = AnalysisReport(run=run, ticks_per_day=tpd, days_per_week=dpw)
    rep.last_tick = db.last_event_tick() or 0
    rep.days_covered = rep.last_tick // tpd

    events = db.events_after(0, _TYPES)
    players: set[str] = set()
    player_deaths: Counter = Counter()
    villager_deaths: Counter = Counter()
    x_days: dict[str, dict[int, tuple[float, float]]] = defaultdict(dict)
    week1: list[float] = []
    loyalty: list[float] = []
    food: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
    # (player, day) -> Counter of trigger, tier
    by_trigger: dict[tuple[str, int], Counter] = defaultdict(Counter)
    by_tier: dict[tuple[str, int], Counter] = defaultdict(Counter)
    for _, event in events:
        p = event.payload
        t = event.type
        day = game_day(event.tick, tpd)
        if t == "died":
            players.add(p.player)
            player_deaths[p.cause] += 1
            rep.death_rows.append(
                {
                    "tick": event.tick,
                    "day": day,
                    "kind": "player",
                    "who": p.player,
                    "cause": p.cause,
                }
            )
        elif t == "villager_died":
            villager_deaths[p.cause] += 1
            rep.death_rows.append(
                {
                    "tick": event.tick,
                    "day": day,
                    "kind": "villager",
                    "who": p.villager,
                    "cause": p.cause,
                }
            )
        elif t == "player_day":
            players.add(p.player)
            x_days[p.player][int(p.day)] = (float(p.x_mean), float(p.x_median))
            if int(p.day) <= dpw:
                week1.extend(float(v) for v in p.x_hourly)
            if p.villager_loyalty is not None:
                loyalty.append(float(p.villager_loyalty))
            food[p.player][int(p.day)] = {
                "home_food_units": float(p.home_food_units),
                "household_need": float(p.household_need),
                "food_stored": float(p.food_stored),
                "villagers": int(p.villagers),
                "short": float(p.home_food_units) < float(p.household_need),
            }
        elif t == "local_extinction":
            rep.extinction_events += 1
            rep.extinction_rows.append(
                {"tick": event.tick, "day": day, "kind": p.kind, "zone": p.zone}
            )
        elif t == "decision_made":
            players.add(p.player)
            if day <= rep.days_covered:
                by_trigger[(p.player, day)][p.trigger] += 1
                by_tier[(p.player, day)][p.tier] += 1
            if p.failure == "format":
                rep.schema_failure_decisions += 1
            elif p.failure == "refusal":
                rep.refusal_decisions += 1
    rep.players = sorted(players)
    rep.player_deaths = sum(player_deaths.values())
    rep.player_deaths_by_cause = dict(sorted(player_deaths.items()))
    rep.villager_deaths = sum(villager_deaths.values())
    rep.villager_deaths_by_cause = dict(sorted(villager_deaths.items()))

    # -- X, loyalty, food ---------------------------------------------------------------
    for pid in rep.players:
        days = x_days.get(pid, {})
        rep.x_by_player_day[pid] = {d: v[0] for d, v in sorted(days.items())}
        weeks: dict[int, list[float]] = defaultdict(list)
        for d, (mean_x, _) in days.items():
            weeks[(d - 1) // dpw + 1].append(mean_x)
        rep.x_week_mean[pid] = {w: sum(v) / len(v) for w, v in sorted(weeks.items())}
        covered = max(food.get(pid, {}), default=0)
        short_days = [d for d, r in sorted(food.get(pid, {}).items()) if r["short"]]
        rep.food_short_days[pid] = len(short_days)
        rep.first_food_short_day[pid] = short_days[0] if short_days else None
        rep.first_food_short_text[pid] = (
            f"day {short_days[0]}" if short_days else f"not within {covered} days"
        )
        for d, r in sorted(food.get(pid, {}).items()):
            rep.resource_rows.append(
                {"player": pid, "day": d, "week": (d - 1) // dpw + 1, **r, "short": int(r["short"])}
            )
    found_days = [d for d in rep.first_food_short_day.values() if d is not None]
    rep.earliest_food_short_day = min(found_days) if found_days else None
    rep.week1_median_x = float(statistics.median(week1)) if week1 else None
    rep.mean_villager_loyalty = _mean(loyalty)
    rep.loyalty_samples = len(loyalty)

    # -- decisions per player per complete game day (zero cells included) -----------------
    days = rep.days_covered
    for pid in rep.players:
        trig_total: Counter = Counter()
        tier_total: Counter = Counter()
        for day in range(1, days + 1):
            for kind, keys, table in (
                ("trigger", TRIGGERS, by_trigger),
                ("tier", TIERS, by_tier),
            ):
                counter = table.get((pid, day), Counter())
                for key in keys:
                    n = counter.get(key, 0)
                    rep.decision_day_rows.append(
                        {"player": pid, "day": day, "group": kind, "key": key, "count": n}
                    )
                    (trig_total if kind == "trigger" else tier_total)[key] += n
        rep.per_player_by_trigger[pid] = {
            k: (trig_total[k] / days if days else None) for k in TRIGGERS
        }
        rep.per_player_by_tier[pid] = {k: (tier_total[k] / days if days else None) for k in TIERS}
    rep.decisions_per_day_by_trigger = _rate_means(rep.per_player_by_trigger, TRIGGERS)
    rep.decisions_per_day_by_tier = _rate_means(rep.per_player_by_tier, TIERS)
    mains = [
        (r["slow"] or 0.0) + (r["hooked"] or 0.0)
        for r in rep.per_player_by_tier.values()
        if r["slow"] is not None
    ]
    rep.main_decisions_per_player_day = _mean(mains)

    # -- main decisions with a player in sight (choice point interrupt kinds) --------------
    sight = total = 0
    for cp in db.choice_details():
        if cp.tier in ("slow", "hooked") and "interrupt_kinds" in cp.details:
            total += 1
            sight += "player_in_sight" in (cp.details.get("interrupt_kinds") or [])
    rep.main_choice_points = total
    rep.player_in_sight_share = sight / total if total else None

    # -- failures -----------------------------------------------------------------------
    attempts: dict[str, dict[str, int]] = defaultdict(dict)
    for role, status, n in db._conn.execute(
        "SELECT role, status, COUNT(*) FROM ai_calls GROUP BY role, status ORDER BY role, status"
    ):
        attempts[role][status] = int(n)
    rep.attempts_by_role = {k: dict(v) for k, v in attempts.items()}
    rep.refusal_attempts = sum(v.get("refusal", 0) for v in attempts.values())
    rep.schema_failure_attempts = sum(v.get("format_error", 0) for v in attempts.values())
    labels = ok_labels(db)
    all_labels = db._conn.execute("SELECT COUNT(DISTINCT choice_point_id) FROM judge_labels")
    rep.judge_labels = int(all_labels.fetchone()[0])
    rep.judge_failed_labels = max(0, rep.judge_labels - len(labels))

    # -- cost ---------------------------------------------------------------------------
    rep.cost_by_week = db.spend_by_week(week_ticks)
    rep.total_cost = db.spend_total()

    # -- values and judge summaries -----------------------------------------------------
    for v in value_rows(db):
        if v.week < 1 or v.old == v.new:
            continue
        items = v.details.get("cause_items") or []
        first = items[0] if items and isinstance(items[0], dict) else {}
        rep.value_change_rows.append(
            {
                "tick": v.tick,
                "week": game_week(v.tick, week_ticks),
                "player": v.player,
                "value_id": v.value_id,
                "old": "" if v.old is None else v.old,
                "new": v.new,
                "reflection_key": v.details.get("reflection_key") or "",
                "cause_kind": v.details.get("cause_kind") or "",
                "cause_memory_id": first.get("memory_id", ""),
                "cause_tick": first.get("tick", ""),
                "cause_text": first.get("text", ""),
            }
        )
    rep.judge_summary_rows = _summaries(db)
    return rep


def _fmt(value: float | None, digits: int = 2) -> str:
    return "none" if value is None else f"{value:.{digits}f}"


def render_markdown(rep: AnalysisReport) -> str:
    """The report as plain text (also written to analysis.md)."""
    out = [f"# Analysis of run {rep.run}".rstrip(), ""]
    out.append(
        f"Covers {rep.days_covered} complete game days (last tick {rep.last_tick}); "
        f"players: {', '.join(rep.players) or 'none'}."
    )
    out += ["", "## Deaths"]
    out.append(f"- Player deaths: {rep.player_deaths}")
    for cause, n in rep.player_deaths_by_cause.items():
        out.append(f"  - {cause}: {n}")
    out.append(f"- Villager deaths: {rep.villager_deaths}")
    for cause, n in rep.villager_deaths_by_cause.items():
        out.append(f"  - {cause}: {n}")
    out += ["", "## X over time (mean X per game day; weekly mean)"]
    for pid in rep.players:
        days = rep.x_by_player_day.get(pid, {})
        weeks = rep.x_week_mean.get(pid, {})
        out.append(
            f"- {pid}: {len(days)} days; weekly mean "
            + (", ".join(f"week {w} {m:.1f}" for w, m in weeks.items()) or "none")
        )
    out.append(f"- Week 1 median X (all players, hourly): {_fmt(rep.week1_median_x, 1)}")
    out.append(
        f"- Mean villager loyalty: {_fmt(rep.mean_villager_loyalty, 1)} "
        f"({rep.loyalty_samples} player-days)"
    )
    out += ["", "## Food and resources"]
    for pid in rep.players:
        out.append(
            f"- {pid}: first food-short day {rep.first_food_short_text.get(pid, 'none')}; "
            f"food-short days {rep.food_short_days.get(pid, 0)}"
        )
    out.append(f"- Local extinction events: {rep.extinction_events}")
    out += ["", "## Decisions per player per game day"]
    out.append("By trigger (finished = action finished, check = 2-hour check):")
    for key in TRIGGERS:
        out.append(f"- {key}: {_fmt(rep.decisions_per_day_by_trigger.get(key))}")
    out.append("By tier:")
    for key in TIERS:
        out.append(f"- {key}: {_fmt(rep.decisions_per_day_by_tier.get(key))}")
    out.append(f"- Main decisions (slow + hooked): {_fmt(rep.main_decisions_per_player_day)}")
    out += ["", "## Refusals and schema failures"]
    out.append(f"- Refused attempts: {rep.refusal_attempts}")
    out.append(f"- Schema-failure attempts: {rep.schema_failure_attempts}")
    out.append(f"- Decisions lost to a refusal: {rep.refusal_decisions}")
    out.append(f"- Decisions lost to a schema failure: {rep.schema_failure_decisions}")
    out.append(f"- Judge labels failed: {rep.judge_failed_labels} of {rep.judge_labels}")
    out += ["", "## Cost per game week (USD)"]
    for week, cost in rep.cost_by_week:
        out.append(f"- week {week}: {cost:.4f}")
    out.append(f"- total: {rep.total_cost:.4f}")
    out += ["", "## Values and judge"]
    out.append(f"- Value changes: {len(rep.value_change_rows)}")
    days = sum(1 for s in rep.judge_summary_rows if s["kind"] == "daily_summary")
    profiles = sum(1 for s in rep.judge_summary_rows if s["kind"] == "weekly_profile")
    out.append(f"- Daily summaries: {days}; weekly profiles: {profiles}")
    out += ["", "## Tuning proposals"]
    if not rep.proposals:
        out.append("- None: every measured number is on target or has too little data.")
    for p in rep.proposals:
        out.append(f"- {p.area}: change {p.key} from {p.current} to {p.proposed}. {p.evidence}")
        if p.related:
            rel = p.related
            out.append(
                f"  - together with: change {rel['key']} from {rel['current']} to {rel['proposed']}"
            )
    for note in rep.notes:
        out.append(f"- Note: {note}")
    return "\n".join(out) + "\n"


def _write_csv(path: Path, columns: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_outputs(rep: AnalysisReport, out_dir: Path) -> list[Path]:
    """analysis.md in ``out_dir`` and the CSV files in ``out_dir/analysis``."""
    out_dir = Path(out_dir)
    csv_dir = out_dir / "analysis"
    csv_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "analysis.md").write_text(rep.text(), encoding="utf-8")
    x_rows = [
        {
            "player": pid,
            "day": day,
            "week": (day - 1) // rep.days_per_week + 1,
            "x_mean": x,
            "week_mean": rep.x_week_mean[pid].get((day - 1) // rep.days_per_week + 1),
        }
        for pid in rep.players
        for day, x in rep.x_by_player_day.get(pid, {}).items()
    ]
    failure_rows = [
        {"role": role, "status": status, "attempts": n}
        for role, statuses in sorted(rep.attempts_by_role.items())
        for status, n in sorted(statuses.items())
    ] + [
        {"role": "decisions", "status": "refusal", "attempts": rep.refusal_decisions},
        {"role": "decisions", "status": "format_error", "attempts": rep.schema_failure_decisions},
        {"role": "judge_labels", "status": "failed", "attempts": rep.judge_failed_labels},
    ]
    proposal_rows = []
    for p in rep.proposals:
        data = asdict(p)
        data["related"] = json.dumps(data.get("related"), sort_keys=True) if p.related else ""
        proposal_rows.append(data)
    tables: dict[str, tuple[tuple[str, ...], list[dict[str, Any]]]] = {
        "deaths": (("tick", "day", "kind", "who", "cause"), rep.death_rows),
        "x_over_time": (("player", "day", "week", "x_mean", "week_mean"), x_rows),
        "resources": (
            (
                "player",
                "day",
                "week",
                "home_food_units",
                "household_need",
                "food_stored",
                "villagers",
                "short",
            ),
            rep.resource_rows,
        ),  # fmt: skip
        "decisions_per_day": (("player", "day", "group", "key", "count"), rep.decision_day_rows),
        "failures": (("role", "status", "attempts"), failure_rows),
        "cost_by_week": (
            ("week", "cost_usd"),
            [{"week": w, "cost_usd": c} for w, c in rep.cost_by_week],
        ),
        "tuning_proposals": (PROPOSAL_COLUMNS, proposal_rows),
        "value_changes": (
            (
                "tick",
                "week",
                "player",
                "value_id",
                "old",
                "new",
                "reflection_key",
                "cause_kind",
                "cause_memory_id",
                "cause_tick",
                "cause_text",
            ),
            rep.value_change_rows,
        ),  # fmt: skip
        "judge_summaries": (
            ("tick", "kind", "period", "player", "text", "flags"),
            rep.judge_summary_rows,
        ),
    }
    written = [out_dir / "analysis.md"]
    for name in CSV_FILES:
        columns, rows = tables[name]
        _write_csv(csv_dir / f"{name}.csv", columns, rows)
        written.append(csv_dir / f"{name}.csv")
    return written


def analyze_run(db_path: Path, out_dir: Path | None = None) -> AnalysisReport:
    """Analyse the run at ``db_path`` (read-only) and write analysis.md and the CSV files.

    ``out_dir`` defaults to the run's folder.
    """
    db_path = Path(db_path)
    db = RunDB.open_readonly(db_path)
    try:
        config = _pinned_config(db)
        rep = build_report(db, config, db_path.parent.name)
    finally:
        db.close()
    try:
        from ai_island.measure.tuning import propose_tuning
    except ImportError:
        rep.notes.append("tuning rules are not available in this build")
    else:
        rep.proposals = propose_tuning(rep, config)
    write_outputs(rep, Path(out_dir) if out_dir is not None else db_path.parent)
    return rep
