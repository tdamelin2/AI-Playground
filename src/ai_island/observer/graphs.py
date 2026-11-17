"""Graphs of one player: wellbeing X per hour, and trust and anger toward each other player.

``GraphStore`` reads the series by cursor (only new rows each time); ``render_graph`` draws three
small line charts side by side into a Surface with pygame.draw.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pygame

from ai_island.measure.series import relation_series, x_series

if TYPE_CHECKING:
    from ai_island.storage.db import RunDB

Series = tuple[tuple[int, float], ...]

_BG = (20, 24, 30)
_FRAME = (70, 78, 92)
_TEXT = (200, 205, 215)
_DIM = (130, 138, 150)


@dataclass(frozen=True)
class GraphData:
    """The series of one player, exactly as the series functions return them."""

    x: Series = ()
    trust: dict[str, Series] = field(default_factory=dict)
    anger: dict[str, Series] = field(default_factory=dict)


class GraphStore:
    """Incremental copy of the graph series. Every new database row is parsed once."""

    def __init__(self) -> None:
        self._x: dict[str, list[tuple[int, float]]] = {}
        self._x_cursor: dict[str, int] = {}
        self._rel: dict[tuple[str, str], dict[int, tuple[float, float]]] = {}
        self._rel_cursor = 0
        self.version = 0  # grows whenever new points arrive (a cache key for drawn surfaces)

    def update(self, db: RunDB, player_ids: list[str]) -> None:
        for pid in player_ids:
            points, last = x_series(db, pid, self._x_cursor.get(pid, 0))
            self._x_cursor[pid] = last
            if points:
                self._x.setdefault(pid, []).extend(points)
                self.version += 1
        rel, last_snap = relation_series(db, self._rel_cursor)
        self._rel_cursor = last_snap
        for point in rel:
            self._rel.setdefault((point.holder, point.other), {})[point.tick] = (
                point.trust,
                point.anger,
            )
        if rel:
            self.version += 1

    def data(self, player_id: str) -> GraphData:
        trust: dict[str, Series] = {}
        anger: dict[str, Series] = {}
        for (holder, other), by_tick in sorted(self._rel.items()):
            if holder != player_id:
                continue
            ticks = sorted(by_tick)
            trust[other] = tuple((t, by_tick[t][0]) for t in ticks)
            anger[other] = tuple((t, by_tick[t][1]) for t in ticks)
        return GraphData(tuple(self._x.get(player_id, ())), trust, anger)


def _plot(
    surface: pygame.Surface,
    area: pygame.Rect,
    lines: list[tuple[Series, tuple[int, int, int]]],
    ui: int,
) -> None:
    """Draw several series into ``area``, sharing one scale; flat and one-point series are fine."""
    points = [p for series, _c in lines for p in series]
    if not points or area.w < 2 or area.h < 2:
        return
    t0 = min(t for t, _v in points)
    t1 = max(t for t, _v in points)
    lo = min(v for _t, v in points)
    hi = max(v for _t, v in points)
    if hi - lo < 1e-9:
        lo, hi = lo - 1.0, hi + 1.0
    span_t = max(1, t1 - t0)

    def place(t: int, v: float) -> tuple[int, int]:
        px = area.x + round((t - t0) * (area.w - 1) / span_t)
        py = area.bottom - 1 - round((v - lo) * (area.h - 1) / (hi - lo))
        return px, py

    for series, colour in lines:
        pts = [place(t, v) for t, v in series]
        if len(pts) == 1:
            pygame.draw.circle(surface, colour, pts[0], max(1, ui))
        elif len(pts) > 1:
            pygame.draw.lines(surface, colour, False, pts, max(1, ui))


def render_graph(
    font: pygame.font.Font,
    size: tuple[int, int],
    data: GraphData,
    own_colour: tuple[int, int, int],
    other_colours: dict[str, tuple[int, int, int]],
    ui: int,
    names: dict[str, str] | None = None,
) -> pygame.Surface:
    """Three charts side by side (X, Trust, Anger) in a Surface of ``size`` pixels."""
    surface = pygame.Surface(size)
    surface.fill(_BG)
    panes = (
        ("X", {"": data.x}),
        ("Trust", data.trust),
        ("Anger", data.anger),
    )
    pane_w = max(1, size[0] // 3)
    head_h = font.get_linesize()
    for i, (title, series_map) in enumerate(panes):
        box = pygame.Rect(i * pane_w, 0, pane_w if i < 2 else size[0] - 2 * pane_w, size[1])
        pygame.draw.rect(surface, _FRAME, box, 1)
        label = font.render(title, False, _TEXT)
        surface.blit(label, (box.x + 2 * ui, box.y + ui))
        legend_x = box.x + 2 * ui + label.get_width() + 3 * ui
        if title != "X":
            sq = max(4 * ui, 4)
            for other in sorted(series_map):
                colour = other_colours.get(other, _TEXT)
                label_h = label.get_height()
                pygame.draw.rect(
                    surface, colour, (legend_x, box.y + ui + (label_h - sq) // 2, sq, sq)
                )
                legend_x += sq + ui
                full = (names or {}).get(other, other)
                text = full
                if legend_x + font.size(text)[0] + 2 * ui > box.right:
                    text = full[:1]
                tag = font.render(text, False, _TEXT)
                surface.blit(tag, (legend_x, box.y + ui))
                legend_x += tag.get_width() + 3 * ui
        area = pygame.Rect(
            box.x + 3 * ui,
            box.y + head_h + ui,
            max(2, box.w - 6 * ui),
            max(2, box.h - head_h - 4 * ui),
        )
        if not any(series_map.values()):
            note = font.render("no data yet", False, _DIM)
            if note.get_width() > box.w - 2 * ui:
                note = font.render("none", False, _DIM)
            surface.blit(note, note.get_rect(center=area.center))
            continue
        lines: list[tuple[Series, tuple[int, int, int]]] = []
        for key in sorted(series_map):
            colour = own_colour if title == "X" else other_colours.get(key, _TEXT)
            lines.append((series_map[key], colour))
        _plot(surface, area, lines, ui)
    return surface
