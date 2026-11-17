"""Wild plants: seven kinds, each present only in its configured seasons."""

from __future__ import annotations

from ai_island.config import SEASONS
from ai_island.storage.events import PlantRegrown, PlantRemoved
from ai_island.world.clock import season_index_at
from ai_island.world.state import Pos, World

ORDER_PLANTS = 4


def remove_plant(world: World, pos: Pos, tick: int) -> bool:
    """Pick the plant at ``pos``; it grows back after its configured time (in season)."""
    for site in world.plants:
        if site.present and (site.x, site.y) == pos:
            site.present = False
            site.regrow_due = tick + world.cfg.balance.plants[site.kind].regrow_ticks
            world.emit(PlantRemoved(plant_id=site.id, kind=site.kind, x=site.x, y=site.y), tick)
            world.sched.push(site.regrow_due, ORDER_PLANTS, site.id, "plant_regrow", (site.id,))
            return True
    return False


def run_plant_regrow(world: World, tick: int, args: tuple) -> None:
    (plant_id,) = args
    for site in world.plants:
        if site.id == plant_id:
            if site.regrow_due != tick:
                return  # stale timer
            site.regrow_due = None
            season = SEASONS[season_index_at(tick, world.cfg.world.clock)]
            if season in world.cfg.world.plants[site.kind].seasons:
                site.present = True
                world.emit(PlantRegrown(plant_id=site.id, kind=site.kind, x=site.x, y=site.y), tick)
            return


def on_season(world: World, season: str) -> None:
    """At a season change, plants out of season vanish and in-season ones appear."""
    for site in world.plants:
        in_season = season in world.cfg.world.plants[site.kind].seasons
        if not in_season:
            site.present = False
            site.regrow_due = None
        elif site.regrow_due is None:
            site.present = True


def apply_initial_season(world: World) -> None:
    """Hide plants that are not in season at tick 0 (spring)."""
    on_season(world, SEASONS[season_index_at(0, world.cfg.world.clock)])


def schedule_initial(world: World) -> None:
    apply_initial_season(world)
