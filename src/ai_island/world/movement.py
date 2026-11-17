"""Time-true movement for animals and wild dogs. Pure Python: no pygame, no AI.

Every moving entity (an animal of a moving kind, or a dog) walks on its own schedule: it
wanders a bout of a few tiles, one tile per ``minutes_per_tile`` game minutes, then rests.
A step starts at tick T and ends at tick T + duration; the logical tile ``x, y`` changes
only when the step ends, while ``from_*`` / ``to_*`` / ``move_*_tick`` let the viewer draw
the entity sliding between the two tiles.

One recurring scheduler job (``movement``) runs every tick. Due work comes from an
in-memory heap of ``(due tick, id, entity)`` that is rebuilt from the saved entity fields on
load, so nothing extra is persisted and no random numbers are drawn on restore.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass
from typing import Any

from ai_island.config import ANIMAL_KINDS, SEASONS
from ai_island.world.clock import is_night_at, season_index_at
from ai_island.world.state import NEIGHBOUR_STEPS, Animal, Dog, World

ORDER_MOVEMENT = 5
FROZEN_TICK = 10**9  # a penned animal never starts another step
_EPS = 1e-9

Mover = Animal | Dog


@dataclass(frozen=True)
class MoveSpec:
    minutes_per_tile: int
    bout_min: int
    bout_max: int
    rest_min: int
    rest_max: int


# ------------------------------------------------------------------------------ primitives


def step_minutes(minutes_per_tile: float, terrain_cost: float = 1.0) -> int:
    """Game minutes one step takes: at least 1, rounded up."""
    return max(1, math.ceil(minutes_per_tile * terrain_cost - _EPS))


def begin_step(entity: Mover, destination: tuple[int, int], tick: int, duration: int) -> None:
    """Start a step to ``destination``. Does not change ``x, y``."""
    entity.from_x, entity.from_y = entity.x, entity.y
    entity.to_x, entity.to_y = destination
    entity.move_start_tick = tick
    entity.move_end_tick = tick + duration
    if destination[0] > entity.x:
        entity.facing = 1
    elif destination[0] < entity.x:
        entity.facing = -1


def is_stepping(entity: Mover) -> bool:
    return entity.to_x != entity.x or entity.to_y != entity.y


def complete_step(entity: Mover, tick: int) -> bool:
    """Commit the destination when the step ends at ``tick``. True exactly once per step."""
    if not is_stepping(entity) or tick < entity.move_end_tick:
        return False
    entity.x, entity.y = entity.to_x, entity.to_y
    entity.from_x, entity.from_y = entity.x, entity.y
    entity.move_start_tick = entity.move_end_tick
    return True


def moving_entities(world: World) -> list[Mover]:
    """Animals of moving kinds and all dogs, sorted by id."""
    out: list[Mover] = []
    for kind in ANIMAL_KINDS:
        if world.cfg.balance.animals[kind].moves:
            out.extend(world.animals[kind])
    out.extend(world.dogs)
    out.sort(key=lambda e: e.id)
    return out


# --------------------------------------------------------------------------------- settings


def _kind_of(entity: Mover) -> str:
    return "wild_dog" if isinstance(entity, Dog) else entity.kind


def _dog_divisor(world: World, tick: int) -> float:
    bal = world.cfg.balance.dogs
    divisor = 1.0
    clock = world.cfg.world.clock
    if is_night_at(tick, clock):
        divisor *= bal.night_multiplier
    if SEASONS[season_index_at(tick, clock)] == "winter":
        divisor *= bal.winter_multiplier
    return divisor


def _shorten(value: int, divisor: float) -> int:
    return max(1, math.ceil(value / divisor - _EPS))


def spec_for(world: World, entity: Mover, tick: int) -> MoveSpec:
    """Movement settings for ``entity`` at ``tick`` (dogs: night / winter shorten times)."""
    if isinstance(entity, Dog):
        bal = world.cfg.balance.dogs
        div = _dog_divisor(world, tick)
        return MoveSpec(
            _shorten(bal.minutes_per_tile, div),
            bal.bout_min_tiles,
            bal.bout_max_tiles,
            _shorten(bal.rest_min_minutes, div),
            _shorten(bal.rest_max_minutes, div),
        )
    ab = world.cfg.balance.animals[entity.kind]
    return MoveSpec(
        ab.minutes_per_tile or 1,
        ab.bout_min_tiles or 1,
        ab.bout_max_tiles or 1,
        ab.rest_min_minutes or 1,
        ab.rest_max_minutes or 1,
    )


def _stream(world: World, entity: Mover) -> Any:
    return world.streams.get("dogs" if isinstance(entity, Dog) else "animals")


# ----------------------------------------------------------------------------- scheduling


def _due(entity: Mover) -> int:
    return entity.move_end_tick if is_stepping(entity) else entity.next_move_tick


def _push(world: World, entity: Mover) -> None:
    heapq.heappush(world.move_heap, (_due(entity), entity.id, entity))


def register(world: World, entity: Mover, tick: int) -> None:
    """Give a newly created mover its staggered first move time and queue it.

    Draws once from the ``animals`` / ``dogs`` stream. Kinds that do not move are ignored.
    """
    if isinstance(entity, Animal) and not world.cfg.balance.animals[entity.kind].moves:
        return
    if isinstance(entity, Dog):
        rest_max = world.cfg.balance.dogs.rest_max_minutes
    else:
        rest_max = world.cfg.balance.animals[entity.kind].rest_max_minutes or 1
    entity.next_move_tick = tick + _stream(world, entity).randint(0, rest_max)
    _push(world, entity)


def retire(entities: list[Animal]) -> None:
    """Mark removed animals so stale heap entries are ignored."""
    for entity in entities:
        entity.gone = True


def freeze(world: World, entity: Mover) -> None:
    """Stop an animal from wandering (a tamed animal stays in its pen)."""
    entity.from_x = entity.to_x = entity.x
    entity.from_y = entity.to_y = entity.y
    entity.next_move_tick = FROZEN_TICK
    _push(world, entity)


def rebuild_heap(world: World) -> None:
    """Rebuild the due heap from the entity fields (after loading a snapshot)."""
    world.move_heap = [(_due(e), e.id, e) for e in moving_entities(world)]
    heapq.heapify(world.move_heap)


def schedule_initial(world: World) -> None:
    world.sched.push(1, ORDER_MOVEMENT, 0, "movement", ())


# ------------------------------------------------------------------------------ decisions


def _animal_neighbours(world: World, animal: Animal) -> list[tuple[int, int]]:
    habitat = world.cfg.world.animals[animal.kind].habitat
    out = []
    for sx, sy in NEIGHBOUR_STEPS:
        nx, ny = animal.x + sx, animal.y + sy
        if (
            world.inside(nx, ny)
            and world.terrain[ny][nx] in habitat
            and world.zone_grid[ny][nx] == animal.zone
        ):
            out.append((nx, ny))
    return out


def _dog_ok(world: World, x: int, y: int) -> bool:
    return (
        world.inside(x, y)
        and world.passable(x, y)
        and world.zone_type(world.zone_at(x, y)) != "home"
        and (x, y) not in world.fire_zone
    )


def target_pos(world: World, dog: Dog) -> tuple[int, int] | None:
    """Where the dog's hunted person (or pen) is, if it still exists."""
    if dog.target.startswith("pen:"):
        s = world.structures.get(int(dog.target[4:]))
        return None if s is None else (s.x, s.y)
    return world.actor_pos(dog.target)


