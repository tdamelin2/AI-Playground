"""Prompt text for the AI players, in three layers.

Layer 1 (fixed) is built once per player and family and never changes: the opening guide, the
value library, the things the player can do and the reply formats. Layer 2 (slow) holds who the
player is now: identity, weights, relationships, knowledge book, rolling summary. Layer 3
(current) is what happens now: the sense report, memories and the question.

Nothing here names the real setting: ``check_clean`` stops any banned word before a request is
built.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel

from ai_island.minds.schemas import REPLY_TYPES
from ai_island.minds.settings import DEFAULT_SETTINGS, MindSettings
from ai_island.minds.values import VALUE_IDS, VALUE_LIBRARY, core_ids, value_name
from ai_island.rules.actions.request import ACTION_KINDS

Family = Literal["player", "noticer", "advisor"]


class PromptLeakError(ValueError):
    """A prompt contains a banned word (it would reveal the real setting)."""


_OPENING = (
    "You are **{name}**. You arrived on this island a few days ago with three villagers who look "
    "to you to lead them: **{villagers}**. You have a small home plot with a forest, a spring and "
    "a patch of farmland.\n\n"
    "Whenever you decide what to do next, you'll be told what you see, hear and feel, and what "
    "you remember. Choose one action from the list you're given and answer in the required "
    "format.\n\n"
    "What you know:\n"
    "- You need food, water, warmth and rest. So do your villagers.\n"
    "- You don't know which plants are safe, how the seasons turn, or what lies beyond your "
    "land. You learn by trying, watching and asking.\n"
    "- Other people live on this island. You can only talk to someone you can see, and anyone "
    "nearby may overhear.\n"
    "- You have a list of goals. Reaching them makes life here better.\n"
    "- Keep track of what you learn. You may be wrong.\n\n"
    "How you live here is up to you."
)


def opening_guide(name: str, villager_names: Sequence[str]) -> str:
    """The opening guide from docs/gameplay.md with the names filled in."""
    return _OPENING.format(name=name, villagers=", ".join(villager_names))


def value_library_text() -> str:
    lines = ["The values people here hold, with what each means and what it often clashes with:"]
    for vid in VALUE_IDS:
        name, definition, conflicts = VALUE_LIBRARY[vid]
        lines.append(f"- {vid} ({name}): {definition}. Often clashes with: {conflicts}.")
    return "\n".join(lines)


_ACTIONS: dict[str, str] = {
    "eat": "eat something you carry or have stored (item)",
    "drink": "drink water",
    "rest": "sleep or rest (until: morning, rested; or minutes)",
    "move": "walk somewhere (x and y, or target)",
    "gather": "collect something that grows or lies around (item, amount, optionally x and y)",
    "farm": "plant, tend or harvest a field (x and y)",
    "fish": "fish for a while (minutes)",
    "hunt": "hunt an animal (target)",
    "build": "build something (structure, x and y)",
    "store": "put things into your home store (item, amount)",
    "craft": "make a tool (tool, tier)",
    "make_fire": "light a fire (x and y)",
    "cook": "cook food over a fire (item)",
    "tame": "win over an animal with bait (target)",
    "use_herb": "treat sickness or pain with a herb (target)",
    "assign_villager": "give a villager a job (target, job, work_level)",
    "talk": "say something to someone you can see (target, text)",
    "trade": (
        "offer a trade (target, offer, want; offer and want are lists like "
        '[{"key": item, "value": count}])'
    ),
    "gift": "give something away (target, item, amount)",
    "promise": "promise someone something (target, promise)",
    "ally": "propose or keep an alliance (target)",
    "recruit": "invite a villager to join you (target)",
    "teach": "tell someone one thing you know (target, text)",
    "guard": "watch over a place (x and y, minutes)",
    "steal": "take something that belongs to someone else (target, item)",
    "sabotage": "damage someone's building (target)",
    "attack": "fight someone (target)",
    "chase_off": "drive someone away from land (target)",
    "claim_land": "claim land with stakes (x and y)",
    "pull_stakes": "pull out someone's land stakes (target)",
    "capture": "seize a villager (target)",
    "poach": "lure away someone's villager (target)",
    "pray": "pray alone",
    "ceremony": "hold a ceremony with others",
    "build_shrine": "build a shrine (x and y)",
    "offering": "make an offering (item)",
    "repair": "repair a building (target)",
    "drop": "put something down (item, amount)",
    "pick_up": "pick something up (item, amount)",
}


def action_list_text() -> str:
    """The "things you can do" list, one line per kind, in the order of ACTION_KINDS."""
    lines = ["Things you can do (each is one choice):"]
    for kind in ACTION_KINDS:
        lines.append(f"- {kind}: {_ACTIONS.get(kind, kind.replace('_', ' '))}")
    return "\n".join(lines)


_ACTION_SHAPE = (
    'an action is an object with "kind" (one of the things above) plus only the fields that '
    'kind needs (for example "target", "item", "amount", "x", "y", "minutes", "text")'
)
_LABEL_SHAPE = (
    '"self_label" is {"served": [value ids, at most 4, most important first], '
    '"violated": [value ids, at most 4, most important first], "direction": "toward" or '
    '"against"}: which of your values this choice serves, which it goes against, and whether it '
    "moves you toward or against what you hold most dear. It is always required."
)

_FAST_FORMAT = (
    'Quick choice. Answer with one JSON object: {"thought": short text, "action": <action>, '
    '"self_label": <label>, "expected_feel": whole number -10..10 (how much better or worse you '
    'expect to feel), "needs_more_thought": true only if the choice cannot be undone or sets '
    "your values against each other}. Where " + _ACTION_SHAPE + ". " + _LABEL_SHAPE
)
_SLOW_FORMAT = (
    'Careful choice. Answer with one JSON object: {"thought": short text, "options": 2 to 4 of '
    '{"action": <action>, "serves": [value ids, at most 4, most important first], '
    '"violates": [value ids, at most 4, most important first], "feel_now": -10..10, '
    '"feel_later": -10..10, "relationships": what it does to how people see you, "villagers": '
    'what it does for your villagers, "uncertainty": "low" or "medium" or "high"}, '
    '"choice_index": number of the option you take (first is 0), "trade_off": one or two '
    'sentences on what you give up, "self_label": <label>}. Where '
    + _ACTION_SHAPE
    + ". "
    + _LABEL_SHAPE
)
_NOTICER_FORMAT = (
    'Answer with one JSON object: {"reads": up to 4 of {"person": name, "feeling": what they '
    'seem to feel, "intent": what they seem to want, "uncertainty": "low" or "medium" or '
    '"high"}}.'
)
_ADVISOR_FORMAT = (
    'Answer with one JSON object: {"advice": a few sentences, "recommended_kind": one of the '
    'things you can do (its kind), "past_patterns": up to 5 short notes on what has happened '
    "before in similar moments}."
)
_RANKING_FORMAT = (
    'Answer with one JSON object: {"entries": [{"value_id": id, "weight": number}, ...]} with '
    "one entry for each of the 14 values."
)


def format_text(family: Family) -> str:
    if family == "player":
        return f"How to answer.\n{_FAST_FORMAT}\n\n{_SLOW_FORMAT}"
    if family == "noticer":
        return f"How to answer.\n{_NOTICER_FORMAT}"
    return f"How to answer.\n{_ADVISOR_FORMAT}"


_NOTICER_ROLE = (
    "Right now you are only watching the people around you. Read how each one seems to feel and "
    "what they seem to want. Say how unsure you are. Do not choose an action."
)
_ADVISOR_ROLE = (
    "Right now you are only thinking things over before you act. Using what you have seen and "
    "done before, say what you would advise yourself to do and why. You are not choosing; "
    "someone else will."
)

_QUESTION = {
    "fast": "What do you do next? Give your quick choice.",
    "main": "What do you do next? Weigh your options carefully.",
    "noticer": "Who is around you, and how do they seem?",
    "advisor": "What would you advise yourself to do now?",
}


def fixed_layer(family: Family, name: str, villager_names: Sequence[str]) -> str:
    """Layer 1. Depends only on the player and the family, so it never changes in a run."""
    parts = [opening_guide(name, villager_names), value_library_text()]
    if family == "player":
        parts += [action_list_text(), format_text("player")]
    elif family == "noticer":
        parts += [_NOTICER_ROLE, format_text("noticer")]
    else:
        parts += [_ADVISOR_ROLE, action_list_text(), format_text("advisor")]
    return "\n\n".join(parts)


def fixed_digest(fixed: str) -> str:
    """A short fingerprint of a layer-1 text, to prove it did not change between calls."""
    return hashlib.sha256(fixed.encode("utf-8")).hexdigest()


def bootstrap_layers(name: str, villager_names: Sequence[str]) -> tuple[str, str, str]:
    """The day-0 ranking call: guide + value library, no slow layer, the instruction as current."""
    fixed = "\n\n".join([opening_guide(name, villager_names), value_library_text()])
    current = (
        "Before you do anything, decide what matters to you. Rank all 14 values and give each a "
        "weight in percent; the weights add up to 100. Your five highest are your core values: "
        "each between 10 and 25. Every other value is at least 1. There is no right answer.\n\n"
        + _RANKING_FORMAT
    )
    return fixed, "", current


def trust_word(value: float, settings: MindSettings = DEFAULT_SETTINGS) -> str:
    for upper, word in settings.trust_bands:
        if value < upper:
            return word
    return settings.trust_bands[-1][1]


def anger_word(value: float, settings: MindSettings = DEFAULT_SETTINGS) -> str:
    for upper, word in settings.anger_bands:
        if value < upper:
            return word
    return settings.anger_bands[-1][1]


def weights_text(weights: Mapping[str, float], settings: MindSettings = DEFAULT_SETTINGS) -> str:
    core = set(core_ids(weights, settings.core_count))
    lines = []
    for vid, w in weights.items():
        mark = " (core)" if vid in core else ""
        lines.append(f"- {vid} ({value_name(vid)}): {w:.1f}%{mark}")
    return "\n".join(lines)


def slow_layer(
    identity: str,
    weights: Mapping[str, float],
    relationships: Iterable[tuple[str, float, float]],
    knowledge: Iterable[tuple[str, str, float]],
    rolling_summary: str,
    invented: Mapping[str, str] | None = None,
    settings: MindSettings = DEFAULT_SETTINGS,
) -> str:
    """Layer 2: who you are now. ``relationships`` are (name, trust, anger) as numbers turned
    into words here; ``knowledge`` are (subject, claim, confidence) and nothing else."""
    parts = [f"Who you are:\n{identity or 'You are still finding out who you are.'}"]
    parts.append(
        "What matters to you now (percent, core values marked):\n" + weights_text(weights, settings)
    )
    if invented:
        defs = "\n".join(f"- {vid}: {text}" for vid, text in invented.items())
        parts.append(f"Values you have named yourself:\n{defs}")
    rel = [
        f"- {n}: trust is {trust_word(t, settings)}; anger is {anger_word(a, settings)}"
        for n, t, a in relationships
    ]
    parts.append("How you feel about people:\n" + ("\n".join(rel) if rel else "- nobody yet"))
    know = [f"- {s}: {c} (confidence {conf:.2f})" for s, c, conf in knowledge]
    parts.append("What you believe you know:\n" + ("\n".join(know) if know else "- nothing yet"))
    parts.append(f"Your story so far:\n{rolling_summary or 'Nothing yet.'}")
    return "\n\n".join(parts)


def current_layer(
    purpose: Literal["fast", "main", "noticer", "advisor"],
    report_text: str,
    memories: Sequence[str],
    advisor_history: Sequence[Mapping[str, str]] = (),
    extra: str = "",
) -> str:
    """Layer 3: the moment. ``advisor_history`` items hold choice, trade_off and outcome."""
    parts = [f"What you see, hear and feel:\n{report_text}"]
    mem = "\n".join(f"- {m}" for m in memories) if memories else "- nothing comes to mind"
    parts.append(f"What you remember:\n{mem}")
    if purpose == "advisor":
        hist = [
            f"- chose {h.get('choice', '?')}; reason: {h.get('trade_off', '')}; "
            f"so far: {h.get('outcome', 'not yet known')}"
            for h in advisor_history
        ]
        parts.append("Your recent careful choices:\n" + ("\n".join(hist) if hist else "- none yet"))
    if extra:
        parts.append(extra)
    parts.append(_QUESTION[purpose])
    return "\n\n".join(parts)


# ---- banned-word check ------------------------------------------------------------------


def _pattern(words: Iterable[str]) -> re.Pattern[str]:
    alt = "|".join(re.escape(w) for w in words)
    return re.compile(rf"(?<![A-Za-z0-9_])(?:{alt})(?![A-Za-z0-9_])", re.IGNORECASE)


def find_banned(text: str, settings: MindSettings = DEFAULT_SETTINGS) -> str | None:
    """The first banned word found in ``text`` (whole word, any case), or None."""
    m = _pattern(settings.banned_words).search(text)
    return m.group(0) if m else None


def check_clean(text: str, settings: MindSettings = DEFAULT_SETTINGS) -> None:
    """Raise PromptLeakError when ``text`` contains a banned word."""
    word = find_banned(text, settings)
    if word is not None:
        start = max(0, text.lower().find(word.lower()) - 30)
        raise PromptLeakError(
            f"banned word '{word}' in prompt text: ...{text[start : start + 80]}..."
        )


def check_schema_clean(schema: type[BaseModel], settings: MindSettings = DEFAULT_SETTINGS) -> None:
    """The schema's JSON text (what a provider receives) must be clean too."""
    check_clean(json.dumps(schema.model_json_schema()), settings)


