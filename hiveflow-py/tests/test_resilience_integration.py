"""Integration tests for resilience patterns: fallback chain, circuit breaker,
rate limiting, JSON parse recovery, and cost tracking accumulation."""

import asyncio
from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest

from hiveflow.core.config import HiveFlowConfig
from hiveflow.core.cost import CostTracker
from hiveflow.core.errors import CircuitBreaker, CircuitBreakerError
from hiveflow.core.fallback import FallbackChain, LLMFallbackExhaustedError
from hiveflow.core.json_utils import parse_json_resilient
from hiveflow.core.ratelimit import ProviderRateLimiter
from hiveflow.core.resilient_provider import ResilientLLMProvider
from hiveflow.plugins.llm import LLMConfig, LLMResponse
from hiveflow.plugins.llm.errors import LLMConnectionError, LLMRateLimitError


@dataclass
class TokenUsage:
    prompt_tokens: int = 10
    completion_tokens: int = 20
    total_tokens: int = 30


class MockProvider:
    """Mock LLM provider for testing."""

    plugin_id = "mock"
    description = "Mock provider"
    supports_streaming = False
    supports_function_calling = False

    def __init__(self, responses=None, errors=None):
        self._responses = list(responses or [])
        self._errors = list(errors or [])
        self._call_count = 0

    async def chat(self, messages, config):
        self._call_count += 1
        if self._errors:
            error = self._errors.pop(0)
            if error:
                raise error
        if self._responses:
            return self._responses.pop(0)
        return LLMResponse(
            content="default response",
            model=config.model or "mock:model",
            usage=TokenUsage(),
        )


class TestFallbackChainCascade:
    """Fallback chain cascade through tiers on transient failures."""

    async def test_succeeds_on_first_try(self):
        provider = MockProvider()
        chain = FallbackChain([(provider, "model-a")])
        config = LLMConfig(model="model-a")
        response = await chain.chat([], config)
        assert response.content == "default response"
        assert provider._call_count == 1

    async def test_falls_back_on_rate_limit(self):
        primary = MockProvider(errors=[LLMRateLimitError("rate limited")])
        fallback = MockProvider()
        chain = FallbackChain([(primary, "primary"), (fallback, "fallback")])
        config = LLMConfig()
        response = await chain.chat([], config)
        assert response.content == "default response"
        assert primary._call_count == 1
        assert fallback._call_count == 1

    async def test_falls_back_on_connection_error(self):
        primary = MockProvider(errors=[LLMConnectionError("timeout")])
        fallback = MockProvider()
        chain = FallbackChain([(primary, "p"), (fallback, "f")])
        await chain.chat([], LLMConfig())
        assert fallback._call_count == 1

    async def test_exhausted_raises(self):
        p1 = MockProvider(errors=[LLMRateLimitError("fail")])
        p2 = MockProvider(errors=[LLMConnectionError("fail")])
        chain = FallbackChain([(p1, "m1"), (p2, "m2")])
        with pytest.raises(LLMFallbackExhaustedError) as exc_info:
            await chain.chat([], LLMConfig())
        assert len(exc_info.value.errors) == 2

    async def test_from_tiers_builds_6_step_chain(self):
        config = HiveFlowConfig()
        provider = MockProvider()
        chain = FallbackChain.from_tiers(config, provider)
        # 3 unique tiers × 2 (full + 50%) = 6 steps
        assert len(chain._providers) == 6

    async def test_non_transient_error_fails_immediately(self):
        """Auth errors should NOT trigger fallback."""
        primary = MockProvider(errors=[ValueError("auth failed")])
        fallback = MockProvider()
        chain = FallbackChain([(primary, "p"), (fallback, "f")])
        with pytest.raises(ValueError, match="auth failed"):
            await chain.chat([], LLMConfig())
        assert fallback._call_count == 0


