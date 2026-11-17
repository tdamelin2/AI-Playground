"""The balance report: did a full dummy game year hit the AC-29 targets?

Reads the run database only (``player_day`` and ``villager_left`` events). A target with too
little data says "insufficient data" instead of a vacuous pass.
"""

from __future__ import annotations

import json
import sqlite3
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# The AC-29 targets (see handoffs/phase-2.md).
WEEK1_MEDIAN_RANGE = (60.0, 80.0)  # 60 <= median < 80
FOOD_SHORT_DAYS = (8, 21)  # the first food-short day falls in week 2 or 3
WINTER_MEAN_LIMIT = 40.0  # mean X in weeks 7-8 below this for players without food stores
SEVERAL_DAYS = 3  # game days of hunger or hard work before any departure
DAYS_PER_WEEK = 7
WINTER_FIRST_DAY = 6 * DAYS_PER_WEEK + 1  # week 7 starts on day 43
LAST_DAY = 8 * DAYS_PER_WEEK
NON_LOYALTY_REASONS = ("poach", "captur", "taken")

PASS = "PASS"
FAIL = "FAIL"
NODATA = "insufficient data"


@dataclass
class Check:
    name: str
    verdict: str
    detail: str


@dataclass
class BalanceReport:
    lines: list[str] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)

    def text(self) -> str:
        out = list(self.lines)
        out.append("")
        out.append("AC-29 targets")
        for c in self.checks:
            out.append(f"  [{c.verdict}] {c.name}: {c.detail}")
        return "\n".join(out)

    @property
    def passed(self) -> bool:
        return all(c.verdict == PASS for c in self.checks)


