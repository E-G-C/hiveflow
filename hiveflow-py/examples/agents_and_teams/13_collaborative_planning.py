#!/usr/bin/env python3
"""Example 13: Collaborative task planning with concurrent execution.

Demonstrates dynamic agent collaboration (User Story 4):
  1. Configure a team with an orchestrator and two specialists
  2. The orchestrator uses plan_and_execute to create a structured plan
  3. Independent sub-tasks in the plan run concurrently
  4. Dependent sub-tasks wait for prerequisites to complete
  5. The orchestrator receives the synthesized plan results

The plan_and_execute tool accepts a structured plan with sub-tasks,
validates the dependency DAG, and executes groups concurrently.

Uses Azure OpenAI with DefaultAzureCredential (Entra ID RBAC).

Usage:
    uv run python examples/agents_and_teams/13_collaborative_planning.py
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

    # Team with orchestrator + specialists for structured planning.
    # The orchestrator can also use 'auto' assignment (system picks best agent)
    # or 'spawn:{archetype}' to create agents on-the-fly within the plan.
    team_config = {
        "team_name": "planning_demo",
        "description": "Orchestrator creates and executes structured task plans",
        "collaboration": {
            "enabled": True,
            "max_delegation_depth": 2,
            "max_spawned_agents": 5,
        },
        "agents": [
            {
                "id": "planner",
                "role": "Strategic Planner",
                "system_prompt": (
                    "You are a strategic planner. When given a complex task:\n"
                    "1. Decompose it into 3-4 sub-tasks with clear dependencies\n"
                    "2. Use the plan_and_execute tool to execute the plan\n\n"
                    "Plan structure rules:\n"
                    "- Each sub-task has an id (e.g., 'st_1'), description, "
                    "and assigned_to\n"
                    "- Use 'researcher' for information gathering\n"
                    "- Use 'writer' for content creation\n"
                    "- Use depends_on to specify ordering (e.g., writing depends "
                    "on research)\n"
                    "- Independent sub-tasks (no shared dependencies) run in "
                    "parallel automatically\n\n"
                    "After the plan executes, synthesize the results into "
                    "a final coherent response."
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
                    "details and examples. Keep your response focused and under "
                    "200 words."
                ),
                "behavior_type": "llm_only",
                "model": f"azure:{DEPLOYMENT}",
            },
            {
                "id": "writer",
                "role": "Technical Writer",
                "system_prompt": (
                    "You are a technical writer. Take the provided information "
                    "and produce a well-structured, clear piece of writing. "
                    "Use headings, bullet points, and concise language. "
                    "Keep your response under 300 words."
                ),
                "behavior_type": "llm_only",
                "model": f"azure:{DEPLOYMENT}",
            },
        ],
        "workflow": {
            "steps": [
                {"agent": "planner", "type": "sequential"},
            ],
        },
    }

    print("=" * 60)
    print("Example 13: Collaborative Task Planning")
    print("=" * 60)
    print(f"Endpoint:      {AZURE_ENDPOINT}")
    print(f"Deployment:    {DEPLOYMENT}")
    print(f"Agents:        {[a['id'] for a in team_config['agents']]}")
    print(f"Collaboration: enabled (plan_and_execute + delegate_task)")
    print()

    task = (
        "Create a technology brief on large language models (LLMs): "
        "research the latest developments in 2024-2025, "
        "analyze the key technical challenges remaining, "
        "and write a 300-word executive summary combining both"
    )
    print(f"Task: {task}")
    print()
    print("The planner will create a structured plan where research tasks")
    print("run in parallel, and the writing task depends on both.")
    print()

    session = await hf.run(team=team_config, task=task)

    print(f"Status: {session.status.value}")
    print()

    if session.status == WorkflowStatus.COMPLETED:
        state = session.result.state

        # Show the planner's final output
        planner_output = state.get("planner_output", "")
        words = len(planner_output.split()) if planner_output else 0
        print(f"--- planner ({words} words) ---")
        print(planner_output[:2000] if planner_output else "(no output)")
        print()

        # Show delegation outputs
        for key in sorted(state.keys()):
            if key.endswith("_output") and key != "planner_output":
                agent_id = key.replace("_output", "")
                val = state[key]
                words = len(str(val).split()) if val else 0
                print(f"--- {agent_id} ({words} words) ---")
                print(str(val)[:500] if val else "(no output)")
                print()
    else:
        print(f"Error: {session.error}")


if __name__ == "__main__":
    asyncio.run(main())
