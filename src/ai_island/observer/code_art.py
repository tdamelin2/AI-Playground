"""Code drawings: 16x16 two-colour shapes for items the Kenney pack lacks.

Each drawing is a 16-row grid of 16 characters: ``#`` ink (black in mono), ``o`` light (white in
mono), ``.`` transparent.
No randomness is used; every drawing is a fixed shape.
"""

from __future__ import annotations

import pygame

SIZE = 16

Colour = tuple[int, int, int, int]

BLACK = (0, 0, 0, 255)
WHITE = (255, 255, 255, 255)
CLEAR = (0, 0, 0, 0)

_BLANK = "." * SIZE

_MUSHROOMS = (
    _BLANK,
    _BLANK,
    _BLANK,
    ".....######.....",
    "....########....",
    "...##########...",
    "...##o##o####...",
    "...##########...",
    "....########....",
    ".......##.......",
    ".......##.......",
    "......####......",
    _BLANK,
    _BLANK,
    _BLANK,
    _BLANK,
)

_STRONG_POISON = (
    _BLANK,
    "......####......",
    ".....######.....",
    "....########....",
    "....#oo##oo#....",
    "....#oo##oo#....",
    "....########....",
    ".....##..##.....",
    ".....######.....",
    "......#..#......",
    ".......##.......",
    ".......##.......",
    "....#..##..#....",
    ".....#.##.#.....",
    "......####......",
    _BLANK,
)

_NEST_EGGS = (
    _BLANK,
    _BLANK,
    _BLANK,
    _BLANK,
    "....##....##....",
    "...#oo#..#oo#...",
    "...#oo#..#oo#...",
    "....##....##....",
    "..############..",
    ".##############.",
    ".#.#.#.#.#.#.#..",
    "..############..",
    "...##########...",
    _BLANK,
    _BLANK,
    _BLANK,
)

_SLEEPING = (
    _BLANK,
    "....######......",
    "..........#.....",
    ".........#......",
    "........#.......",
    ".......#........",
    "......######....",
    _BLANK,
    "...#####........",
    ".........#......",
    "........#.......",
    ".......#........",
    "......#####.....",
    _BLANK,
    _BLANK,
    _BLANK,
)

_COOKED_MEAT = (
    _BLANK,
    _BLANK,
    ".....#####......",
    "....#######.....",
    "...#########....",
    "...#########....",
    "...#########....",
    "....#######.....",
    ".....#####......",
    "......#.#.......",
    ".....#...#......",
    "....#.....##....",
    "...##.....##....",
    _BLANK,
    _BLANK,
    _BLANK,
)

_SPOILED_MEAT = (
    _BLANK,
    "..#.........#...",
    ".....#####......",
    "....#ooooo#.....",
    "...#ooooooo#....",
    "...#ooo#ooo#....",
    "...#ooooooo#....",
    "....#ooooo#.....",
    ".....#####......",
    "......#.#.......",
    ".....#...#......",
    "....#.....##....",
    "...##.....##....",
    _BLANK,
    _BLANK,
    _BLANK,
)

_FISHING_NET = (
    _BLANK,
    ".##############.",
    ".#..#..#..#..#..",
    ".##############.",
    ".#..#..#..#..#..",
    ".##############.",
    ".#..#..#..#..#..",
    ".##############.",
    ".#..#..#..#..#..",
    ".##############.",
    ".#..#..#..#..#..",
    ".##############.",
    _BLANK,
    _BLANK,
    _BLANK,
    _BLANK,
)

_PAUSE = (
    _BLANK,
    _BLANK,
    _BLANK,
    "....###..###....",
    "....###..###....",
    "....###..###....",
    "....###..###....",
    "....###..###....",
    "....###..###....",
    "....###..###....",
    "....###..###....",
    _BLANK,
    _BLANK,
    _BLANK,
    _BLANK,
    _BLANK,
)

_PAUSED_INDICATOR = (
    "################",
    "#oooooooooooooo#",
    "#oooooooooooooo#",
    "#ooo###oo###ooo#",
    "#ooo###oo###ooo#",
    "#ooo###oo###ooo#",
    "#ooo###oo###ooo#",
    "#ooo###oo###ooo#",
    "#ooo###oo###ooo#",
    "#ooo###oo###ooo#",
    "#ooo###oo###ooo#",
    "#oooooooooooooo#",
    "#oooooooooooooo#",
    "#oooooooooooooo#",
    "#oooooooooooooo#",
    "################",
)

_FONT = (
    _BLANK,
    "......####......",
    ".....######.....",
    "....##....##....",
    "....##....##....",
    "....##....##....",
    "....########....",
    "....########....",
    "....##....##....",
    "....##....##....",
    "....##....##....",
    "....##....##....",
    _BLANK,
    _BLANK,
    _BLANK,
    _BLANK,
)

_W = "o" * SIZE

# Grass: white ground with two sparse tufts (Pokemon Red style).
_GRASS = (
    _W,
    _W,
    "ooooo#o#oooooooo",
    "oooooo#ooooooooo",
    _W,
    _W,
    _W,
    _W,
    _W,
    "oooooooooooo#o#o",
    "ooooooooooooo#oo",
    _W,
    _W,
    _W,
    _W,
    _W,
)

