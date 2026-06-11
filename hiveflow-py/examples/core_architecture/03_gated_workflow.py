#!/usr/bin/env python3
"""Example: Gated workflow steps -- workflow-level pauses for external approval.

Demonstrates how to:
1. Add a gated step between two agents in a workflow
2. Detect when a workflow pauses at a gate
3. Inspect the gate context (gate_id, description)

Gated steps differ from human_gate agents: they pause the entire workflow
without executing any agent, allowing an external process to review
intermediate results before the workflow continues.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hiveflow import (
    Agent,
    AgentBehaviorType,
    WorkflowEngine,
    WorkflowStatus,
    WorkflowStep,
)
from hiveflow.core.workflow import StepType
from hiveflow.plugins.llm import LLMConfig, LLMMessage, LLMProvider, LLMResponse, TokenUsage


class MockProvider(LLMProvider):
    """Returns a fixed draft response."""

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def plugin_id(self) -> str:
        return "mock"

    @property
    def description(self) -> str:
        return "Mock LLM"

    async def chat(self, messages: list[LLMMessage], config: LLMConfig) -> LLMResponse:
        return LLMResponse(
            content="Draft blog post about AI safety: AI systems should be designed with ...",
            model="mock",
            usage=TokenUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
        )


async def main() -> None:
    """Run a workflow with a gated step between drafter and publisher."""
    print("Gated Workflow Step Example")
    print("=" * 60)

    # Create agents
    drafter = Agent(
        agent_id="drafter",
        role="Content Drafter",
        system_prompt="Draft a blog post on the given topic.",
        behavior_type=AgentBehaviorType.LLM_ONLY,
        llm_provider=MockProvider(),
    )

    publisher = Agent(
        agent_id="publisher",
        role="Publisher",
        system_prompt="Publish the approved content.",
        behavior_type=AgentBehaviorType.LLM_ONLY,
        llm_provider=MockProvider(),
    )

    # Define workflow with a gated step between drafter and publisher.
    # The gate pauses the workflow so a human can review the draft.
    steps = [
        WorkflowStep(
            agent="drafter",
            step_type=StepType.SEQUENTIAL,
            next_step="review_gate",
        ),
        WorkflowStep(
            agent="review_gate",
            step_type=StepType.GATED,
            gate_id="review_gate",
            gate_description="Review the draft before publishing",
        ),
        # Publisher step would run after the gate is approved
        # (not reached in this demo since gated steps pause the workflow)
    ]

    engine = WorkflowEngine(steps)
    result = await engine.execute(
        {"drafter": drafter, "publisher": publisher},
        {"task": "Write a blog post about AI safety"},
    )

    # The workflow pauses at the gated step
    print(f"\nStatus: {result.status.value}")
    print(f"Drafter output: {result.state.get('drafter_output', '')[:80]}...")

    if result.status == WorkflowStatus.PAUSED:
        print(f"\nWorkflow paused at gate!")
        print(f"  Gate ID: {result.state.get('pending_gate_id')}")
        print(f"  Description: {result.state.get('pending_gate_description')}")
        print(f"  Awaiting approval: {result.state.get('awaiting_gate_approval')}")
        print("\nIn a real application, you would:")
        print("  1. Present the drafter's output to a reviewer")
        print("  2. Collect their approval via UI or API")
        print("  3. Call session.resume(responses) to continue the workflow")


if __name__ == "__main__":
    asyncio.run(main())
