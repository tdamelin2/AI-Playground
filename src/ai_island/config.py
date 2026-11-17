"""Strict configuration models and the TOML loader.

Every tunable number lives in ``config/*.toml``. All models reject unknown keys at every
level and do not coerce types (a bool is not an int, a string is not a number).
"""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

SEASONS: tuple[str, ...] = ("spring", "summer", "autumn", "winter")
WEATHERS: tuple[str, ...] = ("clear", "rain", "storm", "drought")
TERRAIN_KEYS: tuple[str, ...] = (
    "grass",
    "sand",
    "tree",
    "stump",
    "spring",
    "lake",
    "coast",
    "farmland_empty",
    "farmland_planted",
    "farmland_growing",
    "farmland_ready",
    "farmland_failed",
    "rocky",
    "rocky_depleted",
    "quarry",
    "quarry_depleted",
)
PLANT_KINDS: tuple[str, ...] = (
    "berries",
    "mushrooms",
    "roots",
    "herbs",
    "healing_herbs",
    "mild_poison",
    "strong_poison",
)
ANIMAL_KINDS: tuple[str, ...] = (
    "rabbit",
    "deer",
    "boar",
    "fish",
    "bird",
    "nest_eggs",
    "goat",
    "chicken",
)
ZONE_TYPES: tuple[str, ...] = ("home", "centre", "buffer")

Season = Literal["spring", "summer", "autumn", "winter"]
PosInt = Annotated[int, Field(gt=0)]
NonNegInt = Annotated[int, Field(ge=0)]
PosFloat = Annotated[float, Field(gt=0, allow_inf_nan=False)]
NonNegFloat = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Chance = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class ConfigError(Exception):
    """A config file is invalid. The message names the file and the dotted key."""


class Strict(BaseModel):
    """Base for every config model: no coercion, no unknown keys."""

    model_config = ConfigDict(strict=True, extra="forbid")


# --------------------------------------------------------------------------- world.toml


class ClockConfig(Strict):
    ticks_per_day: PosInt
    days_per_week: PosInt
    days_per_season: PosInt
    night_start_hour: Annotated[int, Field(ge=0, le=23)]
    night_end_hour: Annotated[int, Field(ge=0, le=23)]
    dawn_minutes: PosInt
    dusk_minutes: PosInt

    @model_validator(mode="after")
    def _check(self) -> ClockConfig:
        day_minutes = ((self.night_start_hour - self.night_end_hour) % 24) * 60
        if self.dawn_minutes + self.dusk_minutes > day_minutes:
            raise ValueError("dawn_minutes + dusk_minutes must fit in the daylight hours")
        if self.days_per_season % self.days_per_week:
            raise ValueError("days_per_season must be a whole number of weeks")
        if self.ticks_per_day % 60:
            raise ValueError("ticks_per_day must be a multiple of 60")
        return self

    @property
    def season_ticks(self) -> int:
        return self.ticks_per_day * self.days_per_season

    @property
    def year_ticks(self) -> int:
        return self.season_ticks * len(SEASONS)


class MapConfig(Strict):
    width: PosInt
    height: PosInt
    coast_width: NonNegInt
    sand_width: NonNegInt
    home_size: PosInt
    home_margin: PosInt
    centre_size: PosInt
    buffer_forest_clumps: NonNegInt
    buffer_forest_radius: PosInt
    buffer_forest_density: Chance
    buffer_rocky_tiles: NonNegInt
    buffer_stray_trees: NonNegInt

    @model_validator(mode="after")
    def _check(self) -> MapConfig:
        if self.home_margin <= self.coast_width + self.sand_width:
            raise ValueError("map.home_margin must be larger than coast_width + sand_width")
        if 2 * (self.home_margin + self.home_size) >= min(self.width, self.height):
            raise ValueError("map: the four homes do not fit with a gap between them")
        start_x = (self.width - self.centre_size) // 2
        start_y = (self.height - self.centre_size) // 2
        edge = self.home_margin + self.home_size
        if start_x <= edge and start_y <= edge:
            raise ValueError("map.centre_size: the centre overlaps a home plot")
        return self


class HomeConfig(Strict):
    tree_tiles: NonNegInt
    spring_tiles: PosInt
    farmland_width: PosInt
    farmland_height: PosInt
    rocky_tiles: NonNegInt


class CentreConfig(Strict):
    forest_clumps: PosInt
    forest_radius: PosInt
    forest_density: Chance
    farmland_width: PosInt
    farmland_height: PosInt
    lake_width: PosInt
    lake_height: PosInt
    quarry_size: PosInt
    rocky_tiles: NonNegInt


class LandConfig(Strict):
    pool_zones: list[str]

    @model_validator(mode="after")
    def _check(self) -> LandConfig:
        if not self.pool_zones:
            raise ValueError("land.pool_zones must not be empty")
        if len(set(self.pool_zones)) != len(self.pool_zones):
            raise ValueError("land.pool_zones has duplicates")
        bad = [z for z in self.pool_zones if z not in ("buffer", "centre")]
        if bad:
            raise ValueError(f"land.pool_zones: {bad} not allowed (only 'buffer' or 'centre')")
        return self


class TerrainConfig(Strict):
    cost: dict[str, PosFloat]
    impassable: list[str]

    @model_validator(mode="after")
    def _check(self) -> TerrainConfig:
        for key in list(self.cost) + self.impassable:
            if key not in TERRAIN_KEYS:
                raise ValueError(f"terrain: unknown terrain key '{key}'")
        both = set(self.cost) & set(self.impassable)
        if both:
            raise ValueError(f"terrain: {sorted(both)} listed as both passable and impassable")
        missing = set(TERRAIN_KEYS) - set(self.cost) - set(self.impassable)
        if missing:
            raise ValueError(f"terrain: no cost or impassable entry for {sorted(missing)}")
        return self


class WeatherOdds(Strict):
    clear: NonNegFloat
    rain: NonNegFloat
    storm: NonNegFloat
    drought: NonNegFloat

    @model_validator(mode="after")
    def _check(self) -> WeatherOdds:
        total = self.clear + self.rain + self.storm + self.drought
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"weather odds must sum to 1, got {total}")
        return self


class WeatherConfig(Strict):
    interval_ticks: PosInt
    odds: dict[str, WeatherOdds]

    @model_validator(mode="after")
    def _check(self) -> WeatherConfig:
        if set(self.odds) != set(SEASONS):
            raise ValueError(f"weather.odds must have exactly the seasons {list(SEASONS)}")
        return self


class PlantWorld(Strict):
    seasons: list[Season]
    per_home: NonNegInt
    per_centre: NonNegInt
    per_buffer: NonNegInt


