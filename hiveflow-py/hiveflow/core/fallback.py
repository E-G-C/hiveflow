"""LLM Fallback Chains - Resilient LLM provider cascading.

When an LLM provider fails (rate limit, timeout, error), the fallback
chain automatically tries the next provider in the configured sequence.
"""

import asyncio
from collections.abc import Sequence
from typing import TYPE_CHECKING

import structlog

from hiveflow.plugins.llm import LLMConfig, LLMMessage, LLMProvider, LLMResponse
from hiveflow.plugins.llm.errors import LLMConnectionError, LLMRateLimitError

if TYPE_CHECKING:
    from hiveflow.core.config import HiveFlowConfig

logger = structlog.get_logger()

# Transient exceptions that should trigger fallback/retry cascading.
# Auth errors and model-not-found errors fail immediately (FR-019).
_TRANSIENT_EXCEPTIONS: tuple[type[Exception], ...] = (LLMRateLimitError, LLMConnectionError)


class FallbackChain(LLMProvider):
    """LLM provider that cascades through a chain of providers on failure.

    Given a list of providers, tries each one in order. If one fails,
    the next provider in the chain is attempted. Useful for handling
    rate limits, outages, and cost optimization.

    Example:
        chain = FallbackChain([
            (primary_provider, "gpt-4o"),
            (fallback_provider, "claude-sonnet-4-20250514"),
            (local_provider, "llama3.3"),
        ])
        response = await chain.chat(messages, config)
    """

    def __init__(
        self,
        providers: Sequence[tuple[LLMProvider, str]],
        retry_on: tuple[type[Exception], ...] | None = None,
    ) -> None:
        """Initialize fallback chain.

        Args:
            providers: List of (provider, model_name) tuples in priority order
            retry_on: Exception types that trigger fallback (default: all)
        """
        if not providers:
            raise ValueError("FallbackChain requires at least one provider")

        self._providers = providers
        self._retry_on = retry_on or _TRANSIENT_EXCEPTIONS

    @classmethod
    def from_tiers(
        cls,
        config: "HiveFlowConfig",
        provider: LLMProvider,
    ) -> "FallbackChain":
        """Auto-build a fallback chain from configured LLM tiers.

        Creates the chain: strategic → strategic@50% tokens → smart →
        smart@50% tokens → fast → error. Each step uses the same provider
        but with different model and max_tokens settings.

        Args:
            config: HiveFlowConfig with tier assignments and MAX_TOKENS
            provider: LLM provider to use for all tiers

        Returns:
            Configured FallbackChain with intermediate reduced-token steps
        """
        tiers = [
            config.STRATEGIC_LLM,
            config.SMART_LLM,
            config.FAST_LLM,
        ]
        # Deduplicate while preserving order (in case tiers are the same model)
        seen: set[str] = set()
        unique_tiers: list[str] = []
        for tier in tiers:
            if tier not in seen:
                seen.add(tier)
                unique_tiers.append(tier)

        providers: list[tuple[LLMProvider, str]] = []
        for model in unique_tiers:
            # Strip provider prefix (e.g. "azure:gpt-4o-mini" → "gpt-4o-mini")
            # since the provider is already resolved and the deployment name
            # must be a bare model identifier.
            deployment = model.split(":", 1)[-1] if ":" in model else model
            providers.append((provider, deployment))
            providers.append((_ReducedTokensProvider(provider, 0.5), deployment))

        return cls(providers)

    @property
    def plugin_id(self) -> str:
        return "fallback_chain"

    @property
    def description(self) -> str:
        provider_ids = [p.plugin_id for p, _ in self._providers]
        return f"Fallback chain: {' -> '.join(provider_ids)}"

    @property
    def supports_streaming(self) -> bool:
        return any(p.supports_streaming for p, _ in self._providers)

    @property
    def supports_function_calling(self) -> bool:
        return any(p.supports_function_calling for p, _ in self._providers)

    async def chat(self, messages: list[LLMMessage], config: LLMConfig) -> LLMResponse:
        """Send chat completion, falling back through providers on failure.

        If the caller's ``config.model`` specifies a concrete model (i.e. not
        empty and not already the first entry in the tier chain), that model is
        tried first with the primary (first) provider.  On transient failure it
        falls through to the normal tier chain.

        Args:
            messages: Conversation messages
            config: LLM configuration

        Returns:
            LLM response from first successful provider

        Raises:
            LLMFallbackExhaustedError: All providers failed
        """
        errors: list[tuple[str, str, Exception]] = []

        # Build the attempt list: caller's model first, then the tier chain.
        attempts: list[tuple[LLMProvider, str]] = list(self._providers)
        caller_model = config.model.strip() if config.model else ""
        if caller_model:
            # Strip provider prefix ("azure:gpt-4o-mini" → "gpt-4o-mini")
            deployment = caller_model.split(":", 1)[-1] if ":" in caller_model else caller_model
            # Only prepend if it differs from the first tier entry (avoid dup)
            first_tier_model = attempts[0][1] if attempts else None
            if deployment != first_tier_model:
                primary_provider = attempts[0][0] if attempts else None
                if primary_provider is not None:
                    attempts.insert(0, (primary_provider, deployment))

        for provider, model in attempts:
            try:
                # Override config model with the provider-specific model
                provider_config = LLMConfig(
                    model=model,
                    temperature=config.temperature,
                    max_tokens=config.max_tokens,
                    top_p=config.top_p,
                    stop=config.stop,
                    tools=config.tools,
                    response_format=config.response_format,
                    extra=config.extra,
                )

                logger.debug(
                    "Trying provider %s with model %s",
                    provider.plugin_id,
                    model,
                )
                response = await provider.chat(messages, provider_config)

                if errors:
                    logger.info(
                        "Fallback succeeded with %s:%s after %d failures",
                        provider.plugin_id,
                        model,
                        len(errors),
                    )

                return response

            except self._retry_on as exc:
                logger.warning(
                    "Provider %s:%s failed: %s",
                    provider.plugin_id,
                    model,
                    exc,
                )
                errors.append((provider.plugin_id, model, exc))
                continue

        raise LLMFallbackExhaustedError(errors)


