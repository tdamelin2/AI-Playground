"""The observer's one table of keys, buttons and mouse actions (no pygame at import).

The key handler, the H overlay and the generated guide all read ``KEY_TABLE``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class KeyBinding:
    name: str
    kind: Literal["key", "button", "mouse"]
    action: str


def _k(name: str, action: str) -> KeyBinding:
    return KeyBinding(name, "key", action)


def _b(name: str, action: str) -> KeyBinding:
    return KeyBinding(name, "button", action)


def _m(name: str, action: str) -> KeyBinding:
    return KeyBinding(name, "mouse", action)


KEY_TABLE: tuple[KeyBinding, ...] = (
    _k("P", "pause or resume the game"),
    _k("+", "faster (also = and keypad +)"),
    _k("-", "slower (also keypad -)"),
    _k("Left", "scroll the map left"),
    _k("Right", "scroll the map right"),
    _k("Up", "scroll the map up"),
    _k("Down", "scroll the map down"),
    _k("Tab", "hide or show the side panel"),
    _k("B", "bubbles: all, players only, off"),
    _k("M", "mini-map on or off"),
    _k("J", "jump to the latest event"),
    _k("H", "show or hide this key help"),
    _k("F11", "full screen on or off"),
    _k("F12", "save a screenshot"),
    _k("Esc", "quit"),
    _b("Pause/Resume", "pause or resume the game"),
    _b("-", "slower"),
    _b("+", "faster"),
    _b("Chats", "show the Chats tab"),
    _b("Choice points", "show the Choice points tab"),
    _b("World history", "show the World history tab"),
    _b("Players", "show the Players tab"),
    _b("Spend", "show the Spend tab"),
    _b("Older", "older page of the list"),
    _b("Newer", "newer page of the list"),
    _b("Panel", "hide or show the side panel"),
    _b("Display size", "choose the window size"),
    _b("UI scale", "choose the text and button scale"),
    _b("Village guide", "fold or unfold the village guide on the Chats tab"),
    _b("Chat filter", "choose which chats to show"),
    _m("Left click person on map", "select that person (the map follows them)"),
    _m("Right click map", "clear the selection"),
    _m("Click empty map", "clear the selection"),
    _m("Click chat/choice/history row", "select the person named in the row"),
    _m("Click mini-map", "move the view there"),
    _m("Mouse wheel", "scroll the text"),
    _m("Drag window edge", "resize the window"),
)

# pygame constant names per key binding; resolved with getattr(pygame, ...) by the observer.
KEY_CODES: dict[str, tuple[str, ...]] = {
    "P": ("K_p",),
    "+": ("K_PLUS", "K_EQUALS", "K_KP_PLUS"),
    "-": ("K_MINUS", "K_KP_MINUS"),
    "Left": ("K_LEFT",),
    "Right": ("K_RIGHT",),
    "Up": ("K_UP",),
    "Down": ("K_DOWN",),
    "Tab": ("K_TAB",),
    "B": ("K_b",),
    "M": ("K_m",),
    "J": ("K_j",),
    "H": ("K_h",),
    "F11": ("K_F11",),
    "F12": ("K_F12",),
    "Esc": ("K_ESCAPE",),
}

# Keys that may repeat while held; every other key key acts once per press.
REPEATING_KEYS = frozenset({"+", "-", "Left", "Right", "Up", "Down"})


def key_bindings() -> tuple[KeyBinding, ...]:
    return tuple(b for b in KEY_TABLE if b.kind == "key")


def help_lines() -> list[str]:
    """One line per table entry: ``"<name>: <action>"``."""
    return [f"{b.name}: {b.action}" for b in KEY_TABLE]
