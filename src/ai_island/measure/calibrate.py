"""calibrate: measure what a decision costs and match the four main models' thinking effort (C9).

Fixed sample situations (``minds.samples``) are sent to every role through one broker and one
money ledger, on a database of its own under ``runs/calibration/<session>/calls.db``. The thinking
search moves the highest or lowest main model one ladder step at a time until the median thinking
tokens are within ``max_median_ratio``. The cost model turns the measured unit costs into the cost
of a game week, of the real run and of the cheap pilot. A practice run (``dry_run``) uses a
pretend AI priced at the real prices with made-up thinking counts and measures nothing.
"""

from __future__ import annotations

import dataclasses
import json
import math
import os
import statistics
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from ai_island.config import GameConfig, ModelsConfig, RoleConfig
from ai_island.llm.broker import CallBroker
from ai_island.llm.errors import RunPaused
from ai_island.llm.fake import FakeAdapter
from ai_island.llm.ledger import SpendLedger
from ai_island.llm.types import LLMRequest, RawReply
from ai_island.measure.judge_check import (
    live_backend,
    new_session_dir,
    one,
    stop_text,
)
from ai_island.measure.judge_schemas import FullJudgeLabel, ShortJudgeLabel, bind_schema
from ai_island.minds.values import VALUE_IDS
from ai_island.storage.db import RunDB

PRACTICE_TITLE = "Practice estimate (pretend AI), not measured costs"
PLAYERS = (1, 2, 3, 4)
MAIN_ROLES = tuple(f"player_{n}_main" for n in PLAYERS)
_CHUNK = 4  # calls in flight at once (each one reserves its worst case against the limit)

# Dry run: made-up thinking tokens, a base per provider times 0.5 / 1 / 2 for low / medium / high.
_DRY_BASE = {"anthropic": 300, "openai": 330, "google": 360, "xai": 660}
_DRY_FACTOR = {"low": 0.5, "medium": 1.0, "high": 2.0}


class CalibrationError(ValueError):
    """The calibration cannot be applied (or its result is not usable)."""


# ----------------------------------------------------------------------------- pretend AI


class DryRunAdapter(FakeAdapter):
    """The pretend AI for a practice run: billed at real prices, with synthetic thinking counts
    on the main models that follow their ladder setting."""

    def __init__(self, config: GameConfig) -> None:
        super().__init__(bill=True)
        self._ladders = config.models.calibration.ladders

    def generate(self, request: LLMRequest, role: RoleConfig) -> RawReply:
        reply = super().generate(request, role)
        ladder = self._ladders.get(role.provider)
        if ladder is None or not request.role.endswith("_main"):
            return reply
        factor = _DRY_FACTOR.get(role.thinking.get(ladder.key, "medium"), 1.0)
        thinking = int(_DRY_BASE.get(role.provider, 300) * factor)
        usage = dataclasses.replace(
            reply.usage,
            output_tokens=reply.usage.output_tokens + thinking,
            thinking_tokens=thinking,
        )
        return dataclasses.replace(reply, usage=usage)


# ----------------------------------------------------------------------------- cost maths


def seat_week_cost(
    slow: float,
    hooked: float,
    fast: float,
    main_slow: float,
    cal: Any,
    days_per_week: int = 7,
) -> float:
    """One seat for one game week: days x (slow, hooked and fast decisions) + one reflection."""
    per_day = cal.slow_per_day * slow + cal.hooked_per_day * hooked + cal.fast_per_day * fast
    return days_per_week * per_day + cal.reflection_cost_factor * main_slow


def judge_week_cost(
    judge_label: float, cal: Any, days_per_week: int = 7, players: int = 4
) -> float:
    """The judge for one game week: every decision labelled, plus the summaries and profiles."""
    labelled = cal.slow_per_day + cal.hooked_per_day + cal.flagged_fast_per_day
    labels = days_per_week * players * labelled * judge_label
    summaries = (days_per_week + players) * cal.summary_cost_factor * judge_label
    return labels + summaries


def median_ratio(medians: Sequence[float | None]) -> float | None:
    """highest / lowest median, or None when one is missing or not above zero."""
    if not medians or any(m is None or m <= 0 for m in medians):
        return None
    return max(medians) / min(medians)  # type: ignore[type-var]


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


# ----------------------------------------------------------------------------- the report


