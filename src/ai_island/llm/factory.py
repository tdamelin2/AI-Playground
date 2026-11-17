"""The only place that builds real SDK clients and reads API keys from the environment.

``make_runtime`` picks the adapters and the embedder for a run: the fake backend never loads
dotenv and never touches the network; the live backend builds one real adapter per provider and
the Ollama embedder. ``make_adapter`` calls python-dotenv's ``load_dotenv()`` (keys stay in the
process environment, never printed or logged) and builds each SDK client with its own retries
off; the broker owns all retrying. Setting ``AI_ISLAND_OFFLINE=1`` makes every real build fail
with ``RealCallsBlocked`` before anything is created.
"""

from __future__ import annotations

import os
from typing import Any

from ai_island.llm.adapters import (
    AnthropicAdapter,
    GoogleAdapter,
    MistralAdapter,
    OpenAIAdapter,
)
from ai_island.llm.errors import RealCallsBlocked
from ai_island.llm.types import Adapter, Embedder

XAI_BASE_URL = "https://api.x.ai/v1"
OFFLINE_ENV = "AI_ISLAND_OFFLINE"


def check_offline() -> None:
    """Raise RealCallsBlocked when the offline switch is on."""
    if os.environ.get(OFFLINE_ENV) == "1":
        raise RealCallsBlocked(
            f"real AI calls are blocked because {OFFLINE_ENV}=1 is set in this environment"
        )


def make_adapter(provider: str, timeout_seconds: float = 120.0) -> Adapter:
    """Build the adapter (with a real client) for ``provider``."""
    check_offline()
    from dotenv import load_dotenv

    load_dotenv()
    if provider == "anthropic":
        import anthropic

        return AnthropicAdapter(anthropic.Anthropic(max_retries=0, timeout=timeout_seconds))
    if provider == "openai":
        import openai

        return OpenAIAdapter(openai.OpenAI(max_retries=0, timeout=timeout_seconds), "openai")
    if provider == "xai":
        import openai

        client = openai.OpenAI(
            api_key=os.environ.get("XAI_API_KEY"),
            base_url=XAI_BASE_URL,
            max_retries=0,
            timeout=timeout_seconds,
        )
        return OpenAIAdapter(client, "xai")
    if provider == "google":
        from google import genai
        from google.genai import types

        options = types.HttpOptions(timeout=int(timeout_seconds * 1000))
        client: Any = genai.Client(http_options=options)
        return GoogleAdapter(client)
    if provider == "mistral":
        from mistralai.client import Mistral
        from mistralai.client.utils.retries import BackoffStrategy, RetryConfig

        no_retries = RetryConfig("backoff", BackoffStrategy(0, 0, 1.0, 0), False)
        return MistralAdapter(
            Mistral(
                api_key=os.environ.get("MISTRAL_API_KEY"),
                timeout_ms=int(timeout_seconds * 1000),
                retry_config=no_retries,
            )
        )
    raise ValueError(f"unknown provider '{provider}'")


def make_runtime(
    backend: str,
    providers: list[str] | tuple[str, ...],
    embedding_model: str,
    timeout_seconds: float,
) -> tuple[dict[str, Adapter], Embedder]:
    """The adapters (by provider) and the embedder for a run.

    ``fake``: a FakeAdapter under the key "fake" (the broker's practice fallback) and a
    FakeEmbedder; dotenv is never loaded. ``live``: one real adapter per provider and the Ollama
    embedder; raises RealCallsBlocked when the offline switch is on.
    """
    if backend == "fake":
        from ai_island.llm.fake import FakeAdapter, FakeEmbedder

        return {"fake": FakeAdapter()}, FakeEmbedder()
    if backend != "live":
        raise ValueError(f"unknown backend '{backend}'")
    check_offline()
    adapters: dict[str, Adapter] = {
        p: make_adapter(p, timeout_seconds) for p in dict.fromkeys(providers)
    }
    return adapters, make_ollama_embedder(embedding_model)


def make_ollama_embedder(model: str) -> Embedder:
    """The local Ollama embedder (never built while the offline switch is on)."""
    check_offline()
    import ollama

    from ai_island.llm.embeddings import OllamaEmbedder

    return OllamaEmbedder(ollama.Client(), model)


def check_ollama(model: str) -> str | None:
    """None when Ollama runs and has ``model``; otherwise one plain sentence for Tim."""
    pull = f"Install the embedding model with: ollama pull {model}"
    try:
        import ollama

        listed = ollama.Client().list()
        entries = listed["models"] if isinstance(listed, dict) else listed.models
        names = []
        for entry in entries:
            name = entry.get("model") if isinstance(entry, dict) else getattr(entry, "model", None)
            if name:
                names.append(str(name))
    except Exception:
        return f"Ollama is not running on this computer, so memories cannot be searched. {pull}"
    if any(n == model or n.split(":")[0] == model for n in names):
        return None
    return f"Ollama is running but does not have '{model}' yet. {pull}"
