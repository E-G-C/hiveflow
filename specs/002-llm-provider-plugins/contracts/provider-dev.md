# Provider Development Guideline

**Date**: 2026-02-19 | **Plan**: [plan.md](plan.md) | **Fulfills**: FR-012

## Overview

This document describes how to add a new LLM provider plugin to HiveFlow. Providers are discoverable via Python entry points and follow a standard interface.

## API Stability

The `LLMProvider` base class, `LLMConfig`, `LLMMessage`, `LLMResponse`, `TokenUsage`, and `SecretBackend` interfaces are considered **stable** and follow semantic versioning. Breaking changes to these interfaces will be accompanied by a major version bump. The typed exception hierarchy (`LLMProviderError` and subclasses) is also stable.

Internal implementation details (registry internals, observability module internals) are **not** part of the stable plugin API and may change without notice.

## manifest.yaml (Optional, Future)

The requirements document (requirements/04-plugins.md) describes a `manifest.yaml` for plugin metadata (author, version, dependencies, config). This is **not yet implemented** — provider metadata is currently inferred from entry points and the class definition. When manifest support is added, it will be additive and backward-compatible.

## Step-by-Step Guide

### 1. Create the Provider File

Create `hiveflow/plugins/llm/<provider_name>_provider.py`:

```python
"""<Provider Name> LLM Provider for HiveFlow."""

from collections.abc import AsyncIterator
from typing import Any

from hiveflow.plugins.llm import LLMConfig, LLMMessage, LLMProvider, LLMResponse, TokenUsage


class MyProvider(LLMProvider):
    """My LLM provider using the <SDK Name>."""

    def __init__(self) -> None:
        self._client: Any = None

    def _get_client(self) -> Any:
        """Lazy-initialize the async client.

        SDK imports go HERE, not at module level. This ensures
        the provider module can be imported even when the SDK
        is not installed (import fails only when actually used).
        """
        if self._client is None:
            try:
                from my_sdk import AsyncMyClient
            except ImportError as exc:
                raise ImportError(
                    "<SDK Name> required. Install with: uv add my-sdk"
                ) from exc

            from hiveflow.plugins.llm.secrets import get_secret_backend

            backend = get_secret_backend()
            self._client = AsyncMyClient(
                api_key=backend.get_secret("MY_API_KEY"),
            )
        return self._client

    @property
    def plugin_id(self) -> str:
        return "my_provider"  # Used in "my_provider:model-name" references (provider_id)

    @property
    def description(self) -> str:
        return "My Provider API (model-x, model-y)"

    # --- Capability Flags ---
    # Override only the ones your provider supports (defaults are False)

    @property
    def supports_streaming(self) -> bool:
        return True

    @property
    def supports_function_calling(self) -> bool:
        return True

    @property
    def supports_json_mode(self) -> bool:
        return False  # Set True if supported

    @property
    def supports_vision(self) -> bool:
        return False  # Set True if supported

    # --- Core Methods ---

    async def chat(
        self, messages: list[LLMMessage], config: LLMConfig
    ) -> LLMResponse:
        client = self._get_client()

        # Convert LLMMessage to your SDK's format
        formatted = [self._format_message(m) for m in messages]

        # Call the SDK
        response = await client.complete(
            model=config.model,
            messages=formatted,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
        )

        # Convert response to LLMResponse
        return LLMResponse(
            content=response.text,
            model=response.model,
            usage=TokenUsage(
                prompt_tokens=response.usage.input,
                completion_tokens=response.usage.output,
                total_tokens=response.usage.input + response.usage.output,
            ),
            finish_reason=response.stop_reason or "stop",
        )

    async def chat_stream(
        self, messages: list[LLMMessage], config: LLMConfig
    ) -> AsyncIterator[str]:
        client = self._get_client()
        formatted = [self._format_message(m) for m in messages]

        stream = await client.complete(
            model=config.model,
            messages=formatted,
            stream=True,
        )
        async for chunk in stream:
            if chunk.text:
                yield chunk.text

    def get_available_models(self) -> list[str]:
        return ["model-x", "model-y"]

    @staticmethod
    def _format_message(msg: LLMMessage) -> dict[str, Any]:
        """Convert LLMMessage to SDK format."""
        return {"role": msg.role, "content": msg.content}
```

### 2. Register as Entry Point

