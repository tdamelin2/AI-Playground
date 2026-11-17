"""Interrupts: things that make a player decide again. Each is consumed once."""

from __future__ import annotations

from ai_island.storage.events import InterruptRaised
from ai_island.world.agents import Interrupt
from ai_island.world.state import World

INTERRUPT_KINDS: tuple[str, ...] = (
    "spoken_to",
    "attacked",
    "hurt",
    "player_in_sight",
    "dog_in_sight",
    "storm_started",
    "loss_noticed",
    "band_changed",
)


def raise_interrupt(
    world: World,
    kind: str,
    player: str,
    tick: int,
    source: str | None = None,
    detail: str = "",
) -> Interrupt | None:
    """Queue an interrupt for a living player and log an ``interrupt`` event."""
    if kind not in INTERRUPT_KINDS:
        raise ValueError(f"unknown interrupt kind '{kind}'")
    who = world.players.get(player)
    if who is None or not who.alive:
        return None
    item = Interrupt(world.next("interrupt"), kind, player, tick, source, detail)
    world.pending_interrupts.setdefault(player, []).append(item)
    world.emit(
        InterruptRaised(id=item.id, kind=kind, player=player, source=source, detail=detail), tick
    )
    return item


def pending(world: World, player: str) -> list[Interrupt]:
    return list(world.pending_interrupts.get(player, ()))


def take_interrupts(world: World, player: str) -> list[Interrupt]:
    """Hand over and clear a player's interrupts (each fires once)."""
    return world.pending_interrupts.pop(player, [])


def clear_for(world: World, player: str) -> None:
    world.pending_interrupts.pop(player, None)
