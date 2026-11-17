"""Time series for the observer graphs: wellbeing X per hour, trust and anger per autosave.

Read-only (SELECT only), no pygame. Both functions take a cursor so a caller can read only the
new rows on each call.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from ai_island.storage.db import RunDB

DAY_TICKS = 1440  # game minutes in a day
HOUR_TICKS = 60  # game minutes in an hour


@dataclass(frozen=True)
class RelationPoint:
    snapshot_id: int
    tick: int
    holder: str
    other: str
    trust: float
    anger: float


def x_series(
    db: RunDB, player_id: str, after_event_id: int = 0
) -> tuple[list[tuple[int, float]], int]:
    """(tick, X) points from the player's ``player_day`` events with id > ``after_event_id``.

    A player_day event at tick T (the end of a day) carries 24 hourly values; value h is placed at
    tick T - 1440 + 60 * (h + 1). Returns the points and the last event id read.
    """
    points: list[tuple[int, float]] = []
    last = after_event_id
    for event_id, event in db.events_after(after_event_id, ("player_day",)):
        last = event_id
        payload = event.payload
        if payload.player != player_id:
            continue
        base = event.tick - DAY_TICKS
        for h, value in enumerate(payload.x_hourly):
            points.append((base + HOUR_TICKS * (h + 1), float(value)))
    return points, last


def relation_series(db: RunDB, after_snapshot_id: int = 0) -> tuple[list[RelationPoint], int]:
    """Trust and anger between players at autosave ticks, from snapshots with id > the cursor.

    Only snapshots with tick > 0 and tick a multiple of the run's autosave_interval count; for
    equal ticks the largest snapshot id wins. A relation missing from a snapshot is omitted.
    Ordered by (tick, holder, other). Returns the points and the last snapshot id read.
    """
    rows = db.snapshot_states_after(after_snapshot_id)
    last = after_snapshot_id
    best: dict[int, tuple[int, str]] = {}  # tick -> (snapshot id, state_json)
    interval_cache: dict[str, int] = {}
    for snap_id, tick, state_json, config_json in rows:
        last = max(last, snap_id)
        if tick <= 0:
            continue
        interval = interval_cache.get(config_json)
        if interval is None:
            interval = int(json.loads(config_json)["run"]["autosave_interval"])
            interval_cache = {config_json: interval}
        if tick % interval != 0:
            continue
        if tick not in best or snap_id > best[tick][0]:
            best[tick] = (snap_id, state_json)
    points: list[RelationPoint] = []
    for tick in sorted(best):
        snap_id, state_json = best[tick]
        state = json.loads(state_json)
        players = ((state.get("world") or {}).get("people") or {}).get("players") or []
        batch: list[RelationPoint] = []
        for player in players:
            holder = player["id"]
            trust = player.get("trust") or {}
            anger = player.get("anger") or {}
            for other in sorted(set(trust) & set(anger)):
                batch.append(
                    RelationPoint(
                        snap_id, tick, holder, other, float(trust[other]), float(anger[other])
                    )
                )
        batch.sort(key=lambda r: (r.holder, r.other))
        points.extend(batch)
    return points, last