def _pursue(world: World, dog: Dog, tick: int, spec: MoveSpec) -> None:
    """One step toward the hunted target (dogs on the hunt may enter home plots)."""
    goal = target_pos(world, dog)
    here = abs(dog.x - goal[0]) + abs(dog.y - goal[1]) if goal else 0
    best = None
    if goal is not None and here > 1:
        for sx, sy in NEIGHBOUR_STEPS:
            nx, ny = dog.x + sx, dog.y + sy
            if not (world.inside(nx, ny) and world.passable(nx, ny)) or (nx, ny) in world.fire_zone:
                continue
            if world.zone_type(world.zone_at(nx, ny)) == "home":
                continue
            d = abs(nx - goal[0]) + abs(ny - goal[1])
            if d < here and (best is None or d < best[0]):
                best = (d, nx, ny)
    if best is None:
        dog.next_move_tick = tick + 1
        return
    begin_step(dog, (best[1], best[2]), tick, step_minutes(spec.minutes_per_tile))


def _dog_neighbours(world: World, dog: Dog) -> list[tuple[int, int]]:
    out = []
    for sx, sy in NEIGHBOUR_STEPS:
        if _dog_ok(world, dog.x + sx, dog.y + sy):
            out.append((dog.x + sx, dog.y + sy))
    return out


def _nearest_dog(world: World, animal: Animal) -> tuple[int, int] | None:
    """The logical tile of the nearest dog within the animal's flee radius, if any."""
    bal = world.cfg.balance.animals[animal.kind]
    if not bal.flees_dogs or not world.dogs:
        return None
    best = bal.flee_radius + 1
    threat = None
    for d in world.dogs:
        dist = abs(d.x - animal.x) + abs(d.y - animal.y)
        if dist < best:
            best, threat = dist, (d.x, d.y)
    return threat


def _leader_of(world: World, dog: Dog, leaders: dict[int, Dog]) -> Dog:
    if not leaders:
        for d in world.dogs:
            leaders.setdefault(d.pack, d)
    return leaders[dog.pack]


def _too_far(world: World, dog: Dog, leaders: dict[int, Dog]) -> Dog | None:
    leader = _leader_of(world, dog, leaders)
    if leader is dog:
        return None
    far = abs(dog.x - leader.x) + abs(dog.y - leader.y) > world.cfg.balance.dogs.cohesion
    return leader if far else None