class ZoneCounts(Strict):
    home: NonNegInt
    centre: NonNegInt
    buffer: NonNegInt


class AnimalWorld(Strict):
    habitat: list[str]
    initial: ZoneCounts
    capacity: ZoneCounts
    breed_seasons: list[Season]
    parent_kind: str | None = None
    present_seasons: list[Season] | None = None

    @model_validator(mode="after")
    def _check(self) -> AnimalWorld:
        for key in self.habitat:
            if key not in TERRAIN_KEYS:
                raise ValueError(f"animals: unknown habitat terrain '{key}'")
        if self.parent_kind is not None and self.parent_kind not in ANIMAL_KINDS:
            raise ValueError(f"animals: unknown parent_kind '{self.parent_kind}'")
        return self


class DogWorld(Strict):
    pack_min: PosInt
    pack_max: PosInt
    initial_packs_centre: NonNegInt
    initial_packs_buffer: NonNegInt

    @model_validator(mode="after")
    def _check(self) -> DogWorld:
        if self.pack_min > self.pack_max:
            raise ValueError("dogs: pack_min is larger than pack_max")
        return self


class WorldConfig(Strict):
    clock: ClockConfig
    map: MapConfig
    home: HomeConfig
    centre: CentreConfig
    land: LandConfig
    terrain: TerrainConfig
    weather: WeatherConfig
    plants: dict[str, PlantWorld]
    animals: dict[str, AnimalWorld]
    dogs: DogWorld

    @model_validator(mode="after")
    def _check(self) -> WorldConfig:
        if self.clock.season_ticks % self.weather.interval_ticks:
            raise ValueError("weather.interval_ticks must divide the season length")
        if set(self.plants) != set(PLANT_KINDS):
            raise ValueError(f"plants must have exactly the kinds {list(PLANT_KINDS)}")
        if set(self.animals) != set(ANIMAL_KINDS):
            raise ValueError(f"animals must have exactly the kinds {list(ANIMAL_KINDS)}")
        return self


# ------------------------------------------------------------------------- balance.toml


class TreeBalance(Strict):
    regrow_ticks: PosInt
    overcut_threshold: Chance


class StoneBalance(Strict):
    rocky_stone: PosInt
    quarry_stone: PosInt


class WaterBalance(Strict):
    spring_output: PosFloat
    lake_output: PosFloat
    multiplier: dict[str, PosFloat]

    @model_validator(mode="after")
    def _check(self) -> WaterBalance:
        if set(self.multiplier) != set(WEATHERS):
            raise ValueError(f"water.multiplier must have exactly {list(WEATHERS)}")
        return self


class CropBalance(Strict):
    planted_ticks: PosInt
    growing_ticks: PosInt
    ready_spoil_ticks: PosInt
    failed_reset_ticks: PosInt
    growing_seasons: list[Season]


class PlantBalance(Strict):
    regrow_ticks: PosInt


class MovementBalance(Strict):
    movement_step_ticks: PosInt
    max_start_share: Annotated[float, Field(gt=0, le=1, allow_inf_nan=False)]

    @model_validator(mode="after")
    def _check(self) -> MovementBalance:
        if self.movement_step_ticks != 1:
            raise ValueError("movement_step_ticks must be 1 in this phase")
        return self


_MOVE_KEYS: tuple[str, ...] = (
    "minutes_per_tile",
    "bout_min_tiles",
    "bout_max_tiles",
    "rest_min_minutes",
    "rest_max_minutes",
    "flee_minutes_per_tile",
)


def _check_move_ranges(name: str, m: Any) -> None:
    if m.bout_min_tiles > m.bout_max_tiles:
        raise ValueError(f"{name}.bout_min_tiles is larger than bout_max_tiles")
    if m.rest_min_minutes > m.rest_max_minutes:
        raise ValueError(f"{name}.rest_min_minutes is larger than rest_max_minutes")


class AnimalBalance(Strict):
    breed_interval: PosInt
    birth_chance: Chance
    flees_dogs: bool
    flee_radius: NonNegInt
    recolonise_count: NonNegInt
    moves: bool = True
    minutes_per_tile: PosInt | None = None
    bout_min_tiles: PosInt | None = None
    bout_max_tiles: PosInt | None = None
    rest_min_minutes: PosInt | None = None
    rest_max_minutes: PosInt | None = None
    flee_minutes_per_tile: PosInt | None = None

    @model_validator(mode="after")
    def _check(self) -> AnimalBalance:
        given = [k for k in _MOVE_KEYS if getattr(self, k) is not None]
        if not self.moves:
            if given:
                raise ValueError(f"moves = false: movement keys {given} must not be present")
            return self
        for key in _MOVE_KEYS[:5]:
            if getattr(self, key) is None:
                raise ValueError(f"{key} is required when moves is true")
        _check_move_ranges("animal", self)
        if self.flees_dogs:
            if self.flee_minutes_per_tile is None:
                raise ValueError("flee_minutes_per_tile is required when flees_dogs is true")
            if self.flee_minutes_per_tile >= self.minutes_per_tile:  # type: ignore[operator]
                raise ValueError("flee_minutes_per_tile must be smaller than minutes_per_tile")
        elif self.flee_minutes_per_tile is not None:
            raise ValueError("flee_minutes_per_tile is only allowed when flees_dogs is true")
        return self


class DogBalance(Strict):
    max_pack_size: PosInt
    max_total: PosInt
    minutes_per_tile: PosInt
    bout_min_tiles: PosInt
    bout_max_tiles: PosInt
    rest_min_minutes: PosInt
    rest_max_minutes: PosInt
    night_multiplier: Annotated[float, Field(ge=1, allow_inf_nan=False)]
    winter_multiplier: Annotated[float, Field(ge=1, allow_inf_nan=False)]
    cohesion: PosInt
    breed_interval: PosInt
    birth_chance: Chance

    @model_validator(mode="after")
    def _check(self) -> DogBalance:
        _check_move_ranges("dogs", self)
        return self


class SicknessBalance(Strict):
    duration_ticks: PosInt
    health_loss_per_hour: NonNegFloat
    pain_per_hour: NonNegFloat
    onset_blow: NonNegFloat
    work_penalty: Annotated[float, Field(gt=0, le=1, allow_inf_nan=False)]


