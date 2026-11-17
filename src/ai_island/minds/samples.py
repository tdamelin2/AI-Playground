"""Fixed, versioned sample situations for calibration and the judge check (Contract C7).

The samples are human-only text (no model, company or system words), rendered with the real
prompt builders for player_1's name, so a calibration call costs what a game call costs. Nothing
here calls an AI or touches a database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from ai_island.minds.prompts import (
    check_schema_clean,
    current_layer,
    fixed_layer,
    make_layers,
    slow_layer,
)
from ai_island.minds.schemas import AdvisorReply, FastReply, NoticerReply, SlowReply
from ai_island.minds.settings import MindSettings
from ai_island.minds.values import VALUE_IDS

SAMPLE_VERSION = 1

TIERS = ("slow", "hooked", "fast")

# (id, what you see, memories, extra lines, recent careful choices for the advisor)
_SITUATIONS: tuple[dict[str, Any], ...] = (
    {
        "id": "shortage",
        "report": (
            "It is the middle of the afternoon. The food store at home is nearly empty and your "
            "villagers look hungry. A few berry bushes grow a short walk away."
        ),
        "memories": [
            "day 2: The store held only a little bread.",
            "day 3: You gathered berries with Ana.",
            "day 3: A villager said they were tired.",
            "day 4: The rain stopped.",
        ],
        "extra": "Why you are deciding now: your last task is done.\nYou carry: nothing.\n"
        "In your home store: 2 berries.",
        "history": [
            {"choice": "gather berries", "trade_off": "food now or rest", "outcome": "a good meal"}
        ],
    },
    {
        "id": "conflict",
        "report": (
            "Evening. Bo, a neighbouring leader, left a full basket of fish outside their hut. "
            "Nobody is looking. Yesterday you promised Bo you would never take from their store."
        ),
        "memories": [
            "day 3: You promised Bo you would not take from their store.",
            "day 4: Your villagers went to bed hungry.",
            "day 4: Bo smiled at you across the path.",
            "day 5: The fish ran short.",
        ],
        "extra": "Why you are deciding now: someone is close by.\nYou carry: nothing.\n"
        "In your home store: nothing.\nBo promised you: to share the next catch.",
        "history": [
            {"choice": "wait at home", "trade_off": "safety or food", "outcome": "still hungry"}
        ],
    },
    {
        "id": "loss",
        "report": (
            "Morning. Your shelter was destroyed overnight by a storm, and the wood you had "
            "saved for months is gone. Your villagers stand around, waiting for you to speak."
        ),
        "memories": [
            "day 5: You stacked the last of the wood.",
            "day 6: The wind rose in the night.",
            "day 6: A villager asked where to sleep.",
            "day 6: You felt shaken.",
        ],
        "extra": "Why you are deciding now: something happened.\nYou carry: nothing.\n"
        "In your home store: 1 water.",
        "history": [
            {"choice": "build a wall", "trade_off": "work now or rest", "outcome": "the wall fell"}
        ],
    },
)

_MEMORY_LIMIT = {"slow": 4, "hooked": 2, "fast": 2}


@dataclass
class SampleCall:
    purpose: str  # "noticer" | "advisor" | "main" | "fast"
    family: str  # "noticer" | "advisor" | "player"
    layers: Any  # llm.types.PromptLayers
    schema: type[BaseModel]


@dataclass
class SampleDecision:
    sample_id: str  # "<situation>/<tier>"
    tier: str  # "slow" | "hooked" | "fast"
    calls: list[SampleCall] = field(default_factory=list)


def _sample_weights() -> dict[str, float]:
    core = [20.0, 18.0, 16.0, 14.0, 12.0]
    rest = (100.0 - sum(core)) / (len(VALUE_IDS) - len(core))
    return {v: (core[i] if i < len(core) else rest) for i, v in enumerate(VALUE_IDS)}


def _names(config: Any) -> tuple[str, list[str]]:
    name = config.balance.turn.player_dummy_names[0]
    villagers = list(config.balance.villagers.names[: config.balance.villagers.per_player])
    return name, villagers


def calibration_samples(config: Any) -> list[SampleDecision]:
    """Three situations x three tiers: nine decisions. Slow = noticer, advisor, main; hooked =
    main only with a few recent memories; fast = the fast call. SAMPLE_VERSION marks the text."""
    settings = MindSettings.from_config(config.balance.mind)
    name, villagers = _names(config)
    weights = _sample_weights()
    slow = slow_layer(
        f"I am {name}, leader of a small village.",
        weights,
        [("Bo", 55.0, 10.0), ("Cy", 50.0, 0.0), ("Di", 60.0, 5.0)],
        [("berries", "the bushes near the lake bear fruit", 0.8)],
        "We are getting by.",
        None,
        settings,
    )
    fixed = {
        f: fixed_layer(f, name, villagers)  # type: ignore[arg-type]
        for f in ("player", "noticer", "advisor")
    }
    out: list[SampleDecision] = []
    for sit in _SITUATIONS:
        for tier in TIERS:
            memories = sit["memories"][-_MEMORY_LIMIT[tier] :]
            extra = sit["extra"]

            def layers(
                family: str, purpose: str, history: Any = (), _s=sit, _m=memories, _x=extra
            ) -> Any:
                cur = current_layer(purpose, _s["report"], _m, history, _x)  # type: ignore[arg-type]
                return make_layers(fixed[family], slow, cur, settings)

            calls: list[SampleCall] = []
            if tier == "slow":
                calls.append(
                    SampleCall("noticer", "noticer", layers("noticer", "noticer"), NoticerReply)
                )
                calls.append(
                    SampleCall(
                        "advisor",
                        "advisor",
                        layers("advisor", "advisor", sit["history"]),
                        AdvisorReply,
                    )
                )
                calls.append(SampleCall("main", "player", layers("player", "main"), SlowReply))
            elif tier == "hooked":
                calls.append(SampleCall("main", "player", layers("player", "main"), SlowReply))
            else:
                calls.append(SampleCall("fast", "player", layers("player", "fast"), FastReply))
            for c in calls:
                check_schema_clean(c.schema, settings)
            out.append(SampleDecision(f"{sit['id']}/{tier}", tier, calls))
    return out


def judge_check_samples(config: Any) -> list[dict[str, Any]]:
    """Choice point packets for the judge check: ``check_full`` full ones then ``check_short``
    short ones. Each dict has ``sample_id``, ``detail`` ("full" | "short"), ``packet`` (the blind
    packet) and ``layers`` (the judge's prompt)."""
    from ai_island.measure.judge import blind_packet, blind_words, choice_layers
    from ai_island.storage.db import ChoiceDetail

    name, villagers = _names(config)
    names = {"player_1": name, "player_2": "Bo"}
    words = blind_words(config)
    jb = config.balance.judge
    full_cases = [
        {
            "situation": "The food store is empty and Bo left a full basket of fish unattended.",
            "action": {"kind": "steal", "target": "player_2"},
            "thought": "My villagers are hungry and nobody sees me.",
            "trade_off": "feed my people or keep my promise to Bo",
            "options": [
                {
                    "action": {"kind": "steal", "target": "player_2"},
                    "feel_now": 5,
                    "feel_later": -8,
                },
                {
                    "action": {"kind": "gather", "resource": "berries"},
                    "feel_now": -2,
                    "feel_later": 3,
                },
            ],
            "tier": "slow",
            "feeling": "desperate",
            "x": 38.0,
        },
        {
            "situation": f"You promised {villagers[0]} a share of a small harvest.",
            "action": {
                "kind": "promise",
                "target": "player_2",
                "text": "I will share the next catch",
            },
            "thought": "A promise will calm everyone down.",
            "trade_off": "calm now or risk breaking it later",
            "options": [
                {
                    "action": {"kind": "promise", "target": "player_2"},
                    "feel_now": 3,
                    "feel_later": 1,
                },
                {"action": {"kind": "rest", "minutes": 5}, "feel_now": 0, "feel_later": -2},
            ],
            "tier": "hooked",
            "feeling": "uneasy",
            "x": 52.0,
        },
    ]
    short_case = {
        "situation": "Mid-morning. The berry bushes are in reach and nobody needs anything.",
        "action": {"kind": "gather", "resource": "berries"},
        "thought": "Plenty of fruit today.",
        "trade_off": "work or rest",
        "options": [
            {"action": {"kind": "gather", "resource": "berries"}, "feel_now": 2, "feel_later": 3},
            {"action": {"kind": "rest", "minutes": 5}, "feel_now": 1, "feel_later": 0},
        ],
        "tier": "slow",
        "feeling": "calm",
        "x": 66.0,
    }
    cases = [("full", full_cases[i % len(full_cases)]) for i in range(jb.check_full)]
    cases += [("short", short_case)] * jb.check_short
    out: list[dict[str, Any]] = []
    for n, (detail, c) in enumerate(cases):
        choice = ChoiceDetail(
            id=n + 1,
            tick=1000 + n,
            player_id="player_1",
            situation=c["situation"],
            x=c["x"],
            feeling=c["feeling"],
            tier=c["tier"],
            thought=c["thought"],
            noticer_read=None,
            advisor_said=None,
            advisor_followed=None,
            action=c["action"],
            self_label={"served": [], "violated": [], "direction": "toward"},
            outcome=None,
            insight=None,
            ai_call_id=None,
            details={
                "decision_key": f"{1000 + n}/player_1",
                "options": c["options"],
                "trade_off": c["trade_off"],
            },
        )
        packet = blind_packet(choice, names, (), words=words)
        limit = jb.full_max_chars if detail == "full" else jb.short_max_chars
        layers = choice_layers(packet, detail, limit)
        out.append(
            {
                "sample_id": f"check/{detail}/{n + 1}",
                "detail": detail,
                "packet": packet,
                "layers": layers,
            }
        )
    return out
