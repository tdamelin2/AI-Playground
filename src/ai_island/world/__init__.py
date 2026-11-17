"""The island: map, weather, plants, animals, wild dogs (no pygame, no AI)."""

from ai_island.world.animals import population, remove_animal, remove_animals
from ai_island.world.clock import Clock
from ai_island.world.mapgen import generate_world, unclaimed_pool
from ai_island.world.pathfinding import astar
from ai_island.world.plants import remove_plant
from ai_island.world.resources import (
    cut_tree,
    harvest_crop,
    plant_crop,
    take_stone,
    water_output,
)
from ai_island.world.state import World
from ai_island.world.view import (
    EntityView,
    LandmarkView,
    PlayerPanel,
    StructureView,
    WorldFrame,
    frame_from_world,
)

__all__ = [
    "Clock",
    "EntityView",
    "LandmarkView",
    "PlayerPanel",
    "StructureView",
    "World",
    "WorldFrame",
    "astar",
    "cut_tree",
    "frame_from_world",
    "generate_world",
    "harvest_crop",
    "plant_crop",
    "population",
    "remove_animal",
    "remove_animals",
    "remove_plant",
    "take_stone",
    "unclaimed_pool",
    "water_output",
]
