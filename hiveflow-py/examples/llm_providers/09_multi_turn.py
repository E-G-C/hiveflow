"""Example: Multi-Turn Conversation.

Demonstrates how to:
1. Maintain conversation history across multiple exchanges
2. Use system prompts to shape assistant behavior
3. Reference earlier context in follow-up questions
4. Track cumulative token usage across turns

Prerequisites:
    At least one set of credentials.  Easiest: Azure RBAC with `az login`.

Usage:
    AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com \
        uv run python examples/llm_providers/09_multi_turn.py
"""

import asyncio
import os

from hiveflow.plugins.llm import LLMConfig, LLMMessage, get_llm_registry


async def main() -> None:
    registry = get_llm_registry()
    available = registry.list_ids()

    # Pick the first available provider.
    model_ref = None
    if "azure" in available and os.environ.get("AZURE_OPENAI_ENDPOINT"):
        model_ref = "azure:gpt-4o-mini"
    elif "openai" in available and os.environ.get("OPENAI_API_KEY"):
        model_ref = "openai:gpt-4o-mini"
    elif "anthropic" in available and os.environ.get("ANTHROPIC_API_KEY"):
        model_ref = "anthropic:claude-haiku-4-20250414"

    if not model_ref:
        print("No providers available.")
        print("  Easiest: AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com")
        return

    provider, model = registry.resolve_model(model_ref)
    config = LLMConfig(model=model, max_tokens=300, temperature=0.4)
    print(f"Provider: {provider.provider_id} | Model: {model}\n")

    # Build conversation history incrementally.
    history: list[LLMMessage] = [
        LLMMessage(
            role="system",
            content=(
                "You are a knowledgeable Python tutor. "
                "Give concise answers (2-3 sentences max). "
                "When the student asks a follow-up, reference what you said earlier."
            ),
        ),
    ]

    # Simulate a multi-turn conversation.
    user_turns = [
        "What is a Python decorator?",
        "Can you show a simple example?",
        "How would I make that decorator accept arguments?",
        "Summarize the three things you just taught me.",
    ]

    total_prompt = 0
    total_completion = 0

    for i, question in enumerate(user_turns, 1):
        print(f"--- Turn {i} ---")
        print(f"User: {question}")

        # Append user message to history.
        history.append(LLMMessage(role="user", content=question))

        response = await provider.chat(history, config)
        print(f"Assistant: {response.content}\n")

        # Append assistant response to history so the next turn has context.
        history.append(LLMMessage(role="assistant", content=response.content))

        if response.usage:
            total_prompt += response.usage.prompt_tokens
            total_completion += response.usage.completion_tokens

    print("=" * 50)
    print(f"Total turns:      {len(user_turns)}")
    print(f"History messages:  {len(history)}")
    print(f"Cumulative tokens: {total_prompt} prompt + {total_completion} completion "
          f"= {total_prompt + total_completion} total")


if __name__ == "__main__":
    asyncio.run(main())
