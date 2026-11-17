"""One map camera: every place that turns a tile into a screen pixel (or back) uses it."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from ai_island.observer.sprites import SPRITE_SIZE

if TYPE_CHECKING:
    from ai_island.world.view import EntityView, WorldFrame


def slide_position(entity: EntityView, tick: int, sub_tick: float, scale: int) -> tuple[int, int]:
    """Map-pixel top-left of an entity's sprite, part-way between its tiles.

    Progress ``p`` runs 0 to 1 from ``move_start_tick`` to ``move_end_tick`` using game time
    ``tick + sub_tick``; an entity that is not moving (end <= start) sits on its tile. The sprite
    is offset by whole sprite pixels (round(16 * p)) toward the destination tile.
    """
    span = entity.move_end_tick - entity.move_start_tick
    if span <= 0:
        progress = 1.0
    else:
        progress = (tick + sub_tick - entity.move_start_tick) / span
        progress = max(0.0, min(1.0, progress))
    offset = round(SPRITE_SIZE * progress)
    dx = offset * (entity.to_x - entity.from_x)
    dy = offset * (entity.to_y - entity.from_y)
    return (
        (entity.from_x * SPRITE_SIZE + dx) * scale,
        (entity.from_y * SPRITE_SIZE + dy) * scale,
    )


class MapCamera:
    """Scale, scroll offset (in tiles) and map rectangle; the single source of map positions."""

    def __init__(self) -> None:
        self.map_rect = pygame.Rect(0, 0, 0, 0)
        self.scale = 0
        self.offset_x = 0
        self.offset_y = 0
        self.map_w = 0
        self.map_h = 0

    # -- sizes ----------------------------------------------------------------------
    @property
    def tile(self) -> int:
        """Screen pixels of one tile (0 until a scale is chosen)."""
        return SPRITE_SIZE * self.scale

    def view_counts(self) -> tuple[int, int]:
        """Tiles that touch the map rectangle along each axis (partly visible ones included)."""
        tile = self.tile
        if tile <= 0:
            return 1, 1
        return (
            max(1, -(-self.map_rect.w // tile)),
            max(1, -(-self.map_rect.h // tile)),
        )

    def clamp(self) -> None:
        vis_w, vis_h = self.view_counts()
        self.offset_x = max(0, min(self.offset_x, self.map_w - vis_w))
        self.offset_y = max(0, min(self.offset_y, self.map_h - vis_h))

    def origin(self) -> tuple[int, int]:
        """Screen pixel of tile (0, 0): includes centring of a map smaller than its rectangle."""
        tile = self.tile
        rect = self.map_rect
        pad_x = rect.x + max(0, (rect.w - self.map_w * tile) // 2)
        pad_y = rect.y + max(0, (rect.h - self.map_h * tile) // 2)
        return pad_x - self.offset_x * tile, pad_y - self.offset_y * tile

    # -- transforms -----------------------------------------------------------------
    def world_to_screen(self, tx: int, ty: int) -> tuple[int, int]:
        """Screen pixel of the top-left corner of tile (tx, ty)."""
        ox, oy = self.origin()
        tile = self.tile
        return ox + tx * tile, oy + ty * tile

    def screen_to_tile(self, px: int, py: int) -> tuple[int, int]:
        """The tile under a screen pixel (floor); may lie outside the island."""
        ox, oy = self.origin()
        tile = max(1, self.tile)
        return (px - ox) // tile, (py - oy) // tile

    def on_map(self, tx: int, ty: int) -> bool:
        return 0 <= tx < self.map_w and 0 <= ty < self.map_h

    def agent_rect(self, agent: EntityView, frame: WorldFrame, sub_tick: float) -> pygame.Rect:
        """Screen rectangle of a person's sprite, with the same sliding as the drawing."""
        mx, my = slide_position(agent, frame.tick, sub_tick, self.scale)
        ox, oy = self.origin()
        return pygame.Rect(ox + mx, oy + my, self.tile, self.tile)

    def center_on(self, tx: int, ty: int) -> None:
        """Scroll so tile (tx, ty) is in the middle of the map rectangle (clamped to the island)."""
        tile = max(1, self.tile)
        rect = self.map_rect
        self.offset_x = round(tx + 0.5 - rect.w / (2 * tile))
        self.offset_y = round(ty + 0.5 - rect.h / (2 * tile))
        self.clamp()

    def visible_tiles(self) -> tuple[int, int, int, int]:
        """``(x, y, w, h)`` in tiles of the part of the island that is on screen."""
        vis_w, vis_h = self.view_counts()
        x, y = self.offset_x, self.offset_y
        return x, y, max(0, min(self.map_w - x, vis_w)), max(0, min(self.map_h - y, vis_h))
