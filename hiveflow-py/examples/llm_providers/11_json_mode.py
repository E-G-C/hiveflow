"""Example: JSON Mode / Structured Output.

Demonstrates how to:
1. Request structured JSON output via LLMConfig.response_format
2. Parse the JSON response into Python objects
3. Combine JSON mode with a system prompt schema description

This is useful for extracting structured data from LLM responses --
e.g., entity extraction, classification, or data transformation.

Prerequisites:
    At least one set of credentials.  Easiest: Azure RBAC with `az login`.

Usage:
    AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com \
        uv run python examples/llm_providers/11_json_mode.py
"""

import asyncio
import json
import os

from hiveflow.plugins.llm import LLMConfig, LLMMessage, get_llm_registry


async def main() -> None:
    registry = get_llm_registry()
    available = registry.list_ids()

    model_ref = None
    if "azure" in available and os.environ.get("AZURE_OPENAI_ENDPOINT"):
        model_ref = "azure:gpt-4o-mini"
    elif "openai" in available and os.environ.get("OPENAI_API_KEY"):
        model_ref = "openai:gpt-4o-mini"

    if not model_ref:
        print("This example requires OpenAI or Azure (json_mode support).")
        print("  Easiest: AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com")
        return

    provider, model = registry.resolve_model(model_ref)
    print(f"Provider: {provider.provider_id} | Model: {model}")
    print(f"Supports JSON mode: {provider.supports_json_mode}\n")

    # -- 1. Basic JSON mode: entity extraction --------------------------------
    print("--- 1. Entity extraction ---")
    messages = [
        LLMMessage(
            role="system",
            content=(
                "You are a data extraction assistant. "
                "Always respond with valid JSON matching this schema:\n"
                '{"entities": [{"name": str, "type": str, "description": str}]}'
            ),
        ),
        LLMMessage(
            role="user",
            content=(
                "Extract entities from this text: "
                "'Microsoft announced that CEO Satya Nadella will visit the "
                "Azure data center in West Europe next Tuesday to discuss the "
                "new GPT-4o deployment with the engineering team.'"
            ),
        ),
    ]

    config = LLMConfig(
        model=model,
        max_tokens=500,
        temperature=0.0,
        response_format={"type": "json_object"},
    )

    response = await provider.chat(messages, config)
    print(f"Raw response:\n{response.content}\n")

    parsed = json.loads(response.content)
    print("Parsed entities:")
    for entity in parsed.get("entities", []):
        print(f"  - {entity['name']} ({entity['type']}): {entity.get('description', '')}")

    if response.usage:
        print(f"\n  tokens: {response.usage.total_tokens}")

    # -- 2. Classification task -----------------------------------------------
    print("\n--- 2. Sentiment classification ---")
    messages = [
        LLMMessage(
            role="system",
            content=(
                "You are a sentiment classifier. "
                "Always respond with valid JSON matching:\n"
                '{"sentiment": "positive"|"negative"|"neutral", '
                '"confidence": float, "reasoning": str}'
            ),
        ),
        LLMMessage(
            role="user",
            content="The new API is incredibly fast but the documentation is sparse and confusing.",
        ),
    ]

    response = await provider.chat(messages, config)
    result = json.loads(response.content)
    print(f"Sentiment:  {result.get('sentiment')}")
    print(f"Confidence: {result.get('confidence')}")
    print(f"Reasoning:  {result.get('reasoning')}")

    # -- 3. Data transformation -----------------------------------------------
    print("\n--- 3. Data transformation ---")
    messages = [
        LLMMessage(
            role="system",
            content=(
                "You convert unstructured text into structured JSON. "
                "Always respond with valid JSON matching:\n"
                '{"items": [{"name": str, "quantity": int, "unit": str}]}'
            ),
        ),
        LLMMessage(
            role="user",
            content="I need 3 kg of flour, 500 ml of milk, 2 eggs, and a pinch of salt.",
        ),
    ]

    response = await provider.chat(messages, config)
    items = json.loads(response.content)
    print(f"Parsed shopping list:")
    for item in items.get("items", []):
        print(f"  - {item['quantity']} {item['unit']} of {item['name']}")


if __name__ == "__main__":
    asyncio.run(main())
