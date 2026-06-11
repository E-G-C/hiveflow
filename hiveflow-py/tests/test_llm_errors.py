"""Tests for typed exception hierarchy and fallback behavior (T021).

Covers:
- LLMProviderError hierarchy (FR-018)
- provider_id attribute on all exception subclasses
- OpenAI SDK exception mapping (FR-018)
- Anthropic SDK exception mapping (FR-018)
- chat_stream() mid-stream error discards partial content (FR-023)
- FallbackChain transient-only cascading (FR-019)
- FallbackChain retry_on override
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hiveflow.core.fallback import FallbackChain, LLMFallbackExhaustedError
from hiveflow.plugins.llm import LLMConfig, LLMMessage
from hiveflow.plugins.llm.errors import (
    LLMAuthError,
    LLMConnectionError,
    LLMModelNotFoundError,
    LLMProviderError,
    LLMRateLimitError,
)


# ---------------------------------------------------------------------------
# A. Exception Hierarchy Tests (FR-018)
# ---------------------------------------------------------------------------


class TestExceptionHierarchy:
    """Verify the typed exception hierarchy structure."""

    def test_all_subclasses_inherit_from_base(self):
        for cls in (LLMAuthError, LLMRateLimitError, LLMModelNotFoundError, LLMConnectionError):
            assert issubclass(cls, LLMProviderError)
            assert issubclass(cls, Exception)

    def test_isinstance_checks(self):
        err = LLMAuthError("bad key", provider_id="openai")
        assert isinstance(err, LLMAuthError)
        assert isinstance(err, LLMProviderError)
        assert isinstance(err, Exception)

    def test_provider_id_carried_on_all_subclasses(self):
        for cls in (LLMAuthError, LLMRateLimitError, LLMModelNotFoundError, LLMConnectionError):
            err = cls("test msg", provider_id="test_provider")
            assert err.provider_id == "test_provider"
            assert "test msg" in str(err)

    def test_provider_id_defaults_to_none(self):
        err = LLMProviderError("base error")
        assert err.provider_id is None

    def test_auth_error_preserves_message_and_provider(self):
        err = LLMAuthError("Invalid API key", provider_id="openai")
        assert err.provider_id == "openai"
        assert "Invalid API key" in str(err)

    def test_catch_base_catches_all_subclasses(self):
        errors = [
            LLMAuthError("auth"),
            LLMRateLimitError("rate"),
            LLMModelNotFoundError("model"),
            LLMConnectionError("conn"),
        ]
        for err in errors:
            with pytest.raises(LLMProviderError):
                raise err


# ---------------------------------------------------------------------------
# B. OpenAI SDK Exception Mapping Tests (FR-018)
# ---------------------------------------------------------------------------


class TestOpenAIExceptionMapping:
    """Verify OpenAI provider maps SDK exceptions to typed hierarchy."""

    def _get_provider(self):
        from hiveflow.plugins.llm.openai_provider import OpenAIProvider
        return OpenAIProvider()

    def test_auth_error_mapping(self):
        import openai
        provider = self._get_provider()
        sdk_err = openai.AuthenticationError(
            message="Invalid API key",
            response=MagicMock(status_code=401),
            body=None,
        )
        mapped = provider._map_sdk_error(sdk_err)
        assert isinstance(mapped, LLMAuthError)
        assert mapped.provider_id == "openai"

    def test_rate_limit_mapping(self):
        import openai
        provider = self._get_provider()
        sdk_err = openai.RateLimitError(
            message="Rate limited",
            response=MagicMock(status_code=429),
            body=None,
        )
        mapped = provider._map_sdk_error(sdk_err)
        assert isinstance(mapped, LLMRateLimitError)
        assert mapped.provider_id == "openai"

    def test_not_found_mapping(self):
        import openai
        provider = self._get_provider()
        sdk_err = openai.NotFoundError(
            message="Model not found",
            response=MagicMock(status_code=404),
            body=None,
        )
        mapped = provider._map_sdk_error(sdk_err)
        assert isinstance(mapped, LLMModelNotFoundError)
        assert mapped.provider_id == "openai"

    def test_connection_error_mapping(self):
        import openai
        provider = self._get_provider()
        sdk_err = openai.APIConnectionError(request=MagicMock())
        mapped = provider._map_sdk_error(sdk_err)
        assert isinstance(mapped, LLMConnectionError)
        assert mapped.provider_id == "openai"

    def test_server_error_mapping(self):
        import openai
        provider = self._get_provider()
        sdk_err = openai.InternalServerError(
            message="Server error",
            response=MagicMock(status_code=500),
            body=None,
        )
        mapped = provider._map_sdk_error(sdk_err)
        assert isinstance(mapped, LLMConnectionError)

    def test_unrecognized_error_passes_through(self):
        provider = self._get_provider()
        err = ValueError("unknown")
        mapped = provider._map_sdk_error(err)
        assert mapped is err  # Same object, not wrapped


# ---------------------------------------------------------------------------
# C. Anthropic SDK Exception Mapping Tests (FR-018)
# ---------------------------------------------------------------------------


class TestAnthropicExceptionMapping:
    """Verify Anthropic provider maps SDK exceptions to typed hierarchy."""

    def _get_provider(self):
        from hiveflow.plugins.llm.anthropic_provider import AnthropicProvider
        return AnthropicProvider()

    def test_auth_error_mapping(self):
        import anthropic
        provider = self._get_provider()
        sdk_err = anthropic.AuthenticationError(
            message="Invalid API key",
            response=MagicMock(status_code=401),
            body=None,
        )
        mapped = provider._map_sdk_error(sdk_err)
        assert isinstance(mapped, LLMAuthError)
        assert mapped.provider_id == "anthropic"

    def test_rate_limit_mapping(self):
        import anthropic
        provider = self._get_provider()
        sdk_err = anthropic.RateLimitError(
            message="Rate limited",
            response=MagicMock(status_code=429),
            body=None,
        )
        mapped = provider._map_sdk_error(sdk_err)
        assert isinstance(mapped, LLMRateLimitError)
        assert mapped.provider_id == "anthropic"

    def test_not_found_mapping(self):
        import anthropic
        provider = self._get_provider()
        sdk_err = anthropic.NotFoundError(
            message="Not found",
            response=MagicMock(status_code=404),
            body=None,
        )
        mapped = provider._map_sdk_error(sdk_err)
        assert isinstance(mapped, LLMModelNotFoundError)
        assert mapped.provider_id == "anthropic"


# ---------------------------------------------------------------------------
# D. Streaming Error Tests (FR-023)
# ---------------------------------------------------------------------------


class TestStreamingErrors:
    """Verify chat_stream() discards partial content on mid-stream error."""

    @pytest.mark.asyncio
    async def test_openai_stream_error_raises_connection_error(self):
        """Mid-stream error raises LLMConnectionError, partial content lost."""
        import openai
        from hiveflow.plugins.llm.openai_provider import OpenAIProvider

        provider = OpenAIProvider(api_key="test-key")

        # Mock a stream that yields 2 chunks then errors
        async def failing_stream():
            chunk1 = MagicMock()
            chunk1.choices = [MagicMock()]
            chunk1.choices[0].delta.content = "Hello"
            yield chunk1
            chunk2 = MagicMock()
            chunk2.choices = [MagicMock()]
            chunk2.choices[0].delta.content = " world"
            yield chunk2
            raise openai.APIConnectionError(request=MagicMock())

        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=failing_stream())
        provider._client = mock_client

        collected = []
        with pytest.raises(LLMConnectionError) as exc_info:
            async for token in provider.chat_stream(
                [LLMMessage(role="user", content="test")],
                LLMConfig(model="gpt-4o"),
            ):
                collected.append(token)

        # Partial content was yielded before error — caller discards
        assert len(collected) == 2
        assert exc_info.value.provider_id == "openai"


# ---------------------------------------------------------------------------
# E. FallbackChain Transient-Only Tests (FR-019)
# ---------------------------------------------------------------------------


class TestFallbackChainTransientOnly:
    """Verify FallbackChain only cascades on transient errors."""

    def _make_provider(self, plugin_id: str) -> MagicMock:
        p = MagicMock()
        p.plugin_id = plugin_id
        p.supports_streaming = False
        p.supports_function_calling = False
        return p

    @pytest.mark.asyncio
    async def test_cascades_on_connection_error(self):
        p1 = self._make_provider("p1")
        p1.chat = AsyncMock(side_effect=LLMConnectionError("timeout", provider_id="p1"))
        p2 = self._make_provider("p2")
        p2.chat = AsyncMock(return_value=MagicMock(content="ok"))

        chain = FallbackChain([(p1, "m1"), (p2, "m2")])
        response = await chain.chat([], LLMConfig())
        assert response.content == "ok"
        assert p2.chat.call_count == 1

    @pytest.mark.asyncio
    async def test_cascades_on_rate_limit_error(self):
        p1 = self._make_provider("p1")
        p1.chat = AsyncMock(side_effect=LLMRateLimitError("429", provider_id="p1"))
        p2 = self._make_provider("p2")
        p2.chat = AsyncMock(return_value=MagicMock(content="ok"))

        chain = FallbackChain([(p1, "m1"), (p2, "m2")])
        response = await chain.chat([], LLMConfig())
        assert response.content == "ok"

    @pytest.mark.asyncio
    async def test_fails_immediately_on_auth_error(self):
        p1 = self._make_provider("p1")
        p1.chat = AsyncMock(side_effect=LLMAuthError("bad key", provider_id="p1"))
        p2 = self._make_provider("p2")
        p2.chat = AsyncMock(return_value=MagicMock(content="ok"))

        chain = FallbackChain([(p1, "m1"), (p2, "m2")])
        with pytest.raises(LLMAuthError):
            await chain.chat([], LLMConfig())
        # p2 was never tried
        assert p2.chat.call_count == 0

    @pytest.mark.asyncio
    async def test_fails_immediately_on_model_not_found(self):
        p1 = self._make_provider("p1")
        p1.chat = AsyncMock(side_effect=LLMModelNotFoundError("no model", provider_id="p1"))
        p2 = self._make_provider("p2")
        p2.chat = AsyncMock(return_value=MagicMock(content="ok"))

        chain = FallbackChain([(p1, "m1"), (p2, "m2")])
        with pytest.raises(LLMModelNotFoundError):
            await chain.chat([], LLMConfig())
        assert p2.chat.call_count == 0

    @pytest.mark.asyncio
    async def test_override_retry_on_catches_all(self):
        """With retry_on=(Exception,), all errors cascade."""
        p1 = self._make_provider("p1")
        p1.chat = AsyncMock(side_effect=LLMAuthError("bad key", provider_id="p1"))
        p2 = self._make_provider("p2")
        p2.chat = AsyncMock(return_value=MagicMock(content="ok"))

        chain = FallbackChain([(p1, "m1"), (p2, "m2")], retry_on=(Exception,))
        response = await chain.chat([], LLMConfig())
        assert response.content == "ok"
        assert p2.chat.call_count == 1