In `pyproject.toml`, add your provider to the entry point group:

```toml
[project.entry-points."hiveflow.llm"]
my_provider = "hiveflow.plugins.llm.my_provider_provider:MyProvider"
```

The entry point name must match `plugin_id` (which serves as the `provider_id` for LLM providers).

### 3. Add Optional Dependency (if needed)

If your provider depends on an SDK not in core dependencies:

```toml
[project.optional-dependencies]
llm-my-provider = [
    "my-sdk>=1.0.0",
]
```

Update the `all` extra to include it:

```toml
all = [
    "hiveflow[api,frontend,llm-azure,llm-google,llm-my-provider,...]",
]
```

### 4. Write Tests

Create `tests/test_my_provider.py`:

```python
"""Tests for My LLM Provider."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from hiveflow.plugins.llm import LLMConfig, LLMMessage
from hiveflow.plugins.llm.my_provider_provider import MyProvider


class TestMyProvider:
    def test_plugin_id(self):
        provider = MyProvider()
        assert provider.plugin_id == "my_provider"

    def test_capabilities(self):
        provider = MyProvider()
        assert provider.supports_streaming is True
        assert provider.supports_function_calling is True

    @pytest.mark.asyncio
    async def test_chat(self):
        provider = MyProvider()
        mock_client = AsyncMock()
        # ... mock the SDK client and test chat()

    def test_missing_sdk(self):
        provider = MyProvider()
        with patch.dict("sys.modules", {"my_sdk": None}):
            with pytest.raises(ImportError, match="my-sdk"):
                provider._get_client()
```

### 5. Re-install and Verify

```bash
uv sync
uv run python -c "from hiveflow.plugins.llm import get_llm_registry; r = get_llm_registry(); print(r.list_ids())"
# Should include "my_provider"
```

## Architecture Rules

1. **Zero import-time SDK dependencies**: Import SDKs lazily inside `_get_client()`, not at module level
2. **Graceful failure**: If the SDK isn't installed, entry point discovery logs a warning and skips — other providers remain available
3. **Capability flags must be accurate**: The framework uses these to decide whether to send tools, JSON mode config, etc.
4. **Use `plugin_id` as the provider prefix**: Users reference models as `provider_id:model-name` (the `plugin_id` property on `BasePlugin` serves as `provider_id` for LLM providers)
5. **Error messages must be actionable**: Include the install command and any required environment variables
6. **Use `SecretBackend` for ALL credentials**: Call `get_secret_backend().get_secret(key)` instead of `os.environ.get(key)` directly — this enables pluggable credential stores. This applies to all credential lookups including auth decision logic (e.g., Azure API key vs. RBAC check).
7. **Emit structured log events**: Use `structlog.get_logger()` to log `llm.chat.complete` events with `provider_id`, model, latency, and token usage after each call
8. **Raise typed exceptions**: Map SDK-specific errors to `LLMAuthError`, `LLMRateLimitError`, `LLMModelNotFoundError`, or `LLMConnectionError` (from `hiveflow.plugins.llm.errors`). Include `provider_id` in all exceptions.
9. **Streaming errors discard partial content**: In `chat_stream()`, catch SDK errors and raise `LLMConnectionError`. Do not preserve partial output in the exception.

## Examples

- **OpenAI**: `hiveflow/plugins/llm/openai_provider.py` — simplest example
- **Anthropic**: `hiveflow/plugins/llm/anthropic_provider.py` — shows API format translation
- **Azure**: `hiveflow/plugins/llm/azure_provider.py` — shows multi-auth strategy

## Potential Future Providers

| Provider | `provider_id` | SDK | Notes |
|----------|---------------|-----|-------|
| Ollama (native) | `ollama` | `ollama` | Currently served via OpenAI provider's `base_url` override. Native API would support Ollama-specific features. |
| Google Gemini | `google` | `google-generativeai` | Requires tool call format translation |
| Mistral | `mistral` | `mistral` | OpenAI-compatible API |
| Together AI | `together` | `together` | OpenAI-compatible API |
| Fireworks | `fireworks` | `fireworks-ai` | OpenAI-compatible API |
| vLLM | `vllm` | N/A | Use OpenAI provider with `base_url` |
| LM Studio | `lmstudio` | N/A | Use OpenAI provider with `base_url` |
