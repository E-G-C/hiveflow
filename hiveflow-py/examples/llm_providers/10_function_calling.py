"""Example: Function Calling / Tool Use.

Demonstrates how to:
1. Define tool specs in OpenAI function-calling format
2. Send them via LLMConfig.tools
3. Parse tool_calls from the LLMResponse
4. Feed tool results back as a tool message for a follow-up turn
5. Let the model produce the final answer with tool output

This uses a live LLM (Azure RBAC by default) to exercise the full
tool-calling round-trip.

Prerequisites:
    At least one set of credentials.  Easiest: Azure RBAC with `az login`.

Usage:
    AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com \
        uv run python examples/llm_providers/10_function_calling.py
"""

import asyncio
import json
import os

from hiveflow.plugins.llm import LLMConfig, LLMMessage, get_llm_registry


# -- Simulated tool implementations ------------------------------------------

def get_weather(city: str) -> dict:
    """Simulated weather lookup."""
    fake_data = {
        "london": {"temp_c": 12, "condition": "Cloudy"},
        "tokyo": {"temp_c": 22, "condition": "Sunny"},
        "new york": {"temp_c": 8, "condition": "Rainy"},
    }
    data = fake_data.get(city.lower(), {"temp_c": 20, "condition": "Unknown"})
    return {"city": city, **data}


def get_time(timezone: str) -> dict:
    """Simulated time lookup."""
    fake_times = {
        "UTC": "14:30",
        "JST": "23:30",
        "EST": "09:30",
        "GMT": "14:30",
    }
    return {"timezone": timezone, "time": fake_times.get(timezone, "12:00")}


# Map function names to implementations.
TOOL_DISPATCH = {
    "get_weather": lambda args: get_weather(args["city"]),
    "get_time": lambda args: get_time(args["timezone"]),
}

# -- Tool specifications (OpenAI function-calling format) ---------------------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get the current weather for a city.",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "The city name, e.g. 'London'.",
                    },
                },
                "required": ["city"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_time",
            "description": "Get the current time in a timezone.",
            "parameters": {
                "type": "object",
                "properties": {
                    "timezone": {
                        "type": "string",
                        "description": "IANA or abbreviation, e.g. 'UTC', 'JST'.",
                    },
                },
                "required": ["timezone"],
            },
        },
    },
]


async def main() -> None:
    registry = get_llm_registry()
    available = registry.list_ids()

    model_ref = None
    if "azure" in available and os.environ.get("AZURE_OPENAI_ENDPOINT"):
        model_ref = "azure:gpt-4o-mini"
    elif "openai" in available and os.environ.get("OPENAI_API_KEY"):
        model_ref = "openai:gpt-4o-mini"

    if not model_ref:
        print("This example requires OpenAI or Azure (Anthropic uses a different tool format).")
        print("  Easiest: AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com")
        return

    provider, model = registry.resolve_model(model_ref)
    print(f"Provider: {provider.provider_id} | Model: {model}")
    print(f"Supports function calling: {provider.supports_function_calling}\n")

    # -- Turn 1: user question, model may call tools -------------------------
    messages = [
        LLMMessage(role="system", content="You are a helpful assistant with access to weather and time tools."),
        LLMMessage(role="user", content="What's the weather in Tokyo and the current time in JST?"),
    ]
    config = LLMConfig(model=model, max_tokens=300, tools=TOOLS)

    print("--- Turn 1: User asks, model decides to call tools ---")
    response = await provider.chat(messages, config)

    if not response.tool_calls:
        # Model answered directly without calling tools.
        print(f"Model answered directly: {response.content}")
        return

    print(f"Model requested {len(response.tool_calls)} tool call(s):")
    for tc in response.tool_calls:
        print(f"  - {tc['function']['name']}({tc['function']['arguments']})")

    # -- Execute tools locally ------------------------------------------------
    print("\n--- Executing tools locally ---")

    # Append the assistant message (with tool_calls) to history.
    messages.append(LLMMessage(
        role="assistant",
        content=response.content or "",
        tool_calls=response.tool_calls,
    ))

    for tc in response.tool_calls:
        fn_name = tc["function"]["name"]
        fn_args = json.loads(tc["function"]["arguments"])
        result = TOOL_DISPATCH[fn_name](fn_args)
        print(f"  {fn_name}({fn_args}) -> {result}")

        # Add tool result message linked by tool_call_id.
        messages.append(LLMMessage(
            role="tool",
            content=json.dumps(result),
            tool_call_id=tc["id"],
        ))

    # -- Turn 2: model incorporates tool results into final answer -----------
    print("\n--- Turn 2: Model synthesizes tool results ---")
    # No tools in this follow-up config so the model produces a text answer.
    config_final = LLMConfig(model=model, max_tokens=300)
    final = await provider.chat(messages, config_final)
    print(f"Assistant: {final.content}")

    if final.usage:
        print(f"\nTokens: {final.usage.prompt_tokens} prompt "
              f"+ {final.usage.completion_tokens} completion "
              f"= {final.usage.total_tokens} total")


if __name__ == "__main__":
    asyncio.run(main())
