"""Typed exception hierarchy for LLM provider errors.

Provides precise programmatic error handling for fallback chains,
middleware, and user code. All exceptions carry a human-readable
message and optional provider_id.

Hierarchy:
    LLMProviderError (base)
    ├── LLMAuthError          — authentication/authorization failures
    ├── LLMRateLimitError     — rate limit or quota exhaustion
    ├── LLMModelNotFoundError — unknown model or deployment
    └── LLMConnectionError    — network, timeout, or server errors
"""


class LLMProviderError(Exception):
    """Base exception for all LLM provider errors.

    Args:
        message: Human-readable error description.
        provider_id: Identifier of the provider that raised the error
            (e.g., "openai", "anthropic", "azure").
    """

    def __init__(self, message: str, provider_id: str | None = None) -> None:
        self.provider_id = provider_id
        super().__init__(message)


class LLMAuthError(LLMProviderError):
    """Authentication or authorization failure.

    Raised when API keys are invalid, RBAC roles are missing,
    or credentials are expired. This is a permanent error —
    FallbackChain does NOT cascade on this exception.
    """


class LLMRateLimitError(LLMProviderError):
    """Rate limit or quota exhaustion.

    Raised when the provider returns a 429 or equivalent.
    This is a transient error — FallbackChain cascades to the
    next provider.
    """


class LLMModelNotFoundError(LLMProviderError):
    """Unknown model or deployment name.

    Raised when the provider exists but the requested model/deployment
    is not available. This is a permanent error — FallbackChain does
    NOT cascade on this exception.

    Note: For missing *providers* (not registered in the registry),
    the registry raises KeyError, not this exception.
    """


class LLMConnectionError(LLMProviderError):
    """Network, timeout, or server error.

    Raised on connection failures, request timeouts, and server
    errors (5xx). This is a transient error — FallbackChain cascades
    to the next provider.
    """
