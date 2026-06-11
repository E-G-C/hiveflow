#!/usr/bin/env python3
"""Getting Started 03: Dynamic team generation from a task description.

Demonstrates how to:
  1. Use TeamGenerator to create a team from just a task description
  2. Inspect the generated team config (agents, workflow, archetypes)
  3. Customize generation with agent_types and include_review
  4. Build live agents from the generated config (mock provider)

No LLM provider needed -- TeamGenerator uses deterministic archetype
matching (no LLM call) in this mode.

Usage:
    uv run python examples/getting_started/03_generated_team.py

Expected output:
    See sample_output/getting_started/03_generated_team.txt
"""

import json

from hiveflow import TeamGenerator
from hiveflow.plugins.llm import LLMConfig, LLMMessage, LLMProvider, LLMResponse, TokenUsage


# ---------------------------------------------------------------------------
# Mock provider for building agents (no live LLM needed)
# ---------------------------------------------------------------------------

class MockProvider(LLMProvider):
    """Returns fixed text so the example runs without API keys."""

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
        return LLMResponse(
            content="Generated content placeholder.",
            model="mock-model",
            usage=TokenUsage(prompt_tokens=10, completion_tokens=15, total_tokens=25),
        )


def main() -> None:
    """Generate, inspect, and build teams from task descriptions."""
    print("=" * 60)
    print("  HiveFlow -- Dynamic Team Generation")
    print("=" * 60)

    generator = TeamGenerator()

    # -- Example 1: Default generation --------------------------------
    print("\n1. Default generation (auto-select agent types):")
    task = "Analyze the pros and cons of remote work and write a policy recommendation"
    config = generator.generate_team(task_description=task, include_review=True)

    print(f"   Task:       {task[:60]}...")
    print(f"   Team name:  {config['team_name']}")
    print(f"   Agents:     {[a['id'] for a in config['agents']]}")

    print(f"\n   Workflow:")
    for step in config["workflow"]["steps"]:
        nxt = step.get("next") or step.get("next_on_accept", "(end)")
        print(f"     {step['agent']:15s} [{step['type']}] -> {nxt}")

    # -- Example 2: Specify agent types -------------------------------
    print(f"\n{'-' * 60}")
    print("2. Specify agent types:")
    config2 = generator.generate_team(
        task_description="Compare solar, wind, and hydroelectric energy",
        agent_types=["planner", "researcher", "writer"],
        include_review=False,
    )
    print(f"   Agents:   {[a['id'] for a in config2['agents']]}")
    print(f"   Workflow: {' -> '.join(s['agent'] for s in config2['workflow']['steps'])}")

    # -- Example 3: Inspect agent details -----------------------------
    print(f"\n{'-' * 60}")
    print("3. Agent details:")
    for agent in config["agents"]:
        behavior = agent["behavior_type"]
        tools = agent.get("tools", [])
        tools_str = f"  tools={tools}" if tools else ""
        print(f"   - {agent['id']:15s}  role={agent['role']:<25s}  [{behavior}]{tools_str}")
        # Show first 80 chars of system prompt
        prompt_preview = agent.get("system_prompt", "")[:80]
        print(f"     prompt: {prompt_preview}...")

    # -- Example 4: Build live agents from config ---------------------
    print(f"\n{'-' * 60}")
    print("4. Build live agents from generated config:")
    provider = MockProvider()
    agents, engine = generator.build(config, provider, model="mock-model")

    print(f"   Built {len(agents)} agents: {list(agents.keys())}")
    print(f"   Workflow engine: {len(engine.steps)} steps")
    for step in engine.steps:
        print(f"     {step.agent:15s} [{step.step_type}] -> {step.next_step or '(end)'}")

    # -- Example 5: Full config JSON ----------------------------------
    print(f"\n{'-' * 60}")
    print("5. Full generated config (JSON):")
    print(json.dumps(config, indent=2))

    print(f"\n{'-' * 60}")
    print("  Summary")
    print("-" * 60)
    print("  TeamGenerator.generate_team() -- deterministic archetype matching")
    print("  TeamGenerator.build()         -- creates Agent objects + WorkflowEngine")
    print("  For LLM-based generation, see agents_and_teams/07_llm_team_generation.py")


if __name__ == "__main__":
    main()