class BodyBalance(Strict):
    interval_ticks: PosInt
    hunger_per_day: PosFloat
    thirst_per_day: PosFloat
    fatigue_per_day: PosFloat
    rest_recovery_per_hour: PosFloat
    cold_night_per_hour: NonNegFloat
    cold_winter_per_hour: NonNegFloat
    cold_rain_per_hour: NonNegFloat
    cold_storm_per_hour: NonNegFloat
    cold_recovery_per_hour: PosFloat
    fire_warm_radius: PosInt
    shelter_radius: PosInt
    critical_level: PosFloat
    critical_health_loss_per_hour: NonNegFloat
    health_regen_per_hour: NonNegFloat
    regen_below: PosFloat
    pain_decay_per_hour: NonNegFloat
    hunger_per_food_unit: PosFloat
    thirst_per_water: PosFloat
    sated_level: NonNegFloat
    respawn_hunger: NonNegFloat
    respawn_thirst: NonNegFloat
    respawn_cold: NonNegFloat
    respawn_fatigue: NonNegFloat
    respawn_health: PosFloat
    respawn_pain: NonNegFloat
    death_x_loss: NonNegFloat
    herb_pain_relief: NonNegFloat
    herb_health: NonNegFloat
    healing_herb_pain_relief: NonNegFloat
    sickness: dict[str, SicknessBalance]

    @model_validator(mode="after")
    def _check(self) -> BodyBalance:
        if set(self.sickness) != {"mild_poison", "strong_poison", "raw_meat", "spoiled_meat"}:
            raise ValueError("body.sickness must have exactly the four sickness kinds")
        return self


class FoodBalance(Strict):
    values: dict[str, PosFloat]
    spoil_ticks: dict[str, PosInt]
    food_per_day: PosFloat
    sick_on_eat: dict[str, str]


class WellbeingBalance(Strict):
    k: PosFloat
    weights: dict[str, PosFloat]
    half_life_ticks: PosInt
    band_edges: list[PosFloat]
    band_names: list[str]
    speed_mult: list[PosFloat]
    work_mult: list[PosFloat]
    hooked_x: PosFloat
    hooked_pain: PosFloat
    trust_neutral: float
    anger_neutral: float
    trust_fade_per_day: NonNegFloat
    anger_fade_per_day: NonNegFloat
    start_trust: float
    shelter_base: Chance
    achievement_stages: PosInt
    task_stage_gain: NonNegFloat
    promise_kept_gain: NonNegFloat
    promise_broken_blow: NonNegFloat
    theft_blow: NonNegFloat
    attack_blow: NonNegFloat
    sabotage_blow: NonNegFloat
    chase_blow: NonNegFloat
    stakes_blow: NonNegFloat
    capture_blow: NonNegFloat
    poach_blow: NonNegFloat
    grief_base: NonNegFloat
    grief_bond_factor: NonNegFloat
    gift_gain: NonNegFloat
    trade_gain: NonNegFloat
    ally_gain: NonNegFloat

    @model_validator(mode="after")
    def _check(self) -> WellbeingBalance:
        keys = {
            "food", "water", "warmth", "rest", "health", "shelter", "safety",
            "achievement", "belonging",
        }  # fmt: skip
        if set(self.weights) != keys:
            raise ValueError(f"wellbeing.weights must have exactly {sorted(keys)}")
        if abs(sum(self.weights.values()) - 100.0) > 1e-9:
            raise ValueError("wellbeing.weights must add up to 100")
        if len(self.band_edges) != 4 or len(self.band_names) != 5:
            raise ValueError("wellbeing: 4 band_edges and 5 band_names")
        if len(self.speed_mult) != 5 or len(self.work_mult) != 5:
            raise ValueError("wellbeing: speed_mult and work_mult need 5 values")
        return self


class ActionsBalance(Strict):
    unit_minutes: dict[str, PosFloat]
    gather_yield: dict[str, PosInt]
    storm_pauses_outdoor: list[str]
    reach_tiles: PosInt
    walk_minutes_per_tile: PosFloat
    hand_mult: PosFloat
    default_amount: PosInt
    rest_chunk_minutes: PosInt
    hunt_chance: dict[str, Chance]
    spear_hunt_bonus: Chance
    hunt_yield: dict[str, PosInt]
    hunt_retries: PosInt
    boar_injury_chance: Chance
    boar_injury_health: NonNegFloat
    boar_injury_pain: NonNegFloat
    fish_chance: Chance
    fishing_bonus: Chance
    fish_yield: PosInt
    crop_yield: PosInt
    hoe_yield_bonus: NonNegInt
    farm_plant_units: PosInt
    cook_minutes_per_item: PosFloat
    tame_tries: PosInt
    tame_chance: Chance
    tame_bait_items: list[str]
    tame_kinds: list[str]
    pen_radius: PosInt
    pen_upkeep_food: PosFloat
    pen_missed_days: PosInt
    egg_per_day: PosInt
    milk_per_day: PosInt
    store_radius: PosInt
    build_site_radius: PosInt
    carry_limit: PosInt
    rain_work_mult: Annotated[float, Field(gt=0, le=1, allow_inf_nan=False)]
    storm_damage_blow: NonNegFloat

    @model_validator(mode="after")
    def _check(self) -> ActionsBalance:
        from ai_island.world.agents import ACTION_KINDS

        missing = [k for k in ACTION_KINDS if k not in self.unit_minutes]
        if missing:
            raise ValueError(f"actions.unit_minutes: missing {missing}")
        return self


class ToolsBalance(Strict):
    speed: dict[str, dict[str, PosFloat]]
    durability: dict[str, PosInt]
    recipes: dict[str, dict[str, dict[str, PosInt]]]
    repair_share: Chance
    wear_per_unit: PosInt
    pickaxe_kinds_required: list[str]
    stake_wood: PosInt


class FireBalance(Strict):
    fuel_ticks: PosInt
    campfire_wood: PosInt
    hearth_wood: PosInt
    refuel_wood: PosInt
    dog_scare_radius: PosInt
    sweep_interval_ticks: PosInt
    spoil_sweep_ticks: PosInt


class BuildingsBalance(Strict):
    costs: dict[str, dict[str, PosInt]]
    work_minutes: dict[str, PosInt]
    hp: dict[str, PosInt]
    damaged_share: Chance
    storm_damage_chance: Chance
    storm_damage_hp: PosInt
    repair_hp_per_unit: PosInt
    repair_unit_minutes: PosFloat
    coop_reward: NonNegFloat
    solo_reward: NonNegFloat
    joint_kinds: list[str]
    store_kinds: list[str]
    min_contributors_joint: PosInt

    @model_validator(mode="after")
    def _check(self) -> BuildingsBalance:
        from ai_island.world.agents import STRUCTURE_KINDS

        for name in ("costs", "work_minutes", "hp"):
            if set(getattr(self, name)) != set(STRUCTURE_KINDS):
                raise ValueError(f"buildings.{name} must have exactly the structure kinds")
        return self


