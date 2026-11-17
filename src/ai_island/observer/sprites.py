"""Sprite loader: cut tiles from the two sheets, draw code items, in colour or mono."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pygame

from ai_island.observer import code_art
from ai_island.observer.code_art import hex_to_rgba

if TYPE_CHECKING:
    from ai_island.config import AssetsConfig, SheetConfig

SPRITE_SIZE = 16
AUTUMN_SUFFIX = "_autumn"
_ALPHA_CUTOFF = 128
_BLACK = (0, 0, 0, 255)
_WHITE = (255, 255, 255, 255)
_CLEAR = (0, 0, 0, 0)
_MONO_LIGHT_LEVEL = 110  # Tiny Creatures pixels brighter than this become white in mono
_KENNEY_GREEN = "#38d973"
_KENNEY_LIGHT = "#cfc6b8"
_PALETTES = ("color", "mono")


def _resolve_sheet(name: str, sheet: SheetConfig, root: Path) -> Path:
    raw = str(sheet.path)
    if "urizen" in raw.lower():
        raise ValueError(f"assets.toml sheets.{name}.path may not use the Urizen pack: {raw}")
    path = Path(raw)
    return path if path.is_absolute() else Path(root) / path


def _open_sheet(name: str, sheet_cfg: SheetConfig, root: Path) -> pygame.Surface:
    if sheet_cfg.tile_size != SPRITE_SIZE:
        raise ValueError(
            f"assets.toml sheets.{name}.tile_size must be {SPRITE_SIZE}, got {sheet_cfg.tile_size}"
        )
    path = _resolve_sheet(name, sheet_cfg, root)
    if not path.is_file():
        raise FileNotFoundError(f"assets.toml sheets.{name}.path not found: {path}")
    raw_sheet = pygame.image.load(str(path))
    # Palette sheets mark "transparent" with a colour key; blitting to an alpha surface applies it.
    sheet = pygame.Surface(raw_sheet.get_size(), pygame.SRCALPHA, 32)
    sheet.blit(raw_sheet, (0, 0))
    step = sheet_cfg.tile_size + sheet_cfg.gap
    need_w = sheet_cfg.columns * step - sheet_cfg.gap
    need_h = sheet_cfg.rows * step - sheet_cfg.gap
    if sheet.get_width() < need_w or sheet.get_height() < need_h:
        raise ValueError(
            f"assets.toml sheet {path.name} is {sheet.get_size()}, "
            f"smaller than {sheet_cfg.columns}x{sheet_cfg.rows} tiles ({need_w}x{need_h})"
        )
    return sheet


def _cut(sheet: pygame.Surface, sheet_cfg: SheetConfig, col: int, row: int, mode: str):
    """One tile with binary alpha. Colour mode keeps colours; mono gives black/white only."""
    step = sheet_cfg.tile_size + sheet_cfg.gap
    x, y = col * step, row * step
    sprite = pygame.Surface((SPRITE_SIZE, SPRITE_SIZE), pygame.SRCALPHA, 32)
    for dy in range(SPRITE_SIZE):
        for dx in range(SPRITE_SIZE):
            r, g, b, a = sheet.get_at((x + dx, y + dy))
            if a < _ALPHA_CUTOFF:
                sprite.set_at((dx, dy), _CLEAR)
            elif mode == "color":
                sprite.set_at((dx, dy), (r, g, b, 255))
            else:
                sprite.set_at((dx, dy), _mono_pixel(r, g, b))
    return sprite


def _mono_pixel(r: int, g: int, b: int) -> tuple[int, int, int, int]:
    """Dark pixels become black, light ones white (so a Tiny Creature keeps its outline)."""
    level = (299 * r + 587 * g + 114 * b) // 1000
    return _WHITE if level > _MONO_LIGHT_LEVEL else _BLACK


def _mono_kenney(sprite: pygame.Surface) -> pygame.Surface:
    """Kenney mono sheet look: every opaque pixel black."""
    out = sprite.copy()
    for y in range(SPRITE_SIZE):
        for x in range(SPRITE_SIZE):
            if out.get_at((x, y)).a:
                out.set_at((x, y), _BLACK)
    return out


def _replace_colour(
    sprite: pygame.Surface, old: tuple[int, int, int, int], new: tuple[int, int, int, int]
) -> pygame.Surface:
    out = sprite.copy()
    for y in range(SPRITE_SIZE):
        for x in range(SPRITE_SIZE):
            if tuple(out.get_at((x, y))) == old:
                out.set_at((x, y), new)
    return out


def _autumn_variant(sprite: pygame.Surface, colours: list[tuple[int, int, int, int]]):
    """Green pixels become autumn colours in a fixed pixel pattern (no randomness)."""
    green = hex_to_rgba(_KENNEY_GREEN)
    out = sprite.copy()
    for y in range(SPRITE_SIZE):
        for x in range(SPRITE_SIZE):
            if tuple(out.get_at((x, y))) == green:
                out.set_at((x, y), colours[(x * 3 + y * 5) % len(colours)])
    return out


def load_sprites(
    assets: AssetsConfig, root: Path, palette: str | None = None
) -> dict[str, pygame.Surface]:
    """Load every item in ``assets`` as a 16x16 surface, plus ``<key>_autumn`` variants.

    ``palette`` is "color" or "mono" (None uses ``assets.palette``). Colour mode keeps the
    sheet colours; code drawings use only their ink colour and ``code_light``. Mono mode gives
    only black, white and transparent pixels. Raises ValueError / FileNotFoundError /
    pygame.error on any bad entry. No display is needed.
    """
    mode = assets.palette if palette is None else palette
    if mode not in _PALETTES:
        raise ValueError(f"palette must be 'color' or 'mono', got {mode!r}")
    colors = assets.colors
    light = hex_to_rgba(colors.code_light)
    sheets = {
        name: (cfg, _open_sheet(name, cfg, root))
        for name, cfg in (
            ("kenney", assets.sheets.kenney),
            ("tiny_creatures", assets.sheets.tiny_creatures),
        )
    }
    kenney_light = hex_to_rgba(_KENNEY_LIGHT)

    sprites: dict[str, pygame.Surface] = {}
    pending_damaged: list[str] = []
    for key, item in assets.items.items():
        if item.source in sheets:
            cfg, sheet = sheets[item.source]
            if item.col is None or item.row is None:
                raise ValueError(f"assets.toml items.{key}: {item.source} item needs col and row")
            if not (0 <= item.col < cfg.columns and 0 <= item.row < cfg.rows):
                raise ValueError(
                    f"assets.toml items.{key}: tile ({item.col}, {item.row}) is outside the sheet"
                )
            sprite = _cut(sheet, cfg, item.col, item.row, mode)
            if mode == "mono" and item.source == "kenney":
                sprite = _mono_kenney(sprite)
            if mode == "color" and key in colors.players:
                sprite = _replace_colour(sprite, kenney_light, hex_to_rgba(colors.players[key]))
            if item.flip:
                sprite = pygame.transform.flip(sprite, True, False)
            sprites[key] = sprite
        elif item.source == "code":
            if key.startswith(code_art.DAMAGED_PREFIX):
                pending_damaged.append(key)
            elif key in code_art.CODE_KEYS:
                if mode == "color":
                    sprites[key] = code_art.draw_code_item(key, hex_to_rgba(colors.ink[key]), light)
                else:
                    sprites[key] = code_art.draw_code_item(key)
            else:
                raise ValueError(f"assets.toml items.{key}: no code drawing exists for this key")
        else:
            raise ValueError(f"assets.toml items.{key}: unknown source {item.source!r}")

    for key in pending_damaged:
        base_key = key[len(code_art.DAMAGED_PREFIX) :]
        if base_key not in sprites:
            raise ValueError(
                f"assets.toml items.{key}: base item {base_key!r} is missing or not a drawn sprite"
            )
        ink = hex_to_rgba(colors.ink[key]) if mode == "color" else None
        sprites[key] = code_art.add_crack(sprites[base_key], ink)

    autumn = [hex_to_rgba(h) for h in colors.autumn]
    for key in colors.autumn_items:
        if key not in sprites:
            raise ValueError(f"assets.toml colors.autumn_items: '{key}' is not a loaded sprite")
        sprites[key + AUTUMN_SUFFIX] = (
            _autumn_variant(sprites[key], autumn) if mode == "color" else sprites[key].copy()
        )

    palette_set = {hex_to_rgba(h) for h in colors.kenney_palette}
    free_colour = {k for k, v in assets.items.items() if v.source == "tiny_creatures"}
    for key, sprite in sprites.items():
        _audit(key, sprite, mode, palette_set, key in free_colour)
    return sprites


def _audit(
    key: str,
    sprite: pygame.Surface,
    mode: str,
    palette_set: set[tuple[int, int, int, int]],
    free_colour: bool,
) -> None:
    """Check one sprite against the rule of the active mode."""
    if sprite.get_size() != (SPRITE_SIZE, SPRITE_SIZE):
        raise ValueError(f"sprite {key!r} is {sprite.get_size()}, need 16x16")
    allowed = {_BLACK, _WHITE} if mode == "mono" else palette_set
    for y in range(SPRITE_SIZE):
        for x in range(SPRITE_SIZE):
            pixel = tuple(sprite.get_at((x, y)))
            if pixel[3] == 0:
                continue
            if pixel[3] != 255:
                raise ValueError(
                    f"sprite {key!r} pixel ({x}, {y}) is {pixel}: alpha must be 0 or 255"
                )
            if free_colour and mode == "color":
                continue
            if pixel not in allowed:
                rule = (
                    "only black, white, transparent allowed"
                    if mode == "mono"
                    else "only the Kenney palette colours and transparency allowed"
                )
                raise ValueError(f"sprite {key!r} pixel ({x}, {y}) is {pixel}: {rule}")
