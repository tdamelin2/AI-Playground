"""Typed events: a discriminated union of payload models.

``Event(tick, type, payload)``: ``type`` names the payload model; ``payload`` may be given
as a dict or as the model itself. Payloads are strict and reject unknown fields.
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WorldCreated(_Payload):
    type: Literal["world_created"] = "world_created"
    seed: int
    width: int
    height: int


class SeasonChanged(_Payload):
    type: Literal["season_changed"] = "season_changed"
    season: str
    year: int


class WeatherChanged(_Payload):
    type: Literal["weather_changed"] = "weather_changed"
    weather: str
    previous: str | None
    season: str


class DaySummary(_Payload):
    type: Literal["day_summary"] = "day_summary"
    year: int
    day: int
    season: str
    weather: str
    animals: dict[str, int]
    plants: dict[str, int]
    trees: dict[str, int]
    dogs: int
    farmland: dict[str, int]


class TreeCut(_Payload):
    type: Literal["tree_cut"] = "tree_cut"
    x: int
    y: int
    area: str
    trees_left: int


class TreeRegrown(_Payload):
    type: Literal["tree_regrown"] = "tree_regrown"
    x: int
    y: int
    area: str


class StoneTaken(_Payload):
    type: Literal["stone_taken"] = "stone_taken"
    x: int
    y: int
    taken: int
    remaining: int


class CropChanged(_Payload):
    type: Literal["crop_changed"] = "crop_changed"
    x: int
    y: int
    state: str


class PlantRemoved(_Payload):
    type: Literal["plant_removed"] = "plant_removed"
    plant_id: int
    kind: str
    x: int
    y: int


class PlantRegrown(_Payload):
    type: Literal["plant_regrown"] = "plant_regrown"
    plant_id: int
    kind: str
    x: int
    y: int


class AnimalsBorn(_Payload):
    type: Literal["animals_born"] = "animals_born"
    kind: str
    zone: str
    count: int


class AnimalsRemoved(_Payload):
    type: Literal["animals_removed"] = "animals_removed"
    kind: str
    zone: str
    count: int


class LocalExtinction(_Payload):
    type: Literal["local_extinction"] = "local_extinction"
    kind: str
    zone: str
    absent_until: int


class AnimalsReturned(_Payload):
    type: Literal["animals_returned"] = "animals_returned"
    kind: str
    zone: str
    count: int


class DogBorn(_Payload):
    type: Literal["dog_born"] = "dog_born"
    pack: int
    dog_id: int


class ActionStarted(_Payload):
    type: Literal["action_started"] = "action_started"
    player: str
    kind: str


class ActionFinished(_Payload):
    type: Literal["action_finished"] = "action_finished"
    player: str
    kind: str
    units: int
    result: str


class ActionFailed(_Payload):
    type: Literal["action_failed"] = "action_failed"
    player: str
    kind: str
    reason: str


class InterruptRaised(_Payload):
    type: Literal["interrupt"] = "interrupt"
    id: int
    kind: str
    player: str
    source: str | None = None
    detail: str = ""


class ChatSpoken(_Payload):
    type: Literal["chat_spoken"] = "chat_spoken"
    speaker: str
    targets: list[str]
    hearers: list[str]
    text: str
    kind: str


class Harm(_Payload):
    type: Literal["harm"] = "harm"
    id: int
    kind: str
    actor: str
    victim: str
    x: int
    y: int


class Witnessed(_Payload):
    type: Literal["witnessed"] = "witnessed"
    id: int
    saw: list[str]
    heard: list[str]


class CulpritLearned(_Payload):
    type: Literal["culprit_learned"] = "culprit_learned"
    player: str
    harm_id: int
    culprit: str
    how: str = ""


class Died(_Payload):
    type: Literal["died"] = "died"
    player: str
    cause: str
    x: int
    y: int


class Respawned(_Payload):
    type: Literal["respawned"] = "respawned"
    player: str
    x: int
    y: int


class Sickness(_Payload):
    type: Literal["sickness"] = "sickness"
    who: str
    kind: str
    until: int


class BandChanged(_Payload):
    type: Literal["band_changed"] = "band_changed"
    player: str
    old: str
    new: str


class XGain(_Payload):
    type: Literal["x_gain"] = "x_gain"
    player: str
    amount: float
    reason: str


class VillagerJoined(_Payload):
    type: Literal["villager_joined"] = "villager_joined"
    villager: str
    leader: str
    source: str = ""


class VillagerLeft(_Payload):
    type: Literal["villager_left"] = "villager_left"
    villager: str
    leader: str
    to: str | None
    reason: str
    hungry_days: int
    hard_days: int


class VillagerDied(_Payload):
    type: Literal["villager_died"] = "villager_died"
    villager: str
    leader: str | None
    cause: str
    x: int
    y: int


class Grief(_Payload):
    type: Literal["grief"] = "grief"
    player: str
    villager: str
    amount: float


class TaskDone(_Payload):
    type: Literal["task_done"] = "task_done"
    player: str
    stage: int
    task: str


class StageDone(_Payload):
    type: Literal["stage_done"] = "stage_done"
    player: str
    stage: int


class CoopBonus(_Payload):
    type: Literal["coop_bonus"] = "coop_bonus"
    player: str
    structure: int
    kind: str
    amount: float


class DominanceBonus(_Payload):
    type: Literal["dominance_bonus"] = "dominance_bonus"
    player: str
    landmark: str
    week: int
    amount: float


class BeliefAct(_Payload):
    type: Literal["belief_act"] = "belief_act"
    player: str
    kind: str
    text: str = ""
    x: int = -1
    y: int = -1


class PromiseMade(_Payload):
    type: Literal["promise_made"] = "promise_made"
    id: int
    maker: str
    to: str
    kind: str
    text: str = ""


class PromiseKept(_Payload):
    type: Literal["promise_kept"] = "promise_kept"
    id: int
    maker: str
    to: str


class PromiseBroken(_Payload):
    type: Literal["promise_broken"] = "promise_broken"
    id: int
    maker: str
    to: str
    reason: str = ""


class TradeOffered(_Payload):
    type: Literal["trade_offered"] = "trade_offered"
    id: int
    kind: str
    maker: str
    target: str
    give: dict[str, int]
    want: dict[str, int]


class TradeDone(_Payload):
    type: Literal["trade_done"] = "trade_done"
    id: int
    kind: str
    maker: str
    target: str


class DogAttack(_Payload):
    type: Literal["dog_attack"] = "dog_attack"
    dog: int
    victim: str
    x: int
    y: int
    damage: float


class DogScared(_Payload):
    type: Literal["dog_scared"] = "dog_scared"
    dog: int
    by: str


class PlayerDay(_Payload):
    type: Literal["player_day"] = "player_day"
    player: str
    day: int
    x_hourly: list[float]
    x_mean: float
    x_median: float
    band: str
    home_food_units: float
    household_need: float
    food_stored: float
    villagers: int
    alive: bool
    villager_loyalty: float | None = None  # mean loyalty of the living villagers (None if none)


class Helped(_Payload):
    """One act that helped another player; emitted once per action at its first effect."""

    type: Literal["helped"] = "helped"
    actor: str
    target: str
    kind: Literal["gift", "use_herb", "teach", "build", "repair", "build_shrine"]
    action_id: int


class StructureBuilt(_Payload):
    type: Literal["structure_built"] = "structure_built"
    id: int
    kind: str
    owner: str
    x: int
    y: int


class StructureDamaged(_Payload):
    type: Literal["structure_damaged"] = "structure_damaged"
    id: int
    kind: str
    hp: int


class ItemsMoved(_Payload):
    type: Literal["items_moved"] = "items_moved"
    kind: str
    src: str
    dst: str
    items: dict[str, int]


class LandClaimed(_Payload):
    type: Literal["land_claimed"] = "land_claimed"
    player: str
    x: int
    y: int
    tiles: int


class RewardPending(_Payload):
    type: Literal["reward_pending"] = "reward_pending"
    player: str
    kind: str


class ToolBroken(_Payload):
    type: Literal["tool_broken"] = "tool_broken"
    player: str
    tool: str
    tier: str


class DecisionMade(_Payload):
    type: Literal["decision_made"] = "decision_made"
    player: str
    decision_key: str
    tier: str
    trigger: str
    situation: str
    action: str
    self_label: str | None = None
    source: Literal["model", "code", "fallback"]
    failure: Literal["format", "refusal"] | None = None
    choice_point: bool = False


class ValueRepaired(_Payload):
    type: Literal["value_repaired"] = "value_repaired"
    player: str
    problems: list[str]


class ValueViolation(_Payload):
    type: Literal["value_violation"] = "value_violation"
    player: str
    decision_key: str
    violated: list[str]
    direction: str


class MistakeFlagged(_Payload):
    type: Literal["mistake_flagged"] = "mistake_flagged"
    player: str
    decision_key: str
    expected_delta: float
    actual_delta: float


class ReflectionCompleted(_Payload):
    type: Literal["reflection_completed"] = "reflection_completed"
    player: str
    week: int
    changes: dict[str, list[float]]
    invented: str | None = None


class InventionRejected(_Payload):
    type: Literal["invention_rejected"] = "invention_rejected"
    player: str
    week: int
    name: str
    reason: str


Payload = Annotated[
    WorldCreated
    | SeasonChanged
    | WeatherChanged
    | DaySummary
    | TreeCut
    | TreeRegrown
    | StoneTaken
    | CropChanged
    | PlantRemoved
    | PlantRegrown
    | AnimalsBorn
    | AnimalsRemoved
    | LocalExtinction
    | AnimalsReturned
    | DogBorn
    | ActionStarted
    | ActionFinished
    | ActionFailed
    | InterruptRaised
    | ChatSpoken
    | Harm
    | Witnessed
    | CulpritLearned
    | Died
    | Respawned
    | Sickness
    | BandChanged
    | XGain
    | VillagerJoined
    | VillagerLeft
    | VillagerDied
    | Grief
    | TaskDone
    | StageDone
    | CoopBonus
    | DominanceBonus
    | BeliefAct
    | PromiseMade
    | PromiseKept
    | PromiseBroken
    | TradeOffered
    | TradeDone
    | DogAttack
    | DogScared
    | PlayerDay
    | Helped
    | StructureBuilt
    | StructureDamaged
    | ItemsMoved
    | LandClaimed
    | RewardPending
    | ToolBroken
    | DecisionMade
    | ValueRepaired
    | ValueViolation
    | MistakeFlagged
    | ReflectionCompleted
    | InventionRejected,
    Field(discriminator="type"),
]

PAYLOAD_TYPES: dict[str, type[_Payload]] = {
    cls.model_fields["type"].default: cls
    for cls in (
        WorldCreated,
        SeasonChanged,
        WeatherChanged,
        DaySummary,
        TreeCut,
        TreeRegrown,
        StoneTaken,
        CropChanged,
        PlantRemoved,
        PlantRegrown,
        AnimalsBorn,
        AnimalsRemoved,
        LocalExtinction,
        AnimalsReturned,
        DogBorn,
        ActionStarted,
        ActionFinished,
        ActionFailed,
        InterruptRaised,
        ChatSpoken,
        Harm,
        Witnessed,
        CulpritLearned,
        Died,
        Respawned,
        Sickness,
        BandChanged,
        XGain,
        VillagerJoined,
        VillagerLeft,
        VillagerDied,
        Grief,
        TaskDone,
        StageDone,
        CoopBonus,
        DominanceBonus,
        BeliefAct,
        PromiseMade,
        PromiseKept,
        PromiseBroken,
        TradeOffered,
        TradeDone,
        DogAttack,
        DogScared,
        PlayerDay,
        Helped,
        StructureBuilt,
        StructureDamaged,
        ItemsMoved,
        LandClaimed,
        RewardPending,
        ToolBroken,
        DecisionMade,
        ValueRepaired,
        ValueViolation,
        MistakeFlagged,
        ReflectionCompleted,
        InventionRejected,
    )
}


class Event(BaseModel):
    """One logged event. ``id`` is set by the database when the event is stored."""

    model_config = ConfigDict(extra="forbid")

    id: int | None = None
    tick: int = Field(ge=0)
    type: str
    payload: Payload

    @model_validator(mode="before")
    @classmethod
    def _fill_type(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        data = dict(data)
        payload = data.get("payload")
        if isinstance(payload, BaseModel):
            data.setdefault("type", getattr(payload, "type", None))
        elif isinstance(payload, dict):
            kind = data.get("type")
            if kind is None:
                kind = payload.get("type")
            if kind not in PAYLOAD_TYPES:
                raise ValueError(f"unknown event type '{kind}'")
            data["type"] = kind
            data["payload"] = {**payload, "type": kind}
        return data

    @model_validator(mode="after")
    def _check_type(self) -> Event:
        if self.payload.type != self.type:
            raise ValueError(f"event type '{self.type}' does not match its payload")
        return self

    def payload_json(self) -> str:
        """Canonical JSON of the payload (without the type, which has its own column)."""
        data = self.payload.model_dump(mode="json", exclude={"type"})
        return json.dumps(data, sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_row(cls, row_id: int, tick: int, kind: str, payload_json: str) -> Event:
        return cls(id=row_id, tick=tick, type=kind, payload=json.loads(payload_json))