@dataclass
class CalibrationReport:
    dry_run: bool
    complete: bool = False
    stopped: bool = False
    stop_reason: str = "spend_cap"
    stop_detail: str = ""
    matched: bool = False
    max_dollars: float = 0.0
    spent_usd: float = 0.0
    versions: dict[str, str] = field(default_factory=dict)
    settings: dict[str, dict[str, str]] = field(default_factory=dict)
    thinking_tokens_by_model: dict[str, float | None] = field(default_factory=dict)
    median_ratio: float | None = None
    rounds: list[dict[str, Any]] = field(default_factory=list)
    cost_per_slow_decision: float = 0.0
    cost_per_hooked_decision: float = 0.0
    cost_per_slow_by_role: dict[str, float] = field(default_factory=dict)
    cost_per_hooked_by_role: dict[str, float] = field(default_factory=dict)
    cost_per_game_week: float = 0.0
    weeks_per_100: float | None = None
    reaches_week_7: bool = False
    cheap_seat_week_costs: dict[str, float] = field(default_factory=dict)
    cheap_seat_week_cost: float = 0.0
    pilot_cost: float = 0.0
    warnings: list[str] = field(default_factory=list)
    form_checked: list[str] = field(default_factory=list)
    form_refused: list[dict[str, str]] = field(default_factory=list)
    sample_version: int = 0
    report_path: Path | None = None
    db_path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        data = dataclasses.asdict(self)
        data["report_path"] = str(self.report_path) if self.report_path else None
        data["db_path"] = str(self.db_path) if self.db_path else None
        return data

    def _form_lines(self) -> list[str]:
        if not self.form_checked and not self.form_refused:
            return []
        total = len(self.form_checked)
        lines = ["## Form check", ""]
        if not self.form_refused:
            lines += [f"Form check: all {total} models accepted.", ""]
            return lines
        lines.append(
            f"Form check: {len(self.form_refused)} of {total} models refused their reply form. "
            "Nothing else was measured."
        )
        lines.append("")
        for item in self.form_refused:
            lines.append(f"- {item['provider']} / {item['model']}: {item['message']}")
            lines.append(
                f"  Fix: in config/models.toml under [llm.output_mode] set: "
                f'{item["provider"]} = "prompt", then run calibrate again.'
            )
        lines.append("")
        return lines

    def text(self) -> str:
        title = PRACTICE_TITLE if self.dry_run else "Calibration report"
        yes = "yes" if self.matched else "no"
        lines = [
            f"# {title}",
            "",
            f"Limit: ${self.max_dollars:g}. Spent: ${self.spent_usd:.4f}. "
            f"Finished: {'yes' if self.complete else 'no (partial)'}. "
            f"Thinking matched: {yes}"
            + (f" (highest/lowest {self.median_ratio:.2f})" if self.median_ratio else "")
            + ".",
            "",
        ]
        lines += self._form_lines()
        lines += [
            "## Chosen versions",
            "",
        ]
        lines += [f"- {role}: {ver}" for role, ver in sorted(self.versions.items())]
        lines += ["", "## Thinking settings", ""]
        lines += [
            f"- {role}: {', '.join(f'{k}={v}' for k, v in sorted(s.items())) or '(none)'}"
            for role, s in sorted(self.settings.items())
        ]
        lines += ["", "## Thinking tokens per model (median, main decisions)", ""]
        for model, tokens in sorted(self.thinking_tokens_by_model.items()):
            lines.append(f"- {model}: {'not reported' if tokens is None else f'{tokens:g}'}")
        lines += ["", "## Search", ""]
        for r in self.rounds:
            lines.append(f"- {r['text']}")
        lines += [
            "",
            "## Cost",
            "",
            f"- Cost per slow decision: ${self.cost_per_slow_decision:.6f}",
            f"- Cost per hooked decision: ${self.cost_per_hooked_decision:.6f}",
            f"- Cost per game week (four seats and the judge): ${self.cost_per_game_week:.4f}",
            "- Game weeks per $100: "
            + ("n/a" if self.weeks_per_100 is None else f"{self.weeks_per_100:.2f}"),
            f"- Reaches game week 7 within the spend cap: {'yes' if self.reaches_week_7 else 'no'}",
            f"- One cheap seat for a game week: ${self.cheap_seat_week_cost:.4f} (the dearest of: "
            + ", ".join(f"{p} ${c:.4f}" for p, c in sorted(self.cheap_seat_week_costs.items()))
            + ")",
            f"- Estimated pilot cost: ${self.pilot_cost:.4f}",
        ]
        if self.warnings:
            lines += ["", "## Warnings", ""]
            lines += [f"- {w}" for w in self.warnings]
        if self.stopped:
            lines += ["", stop_text(self.stop_reason, self.stop_detail, f"{self.max_dollars:g}")]
        lines.append("")
        return "\n".join(lines)


