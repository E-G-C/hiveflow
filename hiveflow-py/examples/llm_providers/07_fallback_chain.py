"""Example: Fallback Chains for Resilient LLM Calls.

Demonstrates how to:
1. Create a FallbackChain that cascades through providers on failure
2. Use RetryProvider to retry within a single provider
3. Use build_fallback_chain() for the common retry+fallback pattern
4. Handle LLMFallbackExhaustedError when all providers fail

This example uses mock providers to simulate failures without needing
real API keys. See the docstrings for how to adapt with real providers.

Usage:
    uv run python examples/llm_providers/07_fallback_chain.py
"""

import asyncio
from collections.abc import AsyncIterator

from hiveflow.core.fallback import (
    FallbackChain,
    LLMFallbackExhaustedError,
    RetryProvider,
    build_fallback_chain,
)
from hiveflow.plugins.llm import LLMConfig, LLMMessage, LLMProvider, LLMResponse, TokenUsage


# ---------------------------------------------------------------------------
# Mock providers to simulate success/failure without real API calls
# ---------------------------------------------------------------------------

class MockProvider(LLMProvider):
    """A mock provider that can be configured to succeed or fail."""

    def __init__(self, name: str, fail: bool = False) -> None:
        self._name = name
        self._fail = fail
        self._call_count = 0

    @property
    def plugin_id(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"Mock provider '{self._name}'"

    async def chat(
        self, messages: list[LLMMessage], config: LLMConfig
    ) -> LLMResponse:
        self._call_count += 1
        if self._fail:
            raise ConnectionError(f"{self._name} is down (attempt {self._call_count})")
        return LLMResponse(
            content=f"Response from {self._name} (model={config.model})",
            model=config.model,
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )

    async def chat_stream(
        self, messages: list[LLMMessage], config: LLMConfig
    ) -> AsyncIterator[str]:
        response = await self.chat(messages, config)
        yield response.content


async def main() -> None:
    messages = [LLMMessage(role="user", content="Hello")]
    config = LLMConfig(model="test", max_tokens=50)

    # -- 1. Basic fallback: first fails, second succeeds ----------------------
    print("1. Basic fallback chain")
    primary = MockProvider("primary-openai", fail=True)
    secondary = MockProvider("secondary-anthropic", fail=False)

    chain = FallbackChain([
        (primary, "gpt-4o"),
        (secondary, "claude-sonnet-4-20250514"),
    ])
    print(f"   Chain: {chain.description}")

    response = await chain.chat(messages, config)
    print(f"   Result: {response.content}")
    print(f"   primary calls:   {primary._call_count}")
    print(f"   secondary calls: {secondary._call_count}")

    # -- 2. All providers fail -> LLMFallbackExhaustedError -------------------
    print("\n2. All providers fail")
    all_bad = FallbackChain([
        (MockProvider("provider-a", fail=True), "model-a"),
        (MockProvider("provider-b", fail=True), "model-b"),
    ])

    try:
        await all_bad.chat(messages, config)
    except LLMFallbackExhaustedError as exc:
        print(f"   Caught: {type(exc).__name__}")
        print(f"   Message: {exc}")
        print(f"   Individual errors: {len(exc.errors)}")
        for pid, model, err in exc.errors:
            print(f"     - {pid}:{model} -> {err}")

    # -- 3. RetryProvider: retry within a single provider ---------------------
    print("\n3. RetryProvider")

    class FlakyProvider(LLMProvider):
        """Fails the first N attempts, then succeeds."""

        def __init__(self, name: str, fail_count: int) -> None:
            self._name = name
            self._remaining_failures = fail_count
            self.total_calls = 0

        @property
        def plugin_id(self) -> str:
            return self._name

        @property
        def description(self) -> str:
            return f"Flaky {self._name}"

        async def chat(
            self, messages: list[LLMMessage], config: LLMConfig
        ) -> LLMResponse:
            self.total_calls += 1
            if self._remaining_failures > 0:
                self._remaining_failures -= 1
                raise TimeoutError(f"{self._name} timed out")
            return LLMResponse(content=f"Success from {self._name}!", model=config.model)

    flaky = FlakyProvider("flaky-api", fail_count=2)
    retrier = RetryProvider(flaky, max_retries=3)

    response = await retrier.chat(messages, config)
    print(f"   Result: {response.content}")
    print(f"   Total attempts: {flaky.total_calls}")

    # -- 4. build_fallback_chain: retry + fallback combined -------------------
    print("\n4. build_fallback_chain (retry + fallback)")
    # Simulates: try Azure 2x, then OpenAI 2x, then Anthropic 2x
    azure = MockProvider("azure", fail=True)
    openai = MockProvider("openai", fail=True)
    anthropic = MockProvider("anthropic", fail=False)

    chain = build_fallback_chain(
        provider_models=[
            (azure, "gpt-4o-eastus"),
            (openai, "gpt-4o"),
            (anthropic, "claude-sonnet-4-20250514"),
        ],
        max_retries_per_provider=2,
    )
    print(f"   Chain: {chain.description}")

    response = await chain.chat(messages, config)
    print(f"   Result: {response.content}")
    print(f"   azure calls:     {azure._call_count}")
    print(f"   openai calls:    {openai._call_count}")
    print(f"   anthropic calls: {anthropic._call_count}")

    # -- 5. With real providers (commented, for reference) --------------------
    #
    # from hiveflow.plugins.llm import get_llm_registry
    # registry = get_llm_registry()
    #
    # azure_prov, _ = registry.resolve_model("azure:gpt-4o-eastus")
    # openai_prov, _ = registry.resolve_model("openai:gpt-4o")
    # anthropic_prov, _ = registry.resolve_model("anthropic:claude-sonnet-4-20250514")
    #
    # chain = build_fallback_chain([
    #     (azure_prov, "gpt-4o-eastus"),
    #     (openai_prov, "gpt-4o"),
    #     (anthropic_prov, "claude-sonnet-4-20250514"),
    # ], max_retries_per_provider=2)
    #
    # response = await chain.chat(messages, LLMConfig(max_tokens=200))
    # print(response.content)


if __name__ == "__main__":
    asyncio.run(main())
