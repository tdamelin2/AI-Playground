"""Window layout: the top bar, map, side panel, mini-map and inspector rectangles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pygame

if TYPE_CHECKING:
    from ai_island.config import ViewConfig


def view_option(view: ViewConfig, name: str, default: Any) -> Any:
    """A ViewConfig value, or ``default`` (the Contract value) when the field does not exist."""
    return getattr(view, name, default)


@dataclass(frozen=True)
class Layout:
    ui_scale: int
    top_bar: pygame.Rect
    map: pygame.Rect
    panel: pygame.Rect
    minimap: pygame.Rect
    inspector: pygame.Rect


def effective_ui_scale(win_w: int, win_h: int, ui_choice: int, view: ViewConfig) -> int:
    """Auto (choice 0) from the window height, else the choice; lowered until the bars fit."""
    ui = ui_choice if ui_choice > 0 else max(1, win_h // view.ui_reference_height)
    while ui > 1 and (view.panel_width * ui > win_w // 2 or view.top_bar_height * ui > win_h // 8):
        ui -= 1
    return max(1, ui)


def compute_layout(
    win_w: int,
    win_h: int,
    ui_choice: int,
    panel_visible: bool,
    minimap_visible: bool,
    view: ViewConfig,
) -> Layout:
    ui = effective_ui_scale(win_w, win_h, ui_choice, view)
    bar = min(view.top_bar_height * ui, win_h)
    top_bar = pygame.Rect(0, 0, win_w, bar)
    panel_w = min(view.panel_width * ui, win_w)
    body_h = max(0, win_h - bar)
    if panel_visible:
        panel = pygame.Rect(win_w - panel_w, bar, panel_w, body_h)
        map_rect = pygame.Rect(0, bar, win_w - panel_w, body_h)
    else:
        panel = pygame.Rect(win_w, bar, 0, 0)
        map_rect = pygame.Rect(0, bar, win_w, body_h)

    minimap = pygame.Rect(map_rect.x, map_rect.y, 0, 0)
    if minimap_visible:
        margin = int(view_option(view, "minimap_margin", 8)) * ui
        size = int(view_option(view, "minimap_size", 160)) * ui
        size = min(size, map_rect.w - 2 * margin, map_rect.h - 2 * margin)
        if size > 0:
            minimap = pygame.Rect(map_rect.x + margin, map_rect.bottom - margin - size, size, size)

    inspector = pygame.Rect(panel.x, panel.y, 0, 0)
    if panel.w > 0:
        pad = 4 * ui
        top = panel.y + pad + 2 * (28 * ui) + pad  # below the two rows of tab buttons
        height = min(int(view_option(view, "inspector_height", 300)) * ui, panel.bottom - top)
        if height > 0:
            inspector = pygame.Rect(panel.x, top, panel.w, height)
    return Layout(ui, top_bar, map_rect, panel, minimap, inspector)
