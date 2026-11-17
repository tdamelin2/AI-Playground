"""One writer per run: an OS byte lock on <run dir>/run.lock.

The OS drops the lock when the process dies, so a killed run never leaves a stale lock.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import IO


class RunBusyError(Exception):
    """Another process already has this run open for writing."""


def _try_lock(handle: IO[bytes]) -> bool:
    handle.seek(0)
    if sys.platform == "win32":
        import msvcrt

        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined]
        except OSError:
            return False
        return True
    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)  # type: ignore[attr-defined]
    except OSError:
        return False
    return True


def _unlock(handle: IO[bytes]) -> None:
    handle.seek(0)
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)  # type: ignore[attr-defined]


class RunLock:
    """Takes the lock on creation; ``release`` (also safe twice) gives it up."""

    def __init__(self, db_path: Path) -> None:
        db_path = Path(db_path)
        self.path = db_path.parent / "run.lock"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle: IO[bytes] | None = open(self.path, "a+b")  # noqa: SIM115
        self._handle.seek(0, 2)
        if self._handle.tell() == 0:
            self._handle.write(b"0")
            self._handle.flush()
        if not _try_lock(self._handle):
            self._handle.close()
            self._handle = None
            raise RunBusyError(f"run '{db_path.parent.name}' is already open in another window")

    @property
    def held(self) -> bool:
        return self._handle is not None

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            _unlock(self._handle)
        finally:
            self._handle.close()
            self._handle = None

    def __enter__(self) -> RunLock:
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()
