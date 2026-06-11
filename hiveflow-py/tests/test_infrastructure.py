"""Tests for LLM Fallback Chains, Streaming, and Cost Tracking."""


import pytest

from hiveflow.core.cost import CostTracker
from hiveflow.core.fallback import (
    FallbackChain,
    LLMFallbackExhaustedError,
    RetryProvider,
    build_fallback_chain,
)
from hiveflow.plugins.llm.errors import LLMConnectionError
from hiveflow.core.streaming import (
    StreamChannel,
    StreamEvent,
    StreamEventType,
)
from hiveflow.plugins.llm import LLMConfig, LLMMessage, LLMProvider, LLMResponse, TokenUsage

# --- Mock Providers ---


class SuccessProvider(LLMProvider):
    """Provider that always succeeds."""

    def __init__(self, content: str = "Success") -> None:
        self._content = content

    @property
    def plugin_id(self) -> str:
        return "success"

    @property
    def description(self) -> str:
        return "Always succeeds"

    async def chat(self, messages: list[LLMMessage], config: LLMConfig) -> LLMResponse:
        return LLMResponse(
            content=self._content,
            model=config.model,
            usage=TokenUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
        )


class FailProvider(LLMProvider):
    """Provider that always fails."""

    def __init__(self, error: Exception | None = None) -> None:
        self._error = error or LLMConnectionError("Provider failed", provider_id="fail")

    @property
    def plugin_id(self) -> str:
        return "fail"

    @property
    def description(self) -> str:
        return "Always fails"

    async def chat(self, messages: list[LLMMessage], config: LLMConfig) -> LLMResponse:
        raise self._error


class FailThenSucceedProvider(LLMProvider):
    """Provider that fails N times then succeeds."""

    def __init__(self, fail_count: int = 1) -> None:
        self._fail_count = fail_count
        self._attempts = 0

    @property
    def plugin_id(self) -> str:
        return "fail_then_succeed"

    @property
    def description(self) -> str:
        return "Fails then succeeds"

    async def chat(self, messages: list[LLMMessage], config: LLMConfig) -> LLMResponse:
        self._attempts += 1
        if self._attempts <= self._fail_count:
            raise LLMConnectionError(f"Attempt {self._attempts} failed", provider_id="fail_then_succeed")
        return LLMResponse(
            content="Success after retries",
            model=config.model,
            usage=TokenUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
        )


# --- Fallback Chain Tests ---


class TestFallbackChain:
    async def test_success_on_first_provider(self):
        chain = FallbackChain([(SuccessProvider("First"), "model-a")])
        messages = [LLMMessage(role="user", content="test")]
        # When caller's model matches the chain's first entry, use it directly
        config = LLMConfig(model="model-a")

        response = await chain.chat(messages, config)
        assert response.content == "First"
        assert response.model == "model-a"

    async def test_caller_model_tried_first(self):
        """When config.model differs from chain models, it is tried first."""
        chain = FallbackChain([(SuccessProvider("Tier"), "tier-model")])
        messages = [LLMMessage(role="user", content="test")]
        config = LLMConfig(model="agent-model")

        response = await chain.chat(messages, config)
        # The caller's model should be tried first with the primary provider
        assert response.content == "Tier"
        assert response.model == "agent-model"

    async def test_caller_model_fallback_to_tier(self):
        """When caller's model fails, fall back to tier chain."""
        fail = FailProvider()
        success = SuccessProvider("Tier")

        class DualProvider(LLMProvider):
            """Fails on one model, succeeds on another."""

            def __init__(self):
                self._calls = 0

            @property
            def plugin_id(self):
                return "dual"

            @property
            def description(self):
                return "dual"

            async def chat(self, messages, config):
                self._calls += 1
                if config.model == "bad-model":
                    raise LLMConnectionError("not found", provider_id="dual")
                return LLMResponse(
                    content="OK",
                    model=config.model,
                    usage=TokenUsage(prompt_tokens=5, completion_tokens=5, total_tokens=10),
                )

        dual = DualProvider()
        chain = FallbackChain([(dual, "good-model")])
        messages = [LLMMessage(role="user", content="test")]
        config = LLMConfig(model="bad-model")

        response = await chain.chat(messages, config)
        assert response.model == "good-model"
        assert dual._calls == 2  # first try bad-model, then good-model

    async def test_fallback_to_second_provider(self):
        chain = FallbackChain([
            (FailProvider(), "model-a"),
            (SuccessProvider("Fallback"), "model-b"),
        ])
        messages = [LLMMessage(role="user", content="test")]
        config = LLMConfig()

        response = await chain.chat(messages, config)
        assert response.content == "Fallback"
        assert response.model == "model-b"

    async def test_all_providers_fail(self):
        chain = FallbackChain([
            (FailProvider(LLMConnectionError("err1", provider_id="a")), "model-a"),
            (FailProvider(LLMConnectionError("err2", provider_id="b")), "model-b"),
        ])
        messages = [LLMMessage(role="user", content="test")]
        config = LLMConfig()

        with pytest.raises(LLMFallbackExhaustedError) as exc_info:
            await chain.chat(messages, config)

        assert len(exc_info.value.errors) == 2
        assert "LLM provider(s) failed" in str(exc_info.value)

    async def test_empty_chain_raises(self):
        with pytest.raises(ValueError, match="at least one provider"):
            FallbackChain([])

    def test_description(self):
        chain = FallbackChain([
            (SuccessProvider(), "m1"),
            (SuccessProvider(), "m2"),
        ])
        assert "success -> success" in chain.description

    def test_supports_streaming(self):
        chain = FallbackChain([(SuccessProvider(), "m1")])
        assert chain.supports_streaming is False


