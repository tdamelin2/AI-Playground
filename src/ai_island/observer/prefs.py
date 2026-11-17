"""Observer preferences: a small JSON file next to the runs, never under config/."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

PREFS_VERSION = 1
DISPLAY_SIZES = ("fit", "1280x800", "1600x1000", "1920x1080", "fullscreen")
BUBBLE_MODES = ("all", "players", "off")
UI_CHOICES = (0, 1, 2, 3)


def _valid(key: str, value: Any) -> bool:
    if key == "display_size":
        return isinstance(value, str) and value in DISPLAY_SIZES
    if key == "ui_scale":
        return isinstance(value, int) and not isinstance(value, bool) and value in UI_CHOICES
    if key == "bubbles":
        return isinstance(value, str) and value in BUBBLE_MODES
    if key in ("panel_visible", "minimap_visible"):
        return isinstance(value, bool)
    return False


def load_prefs(path: Path | None) -> dict[str, Any]:
    """The valid values found in the file; anything missing, corrupt or invalid is left out."""
    if path is None:
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if k != "version" and _valid(k, v)}


def save_prefs(path: Path | None, prefs: dict[str, Any]) -> str | None:
    """Write atomically (temp file in the same folder, then replace). Returns an error or None."""
    if path is None:
        return None
    path = Path(path)
    data = {"version": PREFS_VERSION, **{k: v for k, v in prefs.items() if _valid(k, v)}}
    tmp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return str(exc)
    return None
