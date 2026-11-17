"""judge-check: run the blind judge on a few fixed sample choices and show what it says (C9).

Every call goes through one broker and one money ledger, on a database of its own under
``runs/judge-check/<session>/calls.db``. Nothing here runs in a game. With the practice backend
(``dry_run``) the pretend AI answers and nothing is spent.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ai_island.config import GameConfig
from ai_island.llm.broker import CallBroker
from ai_island.llm.errors import RunPaused
from ai_island.llm.ledger import SpendLedger
from ai_island.llm.types import LLMRequest
from ai_island.measure.judge import JudgeLeakError, blind_problems, blind_words
from ai_island.measure.judge_schemas import FullJudgeLabel, ShortJudgeLabel, bind_schema
from ai_island.minds.values import VALUE_IDS
from ai_island.storage.db import RunDB

STOP_TEXT = "Stopped: the next call could pass the ${limit} limit."

_PAUSE_WORDS = {
    "network": "there is no internet connection",
    "sleep": "the laptop went to sleep",
    "provider_error": "an AI company rejected a request",
}


def stop_text(reason: str, detail: str, limit: str) -> str:
    """The plain stop line for any pause reason (spend_cap keeps STOP_TEXT)."""
    if reason == "spend_cap":
        return STOP_TEXT.format(limit=limit)
    words = _PAUSE_WORDS.get(reason, reason)
    line = f"Stopped: {words}."
    if detail and detail != reason:
        line += f" Message: {detail}"
    return line


def new_session_dir(base: Path) -> Path:
    """A fresh ``<base>/<timestamp>`` folder name (a suffix is added if it already exists)."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = base / stamp
    n = 1
    while path.exists():
        n += 1
        path = base / f"{stamp}-{n}"
    return path


def one(request: LLMRequest):
    """A broker pipeline that sends one request and returns its result."""
    result = yield request
    return result


def live_backend(config: GameConfig, adapters: dict[str, Any]) -> str:
    """ "live" when every role's provider has its own adapter, else the practice backend."""
    ok = all(r.provider in adapters for r in config.models.roles.values())
    return "live" if ok else "fake"


def words_for(label: dict[str, Any]) -> str:
    """A label in a few plain words."""

    def names(items: Any) -> str:
        if not isinstance(items, list) or not items:
            return "nothing"
        return ", ".join(str(i).replace("_", " ").capitalize() for i in items)

    if label.get("status") == "failed":
        return f"failed ({label.get('reason')})"
    return (
        f"served {names(label.get('served'))}; broke {names(label.get('violated'))}; "
        f"{label.get('direction', '?')}"
    )


@dataclass
class JudgeCheckItem:
    sample_id: str
    detail: str
    status: str
    label: dict[str, Any] | None
    cost_usd: float
    attempts: int
    blind_clean: bool = True


@dataclass
class JudgeCheckResult:
    dry_run: bool
    complete: bool
    stopped: bool
    stop_reason: str = "spend_cap"
    stop_detail: str = ""
    items: list[JudgeCheckItem] = field(default_factory=list)
    total_cost_usd: float = 0.0
    max_dollars: float = 0.0
    report_path: Path | None = None
    db_path: Path | None = None

    def text(self) -> str:
        title = (
            "# Judge check: practice (pretend AI), no money spent"
            if self.dry_run
            else "# Judge check"
        )
        lines = [
            title,
            "",
            f"Limit: ${self.max_dollars:g}. Spent: ${self.total_cost_usd:.6f}.",
            "",
            "| Sample | Level | Status | What the judge said | Cost | Tries |",
            "|---|---|---|---|---|---|",
        ]
        for it in self.items:
            said = words_for(it.label) if it.label else "(no label)"
            lines.append(
                f"| {it.sample_id} | {it.detail} | {it.status} | {said} | "
                f"${it.cost_usd:.6f} | {it.attempts} |"
            )
        lines.append("")
        clean = all(it.blind_clean for it in self.items)
        lines.append(
            "No model or company name was in any prompt."
            if clean
            else "A blind word was found in a prompt (this is a bug)."
        )
        if self.stopped:
            said = stop_text(self.stop_reason, self.stop_detail, f"{self.max_dollars:g}")
            lines += ["", said + " Partial report."]
        lines.append("")
        return "\n".join(lines)


def run_judge_check(
    config: GameConfig,
    adapters: dict[str, Any] | None,
    max_dollars: float,
    out_dir: Path,
    dry_run: bool = False,
    emit: Callable[[str], None] = print,
) -> JudgeCheckResult:
    """Label the sample choices with the judge; stops before a call that could pass the limit.

    ``adapters`` None with ``dry_run`` means the pretend AI priced at the real prices.
    """
    from ai_island.llm.fake import FakeAdapter
    from ai_island.minds.samples import judge_check_samples

    out_dir = Path(out_dir)
    if adapters is None:
        adapters = {"fake": FakeAdapter(bill=True)}
    backend = "fake" if dry_run else live_backend(config, adapters)
    ai_cfg = config.run.ai.model_copy(update={"backend": backend})
    session = new_session_dir(out_dir)
    db = RunDB.create(session / "calls.db")
    ledger = SpendLedger(max_dollars, 1.0)
    broker = CallBroker(db, config.models, ai_cfg, adapters, ledger)
    jb = config.balance.judge
    role = config.models.roles["judge"]
    words = blind_words(config)
    result = JudgeCheckResult(dry_run, False, False, max_dollars=max_dollars, db_path=db.path)
    try:
        for n, sample in enumerate(judge_check_samples(config)):
            layers = sample["layers"]
            for text in (layers.fixed, layers.slow, layers.current):
                found = blind_problems(text, words)
                if found:
                    raise JudgeLeakError(f"judge check sample {sample['sample_id']}: {found}")
            base = FullJudgeLabel if sample["detail"] == "full" else ShortJudgeLabel
            schema = bind_schema(base, VALUE_IDS, jb.full_max_chars)
            key = f"check/{n + 1}/{sample['sample_id']}"
            request = LLMRequest(
                key=key,
                tick=0,
                player_id=None,
                role="judge",
                purpose="judge",
                layers=layers,
                schema=schema,
                max_output_tokens=int(role.max_output_tokens),
                meta={"family": "judge"},
            )
            try:
                res = broker.run({key: one(request)})[key]
            except RunPaused as exc:
                result.stopped = True
                result.stop_reason = str(exc.reason)
                result.stop_detail = str(exc)
                break
            label = res.parsed.model_dump(mode="json") if res.parsed is not None else None
            item = JudgeCheckItem(
                sample["sample_id"], sample["detail"], res.status, label, res.cost_usd, res.attempts
            )
            result.items.append(item)
            said = words_for(label) if label else "(no label)"
            emit(f"{item.sample_id} ({item.detail}): {said}  cost ${item.cost_usd:.6f}")
        else:
            result.complete = True
        result.total_cost_usd = ledger.total_usd
    finally:
        db.close()
    out_dir.mkdir(parents=True, exist_ok=True)
    result.report_path = out_dir / "report.md"
    result.report_path.write_text(result.text(), encoding="utf-8", newline="\n")
    (session / "result.json").write_text(
        json.dumps(
            {
                "dry_run": dry_run,
                "complete": result.complete,
                "stopped": result.stopped,
                "stop_reason": result.stop_reason if result.stopped else None,
                "stop_detail": result.stop_detail if result.stopped else None,
                "total_cost_usd": result.total_cost_usd,
                "items": [it.__dict__ for it in result.items],
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
        newline="\n",
    )
    return result