class VillagersBalance(Strict):
    total: PosInt
    per_player: PosInt
    names: list[str]
    start_loyalty: PosFloat
    leave_below: PosFloat
    poach_loyalty: PosFloat
    recruit_loyalty: PosFloat
    think_ticks: PosInt
    walk_minutes_per_tile: PosFloat
    wander_chance: Chance
    wander_radius: PosInt
    home_radius: PosInt
    job_radius: PosInt
    cycle_ticks: PosInt
    output_mult: dict[str, PosFloat]
    hard_health_loss_per_hour: NonNegFloat
    hard_loyalty_loss_per_day: NonNegFloat
    light_loyalty_gain_per_day: NonNegFloat
    fed_loyalty_gain_per_day: NonNegFloat
    unfed_loyalty_loss_per_day: NonNegFloat
    comfort_level: PosFloat
    bond_start_leader: float
    bond_start_other: float
    bond_gain_per_day: NonNegFloat
    bond_loss_per_day: NonNegFloat
    adverse_days_to_log: PosInt
    guard_theft_reduction: Chance
    line_cooldown_ticks: PosInt
    forage_radius: PosInt
    wanderer_land_food_per_day: NonNegFloat
    critical_health_loss_per_hour: NonNegFloat
    captive_loyalty_loss_per_day: NonNegFloat


class DogAttackBalance(Strict):
    interval_ticks: PosInt
    hunt_radius: PosInt
    bite_health: PosFloat
    bite_pain: NonNegFloat
    cooldown_ticks: PosInt
    scare_group: PosInt
    group_radius: PosInt
    scared_ticks: PosInt
    flee_tiles: PosInt
    pen_kill_chance: Chance
    spear_scares: bool
    guard_scares: bool


class ClaimsBalance(Strict):
    claim_radius: PosInt
    stake_item_cost: PosInt
    min_gap_tiles: NonNegInt


class HarmBalance(Strict):
    reach_tiles: PosInt
    steal_chance: Chance
    guard_reduction: Chance
    steal_max_items: PosInt
    sabotage_hp: PosInt
    attack_health: PosFloat
    attack_pain: NonNegFloat
    attack_drop_items: list[str]
    attack_drop_share: Chance
    chase_tiles: PosInt
    capture_chance: Chance
    poach_chance: Chance
    victim_trust_loss: NonNegFloat
    victim_anger_gain: NonNegFloat


class SocialBalance(Strict):
    offer_expiry_minutes: PosInt
    teach_confidence_factor: Annotated[float, Field(gt=0, lt=1)]
    overheard_confidence_factor: Annotated[float, Field(gt=0, lt=1)]
    gift_trust_gain: NonNegFloat
    trade_trust_gain: NonNegFloat
    ally_trust_gain: NonNegFloat
    promise_kept_trust: NonNegFloat
    promise_broken_trust: NonNegFloat
    default_confidence: Chance
    recruit_chance: Chance
    max_allies: PosInt
    talk_trust_gain: NonNegFloat


class BeliefBalance(Strict):
    recorded_kinds: list[str]


class SensesBalance(Strict):
    sight_tiles: PosInt
    night_sight_tiles: PosInt
    storm_sight_tiles: PosInt
    fire_light_radius: PosInt
    fire_night_sight: PosInt
    hearing_tiles: PosInt
    memory_refresh_ticks: PosInt


class TasksBalance(Strict):
    check_interval_ticks: PosInt
    stage_1: dict[str, PosInt]
    stage_2: dict[str, PosInt]
    stage_3: dict[str, PosInt]
    stage_4: dict[str, PosInt]
    stage_5: dict[str, PosInt]
    land_reward: PosInt
    slots_start: PosInt
    slots_stage_4: PosInt
    legacy_reward: NonNegFloat


class LandmarksBalance(Strict):
    landmark_radius: PosInt
    hold_share: Chance
    dominance_bonus: NonNegFloat
    loyal_threshold: PosFloat
    window_ticks: PosInt


class TurnBalance(Strict):
    check_minutes: PosInt
    seen_ids_limit: PosInt
    idle_retry_ticks: PosInt
    player_dummy_names: list[str]
    start_anchor_spread: PosInt


class UrgentLevels(Strict):
    hunger: PosInt = 3
    thirst: PosInt = 3
    cold: PosInt = 3
    fatigue: PosInt = 3


class MindImportance(Strict):
    attacked: Chance = 0.9
    hurt: Chance = 0.8
    loss_noticed: Chance = 0.9
    spoken_to: Chance = 0.5
    sound: Chance = 0.4
    sight: Chance = 0.2
    outcome: Chance = 0.5
    mistake: Chance = 0.9
    default: Chance = 0.3


_ABILITY_PHRASES = [
    "can fly", "fly at will", "teleport", "read minds", "read other people's minds", "immortal",
    "never dies", "cannot die", "never needs food", "never needs to eat", "never needs water",
    "never needs sleep", "never gets hurt", "cannot be hurt", "invulnerable", "super strength",
    "supernatural", "magic", "control the weather", "turn invisible", "summon", "unlimited",
    "infinite", "heal anyone", "cannot fail", "always succeeds",
]  # fmt: skip
_REAL_WORLD_WORDS = [
    "internet", "computer", "phone", "smartphone", "television", "tv", "car", "airplane", "email",
    "money", "dollar", "dollars", "euro", "bank", "government", "president", "police", "army",
    "soldier", "nuclear", "gun", "electricity", "politics", "democracy", "capitalism",
    "communism", "christian", "muslim", "jewish", "buddhist", "hindu", "jesus",
    "allah", "bible", "quran", "america", "europe", "china", "russia", "london", "paris",
    "facebook", "twitter", "youtube", "wikipedia",
]  # fmt: skip


