"""World history: the major events of a run as plain sentences, in time order."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from ai_island.storage.events import Event

HISTORY_TYPES: tuple[str, ...] = (
    "died",
    "villager_died",
    "villager_left",
    "harm",
    "dog_attack",
    "land_claimed",
    "structure_built",
    "structure_damaged",
    "weather_changed",
    "season_changed",
)

# History kinds the observer flashes on the map (and J jumps to).
FLASH_KINDS: tuple[str, ...] = (
    "death",
    "villager_death",
    "villager_departure",
    "theft",
    "attack",
    "land_claim",
    "building_damaged",
)

_BAD_WEATHER = ("storm", "drought")


@dataclass(frozen=True)
class HistoryRow:
    event_id: int
    tick: int
    kind: str
    text: str
    who: tuple[str, ...] = ()  # ids of the people involved, most important first
    x: int = -1  # tile of the event, -1 when unknown
    y: int = -1


def _row(
    event_id: int,
    event: Event,
    kind: str,
    text: str,
    who: tuple[str, ...] = (),
    x: int = -1,
    y: int = -1,
) -> HistoryRow:
    return HistoryRow(event_id, event.tick, kind, text, who, x, y)


def history_entries(
    events: Iterable[tuple[int, Event]],
    names: Mapping[str, str],
    structures: dict[int, tuple[int, int, str]] | None = None,
) -> list[HistoryRow]:
    """History rows for the major events, ordered by (tick, event id). Unknown ids stay raw.

    ``structures`` maps a structure id to (x, y, owner); it is read for damage rows and updated
    from structure_built events, so a caller that pulls events in batches keeps one dict.
    """
    if structures is None:
        structures = {}

    def name(ident: str | None) -> str:
        if ident is None:
            return "nobody"
        return names.get(ident, ident)

    rows: list[HistoryRow] = []
    for event_id, event in events:
        p = event.payload
        t = event.type
        if t == "died":
            rows.append(
                _row(event_id, event, "death", f"{name(p.player)} died ({p.cause})",
                     (p.player,), p.x, p.y)
            )  # fmt: skip
        elif t == "villager_died":
            who = (p.villager,) if p.leader is None else (p.villager, p.leader)
            rows.append(
                _row(event_id, event, "villager_death", f"{name(p.villager)} died ({p.cause})",
                     who, p.x, p.y)
            )  # fmt: skip
        elif t == "villager_left":
            who = (p.villager, p.leader) if p.to is None else (p.villager, p.leader, p.to)
            rows.append(
                _row(
                    event_id,
                    event,
                    "villager_departure",
                    f"{name(p.villager)} left {name(p.leader)} ({p.reason})",
                    who,
                )
            )
        elif t == "harm" and p.kind == "steal":
            rows.append(
                _row(event_id, event, "theft", f"{name(p.actor)} stole from {name(p.victim)}",
                     (p.actor, p.victim), p.x, p.y)
            )  # fmt: skip
        elif t == "harm" and p.kind == "attack":
            rows.append(
                _row(event_id, event, "attack", f"{name(p.actor)} attacked {name(p.victim)}",
                     (p.actor, p.victim), p.x, p.y)
            )  # fmt: skip
        elif t == "dog_attack":
            rows.append(
                _row(event_id, event, "dog_attack", f"A dog attacked {name(p.victim)}",
                     (p.victim,), p.x, p.y)
            )  # fmt: skip
        elif t == "land_claimed":
            rows.append(
                _row(
                    event_id,
                    event,
                    "land_claim",
                    f"{name(p.player)} claimed land at ({p.x}, {p.y})",
                    (p.player,),
                    p.x,
                    p.y,
                )
            )
        elif t == "structure_built":
            structures[p.id] = (p.x, p.y, p.owner)
            rows.append(
                _row(
                    event_id,
                    event,
                    "building_finished",
                    f"{name(p.owner)} finished a {p.kind} at ({p.x}, {p.y})",
                    (p.owner,),
                    p.x,
                    p.y,
                )
            )
        elif t == "structure_damaged":
            known = structures.get(p.id)
            rows.append(
                _row(
                    event_id,
                    event,
                    "building_damaged",
                    f"A {p.kind} was damaged (hp {p.hp})",
                    () if known is None else (known[2],),
                    -1 if known is None else known[0],
                    -1 if known is None else known[1],
                )
            )
        elif t == "weather_changed" and p.weather in _BAD_WEATHER:
            rows.append(_row(event_id, event, p.weather, f"A {p.weather} began"))
        elif t == "season_changed":
            rows.append(
                _row(
                    event_id,
                    event,
                    "season_change",
                    f"{p.season.capitalize()} began (year {p.year})",
                )
            )
    rows.sort(key=lambda r: (r.tick, r.event_id))
    return rows