# ----------------------------------------------------------------------------- the run


@dataclass
class _Rec:
    key: str
    player: str | None
    role: str
    purpose: str
    kind: str  # main | helper | cheap | judge
    sample_id: str
    tier: str
    repeat: int
    setting: str | None
    layers: Any
    schema: Any
    family: str
    cost: float = 0.0
    thinking: int | None = None
    status: str = ""
    version: str = ""
    done: bool = False


class _Runner:
    def __init__(self, config: GameConfig, adapters: dict[str, Any], max_dollars: float, db):
        self.config = config
        self.db = db
        self.ledger = SpendLedger(max_dollars, 1.0)
        self.backend = "live" if adapters and live_backend(config, adapters) == "live" else "fake"
        self.ai_cfg = config.run.ai.model_copy(update={"backend": self.backend})
        self.adapters = adapters
        self.records: list[_Rec] = []

    def execute(self, specs: list[_Rec], models: ModelsConfig) -> None:
        """Send the specs a few at a time; RunPaused (the limit) propagates."""
        broker = CallBroker(self.db, models, self.ai_cfg, self.adapters, self.ledger)
        for i in range(0, len(specs), _CHUNK):
            chunk = specs[i : i + _CHUNK]
            requests = {}
            for s in chunk:
                role = models.roles[s.role]
                requests[s.key] = LLMRequest(
                    key=s.key,
                    tick=0,
                    player_id=s.player,
                    role=s.role,
                    purpose=s.purpose,  # type: ignore[arg-type]
                    layers=s.layers,
                    schema=s.schema,
                    max_output_tokens=int(role.max_output_tokens),
                    meta={"family": s.family},
                )
            results = broker.run({k: one(r) for k, r in requests.items()})
            for s in chunk:
                res = results[s.key]
                s.cost = res.cost_usd
                s.thinking = res.usage.thinking_tokens
                s.status = res.status
                s.version = res.model_version
                s.done = True
                self.records.append(s)


def _ladder_value(config: GameConfig, role_id: str) -> tuple[str | None, str | None]:
    role = config.models.roles[role_id]
    ladder = config.models.calibration.ladders.get(role.provider)
    if ladder is None:
        return None, None
    return ladder.key, role.thinking.get(ladder.key)


def _with_setting(models: ModelsConfig, role_id: str, key: str, value: str) -> ModelsConfig:
    role = models.roles[role_id]
    new = role.model_copy(update={"thinking": {**role.thinking, key: value}})
    return models.model_copy(update={"roles": {**models.roles, role_id: new}})


def _force_table(config: GameConfig, role_id: str) -> dict[str, str | int] | None:
    """The provider's forced-thinking settings (ladder ``force``), or None."""
    ladder = config.models.calibration.ladders.get(config.models.roles[role_id].provider)
    force = getattr(ladder, "force", None) if ladder is not None else None
    return dict(force) if force else None


def _force_label(table: dict[str, str | int]) -> str:
    items = sorted(table.items(), key=lambda kv: kv[0] != "type")
    return ", ".join(f"{k}={v}" for k, v in items)


def _variant(config: GameConfig, role_id: str, key: str, value: str) -> ModelsConfig:
    """The models with one main role set to a ladder step, or to its forced-thinking table."""
    force = _force_table(config, role_id)
    if force is not None and value == _force_label(force):
        role = config.models.roles[role_id]
        new = role.model_copy(update={"thinking": dict(force)})
        return config.models.model_copy(update={"roles": {**config.models.roles, role_id: new}})
    return _with_setting(config.models, role_id, key, value)


