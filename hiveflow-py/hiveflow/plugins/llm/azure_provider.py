"""Azure OpenAI LLM Provider - Enterprise RBAC + API key authentication.

Supports Azure OpenAI Service deployments with two authentication paths:
1. Microsoft Entra ID RBAC via DefaultAzureCredential (preferred)
2. API key fallback via AZURE_OPENAI_API_KEY

Requires the ``llm-azure`` extras: ``uv add hiveflow[llm-azure]``

See: R1, R2, R4, data-model.md AzureOpenAIProvider section.
"""

import re
import time
from collections.abc import AsyncIterator
from typing import Any

import structlog

from hiveflow.core.observability import llm_duration, llm_token_usage, tracer
from hiveflow.plugins.llm import LLMConfig, LLMMessage, LLMProvider, LLMResponse, TokenUsage
from hiveflow.plugins.llm.errors import (
    LLMAuthError,
    LLMConnectionError,
    LLMModelNotFoundError,
    LLMRateLimitError,
)
from hiveflow.plugins.llm.secrets import get_secret_backend

logger = structlog.get_logger()

# Azure Cognitive Services audience for Entra ID RBAC tokens
_AZURE_COGSERVICES_SCOPE = "https://cognitiveservices.azure.com/.default"


class AzureOpenAIProvider(LLMProvider):
    """Azure OpenAI Service provider (Entra ID RBAC + API key).

    Authentication decision tree:
    1. If ``AZURE_OPENAI_API_KEY`` is set → API key auth
    2. Else → RBAC via ``DefaultAzureCredential`` + ``get_bearer_token_provider``
    3. If neither works → actionable error message
    """

    def __init__(
        self,
        azure_endpoint: str | None = None,
        api_key: str | None = None,
        api_version: str = "2024-10-21",
    ) -> None:
        self._azure_endpoint = azure_endpoint
        self._api_key = api_key
        self._api_version = api_version
        self._client: Any = None

    def _get_client(self) -> Any:
        """Lazy-initialize the Azure OpenAI async client."""
        if self._client is not None:
            return self._client

        try:
            from openai import AsyncAzureOpenAI
        except ImportError as exc:
            raise ImportError(
                "OpenAI SDK required for Azure provider. Install with: uv add openai"
            ) from exc

        secrets = get_secret_backend()
        endpoint = self._azure_endpoint or secrets.get_secret("AZURE_OPENAI_ENDPOINT")
        api_key = self._api_key or secrets.get_secret("AZURE_OPENAI_API_KEY")
        api_version = secrets.get_secret("OPENAI_API_VERSION") or self._api_version

        if not endpoint:
            raise LLMAuthError(
                "Azure OpenAI endpoint not configured. "
                "Set AZURE_OPENAI_ENDPOINT environment variable or pass azure_endpoint.\n"
                "  Use the base URL only: https://<resource>.openai.azure.com",
                provider_id="azure",
            )

        # Strip deployment paths the user may have pasted from the Azure portal.
        # The SDK constructs /openai/deployments/<name>/... automatically.
        endpoint = re.sub(r"/openai/deployments/[^/]+/?$", "", endpoint.rstrip("/"))

        if api_key:
            # Path 1: API key authentication
            self._client = AsyncAzureOpenAI(
                azure_endpoint=endpoint,
                api_key=api_key,
                api_version=api_version,
            )
            logger.info("azure.auth.api_key", endpoint=endpoint)
        else:
            # Path 2: RBAC via DefaultAzureCredential
            try:
                from azure.identity import (  # type: ignore[import-untyped]
                    DefaultAzureCredential,
                    get_bearer_token_provider,
                )
            except ImportError as exc:
                raise LLMAuthError(
                    "azure-identity required for Azure RBAC authentication. "
                    "Install with: uv add hiveflow[llm-azure]",
                    provider_id="azure",
                ) from exc

            try:
                credential = DefaultAzureCredential()
                token_provider = get_bearer_token_provider(credential, _AZURE_COGSERVICES_SCOPE)
            except Exception as exc:
                raise LLMAuthError(
                    "Azure OpenAI authentication failed. Configure one of:\n"
                    "  1. RBAC: Set AZURE_OPENAI_ENDPOINT and assign "
                    "'Cognitive Services OpenAI User' role to your identity "
                    "(service principal, managed identity, or az login)\n"
                    "  2. API Key: Set AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY\n"
                    "Install azure-identity: uv add hiveflow[llm-azure]",
                    provider_id="azure",
                ) from exc

            self._client = AsyncAzureOpenAI(
                azure_endpoint=endpoint,
                azure_ad_token_provider=token_provider,
                api_version=api_version,
            )
            logger.info("azure.auth.rbac", endpoint=endpoint)

        return self._client

    @property
    def plugin_id(self) -> str:
        return "azure"

    @property
    def description(self) -> str:
        return "Azure OpenAI Service provider (Entra ID RBAC + API key)"

    @property
    def supports_streaming(self) -> bool:
        return True

    @property
    def supports_function_calling(self) -> bool:
        return True

    @property
    def supports_json_mode(self) -> bool:
        return True

    @property
    def supports_vision(self) -> bool:
        return True

    async def chat(self, messages: list[LLMMessage], config: LLMConfig) -> LLMResponse:
        """Send chat completion via Azure OpenAI API.

        Args:
            messages: Conversation messages
            config: LLM configuration (model = Azure deployment name)

        Returns:
            LLM response
        """
        client = self._get_client()

        kwargs: dict[str, Any] = {
            "model": config.model,
            "messages": [self._format_message(m) for m in messages],
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
        }

        if config.tools:
            kwargs["tools"] = config.tools
        if config.response_format:
            kwargs["response_format"] = config.response_format
        if config.stop:
            kwargs["stop"] = config.stop

        kwargs.update(config.extra)

        span = None
        if tracer:
            span = tracer.start_span(f"chat {self.provider_id}")
            span.set_attribute("gen_ai.system", self.provider_id)
            span.set_attribute("gen_ai.request.model", config.model)

        t0 = time.perf_counter()
        try:
            response = await client.chat.completions.create(**kwargs)
        except Exception as exc:
            latency_ms = (time.perf_counter() - t0) * 1000
            logger.error(
                "llm.chat.error",
                provider_id=self.provider_id,
                model=config.model,
                latency_ms=round(latency_ms, 1),
            )
            if span:
                span.set_attribute("error", True)
                span.end()
            raise self._map_sdk_error(exc) from exc
        latency_ms = (time.perf_counter() - t0) * 1000

        choice = response.choices[0]

        tool_calls = None
        if choice.message.tool_calls:
            tool_calls = [
                {
                    "id": tc.id,
                    "type": tc.type,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in choice.message.tool_calls
            ]

        usage = None
        prompt_tokens = 0
        completion_tokens = 0
        if response.usage:
            prompt_tokens = response.usage.prompt_tokens
            completion_tokens = response.usage.completion_tokens
            usage = TokenUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=response.usage.total_tokens,
            )

        logger.info(
            "llm.chat.complete",
            provider_id=self.provider_id,
            model=response.model,
            latency_ms=round(latency_ms, 1),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

        if span:
            span.set_attribute("gen_ai.response.model", response.model)
            span.set_attribute("gen_ai.usage.prompt_tokens", prompt_tokens)
            span.set_attribute("gen_ai.usage.completion_tokens", completion_tokens)
            span.end()

        if llm_duration:
            llm_duration.record(
                latency_ms / 1000,
                {"gen_ai.system": self.provider_id, "gen_ai.request.model": config.model},
            )
        if llm_token_usage:
            llm_token_usage.add(
                prompt_tokens + completion_tokens,
                {"gen_ai.system": self.provider_id, "gen_ai.request.model": config.model},
            )

        return LLMResponse(
            content=choice.message.content or "",
            model=response.model,
            tool_calls=tool_calls,
            usage=usage,
            finish_reason=choice.finish_reason or "stop",
        )

    async def chat_stream(
        self, messages: list[LLMMessage], config: LLMConfig
    ) -> AsyncIterator[str]:
        """Stream chat completion via Azure OpenAI API.

        Args:
            messages: Conversation messages
            config: LLM configuration

        Yields:
            Individual tokens
        """
        client = self._get_client()

        kwargs: dict[str, Any] = {
            "model": config.model,
            "messages": [self._format_message(m) for m in messages],
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
            "stream": True,
        }

        if config.stop:
            kwargs["stop"] = config.stop
        kwargs.update(config.extra)

        t0 = time.perf_counter()
        try:
            stream = await client.chat.completions.create(**kwargs)
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as exc:
            latency_ms = (time.perf_counter() - t0) * 1000
            logger.error(
                "llm.chat_stream.error",
                provider_id=self.provider_id,
                model=config.model,
                latency_ms=round(latency_ms, 1),
            )
            raise self._map_sdk_error(exc) from exc

        latency_ms = (time.perf_counter() - t0) * 1000
        logger.info(
            "llm.chat_stream.complete",
            provider_id=self.provider_id,
            model=config.model,
            latency_ms=round(latency_ms, 1),
        )

    def get_available_models(self) -> list[str]:
        # Azure uses deployment names, not model names.
        # Return common deployment patterns as examples.
        return []

    @staticmethod
    def _format_message(msg: LLMMessage) -> dict[str, Any]:
        """Convert LLMMessage to OpenAI API format (Azure uses same format)."""
        result: dict[str, Any] = {
            "role": msg.role,
            "content": msg.content,
        }
        if msg.name:
            result["name"] = msg.name
        if msg.tool_calls:
            result["tool_calls"] = msg.tool_calls
        if msg.tool_call_id:
            result["tool_call_id"] = msg.tool_call_id
        return result

    def _map_sdk_error(self, exc: Exception) -> Exception:
        """Map OpenAI SDK exceptions to typed LLMProviderError subclasses."""
        import openai

        pid = self.plugin_id
        msg = str(exc)

        if isinstance(exc, openai.AuthenticationError):
            return LLMAuthError(msg, provider_id=pid)
        if isinstance(exc, openai.RateLimitError):
            return LLMRateLimitError(msg, provider_id=pid)
        if isinstance(exc, openai.NotFoundError):
            return LLMModelNotFoundError(msg, provider_id=pid)
        if isinstance(exc, (openai.APIConnectionError, openai.APITimeoutError)):
            return LLMConnectionError(msg, provider_id=pid)
        if isinstance(exc, openai.InternalServerError):
            return LLMConnectionError(msg, provider_id=pid)
        if isinstance(exc, openai.APIStatusError):
            return LLMConnectionError(msg, provider_id=pid)
        return exc
