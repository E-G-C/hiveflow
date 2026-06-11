"""Concurrency tests for circuit breaker, rate limiter, and concurrency limiter.

Tests verify correctness under concurrent async load (Items 41, 42).
"""

import asyncio

import pytest

from hiveflow.core.errors import CircuitBreaker, CircuitBreakerError, CircuitState
from hiveflow.core.ratelimit import ConcurrencyLimiter, TokenBucketRateLimiter


class TestCircuitBreakerConcurrency:
    """Verify circuit breaker state transitions are safe under concurrency."""

    async def test_concurrent_calls_respect_open_state(self):
        """When the breaker opens, concurrent callers all see OPEN."""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=10.0)

        async def failing():
            raise RuntimeError("fail")

        # Trip the breaker
        for _ in range(2):
            with pytest.raises(RuntimeError):
                await cb.call(failing)

        assert cb.state == CircuitState.OPEN

        # Many concurrent calls should all fail with CircuitBreakerError
        results = await asyncio.gather(
            *[cb.call(failing) for _ in range(10)],
            return_exceptions=True,
        )
        assert all(isinstance(r, CircuitBreakerError) for r in results)

    async def test_concurrent_success_resets_breaker(self):
        """Concurrent successful calls after half-open should close the breaker."""
        cb = CircuitBreaker(
            failure_threshold=1,
            recovery_timeout=0.01,
            half_open_max_calls=1,
        )

        async def failing():
            raise RuntimeError("fail")

        async def ok():
            return "ok"

        # Trip the breaker
        with pytest.raises(RuntimeError):
            await cb.call(failing)
        assert cb.state == CircuitState.OPEN

        # Wait for recovery
        await asyncio.sleep(0.02)

        # One call should succeed and close the breaker
        result = await cb.call(ok)
        assert result == "ok"
        assert cb.state == CircuitState.CLOSED


class TestTokenBucketConcurrency:
    """Verify token bucket behaves correctly under concurrent access."""

    async def test_concurrent_acquire_respects_capacity(self):
        """Multiple concurrent acquires should not over-consume."""
        limiter = TokenBucketRateLimiter(max_rate=5, per_seconds=60.0)

        acquired = 0

        async def try_acquire():
            nonlocal acquired
            await limiter.acquire(1.0)
            acquired += 1

        # All 5 should acquire immediately (bucket starts full)
        tasks = [asyncio.create_task(try_acquire()) for _ in range(5)]
        await asyncio.gather(*tasks)
        assert acquired == 5

    async def test_acquire_exceeding_capacity_raises(self):
        """Requesting more tokens than bucket capacity raises ValueError."""
        limiter = TokenBucketRateLimiter(max_rate=10, per_seconds=60.0)
        with pytest.raises(ValueError, match="exceeds bucket capacity"):
            await limiter.acquire(20.0)


class TestConcurrencyLimiterConcurrency:
    """Verify concurrency limiter caps parallel execution."""

    async def test_max_concurrent_enforced(self):
        """Only max_concurrent tasks run in parallel."""
        limiter = ConcurrencyLimiter(max_concurrent=3)
        peak = 0
        current = 0

        async def work():
            nonlocal peak, current
            async with limiter:
                current += 1
                if current > peak:
                    peak = current
                await asyncio.sleep(0.01)
                current -= 1

        tasks = [asyncio.create_task(work()) for _ in range(10)]
        await asyncio.gather(*tasks)

        assert peak <= 3
        assert limiter.active_count == 0

    async def test_run_method_limits_concurrency(self):
        """The run() convenience method also respects limits."""
        limiter = ConcurrencyLimiter(max_concurrent=2)
        call_count = 0

        async def work():
            nonlocal call_count
            call_count += 1
            return call_count

        results = await asyncio.gather(
            *[limiter.run(work) for _ in range(5)]
        )
        assert len(results) == 5
        assert limiter.active_count == 0