def _build_specs(config: GameConfig, stage: str, repeats: int) -> dict[str, list[_Rec]]:
    """All sample calls of the baseline, grouped: mains, helpers (with cheap) and judge."""
    from ai_island.minds.samples import calibration_samples, judge_check_samples

    jb = config.balance.judge
    groups: dict[str, list[_Rec]] = {"main": [], "helper": [], "judge": []}
    for n in PLAYERS:
        pid, main, helper = f"player_{n}", f"player_{n}_main", f"player_{n}_helper"
        _, setting = _ladder_value(config, main)
        for sample in calibration_samples(config):
            for call in sample.calls:
                for rep in range(repeats):
                    base = f"cal/{stage}/{pid}/{sample.sample_id}/{call.purpose}/{rep}"
                    if call.purpose == "main":
                        groups["main"].append(
                            _Rec(
                                base,
                                pid,
                                main,
                                "main",
                                "main",
                                sample.sample_id,
                                sample.tier,
                                rep,
                                setting,
                                call.layers,
                                call.schema,
                                call.family,
                            )  # fmt: skip
                        )
                        groups["helper"].append(
                            _Rec(
                                base + "/cheap",
                                pid,
                                helper,
                                "main",
                                "cheap",
                                sample.sample_id,
                                sample.tier,
                                rep,
                                None,
                                call.layers,
                                call.schema,
                                call.family,
                            )  # fmt: skip
                        )
                    else:
                        groups["helper"].append(
                            _Rec(
                                base,
                                pid,
                                helper,
                                call.purpose,
                                "helper",
                                sample.sample_id,
                                sample.tier,
                                rep,
                                None,
                                call.layers,
                                call.schema,
                                call.family,
                            )  # fmt: skip
                        )
    for jn, js in enumerate(judge_check_samples(config)):
        base_schema = FullJudgeLabel if js["detail"] == "full" else ShortJudgeLabel
        schema = bind_schema(base_schema, VALUE_IDS, jb.full_max_chars)
        for rep in range(repeats):
            groups["judge"].append(
                _Rec(
                    f"cal/{stage}/judge/{jn + 1}/{rep}",
                    None,
                    "judge",
                    "judge",
                    "judge",
                    js["sample_id"],
                    js["detail"],
                    rep,
                    None,
                    js["layers"],
                    schema,
                    "judge",
                )  # fmt: skip
            )
    return groups


def _main_specs(config: GameConfig, role_id: str, setting: str | None, tag: str) -> list[_Rec]:
    """The slow and hooked main calls of one main role, for the thinking search."""
    from ai_island.minds.samples import calibration_samples

    cal = config.models.calibration
    pid = role_id.removesuffix("_main")
    out: list[_Rec] = []
    for sample in calibration_samples(config):
        if sample.tier == "fast":
            continue
        for call in sample.calls:
            if call.purpose != "main":
                continue
            for rep in range(cal.repeats):
                out.append(
                    _Rec(
                        f"cal/{tag}/{pid}/{sample.sample_id}/main/{rep}",
                        pid,
                        role_id,
                        "main",
                        "main",
                        sample.sample_id,
                        sample.tier,
                        rep,
                        setting,
                        call.layers,
                        call.schema,
                        call.family,
                    )  # fmt: skip
                )
    return out


def _thinking_medians(
    records: list[_Rec], current: dict[str, str | None]
) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for role, setting in current.items():
        vals = [
            r.thinking
            for r in records
            if r.kind == "main" and r.role == role and r.setting == setting and r.done
        ]
        known = [v for v in vals if v is not None]
        out[role] = float(statistics.median(known)) if known and len(known) == len(vals) else None
    return out


def _next_move(
    config: GameConfig,
    current: dict[str, str | None],
    meds: dict[str, float | None],
    seen: list[dict[str, str | None]],
    blocked: Sequence[tuple[str, str]] = (),
) -> tuple[str, str] | None:
    """(role, new setting): the outlier highest/lowest role one ladder step toward the others."""
    values = [m for m in meds.values() if m is not None]
    middle = statistics.median(values)
    hi = max(meds, key=lambda r: meds[r])  # type: ignore[arg-type,return-value]
    lo = min(meds, key=lambda r: meds[r])  # type: ignore[arg-type,return-value]
    order = [(hi, -1), (lo, 1)]
    if (meds[hi] or 0) / middle < middle / (meds[lo] or 1):
        order.reverse()  # the lowest is the bigger outlier
    for role, step in order:
        provider = config.models.roles[role].provider
        ladder = config.models.calibration.ladders.get(provider)
        value = current[role]
        if ladder is None or value not in ladder.steps:
            continue
        idx = ladder.steps.index(value) + step
        if not 0 <= idx < len(ladder.steps):
            continue
        trial = {**current, role: ladder.steps[idx]}
        if trial in seen or (role, ladder.steps[idx]) in blocked:
            continue
        return role, ladder.steps[idx]
    return None


