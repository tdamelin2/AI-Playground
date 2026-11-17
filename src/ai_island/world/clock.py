"""Game time. One tick is one game minute.

Tick 0 is year 1, spring, week 1, day 1, 00:00. ``day`` counts days of the year (1..56),
``week`` counts weeks of the year (1..8).
"""

from __future__ import annotations

from dataclasses import dataclass

from ai_island.config import SEASONS, ClockConfig


@dataclass(frozen=True)
class Clock:
    """The game time at one tick."""

    tick: int
    year: int
    season: str
    season_index: int
    week: int
    day: int
    hour: int
    minute: int
    is_night: bool

    @classmethod
    def at(cls, tick: int, cfg: ClockConfig) -> Clock:
        minutes_in_day = tick % cfg.ticks_per_day
        day_index = tick // cfg.ticks_per_day
        days_per_year = cfg.days_per_season * len(SEASONS)
        day_of_year = day_index % days_per_year
        season_index = day_of_year // cfg.days_per_season
        hour = minutes_in_day * 24 // cfg.ticks_per_day
        minute = minutes_in_day * 24 * 60 // cfg.ticks_per_day % 60
        return cls(
            tick=tick,
            year=day_index // days_per_year + 1,
            season=SEASONS[season_index],
            season_index=season_index,
            week=day_of_year // cfg.days_per_week + 1,
            day=day_of_year + 1,
            hour=hour,
            minute=minute,
            is_night=is_night_hour(hour, cfg),
        )

    def format(self) -> str:
        """``Year 1, Spring, week 1, day 1, 00:00``."""
        return (
            f"Year {self.year}, {self.season.capitalize()}, week {self.week}, "
            f"day {self.day}, {self.hour:02d}:{self.minute:02d}"
        )


def is_night_hour(hour: int, cfg: ClockConfig) -> bool:
    """True when ``hour`` falls in the night window from world.toml."""
    start, end = cfg.night_start_hour, cfg.night_end_hour
    if start > end:
        return hour >= start or hour < end
    return start <= hour < end


def season_index_at(tick: int, cfg: ClockConfig) -> int:
    """Index (0..3) of the season at ``tick``."""
    return (tick // cfg.season_ticks) % len(SEASONS)


def is_night_at(tick: int, cfg: ClockConfig) -> bool:
    hour = (tick % cfg.ticks_per_day) * 24 // cfg.ticks_per_day
    return is_night_hour(hour, cfg)


def daylight_at(tick: float, cfg: ClockConfig) -> float:
    """Daylight from 0.0 (dark) to 1.0 (full), for a whole or fractional tick.

    0.0 while it is night; a linear rise over ``dawn_minutes`` after night ends; a linear
    fall over ``dusk_minutes`` before night starts; 1.0 otherwise.
    """
    minutes = (tick % cfg.ticks_per_day) * 1440 / cfg.ticks_per_day
    start = cfg.night_start_hour * 60
    end = cfg.night_end_hour * 60
    if start > end:
        night = minutes >= start or minutes < end
    else:
        night = start <= minutes < end
    if night:
        return 0.0
    since_dawn = (minutes - end) % 1440
    if since_dawn < cfg.dawn_minutes:
        return since_dawn / cfg.dawn_minutes
    until_dusk = (start - minutes) % 1440
    if until_dusk < cfg.dusk_minutes:
        return until_dusk / cfg.dusk_minutes
    return 1.0