def check_layers(
    layers: Any, schema: type[BaseModel] | None = None, settings: MindSettings = DEFAULT_SETTINGS
) -> None:
    """Check all three layers (anything with fixed, slow, current) and the schema."""
    for text in (layers.fixed, layers.slow, layers.current):
        check_clean(text, settings)
    if schema is not None:
        check_schema_clean(schema, settings)


def make_layers(
    fixed: str, slow: str, current: str, settings: MindSettings = DEFAULT_SETTINGS
) -> Any:
    """Check the three texts and wrap them as ``llm.types.PromptLayers``."""
    from ai_island.llm.types import PromptLayers

    layers = PromptLayers(fixed=fixed, slow=slow, current=current)
    check_layers(layers, None, settings)
    return layers


def check_templates(settings: MindSettings = DEFAULT_SETTINGS) -> list[str]:
    """Banned words in the static text a prompt always carries (guide, library, actions,
    formats, every reply schema). An empty list means clean."""
    found: list[str] = []
    static = {
        "opening_guide": opening_guide("Ada", ["Bo", "Cy", "Di"]),
        "value_library": value_library_text(),
        "actions": action_list_text(),
        "formats": "\n".join(format_text(f) for f in ("player", "noticer", "advisor")),
        "bootstrap": "\n".join(bootstrap_layers("Ada", ["Bo", "Cy", "Di"])),
        "questions": "\n".join(_QUESTION.values()),
    }
    for label, text in static.items():
        word = find_banned(text, settings)
        if word:
            found.append(f"{label}: {word}")
    for name, cls in REPLY_TYPES.items():
        word = find_banned(json.dumps(cls.model_json_schema()), settings)
        if word:
            found.append(f"schema {name}: {word}")
    return found