def run_calibration(
    config: GameConfig,
    adapters: dict[str, Any] | None,
    max_dollars: float,
    out_dir: Path,
    dry_run: bool = False,
) -> CalibrationReport:
    """Measure, search, price and write the report; stops before a call that could pass the limit.

    ``adapters`` None with ``dry_run`` means the pretend AI (DryRunAdapter).
    """
    out_dir = Path(out_dir)
    if adapters is None:
        adapters = {"fake": DryRunAdapter(config)}
    session = new_session_dir(out_dir)
    db = RunDB.create(session / "calls.db")
    runner = _Runner(config, adapters, max_dollars, db)
    if dry_run:
        runner.backend = "fake"
        runner.ai_cfg = config.run.ai.model_copy(update={"backend": "fake"})
    report = CalibrationReport(dry_run=dry_run, max_dollars=max_dollars, db_path=db.path)
    try:
        _measure(config, runner, report)
    finally:
        report.spent_usd = runner.ledger.total_usd
        db.close()
    out_dir.mkdir(parents=True, exist_ok=True)
    report.report_path = out_dir / "report.md"
    report.report_path.write_text(report.text(), encoding="utf-8", newline="\n")
    (out_dir / "result.json").write_text(
        json.dumps(report.to_dict(), indent=2, sort_keys=True, default=str),
        encoding="utf-8",
        newline="\n",
    )
    return report


def _measure(config: GameConfig, runner: _Runner, report: CalibrationReport) -> None:
    from ai_island.minds.samples import SAMPLE_VERSION

    cal = config.models.calibration
    models = config.models
    report.sample_version = SAMPLE_VERSION
    groups = _build_specs(config, "r0", cal.repeats)
    current: dict[str, str | None] = {r: _ladder_value(config, r)[1] for r in MAIN_ROLES}
    try:
        if not _form_check(config, runner, report, groups):
            report.stopped = True
            report.stop_reason = "provider_error"
            report.stop_detail = "; ".join(
                f"{r['provider']} / {r['model']}: {r['message']}" for r in report.form_refused
            )
            report.warnings.append("Form check failed: nothing else was measured.")
            _finish(config, runner, report, current)
            return
        for name in ("main", "helper", "judge"):
            runner.execute(groups[name], models)
        report.complete = True
        _search(config, runner, report, current)
    except RunPaused as exc:
        report.stopped = True
        report.stop_reason = str(exc.reason)
        report.stop_detail = str(exc)
        if exc.reason == "spend_cap":
            report.warnings.append("The money limit was reached before everything was measured.")
        else:
            report.warnings.append(
                stop_text(report.stop_reason, report.stop_detail, "")
                + " Not everything was measured."
            )
    _finish(config, runner, report, current)


def _schema_size(schema: Any) -> int:
    try:
        return len(json.dumps(schema.model_json_schema(), sort_keys=True))
    except Exception:
        return 0


def _form_specs(config: GameConfig, groups: dict[str, list[_Rec]]) -> list[_Rec]:
    """One spec per distinct (provider, model): the largest reply schema its roles use, with the
    smallest real prompt among those."""
    by_model: dict[tuple[str, str], _Rec] = {}
    ranks: dict[tuple[str, str], tuple[int, int]] = {}
    for name in ("main", "helper", "judge"):
        for spec in groups[name]:
            role = config.models.roles[spec.role]
            ident = (role.provider, role.model)
            rank = (-_schema_size(spec.schema), len(repr(spec.layers)))
            if ident not in ranks or rank < ranks[ident]:
                ranks[ident] = rank
                by_model[ident] = spec
    out = []
    for (provider, model), spec in by_model.items():
        out.append(
            dataclasses.replace(
                spec,
                key=f"cal/form/{provider}/{model}",
                kind="form",
                setting=None,
                cost=0.0,
                done=False,
            )
        )
    return out


def _form_check(
    config: GameConfig,
    runner: _Runner,
    report: CalibrationReport,
    groups: dict[str, list[_Rec]],
) -> bool:
    """Send each model one small request in its configured mode before any measuring.

    A refused request is recorded and the check goes on with the next model; any other pause
    (money limit, no network, sleep) propagates. True when every model accepted.
    """
    for spec in _form_specs(config, groups):
        role = config.models.roles[spec.role]
        label = f"{role.provider} / {role.model}"
        report.form_checked.append(label)
        try:
            runner.execute([spec], config.models)
        except RunPaused as exc:
            if exc.reason != "provider_error":
                raise
            report.form_refused.append(
                {"provider": role.provider, "model": role.model, "message": str(exc)}
            )
    runner.records = [r for r in runner.records if r.kind != "form"]
    return not report.form_refused


def _nonzero_ratio(meds: dict[str, float | None]) -> float | None:
    """highest / lowest over the models that did think; None when one is missing or none thought."""
    if any(m is None for m in meds.values()):
        return None
    pos = [m for m in meds.values() if m is not None and m > 0]
    return median_ratio(pos) if pos else None