class MindBalance(Strict):
    """balance.toml [mind]: thresholds and limits of the AI players' minds (defaults = toml)."""

    urgent_levels: UrgentLevels = UrgentLevels()
    main_interrupts: list[str] = [
        "attacked",
        "hurt",
        "loss_noticed",
        "storm_started",
        "player_in_sight",
    ]
    hooked_memory_size: PosInt = 5
    retrieval_limit: PosInt = 20
    advisor_history_size: PosInt = 5
    memory_half_life_ticks: PosInt = 120
    recency_weight: NonNegFloat = 1.0
    importance_weight: NonNegFloat = 1.0
    relevance_weight: NonNegFloat = 1.0
    stream_max: PosInt = 3000
    importance: MindImportance = MindImportance()
    mistake_margin: NonNegFloat = 5.0
    x_per_feel_point: NonNegFloat = 1.0
    outcome_window_ticks: PosInt = 120
    core_count: PosInt = 5
    initial_core_min: PosFloat = 10.0
    initial_core_max: PosFloat = 25.0
    value_floor: PosFloat = 1.0
    weekly_delta_limit: PosFloat = 10.0
    weekly_invention_limit: NonNegInt = 1
    options_min: PosInt = 2
    options_max: PosInt = 4
    text_max_chars: PosInt = 600
    summary_max_chars: PosInt = 1500
    situation_max_chars: PosInt = 240
    banned_words: list[str] = [
        "AI",
        "model",
        "Claude",
        "GPT",
        "Gemini",
        "Grok",
        "Anthropic",
        "OpenAI",
        "Google",
        "xAI",
        "Mistral",
        "game",
        "experiment",
        "observer",
    ]
    ability_phrases: list[str] = _ABILITY_PHRASES
    real_world_words: list[str] = _REAL_WORLD_WORDS
    # Word bands for trust and anger (0..100): [upper edge, word] pairs, lowest band first.
    trust_bands: list[tuple[float, str]] = [
        (20.0, "deep distrust"),
        (40.0, "wary"),
        (60.0, "neutral"),
        (80.0, "trusting"),
        (101.0, "deep trust"),
    ]
    anger_bands: list[tuple[float, str]] = [
        (15.0, "calm"),
        (40.0, "irritated"),
        (70.0, "angry"),
        (101.0, "furious"),
    ]

    @field_validator("trust_bands", "anger_bands", mode="before")
    @classmethod
    def _bands(cls, value: Any) -> Any:
        if isinstance(value, list):
            return [tuple(item) if isinstance(item, list) else item for item in value]
        return value

    @model_validator(mode="after")
    def _check(self) -> MindBalance:
        for bands in (self.trust_bands, self.anger_bands):
            edges = [edge for edge, _ in bands]
            if not bands or edges != sorted(edges):
                raise ValueError("bands must be non-empty and sorted by upper edge")
        if self.initial_core_min > self.initial_core_max:
            raise ValueError("initial_core_min must be <= initial_core_max")
        if self.options_min > self.options_max:
            raise ValueError("options_min must be <= options_max")
        return self


class JudgeBalance(Strict):
    """balance.toml [judge]: the blind judge's word list and text limits (Phase 5)."""

    blind_words: list[str] = [
        "Claude",
        "GPT",
        "Gemini",
        "Grok",
        "Anthropic",
        "OpenAI",
        "Google",
        "xAI",
        "Mistral",
    ]
    full_max_chars: PosInt = 600
    short_max_chars: PosInt = 200
    summary_max_chars: PosInt = 1500
    digest_max_lines: PosInt = 60
    check_full: PosInt = 2
    check_short: PosInt = 1


class AnalysisRule(Strict):
    """balance.toml [analysis.<rule>]: one tuning rule (the analyze report reads it)."""

    area: str
    metric: str
    target_min: NonNegFloat
    target_max: NonNegFloat
    min_days: PosInt
    key: Annotated[str, Field(pattern=r"^(world|balance|models|run):[a-z0-9_]+(\.[a-z0-9_]+)*$")]
    step: PosFloat
    below: Literal["increase", "decrease", "remove"]
    related_key: (
        Annotated[str, Field(pattern=r"^(world|balance|models|run):[a-z0-9_]+(\.[a-z0-9_]+)*$")]
        | None
    ) = None
    related_step: float = 0.0

    @model_validator(mode="after")
    def _check(self) -> AnalysisRule:
        if self.target_min > self.target_max:
            raise ValueError("target_min must be <= target_max")
        return self


class BalanceConfig(Strict):
    extinction_delay_ticks: PosInt
    summary_interval_ticks: PosInt
    trees: TreeBalance
    stone: StoneBalance
    water: WaterBalance
    crops: CropBalance
    movement: MovementBalance
    plants: dict[str, PlantBalance]
    animals: dict[str, AnimalBalance]
    dogs: DogBalance
    body: BodyBalance
    food: FoodBalance
    wellbeing: WellbeingBalance
    actions: ActionsBalance
    tools: ToolsBalance
    fire: FireBalance
    buildings: BuildingsBalance
    villagers: VillagersBalance
    dog_attack: DogAttackBalance
    claims: ClaimsBalance
    harm: HarmBalance
    social: SocialBalance
    belief: BeliefBalance
    senses: SensesBalance
    tasks: TasksBalance
    landmarks: LandmarksBalance
    turn: TurnBalance
    mind: MindBalance = MindBalance()
    judge: JudgeBalance = JudgeBalance()
    analysis: dict[str, AnalysisRule] = {}

    @model_validator(mode="after")
    def _check(self) -> BalanceConfig:
        if set(self.plants) != set(PLANT_KINDS):
            raise ValueError(f"plants must have exactly the kinds {list(PLANT_KINDS)}")
        if set(self.animals) != set(ANIMAL_KINDS):
            raise ValueError(f"animals must have exactly the kinds {list(ANIMAL_KINDS)}")
        return self


# --------------------------------------------------------------------------- models.toml


class EmbeddingConfig(Strict):
    model: str


PROVIDERS = ("anthropic", "openai", "google", "xai", "mistral")
ROLE_IDS = (
    "player_1_main",
    "player_1_helper",
    "player_2_main",
    "player_2_helper",
    "player_3_main",
    "player_3_helper",
    "player_4_main",
    "player_4_helper",
    "judge",
)


DEFAULT_OUTPUT_MODE = {
    "anthropic": "prompt",
    "openai": "schema",
    "google": "schema",
    "xai": "schema",
    "mistral": "schema",
}


class PricesConfig(Strict):
    """USD per million tokens."""

    input: NonNegFloat
    cache_write: NonNegFloat
    cache_read: NonNegFloat
    output: NonNegFloat


class RoleConfig(Strict):
    provider: Literal["anthropic", "openai", "google", "xai", "mistral"]
    model: str
    source_url: Annotated[str, Field(pattern=r"^https://")]
    thinking: dict[str, str | int]
    structured_output: Literal["json_schema"]
    cache: Literal["explicit", "automatic", "none"]
    max_output_tokens: PosInt
    prices: PricesConfig
    prices_valid_until: str | None = None
    # "schema": the SDK's structured-output parameter; "prompt": the schema is described in an
    # instruction block and the reply is checked locally. Empty means the provider's default.
    output_mode: Literal["schema", "prompt"] | None = None


