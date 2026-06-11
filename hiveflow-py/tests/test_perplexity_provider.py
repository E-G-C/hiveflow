"""Tests for the Perplexity Sonar provider."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hiveflow.plugins.llm import LLMConfig, LLMMessage, LLMResponse
from hiveflow.plugins.llm.errors import LLMAuthError
from hiveflow.plugins.llm.perplexity_provider import PerplexityProvider
from hiveflow.plugins.llm.secrets import EnvVarBackend, set_secret_backend


@pytest.fixture(autouse=True)
def _restore_backend():
    yield
    set_secret_backend(EnvVarBackend())


def _make_dict_backend(secrets: dict[str, str]):
    class DictBackend:
        def get_secret(self, key: str) -> str | None:
            return secrets.get(key)

    return DictBackend()


def _mock_chat_response(content: str = "Hello!", model: str = "sonar-pro"):
    usage = MagicMock()
    usage.prompt_tokens = 10
    usage.completion_tokens = 5
    usage.total_tokens = 15

    message = MagicMock()
    message.content = content
    message.tool_calls = None

    choice = MagicMock()
    choice.message = message
    choice.finish_reason = "stop"

    response = MagicMock()
    response.choices = [choice]
    response.usage = usage
    response.model = model
    return response


class TestProperties:
    def test_plugin_id(self):
        provider = PerplexityProvider()
        assert provider.plugin_id == "perplexity"
        assert provider.provider_id == "perplexity"

    def test_capability_flags(self):
        provider = PerplexityProvider()
        assert provider.supports_streaming is True
        assert provider.supports_function_calling is False
        assert provider.supports_json_mode is True
        assert provider.supports_vision is False

    def test_available_models(self):
        provider = PerplexityProvider()
        assert provider.get_available_models() == [
            "sonar",
            "sonar-pro",
            "sonar-deep-research",
            "sonar-reasoning-pro",
        ]


class TestAuth:
    def test_api_key_from_secret_backend(self):
        mock_openai_cls = MagicMock()
        mock_openai_cls.return_value = MagicMock()
        set_secret_backend(_make_dict_backend({"PERPLEXITY_API_KEY": "pplx-test-key"}))

        provider = PerplexityProvider()
        with patch("openai.AsyncOpenAI", mock_openai_cls):
            provider._get_client()

        mock_openai_cls.assert_called_once_with(
            api_key="pplx-test-key",
            base_url="https://api.perplexity.ai",
        )

    def test_constructor_overrides_secret_backend(self):
        mock_openai_cls = MagicMock()
        mock_openai_cls.return_value = MagicMock()
        set_secret_backend(_make_dict_backend({"PERPLEXITY_API_KEY": "ignored-key"}))

        provider = PerplexityProvider(
            api_key="explicit-key",
            base_url="https://proxy.example.test/pplx/",
        )
        with patch("openai.AsyncOpenAI", mock_openai_cls):
            provider._get_client()

        mock_openai_cls.assert_called_once_with(
            api_key="explicit-key",
            base_url="https://proxy.example.test/pplx",
        )

    def test_missing_api_key_raises_auth_error(self):
        set_secret_backend(_make_dict_backend({}))
        provider = PerplexityProvider()

        with pytest.raises(LLMAuthError, match="PERPLEXITY_API_KEY"):
            provider._get_client()


class TestChat:
    @pytest.mark.asyncio
    async def test_chat_returns_llm_response(self):
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_mock_chat_response("Perplexity response")
        )

        provider = PerplexityProvider()
        provider._client = mock_client

        messages = [LLMMessage(role="user", content="Hello")]
        config = LLMConfig(model="sonar-pro", temperature=0.2, max_tokens=128)
        response = await provider.chat(messages, config)

        assert isinstance(response, LLMResponse)
        assert response.content == "Perplexity response"
        assert response.model == "sonar-pro"
        assert response.usage is not None
        assert response.usage.prompt_tokens == 10
        assert response.usage.completion_tokens == 5
