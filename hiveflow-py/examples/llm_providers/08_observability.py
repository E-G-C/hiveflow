"""Example: Structured Logging and OpenTelemetry Observability.

Demonstrates how to:
1. Configure structured logging (dev console vs production JSON)
2. See structlog events emitted by provider calls
3. Check OTel toggle behavior (disabled by default, no overhead)
4. Enable OTel metrics and spans via environment variable

Prerequisites:
    - At least one set of credentials.  Easiest: Azure RBAC with `az login`.
    - For OTel: `uv add opentelemetry-api` + HIVEFLOW_OTEL_ENABLED=true

Usage:
    # Development mode (pretty console output) with Azure RBAC:
    AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com \
        uv run python examples/llm_providers/08_observability.py

    # Production mode (JSON lines):
    HIVEFLOW_ENV=production \
    AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com \
        uv run python examples/llm_providers/08_observability.py

    # With OTel enabled:
    HIVEFLOW_OTEL_ENABLED=true \
    AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com \
        uv run python examples/llm_providers/08_observability.py
"""

import asyncio
import os


async def main() -> None:
    # -- 1. Configure logging (call once at startup) -------------------------
    print("1. Configure structured logging\n")

    env = os.environ.get("HIVEFLOW_ENV", "development")
    print(f"   HIVEFLOW_ENV = {env}")
    if env == "development":
        print("   Renderer: ConsoleRenderer (pretty, colored)")
    else:
        print("   Renderer: JSONRenderer (one JSON object per line)")

    from hiveflow.core.observability import configure_logging

    configure_logging()
    print("   Logging configured.\n")

    # -- 2. OTel toggle check -------------------------------------------------
    print("2. OpenTelemetry toggle\n")

    from hiveflow.core.observability import llm_duration, llm_token_usage, meter, tracer

    otel_enabled = os.environ.get("HIVEFLOW_OTEL_ENABLED", "false")
    print(f"   HIVEFLOW_OTEL_ENABLED = {otel_enabled}")
    print(f"   tracer:         {type(tracer).__name__ if tracer else 'None (no-op)'}")
    print(f"   meter:          {type(meter).__name__ if meter else 'None (no-op)'}")
    print(f"   llm_duration:   {type(llm_duration).__name__ if llm_duration else 'None (no overhead)'}")
    print(f"   llm_token_usage:{type(llm_token_usage).__name__ if llm_token_usage else ' None (no overhead)'}")

    if otel_enabled.lower() != "true":
        print("\n   To enable OTel metrics and spans:")
        print("     HIVEFLOW_OTEL_ENABLED=true uv run python examples/llm_providers/08_observability.py")

    # -- 3. Make a live call to see structured log events ---------------------
    print("\n3. Live call with structured logging\n")
    print("   Look for 'llm.chat.complete' events with provider_id, model,")
    print("   latency_ms, prompt_tokens, and completion_tokens fields.\n")

    from hiveflow.plugins.llm import LLMConfig, LLMMessage, get_llm_registry

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
        print("   No credentials available.")
        print("   Easiest: AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com")
        print("   (The structlog configuration still works -- you'd see log events on any call.)")
        return

    messages = [LLMMessage(role="user", content="Say 'hello' in one word.")]
    config = LLMConfig(max_tokens=10, temperature=0.0)

    for ref in targets:
        provider, model = registry.resolve_model(ref)
        config_with_model = LLMConfig(
            model=model, max_tokens=config.max_tokens, temperature=config.temperature,
        )
        try:
            response = await provider.chat(messages, config_with_model)
            print(f"   {provider.provider_id}: \"{response.content}\"")
        except Exception as exc:
            print(f"   {provider.provider_id}: skipped ({type(exc).__name__})")


if __name__ == "__main__":
    asyncio.run(main())