def _rest(world: World, entity: Mover, tick: int, rng: Any) -> None:
    spec = spec_for(world, entity, tick)
    entity.bout_remaining = 0
    entity.next_move_tick = tick + rng.randint(spec.rest_min, spec.rest_max)


def _wants_more(world: World, entity: Mover, leaders: dict[int, Dog]) -> bool:
    """After a step ends: continue at once (bout left, fleeing, or catching up) or rest?"""
    if entity.bout_remaining > 0:
        return True
    if isinstance(entity, Dog) and entity.target:
        return True
    if isinstance(entity, Dog):
        return _too_far(world, entity, leaders) is not None
    return _nearest_dog(world, entity) is not None


def _start_step(world: World, entity: Mover, tick: int, leaders: dict[int, Dog]) -> None:
    """Decide and begin the next step of an idle mover whose time has come."""
    rng = _stream(world, entity)
    spec = spec_for(world, entity, tick)
    if isinstance(entity, Dog) and entity.target:
        _pursue(world, entity, tick, spec)
        return
    if isinstance(entity, Dog):
        options = _dog_neighbours(world, entity)
        leader = _too_far(world, entity, leaders)
        if leader is not None:
            sx = (leader.x > entity.x) - (leader.x < entity.x)
            sy = (leader.y > entity.y) - (leader.y < entity.y)
            toward = [(sx, 0), (0, sy)]
            toward = [o for o in toward if o != (0, 0)]
            rng.shuffle(toward)
            for ox, oy in toward:
                if _dog_ok(world, entity.x + ox, entity.y + oy):
                    begin_step(
                        entity,
                        (entity.x + ox, entity.y + oy),
                        tick,
                        step_minutes(spec.minutes_per_tile),
                    )
                    return
            _rest(world, entity, tick, rng)
            return
        duration = step_minutes(spec.minutes_per_tile)
    else:
        options = _animal_neighbours(world, entity)
        threat = _nearest_dog(world, entity)
        if threat is not None:
            if options:
                best = max(abs(threat[0] - nx) + abs(threat[1] - ny) for nx, ny in options)
                target = next(
                    (nx, ny)
                    for nx, ny in options
                    if abs(threat[0] - nx) + abs(threat[1] - ny) == best
                )
                flee = world.cfg.balance.animals[entity.kind].flee_minutes_per_tile or 1
                begin_step(entity, target, tick, step_minutes(flee))
            else:
                _rest(world, entity, tick, rng)
            return
        duration = step_minutes(spec.minutes_per_tile)
    if entity.bout_remaining <= 0:
        entity.bout_remaining = rng.randint(spec.bout_min, spec.bout_max)
    if not options:
        _rest(world, entity, tick, rng)
        return
    target = options[rng.randrange(len(options))]
    entity.bout_remaining -= 1
    begin_step(entity, target, tick, duration)


def _start_cap(world: World, count: int) -> int:
    if count < 4:
        return 1
    return max(1, int(count * world.cfg.balance.movement.max_start_share + _EPS))


# ------------------------------------------------------------------------------- the job


def run_movement(world: World, tick: int, args: tuple) -> None:
    """One movement tick: finish steps ending now, then start steps that are due."""
    from ai_island.world.dogs import activity_bucket

    if world.dogs:
        checks = world.counters["dog_checks"]
        bucket = activity_bucket(world, tick)
        checks[bucket] = checks.get(bucket, 0) + len(world.dogs)
    heap = world.move_heap
    world.sched.push(tick + 1, ORDER_MOVEMENT, 0, "movement", args)
    if not heap or heap[0][0] > tick:
        return
    due: list[Mover] = []
    while heap and heap[0][0] <= tick:
        when, _ident, entity = heapq.heappop(heap)
        if entity.gone or when != _due(entity):
            continue  # removed, or stale (its time was changed)
        due.append(entity)
    due.sort(key=lambda e: e.id)
    leaders: dict[int, Dog] = {}
    # 1. completions (never postponed)
    for entity in due:
        if is_stepping(entity) and complete_step(entity, tick):
            if isinstance(entity, Dog):
                moves = world.counters["dog_moves"]
                bucket = activity_bucket(world, tick)
                moves[bucket] = moves.get(bucket, 0) + 1
            if _wants_more(world, entity, leaders):
                entity.next_move_tick = tick
            else:
                _rest(world, entity, tick, _stream(world, entity))
    # 2. starts, in id order, capped per kind
    counts: dict[str, int] = {}
    started: dict[str, int] = {}
    for entity in due:
        if is_stepping(entity):
            continue
        if entity.next_move_tick > tick:
            _push(world, entity)
            continue
        kind = _kind_of(entity)
        if kind not in counts:
            counts[kind] = len(world.dogs) if kind == "wild_dog" else len(world.animals[kind])
        if started.get(kind, 0) >= _start_cap(world, counts[kind]):
            entity.next_move_tick = tick + 1
            _push(world, entity)
            continue
        _start_step(world, entity, tick, leaders)
        if is_stepping(entity):
            started[kind] = started.get(kind, 0) + 1
        _push(world, entity)
