"""The map window. Read-only: it draws a WorldFrame and never steps the world."""

from __future__ import annotations

import os
import sys
import time
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING

import pygame

from ai_island.observer.camera import MapCamera, slide_position
from ai_island.observer.code_art import hex_to_rgba
from ai_island.observer.sprites import AUTUMN_SUFFIX, SPRITE_SIZE, load_sprites
from ai_island.observer.window import usable_desktop

if TYPE_CHECKING:
    from ai_island.config import AssetsConfig, LightConfig, ViewConfig
    from ai_island.world.view import AgentView, WorldFrame

_WHITE = (255, 255, 255)
_FPS_WINDOW = 30
_SNOW_TERRAIN = frozenset(
    {
        "grass",
        "sand",
        "tree",
        "stump",
        "farmland_empty",
        "farmland_planted",
        "farmland_growing",
        "farmland_ready",
        "farmland_failed",
        "rocky",
        "rocky_depleted",
    }
)
_DROUGHT_TERRAIN = frozenset(
    {"grass", "sand", "farmland_empty", "farmland_planted", "farmland_growing", "farmland_failed"}
)


def light_alpha(daylight: float, weather: str, light: LightConfig) -> int:
    """Strength (0-255) of the one full-window light layer: night darkness plus weather."""
    alpha = round(light.night_alpha * (1.0 - daylight))
    if weather == "rain":
        alpha += light.rain_alpha
    elif weather == "storm":
        alpha += light.storm_alpha
    return max(0, min(255, alpha))