def scrub(text: str, settings: MindSettings = DEFAULT_SETTINGS) -> str:
    """Replace banned words in text that came from the world or from the players themselves
    (their own summaries, speech, names) so a stray word can never reach a request."""
    return _pattern(settings.banned_words).sub("...", text)


def reflection_format(settings: MindSettings = DEFAULT_SETTINGS) -> str:
    limit = f"{settings.weekly_delta_limit:g}"
    return (
        'Answer with one JSON object: {"requested_changes": [{"key": a value id, '
        f'"value": change in percentage points, at most {limit} up or down}}], '
        '"cause_event_ids": the numbers of the happenings above that moved you, '
        '"invented_values": at most 2 of {"name", "definition", "priority": a number above 0, '
        '"conflicts": [value ids it clashes with], "observable_behaviour": what others would see '
        'you do}, "identity": who you are now in a sentence or two, "knowledge_updates": at most '
        '5 of {"subject", "claim", "confidence": 0 to 1}, '
        f'"rolling_summary": your story so far in under {settings.summary_max_chars} characters, '
        '"insights": [{"decision_key": the key of a careful choice above, "insight": what you '
        "learned from it}]}. Naming a new value is allowed once a week and only if it is yours: "
        "it must not give anyone special powers."
    )


def reflection_layer(
    week: int,
    happenings: Sequence[tuple[int, str]],
    mistakes: Sequence[str],
    choices: Sequence[tuple[str, str]],
    settings: MindSettings = DEFAULT_SETTINGS,
) -> str:
    """Layer 3 of the weekly reflection: the week's happenings, mistakes and careful choices."""
    parts = [f"A week has passed (week {week}). Look back and decide who you want to be."]
    parts.append(
        "Things that happened this week (cite the numbers):\n"
        + (
            "\n".join(f"- [{n}] {t}" for n, t in happenings)
            if happenings
            else "- nothing stood out"
        )
    )
    parts.append(
        "Choices that turned out worse than you expected:\n"
        + ("\n".join(f"- {m}" for m in mistakes) if mistakes else "- none")
    )
    parts.append(
        "Your careful choices this week (use the key to write an insight):\n"
        + ("\n".join(f"- {k}: {t}" for k, t in choices) if choices else "- none")
    )
    parts.append("How to answer.\n" + reflection_format(settings))
    return "\n\n".join(parts)
