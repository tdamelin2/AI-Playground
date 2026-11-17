"""Session-wide test setup: real AI calls are blocked for every test (Phase 5 money rule)."""

from __future__ import annotations

import os

os.environ["AI_ISLAND_OFFLINE"] = "1"
