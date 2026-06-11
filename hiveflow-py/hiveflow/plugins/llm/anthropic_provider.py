"""Anthropic LLM Provider - Claude models for HiveFlow."""

import json
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


class AnthropicProvider(LLMProvider):
    """Anthropic LLM provider using the Anthropic SDK."""

    def __init__(self) -> None:
        self._client: Any = None

    def _get_client(self) -> Any:
        """Lazy-initialize the Anthropic async client."""
        if self._client is None:
            try:
                from anthropic import AsyncAnthropic
            except ImportError as exc:
                raise ImportError("Anthropic SDK required. Install with: uv add anthropic") from exc

            api_key = get_secret_backend().get_secret("ANTHROPIC_API_KEY")
            self._client = AsyncAnthropic(api_key=api_key)
        return self._client

    @property
    def plugin_id(self) -> str:
        return "anthropic"

    @property
    def description(self) -> str:
        return "Anthropic API provider (Claude models)"

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
        """Send chat completion via Anthropic API.

        Args:
            messages: Conversation messages
            config: LLM configuration

        Returns:
            LLM response
        """
        client = self._get_client()

        # Extract system message (Anthropic uses separate system param)
        system_prompt = ""
        chat_messages = []
        for msg in messages:
            if msg.role == "system":
                system_prompt = msg.content
            else:
                chat_messages.append({"role": msg.role, "content": msg.content})

        kwargs: dict[str, Any] = {
            "model": config.model,
            "messages": chat_messages,
            "max_tokens": config.max_tokens,
            "temperature": config.temperature,
        }

        if system_prompt:
            kwargs["system"] = system_prompt

        if config.tools:
            # Convert OpenAI-style tool specs to Anthropic format
            kwargs["tools"] = [self._convert_tool_spec(tool) for tool in config.tools]

        if config.stop:
            kwargs["stop_sequences"] = config.stop

        kwargs.update(config.extra)

        span = None
        if tracer:
            span = tracer.start_span(f"chat {self.provider_id}")
            span.set_attribute("gen_ai.system", self.provider_id)
            span.set_attribute("gen_ai.request.model", config.model)

        t0 = time.perf_counter()
        try:
            response = await client.messages.create(**kwargs)
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

        # Extract text content
        content = ""
        tool_calls = None
        for block in response.content:
            if block.type == "text":
                content = block.text
            elif block.type == "tool_use":
                if tool_calls is None:
                    tool_calls = []
                tool_calls.append(
                    {
                        "id": block.id,
                        "type": "function",
                        "function": {
                            "name": block.name,
                            "arguments": json.dumps(block.input),
                        },
                    }
                )

        prompt_tokens = response.usage.input_tokens
        completion_tokens = response.usage.output_tokens
        usage = TokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
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
            content=content,
            model=response.model,
            tool_calls=tool_calls,
            usage=usage,
            finish_reason=response.stop_reason or "end_turn",
        )

    async def chat_stream(
        self, messages: list[LLMMessage], config: LLMConfig
    ) -> AsyncIterator[str]:
        """Stream chat completion via Anthropic API.

        Args:
            messages: Conversation messages
            config: LLM configuration

        Yields:
            Individual tokens
        """
        client = self._get_client()

        system_prompt = ""
        chat_messages = []
        for msg in messages:
            if msg.role == "system":
                system_prompt = msg.content
            else:
                chat_messages.append({"role": msg.role, "content": msg.content})

        kwargs: dict[str, Any] = {
            "model": config.model,
            "messages": chat_messages,
            "max_tokens": config.max_tokens,
            "temperature": config.temperature,
        }

        if system_prompt:
            kwargs["system"] = system_prompt
        if config.stop:
            kwargs["stop_sequences"] = config.stop
        kwargs.update(config.extra)

        t0 = time.perf_counter()
        try:
            async with client.messages.stream(**kwargs) as stream:
                async for text in stream.text_stream:
                    yield text
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
            "claude-sonnet-4-20250514",
            "claude-haiku-4-20250414",
            "claude-3-5-sonnet-20241022",
        ]

    @staticmethod
    def _convert_tool_spec(tool: dict[str, Any]) -> dict[str, Any]:
        """Convert OpenAI-style tool spec to Anthropic format."""
        if tool.get("type") == "function":
            func = tool["function"]
            return {
                "name": func["name"],
                "description": func.get("description", ""),
                "input_schema": func.get("parameters", {}),
            }
        return tool

    def _map_sdk_error(self, exc: Exception) -> Exception:
        """Map Anthropic SDK exceptions to typed LLMProviderError subclasses."""
        import anthropic

        pid = self.plugin_id
        msg = str(exc)

        if isinstance(exc, anthropic.AuthenticationError):
            return LLMAuthError(msg, provider_id=pid)
        if isinstance(exc, anthropic.RateLimitError):
            return LLMRateLimitError(msg, provider_id=pid)
        if isinstance(exc, anthropic.NotFoundError):
            return LLMModelNotFoundError(msg, provider_id=pid)
        if isinstance(exc, (anthropic.APIConnectionError, anthropic.APITimeoutError)):
            return LLMConnectionError(msg, provider_id=pid)
        if isinstance(exc, anthropic.InternalServerError):
            return LLMConnectionError(msg, provider_id=pid)
        if isinstance(exc, anthropic.APIStatusError):
            return LLMConnectionError(msg, provider_id=pid)
        return exc
