"""Example: Resilient LLM Provider with Fallback + Cost Tracking.

Demonstrates how to:
1. Create a ResilientLLMProvider that wraps any LLM provider
2. Auto-build a fallback chain from configured tiers (Strategic → Smart → Fast)
3. Track cost per call and accumulate per-agent totals
4. See the reduced max_tokens intermediate steps in action

Uses live Azure OpenAI via RBAC. Falls back to a mock demonstration
if AZURE_OPENAI_ENDPOINT is not set.

Prerequisites:
    AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com
    uv sync --extra llm-azure

Usage:
    AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com \
        uv run python examples/config_operations/01_resilient_provider.py
"""

import asyncio
import os

from hiveflow.core.config import HiveFlowConfig
from hiveflow.core.cost import CostTracker
from hiveflow.core.fallback import FallbackChain
from hiveflow.core.resilient_provider import ResilientLLMProvider
from hiveflow.plugins.llm import LLMConfig, LLMMessage, get_llm_registry


async def main() -> None:
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    if not endpoint:
        print("Set AZURE_OPENAI_ENDPOINT to run this example with live LLM.")
        print("  AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com")
        return

    registry = get_llm_registry()
    if "azure" not in registry.list_ids():
        print("Azure provider not available. Install with: uv sync --extra llm-azure")
        return

    # Resolve the Azure provider
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
    provider, model = registry.resolve_model(f"azure:{deployment}")
    print(f"Base provider: {provider.plugin_id} (deployment: {model})")

    # -- 1. Auto-build fallback chain from config tiers -----------------------
    print("\n--- 1. FallbackChain.from_tiers() ---")
    config = HiveFlowConfig(
        STRATEGIC_LLM=f"azure:{deployment}",
        SMART_LLM=f"azure:{deployment}",
        FAST_LLM=f"azure:{deployment}",
    )
    chain = FallbackChain.from_tiers(config, provider)
    print(f"Chain steps: {len(chain._providers)}")
    for p, m in chain._providers:
        print(f"  {p.plugin_id}: {m}")

    # -- 2. ResilientLLMProvider wraps provider with full pipeline -------------
    print("\n--- 2. ResilientLLMProvider ---")
    cost_tracker = CostTracker()
    resilient = ResilientLLMProvider.from_config(
        provider, config, cost_tracker=cost_tracker, agent_id="demo-agent"
    )
    print(f"Resilient provider: {resilient.plugin_id}")

    # -- 3. Make a live LLM call through the resilience pipeline ---------------
    print("\n--- 3. Live LLM call with resilience ---")
    messages = [
        LLMMessage(role="system", content="You are a helpful assistant."),
        LLMMessage(role="user", content="What is the capital of France? Be brief."),
    ]
    llm_config = LLMConfig(model=model, max_tokens=50, temperature=0.1)

    try:
        response = await resilient.chat(messages, llm_config)
        print(f"Response: {response.content}")
        if response.usage:
            print(f"Tokens:   {response.usage.total_tokens}")
    except Exception as e:
        print(f"  Call failed (expected if behind VNet): {type(e).__name__}")
        print(f"  This demonstrates the fallback exhaustion path.")
        print(f"  In production, the chain would cascade through multiple providers.")
        return

    # -- 4. Cost tracking report -----------------------------------------------
    print("\n--- 4. Cost tracking ---")
    report = cost_tracker.get_report()
    print(f"Total tokens:     {report.total_tokens}")
    print(f"Estimated cost:   ${report.total_estimated_cost_usd:.6f}")
    print(f"Agent summaries:  {list(report.agent_summaries.keys())}")

    for agent_id, summary in report.agent_summaries.items():
        print(f"  {agent_id}: {summary.call_count} calls, "
              f"{summary.total_tokens} tokens, "
              f"${summary.total_estimated_cost_usd:.6f}")

    # -- 5. Multiple calls accumulate -----------------------------------------
    print("\n--- 5. Multiple calls accumulate ---")
    messages[1] = LLMMessage(role="user", content="What is the capital of Germany?")
    await resilient.chat(messages, llm_config)

    messages[1] = LLMMessage(role="user", content="What is the capital of Spain?")
    await resilient.chat(messages, llm_config)

    report = cost_tracker.get_report()
    print(f"After 3 total calls:")
    print(f"  Total tokens: {report.total_tokens}")
    print(f"  Total cost:   ${report.total_estimated_cost_usd:.6f}")
    for agent_id, summary in report.agent_summaries.items():
        print(f"  {agent_id}: {summary.call_count} calls")


if __name__ == "__main__":
    asyncio.run(main())
