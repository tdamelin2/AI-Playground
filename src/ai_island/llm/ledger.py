"""The spend ledger: a hard money cap with reservations (Contract C4)."""

from __future__ import annotations

import threading
from decimal import Decimal


def _d(value: float) -> Decimal:
    return Decimal(repr(float(value)))


class SpendLedger:
    """Tracks money spent and money reserved for calls in flight.

    ``reserve`` refuses a call when ``total + outstanding reservations + bound`` would be above
    the cap (equal is allowed). Thread-safe, though the broker calls it on one thread.
    """

    def __init__(self, cap_usd: float, warning_share: float, total_usd: float = 0.0) -> None:
        self.cap_usd = float(cap_usd)
        self.warning_share = float(warning_share)
        self._total = _d(total_usd)
        self._reserved: dict[str, Decimal] = {}
        self._lock = threading.Lock()

    @property
    def total_usd(self) -> float:
        return float(self._total)

    @property
    def reserved_usd(self) -> float:
        with self._lock:
            return float(sum(self._reserved.values(), Decimal(0)))

    @property
    def warning(self) -> bool:
        return self._total >= _d(self.warning_share) * _d(self.cap_usd)

    def reserve(self, key: str, bound: float) -> bool:
        with self._lock:
            outstanding = sum(self._reserved.values(), Decimal(0))
            if self._total + outstanding + _d(bound) > _d(self.cap_usd):
                return False
            self._reserved[key] = _d(bound)
            return True

    def settle(self, key: str, cost: float) -> None:
        with self._lock:
            self._reserved.pop(key, None)
            self._total += _d(cost)

    def release(self, key: str) -> None:
        with self._lock:
            self._reserved.pop(key, None)
