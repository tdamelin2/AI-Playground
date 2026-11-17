"""The world state: terrain, resources, plants, animals, dogs, weather and the schedule.

Pure Python. No pygame, no AI. Everything that changes lives here and round-trips through
``to_state`` / ``from_state`` (JSON-safe), so a saved world continues exactly.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Any

from ai_island.config import ANIMAL_KINDS, TERRAIN_KEYS, GameConfig
from ai_island.rng import Streams
from ai_island.storage.events import Event
from ai_island.world import persist
from ai_island.world.agents import (
    HarmRecord,
    Interrupt,
    Inventory,
    Offer,
    Player,
    Promise,
    Structure,
    Utterance,
    Villager,
    configure_items,
)
from ai_island.world.weather import Weather

Pos = tuple[int, int]
NEIGHBOUR_STEPS: tuple[Pos, ...] = ((1, 0), (0, 1), (-1, 0), (0, -1))


@dataclass
class Home:
    index: int
    x: int
    y: int
    size: int
    rotation: int  # the template is rotated clockwise by rotation * 90 degrees
    anchor: Pos  # a walkable tile near the middle of the plot

    @property
    def zone(self) -> str:
        return f"home_{self.index}"


@dataclass
class Landmark:
    kind: str
    x: int
    y: int


@dataclass
class PlantSite:
    id: int
    kind: str
    x: int
    y: int
    present: bool
    regrow_due: int | None


@dataclass
class Animal:
    id: int
    kind: str
    x: int
    y: int
    zone: str
    # mover state (see world/movement.py): x, y is the logical tile and changes only when a
    # step ends; idle means from = to = (x, y) and move_start_tick == move_end_tick
    from_x: int = -1
    from_y: int = -1
    to_x: int = -1
    to_y: int = -1
    move_start_tick: int = 0
    move_end_tick: int = 0
    next_move_tick: int = 0
    bout_remaining: int = 0
    facing: int = 1
    owner: str = ""  # the player whose pen holds this tamed animal
    pen: int = 0  # structure id of that pen (0 = wild)
    gone: bool = field(default=False, repr=False, compare=False)  # removed; not saved

    def __post_init__(self) -> None:
        if self.from_x < 0:
            self.from_x = self.to_x = self.x
            self.from_y = self.to_y = self.y


@dataclass
class Dog:
    id: int
    pack: int
    x: int
    y: int
    from_x: int = -1
    from_y: int = -1
    to_x: int = -1
    to_y: int = -1
    move_start_tick: int = 0
    move_end_tick: int = 0
    next_move_tick: int = 0
    bout_remaining: int = 0
    facing: int = 1
    target: str = ""  # the person this dog is hunting
    scared_until: int = 0
    last_bite: int = -1000000
    gone: bool = field(default=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.from_x < 0:
            self.from_x = self.to_x = self.x
            self.from_y = self.to_y = self.y


def _mover_row(e: Animal | Dog) -> list[int]:
    return [
        e.from_x,
        e.from_y,
        e.to_x,
        e.to_y,
        e.move_start_tick,
        e.move_end_tick,
        e.next_move_tick,
        e.bout_remaining,
        e.facing,
    ]


class Scheduler:
    """A min-heap of due work, ordered by (due tick, subsystem order, entity id, serial)."""

    def __init__(self) -> None:
        self.heap: list[tuple] = []
        self.seq = 0

    def push(self, due: int, order: int, ident: int, kind: str, args: tuple) -> None:
        self.seq += 1
        heapq.heappush(self.heap, (due, order, ident, self.seq, kind, args))

    def peek_due(self) -> int | None:
        return self.heap[0][0] if self.heap else None

    def pop(self) -> tuple:
        return heapq.heappop(self.heap)

    def to_state(self) -> dict[str, Any]:
        return {"seq": self.seq, "heap": [list(item[:5]) + [list(item[5])] for item in self.heap]}

    @classmethod
    def from_state(cls, state: dict[str, Any]) -> Scheduler:
        sched = cls()
        sched.seq = state["seq"]
        sched.heap = [(i[0], i[1], i[2], i[3], i[4], tuple(i[5])) for i in state["heap"]]
        heapq.heapify(sched.heap)
        return sched


def _encode_terrain(terrain: list[list[str]]) -> list[str]:
    index = {key: chr(ord("a") + i) for i, key in enumerate(TERRAIN_KEYS)}
    return ["".join(index[t] for t in row) for row in terrain]


def _decode_terrain(rows: list[str]) -> list[list[str]]:
    return [[TERRAIN_KEYS[ord(ch) - ord("a")] for ch in row] for row in rows]


class World:
    """The whole island."""

    def __init__(self, cfg: GameConfig, streams: Streams) -> None:
        self.cfg = cfg
        self.streams = streams
        self.tick = 0
        self.width = cfg.world.map.width
        self.height = cfg.world.map.height
        self.terrain: list[list[str]] = [["grass"] * self.width for _ in range(self.height)]
        self.stone: dict[Pos, int] = {}
        self.homes: list[Home] = []
        self.landmarks: list[Landmark] = []
        self.zone_grid: list[list[str]] = []
        self.zones: list[str] = []
        self.unclaimed: list[Pos] = []
        self.tree_initial: dict[str, int] = {}
        self.trees_alive: dict[str, int] = {}
        self.plants: list[PlantSite] = []
        self.animals: dict[str, list[Animal]] = {kind: [] for kind in ANIMAL_KINDS}
        self.extinct_until: dict[str, int] = {}
        self.dogs: list[Dog] = []
        self.next_pack = 1
        self.counters: dict[str, dict[str, int]] = {"dog_checks": {}, "dog_moves": {}}
        self.next_id = 1
        self.weather = Weather({k: float(v) for k, v in cfg.balance.water.multiplier.items()})
        self.sched = Scheduler()
        self.move_heap: list[tuple] = []  # (due tick, id, entity); rebuilt on load, not saved
        self.events: list[Event] = []
        self._passable = {key: key in cfg.world.terrain.cost for key in TERRAIN_KEYS}
        # people (Phase 2)
        configure_items(
            cfg.balance.food.values,
            cfg.balance.food.spoil_ticks,
            cfg.balance.wellbeing.band_edges,
            cfg.balance.wellbeing.band_names,
        )
        self.ids: dict[str, int] = {}
        self.players: dict[str, Player] = {}
        self.villagers: dict[str, Villager] = {}
        self.structures: dict[int, Structure] = {}
        self.claims: dict[Pos, str] = {}
        self.stakes: dict[Pos, str] = {}
        self.offers: dict[int, Offer] = {}
        self.promises: dict[int, Promise] = {}
        self.harm_log: list[HarmRecord] = []
        self.pending_interrupts: dict[str, list[Interrupt]] = {}
        self.utterances: list[Utterance] = []
        self.drops: dict[Pos, Inventory] = {}
        self.bridges: set[Pos] = set()
        self.pending_grants: dict[str, int] = {}
        self.fire_zone: set[Pos] = (
            set()
        )  # tiles dogs avoid because a fire burns near them (not saved)
        self.turn_handler: Any = None  # set by Simulation; not saved
        self.controller_kind = "none"
        self.last_weather_flags = ""
        self._cost_cache: list[list[float | None]] | None = None

    # ---------------------------------------------------------------------------- basics

    def emit(self, payload: Any, tick: int | None = None) -> None:
        """Log a typed event at ``tick`` (default: the current tick)."""
        when = self.tick if tick is None else tick
        if payload.type == "player_day" and payload.villager_loyalty is None:
            # The daily player summary carries the mean loyalty of the player's living villagers.
            living = [v for v in self.villagers.values() if v.leader == payload.player and v.alive]
            if living:
                payload.villager_loyalty = round(sum(v.loyalty for v in living) / len(living), 3)
        self.events.append(Event(tick=when, type=payload.type, payload=payload))

    def new_id(self) -> int:
        value = self.next_id
        self.next_id += 1
        return value

    def inside(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def zone_at(self, x: int, y: int) -> str:
        return self.zone_grid[y][x]

    def passable(self, x: int, y: int) -> bool:
        return self._passable[self.terrain[y][x]] or (x, y) in self.bridges

    def cost_grid(self) -> list[list[float | None]]:
        """``costs[y][x]`` for the A* search: cost of entering the tile, None if water."""
        # rebuilt on every call: terrain changes (trees, crops) happen all over the place and a
        # cache that missed one would make a restored run differ from the original
        cost = self.cfg.world.terrain.cost
        grid: list[list[float | None]] = [[cost.get(t) for t in row] for row in self.terrain]
        for bx, by in self.bridges:
            grid[by][bx] = cost["grass"]
        return grid

    def invalidate_costs(self) -> None:
        self._cost_cache = None

    def next(self, name: str) -> int:
        """The next id of a named persisted counter (starts at 1)."""
        value = self.ids.get(name, 1)
        self.ids[name] = value + 1
        return value

    def new_inventory(self) -> Inventory:
        return Inventory(self.ids)

    def actor_pos(self, actor_id: str) -> Pos | None:
        who = self.players.get(actor_id) or self.villagers.get(actor_id)
        return None if who is None else (who.x, who.y)

    def home_by_zone(self, zone: str) -> Home | None:
        for home in self.homes:
            if home.zone == zone:
                return home
        return None

    def zone_type(self, zone: str) -> str:
        return zone.split("_")[0] if zone.startswith("home_") else zone

    def zone_bounds(self, zone: str) -> tuple[int, int, int, int]:
        """Bounding box (x0, y0, x1, y1), end exclusive, used for sampling tiles."""
        if zone == "centre":
            size = self.cfg.world.map.centre_size
            x0 = (self.width - size) // 2
            y0 = (self.height - size) // 2
            return x0, y0, x0 + size, y0 + size
        home = self.home_by_zone(zone)
        if home is not None:
            return home.x, home.y, home.x + home.size, home.y + home.size
        return 0, 0, self.width, self.height

    def random_tile(self, rng: Any, zone: str, allowed: list[str]) -> Pos | None:
        """A random tile of ``zone`` whose terrain is in ``allowed`` (None if there is none)."""
        x0, y0, x1, y1 = self.zone_bounds(zone)
        for _ in range(600):
            x = rng.randrange(x0, x1)
            y = rng.randrange(y0, y1)
            if self.zone_grid[y][x] == zone and self.terrain[y][x] in allowed:
                return x, y
        found = [
            (x, y)
            for y in range(y0, y1)
            for x in range(x0, x1)
            if self.zone_grid[y][x] == zone and self.terrain[y][x] in allowed
        ]
        return found[rng.randrange(len(found))] if found else None

    # ---------------------------------------------------------------------- persistence

    def _encode_pool(self) -> list[str]:
        """The unclaimed pool as one '0'/'1' string per row."""
        rows = [["0"] * self.width for _ in range(self.height)]
        for x, y in self.unclaimed:
            rows[y][x] = "1"
        return ["".join(r) for r in rows]

    def to_state(self) -> dict[str, Any]:
        return {
            "tick": self.tick,
            "terrain": _encode_terrain(self.terrain),
            "stone": [[x, y, n] for (x, y), n in sorted(self.stone.items())],
            "homes": [
                [h.index, h.x, h.y, h.size, h.rotation, h.anchor[0], h.anchor[1]]
                for h in self.homes
            ],
            "landmarks": [[m.kind, m.x, m.y] for m in self.landmarks],
            "unclaimed": self._encode_pool(),
            "tree_initial": self.tree_initial,
            "trees_alive": self.trees_alive,
            "plants": [[p.id, p.kind, p.x, p.y, p.present, p.regrow_due] for p in self.plants],
            "animals": [
                [a.id, a.kind, a.x, a.y, a.zone, *_mover_row(a), a.owner, a.pen]
                for kind in ANIMAL_KINDS
                for a in self.animals[kind]
            ],
            "extinct_until": self.extinct_until,
            "dogs": [
                [d.id, d.pack, d.x, d.y, *_mover_row(d), d.target, d.scared_until, d.last_bite]
                for d in self.dogs
            ],
            "next_pack": self.next_pack,
            "counters": self.counters,
            "next_id": self.next_id,
            "weather": self.weather.current,
            "sched": self.sched.to_state(),
            "people": self._people_state(),
        }

    def _people_state(self) -> dict[str, Any]:
        return {
            "ids": self.ids,
            "players": [persist.player_to_state(p) for _, p in sorted(self.players.items())],
            "villagers": [persist.villager_to_state(v) for _, v in sorted(self.villagers.items())],
            "structures": [s.to_state() for _, s in sorted(self.structures.items())],
            "claims": [[x, y, o] for (x, y), o in sorted(self.claims.items())],
            "stakes": [[x, y, o] for (x, y), o in sorted(self.stakes.items())],
            "offers": [persist.offer_to_state(o) for _, o in sorted(self.offers.items())],
            "promises": [persist.promise_to_state(p) for _, p in sorted(self.promises.items())],
            "harm": [persist.harm_to_state(h) for h in self.harm_log],
            "interrupts": {
                pid: [persist.interrupt_to_state(i) for i in items]
                for pid, items in sorted(self.pending_interrupts.items())
            },
            "utterances": [persist.utterance_to_state(u) for u in self.utterances],
            "drops": [[x, y, inv.to_state()] for (x, y), inv in sorted(self.drops.items())],
            "bridges": [[x, y] for x, y in sorted(self.bridges)],
            "pending_grants": self.pending_grants,
            "controller": self.controller_kind,
            "weather_flags": self.last_weather_flags,
        }

    def _load_people(self, state: dict[str, Any]) -> None:
        self.ids.update(state["ids"])
        self.players = {s["id"]: persist.player_from_state(self.ids, s) for s in state["players"]}
        self.villagers = {
            s["id"]: persist.villager_from_state(self.ids, s) for s in state["villagers"]
        }
        self.structures = {
            row[0]: Structure.from_state(self.ids, row) for row in state["structures"]
        }
        self.claims = {(x, y): o for x, y, o in state["claims"]}
        self.stakes = {(x, y): o for x, y, o in state["stakes"]}
        self.offers = {row[0]: Offer(*row) for row in state["offers"]}
        self.promises = {row[0]: Promise(*row) for row in state["promises"]}
        self.harm_log = [persist.harm_from_state(row) for row in state["harm"]]
        self.pending_interrupts = {
            pid: [Interrupt(*row) for row in items] for pid, items in state["interrupts"].items()
        }
        self.utterances = [Utterance(*row) for row in state["utterances"]]
        self.drops = {(x, y): Inventory.from_state(self.ids, inv) for x, y, inv in state["drops"]}
        self.bridges = {(x, y) for x, y in state["bridges"]}
        self.pending_grants = dict(state["pending_grants"])
        self.controller_kind = state["controller"]
        self.last_weather_flags = state["weather_flags"]
        self._cost_cache = None

    @classmethod
    def from_state(cls, cfg: GameConfig, streams: Streams, state: dict[str, Any]) -> World:
        from ai_island.world.mapgen import build_zone_grid

        world = cls(cfg, streams)
        world.tick = state["tick"]
        world.terrain = _decode_terrain(state["terrain"])
        world.stone = {(x, y): n for x, y, n in state["stone"]}
        world.homes = [
            Home(i, x, y, size, rot, (ax, ay)) for i, x, y, size, rot, ax, ay in state["homes"]
        ]
        world.landmarks = [Landmark(k, x, y) for k, x, y in state["landmarks"]]
        world.zone_grid, world.zones = build_zone_grid(world)
        world.unclaimed = [
            (x, y)
            for y, row in enumerate(state["unclaimed"])
            for x, ch in enumerate(row)
            if ch == "1"
        ]
        world.tree_initial = dict(state["tree_initial"])
        world.trees_alive = dict(state["trees_alive"])
        world.plants = [PlantSite(*row) for row in state["plants"]]
        for row in state["animals"]:
            world.animals[row[1]].append(Animal(*row))
        world.extinct_until = dict(state["extinct_until"])
        world.dogs = [Dog(*row) for row in state["dogs"]]
        world.next_pack = state["next_pack"]
        world.counters = {k: dict(v) for k, v in state["counters"].items()}
        world.next_id = state["next_id"]
        world.weather.current = state["weather"]
        world.sched = Scheduler.from_state(state["sched"])
        world._load_people(state["people"])
        from ai_island.world.movement import rebuild_heap

        rebuild_heap(world)
        return world
