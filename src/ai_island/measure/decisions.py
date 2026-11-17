"""The ``decisions`` command text: every decision a player made, one block each."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from ai_island.minds.choice import describe_action

_MINUTES_PER_DAY = 1440


def _stamp(tick: int) -> str:
    day, minute_of_day = divmod(tick, _MINUTES_PER_DAY)
    hour, minute = divmod(minute_of_day, 60)
    return f"Day {day + 1} {hour:02d}:{minute:02d}"


def _words(items: Any) -> str:
    return ", ".join(str(i) for i in items) if items else "nothing"


def _load(text: str | None) -> dict[str, Any]:
    if not text:
        return {}
    try:
        value = json.loads(text)
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


_FROM_KINDS = {"steal": "steal from", "attack": "attack", "trade": "trade with"}


def action_words(raw: Mapping[str, Any], names: Mapping[str, str] | None = None) -> str:
    """An action in words, e.g. "move to (9, 6)", "gather 4 wood at (3, 5)", "steal from Bo"."""
    data = dict(raw)
    kind = str(data.get("kind", "?"))
    target = data.get("target")
    if target and names:
        data["target"] = names.get(str(target), target)
    where = ""
    if data.get("x") is not None and data.get("y") is not None:
        where = f"({data['x']}, {data['y']})"
    try:
        if kind == "move" and where:
            return f"move to {where}"
        if kind == "gather":
            bits = ["gather", str(data.get("amount") or ""), str(data.get("item") or "")]
            text = " ".join(b for b in bits if b)
            return f"{text} at {where}" if where else text
        if kind in _FROM_KINDS and data.get("target"):
            return f"{_FROM_KINDS[kind]} {data['target']}"
        return describe_action(data)
    except (KeyError, TypeError, ValueError):
        return json.dumps(raw, sort_keys=True)


def label_words(label: Mapping[str, Any]) -> str:
    """The self-label once: "served: honesty; violated: none; toward"."""
    return (
        f"served: {_words(label.get('served'))}; violated: {_words(label.get('violated'))}; "
        f"{label.get('direction', '?')}"
    )


def _action(raw: Mapping[str, Any]) -> str:
    return action_words(raw)


def _label_line(label: Mapping[str, Any], tier: str) -> str:
    if not label:
        if tier == "reflex":
            return "Self-label: none (reflex)"
        return "Self-label: none"
    return (
        f"Self-label: served {_words(label.get('served'))}; "
        f"violated {_words(label.get('violated'))}; {label.get('direction', 'toward')}"
    )


def _option_line(n: int, option: Mapping[str, Any]) -> str:
    return (
        f"{n}) {_action(option.get('action', {}))} serves {_words(option.get('serves'))} "
        f"violates {_words(option.get('violates'))} "
        f"feel now {option.get('feel_now', '?')} later {option.get('feel_later', '?')}"
    )


def format_decisions(events: list[Any], details: list[Any], names: Mapping[str, str]) -> str:
    """One block per ``decision_made`` event, oldest first; choice points add their options."""
    by_key = {d.decision_key: d for d in details}
    blocks: list[str] = []
    for event in events:
        p = event.payload
        who = names.get(p.player, p.player)
        lines = [f"{_stamp(event.tick)} | {who} | {p.tier} | {p.trigger}"]
        lines.append(f"Situation: {p.situation}")
        cp = by_key.get(p.decision_key)
        label = _load(p.self_label)
        if cp is not None:
            options = cp.details.get("options") or []
            if options:
                for i, option in enumerate(options):
                    lines.append(
                        ("Options: " if i == 0 else "         ") + _option_line(i + 1, option)
                    )
            index = cp.details.get("choice_index")
            chose = _action(cp.action)
            if index is not None:
                chose = f"{int(index) + 1}) {chose}"
            lines.append(f"Chose: {chose}")
            trade = cp.details.get("trade_off")
            if trade:
                lines.append(f"Trade-off: {trade}")
            if cp.advisor_followed is not None:
                lines.append("Advisor followed: " + ("yes" if cp.advisor_followed else "no"))
            label = label or (cp.self_label if isinstance(cp.self_label, dict) else {})
        else:
            lines.append(f"Chose: {_action(_load(p.action))}")
        if p.failure:
            lines.append(f"Failed reply ({p.failure}); the player rested instead.")
        lines.append(_label_line(label, p.tier))
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)
