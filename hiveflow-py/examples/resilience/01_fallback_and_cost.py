#!/usr/bin/env python3
"""Resilience Example: Fallback chains, retry providers, and cost tracking.

Demonstrates how to:
  1. Build a fallback chain with multiple providers
  2. Use RetryProvider for automatic retries
  3. Track costs across the workflow
  4. Access cost reports from agents

This example uses mock providers -- no API keys required.

Usage:
    uv run python examples/resilience/01_fallback_and_cost.py
"""

import asyncio

from hiveflow import (
    Agent,
    AgentBehaviorType,
    WorkflowEngine,
    WorkflowStep,
)
from hiveflow.core.cost import CostTracker
from hiveflow.core.fallback import FallbackChain, RetryProvider
from hiveflow.plugins.llm import LLMConfig, LLMMessage, LLMProvider, LLMResponse, TokenUsage
from hiveflow.plugins.llm.errors import LLMConnectionError


# ---------------------------------------------------------------------------
# Mock providers that simulate failures and successes
# ---------------------------------------------------------------------------


class FailingProvider(LLMProvider):
    """A provider that always fails -- simulates an outage."""

    def __init__(self, name: str) -> None:
        self._name = name
        self.call_count = 0

    @property
    def provider_name(self) -> str:
        return self._name

    @property
    def plugin_id(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"Failing provider ({self._name})"

    async def chat(self, messages: list[LLMMessage], config: LLMConfig) -> LLMResponse:
        self.call_count += 1
        raise LLMConnectionError(f"{self._name} is temporarily unavailable")


class WorkingProvider(LLMProvider):
    """A provider that succeeds -- the fallback target."""

    def __init__(self, name: str = "backup") -> None:
        self._name = name
        self.call_count = 0

    @property
    def provider_name(self) -> str:
        return self._name

    @property
    def plugin_id(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"Working provider ({self._name})"

    async def chat(self, messages: list[LLMMessage], config: LLMConfig) -> LLMResponse:
        self.call_count += 1
        return LLMResponse(
            content="Research findings: AI adoption increased 40% in 2025.",
            model="backup-model",
            usage=TokenUsage(prompt_tokens=50, completion_tokens=30, total_tokens=80),
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    print("=" * 60)
    print("  HiveFlow -- Resilience: Fallback Chain + Cost Tracking")
    print("=" * 60)

    # -- 1. Build providers -----------------------------------------------
    primary = FailingProvider("azure-eastus")
    secondary = FailingProvider("azure-westus")
    backup = WorkingProvider("openai-fallback")

    print("\n1. Providers:")
    print(f"   Primary:   {primary.plugin_id} (will fail)")
    print(f"   Secondary: {secondary.plugin_id} (will fail)")
    print(f"   Backup:    {backup.plugin_id} (will succeed)")

    # -- 2. Build fallback chain ------------------------------------------
    chain = FallbackChain([
        (RetryProvider(primary, max_retries=2), "gpt-4o"),
        (RetryProvider(secondary, max_retries=1), "gpt-4o"),
        (backup, "gpt-4o"),
    ])

    print("\n2. Fallback chain:")
    print("   azure-eastus (2 retries) -> azure-westus (1 retry) -> openai-fallback")

    # -- 3. Make a call through the chain ---------------------------------
    print("\n3. Calling through fallback chain...")

    response = await chain.chat(
        messages=[LLMMessage(role="user", content="Analyze AI trends")],
        config=LLMConfig(model="gpt-4o", max_tokens=200),
    )

    print(f"   Response: {response.content[:60]}...")
    print(f"   Primary calls:   {primary.call_count} (all failed)")
    print(f"   Secondary calls: {secondary.call_count} (all failed)")
    print(f"   Backup calls:    {backup.call_count} (succeeded)")

    # -- 4. Cost tracking -------------------------------------------------
    print("\n4. Cost tracking:")

    tracker = CostTracker()
    tracker.record("researcher", "gpt-4o", prompt_tokens=500, completion_tokens=200)
    tracker.record("researcher", "gpt-4o", prompt_tokens=300, completion_tokens=150)
    tracker.record("writer", "gpt-4o-mini", prompt_tokens=800, completion_tokens=400)
    tracker.record("reviewer", "gpt-4o-mini", prompt_tokens=200, completion_tokens=100)

    report = tracker.get_report()
    print(f"   Total tokens: {report.total_tokens}")
    print(f"   Total cost:   ${report.total_estimated_cost_usd:.4f}")
    print(f"   Duration:     {report.duration_seconds:.1f}s")

    print(f"\n   Per-agent breakdown:")
    for agent_id, summary in report.agent_summaries.items():
        print(
            f"     {agent_id:12s}  {summary.call_count} calls  "
            f"{summary.total_tokens:5d} tokens  "
            f"${summary.total_estimated_cost_usd:.4f}"
        )

    # -- 5. Use in a workflow ---------------------------------------------
    print(f"\n{'=' * 60}")
    print("5. Fallback chain in a workflow:")

    agent = Agent(
        agent_id="researcher",
        role="Researcher",
        system_prompt="Research the given topic and provide key findings.",
        behavior_type=AgentBehaviorType.LLM_ONLY,
        llm_provider=backup,  # In real code, use the chain
    )

    engine = WorkflowEngine(
        [WorkflowStep(agent="researcher", step_type="sequential")],
    )

    result = await engine.execute(
        agents={"researcher": agent},
        initial_state={"task": "Analyze AI adoption trends"},
    )

    print(f"   Status: {result.status.value}")
    output = result.state.get("researcher_output", "")
    print(f"   Output: {output[:80]}...")

    print(f"\n{'=' * 60}")
    print("  Summary")
    print("-" * 60)
    print("  FallbackChain cascades through providers on failure")
    print("  RetryProvider retries a single provider N times")
    print("  CostTracker records usage and estimates costs")
    print("  All compose together for production resilience")


if __name__ == "__main__":
    asyncio.run(main())
