"""Tuning proposals: suggested settings changes from an analysis report.

The rules live in ``balance.toml [analysis.*]``. This module only reads them and the report; it
never edits a config file. A rule makes no proposal when its number is on target (inclusive),
missing, or measured over fewer game days than the rule needs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ai_island.config import AnalysisRule, GameConfig
from ai_island.measure.analyze import AnalysisReport

SIGHT_SHARE_LIMIT = 0.30  # player_in_sight must be behind this share of main decisions
UNCLEAR_NOTE = "too many main decisions, cause unclear"
SIGHT_KIND = "player_in_sight"

_LABELS = {
    "first_food_short_day": "first food-short day",
    "week1_median_x": "week 1 median X",
    "mean_loyalty": "mean villager loyalty",
    "checks_per_player_per_day": "checks per player per day",
    "main_decisions_per_player_per_day": "main decisions per player per day",
}


@dataclass
class TuningProposal:
    area: str
    key: str
    current: Any
    proposed: Any
    metric: str
    measured: float
    target_min: float
    target_max: float
    samples: int
    evidence: str
    related: dict[str, Any] | None = None


def _measured(rep: AnalysisReport, rule: AnalysisRule) -> float | None:
    """The report number a rule watches (None when the run has no such number)."""
    metric = rule.metric
    if metric == "first_food_short_day":
        return rep.earliest_food_short_day
    if metric == "week1_median_x":
        return rep.week1_median_x
    if metric == "mean_loyalty":
        return rep.mean_villager_loyalty
    if metric == "checks_per_player_per_day":
        return rep.decisions_per_day_by_trigger.get("check")
    if metric == "main_decisions_per_player_per_day":
        return rep.main_decisions_per_player_day
    return None


def _shift(current: Any, delta: float) -> Any:
    """``current`` moved by ``delta``; whole numbers stay whole."""
    moved = current + delta
    if isinstance(current, int) and not isinstance(current, bool) and float(delta).is_integer():
        return int(moved)
    return round(float(moved), 6)


def _number(value: float) -> str:
    return f"{round(value, 2):g}"


def _evidence(rule: AnalysisRule, measured: float, high: bool) -> str:
    label = _LABELS.get(rule.metric, rule.metric)
    if high:
        return f"{_number(measured)} {label} > {_number(rule.target_max)}"
    return f"{_number(measured)} {label} < {_number(rule.target_min)}"


def _slow_proposal(
    rule: AnalysisRule, rep: AnalysisReport, config: GameConfig, measured: float
) -> TuningProposal:
    current = list(config.resolve_key(rule.key))
    evidence = _evidence(rule, measured, True)
    share = rep.player_in_sight_share
    proposed: Any = list(current)
    if share is not None and share >= SIGHT_SHARE_LIMIT and SIGHT_KIND in current:
        proposed = [kind for kind in current if kind != SIGHT_KIND]
        evidence += f"; {SIGHT_KIND} is behind {_number(share * 100)} % of main decisions"
    else:
        evidence += f"; {UNCLEAR_NOTE}"
    return TuningProposal(
        rule.area,
        rule.key,
        current,
        proposed,
        rule.metric,
        measured,
        rule.target_min,
        rule.target_max,
        rep.days_covered,
        evidence,
    )


def propose_tuning(report: AnalysisReport, config: GameConfig) -> list[TuningProposal]:
    """One proposal per rule whose number is off target and measured over enough game days."""
    out: list[TuningProposal] = []
    for rule in config.balance.analysis.values():
        measured = _measured(report, rule)
        if measured is None or report.days_covered < rule.min_days:
            continue
        if rule.target_min <= measured <= rule.target_max:
            continue
        high = measured > rule.target_max
        if rule.below == "remove":
            if high:
                out.append(_slow_proposal(rule, report, config, measured))
            continue
        # `below` is the direction to move when the number is under target; over target reverses it
        up = (rule.below == "increase") != high
        sign = 1.0 if up else -1.0
        current = config.resolve_key(rule.key)
        proposed = _shift(current, sign * rule.step)
        related = None
        if rule.related_key:
            rel_current = config.resolve_key(rule.related_key)
            related = {
                "key": rule.related_key,
                "current": rel_current,
                "proposed": _shift(rel_current, sign * rule.related_step),
            }
        out.append(
            TuningProposal(
                rule.area,
                rule.key,
                current,
                proposed,
                rule.metric,
                measured,
                rule.target_min,
                rule.target_max,
                report.days_covered,
                _evidence(rule, measured, high),
                related,
            )
        )
    return out