def load_rows(db_path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """player_day and villager_left payloads (with their tick) straight from the database."""
    uri = f"file:{Path(db_path).as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        days: list[dict[str, Any]] = []
        left: list[dict[str, Any]] = []
        rows = conn.execute(
            "SELECT tick, type, payload_json FROM events "
            "WHERE type IN ('player_day', 'villager_left') ORDER BY id"
        )
        for tick, kind, payload in rows:
            data = json.loads(payload)
            data["tick"] = tick
            (days if kind == "player_day" else left).append(data)
    finally:
        conn.close()
    return days, left


def _median(values: list[float]) -> float:
    return float(statistics.median(values))


def _week(day: int) -> int:
    return (day - 1) // DAYS_PER_WEEK + 1


def build_balance_report(days: list[dict[str, Any]], left: list[dict[str, Any]]) -> BalanceReport:
    """Turn the event rows into the printed report and the PASS/FAIL list."""
    rep = BalanceReport()
    players = sorted({d["player"] for d in days})
    by_player: dict[str, dict[int, dict[str, Any]]] = {p: {} for p in players}
    for d in days:
        by_player[d["player"]][int(d["day"])] = d
    covered = max((int(d["day"]) for d in days), default=0)
    rep.lines.append(
        f"Player days recorded: {len(days)} ({len(players)} players, up to day {covered})"
    )

    # -- week 1 median X ------------------------------------------------------------------
    rep.lines.append("")
    rep.lines.append("Week 1 median X (hourly samples, days 1-7)")
    medians: dict[str, float] = {}
    pooled: list[float] = []
    for p in players:
        samples = [
            float(v)
            for day, d in by_player[p].items()
            if day <= DAYS_PER_WEEK
            for v in d["x_hourly"]
        ]
        if samples:
            medians[p] = _median(samples)
            pooled.extend(samples)
            rep.lines.append(f"  {p}: {medians[p]:.1f}")
    lo, hi = WEEK1_MEDIAN_RANGE
    if pooled and covered >= DAYS_PER_WEEK:
        overall = _median(pooled)
        rep.lines.append(f"  overall: {overall:.1f}")
        ok = lo <= overall < hi and all(lo <= m < hi for m in medians.values())
        rep.checks.append(
            Check(
                "week-1 median X 60-79",
                PASS if ok else FAIL,
                f"overall {overall:.1f}, players "
                + ", ".join(f"{p} {m:.1f}" for p, m in sorted(medians.items())),
            )
        )
    else:
        rep.lines.append("  no data")
        rep.checks.append(Check("week-1 median X 60-79", NODATA, "week 1 not finished"))

    # -- first food-short day -------------------------------------------------------------
    rep.lines.append("")
    rep.lines.append("First food-short day per home (home food below the household's daily need)")
    first_short: dict[str, int | None] = {}
    for p in players:
        first_short[p] = next(
            (
                day
                for day, d in sorted(by_player[p].items())
                if float(d["home_food_units"]) < float(d["household_need"])
            ),
            None,
        )
        if first_short[p] is None:
            rep.lines.append(f"  {p}: never (within {covered} days)")
        else:
            day = first_short[p]
            assert day is not None
            rep.lines.append(f"  {p}: day {day} (week {_week(day)})")
    short_lo, short_hi = FOOD_SHORT_DAYS
    if players and covered >= short_hi:
        bad = [p for p, d in first_short.items() if d is None or not short_lo <= d <= short_hi]
        rep.checks.append(
            Check(
                "food first runs short in week 2 or 3",
                FAIL if bad else PASS,
                "all homes in days 8-21" if not bad else "outside days 8-21: " + ", ".join(bad),
            )
        )
    else:
        rep.checks.append(Check("food first runs short in week 2 or 3", NODATA, "under 21 days"))

    # -- winter ---------------------------------------------------------------------------
    rep.lines.append("")
    rep.lines.append("Winter (weeks 7-8): mean X and food stores at the start of week 7")
    cohort: list[float] = []
    for p in players:
        rows = [d for day, d in by_player[p].items() if WINTER_FIRST_DAY <= day <= LAST_DAY]
        start = by_player[p].get(WINTER_FIRST_DAY - 1) or by_player[p].get(WINTER_FIRST_DAY)
        if not rows or start is None:
            rep.lines.append(f"  {p}: no data")
            continue
        mean = float(statistics.fmean(float(d["x_mean"]) for d in rows))
        stores = float(start["food_stored"]) >= float(start["household_need"])
        rep.lines.append(f"  {p}: mean X {mean:.1f}, food stores {'yes' if stores else 'no'}")
        if not stores:
            cohort.append(mean)
    if cohort:
        cohort_mean = float(statistics.fmean(cohort))
        rep.checks.append(
            Check(
                "players without food stores have mean X below 40 in weeks 7-8",
                PASS if cohort_mean < WINTER_MEAN_LIMIT else FAIL,
                f"{len(cohort)} players, mean {cohort_mean:.1f}",
            )
        )
    else:
        rep.checks.append(
            Check(
                "players without food stores have mean X below 40 in weeks 7-8",
                NODATA,
                "no player without stores with winter data",
            )
        )

    # -- villager departures ----------------------------------------------------------------
    rep.lines.append("")
    rep.lines.append("Villager departures")
    leavers = [
        v for v in left if not any(r in str(v.get("reason", "")) for r in NON_LOYALTY_REASONS)
    ]
    if leavers:
        first = min(leavers, key=lambda v: v["tick"])
        rep.lines.append(
            f"  earliest: {first['villager']} left {first.get('leader')} at tick {first['tick']} "
            f"(hungry_days {first.get('hungry_days')}, hard_days {first.get('hard_days')})"
        )
        early = [
            v
            for v in leavers
            if max(int(v.get("hungry_days", 0)), int(v.get("hard_days", 0))) < SEVERAL_DAYS
        ]
        rep.checks.append(
            Check(
                "no villager leaves before at least 3 days of hunger or hard work",
                FAIL if early else PASS,
                f"{len(leavers)} left; "
                + (f"{len(early)} left too early" if early else "all after 3+ days"),
            )
        )
    else:
        rep.lines.append("  none left")
        rep.checks.append(
            Check(
                "no villager leaves before at least 3 days of hunger or hard work",
                NODATA,
                "no villager left, nothing to check",
            )
        )
    return rep


def run_report(db_path: Path) -> BalanceReport:
    days, left = load_rows(db_path)
    return build_balance_report(days, left)
