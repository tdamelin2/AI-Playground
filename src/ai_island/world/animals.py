"""Wild animals: seasonal breeding with capacities, and local
extinction with a recolonisation delay."""

from __future__ import annotations

from ai_island.config import ANIMAL_KINDS, SEASONS
from ai_island.storage.events import (
    AnimalsBorn,
    AnimalsRemoved,
    AnimalsReturned,
    LocalExtinction,
)
from ai_island.world import movement
from ai_island.world.clock import season_index_at
from ai_island.world.state import NEIGHBOUR_STEPS, Animal, World

ORDER_ANIMAL_BREED = 6


def _key(kind: str, zone: str) -> str:
    return f"{kind}|{zone}"


def population(world: World, kind: str, zone: str | None = None) -> int:
    """How many animals of ``kind`` live in ``zone`` (or everywhere)."""
    if zone is None:
        return len(world.animals[kind])
    return sum(1 for a in world.animals[kind] if a.zone == zone)


def capacity(world: World, kind: str, zone: str) -> int:
    return getattr(world.cfg.world.animals[kind].capacity, world.zone_type(zone))


def schedule_initial(world: World) -> None:
    for index, kind in enumerate(ANIMAL_KINDS):
        bal = world.cfg.balance.animals[kind]
        world.sched.push(bal.breed_interval, ORDER_ANIMAL_BREED, index, "animals_breed", (kind,))


def _spawn_near(world: World, kind: str, zone: str, parent: Animal | None) -> bool:
    spec = world.cfg.world.animals[kind]
    rng = world.streams.get("animals")
    pos = None
    if parent is not None:
        options = [(parent.x, parent.y)] + [
            (parent.x + dx, parent.y + dy) for dx, dy in NEIGHBOUR_STEPS
        ]
        options = [
            (x, y)
            for x, y in options
            if world.inside(x, y)
            and world.terrain[y][x] in spec.habitat
            and world.zone_grid[y][x] == zone
        ]
        if options:
            pos = options[rng.randrange(len(options))]
    if pos is None:
        pos = world.random_tile(rng, zone, spec.habitat)
    if pos is None:
        return False
    animal = Animal(world.new_id(), kind, pos[0], pos[1], zone)
    world.animals[kind].append(animal)
    movement.register(world, animal, world.tick)
    return True


def run_animals_breed(world: World, tick: int, args: tuple) -> None:
    (kind,) = args
    spec = world.cfg.world.animals[kind]
    bal = world.cfg.balance.animals[kind]
    rng = world.streams.get("animals")
    season = SEASONS[season_index_at(tick, world.cfg.world.clock)]
    parent_kind = spec.parent_kind or kind
    for zone in world.zones:
        key = _key(kind, zone)
        until = world.extinct_until.get(key)
        if until is not None:
            if tick < until:
                continue
            if spec.present_seasons is not None:
                del world.extinct_until[key]
            elif population(world, kind, zone) == 0:
                source = population(world, kind)
                room = capacity(world, kind, zone)
                if source >= 2 and room > 0 and bal.recolonise_count > 0:
                    del world.extinct_until[key]
                    count = 0
                    for _ in range(min(bal.recolonise_count, room)):
                        count += _spawn_near(world, kind, zone, None)
                    if count:
                        world.emit(AnimalsReturned(kind=kind, zone=zone, count=count), tick)
                continue
            else:
                del world.extinct_until[key]
        if season not in spec.breed_seasons:
            continue
        parents = [a for a in world.animals[parent_kind] if a.zone == zone]
        room = capacity(world, kind, zone) - population(world, kind, zone)
        if len(parents) < 2 or room <= 0:
            continue
        born = 0
        for _ in range(len(parents) // 2):
            if born >= room:
                break
            if rng.random() < bal.birth_chance:
                parent = parents[rng.randrange(len(parents))]
                born += _spawn_near(world, kind, zone, parent)
        if born:
            world.emit(AnimalsBorn(kind=kind, zone=zone, count=born), tick)
    world.sched.push(
        tick + bal.breed_interval,
        ORDER_ANIMAL_BREED,
        ANIMAL_KINDS.index(kind),
        "animals_breed",
        args,
    )


def remove_animals(world: World, kind: str, zone: str, tick: int) -> int:
    """Remove every ``kind`` animal in ``zone`` (a hunt that wipes them out).

    The kind then stays absent from that zone for ``extinction_delay_ticks``.
    """
    remaining = [a for a in world.animals[kind] if a.zone != zone]
    count = len(world.animals[kind]) - len(remaining)
    if count == 0:
        return 0
    movement.retire([a for a in world.animals[kind] if a.zone == zone])
    world.animals[kind] = remaining
    until = tick + world.cfg.balance.extinction_delay_ticks
    world.extinct_until[_key(kind, zone)] = until
    world.emit(AnimalsRemoved(kind=kind, zone=zone, count=count), tick)
    world.emit(LocalExtinction(kind=kind, zone=zone, absent_until=until), tick)
    return count


def remove_animal(world: World, animal: Animal, tick: int) -> bool:
    """Remove one animal (hunted, caught or killed).

    The kind is declared locally extinct only when the last one in its zone goes.
    """
    if animal.gone or animal not in world.animals[animal.kind]:
        return False
    world.animals[animal.kind].remove(animal)
    movement.retire([animal])
    world.emit(AnimalsRemoved(kind=animal.kind, zone=animal.zone, count=1), tick)
    if population(world, animal.kind, animal.zone) == 0:
        until = tick + world.cfg.balance.extinction_delay_ticks
        world.extinct_until[_key(animal.kind, animal.zone)] = until
        world.emit(LocalExtinction(kind=animal.kind, zone=animal.zone, absent_until=until), tick)
    return True


def on_season(world: World, season: str, tick: int) -> None:
    """Kinds that live only in some seasons (spring nests) vanish when their season ends."""
    for kind in ANIMAL_KINDS:
        present = world.cfg.world.animals[kind].present_seasons
        if present is None or season in present:
            continue
        for zone in world.zones:
            count = population(world, kind, zone)
            if count:
                movement.retire([a for a in world.animals[kind] if a.zone == zone])
                world.animals[kind] = [a for a in world.animals[kind] if a.zone != zone]
                world.emit(AnimalsRemoved(kind=kind, zone=zone, count=count), tick)
