"""The scripted players: a fixed scenario that uses every action (a test fixture, no AI).

Scripted controllers may read the world. They arrange everything through normal actions: they
gather and build their way through the five task stages, and meanwhile act out one set piece per
action kind (social, harm, belief, tools, fire, dogs). Player 1 is the visitor who calls on
player 2 at night, when player 2 is at home: it talks, teaches, gifts, promises, trades, allies,
steals, sabotages, attacks, chases, poaches, captures and pulls stakes. Player 3 fights dogs with a
spear; everyone prays, builds, farms, hunts and claims land.

State (persisted): ``done`` = names of finished set pieces, ``tries`` = how often each was issued,
``started`` = the action kinds this player has started, ``facts`` = outcomes seen (trade done,
harm done). A set piece counts as finished when its outcome is seen, or after ``cap`` issues, so
the scenario always moves on. Needs come first: the players eat, drink, rest and (once they own a
house) sleep and warm up at home. An action under way is only replaced by a real need (level 2).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, NamedTuple

from ai_island.minds.dummy import DummyController
from ai_island.rules.actions.request import ActionRequest, PromiseSpec

SAFE_PLANTS = ("berries", "roots", "mushrooms")
FOOD_KINDS = ("cooked_meat", "fish", "eggs", "crops", "berries", "roots", "mushrooms", "milk")
STORE_KINDS = (*FOOD_KINDS, "raw_meat")
PREY = ("deer", "boar", "rabbit")  # big game first: a deer is worth five raw meat
CAP = 6  # a set piece that was issued this often is given up
FIELDS_WANTED = 8
VILLAGERS_WANTED = 5
FARMERS_WANTED = 3
SEARCH_RADIUS = 40
WIDE_RADIUS = 90  # stone and water are searched over the whole island
PRESSING = 2  # a need at this level replaces an action under way
DAY = 1440
VISIT_FROM_DAY = 8
EVENING = 20 * 60 + 30  # the visitor leaves at half past eight
NEAR = 4  # social set pieces need both players within 5 tiles (hearing); stay inside 4

Make = Callable[[Any, str, int], ActionRequest | None]
Ready = Callable[[Any, str, int], bool]


class Piece(NamedTuple):
    name: str
    ready: Ready
    make: Make
    cap: int = CAP
    outcome: str | None = None  # a fact that must be seen (default: the action was started)


def _dist(a: tuple[int, int], b: tuple[int, int]) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def _nearest_tile(
    world: Any, pos: tuple[int, int], terrains: tuple[str, ...], radius: int = SEARCH_RADIUS
) -> tuple[int, int] | None:
    best: tuple[int, tuple[int, int]] | None = None
    x0, x1 = max(0, pos[0] - radius), min(world.width, pos[0] + radius + 1)
    y0, y1 = max(0, pos[1] - radius), min(world.height, pos[1] + radius + 1)
    for y in range(y0, y1):
        row = world.terrain[y]
        for x in range(x0, x1):
            if row[x] in terrains and (
                row[x] not in ("rocky", "quarry") or world.stone.get((x, y), 0) > 0
            ):
                d = (x - pos[0]) ** 2 + (y - pos[1]) ** 2
                if best is None or d < best[0]:
                    best = (d, (x, y))
    return None if best is None else best[1]


def _nearest_plant(world: Any, pos: tuple[int, int], kinds: tuple[str, ...]) -> Any:
    found = [p for p in world.plants if p.present and p.kind in kinds]
    if not found:
        return None
    return min(found, key=lambda p: ((p.x - pos[0]) ** 2 + (p.y - pos[1]) ** 2, p.id))


def _owned(world: Any, pid: str, kind: str, complete: bool = True) -> list[Any]:
    return [
        s
        for s in sorted(world.structures.values(), key=lambda s: s.id)
        if s.owner == pid and s.kind == kind and (s.complete or not complete)
    ]


def _have(world: Any, pid: str, item: str) -> int:
    p = world.players[pid]
    return p.inventory.count(item) + p.home_store.count(item)


def _food_have(world: Any, pid: str) -> float:
    p = world.players[pid]
    total = p.inventory.food_units() + p.home_store.food_units()
    for s in world.structures.values():
        if s.owner == pid and s.store is not None and s.complete:
            total += s.store.food_units()
    return total


def _free_spot(world: Any, pid: str, offset: int) -> tuple[int, int]:
    """A grass tile near the home anchor, different for each ``offset``."""
    ax, ay = world.homes[world.players[pid].index - 1].anchor
    taken = {(s.x, s.y) for s in world.structures.values()} | set(world.claims)
    for r in range(1, 9):
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                if max(abs(dx), abs(dy)) != r:
                    continue
                x, y = ax + dx, ay + dy
                if world.inside(x, y) and world.terrain[y][x] == "grass" and (x, y) not in taken:
                    if offset == 0:
                        return x, y
                    offset -= 1
    return ax, ay


def _stake_spot(world: Any, pid: str) -> tuple[int, int] | None:
    """The free pool tile near home whose stake would claim the most free pool tiles."""
    radius = world.cfg.balance.claims.claim_radius
    ax, ay = world.homes[world.players[pid].index - 1].anchor
    pool = set(world.unclaimed)
    free = [t for t in pool if t not in world.claims and t not in world.stakes]
    free.sort(key=lambda t: (abs(t[0] - ax) + abs(t[1] - ay), t[1], t[0]))
    best: tuple[int, tuple[int, int]] | None = None
    for tile in free[:60]:
        if not world.passable(*tile):
            continue
        gain = sum(
            1
            for dy in range(-radius, radius + 1)
            for dx in range(-radius, radius + 1)
            if dx * dx + dy * dy <= radius * radius
            and (tile[0] + dx, tile[1] + dy) in pool
            and (tile[0] + dx, tile[1] + dy) not in world.claims
        )
        if best is None or gain > best[0]:
            best = (gain, tile)
    return None if best is None else best[1]


class ScriptedController:
    def __init__(self, pid: str, world: Any) -> None:
        self.pid = pid
        self.world = world
        self.idx = int(pid.rsplit("_", 1)[-1])
        self.dummy = DummyController(pid, world.streams.get(f"mind.{pid}"))
        self.done: list[str] = []
        self.tries: dict[str, int] = {}
        self.started: set[str] = set()
        self.facts: set[str] = set()
        self._seen = 0
        self.pieces = self._pieces()

    # -- persistence ------------------------------------------------------------------
    def to_state(self) -> dict[str, Any]:
        return {
            "done": list(self.done),
            "tries": dict(self.tries),
            "started": sorted(self.started),
            "facts": sorted(self.facts),
            "dummy": self.dummy.to_state(),
        }

    def from_state(self, state: dict[str, Any]) -> None:
        self.done = list(state.get("done", []))
        self.tries = {k: int(v) for k, v in state.get("tries", {}).items()}
        self.started = set(state.get("started", []))
        self.facts = set(state.get("facts", []))
        self.dummy.from_state(state.get("dummy", {}))

    # -- helpers ------------------------------------------------------------------------
    def _me(self) -> Any:
        return self.world.players[self.pid]

    def _other(self, index: int) -> Any:
        return self.world.players.get(f"player_{index}")

    def _day(self) -> int:
        return self.world.tick // DAY

    def _scan_events(self) -> None:
        """Learn what happened to this player from the events since the last look."""
        events = self.world.events
        if self._seen > len(events):
            self._seen = 0
        for i in range(self._seen, len(events)):
            payload = events[i].payload
            kind = events[i].type
            if kind == "action_started" and payload.player == self.pid:
                self.started.add(payload.kind)
            elif kind == "harm" and payload.actor == self.pid:
                self.facts.add(f"harm:{payload.kind}")
            elif kind == "trade_done" and payload.maker == self.pid and payload.kind == "trade":
                self.facts.add("trade_done")
        self._seen = len(events)

    def _pending_offer(self) -> Any:
        offers = self.world.offers
        rows = offers.values() if isinstance(offers, dict) else offers
        for offer in sorted(rows, key=lambda o: o.id):
            if offer.target == self.pid and self.world.tick < offer.expires:
                return offer
        return None

    def _near_other(self, radius: int = NEAR) -> bool:
        other, me = self._other(2), self._me()
        return (
            other is not None
            and other.alive
            and (other.x - me.x) ** 2 + (other.y - me.y) ** 2 <= radius * radius
        )

    def _in_window(self) -> bool:
        return self._day() >= VISIT_FROM_DAY and (self.world.tick % DAY) >= EVENING

    def _visiting(self) -> bool:
        """Player 1 is on its evening call and still has talking to do."""
        if self.idx != 1 or not self._in_window():
            return False
        other = self._other(2)
        social = ("talk", "teach", "gift", "promise", "trade", "ally")
        return other is not None and other.alive and any(n not in self.done for n in social)

    # -- the set pieces ---------------------------------------------------------------------
    def _pieces(self) -> list[Piece]:
        out: list[Piece] = []

        def add(name: str, ready: Ready, make: Make, cap: int = CAP, outcome: str | None = None):
            out.append(Piece(name, ready, make, cap, outcome))

        def after_days(n: int) -> Ready:
            return lambda w, p, t: t >= n * DAY

        def has(item: str, n: int = 1) -> Ready:
            return lambda w, p, t: w.players[p].inventory.count(item) >= n

        def housed(w: Any, p: str) -> bool:
            return bool(_owned(w, p, "house"))

        # belief: needs nothing but time
        add("pray", after_days(1), lambda w, p, t: ActionRequest(kind="pray", minutes=30))
        add("ceremony", after_days(1), lambda w, p, t: ActionRequest(kind="ceremony", minutes=30))
        add(
            "offering",
            has("wood", 1),
            lambda w, p, t: ActionRequest(kind="offering", item="wood", amount=1),
        )
        add(
            "build_shrine",
            lambda w, p, t: (
                housed(w, p)
                and w.players[p].inventory.count("wood") >= 4
                and w.players[p].inventory.count("stone") >= 4
            ),
            lambda w, p, t: ActionRequest(
                kind="build_shrine", x=_free_spot(w, p, 5)[0], y=_free_spot(w, p, 5)[1]
            ),
        )
        # items and fire
        add(
            "drop",
            has("wood", 2),
            lambda w, p, t: ActionRequest(kind="drop", item="wood", amount=1),
        )
        add(
            "pick_up",
            lambda w, p, t: "drop" in self.done,
            lambda w, p, t: ActionRequest(
                kind="pick_up", item="wood", x=self._me().x, y=self._me().y
            ),
        )
        add(
            "make_fire",
            has("wood", 3),
            lambda w, p, t: ActionRequest(kind="make_fire", x=self._me().x, y=self._me().y),
        )
        add(
            "craft",
            lambda w, p, t: (
                housed(w, p)
                and w.players[p].inventory.count("wood") >= 3
                and w.players[p].inventory.count("stone") >= 2
            ),
            lambda w, p, t: ActionRequest(kind="craft", tool="spear", tier="basic"),
        )
        add(
            "cook",
            lambda w, p, t: (
                w.players[p].inventory.count("raw_meat") > 0
                and bool([s for s in w.structures.values() if s.burning(t)])
            ),
            lambda w, p, t: ActionRequest(kind="cook", item="raw_meat", amount=1),
        )
        add("get_herb", self._ready_get_herb, self._make_get_herb, 4, outcome="never")
        add(
            "use_herb",
            lambda w, p, t: bool(self._herb_item()),
            lambda w, p, t: ActionRequest(kind="use_herb", item=self._herb_item()),
        )
        add("repair", self._ready_repair, self._make_repair, 8)
        add(
            "guard",
            after_days(2),
            lambda w, p, t: ActionRequest(kind="guard", x=self._me().x, y=self._me().y, minutes=60),
        )
        add(
            "farm",
            lambda w, p, t: bool(_owned(w, p, "field")),
            lambda w, p, t: ActionRequest(
                kind="farm", x=_owned(w, p, "field")[0].x, y=_owned(w, p, "field")[0].y
            ),
        )
        add(
            "fish",
            lambda w, p, t: bool(w.players[p].inventory.find_tool("fishing")) and w.tick >= 2 * DAY,
            self._make_fish,
        )
        add(
            "hunt",
            lambda w, p, t: bool(w.players[p].inventory.find_tool("spear")),
            self._make_hunt,
        )
        add("build_pen", self._ready_pen, self._make_pen, 4, outcome="never")
        add("get_bait", self._ready_bait, self._make_bait, 6, outcome="never")
        add("tame", self._ready_tame, self._make_tame, 8)
        add(
            "assign_villager",
            lambda w, p, t: any(v.leader == p and v.alive for v in w.villagers.values()),
            self._make_assign,
        )
        add("recruit", lambda w, p, t: t >= 2 * DAY and self._recruitable(), self._make_recruit, 12)
        add(
            "eat",
            lambda w, p, t: any(w.players[p].inventory.count(k) for k in FOOD_KINDS),
            self._make_eat,
        )
        add(
            "drink",
            has("water"),
            lambda w, p, t: ActionRequest(kind="drink", item="water", amount=1),
        )
        add("rest", after_days(0), lambda w, p, t: ActionRequest(kind="rest", minutes=30))
        add("store", has("wood", 1), self._make_store)
        # land: a stake early, so that player 1 has a rival stake to pull later
        add("claim_land", self._ready_claim, self._make_claim, 8)
        if self.idx == 1:
            self._visitor_pieces(add)
        return out

    def _visitor_pieces(self, add: Callable[..., None]) -> None:
        window = lambda w, p, t: self._in_window()  # noqa: E731
        near = lambda w, p, t: self._in_window() and self._near_other()  # noqa: E731
        day8 = lambda w, p, t: self._day() >= VISIT_FROM_DAY and self._other(2) is not None  # noqa: E731

        def walk_ready(w: Any, p: str, t: int) -> bool:
            return self._visiting() and not self._near_other(3)

        def prep_ready(w: Any, p: str, t: int) -> bool:
            # carry a few logs to the evening call: they are the gift and the trade
            if self._day() < VISIT_FROM_DAY or (t % DAY) >= EVENING:
                return False
            if all(n in self.done for n in ("gift", "trade")):
                return False
            return w.players[p].inventory.count("wood") < 4

        add("visit_prep", prep_ready, self._make_prep, 10**9, outcome="never")
        add("visit_walk", walk_ready, self._make_visit_walk, 10**9, outcome="never")
        add(
            "talk",
            near,
            lambda w, p, t: ActionRequest(kind="talk", target="player_2", text="Hello, neighbour."),
        )
        add(
            "teach",
            near,
            lambda w, p, t: ActionRequest(
                kind="teach", target="player_2", text="The red berries are good to eat."
            ),
        )
        add(
            "gift",
            lambda w, p, t: self._in_window() and w.players[p].inventory.count("wood") >= 1,
            lambda w, p, t: ActionRequest(kind="gift", target="player_2", item="wood", amount=1),
        )
        add(
            "promise",
            window,
            lambda w, p, t: ActionRequest(
                kind="promise",
                target="player_2",
                text="I will not harm you.",
                promise=PromiseSpec(kind="not_harm", to="player_2", due_tick=t + DAY),
            ),
        )
        add(
            "trade",
            lambda w, p, t: near(w, p, t) and w.players[p].inventory.count("wood") >= 1,
            self._make_trade,
            14,
            outcome="trade_done",
        )
        add(
            "ally",
            lambda w, p, t: near(w, p, t) and len(w.players[p].allies) < 3,
            lambda w, p, t: ActionRequest(kind="ally", target="player_2"),
        )
        add("steal", day8, self._make_steal, 20, outcome="harm:steal")
        add("sabotage", day8, self._make_sabotage, 8, outcome="harm:sabotage")
        add("attack", day8, lambda w, p, t: ActionRequest(kind="attack", target="player_2"))
        add("chase_off", day8, lambda w, p, t: ActionRequest(kind="chase_off", target="player_2"))
        add("poach", day8, self._visit_villager("poach"), 8)
        add("capture", day8, self._visit_villager("capture"), 10)
        add(
            "pull_stakes",
            lambda w, p, t: (
                self._day() >= VISIT_FROM_DAY and any(o == "player_2" for o in w.stakes.values())
            ),
            self._make_pull,
            12,
            outcome="harm:pull_stakes",
        )

    # -- set piece makers ---------------------------------------------------------------------
    def _make_visit_walk(self, w: Any, p: str, t: int) -> ActionRequest | None:
        ax, ay = w.homes[self._other(2).index - 1].anchor
        return ActionRequest(kind="move", x=ax, y=ay)

    def _make_prep(self, w: Any, p: str, t: int) -> ActionRequest | None:
        return self._acquire("wood", 4, (self._me().x, self._me().y))

    def _make_trade(self, w: Any, p: str, t: int) -> ActionRequest | None:
        other = self._other(2)
        want: dict[str, int] = {}
        for item in ("stone", "wood", "water"):
            if other.inventory.count(item) >= 1:
                want = {item: 1}
                break
        return ActionRequest(kind="trade", target="player_2", offer={"wood": 1}, want=want)

    def _make_steal(self, w: Any, p: str, t: int) -> ActionRequest | None:
        other = self._other(2)
        if other is None or not other.alive:
            return None
        if not other.home_store.is_empty():
            return ActionRequest(kind="steal", target=other.id, structure="store")
        return ActionRequest(kind="steal", target=other.id)

    def _make_sabotage(self, w: Any, p: str, t: int) -> ActionRequest | None:
        other = self._other(2)
        if other is None:
            return None
        mine = _owned(w, other.id, "house") or [
            s for s in sorted(w.structures.values(), key=lambda s: s.id) if s.owner == other.id
        ]
        if not mine:
            return None
        return ActionRequest(kind="sabotage", structure=str(mine[0].id))

    def _visit_villager(self, kind: str) -> Make:
        def run(w: Any, p: str, t: int) -> ActionRequest | None:
            mine = sorted(
                (v for v in w.villagers.values() if v.leader == "player_2" and v.alive),
                key=lambda v: v.id,
            )
            if not mine:
                return None
            return ActionRequest(kind=kind, target=mine[0].id)

        return run

    def _make_pull(self, w: Any, p: str, t: int) -> ActionRequest | None:
        stakes = sorted(pos for pos, owner in w.stakes.items() if owner == "player_2")
        if not stakes:
            return None
        return ActionRequest(kind="pull_stakes", x=stakes[0][0], y=stakes[0][1])

    def _herb_item(self) -> str | None:
        inv = self._me().inventory
        for kind in ("healing_herbs", "herbs"):
            if inv.count(kind):
                return kind
        return None

    def _ready_get_herb(self, w: Any, p: str, t: int) -> bool:
        if "use_herb" in self.started or self._herb_item() or t < 2 * DAY:
            return False
        return (
            _nearest_plant(w, (self._me().x, self._me().y), ("healing_herbs", "herbs")) is not None
        )

    def _make_get_herb(self, w: Any, p: str, t: int) -> ActionRequest | None:
        me = self._me()
        plant = _nearest_plant(w, (me.x, me.y), ("healing_herbs", "herbs"))
        if plant is None:
            return None
        return ActionRequest(kind="gather", item=plant.kind, x=plant.x, y=plant.y, amount=1)

    def _damaged(self) -> Any:
        for s in sorted(self.world.structures.values(), key=lambda s: s.id):
            if s.owner == self.pid and s.complete and s.hp < s.max_hp:
                return s
        return None

    def _ready_repair(self, w: Any, p: str, t: int) -> bool:
        s = self._damaged()
        if s is None:
            return False
        me = self._me()
        # half the building cost, from the pack or the home store
        costs = w.cfg.balance.buildings.costs[s.kind]
        return all(_have(w, p, k) >= max(1, (v + 1) // 2) for k, v in costs.items()) and (
            me.inventory.count("wood") >= 1 or _dist((me.x, me.y), (s.x, s.y)) <= 20
        )

    def _make_repair(self, w: Any, p: str, t: int) -> ActionRequest | None:
        s = self._damaged()
        return None if s is None else ActionRequest(kind="repair", structure=str(s.id))

    def _ready_pen(self, w: Any, p: str, t: int) -> bool:
        return (
            t >= 4 * DAY
            and bool(_owned(w, p, "house"))
            and not _owned(w, p, "pen", False)
            and w.players[p].inventory.count("wood") >= 6
        )

    def _make_pen(self, w: Any, p: str, t: int) -> ActionRequest | None:
        x, y = _free_spot(w, p, 12)
        return ActionRequest(kind="build", structure="pen", x=x, y=y)

    def _ready_bait(self, w: Any, p: str, t: int) -> bool:
        inv = self._me().inventory
        has_bait = any(
            inv.count(b) for b in w.cfg.balance.actions.tame_bait_items
        )  # fmt: skip
        return bool(_owned(w, p, "pen")) and not has_bait and "tame" not in self.started

    def _make_bait(self, w: Any, p: str, t: int) -> ActionRequest | None:
        me = self._me()
        plant = _nearest_plant(w, (me.x, me.y), SAFE_PLANTS)
        if plant is None:
            return None
        return ActionRequest(kind="gather", item=plant.kind, x=plant.x, y=plant.y, amount=1)

    def _ready_tame(self, w: Any, p: str, t: int) -> bool:
        inv = self._me().inventory
        return bool(_owned(w, p, "pen")) and any(
            inv.count(b) for b in w.cfg.balance.actions.tame_bait_items
        )

    def _make_tame(self, w: Any, p: str, t: int) -> ActionRequest | None:
        return ActionRequest(kind="tame")

    def _make_fish(self, w: Any, p: str, t: int) -> ActionRequest | None:
        spot = _nearest_tile(w, (self._me().x, self._me().y), ("lake", "coast"))
        if spot is None:
            return None
        return ActionRequest(kind="fish", x=spot[0], y=spot[1], minutes=120)

    def _make_hunt(self, w: Any, p: str, t: int) -> ActionRequest | None:
        return self._hunt_request(w, many=1, kinds=("rabbit", "deer"))

    def _hunt_request(
        self, w: Any, many: int, kinds: tuple[str, ...] = PREY
    ) -> ActionRequest | None:
        me = self._me()
        prey = [a for kind in kinds for a in w.animals.get(kind, []) if not a.pen]
        if not prey:
            return None
        a = min(prey, key=lambda a: ((a.x - me.x) ** 2 + (a.y - me.y) ** 2, a.id))
        return ActionRequest(kind="hunt", target=str(a.id), x=a.x, y=a.y, amount=many)

    def _recruitable(self) -> bool:
        w, pid = self.world, self.pid
        mine = sum(1 for v in w.villagers.values() if v.leader == pid and v.alive)
        free = any(v.alive and v.leader is None for v in w.villagers.values())
        return mine < VILLAGERS_WANTED and free and bool(_owned(w, pid, "house"))

    def _make_recruit(self, w: Any, p: str, t: int) -> ActionRequest | None:
        me = self._me()
        free = [v for v in w.villagers.values() if v.alive and v.leader is None]
        if not free:
            return None
        v = min(free, key=lambda v: ((v.x - me.x) ** 2 + (v.y - me.y) ** 2, v.id))
        return ActionRequest(kind="recruit", target=v.id)

    def _make_assign(self, w: Any, p: str, t: int) -> ActionRequest | None:
        mine = sorted(
            (v for v in w.villagers.values() if v.leader == p and v.alive), key=lambda v: v.id
        )
        if not mine:
            return None
        jobless = [v for v in mine if v.job is None] or mine
        v = jobless[0]
        farmers = sum(1 for q in mine if q.job == "farm")
        job = "farm" if farmers < FARMERS_WANTED else "gather"
        if v.job is not None:
            job = v.job
        return ActionRequest(kind="assign_villager", target=v.id, job=job, work_level="normal")

    def _make_eat(self, w: Any, p: str, t: int) -> ActionRequest | None:
        item = next((k for k in FOOD_KINDS if w.players[p].inventory.count(k)), None)
        return None if item is None else ActionRequest(kind="eat", item=item, amount=1)

    def _make_store(self, w: Any, p: str, t: int) -> ActionRequest | None:
        ax, ay = w.homes[self._me().index - 1].anchor
        return ActionRequest(kind="store", item="wood", amount=1, x=ax, y=ay)

    def _ready_claim(self, w: Any, p: str, t: int) -> bool:
        me = self._me()
        if me.inventory.count("stake") > 0:
            return True
        # make the first stake early; later stakes come from the economy
        return (
            t >= 3 * DAY
            and bool(_owned(w, p, "house"))
            and "claim_land" not in self.started
            and "craft_stake" not in self.done
            and me.inventory.count("wood") >= 3
        )

    def _make_claim(self, w: Any, p: str, t: int) -> ActionRequest | None:
        me = self._me()
        if me.inventory.count("stake") == 0:
            self.done.append("craft_stake")
            return ActionRequest(kind="craft", item="stake", amount=1)
        spot = _stake_spot(w, p)
        if spot is None:
            return None
        return ActionRequest(kind="claim_land", x=spot[0], y=spot[1])

    # -- the economy that walks through the five stages -----------------------------------
    def _economy(self, ctx: Any) -> ActionRequest | None:
        w, pid = self.world, self.pid
        me = self._me()
        pos = (me.x, me.y)
        stage = me.task_stage
        ax, ay = w.homes[me.index - 1].anchor
        inv = me.inventory
        if inv.food_units() >= 6 and _dist(pos, (ax, ay)) > 1:
            return ActionRequest(kind="move", x=ax, y=ay)
        for kind in STORE_KINDS:
            n = inv.count(kind)
            if n and inv.food_units() >= 6:
                return ActionRequest(kind="store", item=kind, amount=n, x=ax, y=ay)
        unfinished = [
            s
            for s in sorted(w.structures.values(), key=lambda s: s.id)
            if s.owner == pid and not s.complete and s.kind != "campfire"
        ]
        if unfinished:
            return ActionRequest(kind="build", target=str(unfinished[0].id))
        mine = sorted(
            (v for v in w.villagers.values() if v.leader == pid and v.alive), key=lambda v: v.id
        )
        idle = [v for v in mine if v.job is None]
        if idle and stage >= 2:
            v = idle[0]
            if (v.x - me.x) ** 2 + (v.y - me.y) ** 2 > 16:
                return ActionRequest(kind="move", x=v.x, y=v.y)
            farmers = sum(1 for q in mine if q.job == "farm")
            job = "farm" if farmers < FARMERS_WANTED else "gather"
            return ActionRequest(kind="assign_villager", target=v.id, job=job, work_level="normal")
        if stage >= 2 and self._recruitable():
            req = self._make_recruit(w, pid, ctx.tick)
            if req is not None:
                return req
        tiles = [
            (s.x, s.y)
            for s in _owned(w, pid, "field")
            if w.terrain[s.y][s.x] in ("farmland_ready", "farmland_empty")
        ]
        if stage >= 2 and tiles:
            return ActionRequest(kind="farm", x=tiles[0][0], y=tiles[0][1], amount=1)
        needs: list[tuple[str, int]]
        if stage == 1:
            needs = [("wood", 10), ("water", 10)]
        elif stage == 2:
            needs = [("wood", 14), ("stone", 2)]
        elif stage == 3:
            needs = [("wood", 12), ("stone", 2)]
        elif stage == 4:
            needs = [("wood", 12), ("stone", 6)]
        else:
            needs = [("wood", 8), ("stone", 16)]
        for item, goal in needs:
            held = _have(w, pid, item)
            if held < goal:
                req = self._acquire(item, goal - held, pos)
                if req is not None:
                    return req
        if stage == 2:
            for i, kind in enumerate(("house", "field")):
                if not _owned(w, pid, kind, False):
                    x, y = _free_spot(w, pid, i)
                    return ActionRequest(kind="build", structure=kind, x=x, y=y)
        fields = len(_owned(w, pid, "field", False))
        if stage >= 2 and _owned(w, pid, "house") and fields < FIELDS_WANTED:
            if _have(w, pid, "wood") >= 2:
                x, y = _free_spot(w, pid, 10 + fields)
                return ActionRequest(kind="build", structure="field", x=x, y=y)
        food_goal = {1: 10, 2: 10, 3: 90, 4: 90, 5: 90}.get(stage, 0)
        if _food_have(w, pid) < food_goal:
            if stage >= 3 and inv.find_tool("spear") and me.body.health >= 50:
                req = self._hunt_request(w, many=2)
                if req is not None:
                    return req
            plant = _nearest_plant(w, pos, SAFE_PLANTS)
            if plant is not None:
                return ActionRequest(kind="gather", item=plant.kind, x=plant.x, y=plant.y, amount=3)
        if stage >= 4:
            claimed = sum(1 for owner in w.claims.values() if owner == pid)
            if not _owned(w, pid, "workshop", False):
                x, y = _free_spot(w, pid, 3)
                return ActionRequest(kind="build", structure="workshop", x=x, y=y)
            if claimed < 10:
                if inv.count("stake") > 0:
                    spot = _stake_spot(w, pid)
                    if spot is not None:
                        return ActionRequest(kind="claim_land", x=spot[0], y=spot[1])
                elif _have(w, pid, "wood") >= 1:
                    return ActionRequest(kind="craft", item="stake", amount=1)
        if stage == 5 and not _owned(w, pid, "monument", False):
            x, y = _free_spot(w, pid, 4)
            return ActionRequest(kind="build", structure="monument", x=x, y=y)
        return None

    def _acquire(self, item: str, amount: int, pos: tuple[int, int]) -> ActionRequest | None:
        w = self.world
        terrains = {
            "wood": ("tree",),
            "stone": ("rocky", "quarry"),
            "water": ("spring", "lake"),
        }[item]
        radius = WIDE_RADIUS if item == "stone" else SEARCH_RADIUS
        spot = _nearest_tile(w, pos, terrains, radius)
        if spot is None:
            return None
        return ActionRequest(kind="gather", item=item, x=spot[0], y=spot[1], amount=min(amount, 10))

    # -- staying alive ----------------------------------------------------------------------
    def _survive(self, ctx: Any, strict: bool = False) -> ActionRequest | None:
        """Eat, drink, rest and get warm; with a house, do the resting and warming at home."""
        w, pid = self.world, self.pid
        me = self._me()
        needs = ctx.report.needs
        pos = (me.x, me.y)
        anchor = w.homes[me.index - 1].anchor
        near_home = _dist(pos, anchor) <= 1
        housed = bool(_owned(w, pid, "house"))
        hunger, thirst = needs.get("hunger", 0), needs.get("thirst", 0)
        fatigue, cold = needs.get("fatigue", 0), needs.get("cold", 0)
        night = (ctx.tick % DAY) >= 20 * 60 or (ctx.tick % DAY) < 5 * 60
        low = PRESSING if strict else 1  # an action under way is only replaced by a real need
        if strict or self._visiting():
            night = False
        if thirst >= low:
            water = me.inventory.count("water")
            if water > 0:
                return ActionRequest(kind="drink", item="water", amount=min(3, water))
            lake = _nearest_tile(w, pos, ("spring", "lake"), WIDE_RADIUS)
            if lake is not None:
                return ActionRequest(kind="gather", item="water", x=lake[0], y=lake[1], amount=6)
            return self.dummy.decide(ctx)
        if hunger >= low:
            held = next((k for k in FOOD_KINDS if _have(w, pid, k)), None)
            if held is not None:
                if me.inventory.count(held) == 0 and not near_home:
                    return ActionRequest(kind="move", x=anchor[0], y=anchor[1])
                return ActionRequest(kind="eat", item=held, until="sated")
            plant = _nearest_plant(w, pos, SAFE_PLANTS)
            if plant is not None:
                return ActionRequest(kind="gather", item=plant.kind, x=plant.x, y=plant.y, amount=4)
            return self.dummy.decide(ctx)
        if housed and (fatigue >= low or cold >= low or night):
            if not near_home:
                return ActionRequest(kind="move", x=anchor[0], y=anchor[1])
            return ActionRequest(kind="rest", minutes=60)
        if fatigue >= PRESSING or cold >= PRESSING:
            return self.dummy.decide(ctx)
        return None

    # -- the decision ---------------------------------------------------------------------
    def _next_piece(self, tick: int) -> ActionRequest | None:
        for piece in self.pieces:
            name = piece.name
            if name in self.done:
                continue
            if name in ("gather", "move", "build", "rest"):
                continue
            if piece.outcome != "never" and (
                (piece.outcome in self.facts) if piece.outcome else (name in self.started)
            ):
                self.done.append(name)
                continue
            if self.tries.get(name, 0) >= piece.cap:
                self.done.append(name)
                continue
            if not piece.ready(self.world, self.pid, tick):
                continue
            request = piece.make(self.world, self.pid, tick)
            if request is None:
                self.tries[name] = self.tries.get(name, 0) + 1
                continue
            self.tries[name] = self.tries.get(name, 0) + 1
            return request
        return None

    def decide(self, ctx: Any) -> ActionRequest | None:
        self._scan_events()
        offer = self._pending_offer()
        if offer is not None:
            return ActionRequest(kind=offer.kind, accept=offer.id)
        busy = self._me().action is not None and ctx.reason in ("check", "interrupt")
        urgent = self._survive(ctx, strict=busy)
        if urgent is not None:
            return urgent
        if busy:
            return None  # let the action under way finish
        request = self._next_piece(ctx.tick)
        if request is not None:
            return request
        request = self._economy(ctx)
        if request is not None:
            me = self._me()
            anchor = self.world.homes[me.index - 1].anchor
            if (
                request.kind in ("build", "craft")
                and request.target is None
                and _dist((me.x, me.y), anchor) > 1
            ):
                # materials kept in the home store are only reachable from home
                return ActionRequest(kind="move", x=anchor[0], y=anchor[1])
            return request
        return self.dummy.decide(ctx)


def scenario_summary(controllers: dict[str, Any], world: Any) -> list[str]:
    """The lines printed at the end of a scripted run: kinds started, kinds missing, stages."""
    from ai_island.rules.actions.request import ACTION_KINDS

    started = sorted({k for c in controllers.values() for k in getattr(c, "started", ())})
    missing = sorted(set(ACTION_KINDS) - set(started))
    stages = ", ".join(
        f"{pid}: stages done {max(0, p.task_stage - 1)}" for pid, p in sorted(world.players.items())
    )
    first = f"scripted run: {len(started)} of {len(ACTION_KINDS)} action kinds started: "
    return [
        first + ", ".join(started),
        "scripted run: kinds never started: " + (", ".join(missing) if missing else "none"),
        "scripted run: " + stages,
    ]
