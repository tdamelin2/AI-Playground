"""The blind judge's output in words for the observer (Contract C10)."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from ai_island.measure.history import HistoryRow

_SUMMARY_ID_BASE = 10**9  # history ids of judge rows: after the events of the same tick


def value_name(value_id: Any) -> str:
    """A value id in words: ``self_reliance`` -> ``Self reliance``."""
    text = str(value_id).replace("_", " ").strip()
    return text[:1].upper() + text[1:]


def _names_list(items: Any) -> str:
    if not isinstance(items, (list, tuple)) or not items:
        return "nothing"
    return ", ".join(value_name(i) for i in items)


def judge_words(label_json: str | None, detail: str | None) -> str:
    """``judge (full): served Family, Honesty; broke Loyalty; against`` and its variants.

    ``judge: pending`` without a label, ``judge: failed`` for a failed row. A full label adds the
    rationale.
    """
    if label_json is None:
        return "judge: pending"
    try:
        label = json.loads(label_json)
    except (ValueError, TypeError):
        return "judge: pending"
    if not isinstance(label, dict):
        return "judge: pending"
    if label.get("status") == "failed":
        return "judge: failed"
    level = detail if detail in ("full", "short") else ("full" if "rationale" in label else "short")
    text = (
        f"judge ({level}): served {_names_list(label.get('served'))}; "
        f"broke {_names_list(label.get('violated'))}; {label.get('direction', '?')}"
    )
    rationale = str(label.get("rationale") or "").strip()
    if level == "full" and rationale:
        text += f" | why: {rationale}"
    return text


def with_names(text: str, names: Mapping[str, str]) -> str:
    """Replace known person ids inside ``text`` by their names."""
    if not names:
        return text
    pattern = "|".join(re.escape(i) for i in sorted(names, key=len, reverse=True))
    return re.sub(rf"\b(?:{pattern})\b", lambda m: names[m.group(0)], text)


def history_rows_for_day(
    db: Any, summary: Any, names: Mapping[str, str], ticks_per_day: int
) -> list[HistoryRow]:
    """The World history rows of one daily summary: the summary and that day's flags."""
    from ai_island.measure.judge import day_flags

    base = _SUMMARY_ID_BASE + summary.period * 100
    rows = [
        HistoryRow(
            base,
            summary.tick,
            "judge_summary",
            f"Day {summary.period} summary: {with_names(summary.text, names)}",
        )
    ]
    try:
        flags = day_flags(db, summary.period, ticks_per_day)
    except Exception:  # a half-written run must not break the window
        flags = []
    for i, flag in enumerate(flags, start=1):
        who = tuple(x for x in (flag.player, *flag.others) if x)
        rows.append(
            HistoryRow(
                base + min(i, 99),
                summary.tick,
                f"flag_{flag.kind}",
                f"Day {summary.period} flag ({flag.kind.replace('_', ' ')}): "
                f"{with_names(flag.text, names)}",
                who,
            )
        )
    return rows


def profile_lines(profiles: Mapping[str, Any], player_id: str) -> str:
    """The Players-tab line of a player's newest weekly profile ('' when none)."""
    row = profiles.get(player_id)
    if row is None:
        return ""
    return f"profile (week {row.period}): {row.text}"
