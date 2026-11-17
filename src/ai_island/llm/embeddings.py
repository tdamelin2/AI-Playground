"""Embedding cache: in memory, plus an optional sqlite file for persisted runs (Contract C5).

Snapshots hold text only; vectors are rebuilt or read back from this cache by
``sha256(model + text)``.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from ai_island.llm.adapters import map_error
from ai_island.llm.types import Embedder


def embedding_key(model: str, text: str) -> str:
    return hashlib.sha256((model + "\x00" + text).encode("utf-8")).hexdigest()


class OllamaEmbedder:
    """Embeds through a local Ollama server: ``client.embed(model, input=[...])``."""

    def __init__(self, client: Any, model: str) -> None:
        self.client = client
        self.model = model

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            response = self.client.embed(model=self.model, input=list(texts), truncate=False)
        except Exception as exc:
            mapped = map_error(exc)
            if mapped is None:
                raise
            raise mapped from exc
        vectors = response["embeddings"] if isinstance(response, dict) else response.embeddings
        return [[float(v) for v in vec] for vec in vectors]


class CachedEmbedder:
    """Wraps an embedder with a memory dict and, when ``path`` is given, a sqlite file."""

    def __init__(self, inner: Embedder, model: str, path: Path | None = None) -> None:
        self.inner = inner
        self.model = model
        self.path = Path(path) if path is not None else None
        self._mem: dict[str, list[float]] = {}
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.path, check_same_thread=False)
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS embeddings "
                "(key TEXT PRIMARY KEY, vector_json TEXT NOT NULL)"
            )
            self._conn.commit()
        self.inner_calls = 0

    def _lookup(self, key: str) -> list[float] | None:
        if key in self._mem:
            return self._mem[key]
        if self._conn is not None:
            row = self._conn.execute(
                "SELECT vector_json FROM embeddings WHERE key = ?", (key,)
            ).fetchone()
            if row is not None:
                vec = json.loads(row[0])
                self._mem[key] = vec
                return vec
        return None

    def embed(self, texts: list[str]) -> list[list[float]]:
        with self._lock:
            keys = [embedding_key(self.model, t) for t in texts]
            found = {k: self._lookup(k) for k in dict.fromkeys(keys)}
            missing = [
                (k, t) for k, t in dict.fromkeys(zip(keys, texts, strict=True)) if found[k] is None
            ]
            if missing:
                self.inner_calls += 1
                vectors = self.inner.embed([t for _, t in missing])
                for (k, _), vec in zip(missing, vectors, strict=True):
                    found[k] = vec
                    self._mem[k] = vec
                    if self._conn is not None:
                        self._conn.execute(
                            "INSERT OR REPLACE INTO embeddings (key, vector_json) VALUES (?, ?)",
                            (k, json.dumps(vec)),
                        )
                if self._conn is not None:
                    self._conn.commit()
            return [found[k] for k in keys]  # type: ignore[misc]

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