class LLMFallbackExhaustedError(Exception):
    """All providers in the fallback chain have failed."""

    def __init__(self, errors: list[tuple[str, str, Exception]]) -> None:
        self.errors = errors
        count = len(errors)
        super().__init__(f"All {count} LLM provider(s) failed. Check logs for details.")


class RetryProvider(LLMProvider):
    """Wraps a single provider with retry logic.

    Retries the same provider N times with optional delay.
    Often combined with FallbackChain for comprehensive resilience.
    """

    def __init__(
        self,
        provider: LLMProvider,
        max_retries: int = 3,
        retry_on: tuple[type[Exception], ...] | None = None,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
    ) -> None:
        """Initialize retry wrapper.

        Args:
            provider: Provider to wrap
            max_retries: Maximum number of retry attempts
            retry_on: Exception types that trigger retry
            base_delay: Initial backoff delay in seconds
            max_delay: Maximum backoff delay in seconds
        """
        self._provider = provider
        self._max_retries = max_retries
        self._retry_on = retry_on or _TRANSIENT_EXCEPTIONS
        self._base_delay = base_delay
        self._max_delay = max_delay

    @property
    def plugin_id(self) -> str:
        return f"retry_{self._provider.plugin_id}"

    @property
    def description(self) -> str:
        return f"Retry wrapper for {self._provider.plugin_id} (max {self._max_retries})"

    @property
    def supports_streaming(self) -> bool:
        return self._provider.supports_streaming

    @property
    def supports_function_calling(self) -> bool:
        return self._provider.supports_function_calling

    async def chat(self, messages: list[LLMMessage], config: LLMConfig) -> LLMResponse:
        """Send chat with automatic retries.

        Args:
            messages: Conversation messages
            config: LLM configuration

        Returns:
            LLM response

        Raises:
            Last exception if all retries exhausted
        """
        last_error: Exception | None = None

        for attempt in range(self._max_retries):
            try:
                return await self._provider.chat(messages, config)
            except self._retry_on as exc:
                last_error = exc
                logger.warning(
                    "Provider %s attempt %d/%d failed: %s",
                    self._provider.plugin_id,
                    attempt + 1,
                    self._max_retries,
                    exc,
                )
                if attempt < self._max_retries - 1:
                    delay = min(self._base_delay * 2**attempt, self._max_delay)
                    await asyncio.sleep(delay)

        raise last_error  # type: ignore[misc]


def build_fallback_chain(
    provider_models: list[tuple[LLMProvider, str]],
    max_retries_per_provider: int = 2,
) -> FallbackChain:
    """Build a fallback chain with retry wrappers on each provider.

    Convenience function that wraps each provider with RetryProvider
    before building the FallbackChain.

    Args:
        provider_models: List of (provider, model) tuples
        max_retries_per_provider: Retries per provider before fallback

    Returns:
        Configured FallbackChain
    """
    wrapped = [
        (RetryProvider(provider, max_retries=max_retries_per_provider), model)
        for provider, model in provider_models
    ]
    return FallbackChain(wrapped)


class _ReducedTokensProvider(LLMProvider):
    """Internal wrapper that reduces max_tokens by a factor before delegating."""

    def __init__(self, provider: LLMProvider, factor: float) -> None:
        self._provider = provider
        self._factor = factor

    @property
    def plugin_id(self) -> str:
        return f"{self._provider.plugin_id}@{int(self._factor * 100)}%"

    @property
    def description(self) -> str:
        return f"{self._provider.description} (max_tokens * {self._factor})"

    @property
    def supports_streaming(self) -> bool:
        return self._provider.supports_streaming

    @property
    def supports_function_calling(self) -> bool:
        return self._provider.supports_function_calling

    async def chat(self, messages: list[LLMMessage], config: LLMConfig) -> LLMResponse:
        reduced_config = LLMConfig(
            model=config.model,
            temperature=config.temperature,
            max_tokens=int(config.max_tokens * self._factor),
            top_p=config.top_p,
            stop=config.stop,
            tools=config.tools,
            response_format=config.response_format,
            extra=config.extra,
        )
        return await self._provider.chat(messages, reduced_config)
