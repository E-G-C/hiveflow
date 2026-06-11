"""Tests for Azure OpenAI provider (T012).

Covers:
- plugin_id and capability flags
- API key auth path (mocked SDK)
- RBAC auth path (mocked azure-identity)
- No-credentials error message quality
- chat() returns LLMResponse (mocked SDK)
- chat_stream() yields tokens (mocked SDK)
- structlog event emission
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hiveflow.plugins.llm import LLMConfig, LLMMessage, LLMResponse
from hiveflow.plugins.llm.azure_provider import AzureOpenAIProvider
from hiveflow.plugins.llm.errors import LLMAuthError
from hiveflow.plugins.llm.secrets import EnvVarBackend, set_secret_backend


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _restore_backend():
    yield
    set_secret_backend(EnvVarBackend())


def _make_dict_backend(secrets: dict[str, str]):
    """Return a DictBackend that resolves from the given dict."""
    class DictBackend:
        def get_secret(self, key: str) -> str | None:
            return secrets.get(key)
    return DictBackend()


def _mock_chat_response(content: str = "Hello!", model: str = "gpt-4o-eastus"):
    """Build a mock response matching OpenAI SDK structure."""
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


def _mock_stream_chunks(texts: list[str]):
    """Build an async iterable of mock stream chunks."""
    chunks = []
    for text in texts:
        delta = MagicMock()
        delta.content = text
        choice = MagicMock()
        choice.delta = delta
        chunk = MagicMock()
        chunk.choices = [choice]
        chunks.append(chunk)

    async def async_iter():
        for c in chunks:
            yield c

    return async_iter()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestProperties:
    """Basic provider properties."""

    def test_plugin_id(self):
        p = AzureOpenAIProvider()
        assert p.plugin_id == "azure"
        assert p.provider_id == "azure"

    def test_description(self):
        p = AzureOpenAIProvider()
        assert "Azure" in p.description
        assert "RBAC" in p.description

    def test_capability_flags(self):
        p = AzureOpenAIProvider()
        assert p.supports_streaming is True
        assert p.supports_function_calling is True
        assert p.supports_json_mode is True
        assert p.supports_vision is True

    def test_available_models_empty(self):
        """Azure uses deployment names, so available models is empty."""
        p = AzureOpenAIProvider()
        assert p.get_available_models() == []


class TestAuthApiKey:
    """API key authentication path."""

    def test_api_key_from_secret_backend(self):
        mock_azure_cls = MagicMock()
        mock_azure_cls.return_value = MagicMock()
        set_secret_backend(_make_dict_backend({
            "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com",
            "AZURE_OPENAI_API_KEY": "test-key-123",
        }))
        p = AzureOpenAIProvider()
        with patch("openai.AsyncAzureOpenAI", mock_azure_cls):
            p._get_client()
        mock_azure_cls.assert_called_once_with(
            azure_endpoint="https://test.openai.azure.com",
            api_key="test-key-123",
            api_version="2024-10-21",
        )

    def test_api_key_from_constructor(self):
        mock_azure_cls = MagicMock()
        mock_azure_cls.return_value = MagicMock()
        set_secret_backend(_make_dict_backend({
            "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com/",
        }))
        p = AzureOpenAIProvider(api_key="explicit-key")
        with patch("openai.AsyncAzureOpenAI", mock_azure_cls):
            p._get_client()
        call_kwargs = mock_azure_cls.call_args[1]
        assert call_kwargs["api_key"] == "explicit-key"

    def test_custom_api_version(self):
        mock_azure_cls = MagicMock()
        mock_azure_cls.return_value = MagicMock()
        set_secret_backend(_make_dict_backend({
            "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com/",
            "AZURE_OPENAI_API_KEY": "key",
            "OPENAI_API_VERSION": "2025-01-01",
        }))
        p = AzureOpenAIProvider()
        with patch("openai.AsyncAzureOpenAI", mock_azure_cls):
            p._get_client()
        call_kwargs = mock_azure_cls.call_args[1]
        assert call_kwargs["api_version"] == "2025-01-01"


try:
    import azure.identity  # noqa: F401
    _has_azure_identity = True
except ImportError:
    _has_azure_identity = False

_skip_no_azure = pytest.mark.skipif(not _has_azure_identity, reason="azure-identity not installed")


@_skip_no_azure
class TestAuthRBAC:
    """RBAC authentication path."""

    def test_rbac_path_uses_token_provider(self):
        mock_azure_cls = MagicMock()
        mock_azure_cls.return_value = MagicMock()
        mock_credential = MagicMock()
        mock_token_provider = MagicMock()

        set_secret_backend(_make_dict_backend({
            "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com/",
        }))
        p = AzureOpenAIProvider()

        with patch("openai.AsyncAzureOpenAI", mock_azure_cls), \
             patch("azure.identity.DefaultAzureCredential", return_value=mock_credential), \
             patch("azure.identity.get_bearer_token_provider", return_value=mock_token_provider):
            p._get_client()

        mock_azure_cls.assert_called_once_with(
            azure_endpoint="https://test.openai.azure.com",
            azure_ad_token_provider=mock_token_provider,
            api_version="2024-10-21",
        )


class TestAuthErrors:
    """Error messages for missing credentials."""

    def test_no_endpoint_raises_value_error(self):
        set_secret_backend(_make_dict_backend({}))
        p = AzureOpenAIProvider()
        with pytest.raises(LLMAuthError, match="AZURE_OPENAI_ENDPOINT"):
            p._get_client()

    def test_deployment_path_stripped_from_endpoint(self):
        """If user pastes the full deployment URL, strip the path automatically."""
        mock_azure_cls = MagicMock()
        mock_azure_cls.return_value = MagicMock()
        set_secret_backend(_make_dict_backend({
            "AZURE_OPENAI_ENDPOINT": "https://my-resource.openai.azure.com/openai/deployments/gpt-4o-mini",
            "AZURE_OPENAI_API_KEY": "key",
        }))
        p = AzureOpenAIProvider()
        with patch("openai.AsyncAzureOpenAI", mock_azure_cls):
            p._get_client()
        call_kwargs = mock_azure_cls.call_args[1]
        assert call_kwargs["azure_endpoint"] == "https://my-resource.openai.azure.com"

    def test_deployment_path_with_trailing_slash_stripped(self):
        mock_azure_cls = MagicMock()
        mock_azure_cls.return_value = MagicMock()
        set_secret_backend(_make_dict_backend({
            "AZURE_OPENAI_ENDPOINT": "https://my-resource.openai.azure.com/openai/deployments/gpt-4o/",
            "AZURE_OPENAI_API_KEY": "key",
        }))
        p = AzureOpenAIProvider()
        with patch("openai.AsyncAzureOpenAI", mock_azure_cls):
            p._get_client()
        call_kwargs = mock_azure_cls.call_args[1]
        assert call_kwargs["azure_endpoint"] == "https://my-resource.openai.azure.com"

    @_skip_no_azure
    def test_no_credentials_error_mentions_rbac_role(self):
        """When RBAC fails, error should mention Cognitive Services OpenAI User."""
        set_secret_backend(_make_dict_backend({
            "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com/",
        }))
        p = AzureOpenAIProvider()

        with patch(
            "azure.identity.DefaultAzureCredential",
            side_effect=Exception("No credentials"),
        ):
            with pytest.raises(LLMAuthError, match="Cognitive Services OpenAI User"):
                p._get_client()

    @_skip_no_azure
    def test_no_credentials_error_mentions_api_key(self):
        set_secret_backend(_make_dict_backend({
            "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com/",
        }))
        p = AzureOpenAIProvider()

        with patch(
            "azure.identity.DefaultAzureCredential",
            side_effect=Exception("No credentials"),
        ):
            with pytest.raises(LLMAuthError, match="AZURE_OPENAI_API_KEY"):
                p._get_client()


class TestChat:
    """chat() with mocked SDK."""

    @pytest.mark.asyncio
    async def test_chat_returns_llm_response(self):
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_mock_chat_response("Test response")
        )

        p = AzureOpenAIProvider()
        p._client = mock_client

        messages = [LLMMessage(role="user", content="Hello")]
        config = LLMConfig(model="gpt-4o-eastus", temperature=0.5, max_tokens=100)
        response = await p.chat(messages, config)

        assert isinstance(response, LLMResponse)
        assert response.content == "Test response"
        assert response.model == "gpt-4o-eastus"
        assert response.usage is not None
        assert response.usage.prompt_tokens == 10
        assert response.usage.completion_tokens == 5
        assert response.finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_chat_passes_tools(self):
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_mock_chat_response()
        )

        p = AzureOpenAIProvider()
        p._client = mock_client

        tools = [{"type": "function", "function": {"name": "test_fn"}}]
        messages = [LLMMessage(role="user", content="Hello")]
        config = LLMConfig(model="gpt-4o", tools=tools)
        await p.chat(messages, config)

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["tools"] == tools

    @pytest.mark.asyncio
    async def test_chat_error_logged(self):
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            side_effect=RuntimeError("API error")
        )

        p = AzureOpenAIProvider()
        p._client = mock_client

        messages = [LLMMessage(role="user", content="Hello")]
        config = LLMConfig(model="gpt-4o-eastus")

        with pytest.raises(RuntimeError, match="API error"):
            await p.chat(messages, config)


class TestChatStream:
    """chat_stream() with mocked SDK."""

    @pytest.mark.asyncio
    async def test_stream_yields_tokens(self):
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_mock_stream_chunks(["Hello", " ", "world"])
        )

        p = AzureOpenAIProvider()
        p._client = mock_client

        messages = [LLMMessage(role="user", content="Hi")]
        config = LLMConfig(model="gpt-4o-eastus")

        tokens = []
        async for token in p.chat_stream(messages, config):
            tokens.append(token)
        assert tokens == ["Hello", " ", "world"]


class TestStructlogEmission:
    """Verify structlog events are emitted without errors."""

    @pytest.mark.asyncio
    async def test_chat_completes_with_logging(self):
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_mock_chat_response()
        )

        p = AzureOpenAIProvider()
        p._client = mock_client

        messages = [LLMMessage(role="user", content="Hello")]
        config = LLMConfig(model="gpt-4o-eastus")
        response = await p.chat(messages, config)
        # Should complete without error — structlog events emit successfully
        assert response.content == "Hello!"
