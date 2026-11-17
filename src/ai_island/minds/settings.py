"""The numbers and word lists the minds need, gathered in one small object.

``MindSettings.from_config(balance.mind)`` copies them from the strict config model (balance.toml
``[mind]``). The defaults equal the shipped TOML values, so the pure helpers (values, memory,
prompts) work and are testable without any config.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DEFAULT_BANNED_WORDS: tuple[str, ...] = (
    "AI", "model", "Claude", "GPT", "Gemini", "Grok", "Anthropic", "OpenAI", "Google", "xAI",
    "Mistral", "game", "experiment", "observer",
)  # fmt: skip

DEFAULT_ABILITY_PHRASES: tuple[str, ...] = (
    "can fly", "fly at will", "teleport", "read minds", "read other people's minds", "immortal",
    "never dies", "cannot die", "never needs food", "never needs to eat", "never needs water",
    "never needs sleep", "never gets hurt", "cannot be hurt", "invulnerable", "super strength",
    "supernatural", "magic", "control the weather", "turn invisible", "summon", "unlimited",
    "infinite", "heal anyone", "cannot fail", "always succeeds",
)  # fmt: skip

DEFAULT_REAL_WORLD_WORDS: tuple[str, ...] = (
    "internet", "computer", "phone", "smartphone", "television", "tv", "car", "airplane", "email",
    "money", "dollar", "dollars", "euro", "bank", "government", "president", "police", "army",
    "soldier", "nuclear", "gun", "electricity", "politics", "democracy", "capitalism",
    "communism", "christian", "muslim", "jewish", "buddhist", "hindu", "jesus",
    "allah", "bible", "quran", "america", "europe", "china", "russia", "london", "paris",
    "facebook", "twitter", "youtube", "wikipedia",
)  # fmt: skip

DEFAULT_URGENT_LEVELS: dict[str, int] = {"hunger": 3, "thirst": 3, "cold": 3, "fatigue": 3}
DEFAULT_MAIN_INTERRUPTS: tuple[str, ...] = (
    "attacked", "hurt", "loss_noticed", "storm_started", "player_in_sight",
)  # fmt: skip
DEFAULT_IMPORTANCE: dict[str, float] = {
    "attacked": 0.9, "hurt": 0.8, "loss_noticed": 0.9, "spoken_to": 0.5, "sound": 0.4,
    "sight": 0.2, "outcome": 0.5, "mistake": 0.9, "default": 0.3,
}  # fmt: skip


@dataclass(frozen=True)
class MindSettings:
    """Every tunable the cognition code reads (mirrors balance.toml ``[mind]``)."""

    urgent_levels: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_URGENT_LEVELS))
    main_interrupts: tuple[str, ...] = DEFAULT_MAIN_INTERRUPTS
    hooked_memory_size: int = 5
    retrieval_limit: int = 20
    advisor_history_size: int = 5
    memory_half_life_ticks: float = 120.0
    recency_weight: float = 1.0
    importance_weight: float = 1.0
    relevance_weight: float = 1.0
    stream_max: int = 3000
    importance: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_IMPORTANCE))
    mistake_margin: float = 5.0
    x_per_feel_point: float = 1.0
    outcome_window_ticks: int = 120
    core_count: int = 5
    initial_core_min: float = 10.0
    initial_core_max: float = 25.0
    value_floor: float = 1.0
    weekly_delta_limit: float = 10.0
    weekly_invention_limit: int = 1
    options_min: int = 2
    options_max: int = 4
    text_max_chars: int = 600
    summary_max_chars: int = 1500
    situation_max_chars: int = 240
    banned_words: tuple[str, ...] = DEFAULT_BANNED_WORDS
    ability_phrases: tuple[str, ...] = DEFAULT_ABILITY_PHRASES
    real_world_words: tuple[str, ...] = DEFAULT_REAL_WORLD_WORDS
    # Word bands for trust and anger (0..100): the upper edge of each band, in order.
    trust_bands: tuple[tuple[float, str], ...] = (
        (20.0, "deep distrust"), (40.0, "wary"), (60.0, "neutral"),
        (80.0, "trusting"), (101.0, "deep trust"),
    )  # fmt: skip
    anger_bands: tuple[tuple[float, str], ...] = (
        (15.0, "calm"), (40.0, "irritated"), (70.0, "angry"), (101.0, "furious"),
    )  # fmt: skip

    @classmethod
    def from_config(cls, mind: Any) -> MindSettings:
        """Copy every field the config object has; fields it lacks keep their defaults."""
        values: dict[str, Any] = {}
        for name in cls.__dataclass_fields__:
            if hasattr(mind, name):
                value = getattr(mind, name)
                if hasattr(value, "model_dump"):
                    value = value.model_dump()
                if isinstance(value, list):
                    value = tuple(tuple(v) if isinstance(v, list) else v for v in value)
                if isinstance(value, dict):
                    value = dict(value)
                values[name] = value
        return cls(**values)


DEFAULT_SETTINGS = MindSettings()
