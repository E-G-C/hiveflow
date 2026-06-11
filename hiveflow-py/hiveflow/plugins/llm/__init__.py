"""LLM Provider Plugin System - Pluggable LLM backends.

LLM providers are the backbone of every agent. Each provider is a separate,
independently installable package following the plugin architecture.

All model references use the provider:model format:
  openai:gpt-4o
  anthropic:claude-sonnet-4-20250514
  ollama:llama3.3
"""

from abc import abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from hiveflow.core.registry import BasePlugin, PluginRegistry


@dataclass
class LLMMessage:
    """A single message in a conversation."""

    role: str  # "system", "user", "assistant", "tool"
    content: str
    name: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None


@dataclass
class LLMConfig:
    """Configuration for an LLM call."""

    model: str = ""
    temperature: float = 0.7
    max_tokens: int = 16000
    top_p: float = 1.0
    stop: list[str] | None = None
    tools: list[dict[str, Any]] | None = None
    response_format: dict[str, Any] | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class TokenUsage:
    """Token usage from an LLM call."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class LLMResponse:
    """Response from an LLM call."""

    content: str
    model: str
    tool_calls: list[dict[str, Any]] | None = None
    usage: TokenUsage | None = None
    finish_reason: str = "stop"


class LLMProvider(BasePlugin):
    """Base class for LLM provider plugins.

    Each provider implements:
    - provider_id: Unique identifier (e.g., "openai", "anthropic")
    - chat(): Synchronous/async completion
    - chat_stream(): Streaming completion
    - Capability reporting (streaming, function calling, etc.)
    """

    @property
    @abstractmethod
    def plugin_id(self) -> str:
        """Provider identifier (e.g., 'openai', 'anthropic')."""
        ...

    @property
    def provider_id(self) -> str:
        """Convenience alias — canonical term for LLM provider identification."""
        return self.plugin_id

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description of this provider."""
        ...

    @property
    def supports_streaming(self) -> bool:
        """Whether this provider supports streaming responses."""
        return False

    @property
    def supports_function_calling(self) -> bool:
        """Whether this provider supports function/tool calling."""
        return False

    @property
    def supports_json_mode(self) -> bool:
        """Whether this provider supports structured JSON output."""
        return False

    @property
    def supports_vision(self) -> bool:
        """Whether this provider supports image inputs."""
        return False

    @property
    def context_window(self) -> int | None:
        """Return the model's context window in tokens, or None if unknown.

        When None, the ModelContextRegistry fallback will be used.
        """
        return None

    @abstractmethod
    async def chat(self, messages: list[LLMMessage], config: LLMConfig) -> LLMResponse:
        """Send a chat completion request.

        Args:
            messages: List of conversation messages
            config: LLM configuration

        Returns:
            LLM response with content and metadata
        """
        ...

    async def chat_stream(
        self, messages: list[LLMMessage], config: LLMConfig
    ) -> AsyncIterator[str]:
        """Stream a chat completion response token by token.

        Default implementation falls back to non-streaming chat.

        Args:
            messages: List of conversation messages
            config: LLM configuration

        Yields:
            Individual tokens as strings
        """
        response = await self.chat(messages, config)
        yield response.content

    def get_available_models(self) -> list[str]:
        """List models this provider can serve.

        Returns:
            List of model identifiers
        """
        return []


