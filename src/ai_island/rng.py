"""Named random streams.

Each stream is its own ``random.Random`` seeded from a stable SHA-256 of a versioned
``"v1:{seed}:{name}"`` string. Python's ``hash()`` and the clock are never used, so the
same seed always gives the same numbers, and drawing from one stream never changes
another.
"""

from __future__ import annotations

import hashlib
import random
from typing import Any

SEED_VERSION = "v1"


def stream_seed(seed: int, name: str) -> int:
    """The integer seed of stream ``name`` for run seed ``seed``."""
    digest = hashlib.sha256(f"{SEED_VERSION}:{seed}:{name}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


class Streams:
    """The set of named random streams of one run."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        self._streams: dict[str, random.Random] = {}

    def get(self, name: str) -> random.Random:
        """The stream called ``name`` (created on first use)."""
        stream = self._streams.get(name)
        if stream is None:
            stream = random.Random(stream_seed(self.seed, name))
            self._streams[name] = stream
        return stream

    def state(self) -> dict[str, Any]:
        """JSON-safe state of every stream created so far."""
        out: dict[str, Any] = {}
        for name in sorted(self._streams):
            version, internal, gauss = self._streams[name].getstate()
            out[name] = {"version": version, "internal": list(internal), "gauss": gauss}
        return {"seed": self.seed, "seed_version": SEED_VERSION, "streams": out}

    @classmethod
    def from_state(cls, state: dict[str, Any]) -> Streams:
        """Rebuild the streams exactly as they were when ``state()`` was taken."""
        streams = cls(int(state["seed"]))
        for name, data in state["streams"].items():
            rng = random.Random()
            rng.setstate((data["version"], tuple(data["internal"]), data["gauss"]))
            streams._streams[name] = rng
        return streams