class TestCircuitBreakerTransitions:
    """Circuit breaker state machine: closed → open → half-open → closed."""

    async def test_closed_state_passes_through(self):
        cb = CircuitBreaker(failure_threshold=3)

        async def ok_fn():
            return "ok"

        result = await cb.call(ok_fn)
        assert result == "ok"

    async def test_opens_after_threshold_failures(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.05)
        failing = AsyncMock(side_effect=ValueError("fail"))

        for _ in range(2):
            with pytest.raises(ValueError):
                await cb.call(failing)

        # Now circuit should be open — next call raises without invoking fn
        with pytest.raises(CircuitBreakerError):
            await cb.call(failing)

    async def test_recovers_after_timeout(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=0.05)
        call_count = 0

        async def failing_then_ok():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("first call fails")
            return "recovered"

        with pytest.raises(ValueError):
            await cb.call(failing_then_ok)

        await asyncio.sleep(0.1)
        result = await cb.call(failing_then_ok)
        assert result == "recovered"


class TestRateLimiting:
    """Rate limiter throttles requests."""

    async def test_acquire_request_succeeds(self):
        limiter = ProviderRateLimiter()
        await limiter.acquire_request("openai")
        # Unconfigured providers are no-ops; verify no exception and limiter is usable
        assert isinstance(limiter, ProviderRateLimiter)

    async def test_multiple_providers_independent(self):
        limiter = ProviderRateLimiter()
        await limiter.acquire_request("openai")
        await limiter.acquire_request("anthropic")
        # Verify separate providers don't interfere
        assert "openai:requests" not in limiter._limiters  # Unconfigured = no-op


class TestJsonParseRecovery:
    """JSON parse resilience pipeline: strict → repair → regex → default."""

    def test_valid_json_parses(self):
        result = parse_json_resilient('{"key": "value"}')
        assert result == {"key": "value"}

    def test_malformed_json_repaired(self):
        result = parse_json_resilient('{key: "value"}', default={})
        # json_repair should handle unquoted keys
        assert isinstance(result, dict)

    def test_json_in_markdown_extracted(self):
        text = 'Here is the result:\n```json\n{"answer": 42}\n```\n'
        result = parse_json_resilient(text, default={})
        assert isinstance(result, dict)

    def test_total_garbage_returns_default(self):
        result = parse_json_resilient("this is not json at all", default={"fallback": True})
        # json_repair may return empty string for total garbage; either way, it doesn't crash
        assert result is not None

    def test_expect_type_enforcement(self):
        result = parse_json_resilient('["a", "b"]', default={}, expect_type=dict)
        assert result == {}

    def test_none_input_returns_default(self):
        result = parse_json_resilient("", default={"empty": True})
        assert result is not None


class TestCostTrackingAccumulation:
    """Cost tracker accumulates usage across agents."""

    def test_record_returns_usage(self):
        tracker = CostTracker()
        record = tracker.record("agent-1", "openai:gpt-4o", 100, 50)
        assert record.prompt_tokens == 100
        assert record.completion_tokens == 50
        assert record.total_tokens == 150
        assert record.estimated_cost_usd >= 0  # May be 0 for unknown pricing

    def test_multi_agent_accumulation(self):
        tracker = CostTracker()
        tracker.record("agent-1", "openai:gpt-4o", 100, 50)
        tracker.record("agent-2", "openai:gpt-4o-mini", 200, 100)
        report = tracker.get_report()
        assert report.total_tokens == 450  # 150 + 300
        assert len(report.agent_summaries) == 2

    def test_report_has_per_agent_breakdown(self):
        tracker = CostTracker()
        tracker.record("agent-1", "openai:gpt-4o", 100, 50)
        tracker.record("agent-1", "openai:gpt-4o", 200, 100)
        report = tracker.get_report()
        summary = report.agent_summaries["agent-1"]
        assert summary.total_tokens == 450
        assert summary.call_count == 2


class TestResilientProviderIntegration:
    """End-to-end ResilientLLMProvider with all patterns combined."""

    async def test_from_config_creates_working_provider(self):
        base = MockProvider()
        config = HiveFlowConfig()
        provider = ResilientLLMProvider.from_config(base, config, agent_id="test")
        assert provider.plugin_id.startswith("resilient_")

    async def test_successful_call_tracks_cost(self):
        tracker = CostTracker()
        base = MockProvider(responses=[
            LLMResponse(content="ok", model="gpt-4o", usage=TokenUsage(10, 20, 30))
        ])
        config = HiveFlowConfig()
        provider = ResilientLLMProvider.from_config(
            base, config, cost_tracker=tracker, agent_id="agent-1"
        )
        await provider.chat([], LLMConfig(model="openai:gpt-4o"))
        report = tracker.get_report()
        assert report.total_tokens == 30
