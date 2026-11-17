"""Bodies: hunger, thirst, cold, tiredness, pain, sickness, death and respawn.

``update_bodies`` runs every ``body.interval_ticks`` for every player and villager.
"""

from __future__ import annotations

from ai_island.rules import interrupts, wellbeing
from ai_island.storage.events import (
    BandChanged,
    Died,
    Grief,
    Respawned,
    Sickness,
    VillagerDied,
)
from ai_island.world.agents import Player, Villager, transfer_all
from ai_island.world.clock import is_night_at, season_index_at
from ai_island.world.state import World

Actor = Player | Villager

FIRE_KINDS = ("campfire", "hearth")


class Env:
    """Facts that are the same for everyone this update."""

    def __init__(self, world: World, tick: int) -> None:
        cfg = world.cfg
        clock = cfg.world.clock
        self.night = is_night_at(tick, clock)
        self.winter = season_index_at(tick, clock) == 3
        self.weather = world.weather.current
        self.fires = [
            (s.x, s.y)
            for s in world.structures.values()
            if s.kind in FIRE_KINDS and s.burning(tick)
        ]
        self.houses: dict[str, list[tuple[int, int]]] = {}
        for s in world.structures.values():
            if s.kind == "house" and s.complete:
                self.houses.setdefault(s.owner, []).append((s.x, s.y))


def _near(points: list[tuple[int, int]], x: int, y: int, radius: int) -> bool:
    r2 = radius * radius
    for px, py in points:
        if (px - x) ** 2 + (py - y) ** 2 <= r2:
            return True
    return False


def is_sheltered(world: World, env: Env, actor: Actor) -> bool:
    owner = actor.id if isinstance(actor, Player) else actor.leader
    if owner is None:
        return False
    return _near(env.houses.get(owner, []), actor.x, actor.y, world.cfg.balance.body.shelter_radius)


def is_warmed(world: World, env: Env, actor: Actor) -> bool:
    return _near(env.fires, actor.x, actor.y, world.cfg.balance.body.fire_warm_radius)


def step_needs(world: World, env: Env, actor: Actor, tick: int, dt: int) -> str | None:
    """Advance one body by ``dt`` minutes. Returns a death cause if health reached 0."""
    cfg = world.cfg.balance.body
    b = actor.body
    day = world.cfg.world.clock.ticks_per_day
    hour = dt / 60.0
    wanderer = isinstance(actor, Villager) and actor.leader is None
    b.hunger = min(100.0, b.hunger + cfg.hunger_per_day * dt / day)
    if not wanderer:
        b.thirst = min(100.0, b.thirst + cfg.thirst_per_day * dt / day)
        resting = isinstance(actor, Player) and actor.action is not None
        resting = (
            resting and actor.action.request.kind == "rest" and actor.action.status == "working"
        )
        if resting:
            b.fatigue = max(0.0, b.fatigue - cfg.rest_recovery_per_hour * hour)
        elif isinstance(actor, Player):
            b.fatigue = min(100.0, b.fatigue + cfg.fatigue_per_day * dt / day)
        rate = 0.0
        if env.night:
            rate += cfg.cold_night_per_hour
        if env.winter:
            rate += cfg.cold_winter_per_hour
        if env.weather == "rain":
            rate += cfg.cold_rain_per_hour
        elif env.weather == "storm":
            rate += cfg.cold_storm_per_hour
        if rate == 0 or is_sheltered(world, env, actor) or is_warmed(world, env, actor):
            b.cold = max(0.0, b.cold - cfg.cold_recovery_per_hour * hour)
        else:
            b.cold = min(100.0, b.cold + rate * hour)
    cause: str | None = None
    crit_loss = cfg.critical_health_loss_per_hour
    if isinstance(actor, Villager):
        crit_loss = world.cfg.balance.villagers.critical_health_loss_per_hour
    for name, value in (("hunger", b.hunger), ("thirst", b.thirst), ("cold", b.cold)):
        if value >= cfg.critical_level:
            b.health -= crit_loss * hour
            cause = cause or name
    if b.sickness is not None:
        sick = cfg.sickness[b.sickness]
        if tick >= b.sickness_until:
            b.sickness = None
        else:
            b.health -= sick.health_loss_per_hour * hour
            b.pain = min(100.0, b.pain + sick.pain_per_hour * hour)
            cause = cause or b.sickness
    else:
        b.pain = max(0.0, b.pain - cfg.pain_decay_per_hour * hour)
        if max(b.hunger, b.thirst, b.cold) < cfg.regen_below:
            b.health = min(100.0, b.health + cfg.health_regen_per_hour * hour)
    if b.health <= 0:
        return cause or "wounds"
    return None


def update_bodies(world: World, tick: int) -> None:
    """Advance every living body by one body interval, then refresh X, bands and totals."""
    from ai_island.world import villagers as villagers_mod

    cfg = world.cfg.balance.body
    dt = cfg.interval_ticks
    env = Env(world, tick)
    for p in list(world.players.values()):
        if not p.alive:
            continue
        cause = step_needs(world, env, p, tick, dt)
        if cause is not None:
            kill_player(world, p, cause, tick)
            continue
        refresh_player(world, p, tick, dt)
    for v in sorted(world.villagers.values(), key=lambda q: q.id):
        if not v.alive:
            continue
        villagers_mod.update_villager_body(world, env, v, tick, dt)
    wellbeing.fade_relationships(world, dt)


