"""Rate Limiting & Concurrency Control for multi-agent LLM workflows.

Provides token bucket rate limiting for API calls and concurrency
limiters for parallel agent execution.
"""

import asyncio
import time
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

import structlog

logger = structlog.get_logger()

T = TypeVar("T")


class TokenBucketRateLimiter:
    """Token bucket rate limiter for API calls.

    Controls the rate of LLM API calls to stay within provider rate limits.
    Supports both requests-per-minute and tokens-per-minute limiting.

    Usage:
        limiter = TokenBucketRateLimiter(max_rate=60, per_seconds=60)  # 60 req/min
        await limiter.acquire()
        # make API call
    """

    def __init__(
        self,
        max_rate: float,
        per_seconds: float = 60.0,
        burst_multiplier: float = 1.0,
    ) -> None:
        """Initialize rate limiter.

        Args:
            max_rate: Maximum number of tokens (requests) in the period
            per_seconds: Period duration in seconds
            burst_multiplier: Allow burst up to this multiplier of max_rate
        """
        self._max_tokens = max_rate * burst_multiplier
        self._tokens = self._max_tokens
        self._refill_rate = max_rate / per_seconds  # tokens per second
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: float = 1.0) -> None:
        """Acquire rate limit tokens, waiting if necessary.

        Args:
            tokens: Number of tokens to consume (default 1 for one request)

        Raises:
            ValueError: If tokens exceeds bucket capacity
        """
        if tokens > self._max_tokens:
            raise ValueError(
                f"Requested {tokens} tokens exceeds bucket capacity {self._max_tokens}"
            )
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                # Calculate wait time for enough tokens
                deficit = tokens - self._tokens
                wait_time = deficit / self._refill_rate

            await asyncio.sleep(wait_time)

    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(
            self._max_tokens,
            self._tokens + elapsed * self._refill_rate,
        )
        self._last_refill = now

    @property
    def available_tokens(self) -> float:
        """Current available tokens (approximate)."""
        return self._tokens


class ConcurrencyLimiter:
    """Limits concurrent execution of async operations.

    Used to control how many agents or tool calls can run simultaneously.
    """

    def __init__(self, max_concurrent: int) -> None:
        """Initialize concurrency limiter.

        Args:
            max_concurrent: Maximum number of concurrent operations
        """
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._max = max_concurrent
        self._active = 0
        self._lock = asyncio.Lock()

    @property
    def active_count(self) -> int:
        """Number of currently active operations."""
        return self._active

    async def __aenter__(self) -> "ConcurrencyLimiter":
        await self._semaphore.acquire()
        async with self._lock:
            self._active += 1
        return self

    async def __aexit__(self, *args: Any) -> None:
        async with self._lock:
            self._active -= 1
        self._semaphore.release()

    async def run(
        self,
        func: Callable[..., Coroutine[Any, Any, T]],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """Execute function with concurrency limit.

        Args:
            func: Async function to call
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Function result
        """
        async with self:
            return await func(*args, **kwargs)


class ProviderRateLimiter:
    """Per-provider rate limiter managing both request and token limits.

    Tracks rate limits per LLM provider, handling both requests/minute
    and tokens/minute constraints.
    """

    def __init__(self) -> None:
        self._limiters: dict[str, TokenBucketRateLimiter] = {}

    def configure(
        self,
        provider_id: str,
        requests_per_minute: float = 60,
        tokens_per_minute: float = 100000,
    ) -> None:
        """Configure rate limits for a provider.

        Args:
            provider_id: Provider identifier
            requests_per_minute: Max requests per minute
            tokens_per_minute: Max tokens per minute
        """
        self._limiters[f"{provider_id}:requests"] = TokenBucketRateLimiter(
            max_rate=requests_per_minute, per_seconds=60.0
        )
        self._limiters[f"{provider_id}:tokens"] = TokenBucketRateLimiter(
            max_rate=tokens_per_minute, per_seconds=60.0
        )

    async def acquire_request(self, provider_id: str) -> None:
        """Acquire a request slot for a provider.

        Args:
            provider_id: Provider identifier
        """
        key = f"{provider_id}:requests"
        if key in self._limiters:
            await self._limiters[key].acquire()

    async def acquire_tokens(self, provider_id: str, token_count: float) -> None:
        """Acquire token capacity for a provider.

        Args:
            provider_id: Provider identifier
            token_count: Estimated token count
        """
        key = f"{provider_id}:tokens"
        if key in self._limiters:
            await self._limiters[key].acquire(token_count)