def _set_dpi_awareness() -> None:
    """Ask Windows for real pixels (no blurry upscaling). Does nothing elsewhere or on failure."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:  # noqa: BLE001 - DPI awareness is cosmetic, never fatal
        return


class Viewer:
    """Draws the island at a whole-number scale. Arrow keys scroll when the map does not fit."""

    def __init__(self, assets: AssetsConfig, view: ViewConfig, root: Path) -> None:
        self._view = view
        self._assets = assets
        self._root = Path(root)
        os.environ.setdefault("SDL_WINDOWS_DPI_AWARENESS", "permonitorv2")
        _set_dpi_awareness()
        pygame.init()
        self._camera = MapCamera()
        self._win_w, self._win_h = self._window_size(view)
        self._screen = pygame.display.set_mode((self._win_w, self._win_h), pygame.RESIZABLE)
        self.speed: float = float(view.speed)
        pygame.key.set_repeat(250, 60)
        self._palette = assets.palette
        self._sprites = load_sprites(assets, self._root, self._palette)
        self._scale = 0
        self._scaled: dict[str, pygame.Surface] = {}
        self._scaled_flipped: dict[str, pygame.Surface] = {}
        self._tinted: dict[tuple[str, int, int, str], pygame.Surface] = {}
        self._closed = False
        self._terrain_surface: pygame.Surface | None = None
        self._terrain_key: tuple[object, ...] | None = None
        self._terrain_rows: tuple[tuple[str, ...], ...] = ()
        self._map_rect = pygame.Rect(0, 0, self._win_w, self._win_h)
        self._graves: frozenset[tuple[int, int]] = frozenset()
        self._light_surface = pygame.Surface((self._win_w, self._win_h))
        self._light_surface.fill(hex_to_rgba(assets.light.night_color)[:3])
        self._draw_times: deque[float] = deque(maxlen=_FPS_WINDOW)
        self._autumn_items = frozenset(assets.colors.autumn_items)

    # -- camera state (kept under the old names) ---------------------------------
    @property
    def camera(self) -> MapCamera:
        return self._camera

    @property
    def _scale(self) -> int:
        return self._camera.scale

    @_scale.setter
    def _scale(self, value: int) -> None:
        self._camera.scale = value

    @property
    def _offset_x(self) -> int:
        return self._camera.offset_x

    @_offset_x.setter
    def _offset_x(self, value: int) -> None:
        self._camera.offset_x = value

    @property
    def _offset_y(self) -> int:
        return self._camera.offset_y

    @_offset_y.setter
    def _offset_y(self, value: int) -> None:
        self._camera.offset_y = value

    @property
    def _map_w(self) -> int:
        return self._camera.map_w

    @_map_w.setter
    def _map_w(self, value: int) -> None:
        self._camera.map_w = value

    @property
    def _map_h(self) -> int:
        return self._camera.map_h

    @_map_h.setter
    def _map_h(self, value: int) -> None:
        self._camera.map_h = value

    @property
    def _map_rect(self) -> pygame.Rect:
        return self._camera.map_rect

    @_map_rect.setter
    def _map_rect(self, value: pygame.Rect) -> None:
        self._camera.map_rect = pygame.Rect(value)

    # -- public read-only accessors ----------------------------------------------
    @property
    def sprites(self) -> dict[str, pygame.Surface]:
        """Every loaded sprite at scale 1 (16x16). Do not change them."""
        return self._sprites

    @property
    def palette(self) -> str:
        return self._palette

    @property
    def fps(self) -> float:
        """Frames per second measured over the most recent draws (0.0 before two draws)."""
        if len(self._draw_times) < 2:
            return 0.0
        span = self._draw_times[-1] - self._draw_times[0]
        return (len(self._draw_times) - 1) / span if span > 0 else 0.0

    def set_palette(self, palette: str) -> None:
        """Switch between "color" and "mono"; every cache is rebuilt on the next draw."""
        if palette == self._palette:
            return
        self._sprites = load_sprites(self._assets, self._root, palette)
        self._palette = palette
        self._scale = 0
        self._terrain_key = None

    def ground_color(self, terrain: str, weather: str) -> tuple[int, int, int] | None:
        """Colour painted under a terrain sprite; None in mono (white background)."""
        if self._palette == "mono":
            return None
        colors = self._assets.colors
        if terrain == "grass" and weather == "drought":
            return hex_to_rgba(colors.drought_ground)[:3]
        return hex_to_rgba(colors.ground[terrain])[:3]

    def terrain_layers(self, terrain: str, season: str, weather: str) -> tuple[str, ...]:
        """Sprite keys drawn on one terrain tile, bottom to top."""
        base = terrain
        if season == "autumn" and terrain in self._autumn_items:
            base = terrain + AUTUMN_SUFFIX
        layers = [base]
        if season == "winter" and terrain in _SNOW_TERRAIN:
            layers.append("snow")
        if weather == "drought" and terrain in _DROUGHT_TERRAIN:
            layers.append("drought")
        return tuple(layers)

    # -- layout -----------------------------------------------------------------
    @staticmethod
    def _window_size(view: ViewConfig) -> tuple[int, int]:
        """The usable desktop (work area minus window frame); the configured size under dummy."""
        width, height = usable_desktop(view)
        return max(SPRITE_SIZE, width), max(SPRITE_SIZE, height)

    def _choose_scale(self, width: int, height: int) -> int:
        """Largest whole scale up to max_scale with min_visible_tiles along the shorter side."""
        short = min(self._map_rect.w, self._map_rect.h)
        best = 1
        for scale in range(1, self._view.max_scale + 1):
            if short // (SPRITE_SIZE * scale) >= self._view.min_visible_tiles:
                best = scale
        return best

    def _apply_scale(self, scale: int) -> None:
        if scale == self._scale:
            return
        self._scale = scale
        self._tinted = {}
        size = SPRITE_SIZE * scale
        self._scaled = {
            key: pygame.transform.scale(sprite, (size, size))
            for key, sprite in self._sprites.items()
        }
        self._scaled_flipped = {
            key: pygame.transform.flip(sprite, True, False) for key, sprite in self._scaled.items()
        }

    def _visible_tiles(self) -> tuple[int, int]:
        return self._camera.view_counts()

    def set_map_rect(self, rect: pygame.Rect) -> None:
        """Draw the map inside ``rect`` only (the default is the whole window)."""
        self._map_rect = pygame.Rect(rect)
        self._scale = 0
        self._light_surface = pygame.Surface(self._map_rect.size)
        self._light_surface.fill(hex_to_rgba(self._assets.light.night_color)[:3])

    def _clamp_offsets(self) -> None:
        self._camera.clamp()

    def _set_display_mode(self, width: int, height: int, flags: int | None = None) -> None:
        """Make the display surface ``width`` x ``height`` (reuses it when it already matches)."""
        self._win_w, self._win_h = max(1, width), max(1, height)
        surface = pygame.display.get_surface()
        if flags is None and surface is not None and surface.get_size() == (width, height):
            self._screen = surface
        else:
            self._screen = pygame.display.set_mode(
                (self._win_w, self._win_h), pygame.RESIZABLE if flags is None else flags
            )

    def relayout(self, width: int, height: int) -> None:
        """The window changed size: rebuild the display surface, the light layer and the map."""
        self._set_display_mode(width, height)
        self.set_map_rect(pygame.Rect(0, 0, self._win_w, self._win_h))

    @staticmethod
    def _resize_of(event: pygame.event.Event) -> tuple[int, int] | None:
        """The new window size carried by a resize event, if it has one."""
        if event.type == pygame.VIDEORESIZE:
            width, height = getattr(event, "w", None), getattr(event, "h", None)
        else:
            width, height = getattr(event, "x", None), getattr(event, "y", None)
        if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
            return width, height
        surface = pygame.display.get_surface()
        return surface.get_size() if surface is not None else None

    # -- events -----------------------------------------------------------------
    def pump(self) -> bool:
        """Handle window events and arrow-key scrolling. Returns False when the user quit."""
        if self._closed:
            return False
        step = self._view.scroll_tiles
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            if event.type in (pygame.VIDEORESIZE, pygame.WINDOWSIZECHANGED):
                size = self._resize_of(event)
                if size is not None and size != (self._win_w, self._win_h):
                    self.relayout(*size)
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return False
                if event.key == pygame.K_LEFT:
                    self._offset_x -= step
                elif event.key == pygame.K_RIGHT:
                    self._offset_x += step
                elif event.key == pygame.K_UP:
                    self._offset_y -= step
                elif event.key == pygame.K_DOWN:
                    self._offset_y += step
                elif event.key in (pygame.K_PLUS, pygame.K_EQUALS, pygame.K_KP_PLUS):
                    self.speed = min(self._view.max_speed, self.speed * 2)
                elif event.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                    self.speed = max(self._view.speed / 8, self.speed / 2)
        if self._scale:
            self._clamp_offsets()
        else:
            self._offset_x = max(0, self._offset_x)
            self._offset_y = max(0, self._offset_y)
        return True

    # -- terrain cache ----------------------------------------------------------
    def _background(self) -> tuple[int, int, int]:
        if self._palette == "mono":
            return _WHITE
        return hex_to_rgba(self._assets.colors.background)[:3]

    def _draw_tile(self, surface: pygame.Surface, x: int, y: int, kind: str, frame: WorldFrame):
        px, py = x * SPRITE_SIZE, y * SPRITE_SIZE
        ground = self.ground_color(kind, frame.weather)
        surface.fill(ground if ground is not None else _WHITE, (px, py, SPRITE_SIZE, SPRITE_SIZE))
        for key in self.terrain_layers(kind, frame.season, frame.weather):
            surface.blit(self._sprites[key], (px, py))

    def _update_terrain(self, frame: WorldFrame) -> pygame.Surface:
        """The native-resolution terrain layer; only changed rows or tiles are redrawn."""
        key = (frame.season, frame.weather, self._palette, frame.width, frame.height)
        surface = self._terrain_surface
        if surface is None or key != self._terrain_key:
            surface = pygame.Surface((frame.width * SPRITE_SIZE, frame.height * SPRITE_SIZE))
            surface.fill(self._background())
            for y, row in enumerate(frame.terrain):
                for x, kind in enumerate(row):
                    self._draw_tile(surface, x, y, kind, frame)
            self._terrain_surface, self._terrain_key = surface, key
        elif frame.terrain != self._terrain_rows:
            for y, row in enumerate(frame.terrain):
                old = self._terrain_rows[y]
                if row == old:
                    continue
                for x, kind in enumerate(row):
                    if kind != old[x]:
                        self._draw_tile(surface, x, y, kind, frame)
        self._terrain_rows = frame.terrain
        return surface

    # -- people, borders, stakes ---------------------------------------------------
    @staticmethod
    def villager_sprite_key(ident: str) -> str:
        """Which of the six villager looks a villager id uses."""
        number = int(ident.rsplit("_", 1)[-1])
        return f"villager_{number % 6 + 1}"

    def _agent_sprite(self, agent: AgentView) -> pygame.Surface:
        """The scaled sprite of a player, or of a villager tinted in its player's colour."""
        if agent.kind == "player":
            return self._scaled[agent.id]
        key = self.villager_sprite_key(agent.id)
        owner = agent.owner_index
        if owner <= 0 or self._palette == "mono":
            return self._scaled[key]
        cache_key = (key, owner, self._scale, self._palette)
        tinted = self._tinted.get(cache_key)
        if tinted is None:
            colour = hex_to_rgba(self._assets.colors.players[f"player_{owner}"])
            mask = pygame.mask.from_surface(self._scaled[key])
            body = mask.to_surface(setcolor=colour, unsetcolor=(0, 0, 0, 0))
            shade = mask.to_surface(setcolor=(15, 15, 25, 255), unsetcolor=(0, 0, 0, 0))
            tinted = pygame.Surface(body.get_size(), pygame.SRCALPHA)
            grow = (
                self._scale
            )  # a dark outline one sprite pixel wide keeps villagers apart from animals
            for dx, dy in ((grow, 0), (-grow, 0), (0, grow), (0, -grow)):
                tinted.blit(shade, (dx, dy))
            tinted.blit(body, (0, 0))
            self._tinted[cache_key] = tinted
        return tinted

    def _border_tile(self, owner: int) -> pygame.Surface:
        """A border tile: in colour a tinted wash with a solid frame, in mono the pattern tile."""
        if self._palette == "mono":
            return self._scaled[f"claim_border_{owner}"]
        cache_key = ("border", owner, self._scale, self._palette)
        tile_surface = self._tinted.get(cache_key)
        if tile_surface is None:
            size = SPRITE_SIZE * self._scale
            red, green, blue, _ = hex_to_rgba(self._assets.colors.players[f"player_{owner}"])
            tile_surface = pygame.Surface((size, size), pygame.SRCALPHA)
            tile_surface.fill((red, green, blue, 70))
            frame = tile_surface.get_rect()
            pygame.draw.rect(tile_surface, (red, green, blue, 255), frame, self._scale * 2)
            self._tinted[cache_key] = tile_surface
        return tile_surface

    def _draw_claims(
        self,
        frame: WorldFrame,
        origin: tuple[int, int],
        view: tuple[int, int, int, int],
    ) -> None:
        """Border pattern on claimed tiles next to another owner or none, and boundary stakes."""
        x0, y0, x1, y1 = view
        tile = SPRITE_SIZE * self._scale
        borders = getattr(frame, "borders", ())
        stakes = getattr(frame, "stakes", ())
        for x, y, owner in borders:
            if x0 <= x < x1 and y0 <= y < y1 and 1 <= owner <= 4:
                self._screen.blit(
                    self._border_tile(owner), (origin[0] + x * tile, origin[1] + y * tile)
                )
        for x, y, _owner in stakes:
            if x0 <= x < x1 and y0 <= y < y1:
                self._screen.blit(
                    self._scaled["boundary_stake"], (origin[0] + x * tile, origin[1] + y * tile)
                )

    def _draw_people(
        self,
        frame: WorldFrame,
        sub_tick: float,
        origin: tuple[int, int],
        view: tuple[int, int, int, int],
    ) -> None:
        """Players and villagers sliding between tiles, with sick / injured / sleeping marks."""
        scale = self._scale
        tile = SPRITE_SIZE * scale
        rect = self._map_rect
        agents = (*getattr(frame, "villagers", ()), *getattr(frame, "players", ()))
        for agent in agents:
            mx, my = slide_position(agent, frame.tick, sub_tick, scale)
            sx, sy = origin[0] + mx, origin[1] + my
            if sx <= rect.x - tile or sy <= rect.y - tile or sx >= rect.right or sy >= rect.bottom:
                continue
            sprite = self._agent_sprite(agent)
            if agent.facing < 0:
                sprite = pygame.transform.flip(sprite, True, False)
            self._screen.blit(sprite, (sx, sy))
            for marker in agent.markers:
                self._screen.blit(self._scaled[f"marker_{marker}"], (sx, sy - tile // 2))

    # -- buildings and graves -------------------------------------------------------
    def _draw_structures(
        self, frame: WorldFrame, origin: tuple[int, int], view: tuple[int, int, int, int]
    ) -> None:
        """Buildings: finished ones draw their sprite_key; sites are faint with a progress bar."""
        x0, y0, x1, y1 = view
        scale = self._scale
        tile = SPRITE_SIZE * scale
        for st in getattr(frame, "structures", ()):
            if not (x0 <= st.x < x1 and y0 <= st.y < y1):
                continue
            pos = (origin[0] + st.x * tile, origin[1] + st.y * tile)
            if st.complete:
                self._screen.blit(self._scaled[st.sprite_key], pos)
                continue
            ghost = self._tinted.get(("site", st.kind, scale, self._palette))
            if ghost is None:
                ghost = self._scaled[st.kind].copy()
                ghost.set_alpha(110)
                self._tinted[("site", st.kind, scale, self._palette)] = ghost
            self._screen.blit(ghost, pos)
            bar_h = max(2, scale * 2)
            back = pygame.Rect(pos[0], pos[1] + tile - bar_h, tile, bar_h)
            pygame.draw.rect(self._screen, (30, 30, 40), back)
            done = max(0, min(tile, round(tile * st.progress)))
            pygame.draw.rect(self._screen, (240, 200, 60), (back.x, back.y, done, bar_h))

    def _draw_graves(self, origin: tuple[int, int], view: tuple[int, int, int, int]) -> None:
        x0, y0, x1, y1 = view
        tile = SPRITE_SIZE * self._scale
        for gx, gy in self._graves:
            if x0 <= gx < x1 and y0 <= gy < y1:
                self._screen.blit(
                    self._scaled["marker_grave"], (origin[0] + gx * tile, origin[1] + gy * tile)
                )

    # -- drawing ----------------------------------------------------------------
    def _draw_map(self, frame: WorldFrame, sub_tick: float) -> None:
        """Draw the world into the map rectangle (clipped); no caption, no flip."""
        self._map_w, self._map_h = frame.width, frame.height
        self._apply_scale(self._choose_scale(frame.width, frame.height))
        self._clamp_offsets()

        scale = self._scale
        tile = SPRITE_SIZE * scale
        rect = self._map_rect
        vis_w, vis_h = self._visible_tiles()
        x0, y0 = self._offset_x, self._offset_y
        x1, y1 = min(frame.width, x0 + vis_w), min(frame.height, y0 + vis_h)
        # The camera centres a map smaller than the map rectangle.
        origin_x, origin_y = self._camera.origin()
        pad_x = origin_x + x0 * tile
        pad_y = origin_y + y0 * tile

        screen = self._screen
        screen.set_clip(rect)
        screen.fill(self._background(), rect)

        terrain = self._update_terrain(frame)
        crop = terrain.subsurface(
            pygame.Rect(
                x0 * SPRITE_SIZE, y0 * SPRITE_SIZE, (x1 - x0) * SPRITE_SIZE, (y1 - y0) * SPRITE_SIZE
            )
        )
        screen.blit(
            pygame.transform.scale(crop, ((x1 - x0) * tile, (y1 - y0) * tile)), (pad_x, pad_y)
        )

        self._draw_claims(frame, (origin_x, origin_y), (x0, y0, x1, y1))
        sprites = self._scaled
        flipped = self._scaled_flipped
        for group in (frame.plants, frame.animals, frame.dogs):
            for entity in group:
                mx, my = slide_position(entity, frame.tick, sub_tick, scale)
                sx, sy = origin_x + mx, origin_y + my
                if (
                    sx <= rect.x - tile
                    or sy <= rect.y - tile
                    or sx >= rect.right
                    or sy >= rect.bottom
                ):
                    continue
                source = flipped if entity.facing < 0 else sprites
                screen.blit(source[entity.kind], (sx, sy))
        for landmark in frame.landmarks:
            if x0 <= landmark.x < x1 and y0 <= landmark.y < y1:
                screen.blit(
                    sprites[landmark.kind],
                    (origin_x + landmark.x * tile, origin_y + landmark.y * tile),
                )
        self._draw_structures(frame, (origin_x, origin_y), (x0, y0, x1, y1))
        self._draw_graves((origin_x, origin_y), (x0, y0, x1, y1))
        self._draw_people(frame, sub_tick, (origin_x, origin_y), (x0, y0, x1, y1))

        if frame.weather in ("rain", "storm"):
            key = "overlay_rain" if frame.weather == "rain" else "overlay_storm"
            every = 4 if frame.weather == "rain" else 3
            for y in range(y0, y1):
                for x in range(x0, x1):
                    if (x * 3 + y * 5) % every == 0:
                        screen.blit(sprites[key], (origin_x + x * tile, origin_y + y * tile))

        alpha = light_alpha(frame.daylight, frame.weather, self._assets.light)
        if alpha:
            self._light_surface.set_alpha(alpha)
            screen.blit(self._light_surface, rect.topleft)
        screen.set_clip(None)

    def draw(self, frame: WorldFrame, sub_tick: float = 0.0) -> None:
        """Draw one frame; ``sub_tick`` (0 to 1) is how far the clock is into the current minute."""
        self._draw_map(frame, sub_tick)
        self._draw_times.append(time.perf_counter())
        pygame.display.set_caption(
            f"AI Island - Year {frame.year}, {frame.season.capitalize()}, week {frame.week}, "
            f"day {frame.day}, {frame.hour:02d}:{frame.minute:02d} - speed x{self.speed:g} "
            f"- {self.fps:.0f} fps"
        )
        pygame.display.flip()

    def save_png(self, path: Path) -> None:
        """Save the current window contents as a PNG (creates the parent folder)."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        pygame.image.save(self._screen, str(path))

    def close(self) -> None:
        """Close the window. Safe to call twice."""
        if self._closed:
            return
        self._closed = True
        pygame.quit()
