"""The value library and the pure weight maths (repair on day 0, weekly reflection, invention).

Weights are a dict value id -> percent (sums to 100). Dict order is the tie-break order everywhere:
the 14 library values first, then invented values by creation.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from typing import Any

from ai_island.minds.schemas import InventedValue
from ai_island.minds.settings import DEFAULT_SETTINGS, MindSettings

VALUE_IDS: tuple[str, ...] = (
    "friendship", "work", "religion", "family", "respect_others", "respect_self", "honesty",
    "loyalty", "fairness", "generosity", "security", "independence", "power", "curiosity",
)  # fmt: skip

# id -> (display name, definition, often conflicts with); text from docs/design.md.
VALUE_LIBRARY: dict[str, tuple[str, str, str]] = {
    "friendship": ("Friendship", "Building close, trusting bonds with others by choice",
                   "Independence, Power"),
    "work": ("Work", "Valuing effort, skill and productive labour for their own sake",
             "Curiosity, Friendship"),
    "religion": ("Religion", "Belief that unseen forces watch over the island and reward or "
                 "punish actions, expressed through shared rituals, sacred places and moral rules",
                 "Curiosity"),
    "family": ("Family", "Protecting and providing for one's own household and villagers first",
               "Fairness, Generosity"),
    "respect_others": ("Respect for others",
                       "Treating others' dignity, property and choices as mattering", "Power"),
    "respect_self": ("Respect for self",
                     "Refusing to be humiliated, exploited or diminished", "Loyalty, Generosity"),
    "honesty": ("Honesty", "Telling the truth and keeping promises, even at a cost",
                "Family, Security"),
    "loyalty": ("Loyalty", "Standing by allies and commitments even when switching would pay",
                "Fairness, Independence"),
    "fairness": ("Fairness", "Equal rules and fair shares for everyone, rivals included",
                 "Family, Loyalty"),
    "generosity": ("Generosity", "Giving without needing a return", "Security"),
    "security": ("Security", "Avoiding risk and keeping enough stored for bad times",
                 "Generosity, Curiosity"),
    "independence": ("Independence", "Relying on oneself and not being bound to others",
                     "Loyalty, Friendship"),
    "power": ("Power", "Gaining control over land, resources and people",
              "Respect for others, Fairness"),
    "curiosity": ("Curiosity", "Exploring, testing and understanding how the island works",
                  "Security, Religion"),
}  # fmt: skip

TOTAL = 100.0


def value_name(value_id: str) -> str:
    """Display name of a library value; other ids are shown as words."""
    if value_id in VALUE_LIBRARY:
        return VALUE_LIBRARY[value_id][0]
    return value_id.replace("_", " ").capitalize()


def invented_id(name: str) -> str:
    """The id an invented value gets from its name (lower case, words joined by underscores)."""
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def core_ids(weights: Mapping[str, float], count: int = DEFAULT_SETTINGS.core_count) -> list[str]:
    """The top ``count`` ids by weight; ties keep the dict (library, then creation) order."""
    order = {vid: i for i, vid in enumerate(weights)}
    ranked = sorted(weights, key=lambda v: (-weights[v], order[v]))
    return ranked[:count]


# ---- day-0 repair -------------------------------------------------------------------------


def _fallback(settings: MindSettings) -> dict[str, float]:
    n_core = settings.core_count
    bg = (TOTAL - n_core * settings.initial_core_min) / (len(VALUE_IDS) - n_core)
    return {v: (settings.initial_core_min if i < n_core else bg) for i, v in enumerate(VALUE_IDS)}


def _entry(item: Any) -> tuple[Any, Any]:
    if isinstance(item, Mapping):
        return item.get("value_id"), item.get("weight")
    if isinstance(item, tuple | list) and len(item) == 2:
        return item[0], item[1]
    return getattr(item, "value_id", None), getattr(item, "weight", None)


def _project(raw: dict[str, float], core: list[str], s: MindSettings) -> dict[str, float]:
    """w_i = min(upper_i, max(lower_i, lambda * raw_i)) with lambda chosen so the sum is 100."""
    core_set = set(core)

    def total(lam: float) -> tuple[float, dict[str, float]]:
        out: dict[str, float] = {}
        for v in core:
            out[v] = min(s.initial_core_max, max(s.initial_core_min, lam * raw[v]))
        floor_core = min(out[v] for v in core)
        for v in raw:
            if v not in core_set:
                out[v] = min(floor_core, max(s.value_floor, lam * raw[v]))
        return sum(out.values()), out

    lo, hi = 0.0, 1.0
    while total(hi)[0] < TOTAL and hi < 1e12:
        hi *= 2.0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if total(mid)[0] < TOTAL:
            lo = mid
        else:
            hi = mid
    return total((lo + hi) / 2.0)[1]


def repair_initial_weights(
    entries: Iterable[Any], settings: MindSettings = DEFAULT_SETTINGS
) -> tuple[dict[str, float], list[str]]:
    """Turn a (possibly bad) day-0 ranking into valid starting weights, with a problem list.

    ``entries`` hold ``value_id`` and ``weight`` (objects, dicts or pairs). Unknown, duplicate,
    non-finite or negative entries are dropped; missing values are added at weight 1; the top 5
    by weight become core; the weights are projected so core is 10..25, background is at least 1
    and no more than the smallest core value, and the total is 100. Unusable input falls back to
    core 5 by library order.
    """
    return repair_with(entries, settings)


def repair_with(
    entries: Iterable[Any], settings: MindSettings
) -> tuple[dict[str, float], list[str]]:
    problems: list[str] = []
    raw: dict[str, float] = {}
    for item in entries:
        vid, weight = _entry(item)
        if vid not in VALUE_IDS:
            problems.append(f"unknown_value:{vid}")
        elif vid in raw:
            problems.append(f"duplicate_value:{vid}")
        elif (
            isinstance(weight, bool)
            or not isinstance(weight, int | float)
            or not math.isfinite(weight)
            or weight < 0
        ):
            problems.append(f"bad_weight:{vid}")
        else:
            raw[vid] = float(weight)
    if not raw or sum(raw.values()) <= 0:
        return _fallback(settings), [*problems, "unusable_ranking"]
    for vid in VALUE_IDS:
        if vid not in raw:
            raw[vid] = 1.0
            problems.append(f"missing_value:{vid}")
    raw = {v: raw[v] for v in VALUE_IDS}
    core = core_ids(raw, settings.core_count)
    if abs(sum(raw.values()) - TOTAL) > 0.01:
        problems.append("sum_not_100")
    if any(raw[v] < settings.initial_core_min for v in core):
        problems.append("core_below_min")
    if any(raw[v] > settings.initial_core_max for v in core):
        problems.append("core_above_max")
    floor_core = min(raw[v] for v in core)
    for v in raw:
        if v not in core:
            if raw[v] < settings.value_floor:
                problems.append("background_below_floor")
                break
    for v in raw:
        if v not in core and raw[v] > min(floor_core, settings.initial_core_max):
            problems.append("background_above_core")
            break
    if not problems:
        return raw, []
    return _project(raw, core, settings), problems


# ---- weekly reflection -------------------------------------------------------------------


def _rescale(raw: dict[str, float], floor: float) -> dict[str, float]:
    """Find lambda with sum(max(floor, lambda * raw_i)) = 100 and apply it."""
    top = max(raw.values()) if raw else 0.0
    if top <= 0:
        return {v: TOTAL / len(raw) for v in raw}
    lo, hi = 0.0, TOTAL / top
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if sum(max(floor, mid * r) for r in raw.values()) < TOTAL:
            lo = mid
        else:
            hi = mid
    lam = (lo + hi) / 2.0
    return {v: max(floor, lam * r) for v, r in raw.items()}


def reflect(
    weights: Mapping[str, float],
    requested_changes: Mapping[str, float],
    invented: InventedValue | None = None,
    settings: MindSettings = DEFAULT_SETTINGS,
) -> tuple[dict[str, float], dict[str, float], str | None]:
    """Apply a weekly change request.

    Each request is clipped to +/- weekly_delta_limit and added; an (already validated) invented
    value joins at raw weight = its priority; then everything is rescaled so that the total is 100
    with a floor of value_floor per value (floor-locked values stay at the floor).

    Returns ``(new_weights, clipped, invented_status)``: ``clipped`` maps each id whose request was
    cut to the delta actually applied; ``invented_status`` is the new value's id, or None.
    """
    limit = settings.weekly_delta_limit
    raw = {v: float(w) for v, w in weights.items()}
    clipped: dict[str, float] = {}
    for vid, delta in requested_changes.items():
        if vid not in raw or not math.isfinite(delta):
            continue
        applied = max(-limit, min(limit, float(delta)))
        if applied != delta:
            clipped[vid] = applied
        raw[vid] = max(0.0, raw[vid] + applied)
    status: str | None = None
    if invented is not None:
        status = invented_id(invented.name)
        raw[status] = float(invented.priority)
    return _rescale(raw, settings.value_floor), clipped, status


# ---- invented values ---------------------------------------------------------------------


def _has_word(text: str, word: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9]){re.escape(word)}(?![A-Za-z0-9])", text, re.I) is not None


def validate_invented(
    v: InventedValue,
    weights: Mapping[str, float],
    settings: MindSettings = DEFAULT_SETTINGS,
    accepted_this_week: int = 0,
) -> str | None:
    """None when the invented value may join, else the reason it is rejected."""
    if accepted_this_week >= settings.weekly_invention_limit:
        return "weekly invention limit reached"
    text = " ".join([v.name, v.definition, v.observable_behaviour])
    for word in settings.banned_words:
        if _has_word(text, word):
            return f"mentions a banned word: {word}"
    for word in settings.real_world_words:
        if _has_word(text, word):
            return f"mentions the real world: {word}"
    low = text.lower()
    for phrase in settings.ability_phrases:
        if phrase.lower() in low:
            return f"grants an ability: {phrase}"
    new_id = invented_id(v.name)
    if not new_id:
        return "empty name"
    known = {k.lower() for k in weights} | {value_name(k).lower() for k in weights}
    known |= {n.lower() for n, _, _ in VALUE_LIBRARY.values()}
    if new_id in known or v.name.strip().lower() in known:
        return "duplicates an existing value"
    return None