class TestRetryProvider:
    async def test_success_no_retries(self):
        provider = RetryProvider(SuccessProvider(), max_retries=3)
        messages = [LLMMessage(role="user", content="test")]
        config = LLMConfig(model="test")

        response = await provider.chat(messages, config)
        assert response.content == "Success"

    async def test_retry_then_succeed(self):
        inner = FailThenSucceedProvider(fail_count=2)
        provider = RetryProvider(inner, max_retries=3)
        messages = [LLMMessage(role="user", content="test")]
        config = LLMConfig(model="test")

        response = await provider.chat(messages, config)
        assert response.content == "Success after retries"

    async def test_all_retries_exhausted(self):
        inner = FailProvider(RuntimeError("persistent failure"))
        provider = RetryProvider(inner, max_retries=2)
        messages = [LLMMessage(role="user", content="test")]
        config = LLMConfig(model="test")

        with pytest.raises(RuntimeError, match="persistent failure"):
            await provider.chat(messages, config)

    def test_plugin_id(self):
        inner = SuccessProvider()
        provider = RetryProvider(inner)
        assert provider.plugin_id == "retry_success"


class TestBuildFallbackChain:
    async def test_convenience_builder(self):
        chain = build_fallback_chain([
            (FailProvider(), "model-a"),
            (SuccessProvider("ok"), "model-b"),
        ], max_retries_per_provider=1)

        messages = [LLMMessage(role="user", content="test")]
        config = LLMConfig()

        response = await chain.chat(messages, config)
        assert response.content == "ok"


# --- Streaming Tests ---


class TestStreamChannel:
    async def test_publish_and_consume(self):
        channel = StreamChannel()
        consumer = channel.subscribe()

        event = StreamEvent(event_type=StreamEventType.TOKEN, token="hello")
        await channel.publish(event)
        await channel.close()

        events = []
        async for e in consumer:
            events.append(e)

        assert len(events) == 1
        assert events[0].token == "hello"

    async def test_multiple_subscribers(self):
        channel = StreamChannel()
        consumer1 = channel.subscribe()
        consumer2 = channel.subscribe()

        await channel.publish(StreamEvent(
            event_type=StreamEventType.TOKEN, token="x"
        ))
        await channel.close()

        events1 = [e async for e in consumer1]
        events2 = [e async for e in consumer2]

        assert len(events1) == 1
        assert len(events2) == 1

    async def test_close_signals_end(self):
        channel = StreamChannel()
        consumer = channel.subscribe()

        await channel.close()
        assert channel.is_closed

        events = [e async for e in consumer]
        assert len(events) == 0

    async def test_unsubscribe(self):
        channel = StreamChannel()
        consumer = channel.subscribe()
        await consumer.close()

        # Should not raise even with no subscribers
        await channel.publish(StreamEvent(event_type=StreamEventType.TOKEN, token="x"))

    async def test_buffer_overflow_drops_events(self):
        channel = StreamChannel(max_buffer=2)
        consumer = channel.subscribe()

        # Publish 3 events to a buffer of 2
        await channel.publish(StreamEvent(event_type=StreamEventType.TOKEN, token="1"))
        await channel.publish(StreamEvent(event_type=StreamEventType.TOKEN, token="2"))
        await channel.publish(StreamEvent(event_type=StreamEventType.TOKEN, token="3"))
        await channel.close()

        events = [e async for e in consumer]
        # Buffer held 2, 3rd dropped. Close drains one to fit sentinel.
        # Consumer gets 1 event then sentinel (end of stream).
        assert len(events) == 1


