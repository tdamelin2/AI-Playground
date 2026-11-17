"""Emitting the mind events (decision_made, value_repaired, ...) through one helper.

The payload classes are registered by storage/events.py (``PAYLOAD_TYPES``). Until a name is
registered the event is kept in ``UNREGISTERED`` instead, so nothing breaks while the storage
layer catches up; once it is registered the same call writes a real event.
"""

from __future__ import annotations

from typing import Any

UNREGISTERED: list[tuple[int, str, dict[str, Any]]] = []
_KEEP = 5000


def emit_event(world: Any, etype: str, tick: int, /, **fields: Any) -> None:
    """Emit the registered payload ``etype`` with the fields its model declares."""
    from ai_island.storage.events import PAYLOAD_TYPES

    model = PAYLOAD_TYPES.get(etype)
    if model is None:
        UNREGISTERED.append((tick, etype, dict(fields)))
        del UNREGISTERED[:-_KEEP]
        return
    wanted = {k: v for k, v in fields.items() if k in model.model_fields}
    world.emit(model(**wanted), tick)
