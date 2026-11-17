"""The four SDK adapters (Contract C2): common request in, common reply out.

Each adapter gets an already built SDK client (so tests inject a mock), turns an ``LLMRequest``
into that SDK's call with structured output, and turns the SDK response into a ``RawReply`` with
normalised ``Usage`` (uncached input only; output includes thinking, counted once). JSON parsing
and Pydantic validation happen in the broker, never here.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from ai_island.config import RoleConfig
from ai_island.llm.errors import NetworkError, ProviderRequestError, RateLimitError
from ai_island.llm.schema_transform import extract_json, provider_schema, schema_instruction
from ai_island.llm.types import LLMRequest, RawReply, Usage

SCHEMA_NAME = "reply"
_NETWORK_NAMES = {
    "APIConnectionError",
    "APITimeoutError",
    "ConnectError",
    "ConnectTimeout",
    "ReadTimeout",
    "TimeoutException",
    "RemoteProtocolError",
    "InternalServerError",
    "ServiceUnavailableError",
}


def _get(obj: Any, name: str, default: Any = None) -> Any:
    """Attribute or dict key, so real SDK objects and plain mock dicts both work."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        value = obj.get(name, default)
    else:
        value = getattr(obj, name, default)
    return default if value is None else value


def _int(obj: Any, name: str) -> int:
    value = _get(obj, name, 0)
    return int(value) if isinstance(value, int | float) else 0


