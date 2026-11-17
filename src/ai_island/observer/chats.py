"""Chat filters and the village guide text. Pure functions over frames and chat rows."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ai_island.world.view import WorldFrame

FILTER_KINDS = ("all", "village", "person", "heard")
NO_SELECTION_TEXT = "Select someone to see what they heard."


def guide_lines(frame: WorldFrame) -> list[str]:
    """One line per village: ``"<leader name>: <members or nobody>"``, wanderers last."""
    lines = []
    for entry in frame.village_guide:
        members = ", ".join(name for _id, name in entry.members) or "nobody"
        lines.append(f"{entry.leader_name}: {members}")
    return lines


def village_ids(frame: WorldFrame, leader_id: str) -> frozenset[str]:
    """The leader and the members of one village (``""`` = the wanderers, who have no leader)."""
    for entry in frame.village_guide:
        if entry.leader_id == leader_id:
            ids = {vid for vid, _name in entry.members}
            if leader_id:
                ids.add(leader_id)
            return frozenset(ids)
    return frozenset({leader_id} if leader_id else ())


def row_matches(
    row: Any,
    kind: str,
    ident: str | None,
    village: frozenset[str],
    selected: str | None,
) -> bool:
    """Does a chat row belong to this filter? Hearing alone doesn't count for villages."""
    if kind == "all":
        return True
    if kind == "village":
        return row.speaker in village or any(t in village for t in row.targets)
    if kind == "person":
        return row.speaker == ident or ident in row.targets
    if kind == "heard":
        return selected is not None and selected in row.hearers
    return False
