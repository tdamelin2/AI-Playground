"""Errors of the AI connection layer (Contract C1)."""

from __future__ import annotations

from typing import Literal

PauseReason = Literal["spend_cap", "network", "sleep", "provider_error"]


class LLMError(Exception):
    """Base class of every error raised by llm/."""


class NetworkError(LLMError):
    """The provider could not be reached or the connection failed."""


class RateLimitError(LLMError):
    """The provider asked us to slow down."""


class ProviderRequestError(LLMError):
    """The provider refused the request itself (a 4xx other than 429): asking again won't help."""

    def __init__(
        self,
        provider: str,
        status_code: int,
        message: str,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code
        self.message = message
        self.request_id = request_id


class ReplayMissingError(LLMError):
    """Replay mode needed a stored reply that is not in the run database."""


class RealCallsBlocked(LLMError):
    """AI_ISLAND_OFFLINE=1 is set: no real client may be built or used (tests, safety switch)."""


class RunPaused(Exception):  # noqa: N818 - name fixed by the contract
    """The run must stop and wait for the user (money limit, no network, laptop slept)."""

    def __init__(self, reason: PauseReason, message: str = "") -> None:
        super().__init__(message or reason)
        self.reason: PauseReason = reason
