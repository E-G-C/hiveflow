#!/usr/bin/env python3
"""Example 11: Dynamic delegation — orchestrator delegates to team members.

Demonstrates dynamic agent collaboration (User Story 1):
  1. Configure a team with collaboration enabled
  2. An orchestrator agent receives a complex task
  3. The orchestrator uses delegate_task to assign sub-tasks to team members
  4. Results flow back through the orchestrator for synthesis

The collaboration runtime automatically injects delegate_task and spawn_agent
tools into orchestrator agents when collaboration.enabled is true.

Uses Azure OpenAI with DefaultAzureCredential (Entra ID RBAC).

Usage:
    uv run python examples/agents_and_teams/11_delegation.py
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hiveflow import HiveFlow, WorkflowStatus
from hiveflow.plugins.llm import LLMProviderRegistry
from hiveflow.plugins.llm.azure_provider import AzureOpenAIProvider

AZURE_ENDPOINT = "https://foundry-aisbx-we.cognitiveservices.azure.com"
DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")


async def main() -> None:
    os.environ.setdefault("AZURE_OPENAI_ENDPOINT", AZURE_ENDPOINT)

    registry = LLMProviderRegistry()
    registry.register(AzureOpenAIProvider(azure_endpoint=AZURE_ENDPOINT))

    hf = HiveFlow(llm_registry=registry)

    # Team config with collaboration enabled.
    # The orchestrator gets delegate_task and spawn_agent tools injected
    # automatically. All agents get send_message and read_messages.
    team_config = {
        "team_name": "delegation_demo",
        "description": "Orchestrator delegates research sub-tasks to specialists",
        "collaboration": {
            "enabled": True,
            "max_delegation_depth": 2,
            "max_spawned_agents": 5,
        },
        "agents": [
            {
                "id": "coordinator",
                "role": "Research Coordinator",
                "system_prompt": (
                    "You are a research coordinator. When given a task:\n"
                    "1. Break it into 2-3 focused sub-tasks\n"
                    "2. Use the delegate_task tool to assign each sub-task "
                    "to the most appropriate team member\n"
                    "   - 'researcher' for gathering information\n"
                    "   - 'analyst' for data analysis and comparison\n"
                    "3. Synthesize all results into a coherent final answer\n\n"
                    "Always delegate before answering. Do not do the research yourself."
                ),
                "behavior_type": "orchestrator",
                "model": f"azure:{DEPLOYMENT}",
            },
            {
                "id": "researcher",
                "role": "Research Specialist",
                "system_prompt": (
                    "You are a research specialist. Provide thorough, factual "
                    "information on the topic you are given. Include specific "
                    "details, dates, and examples. Be concise but comprehensive."
                ),
                "behavior_type": "llm_only",
                "model": f"azure:{DEPLOYMENT}",
            },
            {
                "id": "analyst",
                "role": "Data Analyst",
                "system_prompt": (
                    "You are a data analyst. Analyze information critically, "
                    "identify trends and patterns, compare alternatives, and "
                    "provide structured insights. Use bullet points and tables "
                    "when appropriate."
                ),
                "behavior_type": "llm_only",
                "model": f"azure:{DEPLOYMENT}",
            },
        ],
        "workflow": {
            "steps": [
                {"agent": "coordinator", "type": "sequential"},
            ],
        },
    }

    print("=" * 60)
    print("Example 11: Dynamic Delegation")
    print("=" * 60)
    print(f"Endpoint:      {AZURE_ENDPOINT}")
    print(f"Deployment:    {DEPLOYMENT}")
    print(f"Collaboration: enabled (max_depth=2, max_spawn=5)")
    print(f"Agents:        {[a['id'] for a in team_config['agents']]}")
    print()

    task = "Compare the economic impact of renewable energy vs fossil fuels in the last decade"
    print(f"Task: {task}")
    print()

    session = await hf.run(team=team_config, task=task)

    print(f"Status: {session.status.value}")
    print()

    if session.status == WorkflowStatus.COMPLETED:
        state = session.result.state

        # Show coordinator output (the synthesized result)
        coordinator_output = state.get("coordinator_output", "")
        words = len(coordinator_output.split()) if coordinator_output else 0
        print(f"--- coordinator ({words} words) ---")
        print(coordinator_output[:1500] if coordinator_output else "(no output)")
        print()

        # Show delegation artifacts if present
        for key, val in sorted(state.items()):
            if key.endswith("_output") and key != "coordinator_output":
                agent_id = key.replace("_output", "")
                words = len(str(val).split()) if val else 0
                print(f"--- {agent_id} ({words} words) ---")
                print(str(val)[:500] if val else "(no output)")
                print()
    else:
        print(f"Error: {session.error}")


if __name__ == "__main__":
    asyncio.run(main())
