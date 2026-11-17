"""Weather: equal-length intervals, an independent draw from the season's odds each time."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ai_island.config import SEASONS, WEATHERS, WeatherOdds
from ai_island.storage.events import WeatherChanged
from ai_island.world.clock import season_index_at

if TYPE_CHECKING:
    from ai_island.world.state import World

ORDER_WEATHER = 1


@dataclass(frozen=True)
class WeatherFlags:
    """What the current weather does to the world."""

    stops_outdoor_work: bool
    puts_out_campfires: bool
    water_multiplier: float


class Weather:
    """The current weather and the flags it sets."""

    def __init__(self, multipliers: dict[str, float], current: str = "clear") -> None:
        self._multipliers = multipliers
        self.current = current

    @property
    def flags(self) -> WeatherFlags:
        return WeatherFlags(
            stops_outdoor_work=self.current == "storm",
            puts_out_campfires=self.current in ("rain", "storm"),
            water_multiplier=self._multipliers[self.current],
        )


def draw_weather(rng: random.Random, odds: WeatherOdds) -> str:
    """One draw from a season's odds (clear, rain, storm, drought in that order)."""
    roll = rng.random()
    total = 0.0
    choice = "clear"
    for name in WEATHERS:
        share = getattr(odds, name)
        if share <= 0:
            continue
        total += share
        choice = name
        if roll < total:
            return name
    return choice


def update_weather(world: World, tick: int) -> None:
    """Draw the weather for the interval starting at ``tick`` and schedule the next draw."""
    cfg = world.cfg.world
    season = SEASONS[season_index_at(tick, cfg.clock)]
    new = draw_weather(world.streams.get("weather"), cfg.weather.odds[season])
    previous = world.weather.current
    first = tick == 0
    world.weather.current = new
    if first or new != previous:
        world.emit(WeatherChanged(weather=new, previous=None if first else previous, season=season))
    world.sched.push(tick + cfg.weather.interval_ticks, ORDER_WEATHER, 0, "weather", ())


def run_weather(world: World, tick: int, args: tuple) -> None:
    update_weather(world, tick)
