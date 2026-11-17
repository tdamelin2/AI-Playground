"""Activity bubbles: where a bubble goes so that it never covers the bars, panel or mini-map."""

from __future__ import annotations

import pygame


def place_bubble(
    sprite: pygame.Rect,
    size: tuple[int, int],
    bounds: pygame.Rect,
    forbidden: list[pygame.Rect],
) -> pygame.Rect | None:
    """A rectangle of ``size`` above (else below) ``sprite``, inside ``bounds`` and clear of
    every ``forbidden`` rectangle, or None when there is no such place."""
    width, height = size
    if width > bounds.w or height > bounds.h:
        return None
    if any(f.collidepoint(sprite.center) for f in forbidden):
        return None
    for top in (sprite.top - height, sprite.bottom):
        rect = pygame.Rect(sprite.centerx - width // 2, top, width, height)
        rect.clamp_ip(bounds)
        if rect.colliderect(sprite):
            continue
        if any(rect.colliderect(f) for f in forbidden):
            continue
        return rect
    return None
