#!/usr/bin/env python3
"""Example 12: Spawn specialists from archetypes and delegate work.

Demonstrates dynamic agent collaboration (User Story 2):
  1. Configure a lean team with just an orchestrator
  2. The orchestrator dynamically spawns specialist agents from archetypes
  3. Spawned agents are delegated sub-tasks
  4. Results are synthesized by the orchestrator

This shows how a single orchestrator can build its own team at runtime
based on the task requirements, using the archetype library.

Uses Azure OpenAI with DefaultAzureCredential (Entra ID RBAC).

Usage:
    uv run python examples/agents_and_teams/12_spawn_and_delegate.py
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hiveflow import HiveFlow, WorkflowStatus
from hiveflow.core.teams import ArchetypeLibrary
from hiveflow.plugins.llm import LLMProviderRegistry
from hiveflow.plugins.llm.azure_provider import AzureOpenAIProvider

AZURE_ENDPOINT = "https://foundry-aisbx-we.cognitiveservices.azure.com"
DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")


async def main() -> None:
    os.environ.setdefault("AZURE_OPENAI_ENDPOINT", AZURE_ENDPOINT)

    # Show available archetypes the orchestrator can spawn
    library = ArchetypeLibrary.default()
    print("=" * 60)
    print("Example 12: Spawn Specialists and Delegate")
    print("=" * 60)
    print()
    print("Available archetypes for spawning:")
    for name in library.list_archetypes():
        arch = library.get(name)
        print(f"  - {name:20s}  role={arch['role']}")
    print()

    registry = LLMProviderRegistry()
    registry.register(AzureOpenAIProvider(azure_endpoint=AZURE_ENDPOINT))

    hf = HiveFlow(llm_registry=registry)

    # Minimal team: just an orchestrator. It will spawn helpers as needed.
    team_config = {
        "team_name": "dynamic_spawn_demo",
        "description": "Orchestrator spawns specialists on-demand from archetypes",
        "collaboration": {
            "enabled": True,
            "max_delegation_depth": 2,
            "max_spawned_agents": 5,
            "allow_recursive_orchestrators": False,
        },
        "agents": [
            {
                "id": "lead",
                "role": "Project Lead",
                "system_prompt": (
                    "You are a project lead who builds ad-hoc teams. "
                    "When given a complex task:\n"
                    "1. Decide what specialists you need\n"
                    "2. Use spawn_agent to create them from available archetypes "
                    "(researcher, writer, reviewer, analyst, planner, coder)\n"
                    "   OR create a custom agent with spawn_agent using a "
                    "custom_definition\n"
                    "3. Use delegate_task to assign work to each spawned agent\n"
                    "4. Collect results and produce a final deliverable\n\n"
                    "You must spawn at least 2 agents and delegate to them. "
                    "Do not do the work yourself."
                ),
                "behavior_type": "orchestrator",
                "model": f"azure:{DEPLOYMENT}",
            },
        ],
        "workflow": {
            "steps": [
                {"agent": "lead", "type": "sequential"},
            ],
        },
    }

    print(f"Endpoint:      {AZURE_ENDPOINT}")
    print(f"Deployment:    {DEPLOYMENT}")
    print(f"Team:          1 orchestrator (spawns helpers dynamically)")
    print()

    task = (
        "Write a brief technology assessment on WebAssembly (Wasm): "
        "research its current capabilities, analyze adoption trends, "
        "and produce a 200-word executive summary"
    )
    print(f"Task: {task}")
    print()

    session = await hf.run(team=team_config, task=task)

    print(f"Status: {session.status.value}")
    print()

    if session.status == WorkflowStatus.COMPLETED:
        state = session.result.state

        # Show the lead's synthesized output
        lead_output = state.get("lead_output", "")
        words = len(lead_output.split()) if lead_output else 0
        print(f"--- lead ({words} words) ---")
        print(lead_output[:2000] if lead_output else "(no output)")
        print()

        # Show outputs from any dynamically spawned agents
        print("--- spawned agent outputs ---")
        for key in sorted(state.keys()):
            if key.endswith("_output") and key != "lead_output":
                agent_id = key.replace("_output", "")
                val = state[key]
                words = len(str(val).split()) if val else 0
                print(f"  {agent_id} ({words} words): {str(val)[:300]}...")
                print()
    else:
        print(f"Error: {session.error}")


if __name__ == "__main__":
    asyncio.run(main())
