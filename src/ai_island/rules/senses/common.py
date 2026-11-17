"""Small helpers shared by the sense, task and mind modules.

They read the world through the frozen Contract names only and never import pygame or an AI.
"""

from __future__ import annotations

import hashlib
from typing import Any

Pos = tuple[int, int]

_FLAT: dict[int, tuple[Any, dict[str, Any]]] = {}
_LIKE: dict[int, dict[tuple[str, ...], str]] = {}


class SettingError(KeyError):
    """A balance.toml key this layer needs is not there."""


def _flatten(data: Any, out: dict[str, Any]) -> None:
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, dict):
                _flatten(value, out)
            else:
                out.setdefault(key, value)


def _flat(world: Any) -> dict[str, Any]:
    balance = world.cfg.balance
    cached = _FLAT.get(id(balance))
    if cached is None or cached[0] is not balance:
        flat: dict[str, Any] = {}
        _flatten(balance.model_dump(), flat)
        cached = (balance, flat)
        _FLAT[id(balance)] = cached
    return cached[1]


def setting(world: Any, name: str) -> Any:
    """The value of balance.toml key ``name`` wherever its section is (keys are unique)."""
    try:
        return _flat(world)[name]
    except KeyError:
        raise SettingError(f"balance.toml has no key '{name}'") from None


def setting_like(world: Any, *fragments: str) -> Any:
    """The value of the first balance.toml key whose name contains every fragment (sorted)."""
    flat = _flat(world)
    memo = _LIKE.setdefault(id(flat), {})
    hit = memo.get(fragments)
    if hit is not None:
        return flat[hit]
    for key in sorted(flat):
        if all(f in key for f in fragments):
            memo[fragments] = key
            return flat[key]
    raise SettingError(f"balance.toml has no key containing {fragments}")


def section(world: Any, name: str) -> dict[str, Any]:
    """The balance.toml table called ``name`` as a dict (for example ``tasks``)."""
    value = world.cfg.balance.model_dump().get(name)
    if not isinstance(value, dict):
        raise SettingError(f"balance.toml has no table '{name}'")
    return value


def stable_index(count: int, *parts: object) -> int:
    """A stable choice in range(count) from a hashlib digest of ``parts`` (no RNG, no hash())."""
    text = "|".join(str(p) for p in parts)
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % count


def dist2(a: Pos, b: Pos) -> int:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def actor(world: Any, ident: str) -> Any | None:
    """The player or villager with this id, or None."""
    found = world.players.get(ident)
    if found is None:
        found = world.villagers.get(ident)
    return found


def pos_of(entity: Any) -> Pos:
    return (entity.x, entity.y)


def emit(world: Any, name: str, tick: int | None = None, **fields: Any) -> None:
    """Emit the registered payload ``name``, passing only the fields its model declares."""
    from ai_island.storage.events import PAYLOAD_TYPES

    model = PAYLOAD_TYPES[name]
    wanted = {k: v for k, v in fields.items() if k in model.model_fields}
    world.emit(model(**wanted), tick)


def interrupt(world: Any, kind: str, player: str, tick: int, source: str | None = None) -> None:
    """Raise an interrupt through the engine function."""
    from ai_island.rules.interrupts import raise_interrupt

    raise_interrupt(world, kind, player, tick, source)