class LLMProviderRegistry(PluginRegistry[LLMProvider]):
    """Registry for LLM provider plugins.

    Discovers providers from:
    - Python entry points under 'hiveflow.llm'
    - Drop-in directory at 'providers/'
    """

    def __init__(self, drop_in_dir: str | None = "providers") -> None:
        """Initialize LLM provider registry.

        Args:
            drop_in_dir: Path to drop-in providers directory
        """
        super().__init__(
            entry_point_group="hiveflow.llm",
            drop_in_dir=drop_in_dir,
        )

    # Known extras for install suggestions
    _KNOWN_EXTRAS: dict[str, str] = {
        "azure": "llm-azure",
        "google": "llm-google",
        "ollama": "llm-ollama",
    }

    def resolve_model(self, model_ref: str) -> tuple[LLMProvider, str]:
        """Resolve a provider:model reference to provider instance and model name.

        Args:
            model_ref: Model reference in format 'provider:model' (e.g., 'openai:gpt-4o')

        Returns:
            Tuple of (provider instance, model name)

        Raises:
            ValueError: If model reference format is invalid
            KeyError: If provider not found
        """
        if ":" not in model_ref:
            raise ValueError(
                f"Invalid model reference '{model_ref}'. "
                f"Expected format: 'provider:model' (e.g., 'openai:gpt-4o')"
            )

        provider_id, model_name = model_ref.split(":", 1)
        provider = self._plugins.get(provider_id)
        if provider is None:
            available = ", ".join(sorted(self._plugins.keys()))
            msg = f"Provider '{provider_id}' not found. Available: {available or '(none)'}."
            extra = self._KNOWN_EXTRAS.get(provider_id)
            if extra:
                msg += f"\n  Install with: uv add hiveflow[{extra}]"
            raise KeyError(msg)
        return provider, model_name


# Global LLM provider registry
_llm_registry: LLMProviderRegistry | None = None


def get_llm_registry() -> LLMProviderRegistry:
    """Get or create the global LLM provider registry.

    Returns:
        LLMProviderRegistry instance
    """
    global _llm_registry
    if _llm_registry is None:
        _llm_registry = LLMProviderRegistry()
        _llm_registry.discover()
    return _llm_registry


def reset_llm_registry() -> None:
    """Reset global LLM registry (mainly for testing)."""
    global _llm_registry
    _llm_registry = None


# Re-export SecretBackend symbols for convenience
# Re-export typed exception hierarchy
from hiveflow.plugins.llm.errors import (  # noqa: E402
    LLMAuthError,
    LLMConnectionError,
    LLMModelNotFoundError,
    LLMProviderError,
    LLMRateLimitError,
)
from hiveflow.plugins.llm.secrets import (  # noqa: E402
    EnvVarBackend,
    SecretBackend,
    get_secret_backend,
    set_secret_backend,
)

# Capability name → LLMProvider property mapping
_CAPABILITY_PROPERTIES = {
    "streaming": "supports_streaming",
    "function_calling": "supports_function_calling",
    "json_mode": "supports_json_mode",
    "vision": "supports_vision",
}


def check_provider_capabilities(
    provider: LLMProvider,
    required: list[str],
) -> list[str]:
    """Check a provider against required capabilities, logging warnings for mismatches.

    Args:
        provider: The LLM provider to check.
        required: List of capability names (e.g., ``["function_calling", "vision"]``).
            Valid names: ``streaming``, ``function_calling``, ``json_mode``, ``vision``.

    Returns:
        List of missing capability names (empty if all present).
    """
    import structlog

    _logger = structlog.get_logger()
    missing: list[str] = []

    for cap in required:
        prop_name = _CAPABILITY_PROPERTIES.get(cap)
        if prop_name is None:
            _logger.warning(
                "llm.capability.unknown",
                provider_id=provider.provider_id,
                capability=cap,
            )
            continue
        if not getattr(provider, prop_name, False):
            missing.append(cap)
            _logger.warning(
                "llm.capability.missing",
                provider_id=provider.provider_id,
                capability=cap,
                message=f"Provider '{provider.provider_id}' does not support '{cap}'. "
                "A prompt-based workaround will be attempted.",
            )

    return missing


__all__ = [
    "LLMMessage",
    "LLMConfig",
    "LLMResponse",
    "TokenUsage",
    "LLMProvider",
    "LLMProviderRegistry",
    "get_llm_registry",
    "reset_llm_registry",
    "SecretBackend",
    "EnvVarBackend",
    "get_secret_backend",
    "set_secret_backend",
    "LLMProviderError",
    "LLMAuthError",
    "LLMRateLimitError",
    "LLMModelNotFoundError",
    "LLMConnectionError",
    "check_provider_capabilities",
]