def _optional_int(obj: Any, name: str) -> int | None:
    value = _get(obj, name, None)
    return int(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _request_error(exc: Exception, status: int) -> ProviderRequestError:
    """A short, key-free summary of an SDK 4xx error (never the request body or headers)."""
    body = getattr(exc, "body", None)
    message = ""
    if isinstance(body, dict):
        err = body.get("error", body)
        if isinstance(err, dict):
            message = str(err.get("message") or "")
    if not message:
        message = str(getattr(exc, "message", "") or exc)
    message = " ".join(message.split())[:300]
    request_id = getattr(exc, "request_id", None)
    module = type(exc).__module__.split(".")[0]
    return ProviderRequestError(
        module, status, message, request_id if isinstance(request_id, str) else None
    )


def map_error(exc: Exception) -> Exception | None:
    """Our error for an SDK / transport exception, or None when it is not a connection problem."""
    if isinstance(exc, NetworkError | RateLimitError | ProviderRequestError):
        return exc
    name = type(exc).__name__
    status = getattr(exc, "status_code", None)
    if name == "RateLimitError" or status == 429:
        return RateLimitError(str(exc))
    if name in _NETWORK_NAMES or (isinstance(status, int) and status >= 500):
        return NetworkError(str(exc))
    if isinstance(status, int) and not isinstance(status, bool) and 400 <= status < 500:
        if status in (408, 409):
            return NetworkError(str(exc))  # retryable
        return _request_error(exc, status)
    try:
        import httpx

        if isinstance(exc, httpx.TransportError):
            return NetworkError(str(exc))
    except ImportError:  # pragma: no cover - httpx ships with the SDKs
        pass
    return None


def _guarded(call: Callable[[], Any]) -> Any:
    try:
        return call()
    except Exception as exc:
        mapped = map_error(exc)
        if mapped is None:
            raise
        raise mapped from exc


def _prompt_mode(role: RoleConfig) -> bool:
    return role.output_mode == "prompt"


def _extracted(text: str, role: RoleConfig) -> str:
    """Prompt mode: the JSON object inside the reply; schema mode: the text as is."""
    return extract_json(text) if _prompt_mode(role) else text


def _joined(request: LLMRequest) -> str:
    layers = request.layers
    return layers.fixed + ("\n\n" + layers.slow if layers.slow else "")


class AnthropicAdapter:
    def __init__(self, client: Any) -> None:
        self.client = client

    def build_kwargs(self, request: LLMRequest, role: RoleConfig) -> dict[str, Any]:
        layers = request.layers
        marker = {"type": "ephemeral"}
        system = [{"type": "text", "text": layers.fixed, "cache_control": dict(marker)}]
        if layers.slow:
            system.append({"type": "text", "text": layers.slow, "cache_control": dict(marker)})
        output_config: dict[str, Any] = {}
        if _prompt_mode(role):
            system.append(
                {
                    "type": "text",
                    "text": schema_instruction(request.schema, "anthropic"),
                    "cache_control": dict(marker),
                }
            )
        else:
            output_config["format"] = {
                "type": "json_schema",
                "schema": provider_schema(request.schema, "anthropic"),
            }
        if "effort" in role.thinking:
            output_config["effort"] = role.thinking["effort"]
        kwargs: dict[str, Any] = {
            "model": role.model,
            "max_tokens": request.max_output_tokens,
            "system": system,
            "messages": [{"role": "user", "content": layers.current}],
        }
        if output_config:
            kwargs["output_config"] = output_config
        if "type" in role.thinking:
            thinking: dict[str, Any] = {"type": role.thinking["type"]}
            if role.thinking["type"] == "enabled":
                thinking["budget_tokens"] = int(role.thinking["budget_tokens"])
                if "display" in role.thinking:
                    thinking["display"] = role.thinking["display"]
            kwargs["thinking"] = thinking
        return kwargs

    def generate(self, request: LLMRequest, role: RoleConfig) -> RawReply:
        kwargs = self.build_kwargs(request, role)
        started = time.perf_counter()
        response = _guarded(lambda: self.client.messages.create(**kwargs))
        elapsed = (time.perf_counter() - started) * 1000.0
        blocks = _get(response, "content", []) or []
        text = "".join(
            str(_get(b, "text", "")) for b in blocks if _get(b, "type", "text") == "text"
        )
        usage = _get(response, "usage", None)
        return RawReply(
            text=_extracted(text, role),
            usage=Usage(
                input_tokens=_int(usage, "input_tokens"),
                output_tokens=_int(usage, "output_tokens"),
                thinking_tokens=_optional_int(
                    _get(usage, "output_tokens_details", None), "thinking_tokens"
                ),
                cache_read_tokens=_int(usage, "cache_read_input_tokens"),
                cache_write_tokens=_int(usage, "cache_creation_input_tokens"),
            ),
            model_version=str(_get(response, "model", role.model)),
            refused=_get(response, "stop_reason", None) == "refusal",
            duration_ms=elapsed,
        )


class OpenAIAdapter:
    """OpenAI Responses API; xAI uses the same class with ``base_url`` set on the client."""

    def __init__(self, client: Any, provider: str = "openai") -> None:
        self.client = client
        self.provider = provider

    def build_kwargs(self, request: LLMRequest, role: RoleConfig) -> dict[str, Any]:
        system = _joined(request)
        if _prompt_mode(role):
            system += "\n\n" + schema_instruction(request.schema, self.provider)
        kwargs: dict[str, Any] = {
            "model": role.model,
            "input": [
                {"role": "system", "content": system},
                {"role": "user", "content": request.layers.current},
            ],
            "max_output_tokens": request.max_output_tokens,
        }
        if not _prompt_mode(role):
            kwargs["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": SCHEMA_NAME,
                    "schema": provider_schema(request.schema, self.provider),
                    "strict": True,
                }
            }
        if "effort" in role.thinking:
            kwargs["reasoning"] = {"effort": role.thinking["effort"]}
        return kwargs

    def generate(self, request: LLMRequest, role: RoleConfig) -> RawReply:
        kwargs = self.build_kwargs(request, role)
        started = time.perf_counter()
        response = _guarded(lambda: self.client.responses.create(**kwargs))
        elapsed = (time.perf_counter() - started) * 1000.0
        text = _get(response, "output_text", None)
        refused = False
        parts: list[str] = []
        for item in _get(response, "output", []) or []:
            for part in _get(item, "content", []) or []:
                kind = _get(part, "type", "")
                if kind == "refusal":
                    refused = True
                elif kind == "output_text":
                    parts.append(str(_get(part, "text", "")))
        if text is None:
            text = "".join(parts)
        usage = _get(response, "usage", None)
        total_in = _int(usage, "input_tokens")
        cached = _int(_get(usage, "input_tokens_details", None), "cached_tokens")
        return RawReply(
            text=_extracted(str(text), role),
            usage=Usage(
                input_tokens=max(0, total_in - cached),
                output_tokens=_int(usage, "output_tokens"),
                thinking_tokens=_optional_int(
                    _get(usage, "output_tokens_details", None), "reasoning_tokens"
                ),
                cache_read_tokens=cached,
                cache_write_tokens=0,
            ),
            model_version=str(_get(response, "model", role.model)),
            refused=refused,
            duration_ms=elapsed,
        )


