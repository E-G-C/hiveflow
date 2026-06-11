"""OpenAI LLM Provider - Default provider for HiveFlow.

Supports GPT-4o, GPT-4o-mini, o3-mini, and any OpenAI-compatible endpoint
(llama.cpp, vLLM, Ollama, etc.) via the base_url parameter.
"""

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


class OpenAIProvider(LLMProvider):
    """OpenAI LLM provider using the OpenAI SDK.

    Supports any OpenAI-compatible endpoint (llama.cpp, vLLM, etc.)
    via the base_url parameter.
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self._base_url = base_url
        self._api_key = api_key
        self._client: Any = None

    def _get_client(self) -> Any:
        """Lazy-initialize the OpenAI async client."""
        if self._client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError as exc:
                raise ImportError("OpenAI SDK required. Install with: uv add openai") from exc

            api_key = self._api_key or get_secret_backend().get_secret("OPENAI_API_KEY")
            self._client = AsyncOpenAI(
                api_key=api_key,
                base_url=self._base_url,
            )
        return self._client

    @property
    def plugin_id(self) -> str:
        return "openai"

    @property
    def description(self) -> str:
        return "OpenAI API provider (GPT-4o, o3-mini, etc.)"

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
        """Send chat completion via OpenAI API.

        Args:
            messages: Conversation messages
            config: LLM configuration

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

        # Merge any extra parameters
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
        """Stream chat completion via OpenAI API.

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
        return [
            "gpt-4o",
            "gpt-4o-mini",
            "o3-mini",
            "gpt-4-turbo",
        ]

    @staticmethod
    def _format_message(msg: LLMMessage) -> dict[str, Any]:
        """Convert LLMMessage to OpenAI API format."""
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
        # Unrecognized OpenAI error — wrap as generic connection error
        if isinstance(exc, openai.APIStatusError):
            return LLMConnectionError(msg, provider_id=pid)
        return exc
