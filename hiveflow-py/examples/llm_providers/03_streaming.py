"""Example: Streaming Responses.

Demonstrates how to:
1. Stream tokens from a provider in real time
2. Detect whether a provider supports streaming
3. Compare streamed output across providers

The example tries providers in order: Azure -> OpenAI -> Anthropic.

Prerequisites:
    At least one set of credentials.  Easiest: Azure RBAC with `az login`.

Usage:
    # Azure RBAC (recommended):
    AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com \
        uv run python examples/llm_providers/03_streaming.py

    # OpenAI:
    OPENAI_API_KEY=sk-... uv run python examples/llm_providers/03_streaming.py
"""

import asyncio
import os
import sys

from hiveflow.plugins.llm import LLMConfig, LLMMessage, get_llm_registry


async def stream_demo(model_ref: str) -> None:
    """Stream a response and print tokens as they arrive."""
    registry = get_llm_registry()
    provider, model = registry.resolve_model(model_ref)

    if not provider.supports_streaming:
        print(f"  {provider.provider_id} does not support streaming, skipping.")
        return

    messages = [
        LLMMessage(
            role="user",
            content="Write a haiku about distributed systems.",
        ),
    ]
    config = LLMConfig(model=model, max_tokens=60, temperature=0.9)

    print(f"  [{provider.provider_id}:{model}] ", end="", flush=True)

    async for token in provider.chat_stream(messages, config):
        sys.stdout.write(token)
        sys.stdout.flush()

    print("\n")


async def main() -> None:
    registry = get_llm_registry()
    available = registry.list_ids()

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
        return

    print("Streaming responses:\n")
    for ref in targets:
        try:
            await stream_demo(ref)
        except Exception as exc:
            print(f"  Skipped {ref} ({type(exc).__name__}: {exc})\n")


if __name__ == "__main__":
    asyncio.run(main())
