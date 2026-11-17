"""What the simulation hands to an AI controller when it binds it (Contract C6)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ai_island.minds.settings import MindSettings


@dataclass
class MindsRuntime:
    """``embedder``: anything with ``embed(texts)``; ``models``: ModelsConfig (its ``roles``);
    ``balance``: BalanceConfig (or its ``mind`` table); ``ai_cfg``: run.toml ``[ai]``."""

    embedder: Any
    models: Any
    balance: Any
    ai_cfg: Any
    cheap: bool = False

    def settings(self) -> MindSettings:
        mind = getattr(self.balance, "mind", self.balance)
        return MindSettings.from_config(mind)