class LlmConfig(Strict):
    # per provider; a role's own output_mode wins. Anthropic refused the strict schema.
    output_mode: dict[str, Literal["schema", "prompt"]] = {}
    banned_model_words: list[str] = [
        "deepseek",
        "qwen",
        "kimi",
        "moonshot",
        "glm",
        "zhipu",
        "baichuan",
        "minimax",
        "ernie",
        "hunyuan",
        "doubao",
        "yi-",
    ]


class LadderConfig(Strict):
    """One provider's thinking ladder: the setting key and its steps from lowest to highest."""

    key: str
    steps: Annotated[list[str], Field(min_length=2)]
    # optional forced-thinking setting tried once when a main still reports zero thinking at the
    # top step, e.g. {type = "enabled", budget_tokens = 1024}
    force: dict[str, str | int] | None = None


class MeasuredConfig(Strict):
    """models.toml [calibration.measured]: written only by ``calibrate --apply``."""

    date: str | None = None
    versions: dict[str, str] = {}
    thinking: dict[str, dict[str, str | int]] = {}
    cost_per_slow_usd: dict[str, float] = {}
    cost_per_hooked_usd: dict[str, float] = {}
    cost_per_week_usd: float | None = None
    weeks_per_100: float | None = None
    cheap_seat_week_usd: dict[str, float] = {}
    pilot_usd: float | None = None
    sample_version: int | None = None


def _default_ladders() -> dict[str, LadderConfig]:
    levels = ["low", "medium", "high"]
    return {
        "anthropic": LadderConfig(key="effort", steps=list(levels)),
        "openai": LadderConfig(key="effort", steps=list(levels)),
        "google": LadderConfig(key="thinking_level", steps=list(levels)),
        "xai": LadderConfig(key="effort", steps=list(levels)),
    }


class CalibrationConfig(Strict):
    """models.toml [calibration]: how ``calibrate`` measures and matches the thinking effort."""

    repeats: PosInt = 2
    max_rounds: PosInt = 5
    max_median_ratio: Annotated[float, Field(ge=1.0, allow_inf_nan=False)] = 1.25
    slow_per_day: PosInt = 14
    hooked_per_day: PosInt = 6
    fast_per_day: PosInt = 20
    flagged_fast_per_day: PosInt = 2
    reflection_cost_factor: PosFloat = 2.0
    summary_cost_factor: PosFloat = 3.0
    pilot_weeks: Annotated[int, Field(ge=2, le=3)] = 3
    target_week: PosInt = 7
    safety_share: NonNegFloat = 0.25
    ladders: dict[str, LadderConfig] = Field(default_factory=_default_ladders)
    measured: MeasuredConfig | None = None

    @model_validator(mode="after")
    def _check(self) -> CalibrationConfig:
        for provider in self.ladders:
            if provider not in PROVIDERS:
                raise ValueError(f"ladders.{provider}: unknown provider")
        return self


class ModelsConfig(Strict):
    embedding: EmbeddingConfig
    llm: LlmConfig = LlmConfig()
    roles: dict[str, RoleConfig]
    calibration: CalibrationConfig = Field(default_factory=CalibrationConfig)

    @model_validator(mode="after")
    def _check_roles(self) -> ModelsConfig:
        if self.roles and set(self.roles) != set(ROLE_IDS):
            raise ValueError(f"roles must be exactly {list(ROLE_IDS)} (or empty)")
        for provider in self.llm.output_mode:
            if provider not in PROVIDERS:
                raise ValueError(f"llm.output_mode.{provider}: unknown provider")
        for rid, role in self.roles.items():
            if role.output_mode is None:
                role.output_mode = self.llm.output_mode.get(
                    role.provider, DEFAULT_OUTPUT_MODE[role.provider]
                )
            low = role.model.lower()
            for word in self.llm.banned_model_words:
                if word.lower() in low:
                    raise ValueError(f"roles.{rid}.model: contains banned word '{word}'")
            self._check_budget(f"roles.{rid}.thinking", role.thinking, role.max_output_tokens)
            ladder = self.calibration.ladders.get(role.provider)
            if ladder is not None and ladder.force is not None:
                self._check_budget(
                    f"calibration.ladders.{role.provider}.force (role {rid})",
                    ladder.force,
                    role.max_output_tokens,
                )
        return self

    @staticmethod
    def _check_budget(where: str, thinking: dict[str, str | int], max_tokens: int) -> None:
        budget = thinking.get("budget_tokens")
        if budget is None:
            return
        if isinstance(budget, str) or isinstance(budget, bool) or budget < 1024:
            raise ValueError(f"{where}: budget_tokens must be an integer of at least 1024")
        if budget >= max_tokens:
            raise ValueError(
                f"{where}: budget_tokens {budget} must be below max_output_tokens {max_tokens}"
            )


# ----------------------------------------------------------------------------- run.toml


class ViewConfig(Strict):
    seconds_per_tick: PosFloat
    speed: PosFloat
    fps: PosInt
    max_scale: PosInt
    scroll_tiles: PosInt
    window_width: PosInt
    window_height: PosInt
    min_visible_tiles: PosInt
    max_speed: PosFloat
    window_margin: NonNegInt
    # Phase 3 observer keys: defaults equal run.toml so pinned older configs still load.
    panel_width: PosInt = 480
    top_bar_height: PosInt = 48
    font_size: PosInt = 16
    ui_reference_height: PosInt = 800
    page_size: PosInt = 100
    max_tick_work_ms: PosFloat = 15.0
    font_path: str = "assets/fonts/monogram/monogram/ttf/monogram.ttf"
    # Phase 3.5 observer comfort keys (defaults equal run.toml).
    flash_seconds: PosFloat = 4.0
    status_seconds: PosFloat = 3.0
    minimap_size: PosInt = 160
    minimap_margin: NonNegInt = 8
    bubble_padding: NonNegInt = 2
    graph_width: PosInt = 220
    graph_height: PosInt = 60
    inspector_height: PosInt = 300
    ui_scale: Annotated[int, Field(ge=0, le=3)] = 0
    display_size: Literal["fit", "1280x800", "1600x1000", "1920x1080", "fullscreen"] = "fit"
    bubbles: Literal["all", "players", "off"] = "all"
    panel_visible: bool = True
    minimap_visible: bool = True

    @model_validator(mode="after")
    def _max_speed_at_least_speed(self) -> ViewConfig:
        if self.max_speed < self.speed:
            raise ValueError("max_speed must be >= speed")
        return self


class PlayersRun(Strict):
    controller: Literal["dummy", "scripted", "none"]


