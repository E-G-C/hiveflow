"""Resilient LLM Provider - Wraps LLM providers with resilience patterns.

Applies rate limiting, circuit breaking, fallback chains, and cost tracking
transparently. Drop-in replacement for any LLMProvider.
"""

import time

import structlog

from hiveflow.core.config import HiveFlowConfig
from hiveflow.core.cost import CostTracker
from hiveflow.core.errors import CircuitBreaker
from hiveflow.core.fallback import FallbackChain
from hiveflow.core.ratelimit import ProviderRateLimiter
from hiveflow.plugins.llm import LLMConfig, LLMMessage, LLMProvider, LLMResponse

logger = structlog.get_logger()

# Global per-process rate limiter (shared across all workflows)
_global_rate_limiter: ProviderRateLimiter | None = None


def _get_global_rate_limiter() -> ProviderRateLimiter:
    """Get or create the global per-process rate limiter."""
    global _global_rate_limiter  # noqa: PLW0603
    if _global_rate_limiter is None:
        _global_rate_limiter = ProviderRateLimiter()
    return _global_rate_limiter


class ResilientLLMProvider(LLMProvider):
    """Wraps an LLMProvider with resilience patterns.

    Pipeline: rate_limit → circuit_breaker → fallback_chain → cost_track

    Usage:
        provider = ResilientLLMProvider.from_config(base_provider, config)
        response = await provider.chat(messages, llm_config)
    """

    def __init__(
        self,
        fallback_chain: FallbackChain,
        circuit_breaker: CircuitBreaker | None = None,
        rate_limiter: ProviderRateLimiter | None = None,
        cost_tracker: CostTracker | None = None,
        agent_id: str = "unknown",
    ) -> None:
        self._fallback_chain = fallback_chain
        self._circuit_breaker = circuit_breaker or CircuitBreaker()
        self._rate_limiter = rate_limiter or _get_global_rate_limiter()
        self._cost_tracker = cost_tracker
        self._agent_id = agent_id

    @classmethod
    def from_config(
        cls,
        provider: LLMProvider,
        config: HiveFlowConfig,
        cost_tracker: CostTracker | None = None,
        agent_id: str = "unknown",
    ) -> "ResilientLLMProvider":
        """Factory: auto-build resilience stack from config.

        Args:
            provider: Base LLM provider to wrap
            config: HiveFlowConfig with tier assignments
            cost_tracker: Optional cost tracker (created if None and tracking enabled)
            agent_id: Agent identifier for cost attribution

        Returns:
            Configured ResilientLLMProvider
        """
        fallback_chain = FallbackChain.from_tiers(config, provider)

        if cost_tracker is None and config.ENABLE_COST_TRACKING:
            cost_tracker = CostTracker()

        rate_limiter = _get_global_rate_limiter()
        # Ensure the rate limiter is configured for the default provider
        provider_id = provider.plugin_id
        if provider_id not in rate_limiter._limiters:
            rate_limiter.configure(provider_id)

        return cls(
            fallback_chain=fallback_chain,
            rate_limiter=rate_limiter,
            cost_tracker=cost_tracker,
            agent_id=agent_id,
        )

    @property
    def plugin_id(self) -> str:
        return f"resilient_{self._fallback_chain.plugin_id}"

    @property
    def description(self) -> str:
        return f"Resilient wrapper: {self._fallback_chain.description}"

    @property
    def supports_streaming(self) -> bool:
        return self._fallback_chain.supports_streaming

    @property
    def supports_function_calling(self) -> bool:
        return self._fallback_chain.supports_function_calling

    async def chat(self, messages: list[LLMMessage], config: LLMConfig) -> LLMResponse:
        """Execute LLM call with full resilience pipeline.

        Pipeline order:
        1. Rate limiter acquire (global per-process)
        2. Circuit breaker gate
        3. Fallback chain (with tier cascade)
        4. Cost tracking on success

        Args:
            messages: Conversation messages
            config: LLM configuration

        Returns:
            LLM response from the first successful provider/tier

        Raises:
            LLMFallbackExhaustedError: All fallback options exhausted
            CircuitBreakerOpenError: Circuit breaker is open
        """
        # 1. Rate limiting
        provider_id = config.model.split(":")[0] if ":" in config.model else "default"
        await self._rate_limiter.acquire_request(provider_id)

        # 2. Circuit breaker + 3. Fallback chain
        start_time = time.monotonic()
        response = await self._circuit_breaker.call(self._fallback_chain.chat, messages, config)
        latency_ms = (time.monotonic() - start_time) * 1000

        # 4. Cost tracking
        if self._cost_tracker and response.usage:
            self._cost_tracker.record(
                agent_id=self._agent_id,
                model=response.model or config.model,
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens,
            )
            logger.debug(
                "LLM call cost tracked: model=%s, tokens=%d, latency=%.1fms",
                response.model,
                response.usage.total_tokens,
                latency_ms,
            )

        return response
