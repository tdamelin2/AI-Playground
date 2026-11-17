"""A small hand-made island for one-test-per-action checks (AC-11).

``build_example_world`` returns a 24 x 24 world with every terrain kind, a spring, farmland in
every state, rocky and quarry tiles, a lake with fish, each plant kind, one of each animal, one
dog pack, two players standing next to each other and their villagers. Weather stays clear and
no controller runs; tests drive the world through ``rules.actions``.
"""

from __future__ import annotations

from ai_island.config import ANIMAL_KINDS, PLANT_KINDS, GameConfig
from ai_island.rng import Streams
from ai_island.storage.events import WorldCreated
from ai_island.world import animals as animals_mod
from ai_island.world import dogs as dogs_mod
from ai_island.world import engine as engine_mod
from ai_island.world import movement as movement_mod
from ai_island.world.agents import Player
from ai_island.world.people import _new_villager
from ai_island.world.state import Animal, Dog, Home, Landmark, PlantSite, World


def build_example_world(cfg: GameConfig, seed: int, size: int = 24) -> World:
    streams = Streams(seed)
    world = World(cfg, streams)
    world.width = world.height = size
    world.terrain = [["grass"] * size for _ in range(size)]
    for y in range(size):
        for x in range(size):
            d = min(x, y, size - 1 - x, size - 1 - y)
            if d == 0:
                world.terrain[y][x] = "coast"
            elif d == 1:
                world.terrain[y][x] = "sand"
    t = world.terrain
    # two home plots: a big one and a small one right next to it
    world.homes = [Home(0, 3, 3, 10, 0, (8, 8)), Home(1, 13, 3, 4, 1, (14, 4))]
    world.zone_grid = [["buffer"] * size for _ in range(size)]
    for home in world.homes:
        for y in range(home.y, home.y + home.size):
            for x in range(home.x, home.x + home.size):
                world.zone_grid[y][x] = home.zone
    world.zones = [h.zone for h in world.homes] + ["buffer"]
    t[5][5] = "spring"
    for x, state in zip(range(6, 9), ("farmland_empty",) * 3, strict=True):
        t[8][x] = state
    t[9][6], t[9][7], t[9][8] = "farmland_ready", "farmland_planted", "farmland_growing"
    t[10][14] = "farmland_failed"
    for x, y in ((10, 4), (11, 4), (10, 5), (11, 5)):
        t[y][x] = "tree"
    t[6][9] = "stump"
    t[10][4] = "rocky"
    world.stone = {(4, 10): cfg.balance.stone.rocky_stone}
    t[11][4] = "rocky_depleted"
    for yy in range(4, 7):
        for xx in range(19, 22):
            t[yy][xx] = "quarry"
            world.stone[(xx, yy)] = cfg.balance.stone.quarry_stone
    t[7][21] = "quarry_depleted"
    for yy in range(15, 19):
        for xx in range(15, 19):
            if (xx, yy) not in ((15, 15), (18, 15), (15, 18), (18, 18)):
                t[yy][xx] = "lake"
    world.landmarks = [
        Landmark("quarry", 20, 5),
        Landmark("lake_dock", 14, 16),
        Landmark("great_tree", 12, 14),
    ]
    # plants: every kind once at home and once in the open
    free_home = [(4, 4), (5, 4), (6, 4), (4, 6), (5, 6), (6, 6), (7, 6)]
    free_open = [(14, 12), (15, 12), (16, 12), (17, 12), (18, 12), (19, 12), (20, 12)]
    for i, kind in enumerate(PLANT_KINDS):
        for pos in (free_home[i], free_open[i]):
            world.plants.append(PlantSite(world.new_id(), kind, pos[0], pos[1], True, None))
    # animals: one of each, on terrain they accept
    spots = {
        "rabbit": (15, 10), "deer": (16, 10), "boar": (17, 10), "bird": (18, 10),
        "nest_eggs": (19, 10), "goat": (20, 10), "chicken": (21, 10), "fish": (16, 16),
    }  # fmt: skip
    for kind in ANIMAL_KINDS:
        x, y = spots[kind]
        zone = world.zone_grid[y][x]
        world.animals[kind].append(Animal(world.new_id(), kind, x, y, zone))
    world.tree_initial = {z: 0 for z in world.zones}
    for y in range(size):
        for x in range(size):
            if t[y][x] == "tree":
                world.tree_initial[world.zone_at(x, y)] += 1
    world.trees_alive = dict(world.tree_initial)
    # one dog pack of two
    pack = world.next_pack
    world.next_pack += 1
    for _ in range(2):
        world.dogs.append(Dog(world.new_id(), pack, 21, 20))
    world.unclaimed = [
        (x, y)
        for y in range(size)
        for x in range(size)
        if world.zone_grid[y][x] == "buffer" and world.passable(x, y)
        and not any((x, y) == (m.x, m.y) for m in world.landmarks)
    ]  # fmt: skip
    # two players side by side, three villagers each, two wanderers
    names = cfg.balance.turn.player_dummy_names
    for index, pos in ((1, (8, 8)), (2, (9, 8))):
        pid = f"player_{index}"
        p = Player(pid, index, names[index - 1], pos[0], pos[1])
        p.inventory = world.new_inventory()
        p.home_store = world.new_inventory()
        p.slots = cfg.balance.tasks.slots_start
        world.players[pid] = p
    for p in world.players.values():
        for other in world.players:
            if other != p.id:
                p.trust[other] = cfg.balance.wellbeing.start_trust
                p.anger[other] = cfg.balance.wellbeing.anger_neutral
    counter = 0
    for pid, base in (("player_1", (7, 7)), ("player_2", (10, 7))):
        for i in range(3):
            _new_villager(world, counter, pid, (base[0] + i % 2, base[1] + i // 2))
            counter += 1
    for pos in ((13, 12), (14, 13)):
        _new_villager(world, counter, None, pos)
        counter += 1
    for mover in movement_mod.moving_entities(world):
        movement_mod.register(world, mover, 0)
    world.emit(WorldCreated(seed=seed, width=size, height=size))
    engine_mod.schedule_core(world)
    animals_mod.schedule_initial(world)
    dogs_mod.schedule_initial(world)
    movement_mod.schedule_initial(world)
    engine_mod.schedule_turn(world)
    world.controller_kind = "none"
    return world
