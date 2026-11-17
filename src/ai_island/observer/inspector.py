"""Inspector sections: label / value rows about the selected person, built from a WorldFrame."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ai_island.storage.db import RunDB
    from ai_island.world.view import AgentView, PlayerPanel, WorldFrame

Rows = list[tuple[str, str]]


@dataclass(frozen=True)
class Section:
    """A named group of inspector rows. ``rows(frame, db, selected_id)`` returns the lines."""

    name: str
    rows: Callable[[WorldFrame, RunDB | None, str], Rows]


def agent_of(frame: WorldFrame, ident: str) -> AgentView | None:
    """The person on the map with this id (a dead player is not on the map), else None."""
    for panel in frame.panels:
        if panel.id == ident and not panel.alive:
            return None
    for agent in (*frame.players, *frame.villagers):
        if agent.id == ident:
            return agent
    return None


def panel_of(frame: WorldFrame, ident: str) -> PlayerPanel | None:
    for panel in frame.panels:
        if panel.id == ident:
            return panel
    return None


def name_of(frame: WorldFrame, ident: str) -> str:
    return dict(frame.names).get(ident, ident)


def _identity(frame: WorldFrame, _db: Any, ident: str) -> Rows:
    rows: Rows = [("Name", name_of(frame, ident))]
    agent = agent_of(frame, ident)
    if agent is None:
        rows.append(("Status", "not on the map now"))
        return rows
    if agent.kind == "player":
        rows.append(("Village", f"{name_of(frame, agent.id)}'s village"))
    elif agent.leader:
        rows.append(("Village", f"{name_of(frame, agent.leader)}'s village"))
    else:
        rows.append(("Village", "wanderer"))
    return rows


def _activity(frame: WorldFrame, _db: Any, ident: str) -> Rows:
    agent = agent_of(frame, ident)
    if agent is None:
        return []
    text = f"{agent.activity} {agent.activity_target}".strip()
    return [("Activity", text), ("Progress", f"{round(agent.activity_progress * 100)}%")]


def _body(frame: WorldFrame, _db: Any, ident: str) -> Rows:
    agent = agent_of(frame, ident)
    if agent is None:
        return []
    return [
        ("Hunger", str(round(agent.hunger))),
        ("Thirst", str(round(agent.thirst))),
        ("Cold", str(round(agent.cold))),
        ("Rest", str(round(agent.rest))),
        ("Health", str(round(agent.health))),
        ("Pain", str(round(agent.pain))),
        ("Sickness", agent.sickness or "none"),
    ]


def _player(frame: WorldFrame, _db: Any, ident: str) -> Rows:
    panel = panel_of(frame, ident)
    if panel is None:
        return []
    rows: Rows = [
        ("Feeling", panel.feeling),
        ("X", f"{panel.x:.1f}"),
        ("Hooked", "yes" if panel.hooked else "no"),
    ]
    agent = agent_of(frame, ident)
    if agent is not None:
        items = ", ".join(f"{kind} {count}" for kind, count in agent.items)
        tools = ", ".join(f"{kind} {tier} ({dur})" for kind, tier, dur in agent.tools)
        rows += [("Items", items or "none"), ("Tools", tools or "none")]
    return rows


def _villager(frame: WorldFrame, _db: Any, ident: str) -> Rows:
    agent = agent_of(frame, ident)
    if agent is None or agent.kind != "villager":
        return []
    bond = "none" if agent.bond_leader is None else str(round(agent.bond_leader))
    return [
        ("Job", agent.job or "none"),
        ("Work level", agent.work_level),
        ("Loyalty", str(round(agent.loyalty))),
        ("Bond with leader", bond),
    ]


DEFAULT_SECTIONS: tuple[Section, ...] = (
    Section("Who", _identity),
    Section("Doing", _activity),
    Section("Body", _body),
    Section("Player", _player),
    Section("Villager", _villager),
)


def collect_rows(sections: list[Section], frame: WorldFrame, db: RunDB | None, ident: str) -> Rows:
    """All rows of all sections, in section order."""
    rows: Rows = []
    for section in sections:
        rows.extend(section.rows(frame, db, ident))
    return rows