_PATTERNS: dict[str, tuple[str, ...]] = {
    "grass": _GRASS,
    "mushrooms": _MUSHROOMS,
    "item_mushrooms": _MUSHROOMS,
    "strong_poison": _STRONG_POISON,
    "nest_eggs": _NEST_EGGS,
    "marker_sleeping": _SLEEPING,
    "item_cooked_meat": _COOKED_MEAT,
    "item_spoiled_meat": _SPOILED_MEAT,
    "tool_fishing_net": _FISHING_NET,
    "ui_pause": _PAUSE,
    "ui_paused_indicator": _PAUSED_INDICATOR,
    "ui_font": _FONT,
}

# Pixel lists for overlays and the crack. (x, y) with 0 <= x, y < 16.
_SNOW_WHITE = ((2, 3), (9, 1), (13, 6), (5, 10), (11, 12), (1, 14), (7, 6), (14, 13))
_DROUGHT_CRACK = (
    (1, 2),
    (2, 3),
    (3, 3),
    (4, 4),
    (5, 5),
    (5, 6),
    (6, 7),
    (7, 8),
    (8, 8),
    (9, 9),
    (10, 10),
    (10, 11),
    (11, 12),
    (12, 13),
)
_CRACK = (
    (7, 1),
    (6, 3),
    (7, 5),
    (6, 7),
    (7, 9),
    (6, 11),
    (7, 13),
    (6, 14),
)
_RAIN_STREAKS = ((2, 1), (10, 6), (5, 11))
_STORM_STREAKS = _RAIN_STREAKS + ((13, 2), (1, 8), (8, 13))
_BOLT = ((9, 2), (8, 3), (7, 4), (8, 5), (7, 6), (6, 7), (7, 8), (5, 10))

CODE_KEYS = frozenset(_PATTERNS) | {
    "snow",
    "drought",
    "overlay_night",
    "overlay_rain",
    "overlay_storm",
}

DAMAGED_PREFIX = "damaged_"


def _validate(name: str, rows: tuple[str, ...]) -> None:
    if len(rows) != SIZE:
        raise ValueError(f"code drawing {name!r} has {len(rows)} rows, need {SIZE}")
    for index, row in enumerate(rows):
        if len(row) != SIZE or set(row) - set("#o."):
            raise ValueError(f"code drawing {name!r} row {index} is malformed: {row!r}")


for _name, _rows in _PATTERNS.items():
    _validate(_name, _rows)


def _blank() -> pygame.Surface:
    return pygame.Surface((SIZE, SIZE), pygame.SRCALPHA, 32)


def _from_rows(
    rows: tuple[str, ...], ink: Colour = BLACK, light: Colour = WHITE, clear_light: bool = False
) -> pygame.Surface:
    surface = _blank()
    colours = {"#": ink, "o": CLEAR if clear_light else light, ".": CLEAR}
    for y, row in enumerate(rows):
        for x, char in enumerate(row):
            surface.set_at((x, y), colours[char])
    return surface


def _streaks(points: tuple[tuple[int, int], ...], ink: Colour) -> pygame.Surface:
    surface = _blank()
    for x, y in points:
        for step in range(3):
            if x + step < SIZE and y + step < SIZE:
                surface.set_at((x + step, y + step), ink)
    return surface


def hex_to_rgba(value: str) -> Colour:
    """``#rrggbb`` -> an opaque RGBA tuple."""
    text = value.lstrip("#")
    return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16), 255)


def draw_code_item(
    key: str, ink: Colour | None = None, light: Colour | None = None
) -> pygame.Surface:
    """Return the 16x16 drawing for a code item. Raises KeyError for an unknown key.

    Without ``ink`` the drawing is the black-and-white (mono) one. With ``ink`` (and ``light``)
    its black parts use ``ink`` and its white parts use ``light``; the grass ground is left
    transparent because the viewer paints the ground colour under it.
    """
    colour = ink is not None
    black = ink if ink is not None else BLACK
    white = light if light is not None else WHITE
    if key in _PATTERNS:
        return _from_rows(_PATTERNS[key], black, white, clear_light=colour and key == "grass")
    surface = _blank()
    if key == "snow":
        for x, y in _SNOW_WHITE:
            surface.set_at((x, y), white)
            if x + 1 < SIZE:
                surface.set_at((x + 1, y), black)
            if y + 1 < SIZE:
                surface.set_at((x, y + 1), black)
    elif key == "drought":
        for x, y in _DROUGHT_CRACK:
            surface.set_at((x, y), black)
    elif key == "overlay_night":
        for y in range(SIZE):
            for x in range(SIZE):
                if x % 4 == 0 and y % 4 == 0:
                    surface.set_at((x, y), black)
    elif key == "overlay_rain":
        surface = _streaks(_RAIN_STREAKS, black)
    elif key == "overlay_storm":
        surface = _streaks(_STORM_STREAKS, black)
        for x, y in _BOLT:
            surface.set_at((x, y), white)
            if x + 1 < SIZE:
                surface.set_at((x + 1, y), black)
    else:
        raise KeyError(key)
    return surface


def add_crack(base: pygame.Surface, ink: Colour | None = None) -> pygame.Surface:
    """Return a copy of ``base`` with a crack.

    Mono (no ``ink``): a white crack with a black edge where the tile is empty.
    Colour: the crack is drawn in ``ink`` only.
    """
    surface = base.copy()
    for x, y in _CRACK:
        if ink is not None:
            surface.set_at((x, y), ink)
            continue
        surface.set_at((x, y), WHITE)
        if x + 1 < SIZE and surface.get_at((x + 1, y)).a == 0:
            surface.set_at((x + 1, y), BLACK)
    return surface