def refresh_player(world: World, p: Player, tick: int, dt: int) -> None:
    """X accumulators, band and hooked flag after a body update."""
    x = wellbeing.x_of(world, p.id, tick)
    p.x_minute_sum += x * dt
    p.x_minutes += dt
    p.x_hour_sum += x * dt
    p.x_hour_n += dt
    if p.x_hour_n >= 60:
        p.x_hourly.append(round(p.x_hour_sum / p.x_hour_n, 3))
        p.x_hour_sum = 0.0
        p.x_hour_n = 0
    band = wellbeing.band_of(x)
    p.hooked = x < world.cfg.balance.wellbeing.hooked_x or (
        p.body.pain >= world.cfg.balance.wellbeing.hooked_pain
    )
    if band != p.band:
        old = p.band
        p.band = band
        world.emit(BandChanged(player=p.id, old=old, new=band), tick)
        interrupts.raise_interrupt(world, "band_changed", p.id, tick, detail=band)


def apply_sickness(world: World, who: Actor, kind: str, tick: int) -> None:
    """Make ``who`` sick with ``kind`` (a longer or equal sickness replaces a shorter one)."""
    spec = world.cfg.balance.body.sickness[kind]
    until = tick + spec.duration_ticks
    b = who.body
    if b.sickness is not None and b.sickness_until > until:
        return
    b.sickness = kind
    b.sickness_until = until
    world.emit(Sickness(who=who.id, kind=kind, until=until), tick)
    if isinstance(who, Player):
        wellbeing.add_gain(world, who.id, -spec.onset_blow, f"sick:{kind}", tick)


def cure_sickness(who: Actor) -> bool:
    if who.body.sickness is None:
        return False
    who.body.sickness = None
    who.body.sickness_until = 0
    return True


def hurt(world: World, who: Actor, health: float, pain: float, cause: str, tick: int) -> None:
    """Injure someone; kill them if their health reaches zero."""
    who.body.health -= health
    who.body.pain = min(100.0, who.body.pain + pain)
    if isinstance(who, Player):
        who.last_harm_tick = tick
        interrupts.raise_interrupt(world, "hurt", who.id, tick, detail=cause)
        if who.body.health <= 0:
            kill_player(world, who, cause, tick)
    elif who.body.health <= 0:
        kill_villager(world, who, cause, tick)


def drop_all_at(world: World, who: Actor, tick: int) -> None:
    pos = (who.x, who.y)
    if who.inventory.is_empty():
        return
    inv = world.drops.get(pos)
    if inv is None:
        inv = world.new_inventory()
        world.drops[pos] = inv
    transfer_all(who.inventory, inv)


def reset_mover(who: Actor, x: int, y: int, tick: int) -> None:
    who.x = who.from_x = who.to_x = x
    who.y = who.from_y = who.to_y = y
    who.move_start_tick = who.move_end_tick = tick


def kill_player(world: World, p: Player, cause: str, tick: int) -> None:
    """Death: carried goods lie on the tile, respawn at home, X ends 10 lower."""
    from ai_island.rules.actions import core as actions_core

    cfg = world.cfg.balance
    x_before = wellbeing.x_of(world, p.id, tick)
    world.emit(Died(player=p.id, cause=cause, x=p.x, y=p.y), tick)
    drop_all_at(world, p, tick)
    actions_core.clear_action(world, p)
    home = world.homes[p.index - 1]
    reset_mover(p, home.anchor[0], home.anchor[1], tick)
    b = p.body
    b.hunger, b.thirst, b.cold = (
        cfg.body.respawn_hunger,
        cfg.body.respawn_thirst,
        cfg.body.respawn_cold,
    )
    b.fatigue, b.health, b.pain = (
        cfg.body.respawn_fatigue,
        cfg.body.respawn_health,
        cfg.body.respawn_pain,
    )
    b.sickness, b.sickness_until = None, 0
    p.sleeping = False
    target = max(0.0, x_before - cfg.body.death_x_loss)
    p.b = target - wellbeing.x_core(world, p.id, tick)
    p.b_tick = tick
    world.emit(Respawned(player=p.id, x=p.x, y=p.y), tick)
    interrupts.clear_for(world, p.id)
    refresh_after_respawn(world, p, tick)


def refresh_after_respawn(world: World, p: Player, tick: int) -> None:
    band = wellbeing.band_of(wellbeing.x_of(world, p.id, tick))
    if band != p.band:
        old, p.band = p.band, band
        world.emit(BandChanged(player=p.id, old=old, new=band), tick)


def kill_villager(world: World, v: Villager, cause: str, tick: int) -> None:
    """A villager dies: drops goods, its leader grieves in proportion to the bond."""
    if not v.alive:
        return
    v.alive = False
    world.emit(VillagerDied(villager=v.id, leader=v.leader, cause=cause, x=v.x, y=v.y), tick)
    drop_all_at(world, v, tick)
    world.villagers.pop(v.id, None)
    wb = world.cfg.balance.wellbeing
    if v.leader in world.players:
        bond = v.bond.get(v.leader, 0.0)
        amount = wb.grief_base + wb.grief_bond_factor * bond
        world.emit(Grief(player=v.leader, villager=v.id, amount=round(amount, 3)), tick)
        wellbeing.add_gain(world, v.leader, -amount, "grief", tick)
        interrupts.raise_interrupt(world, "loss_noticed", v.leader, tick, detail="villager_died")
