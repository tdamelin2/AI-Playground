"""People and things they carry: bodies, inventories, players, villagers, structures.

Pure data plus the one atomic item mover (``transfer_items``). No pygame, no AI, no
random numbers. Everything round-trips through ``to_state`` / ``from_state``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from ai_island.rules.actions.request import ActionRequest
    from ai_island.world.state import World

Pos = tuple[int, int]

ITEM_KINDS: tuple[str, ...] = (
    "wood",
    "stone",
    "water",
    "berries",
    "mushrooms",
    "roots",
    "herbs",
    "healing_herbs",
    "mild_poison",
    "strong_poison",
    "raw_meat",
    "cooked_meat",
    "spoiled_meat",
    "fish",
    "eggs",
    "milk",
    "crops",
    "stake",
)
TOOL_KINDS: tuple[str, ...] = ("axe", "pickaxe", "hoe", "fishing", "spear", "water")
TOOL_TIERS: tuple[str, ...] = ("basic", "better")
SICKNESSES: tuple[str, ...] = ("mild_poison", "strong_poison", "raw_meat", "spoiled_meat")
STRUCTURE_KINDS: tuple[str, ...] = (
    "house",
    "hearth",
    "field",
    "storehouse",
    "workshop",
    "pen",
    "granary",
    "bridge",
    "monument",
    "shrine",
    "campfire",
)
ACTION_KINDS: tuple[str, ...] = (
    "eat",
    "drink",
    "rest",
    "move",
    "gather",
    "farm",
    "fish",
    "hunt",
    "build",
    "store",
    "craft",
    "make_fire",
    "cook",
    "tame",
    "use_herb",
    "assign_villager",
    "talk",
    "trade",
    "gift",
    "promise",
    "ally",
    "recruit",
    "teach",
    "guard",
    "steal",
    "sabotage",
    "attack",
    "chase_off",
    "claim_land",
    "pull_stakes",
    "capture",
    "poach",
    "pray",
    "ceremony",
    "build_shrine",
    "offering",
    "repair",
    "drop",
    "pick_up",
)

JOBS: tuple[str, ...] = ("gather", "farm", "guard", "build", "tend_animals")
WORK_LEVELS: tuple[str, ...] = ("light", "normal", "hard")

# filled from balance.toml when a World is created (see configure_items)
FOOD_UNITS: dict[str, float] = {}
SPOIL_TICKS: dict[str, int] = {}
SPOIL_INTO: dict[str, str] = {}
BAND_EDGES: list[float] = [80.0, 60.0, 40.0, 20.0]
BAND_NAMES: list[str] = ["strong", "all_right", "uneasy", "suffering", "miserable"]


def configure_items(
    food_values: dict[str, float],
    spoilage: dict[str, int],
    edges: list[float] | None = None,
    names: list[str] | None = None,
) -> None:
    if edges is not None:
        BAND_EDGES[:] = edges
    if names is not None:
        BAND_NAMES[:] = names
    """Set the food values and spoil times that Inventory uses (balance.toml)."""
    FOOD_UNITS.clear()
    FOOD_UNITS.update(food_values)
    SPOIL_TICKS.clear()
    SPOIL_TICKS.update(spoilage)
    SPOIL_INTO.clear()
    for kind in spoilage:
        SPOIL_INTO[kind] = "spoiled_meat"


# ------------------------------------------------------------------------------ inventory


@dataclass
class Lot:
    id: int
    kind: str
    quantity: int
    created_tick: int
    spoil_due: int | None = None


@dataclass
class Tool:
    id: int
    kind: str  # axe | pickaxe | hoe | fishing | spear | water
    tier: str  # basic | better
    durability: int


class Inventory:
    """Item lots (with age) and tools. Moves between inventories only via transfer_items."""

    def __init__(self, ids: dict[str, int] | None = None) -> None:
        self.lots: list[Lot] = []
        self.tools: list[Tool] = []
        self.ids: dict[str, int] = ids if ids is not None else {}

    def _next(self, name: str) -> int:
        value = self.ids.get(name, 1)
        self.ids[name] = value + 1
        return value

    def count(self, kind: str) -> int:
        return sum(lot.quantity for lot in self.lots if lot.kind == kind)

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for lot in self.lots:
            out[lot.kind] = out.get(lot.kind, 0) + lot.quantity
        return dict(sorted(out.items()))

    def total_items(self) -> int:
        return sum(lot.quantity for lot in self.lots)

    def is_empty(self) -> bool:
        return not self.lots and not self.tools

    def _put(self, kind: str, qty: int, created: int, spoil_due: int | None) -> None:
        for lot in self.lots:
            if lot.kind == kind and lot.created_tick == created and lot.spoil_due == spoil_due:
                lot.quantity += qty
                return
        self.lots.append(Lot(self._next("lot"), kind, qty, created, spoil_due))

    def add(self, kind: str, n: int, tick: int) -> None:
        """Add ``n`` fresh items of ``kind`` (spoil time from balance.toml)."""
        if n <= 0:
            return
        span = SPOIL_TICKS.get(kind)
        self._put(kind, n, tick, None if span is None else tick + span)

    def take(self, kind: str, n: int) -> list[tuple[int, int, int | None]]:
        """Remove ``n`` of ``kind``, oldest first; returns (quantity, created, spoil_due)."""
        pieces: list[tuple[int, int, int | None]] = []
        need = n
        for lot in sorted(self.lots, key=lambda lt: (lt.created_tick, lt.id)):
            if lot.kind != kind or need <= 0:
                continue
            got = min(need, lot.quantity)
            lot.quantity -= got
            need -= got
            pieces.append((got, lot.created_tick, lot.spoil_due))
        self.lots = [lot for lot in self.lots if lot.quantity > 0]
        return pieces

    def remove(self, kind: str, n: int) -> bool:
        """Consume ``n`` of ``kind`` (False and no change if there are not enough)."""
        if self.count(kind) < n:
            return False
        self.take(kind, n)
        return True

    def spoil(self, tick: int) -> int:
        """Turn lots whose spoil time has come into spoiled meat; returns how many items."""
        expired = [lot for lot in self.lots if lot.spoil_due is not None and lot.spoil_due <= tick]
        if not expired:
            return 0
        self.lots = [lot for lot in self.lots if lot not in expired]
        for lot in expired:
            self._put(
                SPOIL_INTO.get(lot.kind, "spoiled_meat"), lot.quantity, lot.created_tick, None
            )
        return sum(lot.quantity for lot in expired)

    def food_units(self, values: dict[str, float] | None = None) -> float:
        table = FOOD_UNITS if values is None else values
        return sum(lot.quantity * table.get(lot.kind, 0.0) for lot in self.lots)

    def add_tool(self, kind: str, tier: str, durability: int) -> Tool:
        tool = Tool(self._next("tool"), kind, tier, durability)
        self.tools.append(tool)
        return tool

    def find_tool(self, kind: str) -> Tool | None:
        """The best tool of ``kind`` carried (better tier first, then lowest id)."""
        found = [t for t in self.tools if t.kind == kind]
        found.sort(key=lambda t: (t.tier != "better", t.id))
        return found[0] if found else None

    def tool_by_id(self, tool_id: int) -> Tool | None:
        for tool in self.tools:
            if tool.id == tool_id:
                return tool
        return None

    def to_state(self) -> dict[str, Any]:
        return {
            "lots": [[x.id, x.kind, x.quantity, x.created_tick, x.spoil_due] for x in self.lots],
            "tools": [[t.id, t.kind, t.tier, t.durability] for t in self.tools],
        }

    @classmethod
    def from_state(cls, ids: dict[str, int], state: dict[str, Any]) -> Inventory:
        inv = cls(ids)
        inv.lots = [Lot(*row) for row in state["lots"]]
        inv.tools = [Tool(*row) for row in state["tools"]]
        return inv


def transfer_items(
    world: World | None,
    src: Inventory,
    dst: Inventory,
    items: dict[str, int],
    tools: list[int],
) -> bool:
    """Move exact quantities and tools from ``src`` to ``dst``; all or nothing.

    Lots keep their age. A failed transfer changes nothing.
    """
    for kind, n in items.items():
        if n <= 0 or kind not in ITEM_KINDS or src.count(kind) < n:
            return False
    if len(set(tools)) != len(tools):
        return False
    moving = []
    for tool_id in tools:
        tool = src.tool_by_id(tool_id)
        if tool is None:
            return False
        moving.append(tool)
    if src is dst:
        return True
    for kind, n in items.items():
        for qty, created, spoil in src.take(kind, n):
            dst._put(kind, qty, created, spoil)
    for tool in moving:
        src.tools.remove(tool)
        dst.tools.append(tool)
    return True


def transfer_all(src: Inventory, dst: Inventory) -> None:
    """Move everything (used for death drops and storage)."""
    for kind, n in src.counts().items():
        transfer_items(None, src, dst, {kind: n}, [])
    transfer_items(None, src, dst, {}, [t.id for t in src.tools])


# --------------------------------------------------------------------------------- bodies


@dataclass
class Body:
    hunger: float = 0.0
    thirst: float = 0.0
    cold: float = 0.0
    fatigue: float = 0.0
    pain: float = 0.0  # 0 = fine
    health: float = 100.0  # 100 = well
    sickness: str | None = None
    sickness_until: int = 0

    def to_state(self) -> list[Any]:
        return [
            self.hunger,
            self.thirst,
            self.cold,
            self.fatigue,
            self.pain,
            self.health,
            self.sickness,
            self.sickness_until,
        ]

    @classmethod
    def from_state(cls, row: list[Any]) -> Body:
        return cls(*row)


# ---------------------------------------------------------------------------------- others


class PromiseSpec(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    kind: Literal["give", "not_harm"]
    to: str
    item: str | None = None
    amount: int | None = Field(default=None, gt=0)
    due_tick: int


@dataclass
class KnowledgeEntry:
    id: int
    subject: str
    claim: str
    confidence: float
    source: str  # "self" | "taught:<id>" | "overheard:<id>"
    learned_tick: int
    true: bool | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")


@dataclass
class HarmRecord:
    id: int
    tick: int
    kind: str  # steal | sabotage | attack | chase_off | pull_stakes | capture | poach
    actor: str
    victim: str
    x: int
    y: int
    saw: list[str] = field(default_factory=list)
    heard: list[str] = field(default_factory=list)
    processed: bool = False


@dataclass
class Interrupt:
    id: int
    kind: str  # spoken_to attacked hurt player_in_sight dog_in_sight storm_started ...
    player: str
    tick: int
    source: str | None = None
    detail: str = ""


@dataclass
class Utterance:
    speaker: str
    targets: list[str]
    text: str
    kind: str = "talk"  # talk | teach | trade | line | gossip
    ref: int | None = None


@dataclass
class Offer:
    id: int
    kind: str  # "trade" | "ally"
    maker: str
    target: str
    give: dict[str, int]
    want: dict[str, int]
    tick: int
    expires: int
    give_tools: list[int] = field(default_factory=list)
    want_tools: list[int] = field(default_factory=list)


@dataclass
class Promise:
    id: int
    maker: str
    to: str
    kind: str
    item: str | None
    amount: int | None
    due_tick: int
    text: str
    made_tick: int
    status: str = "open"  # open | kept | broken
    given: int = 0  # how much of a "give" promise has been handed over


@dataclass
class ActiveAction:
    id: int
    request: ActionRequest
    start_tick: int
    units_done: int = 0
    work_done: float = 0.0
    next_unit_due: int = 0
    route: list[Pos] = field(default_factory=list)
    route_index: int = 0
    status: str = "walking"  # walking | working | done
    data: dict[str, Any] = field(default_factory=dict)

    def to_state(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "request": self.request.model_dump(mode="json"),
            "start": self.start_tick,
            "units": self.units_done,
            "work": self.work_done,
            "due": self.next_unit_due,
            "route": [list(p) for p in self.route],
            "ri": self.route_index,
            "status": self.status,
            "data": self.data,
        }

    @classmethod
    def from_state(cls, s: dict[str, Any]) -> ActiveAction:
        from ai_island.rules.actions.request import ActionRequest

        return cls(
            s["id"],
            ActionRequest.model_validate(s["request"]),
            s["start"],
            s["units"],
            s["work"],
            s["due"],
            [(p[0], p[1]) for p in s["route"]],
            s["ri"],
            s["status"],
            dict(s["data"]),
        )


@dataclass
class Structure:
    id: int
    kind: str
    x: int
    y: int
    owner: str
    hp: int
    max_hp: int
    complete: bool = False
    progress: float = 0.0
    contributors: dict[str, int] = field(default_factory=dict)
    store: Inventory | None = None
    fuel_until: int = 0
    belief: bool = False  # a shrine built through build_shrine

    def damaged(self, share: float) -> bool:
        return self.hp < self.max_hp * share

    def burning(self, tick: int) -> bool:
        return self.complete and self.fuel_until > tick

    def to_state(self) -> list[Any]:
        return [
            self.id,
            self.kind,
            self.x,
            self.y,
            self.owner,
            self.hp,
            self.max_hp,
            self.complete,
            self.progress,
            self.contributors,
            None if self.store is None else self.store.to_state(),
            self.fuel_until,
            self.belief,
        ]

    @classmethod
    def from_state(cls, ids: dict[str, int], row: list[Any]) -> Structure:
        store = None if row[10] is None else Inventory.from_state(ids, row[10])
        return cls(
            row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[8],
            {k: int(v) for k, v in row[9].items()}, store, row[11], row[12],
        )  # fmt: skip


@dataclass
class Player:
    id: str
    index: int
    name: str
    x: int
    y: int
    from_x: int = -1
    from_y: int = -1
    to_x: int = -1
    to_y: int = -1
    move_start_tick: int = 0
    move_end_tick: int = 0
    facing: int = 1
    body: Body = field(default_factory=Body)
    inventory: Inventory = field(default_factory=Inventory)
    home_store: Inventory = field(default_factory=Inventory)
    b: float = 0.0
    b_tick: int = 0
    band: str = "all_right"
    hooked: bool = False
    trust: dict[str, float] = field(default_factory=dict)
    anger: dict[str, float] = field(default_factory=dict)
    action: ActiveAction | None = None
    last_decision_tick: int = 0
    knowledge: list[KnowledgeEntry] = field(default_factory=list)
    allies: list[str] = field(default_factory=list)
    task_stage: int = 1
    task_receipts: list[int] = field(default_factory=list)
    slots: int = 6
    place_memory: dict[str, Any] = field(default_factory=dict)
    seen_ids: list[str] = field(default_factory=list)
    known_culprits: dict[int, str] = field(default_factory=dict)
    alive: bool = True
    x_minute_sum: float = 0.0
    x_minutes: int = 0
    x_hourly: list[float] = field(default_factory=list)
    x_hour_sum: float = 0.0
    x_hour_n: int = 0
    sleeping: bool = False
    last_harm_tick: int = -(10**9)
    achievements: int = 0
    pending_rewards: list[str] = field(default_factory=list)
    just_finished: bool = False

    def __post_init__(self) -> None:
        if self.from_x < 0:
            self.from_x = self.to_x = self.x
            self.from_y = self.to_y = self.y


@dataclass
class Villager:
    id: str
    name: str
    leader: str | None
    x: int
    y: int
    from_x: int = -1
    from_y: int = -1
    to_x: int = -1
    to_y: int = -1
    move_start_tick: int = 0
    move_end_tick: int = 0
    facing: int = 1
    body: Body = field(default_factory=Body)
    inventory: Inventory = field(default_factory=Inventory)
    loyalty: float = 70.0
    bond: dict[str, float] = field(default_factory=dict)
    job: str | None = None
    work_level: str = "normal"
    job_x: int = -1
    job_y: int = -1
    hungry_minutes: int = 0
    hard_minutes: int = 0
    adverse_days: dict[str, int] = field(default_factory=dict)
    witnessed: list[int] = field(default_factory=list)
    alive: bool = True
    captive: bool = False
    captor: str | None = None
    route: list[Pos] = field(default_factory=list)
    route_index: int = 0
    next_think: int = 0
    work_acc: float = 0.0
    last_line_tick: int = -(10**9)

    def __post_init__(self) -> None:
        if self.from_x < 0:
            self.from_x = self.to_x = self.x
            self.from_y = self.to_y = self.y


def inventory_ids(world: World) -> dict[str, int]:
    return world.ids