def _zero_move(
    config: GameConfig,
    current: dict[str, str | None],
    zeros: list[str],
    seen: list[dict[str, str | None]],
    blocked: Sequence[tuple[str, str]] = (),
) -> tuple[str | None, str | None, list[str]]:
    """(role, new setting, stuck roles): the first zero-thinking main goes one step up; at the
    top of its ladder it gets one forced-thinking round when the provider has a ``force`` table."""
    stuck: list[str] = []
    for role in zeros:
        ladder = config.models.calibration.ladders.get(config.models.roles[role].provider)
        value = current[role]
        if ladder is not None and value in ladder.steps:
            idx = ladder.steps.index(value) + 1
            if idx < len(ladder.steps):
                step = ladder.steps[idx]
                if {**current, role: step} not in seen and (role, step) not in blocked:
                    return role, step, stuck
            else:
                force = _force_table(config, role)
                if force is not None:
                    label = _force_label(force)
                    if (role, label) not in blocked and {**current, role: label} not in seen:
                        return role, label, stuck
        stuck.append(role)
    return None, None, stuck


def _search(
    config: GameConfig,
    runner: _Runner,
    report: CalibrationReport,
    current: dict[str, str | None],
) -> None:
    cal = config.models.calibration
    history = [dict(current)]
    meds = _thinking_medians(runner.records, current)
    ratio = _nonzero_ratio(meds)
    report.rounds.append({"text": f"Start: medians {_fmt(meds)}", "ratio": ratio})
    if any(m is None for m in meds.values()):
        report.warnings.append(
            "A main model reported no thinking tokens, so the effort cannot be matched."
        )
        return
    if ratio is None:
        report.warnings.append(
            "No main model reported any thinking tokens, so the effort cannot be matched."
        )
        return
    models = config.models
    warned: set[str] = set()
    blocked: list[tuple[str, str]] = []

    def _at_top(role: str) -> bool:
        ladder = models.calibration.ladders.get(models.roles[role].provider)
        value = current[role]
        return ladder is None or value not in ladder.steps or value == ladder.steps[-1]

    def _zero_warning(role: str) -> None:
        warned.add(role)
        name = models.roles[role].model
        force = _force_table(config, role)
        if force is not None and current[role] == _force_label(force):
            report.warnings.append(
                f"{name} did not think even with thinking forced on; its thinking is not matched."
            )
        elif _at_top(role):
            report.warnings.append(
                f"{name} did not think even at its highest setting; its thinking is not matched."
            )
        else:
            report.warnings.append(
                f"{name} did not think and no higher setting could be tried; "
                "its thinking is not matched."
            )

    for rnd in range(1, cal.max_rounds + 1):
        zeros = [r for r, m in meds.items() if m == 0 and r not in warned]
        zero_role, zero_value, stuck = _zero_move(config, current, zeros, history, blocked)
        for role in stuck:
            _zero_warning(role)
        if zero_role is not None and zero_value is not None:
            move: tuple[str, str] | None = (zero_role, zero_value)
        else:
            if ratio is None or ratio <= cal.max_median_ratio:
                break
            nonzero = {r: m for r, m in meds.items() if m is not None and m > 0}
            move = _next_move(
                config,
                {r: current[r] for r in nonzero},
                nonzero,
                [{r: h[r] for r in nonzero} for h in history],
                blocked,
            )
            if move is not None:
                move = (move[0], move[1])
        if move is None:
            report.warnings.append("No ladder step is left to try; the effort is not matched.")
            break
        role, value = move
        key = _ladder_value(config, role)[0] or ""
        previous = current[role]
        force = _force_table(config, role)
        is_force = force is not None and value == _force_label(force)
        ladder = models.calibration.ladders.get(models.roles[role].provider)
        went_down = bool(
            ladder is not None
            and previous in ladder.steps
            and value in ladder.steps
            and ladder.steps.index(value) < ladder.steps.index(previous)
        )
        have = [
            r for r in runner.records if r.role == role and r.setting == value and r.kind == "main"
        ]
        if not have:
            costs = [r.cost for r in runner.records if r.kind == "main" and r.done]
            need = _mean(costs) * 2 * len(_main_specs(config, role, value, "est"))
            room = runner.ledger.cap_usd - runner.ledger.total_usd - runner.ledger.reserved_usd
            if need > room:
                report.warnings.append("The money limit is near, so the search stopped early.")
                break
            variant = _variant(config, role, key, value)
            try:
                runner.execute(_main_specs(config, role, value, f"r{rnd}"), variant)
            except RunPaused as exc:
                if exc.reason != "provider_error":
                    raise
                blocked.append((role, value))
                provider = models.roles[role].provider
                what = "forced thinking" if is_force else f"the {value} setting"
                report.warnings.append(f"{provider} refused {what}: {exc}")
                report.rounds.append(
                    {
                        "text": f"Round {rnd}: {role} -> {value} was refused; medians {_fmt(meds)}",
                        "ratio": ratio,
                    }
                )
                if meds.get(role) == 0:
                    warned.add(role)
                continue
        current[role] = value
        meds = _thinking_medians(runner.records, current)
        if went_down and meds.get(role) == 0:
            blocked.append((role, value))
            current[role] = previous
            meds = _thinking_medians(runner.records, current)
            ratio = _nonzero_ratio(meds)
            report.rounds.append(
                {
                    "text": (
                        f"Round {rnd}: {role} -> {value} gave no thinking; step unusable, "
                        f"back to {previous}; medians {_fmt(meds)}"
                    ),
                    "ratio": ratio,
                }
            )
            continue
        history.append(dict(current))
        ratio = _nonzero_ratio(meds)
        report.rounds.append(
            {"text": f"Round {rnd}: {role} -> {value}; medians {_fmt(meds)}", "ratio": ratio}
        )
        if any(m is None for m in meds.values()):
            report.warnings.append("Thinking counts went missing during the search.")
            break
        if is_force and meds.get(role) == 0:
            _zero_warning(role)
    # a zero model that is still zero after the rounds run out
    for role, m in meds.items():
        if m == 0 and role not in warned:
            _zero_warning(role)
    best, best_ratio, best_zeros = None, math.inf, math.inf
    for cfg in history:
        hm = _thinking_medians(runner.records, cfg)
        m = _nonzero_ratio(hm)
        zc = sum(1 for v in hm.values() if v == 0)
        if m is not None and (zc, m) < (best_zeros, best_ratio):
            best, best_ratio, best_zeros = cfg, m, zc
    if best is not None:
        current.update(best)
    if best is not None and best_ratio > cal.max_median_ratio:
        report.warnings.append(
            f"Thinking not matched after the search (closest {best_ratio:.2f}, "
            f"wanted {cal.max_median_ratio:g})."
        )


