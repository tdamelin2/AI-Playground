"""Mini-map: the whole island in a small square, with owned land, people and the view frame."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

if TYPE_CHECKING:
    from ai_island.world.view import WorldFrame

_FRAME_COLOUR = (255, 255, 255)
_EDGE = (20, 24, 30)
_OWNER_MIX = 0.45  # how much of the owner's colour tints a claimed tile


def tile_to_pixel(rect: pygame.Rect, map_w: int, map_h: int, x: int, y: int) -> tuple[int, int]:
    """Mini-map pixel at the centre of tile (x, y)."""
    return (
        rect.x + int((x + 0.5) * rect.w / max(1, map_w)),
        rect.y + int((y + 0.5) * rect.h / max(1, map_h)),
    )


def pixel_to_tile(
    rect: pygame.Rect, map_w: int, map_h: int, px: int, py: int
) -> tuple[int, int] | None:
    """The tile under a pixel inside ``rect`` (floor mapping), or None outside it."""
    if not rect.collidepoint(px, py):
        return None
    tx = min(map_w - 1, (px - rect.x) * map_w // rect.w)
    ty = min(map_h - 1, (py - rect.y) * map_h // rect.h)
    return tx, ty


def base_surface(
    frame: WorldFrame,
    ground: dict[str, tuple[int, int, int]],
    owners: dict[int, tuple[int, int, int]],
    fallback: tuple[int, int, int],
) -> pygame.Surface:
    """One pixel per tile: ground colour, tinted by the owner where land is owned."""
    surf = pygame.Surface((frame.width, frame.height))
    surf.fill(fallback)
    for y, row in enumerate(frame.terrain):
        for x, kind in enumerate(row):
            surf.set_at((x, y), ground.get(kind, fallback))
    for x, y, owner in frame.owned_tiles:
        colour = owners.get(owner)
        if colour is None or not (0 <= x < frame.width and 0 <= y < frame.height):
            continue
        base = surf.get_at((x, y))
        surf.set_at(
            (x, y),
            tuple(
                round(b * (1 - _OWNER_MIX) + c * _OWNER_MIX)
                for b, c in zip(base[:3], colour, strict=False)
            ),
        )
    return surf


def draw_frame_box(
    screen: pygame.Surface,
    rect: pygame.Rect,
    visible: tuple[int, int, int, int],
    map_w: int,
    map_h: int,
    width: int,
) -> None:
    """Outline of the part of the island the camera shows."""
    vx, vy, vw, vh = visible
    box = pygame.Rect(
        rect.x + vx * rect.w // max(1, map_w),
        rect.y + vy * rect.h // max(1, map_h),
        max(2, vw * rect.w // max(1, map_w)),
        max(2, vh * rect.h // max(1, map_h)),
    ).clip(rect)
    pygame.draw.rect(screen, _FRAME_COLOUR, box, width)


def draw_border(screen: pygame.Surface, rect: pygame.Rect, width: int) -> None:
    pygame.draw.rect(screen, _EDGE, rect.inflate(2 * width, 2 * width), width)
