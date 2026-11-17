"""The router: which thinking tier decides this moment (Contract C9).

reflex   an urgent body need and the reflex code has an answer: no AI call;
slow     a main-model decision (Noticer, Advisor, main);
hooked   a main-model decision for a player whose wellbeing is low: main only, short memory;
fast     everything else, one helper call.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ai_island.minds.reflex import reflex_action
from ai_island.minds.settings import DEFAULT_SETTINGS, MindSettings


def trigger_of(ctx: Any) -> str:
    """finished | spoken_to | interrupt | check (from ``ctx.trigger`` or the older ``reason``)."""
    found = getattr(ctx, "trigger", None)
    if found:
        return str(found)
    reason = getattr(ctx, "reason", "finished")
    if reason == "interrupt":
        if any(i.kind == "spoken_to" for i in getattr(ctx, "interrupts", ())):
            return "spoken_to"
        return "interrupt"
    return "finished" if reason == "idle" else str(reason)


def _from_player(world: Any, source: str | None) -> bool:
    if not source:
        return False
    if world is None:
        return source.startswith("player_")
    return source in world.players


def _pending_from_player(world: Any, pid: str) -> bool:
    """An open trade offer or promise from another player waiting for ``pid``."""
    if world is None:
        return False
    for offer in world.offers.values():
        if offer.target == pid and offer.maker in world.players:
            return True
    for promise in world.promises.values():
        if promise.to == pid and promise.status == "open" and promise.maker in world.players:
            return True
    return False


def needs_main(ctx: Any, world: Any = None, settings: MindSettings = DEFAULT_SETTINGS) -> bool:
    for item in getattr(ctx, "interrupts", ()):
        if item.kind in settings.main_interrupts:
            return True
        if item.kind == "spoken_to" and _from_player(world, item.source):
            return True
    return _pending_from_player(world, ctx.player_id)


def route(
    ctx: Any,
    report: Any,
    world: Any = None,
    settings: MindSettings = DEFAULT_SETTINGS,
    hooked: bool | None = None,
    reflex_fn: Callable[[Any, Any], Any] | None = None,
) -> str:
    """ "reflex" | "fast" | "slow" | "hooked" for this decision."""
    if hooked is None:
        hooked = bool(getattr(ctx, "hooked", False))
    fn = reflex_fn or (lambda c, r: reflex_action(c, r, settings))
    needs = getattr(report, "needs", None) or {}
    if any(needs.get(n, 0) >= lvl for n, lvl in settings.urgent_levels.items()):
        if fn(ctx, report) is not None:
            return "reflex"
    if needs_main(ctx, world, settings):
        return "hooked" if hooked else "slow"
    return "fast"
