#!/usr/bin/env python3
"""Getting Started 01: Basic two-agent workflow.

Demonstrates how to:
  1. Create agents with roles and system prompts
  2. Wire them into a sequential workflow (researcher -> writer)
  3. Execute the workflow and inspect per-agent results
  4. Use event callbacks for live progress
  5. Use code-level assembly to combine outputs

This example uses a mock LLM provider -- no API keys required.

Usage:
    uv run python examples/getting_started/01_basic_workflow.py

Expected output:
    See sample_output/getting_started/01_basic_workflow.txt
"""

import asyncio

from hiveflow import (
    Agent,
    AgentBehaviorType,
    WorkflowEngine,
    WorkflowStatus,
    WorkflowStep,
)
from hiveflow.plugins.llm import LLMConfig, LLMMessage, LLMProvider, LLMResponse, TokenUsage


# ---------------------------------------------------------------------------
# Mock LLM provider -- returns deterministic responses for demonstration
# ---------------------------------------------------------------------------

class MockProvider(LLMProvider):
    """Simulates LLM responses so the example runs without API keys."""

    RESPONSES = {
        "researcher": (
            "Key findings on renewable energy:\n\n"
            "1. **Solar power** costs dropped 89% since 2010, making it the cheapest "
            "electricity source in most regions.\n"
            "2. **Wind energy** now provides 7% of global electricity, with offshore "
            "wind capacity growing 30% year-over-year.\n"
            "3. **Battery storage** costs fell 97% in three decades, enabling reliable "
            "renewable grids.\n"
            "4. **Green hydrogen** produced from renewables is emerging as a solution "
            "for hard-to-electrify sectors.\n"
            "5. **Job creation**: the renewable sector employs 13.7 million people "
            "worldwide (IRENA 2023)."
        ),
        "writer": (
            "# The Benefits of Renewable Energy\n\n"
            "Renewable energy is transforming the global power landscape. Solar costs "
            "have plummeted 89% since 2010, making it the cheapest source of new "
            "electricity in most of the world. Wind energy contributes 7% of global "
            "power and is accelerating through offshore installations.\n\n"
            "Advances in battery storage -- costs down 97% over three decades -- are "
            "solving intermittency, while green hydrogen opens pathways for sectors "
            "that are hard to electrify directly.\n\n"
            "Beyond climate benefits, the sector drives economic growth: 13.7 million "
            "jobs worldwide and counting. The transition to renewables is not just an "
            "environmental imperative -- it is an economic opportunity."
        ),
    }

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def plugin_id(self) -> str:
        return "mock"

    @property
    def description(self) -> str:
        return "Mock LLM for demonstration"

    async def chat(self, messages: list[LLMMessage], config: LLMConfig) -> LLMResponse:
        # Determine which agent is calling based on system prompt keywords
        system_msg = next((m.content for m in messages if m.role == "system"), "")
        if "research analyst" in system_msg.lower():
            content = self.RESPONSES["researcher"]
            usage = TokenUsage(prompt_tokens=45, completion_tokens=120, total_tokens=165)
        else:
            content = self.RESPONSES["writer"]
            usage = TokenUsage(prompt_tokens=180, completion_tokens=150, total_tokens=330)
        return LLMResponse(content=content, model="mock-model", usage=usage)


# ---------------------------------------------------------------------------
# Build agents and workflow
# ---------------------------------------------------------------------------

def build_agents(provider: LLMProvider) -> dict[str, Agent]:
    """Create a researcher -> writer agent pair."""
    researcher = Agent(
        agent_id="researcher",
        role="Research Analyst",
        system_prompt=(
            "You are a research analyst. Given a topic, provide 3-5 key "
            "findings with supporting data and sources."
        ),
        behavior_type=AgentBehaviorType.LLM_ONLY,
        llm_provider=provider,
    )

    writer = Agent(
        agent_id="writer",
        role="Report Writer",
        system_prompt=(
            "You are a professional writer. Based on the research findings "
            "provided, write a clear, concise report with a title and "
            "well-structured paragraphs."
        ),
        behavior_type=AgentBehaviorType.LLM_ONLY,
        llm_provider=provider,
        # Limit context to 4000 words so the writer isn't overwhelmed
        context_budget=4000,
    )

    return {"researcher": researcher, "writer": writer}


def build_workflow() -> WorkflowEngine:
    """Create a two-step sequential workflow with assembly."""
    steps = [
        WorkflowStep(
            agent="researcher",
            step_type="sequential",
            next_step="writer",
        ),
        WorkflowStep(
            agent="writer",
            step_type="sequential",
        ),
    ]

    # assembly_agents tells the engine to stitch these agents' full outputs
    # into a single `final_output` key in the result state.
    return WorkflowEngine(steps, assembly_agents=["writer"])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    """Execute a basic researcher -> writer workflow."""
    print("=" * 60)
    print("  HiveFlow -- Basic Two-Agent Workflow")
    print("=" * 60)

    provider = MockProvider()
    agents = build_agents(provider)
    engine = build_workflow()

    # Register an event callback for live progress
    def on_event(event_type: str, agent_id: str, data: dict) -> None:
        if event_type == "step_start":
            print(f"\n  > Starting: {agent_id}")
        elif event_type == "step_complete":
            print(f"  * Complete: {agent_id}")

    engine.on_event(on_event)

    # Execute the workflow
    result = await engine.execute(
        agents=agents,
        initial_state={"task": "Explain the benefits of renewable energy"},
    )

    # --------------- Display results ---------------

    print(f"\n{'-' * 60}")
    print(f"Workflow status: {result.status.value}")
    print(f"Steps executed:  {len(result.step_results)}")

    for step in result.step_results:
        output = result.state.get(f"{step.agent_id}_output", "")
        usage = result.state.get(f"{step.agent_id}_usage", {})
        words = len(output.split()) if output else 0
        tokens = usage.get("total_tokens", 0) if usage else 0
        print(f"  {step.agent_id:12s}  {words:4d} words  {tokens:4d} tokens")

    # Show the assembled final output
    final = result.state.get("final_output", "")
    if final:
        print(f"\n{'-' * 60}")
        print("Final assembled output:")
        print(f"{'-' * 60}")
        print(final)

    # Show state keys for learning
    print(f"\n{'-' * 60}")
    print(f"State keys: {sorted(result.state.keys())}")


if __name__ == "__main__":
    asyncio.run(main())
