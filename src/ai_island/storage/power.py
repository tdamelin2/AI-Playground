"""Keep the computer awake while a run is active (Windows SetThreadExecutionState)."""

from __future__ import annotations

import sys
from collections.abc import Callable

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ACQUIRE_FLAGS = ES_CONTINUOUS | ES_SYSTEM_REQUIRED
RELEASE_FLAGS = ES_CONTINUOUS


def _default_setter() -> Callable[[int], int]:
    """kernel32.SetThreadExecutionState on Windows, a no-op that reports success elsewhere."""
    if sys.platform != "win32":
        return lambda flags: 1
    import ctypes

    func = ctypes.windll.kernel32.SetThreadExecutionState  # type: ignore[attr-defined]
    func.argtypes = [ctypes.c_uint32]
    func.restype = ctypes.c_uint32
    return lambda flags: int(func(flags))


class KeepAwake:
    """Asks the OS not to sleep between ``acquire`` and ``release`` (call both on one thread)."""

    def __init__(self, setter: Callable[[int], int] | None = None) -> None:
        self._setter = setter if setter is not None else _default_setter()
        self.active = False
        self.ok = True  # False when the OS refused the request (setter returned 0)

    def acquire(self) -> None:
        if self.active:
            return
        self.ok = self._setter(ACQUIRE_FLAGS) != 0
        self.active = True

    def release(self) -> None:
        if not self.active:
            return
        self._setter(RELEASE_FLAGS)
        self.active = False