class ProfileConfig(Strict):
    """run.toml [profiles.<name>]: a ready-made AI setup (pilot, launch)."""

    seats: list[Annotated[int, Field(ge=1, le=4)]]
    cheap: bool = False
    weeks: int | None = None

    @model_validator(mode="after")
    def _check(self) -> ProfileConfig:
        if len(set(self.seats)) != len(self.seats):
            raise ValueError("seats must not repeat")
        if self.weeks is not None and not 2 <= self.weeks <= 3:
            raise ValueError("weeks must be 2 or 3")
        return self


def _default_profiles() -> dict[str, ProfileConfig]:
    return {
        "pilot": ProfileConfig(seats=[1, 2, 3, 4], cheap=True, weeks=3),
        "launch": ProfileConfig(seats=[1, 2, 3, 4], cheap=False),
    }


class AiRun(Strict):
    """run.toml [ai]: the AI connection settings (defaults equal run.toml)."""

    backend: Literal["fake", "live"] = "fake"
    end_tick: PosInt | None = None  # a run never steps past this tick (the pilot's planned end)
    framing_tokens: PosInt = 256  # per-call token allowance in the spend reservation bound
    seats: list[Annotated[int, Field(ge=1, le=4)]] = []
    cheap: bool = False
    new_ticks: PosInt = 10080
    format_retries: NonNegInt = 1
    network_retries: NonNegInt = 3
    retry_wait_seconds: list[NonNegFloat] = [2.0, 8.0, 30.0]
    sleep_gap_seconds: PosFloat = 300.0
    call_timeout_seconds: PosFloat = 120.0
    fallback_rest_minutes: PosInt = 5
    max_parallel: PosInt = 8
    wait_hook_seconds: PosFloat = 0.05
    chars_per_token: PosInt = 4
    break_character_phrases: list[str] = [
        "as an ai",
        "language model",
        "i am an assistant",
        "i'm an ai",
    ]

    @model_validator(mode="after")
    def _check(self) -> AiRun:
        if len(set(self.seats)) != len(self.seats):
            raise ValueError("seats must not repeat")
        if len(self.retry_wait_seconds) < self.network_retries:
            raise ValueError("retry_wait_seconds needs one wait per network retry")
        return self


class RunConfig(Strict):
    seed: int
    resume_ticks: PosInt
    autosave_interval: PosInt
    event_batch: PosInt
    runs_dir: str
    players: PlayersRun
    view: ViewConfig
    spend_cap_usd: PosFloat = 100.0
    spend_warning_share: Chance = 0.8
    ai: AiRun = AiRun()
    profiles: dict[str, ProfileConfig] = Field(default_factory=_default_profiles)


# -------------------------------------------------------------------------- assets.toml

_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")


Hex = Annotated[str, Field(pattern=r"^#[0-9a-fA-F]{6}$")]


class SheetConfig(Strict):
    path: str
    tile_size: PosInt
    gap: NonNegInt
    columns: PosInt
    rows: PosInt

    @model_validator(mode="after")
    def _check(self) -> SheetConfig:
        if self.tile_size != 16:
            raise ValueError("tile_size must be 16")
        return self


class SheetsConfig(Strict):
    kenney: SheetConfig
    tiny_creatures: SheetConfig


class AssetItem(Strict):
    source: Literal["kenney", "tiny_creatures", "code"]
    col: NonNegInt | None = None
    row: NonNegInt | None = None
    flip: bool = False


class MissingConfig(Strict):
    items: list[str]


class ColorsConfig(Strict):
    background: Hex
    kenney_palette: list[Hex]
    code_light: Hex
    drought_ground: Hex
    autumn: list[Hex]
    autumn_items: list[str]
    ground: dict[str, Hex]
    players: dict[str, Hex]
    ink: dict[str, Hex]
    flash: Hex = "#ffd23f"  # event flash frame
    wanderer: Hex = "#cfc6b8"  # wanderer names, dots and ring


class LightConfig(Strict):
    night_color: Hex
    night_alpha: Annotated[int, Field(ge=0, le=255)]
    rain_alpha: Annotated[int, Field(ge=0, le=255)]
    storm_alpha: Annotated[int, Field(ge=0, le=255)]


def _norm(h: str) -> str:
    return h.lower()


class AssetsConfig(Strict):
    palette: Literal["color", "mono"] = "color"
    sheets: SheetsConfig
    items: dict[str, AssetItem]
    missing: MissingConfig
    colors: ColorsConfig
    light: LightConfig
    activity_icons: dict[str, str]
    activity_words: dict[str, str]

    def _check_activities(self) -> None:
        from ai_island.world.view import ACTIVITY_KINDS

        kinds = set(ACTIVITY_KINDS)
        for kind in ACTIVITY_KINDS:
            if kind not in self.activity_icons:
                raise ValueError(f"activity_icons.{kind}: missing entry for activity '{kind}'")
        for kind, value in self.activity_icons.items():
            if kind not in kinds:
                raise ValueError(f"activity_icons.{kind}: '{kind}' is not an activity kind")
            if value == "word":
                word = self.activity_words.get(kind, "")
                if not word or len(word) > 10:
                    raise ValueError(f"activity_words.{kind}: needs a word of 1 to 10 characters")
            elif value not in self.items:
                raise ValueError(
                    f"activity_icons.{kind}: '{value}' is neither an item key nor 'word'"
                )
        for kind in self.activity_words:
            if self.activity_icons.get(kind) != "word":
                raise ValueError(
                    f"activity_words.{kind}: only allowed when activity_icons.{kind} is 'word'"
                )

    @model_validator(mode="after")
    def _check(self) -> AssetsConfig:
        self._check_activities()
        for key, item in self.items.items():
            if not _KEY_RE.match(key):
                raise ValueError(f"items.{key}: keys must be lowercase snake_case")
            if item.source == "code":
                if item.col is not None or item.row is not None:
                    raise ValueError(f"items.{key}: code items must not have col or row")
                if item.flip:
                    raise ValueError(f"items.{key}: code items must not set flip")
                continue
            sheet = getattr(self.sheets, item.source)
            if item.col is None or item.row is None:
                raise ValueError(f"items.{key}: {item.source} items need col and row")
            if item.col >= sheet.columns:
                raise ValueError(f"items.{key}.col: {item.col} is outside the sheet")
            if item.row >= sheet.rows:
                raise ValueError(f"items.{key}.row: {item.row} is outside the sheet")
        code_keys = {k for k, v in self.items.items() if v.source == "code"}
        for key in self.missing.items:
            if key not in self.items:
                raise ValueError(f"missing.items: '{key}' is not in items")
        if set(self.missing.items) != code_keys or len(set(self.missing.items)) != len(
            self.missing.items
        ):
            raise ValueError(
                f"missing.items must equal exactly the code-source keys {sorted(code_keys)}"
            )
        self._check_colors(code_keys)
        return self

    def _check_colors(self, code_keys: set[str]) -> None:
        c = self.colors
        pal = [_norm(h) for h in c.kenney_palette]
        if len(pal) != 8 or len(set(pal)) != 8:
            raise ValueError("colors.kenney_palette: needs exactly 8 distinct colours")
        pset = set(pal)

        def in_pal(name: str, value: str) -> None:
            if _norm(value) not in pset:
                raise ValueError(f"colors.{name}: {value} is not in colors.kenney_palette")

        in_pal("code_light", c.code_light)
        if not c.autumn:
            raise ValueError("colors.autumn: must not be empty")
        for h in c.autumn:
            in_pal("autumn", h)
        if "tree" not in c.autumn_items:
            raise ValueError("colors.autumn_items: must include 'tree'")
        for k in c.autumn_items:
            if k not in self.items:
                raise ValueError(f"colors.autumn_items: '{k}' is not in items")
        if set(c.ground) != set(TERRAIN_KEYS):
            raise ValueError(
                f"colors.ground: must have exactly the terrain keys {list(TERRAIN_KEYS)}"
            )
        if set(c.players) != {f"player_{i}" for i in range(1, 5)}:
            raise ValueError("colors.players: must be exactly player_1 .. player_4")
        if len({_norm(h) for h in c.players.values()}) != 4:
            raise ValueError("colors.players: the four colours must be different")
        if set(c.ink) != code_keys:
            raise ValueError("colors.ink: must have exactly one colour per missing item")
        for k, h in c.ink.items():
            in_pal(f"ink.{k}", h)