def _fmt(meds: dict[str, float | None]) -> str:
    return ", ".join(
        f"{r.removesuffix('_main')}={'?' if m is None else f'{m:g}'}" for r, m in meds.items()
    )


def _finish(
    config: GameConfig,
    runner: _Runner,
    report: CalibrationReport,
    current: dict[str, str | None],
) -> None:
    cal = config.models.calibration
    days = config.world.clock.days_per_week
    recs = [r for r in runner.records if r.done]
    # versions, settings
    for r in recs:
        if r.version:
            report.versions[r.role] = r.version
    for role_id, role in config.models.roles.items():
        report.versions.setdefault(role_id, role.model)
        thinking = dict(role.thinking)
        if role_id in current:
            key, _ = _ladder_value(config, role_id)
            value = current[role_id]
            force = _force_table(config, role_id)
            if force is not None and value == _force_label(force):
                thinking = dict(force)
            elif key and value is not None:
                thinking[key] = value
        report.settings[role_id] = thinking
    meds = _thinking_medians(recs, current)
    for role_id, med in meds.items():
        model = config.models.roles[role_id].model
        report.thinking_tokens_by_model[model] = med
    report.median_ratio = _nonzero_ratio(meds)
    values = list(meds.values())
    report.matched = (
        report.complete
        and report.median_ratio is not None
        and report.median_ratio <= cal.max_median_ratio
        and len(values) == len(MAIN_ROLES)
    )
    if not report.complete:
        report.matched = False
        return

    def costs(role: str, kind: str, purpose: str, tier: str | None, setting: Any = "any") -> float:
        sel = [
            r.cost
            for r in recs
            if r.role == role
            and r.kind == kind
            and r.purpose == purpose
            and (tier is None or r.tier == tier)
            and (setting == "any" or r.setting == setting)
        ]
        return _mean(sel)

    judge_label = _mean([r.cost for r in recs if r.kind == "judge"])
    jweek = judge_week_cost(judge_label, cal, days)
    seats: list[float] = []
    cheap: dict[str, float] = {}
    slow_all: list[float] = []
    hooked_all: list[float] = []
    for n in PLAYERS:
        main, helper = f"player_{n}_main", f"player_{n}_helper"
        noticer = costs(helper, "helper", "noticer", None)
        advisor = costs(helper, "helper", "advisor", None)
        fast = costs(helper, "helper", "fast", None)
        main_slow = costs(main, "main", "main", "slow", current[main])
        hooked = costs(main, "main", "main", "hooked", current[main])
        slow = noticer + advisor + main_slow
        report.cost_per_slow_by_role[main] = slow
        report.cost_per_hooked_by_role[main] = hooked
        slow_all.append(slow)
        hooked_all.append(hooked)
        seats.append(seat_week_cost(slow, hooked, fast, main_slow, cal, days))
        c_slow = costs(helper, "cheap", "main", "slow")
        c_hooked = costs(helper, "cheap", "main", "hooked")
        week = seat_week_cost(noticer + advisor + c_slow, c_hooked, fast, c_slow, cal, days)
        cheap[config.models.roles[helper].provider] = week + jweek / len(PLAYERS)
    report.cost_per_slow_decision = _mean(slow_all)
    report.cost_per_hooked_decision = _mean(hooked_all)
    report.cost_per_game_week = sum(seats) + jweek
    report.weeks_per_100 = 100.0 / report.cost_per_game_week if report.cost_per_game_week else None
    report.reaches_week_7 = bool(
        report.cost_per_game_week
        and config.run.spend_cap_usd >= cal.target_week * report.cost_per_game_week
    )
    report.cheap_seat_week_costs = cheap
    report.cheap_seat_week_cost = max(cheap.values()) if cheap else 0.0
    report.pilot_cost = cal.pilot_weeks * sum(cheap.values()) * (1 + cal.safety_share)
    bad = sum(1 for r in recs if r.status != "ok")
    if bad:
        report.warnings.append(f"{bad} sample replies were refused or had a wrong format.")
    if report.dry_run:
        report.warnings.append("Practice run: thinking counts and costs are made up, not measured.")