class GoogleAdapter:
    """Google's Interactions API through google-genai."""

    def __init__(self, client: Any) -> None:
        self.client = client

    def build_kwargs(self, request: LLMRequest, role: RoleConfig) -> dict[str, Any]:
        from google.genai._gaos.google_genai import interactions as it

        generation_config: dict[str, Any] = {"max_output_tokens": request.max_output_tokens}
        if "thinking_level" in role.thinking:
            generation_config["thinking_level"] = role.thinking["thinking_level"]
        system = request.layers.fixed + ("\n" + request.layers.slow if request.layers.slow else "")
        kwargs: dict[str, Any] = {
            "model": role.model,
            "input": request.layers.current,
            "generation_config": generation_config,
            "store": False,
        }
        if _prompt_mode(role):
            system += "\n\n" + schema_instruction(request.schema, "google")
        else:
            kwargs["response_format"] = it.TextResponseFormat(
                schema_=provider_schema(request.schema, "google"), mime_type="application/json"
            )
        kwargs["system_instruction"] = system
        return kwargs

    def generate(self, request: LLMRequest, role: RoleConfig) -> RawReply:
        kwargs = self.build_kwargs(request, role)
        started = time.perf_counter()
        response = _guarded(lambda: self.client.interactions.create(**kwargs))
        elapsed = (time.perf_counter() - started) * 1000.0
        status = str(_get(response, "status", "")).lower()
        usage = _get(response, "usage", None)
        total_in = _int(usage, "total_input_tokens")
        cached = _int(usage, "total_cached_tokens")
        thought = _int(usage, "total_thought_tokens")
        return RawReply(
            text=_extracted(str(_get(response, "output_text", "") or ""), role),
            usage=Usage(
                input_tokens=max(0, total_in - cached),
                output_tokens=_int(usage, "total_output_tokens") + thought,
                thinking_tokens=_optional_int(usage, "total_thought_tokens"),
                cache_read_tokens=cached,
                cache_write_tokens=0,
            ),
            model_version=str(_get(response, "model", role.model)),
            refused=status in ("blocked", "safety", "content_filter"),
            duration_ms=elapsed,
        )


class MistralAdapter:
    def __init__(self, client: Any) -> None:
        self.client = client

    def build_kwargs(self, request: LLMRequest, role: RoleConfig) -> dict[str, Any]:
        system = _joined(request)
        if _prompt_mode(role):
            system += "\n\n" + schema_instruction(request.schema, "mistral")
        kwargs: dict[str, Any] = {
            "model": role.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": request.layers.current},
            ],
            "reasoning_effort": role.thinking.get("reasoning_effort", "none"),
            "max_tokens": request.max_output_tokens,
        }
        if not _prompt_mode(role):
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": SCHEMA_NAME,
                    "schema": provider_schema(request.schema, "mistral"),
                    "strict": True,
                },
            }
        return kwargs

    def generate(self, request: LLMRequest, role: RoleConfig) -> RawReply:
        kwargs = self.build_kwargs(request, role)
        started = time.perf_counter()
        response = _guarded(lambda: self.client.chat.complete(**kwargs))
        elapsed = (time.perf_counter() - started) * 1000.0
        choices = _get(response, "choices", []) or []
        choice = choices[0] if choices else None
        content = _get(_get(choice, "message", None), "content", "")
        if isinstance(content, list):
            content = "".join(
                str(_get(c, "text", c if isinstance(c, str) else "")) for c in content
            )
        usage = _get(response, "usage", None)
        total_in = _int(usage, "prompt_tokens")
        cached = _int(usage, "num_cached_tokens") or _int(
            _get(usage, "prompt_tokens_details", None), "cached_tokens"
        )
        return RawReply(
            text=_extracted(str(content or ""), role),
            usage=Usage(
                input_tokens=max(0, total_in - cached),
                output_tokens=_int(usage, "completion_tokens"),
                thinking_tokens=None,
                cache_read_tokens=cached,
                cache_write_tokens=0,
            ),
            model_version=str(_get(response, "model", role.model)),
            refused=str(_get(choice, "finish_reason", "")) == "content_filter",
            duration_ms=elapsed,
        )
