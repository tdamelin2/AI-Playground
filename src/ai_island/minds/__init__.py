"""Players' minds: the Controller protocol and the rule-based players of Phase 2.

``make_controllers(kind, world)`` returns one controller per living seat:
  "dummy"    looks after its own needs only (eat, drink, rest, warmth, fetch food and water);
  "scripted" follows a fixed scenario that uses every action (test fixture, may read the world);
  "none"     no controllers at all (ecology-only, used by the Phase 1 and 1.5 tests).
"""

from __future__ import annotations

from typing import Any, Protocol

from ai_island.minds.dummy import DummyController
from ai_island.minds.scripted import ScriptedController

CONTROLLER_KINDS: tuple[str, ...] = ("dummy", "scripted", "none", "mixed")


class Controller(Protocol):
    """Decides what a player does next. ``ctx`` is a DecisionContext."""

    def decide(self, ctx: Any) -> Any | None: ...

    def to_state(self) -> dict[str, Any]: ...

    def from_state(self, state: dict[str, Any]) -> None: ...


def make_controllers(kind: str, world: Any) -> dict[str, Controller]:
    """One controller per player id for ``kind`` (an empty dict for "none")."""
    if kind == "none":
        return {}
    if kind == "dummy":
        return {
            pid: DummyController(pid, world.streams.get(f"mind.{pid}")) for pid in world.players
        }
    if kind == "scripted":
        return {pid: ScriptedController(pid, world) for pid in world.players}
    if kind == "mixed":
        from ai_island.minds.ai import AiController

        seats = {f"player_{n}" for n in world.cfg.run.ai.seats}
        out: dict[str, Controller] = {}
        for pid in world.players:
            rng = world.streams.get(f"mind.{pid}")
            out[pid] = AiController(pid, world, rng) if pid in seats else DummyController(pid, rng)
        return out
    raise ValueError(f"unknown controller kind '{kind}' (use one of {CONTROLLER_KINDS})")


__all__ = [
    "CONTROLLER_KINDS",
    "Controller",
    "DummyController",
    "ScriptedController",
    "make_controllers",
]
