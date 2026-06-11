"""Example: Basic Chat Completions Across Providers.

Demonstrates how to:
1. Send a chat message via Azure OpenAI (RBAC)
2. Optionally compare with OpenAI and Anthropic
3. Inspect token usage in each response

The example tries providers in order: Azure -> OpenAI -> Anthropic.
Only providers with valid credentials are called; the rest are skipped.

Prerequisites:
    At least one set of credentials.  Easiest: Azure RBAC with `az login`.

Usage:
    # Azure RBAC (recommended -- no API key needed):
    AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com \
        uv run python examples/llm_providers/02_chat.py

    # OpenAI:
    OPENAI_API_KEY=sk-... uv run python examples/llm_providers/02_chat.py

    # All three at once:
    AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com \
    OPENAI_API_KEY=sk-... ANTHROPIC_API_KEY=sk-ant-... \
        uv run python examples/llm_providers/02_chat.py
"""

import asyncio
import os

from hiveflow.plugins.llm import LLMConfig, LLMMessage, get_llm_registry


async def main() -> None:
    registry = get_llm_registry()
    available = registry.list_ids()

    messages = [
        LLMMessage(role="system", content="You are a helpful assistant. Be concise."),
        LLMMessage(role="user", content="What are three benefits of type hints in Python?"),
    ]

    # Azure first (RBAC, no key needed), then OpenAI, then Anthropic.
    targets = []
    if "azure" in available and os.environ.get("AZURE_OPENAI_ENDPOINT"):
        targets.append("azure:gpt-4o-mini")
    if "openai" in available and os.environ.get("OPENAI_API_KEY"):
        targets.append("openai:gpt-4o-mini")
    if "anthropic" in available and os.environ.get("ANTHROPIC_API_KEY"):
        targets.append("anthropic:claude-haiku-4-20250414")

    if not targets:
        print("No providers available.")
        print("  Easiest: AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com")
        print("  Or set OPENAI_API_KEY or ANTHROPIC_API_KEY.")
        return

    for model_ref in targets:
        provider, model = registry.resolve_model(model_ref)
        config = LLMConfig(model=model, max_tokens=200, temperature=0.3)

        print(f"\n{'=' * 60}")
        print(f"  Provider: {provider.provider_id} | Model: {model}")
        print(f"{'=' * 60}")

        try:
            response = await provider.chat(messages, config)
            print(f"\n{response.content}\n")
            if response.usage:
                print(
                    f"  tokens: {response.usage.prompt_tokens} prompt "
                    f"+ {response.usage.completion_tokens} completion "
                    f"= {response.usage.total_tokens} total"
                )
            print(f"  finish_reason: {response.finish_reason}")
        except Exception as exc:
            print(f"  Skipped ({type(exc).__name__}: {exc})")


if __name__ == "__main__":
    asyncio.run(main())