# ----------------------------------------------------------------------------- --apply


def apply_calibration(models_toml: Path, report: CalibrationReport) -> None:
    """Write the matched thinking settings and the measured costs into models.toml.

    Only a finished, matched, non-practice report is accepted. Comments and prices are kept; the
    new file is validated, written next to the old one and swapped in.
    """
    import tomlkit

    if report.dry_run:
        raise CalibrationError("a practice run measures nothing, so it cannot be applied")
    if not report.complete or report.stopped:
        raise CalibrationError("the calibration did not finish, so it cannot be applied")
    if not report.matched:
        raise CalibrationError("the thinking effort is not matched, so it cannot be applied")
    path = Path(models_toml)
    raw = path.read_bytes()
    bom = raw.startswith(b"\xef\xbb\xbf")
    doc = tomlkit.parse(raw.decode("utf-8-sig"))
    roles = doc["roles"]
    for role_id in MAIN_ROLES:
        wanted = report.settings.get(role_id)
        if wanted is None or role_id not in roles:
            raise CalibrationError(f"no settings for {role_id}")
        table = roles[role_id]["thinking"]
        for key in [k for k in table if k not in wanted]:
            del table[key]
        for key, value in wanted.items():
            if table.get(key) != value:
                table[key] = value
    measured = tomlkit.table()
    measured.add("date", date.today().isoformat())
    measured.add("versions", dict(sorted(report.versions.items())))
    measured.add("thinking", {r: dict(report.settings[r]) for r in MAIN_ROLES})
    measured.add("cost_per_slow_usd", _rounded(report.cost_per_slow_by_role))
    measured.add("cost_per_hooked_usd", _rounded(report.cost_per_hooked_by_role))
    measured.add("cost_per_week_usd", round(report.cost_per_game_week, 6))
    if report.weeks_per_100 is not None:
        measured.add("weeks_per_100", round(report.weeks_per_100, 6))
    measured.add("cheap_seat_week_usd", _rounded(report.cheap_seat_week_costs))
    measured.add("pilot_usd", round(report.pilot_cost, 6))
    measured.add("sample_version", report.sample_version)
    calibration = doc["calibration"]
    if "measured" in calibration:
        del calibration["measured"]
    calibration["measured"] = measured
    text = tomlkit.dumps(doc)
    try:
        ModelsConfig.model_validate(tomllib.loads(text))
    except Exception as exc:  # the file is left exactly as it was
        raise CalibrationError(f"the updated models file would not load: {exc}") from exc
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes((b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))
    os.replace(tmp, path)


def _rounded(values: dict[str, float]) -> dict[str, float]:
    return {k: round(v, 6) for k, v in sorted(values.items())}
