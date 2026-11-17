"""Wild dog packs: they live in buffer and centre land, move faster at night and in winter,
and breed slowly. No attacks in this phase."""

from __future__ import annotations

from ai_island.config import ANIMAL_KINDS, SEASONS
from ai_island.storage.events import DogAttack, DogBorn, DogScared
from ai_island.world import movement
from ai_island.world.clock import is_night_at, season_index_at
from ai_island.world.state import Dog, World

ORDER_DOG_BREED = 8


def schedule_initial(world: World) -> None:
    bal = world.cfg.balance.dogs
    world.sched.push(bal.breed_interval, ORDER_DOG_BREED, 0, "dogs_breed", ())


def activity_bucket(world: World, tick: int) -> str:
    """Counter bucket such as ``summer_day`` or ``winter_night``."""
    clock = world.cfg.world.clock
    season = SEASONS[season_index_at(tick, clock)]
    return f"{season}_{'night' if is_night_at(tick, clock) else 'day'}"


def packs(world: World) -> dict[int, list[Dog]]:
    """Dogs grouped by pack id (sorted by pack id; members in id order)."""
    out: dict[int, list[Dog]] = {}
    for dog in world.dogs:
        out.setdefault(dog.pack, []).append(dog)
    return dict(sorted(out.items()))


def run_dogs_breed(world: World, tick: int, args: tuple) -> None:
    bal = world.cfg.balance.dogs
    rng = world.streams.get("dogs")
    for pack, members in packs(world).items():
        if len(world.dogs) >= bal.max_total:
            break
        if len(members) < 2 or len(members) >= bal.max_pack_size:
            continue
        if rng.random() < bal.birth_chance:
            leader = members[0]
            pup = Dog(world.new_id(), pack, leader.x, leader.y)
            world.dogs.append(pup)
            movement.register(world, pup, tick)
            world.emit(DogBorn(pack=pack, dog_id=pup.id), tick)
    world.sched.push(tick + bal.breed_interval, ORDER_DOG_BREED, 0, "dogs_breed", args)


# ----------------------------------------------------------------------------- hunting


def hunting_time(world: World, tick: int) -> bool:
    """Dogs hunt at night and in winter (gameplay.md)."""
    clock = world.cfg.world.clock
    return is_night_at(tick, clock) or season_index_at(tick, clock) == 3


def _people(world: World) -> list:
    out: list = [p for p in world.players.values() if p.alive]
    # leaderless wanderers keep to the wilds and are not prey (they would be wiped out in days)
    out.extend(v for v in world.villagers.values() if v.alive and v.leader is not None)
    return out


def _deterrent(world: World, who, pack: list[Dog], crowd: list, tick: int) -> str | None:
    """Why this target is safe from dogs, or None if it is prey."""
    from ai_island.rules.actions import social

    cfg = world.cfg.balance.dog_attack
    pos = (who.x, who.y)
    if world.zone_type(world.zone_at(who.x, who.y)) == "home":
        return "home"
    if pos in world.fire_zone or any((d.x, d.y) in world.fire_zone for d in pack):
        return "fire"
    if cfg.spear_scares and getattr(who, "inventory", None) is not None:
        if who.inventory.find_tool("spear") is not None:
            return "spear"
    near = sum(
        1
        for o in crowd
        if o is not who
        and (o.x - who.x) ** 2 + (o.y - who.y) ** 2 <= cfg.group_radius * cfg.group_radius
    )
    if near + 1 >= cfg.scare_group:
        return "group"
    if cfg.guard_scares and social.guards_near(world, pos, 4, tick):
        return "guard"
    return None


def run_dog_attacks(world: World, tick: int) -> None:
    """Decide hunts for each pack and resolve bites. Cheap: one decision per pack."""
    from ai_island.rules import body

    cfg = world.cfg.balance.dog_attack
    if not world.dogs:
        return
    hunting = hunting_time(world, tick)
    crowd = _people(world) if hunting else []
    for members in packs(world).values():
        scared = members[0].scared_until > tick
        if not hunting or scared:
            for d in members:
                d.target = ""
            continue
        leader = members[0]
        current = leader.target
        if not current or movement.target_pos(world, leader) is None:
            current = _pick_target(world, members, crowd, tick)
            for d in members:
                d.target = current
        if not current:
            continue
        who = world.players.get(current) or world.villagers.get(current)
        if who is not None:
            why = _deterrent(world, who, members, crowd, tick)
            if why is not None:
                for d in members:
                    d.target = ""
                    d.scared_until = tick + cfg.scared_ticks
                    world.emit(DogScared(dog=d.id, by=why), tick)
                continue
        goal = movement.target_pos(world, leader)
        for d in members:
            if goal is None or tick - d.last_bite < cfg.cooldown_ticks:
                continue
            if abs(d.x - goal[0]) + abs(d.y - goal[1]) > 1:
                continue
            d.last_bite = tick
            if who is not None and who.alive:
                world.emit(
                    DogAttack(dog=d.id, victim=who.id, x=who.x, y=who.y, damage=cfg.bite_health),
                    tick,
                )
                body.hurt(world, who, cfg.bite_health, cfg.bite_pain, "dog_bite", tick)
                if not who.alive:
                    for m in members:
                        m.target = ""
            elif current.startswith("pen:"):
                _attack_pen(world, d, int(current[4:]), tick)


def _pick_target(world: World, pack: list[Dog], crowd: list, tick: int) -> str:
    cfg = world.cfg.balance.dog_attack
    leader = pack[0]
    best: tuple[int, str] | None = None
    for who in crowd:
        d = abs(who.x - leader.x) + abs(who.y - leader.y)
        if d > cfg.hunt_radius:
            continue
        if _deterrent(world, who, pack, crowd, tick) is not None:
            continue
        if best is None or (d, who.id) < best:
            best = (d, who.id)
    for s in world.structures.values():
        if s.kind == "pen" and s.complete:
            d = abs(s.x - leader.x) + abs(s.y - leader.y)
            holds = any(a.pen == s.id for kind in ANIMAL_KINDS for a in world.animals[kind])
            if holds and d <= cfg.hunt_radius and (best is None or (d, f"pen:{s.id}") < best):
                best = (d, f"pen:{s.id}")
    return "" if best is None else best[1]


def _attack_pen(world: World, dog: Dog, pen_id: int, tick: int) -> None:
    from ai_island.world import animals as animals_mod

    cfg = world.cfg.balance.dog_attack
    rng = world.streams.get("dogs")
    if rng.random() >= cfg.pen_kill_chance:
        return
    for kind in ANIMAL_KINDS:
        for a in list(world.animals[kind]):
            if a.pen == pen_id:
                animals_mod.remove_animal(world, a, tick)
                world.emit(
                    DogAttack(dog=dog.id, victim=f"animal_{a.id}", x=a.x, y=a.y, damage=0.0), tick
                )
                return
