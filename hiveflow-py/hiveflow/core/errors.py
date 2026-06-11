"""Error Isolation Patterns - Prevent cascading failures in multi-agent workflows.

Provides circuit breakers, timeouts, and bulkhead patterns to isolate
failures in individual agents from bringing down the entire workflow.
"""

import asyncio
import time
from collections.abc import Callable, Coroutine
from enum import StrEnum
from typing import Any, TypeVar

import structlog

logger = structlog.get_logger()

T = TypeVar("T")


class CircuitState(StrEnum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, reject calls
    HALF_OPEN = "half_open"  # Testing if recovered


class CircuitBreakerError(Exception):
    """Raised when circuit breaker is open and call is rejected."""


class CircuitBreaker:
    """Circuit breaker pattern for LLM/tool calls.

    Tracks failure rate and "opens" the circuit when failures exceed threshold,
    preventing further calls until a cooldown period has elapsed.

    Usage:
        breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=30.0)
        result = await breaker.call(some_async_function, arg1, arg2)
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max_calls: int = 1,
    ) -> None:
        """Initialize circuit breaker.

        Args:
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Seconds to wait before testing recovery
            half_open_max_calls: Max calls allowed in half-open state
        """
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._half_open_max_calls = half_open_max_calls

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._half_open_calls = 0
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        """Current circuit breaker state (read-only snapshot)."""
        return self._state

    async def call(
        self,
        func: Callable[..., Coroutine[Any, Any, T]],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """Execute a function through the circuit breaker.

        Args:
            func: Async function to call
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Function result

        Raises:
            CircuitBreakerError: If circuit is open
        """
        async with self._lock:
            # Transition OPEN -> HALF_OPEN if recovery timeout has elapsed
            if (
                self._state == CircuitState.OPEN
                and time.monotonic() - self._last_failure_time >= self._recovery_timeout
            ):
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0

            current_state = self._state

            if current_state == CircuitState.OPEN:
                raise CircuitBreakerError(
                    f"Circuit breaker is open (failures={self._failure_count}). "
                    f"Recovery in {self._recovery_timeout - (time.monotonic() - self._last_failure_time):.1f}s"
                )

            if current_state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self._half_open_max_calls:
                    raise CircuitBreakerError(
                        "Circuit breaker is half-open, max test calls reached"
                    )
                self._half_open_calls += 1

        try:
            result = await func(*args, **kwargs)
            async with self._lock:
                self._on_success()
            return result
        except Exception:
            async with self._lock:
                self._on_failure()
            raise

    def _on_success(self) -> None:
        """Handle successful call."""
        self._failure_count = 0
        self._state = CircuitState.CLOSED

    def _on_failure(self) -> None:
        """Handle failed call."""
        self._failure_count += 1
        self._last_failure_time = time.monotonic()

        if self._failure_count >= self._failure_threshold:
            self._state = CircuitState.OPEN
            logger.warning(
                "Circuit breaker opened after %d failures",
                self._failure_count,
            )

    def reset(self) -> None:
        """Manually reset circuit breaker to closed state."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._half_open_calls = 0


async def with_timeout(
    coro: Coroutine[Any, Any, T],
    timeout_seconds: float,
    default: T | None = None,
) -> T | None:
    """Execute a coroutine with a timeout.

    Args:
        coro: Coroutine to execute
        timeout_seconds: Maximum execution time in seconds
        default: Value to return on timeout (None if not specified)

    Returns:
        Coroutine result or default on timeout
    """
    try:
        return await asyncio.wait_for(coro, timeout=timeout_seconds)
    except TimeoutError:
        logger.warning("Operation timed out after %.1fs", timeout_seconds)
        return default


class BulkheadSemaphore:
    """Bulkhead pattern limiting concurrent operations.

    Prevents a single agent or tool from consuming all available resources
    by limiting the number of concurrent calls.
    """

    def __init__(self, max_concurrent: int = 10) -> None:
        """Initialize bulkhead.

        Args:
            max_concurrent: Maximum concurrent operations
        """
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._max_concurrent = max_concurrent
        self._active = 0

    @property
    def active_count(self) -> int:
        """Number of currently active operations."""
        return self._active

    @property
    def available(self) -> int:
        """Number of available slots."""
        return self._max_concurrent - self._active

    async def acquire(self) -> None:
        """Acquire a bulkhead slot."""
        await self._semaphore.acquire()
        self._active += 1

    def release(self) -> None:
        """Release a bulkhead slot."""
        self._active -= 1
        self._semaphore.release()

    async def call(
        self,
        func: Callable[..., Coroutine[Any, Any, T]],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """Execute a function within the bulkhead.

        Args:
            func: Async function to call
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Function result
        """
        await self.acquire()
        try:
            return await func(*args, **kwargs)
        finally:
            self.release()
