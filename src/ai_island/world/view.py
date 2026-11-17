"""The snapshot of the map handed to the viewer. No pygame, no mutable references."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ai_island.rules.land import border_tiles, owner_index, stake_tiles
from ai_island.world.agents import ACTION_KINDS, JOBS
from ai_island.world.clock import daylight_at
from ai_island.world.state import Animal, Dog

if TYPE_CHECKING:
    from ai_island.sim import Simulation

# Every activity an AgentView can show: the actions, the villager jobs, idle and sleeping.
ACTIVITY_KINDS: tuple[str, ...] = tuple(
    sorted(set(ACTION_KINDS) | set(JOBS) | {"idle", "sleeping"})
)


@dataclass(frozen=True)
class EntityView:
    id: int
    kind: str
    x: int
    y: int
    from_x: int = -1
    from_y: int = -1
    to_x: int = -1
    to_y: int = -1
    move_start_tick: int = 0
    move_end_tick: int = 0
    facing: int = 1

    def __post_init__(self) -> None:
        if self.from_x < 0:
            object.__setattr__(self, "from_x", self.x)
            object.__setattr__(self, "from_y", self.y)
            object.__setattr__(self, "to_x", self.x)
            object.__setattr__(self, "to_y", self.y)


@dataclass(frozen=True)
class LandmarkView:
    kind: str  # quarry | lake_dock | great_tree
    x: int
    y: int


@dataclass(frozen=True)
class AgentView:
    id: str
    kind: str  # player | villager
    owner_index: int  # 1..4 (0 = belongs to nobody)
    x: int
    y: int
    from_x: int
    from_y: int
    to_x: int
    to_y: int
    move_start_tick: int
    move_end_tick: int
    facing: int
    markers: tuple[str, ...] = ()  # from sick | injured | sleeping
    activity: str = "idle"  # one of ACTIVITY_KINDS
    activity_target: str = ""  # an item, structure or person name, never an id or coordinates
    activity_progress: float = 0.0  # 0..1
    job: str = ""
    work_level: str = ""
    hunger: float = 0.0
    thirst: float = 0.0
    cold: float = 0.0
    rest: float = 0.0  # body.fatigue ("rest needed")
    health: float = 100.0
    pain: float = 0.0
    sickness: str = ""
    items: tuple[tuple[str, int], ...] = ()  # sorted by item kind
    tools: tuple[tuple[str, str, int], ...] = ()  # (kind, tier, durability) by tool id
    leader: str = ""
    loyalty: float = 0.0
    bond_leader: float | None = None  # None for a wanderer


@dataclass(frozen=True)
class VillageEntry:
    leader_id: str  # "" for the wanderers entry
    leader_name: str
    color_index: int
    members: tuple[tuple[str, str], ...]  # (villager id, name) sorted by id


@dataclass(frozen=True)
class StructureView:
    id: int
    kind: str
    x: int
    y: int
    owner_index: int  # 1..4 (0 = belongs to nobody)
    complete: bool
    progress: float  # 0..1
    hp: int
    max_hp: int
    sprite_key: str  # damaged_<kind> only when complete and damaged, else <kind>


@dataclass(frozen=True)
class PlayerPanel:
    id: str
    name: str
    index: int
    alive: bool
    feeling: str  # feeling words, never a number
    x: float  # wellbeing X
    hooked: bool
    trust: tuple[tuple[str, float], ...]  # toward every other player, sorted by id
    anger: tuple[tuple[str, float], ...]  # toward every other player, sorted by id


@dataclass(frozen=True)
class WorldFrame:
    tick: int
    year: int
    season: str  # spring | summer | autumn | winter
    week: int
    day: int
    hour: int
    minute: int
    is_night: bool
    weather: str  # clear | rain | storm | drought
    width: int
    height: int
    terrain: tuple[tuple[str, ...], ...]  # row-major [y][x]
    plants: tuple[EntityView, ...]  # sorted by id
    animals: tuple[EntityView, ...]  # sorted by id
    dogs: tuple[EntityView, ...]  # sorted by id
    landmarks: tuple[LandmarkView, ...]
    daylight: float = 1.0  # 0.0 dark .. 1.0 full light (daylight_at)
    players: tuple[AgentView, ...] = ()  # sorted by id
    villagers: tuple[AgentView, ...] = ()  # sorted by id
    borders: tuple[tuple[int, int, int], ...] = ()  # (x, y, owner_index) edge tiles of claimed land
    stakes: tuple[tuple[int, int, int], ...] = ()  # (x, y, owner_index)
    structures: tuple[StructureView, ...] = ()  # sorted by id; destroyed ones are absent
    names: tuple[tuple[str, str], ...] = ()  # (id, name) for every player and villager
    panels: tuple[PlayerPanel, ...] = ()  # sorted by id
    village_guide: tuple[VillageEntry, ...] = ()  # one per player by id, then Wanderers last
    owned_tiles: tuple[tuple[int, int, int], ...] = ()  # (x, y, owner_index) sorted by (y, x)


def _moving_view(ident: int, kind: str, e: Animal | Dog) -> EntityView:
    return EntityView(
        ident,
        kind,
        e.x,
        e.y,
        e.from_x,
        e.from_y,
        e.to_x,
        e.to_y,
        e.move_start_tick,
        e.move_end_tick,
        e.facing,
    )


def _is_structure_id(text: object) -> bool:
    return isinstance(text, str) and text.isdigit()


def _person_name(world, ident: object) -> str:
    if isinstance(ident, str):
        if ident in world.players:
            return world.players[ident].name
        if ident in world.villagers:
            return world.villagers[ident].name
    return ""


def _structure_of(world, act):
    sid = act.data.get("structure")
    if isinstance(sid, int):
        return world.structures.get(sid)
    if _is_structure_id(act.request.target):
        return world.structures.get(int(act.request.target))
    return None


def _activity_target(world, act) -> str:
    req = act.request
    if req.kind in ("build", "build_shrine", "repair"):
        s = _structure_of(world, act)
        if s is not None:
            return s.kind
        if req.structure:
            return req.structure
        return "shrine" if req.kind == "build_shrine" else ""
    item = act.data.get("item")
    if isinstance(item, str) and item:
        return item
    if req.item:
        return req.item
    if req.structure:
        return req.structure
    for ident in (act.data.get("target"), req.target):
        name = _person_name(world, ident)
        if name:
            return name
    return ""


def _activity_progress(world, act, tick: int) -> float:
    req = act.request
    data = act.data
    if act.status == "working":
        u = min(1.0, act.work_done / max(1, data.get("need", 1)))
    else:
        u = 0.0
    if req.kind == "move":
        value = act.route_index / max(1, len(act.route) - 1)
    elif isinstance(data.get("want"), int | float) and isinstance(data.get("got"), int | float):
        want = data["want"]
        got = data["got"]
        if want <= 0:
            value = u
        else:
            step = 1
            if req.kind == "gather":
                step = world.cfg.balance.actions.gather_yield.get(str(data.get("item")), 1)
            value = (got + min(step, max(0, want - got)) * u) / want
    elif req.minutes:
        value = (tick - act.start_tick) / req.minutes
    elif req.kind in ("build", "build_shrine", "repair") and _structure_of(world, act):
        s = _structure_of(world, act)
        if req.kind == "repair":
            value = s.hp / max(1, s.max_hp)
        else:
            value = s.progress / world.cfg.balance.buildings.work_minutes[s.kind]
    else:
        value = u
    return min(1.0, max(0.0, float(value)))


def _player_activity(world, p) -> tuple[str, str, float]:
    act = p.action
    if act is not None:
        return (
            act.request.kind,
            _activity_target(world, act),
            _activity_progress(world, act, world.tick),
        )
    return ("sleeping" if p.sleeping else "idle", "", 0.0)


def _agent_view(world, a, kind: str, owner_index: int, night: bool) -> AgentView:
    markers = []
    if a.body.sickness is not None:
        markers.append("sick")
    if a.body.health < 50 or a.body.pain >= 50:
        markers.append("injured")
    if getattr(a, "sleeping", False):
        markers.append("sleeping")
    body = a.body
    extra: dict = {
        "hunger": float(body.hunger),
        "thirst": float(body.thirst),
        "cold": float(body.cold),
        "rest": float(body.fatigue),
        "health": float(body.health),
        "pain": float(body.pain),
        "sickness": body.sickness or "",
        "items": tuple(a.inventory.counts().items()),
        "tools": tuple(
            (t.kind, t.tier, t.durability) for t in sorted(a.inventory.tools, key=lambda t: t.id)
        ),
    }
    if kind == "player":
        activity, target, progress = _player_activity(world, a)
        extra.update(activity=activity, activity_target=target, activity_progress=progress)
    else:
        extra.update(
            activity="sleeping" if night else (a.job or "idle"),
            job=a.job or "",
            work_level=a.work_level,
            leader=a.leader or "",
            loyalty=float(a.loyalty),
            bond_leader=(
                None
                if a.leader is None
                else float(a.bond.get(a.leader, world.cfg.balance.villagers.bond_start_other))
            ),
        )
    return AgentView(
        a.id, kind, owner_index, a.x, a.y, a.from_x, a.from_y, a.to_x, a.to_y,
        a.move_start_tick, a.move_end_tick, a.facing, tuple(markers), **extra,
    )  # fmt: skip


def _village_guide(world) -> tuple[VillageEntry, ...]:
    alive = [v for _, v in sorted(world.villagers.items()) if v.alive]
    out = []
    for pid, p in sorted(world.players.items()):
        members = tuple((v.id, v.name) for v in alive if v.leader == pid)
        out.append(VillageEntry(pid, p.name, p.index, members))
    out.append(
        VillageEntry("", "Wanderers", 0, tuple((v.id, v.name) for v in alive if v.leader is None))
    )
    return tuple(out)


def _owned_tiles(world) -> tuple[tuple[int, int, int], ...]:
    homes = getattr(world, "_home_tile_owners", None)
    if homes is None:
        homes = {}
        for home in world.homes:
            for y in range(home.y, home.y + home.size):
                for x in range(home.x, home.x + home.size):
                    homes[(x, y)] = home.index + 1
        world._home_tile_owners = homes  # type: ignore[attr-defined]
    merged = dict(homes)
    for pos, owner in world.claims.items():
        if pos not in merged:
            merged[pos] = owner_index(owner)
    return tuple(
        (x, y, o) for (x, y), o in sorted(merged.items(), key=lambda kv: (kv[0][1], kv[0][0]))
    )


def _structure_views(sim: Simulation) -> tuple[StructureView, ...]:
    world = sim.world
    share = sim.config.balance.buildings.damaged_share
    work = sim.config.balance.buildings.work_minutes
    out = []
    for sid, s in sorted(world.structures.items()):
        damaged = s.complete and s.damaged(share)
        out.append(
            StructureView(
                sid,
                s.kind,
                s.x,
                s.y,
                owner_index(s.owner),
                s.complete,
                1.0 if s.complete else min(1.0, max(0.0, float(s.progress) / work[s.kind])),
                s.hp,
                s.max_hp,
                f"damaged_{s.kind}" if damaged else s.kind,
            )
        )
    return tuple(out)


def _names(world) -> tuple[tuple[str, str], ...]:
    pairs = {pid: p.name for pid, p in world.players.items()}
    pairs.update({vid: v.name for vid, v in world.villagers.items()})
    return tuple(sorted(pairs.items()))


def _panels(world) -> tuple[PlayerPanel, ...]:
    from ai_island.rules.senses.report import feeling_words
    from ai_island.rules.wellbeing import is_hooked, x_of

    ids = sorted(world.players)
    out = []
    for pid in ids:
        p = world.players[pid]
        others = [o for o in ids if o != pid]
        start_trust = world.cfg.balance.wellbeing.start_trust
        neutral_anger = world.cfg.balance.wellbeing.anger_neutral
        out.append(
            PlayerPanel(
                pid,
                p.name,
                p.index,
                p.alive,
                feeling_words(world, pid),
                float(x_of(world, pid)),
                bool(is_hooked(world, pid)),
                tuple((o, float(p.trust.get(o, start_trust))) for o in others),
                tuple((o, float(p.anger.get(o, neutral_anger))) for o in others),
            )
        )
    return tuple(out)


def frame_from_world(sim: Simulation) -> WorldFrame:
    """Copy the current state of ``sim`` into an immutable frame."""
    world = sim.world
    clock = sim.clock
    animals = sorted((a for group in world.animals.values() for a in group), key=lambda a: a.id)
    return WorldFrame(
        tick=world.tick,
        year=clock.year,
        season=clock.season,
        week=clock.week,
        day=clock.day,
        hour=clock.hour,
        minute=clock.minute,
        is_night=clock.is_night,
        weather=world.weather.current,
        width=world.width,
        height=world.height,
        terrain=tuple(tuple(row) for row in world.terrain),
        plants=tuple(
            EntityView(p.id, p.kind, p.x, p.y)
            for p in sorted(world.plants, key=lambda p: p.id)
            if p.present
        ),
        animals=tuple(_moving_view(a.id, a.kind, a) for a in animals),
        dogs=tuple(_moving_view(d.id, "wild_dog", d) for d in world.dogs),
        landmarks=tuple(LandmarkView(m.kind, m.x, m.y) for m in world.landmarks),
        daylight=daylight_at(world.tick, sim.config.world.clock),
        players=tuple(
            _agent_view(world, p, "player", p.index, clock.is_night)
            for _, p in sorted(world.players.items())
        ),
        villagers=tuple(
            _agent_view(world, v, "villager", owner_index(v.leader), clock.is_night)
            for _, v in sorted(world.villagers.items())
            if v.alive
        ),
        borders=border_tiles(world),
        stakes=stake_tiles(world),
        structures=_structure_views(sim),
        names=_names(world),
        panels=_panels(world),
        village_guide=_village_guide(world),
        owned_tiles=_owned_tiles(world),
    )
