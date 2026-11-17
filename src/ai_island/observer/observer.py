"""The full observer window: top bar, map, and five text tabs. It only reads and never steps."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pygame
import pygame_gui
from pygame_gui.core import UIElement

from ai_island.measure.decisions import action_words, label_words
from ai_island.measure.history import FLASH_KINDS, HISTORY_TYPES, history_entries
from ai_island.minds.values import VALUE_IDS, core_ids
from ai_island.observer.bubbles import place_bubble
from ai_island.observer.chats import (
    FILTER_KINDS,
    NO_SELECTION_TEXT,
    guide_lines,
    row_matches,
    village_ids,
)
from ai_island.observer.code_art import hex_to_rgba
from ai_island.observer.flashes import Flash, blink_on
from ai_island.observer.graphs import GraphData, GraphStore, render_graph
from ai_island.observer.inspector import DEFAULT_SECTIONS, Section, agent_of, collect_rows
from ai_island.observer.judgeview import history_rows_for_day, judge_words, profile_lines
from ai_island.observer.keys import (
    KEY_CODES,
    REPEATING_KEYS,
    help_lines,
    key_bindings,
)
from ai_island.observer.layout import Layout, compute_layout, view_option
from ai_island.observer.minimap import (
    base_surface,
    draw_border,
    draw_frame_box,
    pixel_to_tile,
    tile_to_pixel,
)
from ai_island.observer.prefs import (
    BUBBLE_MODES,
    DISPLAY_SIZES,
    UI_CHOICES,
    load_prefs,
    save_prefs,
)
from ai_island.observer.viewer import Viewer
from ai_island.observer.window import desktop_size, preset_size

if TYPE_CHECKING:
    from ai_island.config import AssetsConfig, ViewConfig
    from ai_island.storage.db import RunDB
    from ai_island.storage.run_control import Controls
    from ai_island.world.view import WorldFrame

TAB_NAMES = ("Chats", "Choice points", "World history", "Players", "Spend")
_TAB_KEYS = {
    "Chats": "tab_chats",
    "Choice points": "tab_choice_points",
    "World history": "tab_world_history",
    "Players": "tab_players",
    "Spend": "tab_spend",
}
_PANEL_KEYS = (*_TAB_KEYS.values(), "page_older", "page_label", "page_newer", "text_box")
_CHAT_KEYS = ("guide_toggle", "chat_filter", "chat_guide")
_LINK_ID = re.compile(r"^[A-Za-z0-9_]+$")
_BUBBLE_BG = (246, 242, 226)
_BUBBLE_EDGE = (30, 30, 40)
_INSPECT_LABEL = (150, 160, 175)
_INSPECT_VALUE = (232, 232, 220)
_GUIDE_ROWS = 6
_PAGED = ("Chats", "Choice points", "World history")
_DEFAULT_FONT = "assets/fonts/monogram/monogram/ttf/monogram.ttf"
_GRAVE_TYPES = ("died", "villager_died")
_PANEL_BG = (28, 32, 40)
_BAR_BG = (20, 24, 30)
_HELP_BG = (10, 12, 18, 232)
_HELP_FG = (232, 232, 220)
_MAX_DT = 0.1
WAITING_TEXT = "Waiting for replies..."
_MINUTES_PER_DAY = 1440
_TICKS_PER_WEEK = 7 * _MINUTES_PER_DAY
_SIZE_LABELS = {
    "fit": "Fit screen",
    "1280x800": "1280x800",
    "1600x1000": "1600x1000",
    "1920x1080": "1920x1080",
    "fullscreen": "Full screen",
}
# Top bar elements left to right: (key, kind, width in pixels at ui scale 1, first text).
# The last one takes whatever width is left. Widths shrink together when the window is narrow.
_BAR_SPEC = (
    ("top_clock", "label", 52, "00:00"),
    ("top_day_season", "label", 210, ""),
    ("top_pause", "button", 60, "Pause"),
    ("top_speed_down", "button", 28, "-"),
    ("top_speed_label", "label", 48, "x1"),
    ("top_speed_up", "button", 28, "+"),
    ("top_spend_warning", "label", 160, "Spend OK"),
    ("top_panel", "button", 56, "Panel"),
    ("display_size", "menu", 96, ""),
    ("display_ui_scale", "menu", 104, ""),
    ("top_status", "label", 230, ""),
    ("top_autosave", "label", 0, "Not saved yet"),
)


def _value_order(value_id: str) -> int:
    """Library position of a value (invented values come after, in creation order)."""
    return VALUE_IDS.index(value_id) if value_id in VALUE_IDS else len(VALUE_IDS)


def when(tick: int) -> str:
    """``D<day> <HH:MM>`` for a game minute: tick 3255 is ``D3 06:15``."""
    day, minute_of_day = divmod(tick, _MINUTES_PER_DAY)
    hour, minute = divmod(minute_of_day, 60)
    return f"D{day + 1} {hour:02d}:{minute:02d}"


def escape_rich(text: str) -> str:
    """Make text safe for pygame_gui rich text: escape & < > and turn newlines into <br>."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return text.replace("\r", "").replace("\n", "<br>")


