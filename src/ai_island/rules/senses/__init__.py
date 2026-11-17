"""Senses: what players see, hear and remember, chat, gossip and witnesses.

Mutates only place_memory, seen_ids, harm_log saw/heard/processed, known_culprits and
villagers' witnessed, and raises interrupts through the engine.
"""

from ai_island.rules.senses.chat import run_chat_phase
from ai_island.rules.senses.memory import (
    RememberedTile,
    detect_sight_interrupts,
    refresh_memory,
    remembered_tile,
)
from ai_island.rules.senses.ranges import can_hear, can_see, sight_range
from ai_island.rules.senses.report import Seen, SenseReport, build_report
from ai_island.rules.senses.witness import record_witnesses

__all__ = [
    "RememberedTile",
    "SenseReport",
    "Seen",
    "build_report",
    "can_hear",
    "can_see",
    "detect_sight_interrupts",
    "record_witnesses",
    "refresh_memory",
    "remembered_tile",
    "run_chat_phase",
    "sight_range",
]
