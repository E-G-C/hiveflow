#!/usr/bin/env python3
"""Example 03: Browse and compose teams from the archetype library.

Demonstrates User Story 2 -- Archetypes:
  1. Load the default ArchetypeLibrary (6 built-in archetypes from JSON files)
  2. List and inspect archetypes
  3. Compose a team by selecting archetypes
  4. Run the composed team on Azure OpenAI

Archetypes are copied inline -- the saved team is self-contained.

Usage:
    uv run python examples/agents_and_teams/03_archetypes.py
"""

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hiveflow import HiveFlow, TeamGenerator, WorkflowStatus
from hiveflow.core.teams import ArchetypeLibrary
from hiveflow.plugins.llm import LLMProviderRegistry
from hiveflow.plugins.llm.azure_provider import AzureOpenAIProvider

AZURE_ENDPOINT = "https://foundry-aisbx-we.cognitiveservices.azure.com"
DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")


async def main() -> None:
    os.environ.setdefault("AZURE_OPENAI_ENDPOINT", AZURE_ENDPOINT)

    # -- Step 1: Load and browse archetypes ------------------------------------
    library = ArchetypeLibrary.default()
    print("Available archetypes:")
    for name in library.list_archetypes():
        arch = library.get(name)
        print(f"  - {name:20s}  role={arch['role']:<25s}  type={arch['behavior_type']}")
    print()

    # -- Step 2: Compose a team from selected archetypes ----------------------
    #   We pick researcher + writer + reviewer for a classic research pipeline.
    selected = ["researcher", "writer", "reviewer"]
    print(f"Composing team from: {selected}")

    agents = []
    for name in selected:
        arch = library.get(name)
        agent_def = {
            **arch,
            "id": name,
            "model": f"azure:{DEPLOYMENT}",
        }
        # Strip tools that are not registered locally (e.g. web_search).
        # Without a running tool plugin the build step would fail.
        if agent_def.get("tools"):
            agent_def["tools"] = []
            if agent_def.get("behavior_type") == "tool_user":
                agent_def["behavior_type"] = "llm_only"
        agents.append(agent_def)

    team_config = {
        "team_name": "archetype_composed_team",
        "description": "Team composed from library archetypes",
        "agents": agents,
        "workflow": {
            "steps": [
                {"agent": "researcher", "type": "sequential", "next": "writer"},
                {"agent": "writer", "type": "sequential", "next": "reviewer"},
                {"agent": "reviewer", "type": "sequential"},
            ],
        },
    }

    print(f"\nComposed team config:")
    print(json.dumps(team_config, indent=2)[:800])
    print("...\n")

    # -- Step 3: Run the composed team ----------------------------------------
    registry = LLMProviderRegistry()
    registry.register(AzureOpenAIProvider(azure_endpoint=AZURE_ENDPOINT))

    hf = HiveFlow(llm_registry=registry)
    session = await hf.run(
        team=team_config,
        task="Compare the benefits and risks of nuclear fusion energy",
    )

    print(f"Status: {session.status.value}")
    if session.status == WorkflowStatus.COMPLETED:
        state = session.result.state
        for aid in selected:
            output = state.get(f"{aid}_output", "")
            words = len(output.split()) if output else 0
            print(f"  {aid}: {words} words")
        print()
        print("--- reviewer output ---")
        print(state.get("reviewer_output", "(no output)")[:500])
    else:
        print(f"Error: {session.error}")


if __name__ == "__main__":
    asyncio.run(main())
