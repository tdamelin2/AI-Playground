"""The reflex tier: a player whose body is in urgent need acts by code, with no AI call.

``reflex_action`` is pure (it changes nothing); the controller remembers a fire back-off itself.
It only ever answers an urgent need (level at or above ``urgent_levels``); when no action can be
built (no water in sight, no food to eat) it returns None and the router falls through.
"""

from __future__ import annotations

import random
from typing import Any

from ai_island.minds.dummy import FIRE_RETRY, FOOD_ORDER, WOOD_FETCH, DummyController
from ai_island.minds.settings import DEFAULT_SETTINGS, MindSettings
from ai_island.rules.actions.request import ActionRequest

_HELPER = DummyController("reflex", random.Random(0))  # its fetch helpers never use the rng
NEED_ORDER: tuple[str, ...] = ("fatigue", "thirst", "hunger", "cold")


def urgent_needs(report: Any, settings: MindSettings = DEFAULT_SETTINGS) -> list[str]:
    needs = getattr(report, "needs", None) or {}
    return [n for n in NEED_ORDER if needs.get(n, 0) >= settings.urgent_levels.get(n, 99)]


def reflex_action(
    ctx: Any, report: Any, settings: MindSettings = DEFAULT_SETTINGS, fire_after: int = 0
) -> ActionRequest | None:
    """The action that answers the most pressing urgent need, or None."""
    urgent = urgent_needs(report, settings)
    carried = report.carried
    for need in urgent:
        if need == "fatigue":
            return ActionRequest(kind="rest", until="rested")
        if need == "thirst":
            if carried.get("water", 0) > 0:
                return ActionRequest(kind="drink", item="water", amount=min(3, carried["water"]))
            water = _HELPER._fetch_water(report)
            if water is not None:
                return water
        elif need == "hunger":
            food = next((k for k in FOOD_ORDER if carried.get(k, 0) > 0), None)
            if food is not None:
                return ActionRequest(kind="eat", item=food, until="sated")
            fetch = _HELPER._fetch_food(report)
            if fetch is not None:
                return fetch
        elif need == "cold":
            fire = _HELPER._near(report, ("structure",), {"a campfire": "", "a hearth": ""})
            if fire is not None and ctx.tick < fire_after:
                here = report.position
                if max(abs(fire.x - here[0]), abs(fire.y - here[1])) > 1:
                    return ActionRequest(kind="move", x=fire.x, y=fire.y)
                return ActionRequest(kind="rest", minutes=30)
            if carried.get("wood", 0) > 0 and ctx.tick >= fire_after:
                return ActionRequest(kind="make_fire", x=report.position[0], y=report.position[1])
            tree = _HELPER._near(report, ("terrain",), {"a tree": ""})
            if tree is not None and carried.get("wood", 0) < WOOD_FETCH:
                return ActionRequest(
                    kind="gather", item="wood", x=tree.x, y=tree.y, amount=WOOD_FETCH
                )
    return None


__all__ = ["FIRE_RETRY", "NEED_ORDER", "reflex_action", "urgent_needs"]