class Observer(Viewer):
    """Viewer plus the pygame_gui screen. Writes nothing except through ``controls``."""

    def __init__(
        self,
        assets: AssetsConfig,
        view: ViewConfig,
        root: Path,
        db: RunDB | None = None,
        controls: Controls | None = None,
        *,
        spend_warning_share: float = 0.8,
        week_ticks: int = _TICKS_PER_WEEK,
        run_name: str | None = None,
        prefs_path: Path | None = None,
        screenshot_dir: Path | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        font_rel = Path(view.font_path)
        font = font_rel if font_rel.is_absolute() else Path(root) / font_rel
        if not font.is_file():
            raise FileNotFoundError(f"observer font not found: {font}")
        self._font_path = font
        super().__init__(assets, view, root)
        self._db = db
        self._controls = controls
        self._share = spend_warning_share
        self._week_ticks = week_ticks
        self._run_name = run_name
        self._prefs_path = Path(prefs_path) if prefs_path is not None else None
        self._screenshot_dir = Path(screenshot_dir) if screenshot_dir is not None else None
        self._clock = clock
        self._page_size = int(view.page_size)

        # Settings: run.toml defaults, overridden by whatever valid values the prefs file holds.
        prefs = load_prefs(self._prefs_path)
        self._display_size: str = prefs.get(
            "display_size", view_option(view, "display_size", "fit")
        )
        self._ui_choice: int = prefs.get("ui_scale", view_option(view, "ui_scale", 0))
        self._panel_visible: bool = prefs.get(
            "panel_visible", view_option(view, "panel_visible", True)
        )
        self._bubble_mode: str = prefs.get("bubbles", view_option(view, "bubbles", "all"))
        self._minimap_visible: bool = prefs.get(
            "minimap_visible", view_option(view, "minimap_visible", True)
        )
        self._fullscreen = False
        self._windowed_size = (self._win_w, self._win_h)
        self._help_visible = False
        self._status_text = ""
        self._status_until = 0.0
        self._held: set[int] = set()
        self._last_frame: WorldFrame | None = None
        self._key_names = self._build_key_map()
        self._key_handlers: dict[str, Callable[[], None]] = {
            "P": self._key_pause,
            "+": lambda: self._change_speed(2.0),
            "-": lambda: self._change_speed(0.5),
            "Left": lambda: self._scroll(-1, 0),
            "Right": lambda: self._scroll(1, 0),
            "Up": lambda: self._scroll(0, -1),
            "Down": lambda: self._scroll(0, 1),
            "Tab": self.toggle_panel,
            "B": self.cycle_bubbles,
            "M": self.toggle_minimap,
            "J": self._key_jump,
            "H": self.toggle_help,
            "F11": self.toggle_fullscreen,
            "F12": self._key_screenshot,
        }
        missing = [b.name for b in key_bindings() if b.name not in self._key_handlers | {"Esc": 0}]
        if missing:
            raise RuntimeError(f"keys without a handler: {missing}")

        self._elements: dict[str, UIElement] = {}
        self._active = TAB_NAMES[0]
        self._pages: dict[str, int] = {name: 0 for name in TAB_NAMES}
        self._chats: list[Any] = []
        self._chat_cursor = 0
        self._choices: list[Any] = []
        self._labels_version: tuple[int, int] | None = None
        self._history: list[Any] = []
        self._history_cursor = 0
        self._summaries_version = -1
        self._summary_days: set[int] = set()
        self._profiles: dict[str, Any] = {}
        self._grave_cursor = 0
        self._grave_at: dict[int, tuple[int, int]] = {}
        self._names: dict[str, str] = {}
        self._players_text = ""
        self._values: dict[str, tuple[tuple[str, float], ...] | None] = {}
        self._values_version = -1
        self._details: dict[int, Any] = {}
        self._waiting = False
        self._quit_seen = False
        self._spend_text = ""
        self._rendered: tuple[str, str] | None = None
        self._last_draw = time.perf_counter()
        self._fit_cache: dict[tuple[str, int, str], str] = {}
        self._selected: str | None = None
        self._following = False
        self.inspector_sections: list[Section] = list(DEFAULT_SECTIONS)
        self._chat_filter: tuple[str, str | None] = ("all", None)
        self._chat_cache: tuple[tuple[Any, ...], list[Any]] | None = None
        self._guide_collapsed = False
        self._guide_rendered: str | None = None
        self._colour_hex: dict[str, str] = {}
        self._guide_sig: tuple[Any, ...] = ()
        self._agent_rects: dict[str, pygame.Rect] = {}
        self._bubbles: list[tuple[str, pygame.Rect, str]] = []
        self._hit_order: list[str] = []
        self._last_sub = 0.0
        self._filter_choices: dict[str, tuple[str, str | None]] = {}
        self._flashes: list[Flash] = []
        self._latest_flash: tuple[int, int, Flash] | None = None
        self._flash_loaded = False
        self._structures: dict[int, tuple[int, int, str]] = {}
        self._graphs = GraphStore()
        self._graph_cache: dict[str, tuple[Any, pygame.Surface]] = {}
        self._graph_rects: dict[str, pygame.Rect] = {}
        self._graph_space = 0
        self._players_n = 4
        self._mini_cache: tuple[Any, pygame.Surface] | None = None
        self._mini_stamp = -1e9
        self._mini_dots: list[tuple[str, int, int, tuple[int, int, int]]] = []
        self._layout: Layout = compute_layout(
            self._win_w, self._win_h, self._ui_choice, self._panel_visible, False, view
        )
        self._apply_start_display()
        self._rebuild()

    # -- window, layout and theme ----------------------------------------------------
    def _build_key_map(self) -> dict[int, str]:
        mapping: dict[int, str] = {}
        for binding in key_bindings():
            for const in KEY_CODES[binding.name]:
                mapping[getattr(pygame, const)] = binding.name
        return mapping

    def _apply_start_display(self) -> None:
        """Open at the saved or configured display size ("fit" is what the Viewer already made)."""
        if self._display_size == "fullscreen":
            self._enter_fullscreen()
        elif self._display_size != "fit":
            width, height = preset_size(self._display_size, self._view, DISPLAY_SIZES)
            self._set_display_mode(width, height)
            self._windowed_size = (self._win_w, self._win_h)

    def _enter_fullscreen(self) -> None:
        if not self._fullscreen:
            self._windowed_size = (self._win_w, self._win_h)
        width, height = desktop_size(self._view)
        self._set_display_mode(width, height, pygame.FULLSCREEN)
        self._fullscreen = True

    def _leave_fullscreen(self) -> None:
        self._fullscreen = False
        width, height = self._windowed_size
        self._set_display_mode(width, height, pygame.RESIZABLE)

    def _make_manager(self) -> pygame_gui.UIManager:
        manager = pygame_gui.UIManager((self._win_w, self._win_h))
        path = str(self._font_path)
        manager.add_font_paths("monogram", path, path, path, path)
        font = {"name": "monogram", "size": str(self._font_px)}
        theme: dict[str, Any] = {"defaults": {"font": font}}
        for key in ("button", "label", "text_box", "drop_down_menu"):
            theme[key] = {"font": font}
        theme["label"]["misc"] = {"text_horiz_alignment": "left"}
        theme["text_box"]["misc"] = {"line_spacing": "1.0"}
        manager.get_theme().update_theming(json.dumps(theme))
        return manager

    def _rebuild(self) -> None:
        """Recompute the layout and rebuild every pygame_gui element in one go."""
        layout = compute_layout(
            self._win_w,
            self._win_h,
            self._ui_choice,
            self._panel_visible,
            self._minimap_visible,
            self._view,
        )
        self._layout = layout
        self._ui = layout.ui_scale
        self._font_px = self._view.font_size * self._ui
        self._bar_h = layout.top_bar.h
        self._top_bar_rect = layout.top_bar.copy()
        self._panel_rect = layout.panel.copy()
        self._ui_map_rect = layout.map.copy()
        self.set_map_rect(layout.map)
        self._font = pygame.font.Font(str(self._font_path), self._font_px)
        self._fit_cache = {}
        for element in self._elements.values():
            element.kill()
        self._elements = {}
        self._manager = self._make_manager()
        self._build_ui()
        self._rendered = None
        self._guide_rendered = None

    def relayout(self, width: int, height: int) -> None:
        """The window changed size: one transaction that rebuilds everything from the new size."""
        flags = pygame.FULLSCREEN if self._fullscreen else None
        self._set_display_mode(width, height, flags)
        if not self._fullscreen:
            self._windowed_size = (self._win_w, self._win_h)
        self._rebuild()

    def _bar_widths(self) -> list[int]:
        """Pixel width of each top bar element; they shrink together so nothing overflows."""
        ui = self._ui
        pad = 4 * ui
        count = len(_BAR_SPEC)
        avail = self._top_bar_rect.w - pad * (count + 1)
        wanted = [w * ui for _k, _t, w, _x in _BAR_SPEC]
        flexible = 120 * ui
        wanted[-1] = max(wanted[-1], flexible)
        fixed = sum(wanted[:-1])
        if fixed + flexible <= avail:
            wanted[-1] = avail - fixed
            return wanted
        factor = max(0.05, avail / (fixed + flexible))
        shrunk = [max(2, int(w * factor)) for w in wanted[:-1]]
        shrunk.append(max(2, avail - sum(shrunk)))
        return shrunk

    def _display_options(self) -> tuple[list[str], str, list[str], str]:
        """Labels for the two Display dropdowns and the label that is currently chosen."""
        sizes = [_SIZE_LABELS[s] for s in DISPLAY_SIZES]
        shown = "fullscreen" if self._fullscreen else self._display_size
        eff = self._ui
        scales: list[str] = []
        for choice in UI_CHOICES:
            label = "Auto" if choice == 0 else str(choice)
            if choice == self._ui_choice:
                if choice == 0:
                    label = f"Auto ({eff})"
                elif eff != choice:
                    label = f"{choice} (using {eff})"
            scales.append(label)
        return sizes, _SIZE_LABELS[shown], scales, scales[UI_CHOICES.index(self._ui_choice)]

    def _build_ui(self) -> None:
        ui, mgr = self._ui, self._manager
        pad = 4 * ui
        bar = self._top_bar_rect
        height = max(1, bar.h - 2 * pad)
        widths = self._bar_widths()
        sizes, size_now, scales, scale_now = self._display_options()
        x = pad
        for (key, kind, _w, text), width in zip(_BAR_SPEC, widths, strict=True):
            rect = pygame.Rect(x, pad, width, height)
            element: UIElement
            if kind == "menu":
                options, start = (sizes, size_now) if key == "display_size" else (scales, scale_now)
                element = pygame_gui.elements.UIDropDownMenu(options, start, rect, mgr)
            elif kind == "button":
                element = pygame_gui.elements.UIButton(rect, self._fit(width, text), mgr)
            else:
                element = pygame_gui.elements.UILabel(rect, self._fit(width, text), mgr)
            self._elements[key] = element
            x += width + pad

        # The panel is laid out where it would be when shown, then hidden if it is not.
        shown = compute_layout(
            self._win_w, self._win_h, self._ui_choice, True, self._minimap_visible, self._view
        ).panel
        row_h = 28 * ui
        tab_w = max(1, (shown.w - 2 * pad) // 3)
        for i, name in enumerate(TAB_NAMES):
            row, col = divmod(i, 3)
            rect = pygame.Rect(
                shown.x + pad + col * tab_w, shown.y + pad + row * row_h, tab_w, row_h
            )
            self._elements[_TAB_KEYS[name]] = pygame_gui.elements.UIButton(rect, name, mgr)
        foot_y = shown.bottom - pad - row_h
        third = max(1, (shown.w - 2 * pad) // 3)
        self._elements["page_older"] = pygame_gui.elements.UIButton(
            pygame.Rect(shown.x + pad, foot_y, third, row_h), "Older", mgr
        )
        self._elements["page_label"] = pygame_gui.elements.UILabel(
            pygame.Rect(shown.x + pad + third, foot_y, third, row_h), "", mgr
        )
        self._elements["page_newer"] = pygame_gui.elements.UIButton(
            pygame.Rect(shown.x + pad + 2 * third, foot_y, third, row_h), "Newer", mgr
        )
        rects = self._content_rects()
        self._elements["guide_toggle"] = pygame_gui.elements.UIButton(
            rects["guide_toggle"], self._fit(rects["guide_toggle"].w, "Village guide"), mgr
        )
        labels, current = self._filter_options()
        self._elements["chat_filter"] = pygame_gui.elements.UIDropDownMenu(
            labels, current, rects["chat_filter"], mgr
        )
        self._elements["chat_guide"] = pygame_gui.elements.UITextBox("", rects["chat_guide"], mgr)
        self._box = pygame_gui.elements.UITextBox("", rects["text_box"], mgr)
        self._elements["text_box"] = self._box
        self._elements[_TAB_KEYS[self._active]].select()  # type: ignore[attr-defined]
        self._sync_visibility()

    def _content_rects(self) -> dict[str, pygame.Rect]:
        """Rectangles of the Chats extras and the text box inside the panel, as they are now."""
        ui = self._ui
        pad = 4 * ui
        row_h = 28 * ui
        shown = compute_layout(
            self._win_w, self._win_h, self._ui_choice, True, self._minimap_visible, self._view
        )
        panel = shown.panel
        if self._selected is not None and shown.inspector.h > 0:
            y = shown.inspector.bottom + pad + self._inspector_graph_space()
        else:
            y = panel.y + pad + 2 * row_h + pad
        foot_y = panel.bottom - pad - row_h
        width = max(1, panel.w - 2 * pad)
        toggle_w = max(1, width * 2 // 5)
        rects = {
            "guide_toggle": pygame.Rect(panel.x + pad, y, toggle_w, row_h),
            "chat_filter": pygame.Rect(
                panel.x + pad + toggle_w + pad, y, max(1, width - toggle_w - pad), row_h
            ),
        }
        chats = self._active == "Chats"
        if chats:
            y += row_h + pad
        guide_h = (self._guide_row_count(width - 6 * pad) + 1) * self._font.get_linesize() + 2 * pad
        guide_h = min(guide_h, max(row_h, (panel.h - 6 * row_h) // 2))
        rects["chat_guide"] = pygame.Rect(panel.x + pad, y, width, guide_h)
        if chats and not self._guide_collapsed:
            y += guide_h + pad
        bottom = foot_y - pad
        self._graph_rects = {}
        if self._active == "Players" and self._players_n > 0:
            _graph_w, graph_h = self._graph_size()
            line = self._font.get_linesize()
            min_text = 8 * line
            fit = max(0, (bottom - y - min_text) // (graph_h + pad))
            if fit < self._players_n:
                # shrink the blocks (down to a readable minimum) so that none is hidden
                small = (bottom - y - 4 * line) // self._players_n - pad
                if small >= 32 * ui:
                    graph_h = min(graph_h, small)
                    fit = self._players_n
            count = min(self._players_n, fit)
            graph_w = width
            top = bottom - count * (graph_h + pad)
            panels = self._last_frame.panels if self._last_frame is not None else ()
            for i in range(count):
                ident = panels[i].id if i < len(panels) else f"player_{i + 1}"
                self._graph_rects[ident] = pygame.Rect(
                    panel.x + pad, top + i * (graph_h + pad) + pad, min(graph_w, width), graph_h
                )
            bottom = top
        rects["text_box"] = pygame.Rect(panel.x + pad, y, width, max(1, bottom - y))
        return rects

    def _graph_size(self) -> tuple[int, int]:
        """Graph block size: the full panel content width (graph_width is the chart floor)."""
        ui = self._ui
        panel = self._layout.panel
        per_chart = int(view_option(self._view, "graph_width", 220)) * ui // 3
        return (
            max(panel.w - 8 * ui, 3 * per_chart if panel.w <= 0 else 1),
            int(view_option(self._view, "graph_height", 60)) * ui,
        )

    def _is_player(self, ident: str | None) -> bool:
        frame = self._last_frame
        return ident is not None and frame is not None and any(p.id == ident for p in frame.panels)

    def _inspector_graph_space(self) -> int:
        """Pixels reserved under the Inspector rows for the selected player's graphs."""
        if not self._is_player(self._selected):
            return 0
        return self._graph_size()[1] + 4 * self._ui

    def graph_rect(self, player_id: str) -> pygame.Rect | None:
        """Screen rectangle where a player's graphs were laid out (Players tab or Inspector)."""
        if not self._panel_visible:
            return None
        if self._active == "Players" and player_id in self._graph_rects:
            return self._graph_rects[player_id].copy()
        if player_id == self._selected:
            return self._inspector_graph_rect()
        return None

    def _inspector_graph_rect(self) -> pygame.Rect | None:
        if self._inspector_graph_space() <= 0:
            return None
        ins = self._layout.inspector
        width, height = self._graph_size()
        return pygame.Rect(
            ins.x + 4 * self._ui, ins.bottom + 2 * self._ui, min(width, ins.w), height
        )

    def _draw_graphs(self) -> None:
        """Blit each player's graph surface (cached until new points arrive or the size changes)."""
        if not self._panel_visible or self._last_frame is None:
            return
        targets: list[tuple[str, pygame.Rect]] = []
        if self._active == "Players":
            targets.extend(self._graph_rects.items())
        if self._selected is not None and self._is_player(self._selected):
            rect = self._inspector_graph_rect()
            if rect is not None:
                targets.append((self._selected, rect))
        for ident, rect in targets:
            sig = (self._graphs.version, rect.size, self._ui)
            cached = self._graph_cache.get(ident)
            if cached is None or cached[0] != sig:
                data = self._graphs.data(ident)
                others = {
                    p.id: self._rgb_of(p.id) for p in self._last_frame.panels if p.id != ident
                }
                surface = render_graph(
                    self._font,
                    rect.size,
                    data,
                    self._rgb_of(ident),
                    others,
                    self._ui,
                    {p.id: p.name for p in self._last_frame.panels},
                )
                cached = (sig, surface)
                self._graph_cache[ident] = cached
            self._screen.blit(cached[1], rect.topleft)

    def _sync_visibility(self) -> None:
        """Show or hide panel parts for the panel switch, the active tab and the guide fold."""
        elements = self._elements
        panel_on = self._panel_visible
        chats = panel_on and self._active == "Chats"
        for keys, on in ((_PANEL_KEYS, panel_on), (_CHAT_KEYS, chats)):
            for key in keys:
                if on:
                    elements[key].show()
                else:
                    elements[key].hide()
        if chats and self._guide_collapsed:
            elements["chat_guide"].hide()
        rects = self._content_rects()
        box = self._box
        if box.rect != rects["text_box"]:
            box.set_dimensions(rects["text_box"].size)
            box.set_relative_position(rects["text_box"].topleft)
            self._rendered = None
        guide = elements["chat_guide"]
        if guide.rect != rects["chat_guide"]:
            guide.set_dimensions(rects["chat_guide"].size)
            guide.set_relative_position(rects["chat_guide"].topleft)

    def _filter_label(self, kind: str, ident: str | None) -> str:
        if kind == "all":
            return "All chats"
        if kind == "heard":
            return "Heard by selected"
        if kind == "village":
            frame = self._last_frame
            if frame is not None:
                for entry in frame.village_guide:
                    if entry.leader_id == ident:
                        return f"Village: {entry.leader_name}"
            return "Village: Wanderers" if not ident else f"Village: {self._name(ident)}"
        return f"Person: {self._name(ident or '')}"

    def _filter_options(self) -> tuple[list[str], str]:
        """Labels of the chat filter dropdown, and the one that is chosen now."""
        choices: dict[str, tuple[str, str | None]] = {"All chats": ("all", None)}
        frame = self._last_frame
        if frame is not None:
            for entry in frame.village_guide:
                choices[f"Village: {entry.leader_name}"] = ("village", entry.leader_id)
            for panel in frame.panels:
                choices[f"Person: {panel.name}"] = ("person", panel.id)
        choices["Selected person"] = ("person", None)
        choices["Heard by selected"] = ("heard", None)
        current = self._filter_label(*self._chat_filter)
        choices.setdefault(current, self._chat_filter)
        self._filter_choices = choices
        return list(choices), current

    def _fit(self, width: int, text: str) -> str:
        """``text`` cut with ".." so it fits inside an element ``width`` pixels wide."""
        limit = width - 6 * self._ui
        if not text or self._font.size(text)[0] <= limit:
            return text
        cache_key = (text, limit, "")
        cached = self._fit_cache.get(cache_key)
        if cached is not None:
            return cached
        cut = text
        while cut and self._font.size(cut.rstrip() + "..")[0] > limit:
            cut = cut[:-1]
        result = cut.rstrip() + ".." if cut else ""
        self._fit_cache[cache_key] = result
        return result

    # -- accessors -----------------------------------------------------------------------
    @property
    def tab_names(self) -> tuple[str, ...]:
        return TAB_NAMES

    @property
    def elements(self) -> dict[str, UIElement]:
        return self._elements

    @property
    def font_path(self) -> Path:
        return self._font_path

    @property
    def active_tab(self) -> str:
        return self._active

    @property
    def map_rect(self) -> pygame.Rect:
        return self._ui_map_rect.copy()

    @property
    def panel_rect(self) -> pygame.Rect:
        return self._panel_rect.copy()

    @property
    def top_bar_rect(self) -> pygame.Rect:
        return self._top_bar_rect.copy()

    @property
    def ui_scale(self) -> int:
        return self._ui

    @property
    def layout(self) -> Layout:
        return self._layout

    @property
    def minimap_rect(self) -> pygame.Rect:
        return self._layout.minimap.copy()

    @property
    def panel_visible(self) -> bool:
        return self._panel_visible

    @property
    def minimap_visible(self) -> bool:
        return self._minimap_visible

    @property
    def bubble_mode(self) -> str:
        return self._bubble_mode

    @property
    def help_visible(self) -> bool:
        return self._help_visible

    @property
    def fullscreen(self) -> bool:
        return self._fullscreen

    @property
    def display_size(self) -> str:
        return self._display_size

    @property
    def ui_choice(self) -> int:
        return self._ui_choice

    @property
    def prefs_path(self) -> Path | None:
        return self._prefs_path

    @property
    def status_text(self) -> str:
        return self._status_text if self._clock() < self._status_until else ""

    def help_text(self) -> str:
        """One line per key, button and mouse action: ``"<name>: <action>"``."""
        return "\n".join(help_lines())

    def _check_tab(self, name: str) -> None:
        if name not in TAB_NAMES:
            raise KeyError(f"unknown tab {name!r}; choose one of {TAB_NAMES}")

    def select_tab(self, name: str) -> None:
        self._check_tab(name)
        if name == self._active:
            return
        self._elements[_TAB_KEYS[self._active]].unselect()  # type: ignore[attr-defined]
        before = self._active
        self._active = name
        self._rendered = None
        if {before, name} & {"Chats", "Players"}:
            self._rebuild()  # the Chats extras and the Players graphs change the panel layout
            return
        self._elements[_TAB_KEYS[name]].select()  # type: ignore[attr-defined]
        self._sync_visibility()

    def _row_count(self, name: str) -> int:
        if name == "Chats":
            return len(self._chat_rows())
        if name == "Choice points":
            return len(self._choices)
        if name == "World history":
            return len(self._history)
        return 0

    def page_count(self, name: str) -> int:
        self._check_tab(name)
        if name not in _PAGED:
            return 1
        return max(1, -(-self._row_count(name) // self._page_size))

    def show_page(self, name: str, index: int) -> None:
        self._check_tab(name)
        index = max(0, min(index, self.page_count(name) - 1))
        if index != self._pages[name]:
            self._pages[name] = index
            self._rendered = None

    # -- tab text ------------------------------------------------------------------------
    def _name(self, ident: str) -> str:
        return self._names.get(ident, ident)

    def _names_of(self, idents: Any) -> str:
        return ", ".join(self._name(i) for i in idents)

    def _chat_line(self, row: Any) -> str:
        who = self._name(row.speaker)
        if row.targets:
            who += " -> " + self._names_of(row.targets)
        heard = self._names_of(row.hearers) if row.hearers else "nobody"
        text = str(row.text).replace("\r", " ").replace("\n", " ")
        return f"{when(row.tick)} {who}: {text} | heard: {heard}"

    def _choice_line(self, row: Any) -> str:
        judge = judge_words(row.judge_label_json, getattr(row, "judge_detail", None))
        line = (
            f"{when(row.tick)} {self._name(row.player_id)} [{row.tier}] {row.situation}"
            f" | {self._action_text(row)} | {self._label_text(row)}"
            f" | feeling: {getattr(row, 'feeling', '?')} | {judge}"
            f"{self._detail_text(row)}"
        )
        return line.replace("\r", " ").replace("\n", " ")

    @staticmethod
    def _loaded(text: Any) -> dict[str, Any]:
        try:
            value = json.loads(text) if text else {}
        except (ValueError, TypeError):
            return {}
        return value if isinstance(value, dict) else {}

    def _action_text(self, row: Any) -> str:
        raw = self._loaded(row.action_json)
        return action_words(raw, self._names) if raw else str(row.action_json)

    def _label_text(self, row: Any) -> str:
        d = self._details.get(row.id)
        label = self._loaded(row.self_label_json)
        if not label and d is not None and isinstance(d.self_label, dict):
            label = d.self_label
        return label_words(label) if label else "no self-label"

    @staticmethod
    def _load_details(db: Any) -> dict[int, Any]:
        """The AI details of every choice point by id ({} when the database has none)."""
        loader = getattr(db, "choice_details", None)
        if loader is None:
            return {}
        try:
            return {d.id: d for d in loader()}
        except (ValueError, TypeError, KeyError):
            return {}

    def _detail_text(self, row: Any) -> str:
        """Self-label words and the advisor's part for a choice point, '' when unknown."""
        d = self._details.get(row.id)
        if d is None:
            return ""
        if d.advisor_followed is None:
            return ""
        return " | advisor followed: " + ("yes" if d.advisor_followed else "no")

    def _history_line(self, row: Any) -> str:
        return f"{when(row.tick)} {row.kind}: {row.text}"

    def tab_text(self, name: str) -> str:
        """Plain text of the page shown for ``name`` (not escaped)."""
        self._check_tab(name)
        if name == "Players":
            return self._players_text
        if name == "Spend":
            return self._spend_text
        if name == "Chats":
            if self._chat_filter[0] == "heard" and self._selected is None:
                return NO_SELECTION_TEXT
            fmt = self._chat_line
        elif name == "Choice points":
            if not self._choices:
                return "No choice points yet."
            fmt = self._choice_line
        else:
            fmt = self._history_line
        return "\n".join(fmt(row) for row in self._page_rows(name))

    def _page_rows(self, name: str) -> list[Any]:
        """The rows of the page shown for a paged tab (after the chat filter)."""
        rows: list[Any]
        if name == "Chats":
            rows = self._chat_rows()
        elif name == "Choice points":
            rows = self._choices
        else:
            rows = self._history
        end = len(rows) - self._pages[name] * self._page_size
        start = max(0, end - self._page_size)
        return rows[start:end]

    # -- chat filter and village guide ----------------------------------------------------
    @property
    def chat_filter(self) -> tuple[str, str | None]:
        return self._chat_filter

    def set_chat_filter(self, kind: str, ident: str | None = None) -> None:
        """Show all chats, one village (ident = leader id, "" = wanderers), one person, or what the
        selected person heard."""
        if kind not in FILTER_KINDS:
            raise ValueError(f"unknown chat filter {kind!r}; choose one of {FILTER_KINDS}")
        if kind in ("village", "person") and ident is None:
            raise ValueError(f"chat filter {kind!r} needs an id")
        self._chat_filter = (kind, ident if kind in ("village", "person") else None)
        self._pages["Chats"] = 0
        self._rebuild()

    def _chat_rows(self) -> list[Any]:
        kind, ident = self._chat_filter
        if kind == "all":
            return self._chats
        selected = self._selected if kind == "heard" else None
        key = (kind, ident, len(self._chats), self._guide_sig, selected)
        cached = self._chat_cache
        if cached is not None and cached[0] == key:
            return cached[1]
        frame = self._last_frame
        village: frozenset[str] = frozenset()
        if kind == "village" and ident is not None:
            village = village_ids(frame, ident) if frame is not None else frozenset({ident} - {""})
        rows = [r for r in self._chats if row_matches(r, kind, ident, village, selected)]
        self._chat_cache = (key, rows)
        return rows

    def guide_text(self) -> str:
        """One line per village: ``"<leader name>: <member names or nobody>"``, wanderers last."""
        frame = self._last_frame
        return "\n".join(guide_lines(frame)) if frame is not None else ""

    @property
    def guide_collapsed(self) -> bool:
        return self._guide_collapsed

    def set_guide_collapsed(self, collapsed: bool) -> None:
        if collapsed == self._guide_collapsed:
            return
        self._guide_collapsed = collapsed
        self._sync_visibility()

    def toggle_guide(self) -> None:
        self.set_guide_collapsed(not self._guide_collapsed)

    def _guide_rich(self) -> str:
        frame = self._last_frame
        if frame is None:
            return ""
        lines = []
        for entry in frame.village_guide:
            names = [self._person_rich(vid) for vid, _n in entry.members]
            head = self._coloured(escape_rich(entry.leader_name), self._colour_of_index(entry))
            lines.append(f"{head}: " + (", ".join(names) or "nobody"))
        return "<br>".join(lines)

    def _guide_row_count(self, room: int) -> int:
        """Text rows the village guide needs at ``room`` pixels wide (wrapped), at least 1."""
        frame = self._last_frame
        if frame is None or not frame.village_guide:
            return _GUIDE_ROWS
        total = 0
        for entry in frame.village_guide:
            names = ", ".join(n for _v, n in entry.members) or "nobody"
            width = self._font.size(f"{entry.leader_name}: {names}")[0]
            total += max(1, -(-width // max(1, room)))
        return total

    def _colour_of_index(self, entry: Any) -> str:
        if entry.leader_id:
            return self._colour_hex.get(entry.leader_id, "")
        return self._hex(self._assets.colors.wanderer)

    @staticmethod
    def _hex(colour: str) -> str:
        red, green, blue, _alpha = hex_to_rgba(colour)
        return f"#{red:02x}{green:02x}{blue:02x}"

    @staticmethod
    def _coloured(text: str, colour: str) -> str:
        return f'<font color="{colour}">{text}</font>' if colour else text

    def _person_rich(self, ident: str) -> str:
        """A person's name in their village colour (never a link: links ignore font colours)."""
        return self._coloured(escape_rich(self._name(ident)), self._colour_hex.get(ident, ""))

    @staticmethod
    def _stamp_link(ident: str, tick: int) -> str:
        """The time stamp of a row, as a link that selects ``ident``."""
        if _LINK_ID.match(ident):
            return f'<a href="select:{ident}">{when(tick)}</a>'
        return when(tick)

    def _chat_rich(self, row: Any) -> str:
        who = self._person_rich(row.speaker)
        if row.targets:
            who += " -&gt; " + ", ".join(self._person_rich(t) for t in row.targets)
        heard = ", ".join(self._person_rich(h) for h in row.hearers) or "nobody"
        text = escape_rich(str(row.text).replace("\r", " ").replace("\n", " "))
        return f"{self._stamp_link(row.speaker, row.tick)} {who}: {text} | heard: {heard}"

    def _choice_rich(self, row: Any) -> str:
        judge = judge_words(row.judge_label_json, getattr(row, "judge_detail", None))
        rest = (
            f" [{row.tier}] {row.situation}"
            f" | {self._action_text(row)} | {self._label_text(row)}"
            f" | feeling: {getattr(row, 'feeling', '?')} | {judge}"
            f"{self._detail_text(row)}"
        )
        rest = escape_rich(rest.replace("\r", " ").replace("\n", " "))
        return (
            f"{self._stamp_link(row.player_id, row.tick)} {self._person_rich(row.player_id)}{rest}"
        )

    def _history_rich(self, row: Any) -> str:
        line = escape_rich(self._history_line(row))
        frame = self._last_frame
        present = {a.id for a in (*frame.players, *frame.villagers)} if frame is not None else set()
        for ident in getattr(row, "who", ()):
            if ident in present and _LINK_ID.match(ident):
                return f'<a href="select:{ident}">{line}</a>'
        return line

    def _rich_text(self, name: str) -> str:
        """The page as pygame_gui rich text: coloured names and select links."""
        if name in ("Players", "Spend"):
            return escape_rich(self.tab_text(name))
        plain = self.tab_text(name)
        if (name == "Chats" and self._chat_filter[0] == "heard" and self._selected is None) or (
            name == "Choice points" and not self._choices
        ):
            return escape_rich(plain)
        fmt = {
            "Chats": self._chat_rich,
            "Choice points": self._choice_rich,
            "World history": self._history_rich,
        }[name]
        return "<br>".join(fmt(row) for row in self._page_rows(name))

    def _players_block(self, frame: WorldFrame) -> str:
        panels = frame.panels
        if not panels:
            return ""
        lines: list[str] = []
        for p in panels:
            state = "alive" if p.alive else "dead"
            hooked = "yes" if p.hooked else "no"
            lines.append(
                f"{p.name} ({p.id}) {state} | {p.feeling} | X {p.x:.1f} | hooked: {hooked}"
            )
            profile = profile_lines(self._profiles, p.id)
            if profile:
                lines.append(profile)
            values = self._values.get(p.id)
            if values is None:
                lines.append("values: none (no value table)")
            else:
                core = set(core_ids(dict(values)))
                ranked = sorted(values, key=lambda item: (-item[1], _value_order(item[0])))
                lines.append(
                    "values (* = core): "
                    + ", ".join(f"{vid}{'*' if vid in core else ''} {w:.2f}" for vid, w in ranked)
                )
        lines.append("")
        lines.append("trust/anger toward: " + ", ".join(p.name for p in panels))
        for holder in panels:
            trust, anger = dict(holder.trust), dict(holder.anger)
            cells = []
            for other in panels:
                if other.id == holder.id:
                    cells.append("-")
                elif other.id in trust or other.id in anger:
                    cells.append(
                        f"{round(trust.get(other.id, 0.0))}/{round(anger.get(other.id, 0.0))}"
                    )
                else:
                    cells.append("-")
            lines.append(f"{holder.name}: " + "  ".join(cells))
        return "\n".join(lines)

    def _spend_block(self) -> str:
        db, ctl = self._db, self._controls
        total = db.spend_total() if db is not None else float(getattr(ctl, "spend_usd", 0.0))
        cap = float(getattr(ctl, "spend_cap_usd", 0.0))
        share = (100.0 * total / cap) if cap > 0 else 0.0
        lines = [
            f"Spent ${total:.2f} of ${cap:.2f} cap ({share:.1f}%)",
            f"Remaining ${max(0.0, cap - total):.2f}",
        ]
        if cap > 0 and total >= self._share * cap:
            lines.append(f"SPEND WARNING: {self._share * 100:.0f}% of the cap is used")
        reason = getattr(ctl, "pause_reason", None)
        if reason:
            lines.append(str(reason))
        if db is not None:
            lines += [f"Week {n}: ${usd:.2f}" for n, usd in db.spend_by_week(self._week_ticks)]
        return "\n".join(lines)

    # -- incremental reads -----------------------------------------------------------------
    def _refresh_people(self, frame: WorldFrame) -> None:
        """Village colour of every person (hex text) and a signature of the village guide."""
        colors = self._assets.colors
        wanderer = self._hex(colors.wanderer)
        out: dict[str, str] = {}
        for panel in frame.panels:
            out[panel.id] = self._hex(colors.players[f"player_{panel.index}"])
        for entry in frame.village_guide:
            colour = out.get(entry.leader_id, wanderer) if entry.leader_id else wanderer
            for vid, _name in entry.members:
                out[vid] = colour
        self._colour_hex = out
        self._guide_sig = tuple(
            (e.leader_id, e.leader_name, tuple(v for v, _n in e.members))
            for e in frame.village_guide
        )

    def _pull(self, frame: WorldFrame) -> None:
        names = dict(frame.names)
        if names:
            self._names = names
        self._refresh_people(frame)
        db = self._db
        if db is None:
            self._players_text = self._players_block(frame)
            self._spend_text = self._spend_block()
            return
        rows = db.chats_after(self._chat_cursor)
        if rows:
            self._chats.extend(rows)
            self._chat_cursor = rows[-1].id
        version = db.labels_version()
        labels_changed = version != self._labels_version
        if labels_changed:
            self._labels_version = version
            self._choices = list(db.choice_points_all())
        batch = db.events_after(self._history_cursor, tuple(HISTORY_TYPES))
        if batch:
            self._history_cursor = batch[-1][0]
            new_rows = history_entries(batch, self._names, self._structures)
            self._history.extend(new_rows)
            self._note_flashes(new_rows, frame)
        self._pull_summaries(db)
        self._flash_loaded = True
        self._graphs.update(db, [p.id for p in frame.panels])
        graves = db.events_after(self._grave_cursor, _GRAVE_TYPES)
        if graves:
            self._grave_cursor = graves[-1][0]
            for ident, event in graves:
                self._grave_at[ident] = (event.payload.x, event.payload.y)
            self._graves = frozenset(self._grave_at.values())
        values_version = getattr(db, "values_version", None)
        version_now = int(values_version()) if values_version is not None else -2
        panels_known = all(p.id in self._values for p in frame.panels)
        if version_now != self._values_version or not panels_known:
            self._values_version = version_now
            for p in frame.panels:
                self._values[p.id] = db.latest_values(p.id)
        if labels_changed:
            self._details = self._load_details(db)
        self._players_text = self._players_block(frame)
        self._spend_text = self._spend_block()

    def _pull_summaries(self, db: Any) -> None:
        """Daily summaries (with the day's flags) into World history; newest profile per player."""
        reader = getattr(db, "summaries_version", None)
        if reader is None:
            return
        version = int(reader())
        if version == self._summaries_version:
            return
        self._summaries_version = version
        tpd = max(1, self._week_ticks // 7)
        added = False
        for row in db.judge_summaries():
            if row.kind == "weekly_profile" and row.player_id:
                self._profiles[row.player_id] = row
            elif row.kind == "daily_summary" and row.period not in self._summary_days:
                self._summary_days.add(row.period)
                self._history.extend(history_rows_for_day(db, row, self._names, tpd))
                added = True
        if added:
            self._history.sort(key=lambda r: (r.tick, r.event_id))

    # -- top bar -----------------------------------------------------------------------------
    def _set_text(self, key: str, text: str) -> None:
        element = self._elements[key]
        text = self._fit(element.rect.w, text)
        if getattr(element, "text", None) != text:
            element.set_text(text)  # type: ignore[attr-defined]

    def _note(self, text: str) -> None:
        """Show a short note in the status label for ``status_seconds``."""
        self._status_text = text
        seconds = float(view_option(self._view, "status_seconds", 3.0))
        self._status_until = self._clock() + seconds
        self._set_text("top_status", text)

    def _update_top_bar(self, frame: WorldFrame) -> None:
        ctl = self._controls
        self._set_text("top_clock", f"{frame.hour:02d}:{frame.minute:02d}")
        self._set_text(
            "top_day_season",
            f"Year {frame.year}, {frame.season.capitalize()}, week {frame.week}, day {frame.day}",
        )
        paused = bool(getattr(ctl, "paused", False))
        self._set_text("top_pause", "Resume" if paused else "Pause")
        if ctl is not None:
            self.speed = float(ctl.speed)
        self._set_text("top_speed_label", f"x{self.speed:g}")
        spent = float(getattr(ctl, "spend_usd", 0.0))
        cap = float(getattr(ctl, "spend_cap_usd", 0.0))
        if cap > 0 and spent >= self._share * cap:
            warn = f"SPEND WARNING: {self._share * 100:.0f}% of cap"
        else:
            warn = "Spend OK"
        self._set_text("top_spend_warning", warn)
        saved = getattr(ctl, "last_autosave_tick", None)
        text = f"Autosaved {when(saved)}" if saved is not None else "Not saved yet"
        if getattr(ctl, "preview", False):
            text += " (preview)"
        self._set_text("top_autosave", text)
        reason = getattr(ctl, "pause_reason", None)
        if self._waiting:
            self._set_text("top_status", WAITING_TEXT)
        elif paused and reason:
            self._set_text("top_status", str(reason))
        else:
            self._set_text("top_status", self.status_text)

    def waiting_frame(self) -> bool:
        """Called by the simulation while it waits for AI replies (about 20 times a second).

        Handles window events and redraws the last finished frame with "Waiting for replies..."
        in the top bar. It never advances, runs, saves or flushes. Returns False once the user
        asked to close the window (the run control then closes after the current tick).
        """
        if self._closed:
            return False
        if not self.pump():
            self._quit_seen = True
            request = getattr(self._controls, "request_close", None)
            if request is not None:
                request()
        if self._last_frame is not None:
            self._waiting = True
            try:
                self.draw(self._last_frame, 0.0)
            finally:
                self._waiting = False
        return not self._quit_seen

    def _update_panel(self) -> None:
        if not self._panel_visible:
            return
        name = self._active
        if name == "Chats":
            self.show_page(name, self._pages[name])  # membership may have changed the page count
            self._update_guide()
        text = self._rich_text(name)
        key = (name, f"{self._pages[name]}:{text}")
        pages = self.page_count(name)
        shown = self._pages[name]
        label = f"Page {pages - shown} of {pages}" if name in _PAGED else ""
        self._set_text("page_label", label)
        if key == self._rendered:
            return
        first = self._rendered is None or self._rendered[0] != name
        box = self._box
        bar = box.scroll_bar
        pct = bar.start_percentage if bar is not None else None
        follow = first or pct is None or pct >= 0.99
        box.set_text(text)
        bar = box.scroll_bar
        if bar is not None:
            if name in _PAGED and follow:
                bar.set_scroll_from_start_percentage(1.0)
            elif first or pct is None:
                bar.set_scroll_from_start_percentage(0.0)
            else:
                bar.set_scroll_from_start_percentage(pct)
        self._rendered = key

    def _update_guide(self) -> None:
        rich = self._guide_rich()
        if rich != self._guide_rendered:
            self._guide_rendered = rich
            self._elements["chat_guide"].set_text(rich)  # type: ignore[attr-defined]
            self._sync_visibility()

    # -- settings and prefs --------------------------------------------------------------------
    def _save_prefs(self) -> None:
        error = save_prefs(
            self._prefs_path,
            {
                "display_size": self._display_size,
                "ui_scale": self._ui_choice,
                "panel_visible": self._panel_visible,
                "bubbles": self._bubble_mode,
                "minimap_visible": self._minimap_visible,
            },
        )
        if error is not None:
            self._note(f"Could not save settings: {error}")

    def apply_display(self, size: str, ui_choice: int) -> None:
        """Apply a Display menu choice at once and remember it in the prefs file."""
        if size not in DISPLAY_SIZES:
            raise ValueError(f"unknown display size {size!r}; choose one of {DISPLAY_SIZES}")
        if ui_choice not in UI_CHOICES:
            raise ValueError(f"unknown ui scale {ui_choice!r}; choose one of {UI_CHOICES}")
        self._display_size = size
        self._ui_choice = ui_choice
        if size == "fullscreen":
            self._enter_fullscreen()
        else:
            if self._fullscreen:
                self._leave_fullscreen()
            width, height = preset_size(size, self._view, DISPLAY_SIZES)
            self._set_display_mode(width, height, pygame.RESIZABLE)
            self._windowed_size = (self._win_w, self._win_h)
        self._rebuild()
        self._save_prefs()

    def set_fullscreen(self, on: bool) -> None:
        """Full screen on or off (F11); leaving restores the last windowed size."""
        if on == self._fullscreen:
            return
        if on:
            self._enter_fullscreen()
        else:
            self._leave_fullscreen()
        self._rebuild()

    def toggle_fullscreen(self) -> None:
        self.set_fullscreen(not self._fullscreen)

    def set_panel_visible(self, visible: bool) -> None:
        if visible == self._panel_visible:
            return
        self._panel_visible = visible
        self._rebuild()
        self._save_prefs()

    def toggle_panel(self) -> None:
        self.set_panel_visible(not self._panel_visible)

    def set_minimap_visible(self, visible: bool) -> None:
        if visible == self._minimap_visible:
            return
        self._minimap_visible = visible
        self._layout = compute_layout(
            self._win_w,
            self._win_h,
            self._ui_choice,
            self._panel_visible,
            self._minimap_visible,
            self._view,
        )
        self._save_prefs()

    def toggle_minimap(self) -> None:
        self.set_minimap_visible(not self._minimap_visible)

    def cycle_bubbles(self) -> None:
        """Bubble mode all -> players -> off -> all."""
        index = BUBBLE_MODES.index(self._bubble_mode)
        self._bubble_mode = BUBBLE_MODES[(index + 1) % len(BUBBLE_MODES)]
        self._save_prefs()

    def toggle_help(self) -> None:
        self._help_visible = not self._help_visible

    # -- screenshot ----------------------------------------------------------------------------
    def screenshot_folder(self) -> Path | None:
        if self._run_name is None:
            return None
        if self._screenshot_dir is not None:
            return self._screenshot_dir
        return self._root / "runs" / self._run_name / "screenshots"

    def save_screenshot(self) -> Path | None:
        """Write the composed window to a PNG named after the run and game time (F12)."""
        folder = self.screenshot_folder()
        if folder is None:
            self._note("Open a named run to save screenshots")
            return None
        frame = self._last_frame
        if frame is None:
            self._note("Nothing drawn yet")
            return None
        days_per_week = max(1, self._week_ticks // _MINUTES_PER_DAY)
        dow = (frame.day - 1) % days_per_week + 1
        stem = (
            f"{self._run_name}_y{frame.year}_w{frame.week}_d{dow}"
            f"_{frame.hour:02d}-{frame.minute:02d}"
        )
        path = folder / f"{stem}.png"
        number = 2
        while path.exists():
            path = folder / f"{stem}_{number}.png"
            number += 1
        try:
            folder.mkdir(parents=True, exist_ok=True)
            pygame.image.save(self._screen, str(path))
        except (OSError, pygame.error) as exc:
            self._note(f"Could not save screenshot: {exc}")
            return None
        self._note(f"Saved {path.name}")
        return path

    # -- selection -------------------------------------------------------------------------------
    @property
    def selected(self) -> str | None:
        return self._selected

    @property
    def following(self) -> bool:
        return self._following

    @following.setter
    def following(self, value: bool) -> None:
        self._following = bool(value)

    def select(self, ident: str) -> None:
        """Select a person: the inspector shows them and the map follows them."""
        if not isinstance(ident, str) or not ident:
            return
        was = self._selected
        self._selected = ident
        self._following = True
        self._rendered = None
        space = self._inspector_graph_space()
        if was is None or space != self._graph_space:
            self._graph_space = space
            self._rebuild()  # the inspector takes room at the top of the panel
        self._center_on_selected()

    def clear_selection(self) -> None:
        if self._selected is None:
            self._following = False
            return
        self._selected = None
        self._following = False
        self._rebuild()

    def _center_on_selected(self) -> None:
        frame = self._last_frame
        if frame is None or self._selected is None:
            return
        self._ensure_camera(frame)
        agent = agent_of(frame, self._selected)
        if agent is not None:
            self._camera.center_on(agent.x, agent.y)

    def _ensure_camera(self, frame: WorldFrame) -> None:
        """Give the camera a scale and map size right after a rebuild (before the next draw)."""
        self._map_w, self._map_h = frame.width, frame.height
        if self._camera.scale <= 0:
            self._apply_scale(self._choose_scale(frame.width, frame.height))

    def screen_pos_of(self, ident: str) -> tuple[int, int] | None:
        """Centre of a person's sprite in the last draw, or None when it was not drawn."""
        rect = self._agent_rects.get(ident)
        return None if rect is None else rect.center

    def person_at(self, px: int, py: int) -> str | None:
        """The person drawn under a screen point (players above villagers, lower id first)."""
        for ident in self._hit_order:
            rect = self._agent_rects.get(ident)
            if rect is not None and rect.collidepoint(px, py):
                return ident
        return None

    @property
    def inspector_rect(self) -> pygame.Rect:
        if self._selected is None or not self._panel_visible:
            return pygame.Rect(self._layout.panel.x, self._layout.panel.y, 0, 0)
        return self._layout.inspector.copy()

    def inspector_rows(self) -> list[tuple[str, str]]:
        """Label / value rows for the selected person (empty without a selection)."""
        frame = self._last_frame
        if self._selected is None or frame is None:
            return []
        return collect_rows(self.inspector_sections, frame, self._db, self._selected)

    def _popup_open(self) -> bool:
        for key in ("display_size", "display_ui_scale", "chat_filter"):
            element = self._elements.get(key)
            states = getattr(element, "menu_states", None)
            if states and getattr(element, "current_state", None) is states.get("expanded"):
                return True
        return False

    def _map_click(self, button: int, pos: tuple[int, int]) -> None:
        if button not in (1, 3) or not self._map_rect.collidepoint(pos):
            return
        if self._minimap_visible and self._layout.minimap.collidepoint(pos):
            if button == 1:
                self._minimap_click(pos)
            return
        if button == 3:
            self.clear_selection()
            return
        hit = self.person_at(*pos)
        if hit is None:
            self.clear_selection()
        else:
            self.select(hit)

    def _link_clicked(self, target: str) -> None:
        if not target.startswith("select:"):
            return
        ident = target[len("select:") :]
        if ident in self._names or ident in self._colour_hex:
            self.select(ident)

    def _chat_filter_chosen(self, label: str) -> None:
        choice = self._filter_choices.get(label)
        if choice is None:
            return
        kind, ident = choice
        if kind == "person" and ident is None:
            if self._selected is None:
                self._rebuild()  # nothing to filter by: put the old label back
                return
            ident = self._selected
        self.set_chat_filter(kind, ident)

    # -- bubbles, ring and inspector drawing ------------------------------------------------------
    def bubble_rects(self) -> list[tuple[str, pygame.Rect, str]]:
        """``(person id, screen rect, item key or "word:<text>")`` of the last draw's bubbles."""
        return [(ident, rect.copy(), label) for ident, rect, label in self._bubbles]

    def _rgb_of(self, ident: str) -> tuple[int, int, int]:
        text = self._colour_hex.get(ident, self._hex(self._assets.colors.wanderer))
        return hex_to_rgba(text)[:3]

    def _draw_map(self, frame: WorldFrame, sub_tick: float) -> None:
        self._map_w, self._map_h = frame.width, frame.height
        self._apply_scale(self._choose_scale(frame.width, frame.height))
        if self._following and self._selected is not None:
            agent = agent_of(frame, self._selected)
            if agent is not None:
                self._camera.center_on(agent.x, agent.y)
        super()._draw_map(frame, sub_tick)
        self._draw_overlays(frame, sub_tick)

    def _draw_overlays(self, frame: WorldFrame, sub_tick: float) -> None:
        """Selection ring and activity bubbles, over the map after the light layer."""
        self._last_sub = sub_tick
        camera, rect = self._camera, self._map_rect
        dead = {p.id for p in frame.panels if not p.alive}
        order = [a for a in frame.players if a.id not in dead] + list(frame.villagers)
        rects: dict[str, pygame.Rect] = {}
        for agent in order:
            box = camera.agent_rect(agent, frame, sub_tick)
            if box.colliderect(rect):
                rects[agent.id] = box
        self._agent_rects = rects
        self._hit_order = [a.id for a in order if a.id in rects]
        screen = self._screen
        screen.set_clip(rect)
        ring = rects.get(self._selected) if self._selected is not None else None
        if ring is not None and self._selected is not None:
            width = max(2, camera.scale)
            pygame.draw.rect(screen, _BUBBLE_EDGE, ring.inflate(2 * width, 2 * width), width)
            pygame.draw.rect(screen, self._rgb_of(self._selected), ring, width)
        self._draw_flashes()
        self._bubbles = self._draw_bubbles(order, rects)
        self._draw_minimap(frame, order)
        screen.set_clip(None)

    def _draw_flashes(self) -> None:
        """A blinking frame around the tile of every active flash."""
        flashes = self.active_flashes()
        if not flashes or not blink_on(self._clock()):
            return
        camera = self._camera
        colour = hex_to_rgba(self._assets.colors.flash)[:3]
        width = max(2, camera.scale)
        for flash in flashes:
            if flash.x < 0 or flash.y < 0:
                continue
            px, py = camera.world_to_screen(flash.x, flash.y)
            box = pygame.Rect(px, py, camera.tile, camera.tile)
            if box.colliderect(self._map_rect):
                pygame.draw.rect(self._screen, colour, box.inflate(width, width), width)

    def _draw_bubbles(
        self, order: list[Any], rects: dict[str, pygame.Rect]
    ) -> list[tuple[str, pygame.Rect, str]]:
        if self._bubble_mode == "off":
            return []
        layout = self._layout
        forbidden = [self._top_bar_rect, self._panel_rect]
        if self._minimap_visible and layout.minimap.w > 0:
            forbidden.append(layout.minimap)
        pad = int(view_option(self._view, "bubble_padding", 2)) * self._camera.scale
        assets = self._assets
        out: list[tuple[str, pygame.Rect, str]] = []
        for agent in order:
            sprite = rects.get(agent.id)
            if sprite is None or (self._bubble_mode == "players" and agent.kind != "player"):
                continue
            icon = assets.activity_icons.get(agent.activity, "word")
            picture = self._scaled.get(icon) if icon != "word" else None
            if picture is None:
                word = assets.activity_words.get(agent.activity, agent.activity)[:10]
                picture = self._font.render(word, False, _BUBBLE_EDGE)
                label = f"word:{word}"
            else:
                label = icon
            size = (picture.get_width() + 2 * pad, picture.get_height() + 2 * pad)
            spot = place_bubble(sprite, size, self._map_rect, forbidden)
            if spot is None:
                continue
            pygame.draw.rect(self._screen, _BUBBLE_BG, spot, border_radius=pad)
            pygame.draw.rect(self._screen, _BUBBLE_EDGE, spot, 1, border_radius=pad)
            self._screen.blit(picture, (spot.x + pad, spot.y + pad))
            out.append((agent.id, spot, label))
        return out

    def _draw_inspector(self) -> None:
        rect = self.inspector_rect
        if rect.h <= 0 or rect.w <= 0:
            return
        self._screen.fill(_BAR_BG, rect)
        rows = self.inspector_rows()
        pad = 4 * self._ui
        line_h = self._font.get_linesize() + self._ui
        per_col = max(1, (rect.h - 2 * pad) // line_h)
        font = self._font
        columns = 1
        laid: list[tuple[str, list[str]]] = []
        col_w = max(1, rect.w - pad)
        for columns in range(1, max(1, len(rows)) + 1):
            col_w = max(1, (rect.w - pad) // columns)
            laid = [(label, self._wrap_value(label, value, col_w - pad)) for label, value in rows]
            # greedy flow into columns; fits when it needs no more than ``columns`` columns
            need, used = 1, 0
            for _label, lines in laid:
                if used + len(lines) > per_col and used > 0:
                    need, used = need + 1, 0
                used += len(lines)
            if need <= columns:
                break
        self._screen.set_clip(rect)
        col, used = 0, 0
        for label, lines in laid:
            if used + len(lines) > per_col and used > 0:
                col, used = col + 1, 0
            x = rect.x + pad + col * col_w
            y = rect.y + pad + used * line_h
            head = font.render(f"{label}: ", False, _INSPECT_LABEL)
            self._screen.blit(head, (x, y))
            for j, line in enumerate(lines):
                self._screen.blit(
                    font.render(line, False, _INSPECT_VALUE),
                    (x + (head.get_width() if j == 0 else 2 * self._ui), y + j * line_h),
                )
            used += len(lines)
        self._screen.set_clip(None)

    def _wrap_value(self, label: str, value: str, room: int) -> list[str]:
        """Split an inspector value into lines; the first line sits after ``label: ``."""
        font = self._font
        first = room - font.size(f"{label}: ")[0]
        lines: list[str] = []
        current = ""
        limit = first
        for word in value.split(" "):
            trial = f"{current} {word}" if current else word
            if font.size(trial)[0] <= limit or not current:
                current = trial
            else:
                lines.append(current)
                current, limit = word, room - 2 * self._ui
        lines.append(current)
        return lines

    # -- events --------------------------------------------------------------------------------
    def _button(self, element: UIElement) -> None:
        ctl = self._controls
        elements = self._elements
        for tab, key in _TAB_KEYS.items():
            if element is elements[key]:
                self.select_tab(tab)
                return
        if element is elements["page_older"]:
            self.show_page(self._active, self._pages[self._active] + 1)
        elif element is elements["page_newer"]:
            self.show_page(self._active, self._pages[self._active] - 1)
        elif element is elements["top_pause"] and ctl is not None:
            ctl.toggle_pause()
        elif element is elements["top_speed_up"]:
            self._change_speed(2.0)
        elif element is elements["top_speed_down"]:
            self._change_speed(0.5)
        elif element is elements["top_panel"]:
            self.toggle_panel()
        elif element is elements["guide_toggle"]:
            self.toggle_guide()

    def _menu_changed(self, element: UIElement) -> None:
        elements = self._elements
        sizes, _size_now, scales, _scale_now = self._display_options()
        text = getattr(element, "selected_option", "")
        if isinstance(text, tuple):
            text = text[0]
        if element is elements["chat_filter"]:
            self._chat_filter_chosen(str(text))
        elif element is elements["display_size"] and text in sizes:
            self.apply_display(DISPLAY_SIZES[sizes.index(text)], self._ui_choice)
        elif element is elements["display_ui_scale"] and text in scales:
            self.apply_display(self._display_size, UI_CHOICES[scales.index(text)])

    def _change_speed(self, factor: float) -> None:
        if self._controls is not None:
            self._controls.set_speed(self._controls.speed * factor)
            self.speed = float(self._controls.speed)
        elif factor > 1:
            self.speed = min(self._view.max_speed, self.speed * factor)
        else:
            self.speed = max(self._view.speed / 8, self.speed * factor)

    def _scroll(self, dx: int, dy: int) -> None:
        step = self._view.scroll_tiles
        self._offset_x += dx * step
        self._offset_y += dy * step
        self._following = False

    def _key_pause(self) -> None:
        if self._controls is not None:
            self._controls.toggle_pause()

    def _key_jump(self) -> None:
        self.jump_to_latest()

    # -- flashes and J -----------------------------------------------------------------------------
    def _note_flashes(self, rows: list[Any], frame: WorldFrame) -> None:
        """Turn new history rows of the flash kinds into markers (not for the first backlog)."""
        seconds = float(view_option(self._view, "flash_seconds", 4.0))
        until = self._clock() + seconds if self._flash_loaded else 0.0
        for row in rows:
            if row.kind not in FLASH_KINDS:
                continue
            x, y = row.x, row.y
            if x < 0 and row.who:
                agent = agent_of(frame, row.who[0])
                if agent is not None:
                    x, y = agent.x, agent.y
            flash = Flash(row.event_id, row.kind, x, y, tuple(row.who), until)
            if self._flash_loaded:
                self._flashes.append(flash)
            key = (row.tick, row.event_id)
            if self._latest_flash is None or key >= self._latest_flash[:2]:
                self._latest_flash = (row.tick, row.event_id, flash)

    def active_flashes(self) -> list[Flash]:
        """Markers that are still showing (expired ones are dropped)."""
        now = self._clock()
        self._flashes = [f for f in self._flashes if f.until > now]
        return list(self._flashes)

    def jump_to_latest(self) -> None:
        """J: centre on the latest flash event of this session and select who was involved."""
        if self._latest_flash is None:
            self._note("No events to jump to yet")
            return
        flash = self._latest_flash[2]
        frame = self._last_frame
        if frame is None:
            return
        known = {ident for ident, _name in frame.names}
        ident = next((w for w in flash.who if w in known), None)
        if ident is not None:
            self.select(ident)
        x, y = flash.x, flash.y
        if x < 0 and ident is not None:
            agent = agent_of(frame, ident)
            if agent is not None:
                x, y = agent.x, agent.y
        if x >= 0:
            self._ensure_camera(frame)
            self._camera.center_on(x, y)
        self._following = ident is not None

    def graph_data(self, player_id: str) -> GraphData:
        """The graph series of a player, as the series functions returned them."""
        return self._graphs.data(player_id)

    # -- mini-map ----------------------------------------------------------------------------------
    def minimap_dots(self) -> list[tuple[str, int, int, tuple[int, int, int]]]:
        """``(person id, px, py, rgb)`` of every person on the map in the last draw."""
        if not self._minimap_visible or self._layout.minimap.w <= 0:
            return []
        return list(self._mini_dots)

    def _minimap_click(self, pos: tuple[int, int]) -> None:
        frame = self._last_frame
        rect = self._layout.minimap
        if frame is None:
            return
        tile = pixel_to_tile(rect, frame.width, frame.height, *pos)
        if tile is not None:
            self._camera.center_on(*tile)
            self._following = False

    def _draw_minimap(self, frame: WorldFrame, order: list[Any]) -> None:
        rect = self._layout.minimap
        if not self._minimap_visible or rect.w <= 0:
            self._mini_dots = []
            return
        colors = self._assets.colors
        stamp = (frame.width, frame.height, len(frame.owned_tiles), rect.size)
        now = self._clock()
        cached = self._mini_cache
        if cached is None or cached[0] != stamp or now - self._mini_stamp >= 0.5:
            ground = {k: hex_to_rgba(v)[:3] for k, v in colors.ground.items()}
            owners = {int(k.split("_")[1]): hex_to_rgba(v)[:3] for k, v in colors.players.items()}
            small = base_surface(frame, ground, owners, hex_to_rgba(colors.background)[:3])
            self._mini_cache = (stamp, pygame.transform.scale(small, rect.size))
            self._mini_stamp = now
        screen = self._screen
        draw_border(screen, rect, max(1, self._ui))
        screen.blit(self._mini_cache[1], rect.topleft)  # type: ignore[index]
        draw_frame_box(
            screen,
            rect,
            self._camera.visible_tiles(),
            frame.width,
            frame.height,
            max(1, self._ui),
        )
        dots: list[tuple[str, int, int, tuple[int, int, int]]] = []
        size = max(2, 2 * self._ui)
        for agent in order:
            px, py = tile_to_pixel(rect, frame.width, frame.height, agent.x, agent.y)
            colour = self._rgb_of(agent.id)
            pygame.draw.rect(
                screen, (20, 24, 30), (px - size // 2 - 1, py - size // 2 - 1, size + 2, size + 2)
            )
            pygame.draw.rect(screen, colour, (px - size // 2, py - size // 2, size, size))
            dots.append((agent.id, px, py, colour))
        self._mini_dots = dots

    def _key_screenshot(self) -> None:
        self.save_screenshot()

    def _on_key(self, key: int) -> bool:
        """Run the table entry for a key press. False means quit (Esc)."""
        name = self._key_names.get(key)
        if name is None:
            return True
        if name == "Esc":
            return False
        if name not in REPEATING_KEYS:
            if key in self._held:
                return True
            self._held.add(key)
        self._key_handlers[name]()
        return True

    def pump(self) -> bool:
        """Handle window events. Returns False when the user quit."""
        if self._closed or self._quit_seen:
            return False
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return False
            if event.type in (pygame.VIDEORESIZE, pygame.WINDOWSIZECHANGED):
                size = self._resize_of(event)
                if size is not None and size != (self._win_w, self._win_h):
                    self.relayout(*size)
            if event.type == pygame.WINDOWFOCUSLOST:
                self._held.clear()
            popup = event.type == pygame.MOUSEBUTTONDOWN and self._popup_open()
            self._manager.process_events(event)
            if event.type == pygame.KEYUP:
                self._held.discard(event.key)
            elif event.type == pygame.MOUSEBUTTONDOWN:
                if not popup:
                    self._map_click(event.button, event.pos)
            elif event.type == pygame_gui.UI_TEXT_BOX_LINK_CLICKED:
                self._link_clicked(str(event.link_target))
            elif event.type == pygame_gui.UI_BUTTON_PRESSED:
                self._button(event.ui_element)
            elif event.type == pygame_gui.UI_DROP_DOWN_MENU_CHANGED:
                self._menu_changed(event.ui_element)
            elif event.type == pygame.KEYDOWN:
                if not self._on_key(event.key):
                    return False
        if self._scale:
            self._clamp_offsets()
        else:
            self._offset_x = max(0, self._offset_x)
            self._offset_y = max(0, self._offset_y)
        return True

    # -- drawing ---------------------------------------------------------------------------------
    def _draw_help(self) -> None:
        """The key-help overlay: every table line, in as many columns as fit."""
        if not self._help_visible:
            return
        area = pygame.Rect(0, self._bar_h, self._win_w, max(0, self._win_h - self._bar_h))
        shade = pygame.Surface(area.size, pygame.SRCALPHA)
        shade.fill(_HELP_BG)
        self._screen.blit(shade, area.topleft)
        pad = 8 * self._ui
        line_h = self._font.get_linesize() + self._ui
        lines = ["Keys and buttons (H closes this)", "", *help_lines()]
        rows = max(1, (area.h - 2 * pad) // line_h)
        col_w = max(self._font.size(text)[0] for text in lines) + 2 * pad
        for i, text in enumerate(lines):
            col, row = divmod(i, rows)
            x = area.x + pad + col * col_w
            if x >= area.right:
                break
            self._screen.blit(
                self._font.render(text, False, _HELP_FG), (x, area.y + pad + row * line_h)
            )

    def draw(self, frame: WorldFrame, sub_tick: float = 0.0) -> None:
        """Draw the whole screen. Reads new database rows first, paused or not."""
        self._pull(frame)
        self._last_frame = frame
        if self._players_n != len(frame.panels):
            self._players_n = len(frame.panels)
            self._rebuild()
        self._draw_map(frame, sub_tick)
        self._update_top_bar(frame)
        self._update_panel()
        screen = self._screen
        screen.fill(_BAR_BG, self._top_bar_rect)
        if self._panel_visible:
            screen.fill(_PANEL_BG, self._panel_rect)
            self._draw_inspector()
            self._draw_graphs()
        now = time.perf_counter()
        self._manager.update(min(_MAX_DT, now - self._last_draw))
        self._last_draw = now
        self._manager.draw_ui(screen)
        self._draw_help()
        self._draw_times.append(now)
        pygame.display.set_caption(
            f"AI Island - Year {frame.year}, {frame.season.capitalize()}, week {frame.week}, "
            f"day {frame.day}, {frame.hour:02d}:{frame.minute:02d} - speed x{self.speed:g} "
            f"- {self.fps:.0f} fps"
        )
        pygame.display.flip()