class TestStreamEvent:
    def test_to_dict_basic(self):
        event = StreamEvent(event_type=StreamEventType.TOKEN, token="hi")
        d = event.to_dict()
        assert d["type"] == "token"
        assert d["token"] == "hi"
        assert "agent_id" not in d

    def test_to_dict_with_agent(self):
        event = StreamEvent(
            event_type=StreamEventType.AGENT_START,
            agent_id="researcher",
            data={"step": 1},
        )
        d = event.to_dict()
        assert d["agent_id"] == "researcher"
        assert d["data"]["step"] == 1

    def test_to_dict_minimal(self):
        event = StreamEvent(event_type=StreamEventType.ERROR)
        d = event.to_dict()
        assert d["type"] == "error"
        assert "timestamp" in d  # Added by FR-020


# --- Cost Tracking Tests ---


class TestCostTracker:
    def test_record_and_total(self):
        tracker = CostTracker()
        tracker.record("agent1", "gpt-4o", prompt_tokens=1000, completion_tokens=500)

        assert tracker.total_tokens == 1500
        assert tracker.total_cost > 0

    def test_estimate_cost_gpt4o(self):
        tracker = CostTracker()
        record = tracker.record(
            "agent1", "gpt-4o",
            prompt_tokens=1_000_000, completion_tokens=1_000_000,
        )
        # gpt-4o: $2.50/1M input + $10.00/1M output = $12.50
        assert abs(record.estimated_cost_usd - 12.50) < 0.01

    def test_estimate_cost_unknown_model(self):
        tracker = CostTracker()
        record = tracker.record("agent1", "unknown-model", prompt_tokens=100, completion_tokens=50)
        assert record.estimated_cost_usd == 0.0

    def test_custom_pricing(self):
        tracker = CostTracker(custom_pricing={"my-model": (1.0, 2.0)})
        record = tracker.record(
            "agent1", "my-model",
            prompt_tokens=1_000_000, completion_tokens=1_000_000,
        )
        assert abs(record.estimated_cost_usd - 3.0) < 0.01

    def test_get_report(self):
        tracker = CostTracker()
        tracker.record("agent1", "gpt-4o", prompt_tokens=100, completion_tokens=50)
        tracker.record("agent2", "gpt-4o-mini", prompt_tokens=200, completion_tokens=100)
        tracker.record("agent1", "gpt-4o", prompt_tokens=300, completion_tokens=150)

        report = tracker.get_report()

        assert report.total_prompt_tokens == 600
        assert report.total_completion_tokens == 300
        assert report.total_tokens == 900
        assert len(report.records) == 3
        assert "agent1" in report.agent_summaries
        assert "agent2" in report.agent_summaries
        assert report.agent_summaries["agent1"].call_count == 2
        assert report.agent_summaries["agent2"].call_count == 1
        assert "gpt-4o" in report.model_breakdown
        assert "gpt-4o-mini" in report.model_breakdown

    def test_reset(self):
        tracker = CostTracker()
        tracker.record("agent1", "gpt-4o", prompt_tokens=100, completion_tokens=50)
        assert tracker.total_tokens > 0

        tracker.reset()
        assert tracker.total_tokens == 0
        assert tracker.total_cost == 0.0

    def test_auto_total_tokens(self):
        tracker = CostTracker()
        record = tracker.record("a", "gpt-4o", prompt_tokens=100, completion_tokens=50)
        assert record.total_tokens == 150

    def test_explicit_total_tokens(self):
        tracker = CostTracker()
        record = tracker.record(
            "a", "gpt-4o",
            prompt_tokens=100, completion_tokens=50, total_tokens=200,
        )
        assert record.total_tokens == 200
