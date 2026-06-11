"""Tests for _retry_transient exponential backoff in WorkflowEngine (T011)."""

import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from hiveflow.core.workflow import WorkflowEngine, WorkflowStep


def _make_engine() -> WorkflowEngine:
    """Create a minimal WorkflowEngine for testing."""
    steps = [WorkflowStep(agent="test", step_type="sequential")]
    return WorkflowEngine(steps)


def _http_status_error(status_code: int) -> httpx.HTTPStatusError:
    """Create an httpx.HTTPStatusError with the given status code."""
    request = httpx.Request("POST", "https://api.example.com/v1/chat")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError(
        f"{status_code} Error", request=request, response=response
    )


class TestRetryTransient:
    """Tests for WorkflowEngine._retry_transient."""

    @pytest.mark.asyncio
    async def test_success_after_two_429s(self):
        """Mock 429 twice then succeed — verify success."""
        engine = _make_engine()
        call_count = 0

        async def flaky_func(state):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise _http_status_error(429)
            return {**state, "done": True}

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await engine._retry_transient(flaky_func, {"task": "test"})

        assert result["done"] is True
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_persistent_5xx_raises_after_max_retries(self):
        """Mock persistent 5xx — verify raises after 3 retries."""
        engine = _make_engine()
        call_count = 0

        async def always_5xx(state):
            nonlocal call_count
            call_count += 1
            raise _http_status_error(500)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(httpx.HTTPStatusError):
                await engine._retry_transient(always_5xx, {"task": "test"})

        # Initial attempt + 3 retries = 4 calls
        assert call_count == 4

    @pytest.mark.asyncio
    async def test_connection_error_retried(self):
        """Mock ConnectionError — verify retried and eventually succeeds."""
        engine = _make_engine()
        call_count = 0

        async def conn_error_then_ok(state):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("Connection refused")
            return {**state, "connected": True}

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await engine._retry_transient(conn_error_then_ok, {"task": "test"})

        assert result["connected"] is True
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_timeout_error_retried(self):
        """TimeoutError should be retried as transient."""
        engine = _make_engine()
        call_count = 0

        async def timeout_then_ok(state):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise TimeoutError("Request timed out")
            return {**state, "ok": True}

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await engine._retry_transient(timeout_then_ok, {"task": "test"})

        assert result["ok"] is True
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_asyncio_timeout_retried(self):
        """asyncio.TimeoutError should be retried as transient."""
        engine = _make_engine()
        call_count = 0

        async def async_timeout_then_ok(state):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise asyncio.TimeoutError()
            return {**state, "ok": True}

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await engine._retry_transient(async_timeout_then_ok, {"task": "test"})

        assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_non_transient_error_not_retried(self):
        """Non-transient errors (e.g. ValueError) should raise immediately."""
        engine = _make_engine()
        call_count = 0

        async def value_error(state):
            nonlocal call_count
            call_count += 1
            raise ValueError("Bad input")

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(ValueError, match="Bad input"):
                await engine._retry_transient(value_error, {"task": "test"})

        assert call_count == 1  # No retry for non-transient

    @pytest.mark.asyncio
    async def test_http_400_not_retried(self):
        """HTTP 400 is not transient — should not be retried."""
        engine = _make_engine()
        call_count = 0

        async def bad_request(state):
            nonlocal call_count
            call_count += 1
            raise _http_status_error(400)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(httpx.HTTPStatusError):
                await engine._retry_transient(bad_request, {"task": "test"})

        assert call_count == 1

    @pytest.mark.asyncio
    async def test_exponential_delay_timing(self):
        """Verify delays follow exponential backoff pattern."""
        engine = _make_engine()
        sleep_calls: list[float] = []

        async def mock_sleep(delay: float) -> None:
            sleep_calls.append(delay)

        call_count = 0

        async def always_fail(state):
            nonlocal call_count
            call_count += 1
            raise _http_status_error(503)

        with patch("asyncio.sleep", side_effect=mock_sleep):
            with pytest.raises(httpx.HTTPStatusError):
                await engine._retry_transient(
                    always_fail, {"task": "test"},
                    base_delay=1.0, backoff_factor=2.0, max_retries=3,
                )

        # 3 retries = 3 sleep calls with delays: 1.0, 2.0, 4.0
        assert len(sleep_calls) == 3
        assert sleep_calls[0] == pytest.approx(1.0)
        assert sleep_calls[1] == pytest.approx(2.0)
        assert sleep_calls[2] == pytest.approx(4.0)

    @pytest.mark.asyncio
    async def test_custom_max_retries(self):
        """Custom max_retries should be honored."""
        engine = _make_engine()
        call_count = 0

        async def always_fail(state):
            nonlocal call_count
            call_count += 1
            raise _http_status_error(429)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(httpx.HTTPStatusError):
                await engine._retry_transient(
                    always_fail, {"task": "test"}, max_retries=5,
                )

        assert call_count == 6  # 1 initial + 5 retries