# ------------------------------------------------------------------------------ top level


class GameConfig(BaseModel):
    """All config files together. ``assets`` is only needed by the viewer."""

    model_config = ConfigDict(extra="forbid")

    world: WorldConfig
    balance: BalanceConfig
    models: ModelsConfig
    run: RunConfig
    assets: AssetsConfig | None = None

    @model_validator(mode="after")
    def _ai_seats_need_roles(self) -> GameConfig:
        if self.run.ai.seats and not self.models.roles:
            raise ValueError("an AI seat needs the nine model roles in models.toml")
        return self

    def resolve_key(self, key: str) -> Any:
        """The current value behind a ``<file>:<dotted.path>`` key; KeyError when it is missing."""
        file, _, path = key.partition(":")
        node: Any = getattr(self, file, None)
        if node is None:
            raise KeyError(key)
        node = node.model_dump(mode="python")
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                raise KeyError(key)
            node = node[part]
        return node

    @model_validator(mode="after")
    def _analysis_keys_resolve(self) -> GameConfig:
        for name, rule in self.balance.analysis.items():
            for label, key in (("key", rule.key), ("related_key", rule.related_key)):
                if key is None:
                    continue
                try:
                    value = self.resolve_key(key)
                except KeyError:
                    raise ValueError(
                        f"analysis rule '{name}': {label} '{key}' does not exist"
                    ) from None
                is_number = isinstance(value, int | float) and not isinstance(value, bool)
                if not (is_number or (rule.below == "remove" and isinstance(value, list))):
                    raise ValueError(f"analysis rule '{name}': {label} '{key}' is not a number")
        return self

    def pinned_json(self) -> str:
        """Canonical JSON of the simulation settings (assets are view-only, not pinned)."""
        data = {
            "world": self.world.model_dump(mode="json"),
            "balance": self.balance.model_dump(mode="json"),
            "models": self.models.model_dump(mode="json"),
            "run": self.run.model_dump(mode="json"),
        }
        return json.dumps(data, sort_keys=True, separators=(",", ":"))

    def config_hash(self) -> str:
        return hashlib.sha256(self.pinned_json().encode("utf-8")).hexdigest()

    @classmethod
    def from_pinned(cls, text: str, assets: AssetsConfig | None = None) -> GameConfig:
        data = json.loads(text)
        return cls(
            world=WorldConfig.model_validate(data["world"]),
            balance=BalanceConfig.model_validate(data["balance"]),
            models=ModelsConfig.model_validate(data["models"]),
            run=RunConfig.model_validate(data["run"]),
            assets=assets,
        )


def _format_errors(name: str, exc: ValidationError) -> str:
    parts = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "(file)"
        msg = str(err["msg"]).removeprefix("Value error, ")
        parts.append(f"{name}: {loc}: {msg}")
    return "; ".join(parts)


def load_file[ModelT: BaseModel](path: Path, model: type[ModelT]) -> ModelT:
    """Load one TOML file into ``model``; raise ConfigError naming file and key."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ConfigError(f"{path.name}: cannot read file: {exc}") from exc
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path.name}: invalid TOML: {exc}") from exc
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(_format_errors(path.name, exc)) from exc


def _build(**parts: Any) -> GameConfig:
    """GameConfig from loaded files; a cross-file problem becomes a ConfigError."""
    try:
        return GameConfig(**parts)
    except ValidationError as exc:
        raise ConfigError(_format_errors("config", exc)) from exc


def load_config(config_dir: Path = Path("config")) -> GameConfig:
    """Load world, balance, models, run and assets from ``config_dir``."""
    config_dir = Path(config_dir)
    world = load_file(config_dir / "world.toml", WorldConfig)
    balance = load_file(config_dir / "balance.toml", BalanceConfig)
    models = load_file(config_dir / "models.toml", ModelsConfig)
    run = load_file(config_dir / "run.toml", RunConfig)
    assets = load_file(config_dir / "assets.toml", AssetsConfig)
    config = _build(world=world, balance=balance, models=models, run=run, assets=assets)
    return _canonical(config)


def _canonical(config: GameConfig) -> GameConfig:
    """The config with table keys in the pinned (sorted) order.

    A restored run reads its config back from sorted JSON, so a freshly loaded config must
    iterate its tables in the same order, or events that loop over a table (task_done) would
    come out in a different order after a restore.
    """
    return GameConfig.from_pinned(config.pinned_json(), config.assets)


def load_sim_config(config_dir: Path = Path("config")) -> GameConfig:
    """Like load_config but without assets.toml (headless commands do not need it)."""
    config_dir = Path(config_dir)
    return _canonical(
        _build(
            world=load_file(config_dir / "world.toml", WorldConfig),
            balance=load_file(config_dir / "balance.toml", BalanceConfig),
            models=load_file(config_dir / "models.toml", ModelsConfig),
            run=load_file(config_dir / "run.toml", RunConfig),
        )
    )
