"""The scheduler dispatch: seasons, the daily summary and every timed subsystem."""

from __future__ import annotations

from collections.abc import Callable

from ai_island.config import ANIMAL_KINDS, PLANT_KINDS, SEASONS
from ai_island.storage.events import DaySummary, SeasonChanged
from ai_island.world import animals, dogs, movement, plants, resources, weather
from ai_island.world.clock import Clock, season_index_at
from ai_island.world.state import World

ORDER_SEASON = 0
ORDER_TURN = 8  # after ecology and movement, before the day summary
ORDER_SUMMARY = 9

Handler = Callable[[World, int, tuple], None]


def run_season(world: World, tick: int, args: tuple) -> None:
    clock = world.cfg.world.clock
    season = SEASONS[season_index_at(tick, clock)]
    year = tick // clock.year_ticks + 1
    world.emit(SeasonChanged(season=season, year=year), tick)
    plants.on_season(world, season)
    animals.on_season(world, season, tick)
    world.sched.push(tick + clock.season_ticks, ORDER_SEASON, 0, "season", ())


def run_summary(world: World, tick: int, args: tuple) -> None:
    clock = Clock.at(tick, world.cfg.world.clock)
    farmland: dict[str, int] = {}
    for row in world.terrain:
        for t in row:
            if t.startswith("farmland_"):
                farmland[t] = farmland.get(t, 0) + 1
    world.emit(
        DaySummary(
            year=clock.year,
            day=clock.day,
            season=clock.season,
            weather=world.weather.current,
            animals={k: len(world.animals[k]) for k in ANIMAL_KINDS},
            plants={
                k: sum(1 for p in world.plants if p.present and p.kind == k) for k in PLANT_KINDS
            },
            trees=dict(world.trees_alive),
            dogs=len(world.dogs),
            farmland=dict(sorted(farmland.items())),
        ),
        tick,
    )
    world.sched.push(
        tick + world.cfg.balance.summary_interval_ticks, ORDER_SUMMARY, 0, "summary", ()
    )


def run_turn_job(world: World, tick: int, args: tuple) -> None:
    """The recurring per-minute turn for people. Simulation sets `world.turn_handler`."""
    world.sched.push(tick + 1, ORDER_TURN, 0, "turn", ())
    handler = world.turn_handler
    if handler is not None:
        handler(world, tick)
        return
    from ai_island.rules.turn import run_turn

    run_turn(world, tick, None)


def schedule_turn(world: World) -> None:
    """Start the per-minute turn (only worlds with people have one)."""
    world.sched.push(world.tick + 1, ORDER_TURN, 0, "turn", ())


HANDLERS: dict[str, Handler] = {
    "turn": run_turn_job,
    "season": run_season,
    "summary": run_summary,
    "weather": weather.run_weather,
    "tree_regrow": resources.run_tree_regrow,
    "crop": resources.run_crop,
    "plant_regrow": plants.run_plant_regrow,
    "movement": movement.run_movement,
    "animals_breed": animals.run_animals_breed,
    "dogs_breed": dogs.run_dogs_breed,
}


def schedule_core(world: World) -> None:
    """Schedule the first season change and the first day summary."""
    clock = world.cfg.world.clock
    world.sched.push(clock.season_ticks, ORDER_SEASON, 0, "season", ())
    world.sched.push(world.cfg.balance.summary_interval_ticks, ORDER_SUMMARY, 0, "summary", ())


def advance_to(world: World, end_tick: int) -> None:
    """Run all work due up to and including ``end_tick``, then set the clock to it."""
    sched = world.sched
    heap = sched.heap
    while heap and heap[0][0] <= end_tick:
        due, _order, _ident, _seq, kind, args = sched.pop()
        world.tick = due
        HANDLERS[kind](world, due, args)
    world.tick = end_tick
