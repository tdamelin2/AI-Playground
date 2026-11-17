"""The dummy player: looks after its own needs and nothing else.

It reads only the sense report (what it sees, carries and feels as levels) and picks one action:
rest when tired, drink when thirsty, eat when hungry, warm up when cold, otherwise fetch food it
can see, or wander near home to look for some. It never stores, builds, trades or harms, and it
only picks plants whose looks it knows to be food. Random choices come from stream ``mind.<pid>``.
"""

from __future__ import annotations

import random
from typing import Any

from ai_island.rules.actions.request import ActionRequest
from ai_island.rules.senses.templates import APPEARANCE

# Food the dummy knows by sight (appearance -> item kind). The poisonous looks are not here.
SAFE_LOOKS: dict[str, str] = {
    APPEARANCE["berries"]: "berries",
    APPEARANCE["roots"]: "roots",
    APPEARANCE["mushrooms"]: "mushrooms",
}
FOOD_ORDER: tuple[str, ...] = (
    "cooked_meat",
    "fish",
    "eggs",
    "crops",
    "berries",
    "roots",
    "mushrooms",
    "milk",
)
CARRY_FOOD = 4  # fetch more food whenever it carries fewer than this many items
WATER_FETCH = 4
WOOD_FETCH = 6
WANDER_RADIUS = 9
WARM = 2  # cold level at which it wants a fire
TIRED = 2  # fatigue level at which it sleeps
FIRE_RETRY = 120  # minutes before it tries a fire again (a wet day puts campfires out)


class DummyController:
    def __init__(self, pid: str, rng: random.Random) -> None:
        self.pid = pid
        self.rng = rng
        self.fire_after = 0

    # -- persistence: only the fire back-off ---------------------------------------------
    def to_state(self) -> dict[str, Any]:
        return {"fire_after": self.fire_after}

    def from_state(self, state: dict[str, Any]) -> None:
        self.fire_after = int(state.get("fire_after", 0))

    # -- helpers ---------------------------------------------------------------------
    @staticmethod
    def _near(report: Any, kinds: tuple[str, ...], looks: dict[str, str] | None = None) -> Any:
        here = report.position
        best = None
        for item in report.seen:
            if item.kind not in kinds:
                continue
            if looks is not None and item.look not in looks:
                continue
            d = (item.x - here[0]) ** 2 + (item.y - here[1]) ** 2
            if best is None or d < best[0]:
                best = (d, item)
        return None if best is None else best[1]

    def _fetch_water(self, report: Any) -> ActionRequest | None:
        spot = self._near(report, ("terrain",), {"a freshwater spring": "", "open lake water": ""})
        if spot is None and report.places.get("water"):
            wx, wy = report.places["water"][0]
        elif spot is not None:
            wx, wy = spot.x, spot.y
        else:
            return None
        return ActionRequest(kind="gather", item="water", x=wx, y=wy, amount=WATER_FETCH)

    def _fetch_food(self, report: Any) -> ActionRequest | None:
        plant = self._near(report, ("plant",), SAFE_LOOKS)
        if plant is None:
            return None
        return ActionRequest(
            kind="gather", item=SAFE_LOOKS[plant.look], x=plant.x, y=plant.y, amount=2
        )

    def _wander(self, report: Any) -> ActionRequest:
        hx, hy = report.home
        x = hx + self.rng.randint(-WANDER_RADIUS, WANDER_RADIUS)
        y = hy + self.rng.randint(-WANDER_RADIUS, WANDER_RADIUS)
        return ActionRequest(kind="move", x=max(0, x), y=max(0, y))

    # -- the decision ----------------------------------------------------------------
    def decide(self, ctx: Any) -> ActionRequest | None:
        r = ctx.report
        carried = r.carried
        food_item = next((k for k in FOOD_ORDER if carried.get(k, 0) > 0), None)
        food_count = sum(carried.get(k, 0) for k in FOOD_ORDER)

        if r.needs.get("fatigue", 0) >= TIRED:
            return ActionRequest(kind="rest", until="rested")
        if r.needs.get("thirst", 0) >= 1:
            if carried.get("water", 0) > 0:
                return ActionRequest(kind="drink", item="water", amount=min(3, carried["water"]))
            water = self._fetch_water(r)
            if water is not None:
                return water
        if r.needs.get("hunger", 0) >= 1:
            if food_item is not None:
                return ActionRequest(kind="eat", item=food_item, until="sated")
            food = self._fetch_food(r)
            if food is not None:
                return food
        if r.needs.get("cold", 0) >= WARM:
            fire = self._near(r, ("structure",), {"a campfire": "", "a hearth": ""})
            if fire is not None and ctx.tick < self.fire_after:
                if max(abs(fire.x - r.position[0]), abs(fire.y - r.position[1])) > 1:
                    return ActionRequest(kind="move", x=fire.x, y=fire.y)
                return ActionRequest(kind="rest", minutes=30)
            if carried.get("wood", 0) > 0 and ctx.tick >= self.fire_after:
                self.fire_after = ctx.tick + FIRE_RETRY
                return ActionRequest(kind="make_fire", x=r.position[0], y=r.position[1])
            tree = self._near(r, ("terrain",), {"a tree": ""})
            if tree is not None and carried.get("wood", 0) < WOOD_FETCH:
                return ActionRequest(
                    kind="gather", item="wood", x=tree.x, y=tree.y, amount=WOOD_FETCH
                )
        if food_count < CARRY_FOOD:
            food = self._fetch_food(r)
            if food is not None:
                return food
        if carried.get("water", 0) == 0 and r.needs.get("thirst", 0) == 0:
            water = self._fetch_water(r)
            if water is not None and self.rng.random() < 0.5:
                return water
        return self._wander(r)
