"""Event flashes: a blinking frame on the tile where something important just happened."""

from __future__ import annotations

from dataclasses import dataclass

BLINKS_PER_SECOND = 3  # the frame is on for half of each 1/3 second so it catches the eye


@dataclass(frozen=True)
class Flash:
    """One marked event. ``x`` and ``y`` are -1 when the event has no known tile."""

    event_id: int
    kind: str
    x: int
    y: int
    who: tuple[str, ...]
    until: float  # clock() time when the marker disappears


def blink_on(now: float) -> bool:
    """True during the lit half of the blink cycle."""
    return int(now * BLINKS_PER_SECOND * 2) % 2 == 0
