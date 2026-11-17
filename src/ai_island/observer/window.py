"""Window size helpers: the usable desktop area and the display size presets."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pygame

if TYPE_CHECKING:
    from ai_island.config import ViewConfig

MIN_WINDOW = (320, 240)


def is_dummy() -> bool:
    try:
        return pygame.display.get_driver() == "dummy"
    except pygame.error:
        return False


def _windows_usable_area() -> tuple[int, int] | None:
    """Work area (desktop minus taskbar) minus the window caption and frame, in real pixels."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        rect = wintypes.RECT()
        if not user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):  # SPI_GETWORKAREA
            return None
        width, height = rect.right - rect.left, rect.bottom - rect.top
        try:
            dpi = int(user32.GetDpiForSystem())
            caption = user32.GetSystemMetricsForDpi(4, dpi)  # SM_CYCAPTION
            frame = user32.GetSystemMetricsForDpi(33, dpi)  # SM_CYSIZEFRAME
            padded = user32.GetSystemMetricsForDpi(92, dpi)  # SM_CXPADDEDBORDER
        except (AttributeError, OSError):
            caption, frame, padded = (
                user32.GetSystemMetrics(4),
                user32.GetSystemMetrics(33),
                user32.GetSystemMetrics(92),
            )
        width -= 2 * (frame + padded)
        height -= caption + 2 * (frame + padded)
        if width <= 0 or height <= 0:
            return None
        return width, height
    except Exception:  # noqa: BLE001 - metrics are cosmetic; fall back to the margin rule
        return None


def usable_desktop(view: ViewConfig) -> tuple[int, int]:
    """Largest window that fits the desktop. The dummy driver uses the configured window size."""
    if is_dummy():
        return view.window_width, view.window_height
    area = _windows_usable_area()
    if area is not None:
        return area
    try:
        width, height = pygame.display.get_desktop_sizes()[0]
    except (pygame.error, IndexError):
        return view.window_width, view.window_height
    if width <= 0 or height <= 0:
        return view.window_width, view.window_height
    margin = view.window_margin
    return max(MIN_WINDOW[0], width - margin), max(MIN_WINDOW[1], height - margin)


def desktop_size(view: ViewConfig) -> tuple[int, int]:
    """Full size of the screen, for full-screen mode."""
    try:
        width, height = pygame.display.get_desktop_sizes()[0]
    except (pygame.error, IndexError):
        return view.window_width, view.window_height
    if width <= 0 or height <= 0:
        return view.window_width, view.window_height
    return width, height


def parse_size(text: str) -> tuple[int, int] | None:
    """``"1600x1000"`` -> (1600, 1000); None for anything else."""
    parts = text.split("x")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        return None
    return int(parts[0]), int(parts[1])


def preset_size(name: str, view: ViewConfig, presets: tuple[str, ...]) -> tuple[int, int]:
    """Pixel size for a windowed preset ("fit" or "WxH"); bigger than the desktop -> largest fit."""
    usable = usable_desktop(view)
    if name == "fit":
        return usable
    size = parse_size(name)
    if size is None:
        return usable
    if is_dummy() or (size[0] <= usable[0] and size[1] <= usable[1]):
        return size
    fitting = [
        s
        for s in (parse_size(p) for p in presets)
        if s is not None and s[0] <= usable[0] and s[1] <= usable[1]
    ]
    return max(fitting, key=lambda s: s[0] * s[1]) if fitting else usable
