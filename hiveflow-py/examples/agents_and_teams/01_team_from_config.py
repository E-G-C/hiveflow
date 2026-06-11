#!/usr/bin/env python3
"""Example 01: Define and run a team from inline configuration.

Demonstrates User Story 1 -- the foundational capability:
  1. Create an inline team config with multiple agents
  2. Run the workflow end-to-end on Azure OpenAI via RBAC
  3. Inspect per-agent outputs, token usage, and session status

Uses Azure OpenAI with DefaultAzureCredential (Entra ID RBAC).

Usage:
    uv run python examples/agents_and_teams/01_team_from_config.py
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

    # Register the Azure provider so HiveFlow can resolve it
    registry = LLMProviderRegistry()
    registry.register(AzureOpenAIProvider(azure_endpoint=AZURE_ENDPOINT))

    hf = HiveFlow(llm_registry=registry)

    # Inline team config -- three agents in a sequential workflow
    team_config = {
        "team_name": "research_summary",
        "description": "Research a topic and produce a concise summary",
        "agents": [
            {
                "id": "researcher",
                "role": "Researcher",
                "system_prompt": (
                    "You are a research specialist. Given a topic, provide "
                    "3-5 key findings with supporting details. Be thorough."
                ),
                "behavior_type": "llm_only",
                "model": f"azure:{DEPLOYMENT}",
            },
            {
                "id": "writer",
                "role": "Summary Writer",
                "system_prompt": (
                    "You are a concise writer. Take the research findings and "
                    "produce a well-structured 200-word summary with clear sections."
                ),
                "behavior_type": "llm_only",
                "model": f"azure:{DEPLOYMENT}",
            },
            {
                "id": "reviewer",
                "role": "Quality Reviewer",
                "system_prompt": (
                    "You are a quality reviewer. Evaluate the summary for accuracy, "
                    "clarity, and completeness. Say 'APPROVED' if it meets standards, "
                    "or 'NEEDS REVISION' with specific feedback."
                ),
                "behavior_type": "llm_only",
                "model": f"azure:{DEPLOYMENT}",
            },
        ],
        "workflow": {
            "steps": [
                {"agent": "researcher", "type": "sequential", "next": "writer"},
                {"agent": "writer", "type": "sequential", "next": "reviewer"},
                {"agent": "reviewer", "type": "sequential"},
            ],
        },
    }

    print(f"Endpoint:   {AZURE_ENDPOINT}")
    print(f"Deployment: {DEPLOYMENT}")
    print(f"Team:       {team_config['team_name']}")
    print(f"Agents:     {[a['id'] for a in team_config['agents']]}")
    print()

    session = await hf.run(
        team=team_config,
        task="Explain the current state and future of quantum computing",
    )

    print(f"Status: {session.status.value}")
    print()

    if session.status == WorkflowStatus.COMPLETED:
        state = session.result.state
        for agent in team_config["agents"]:
            aid = agent["id"]
            output = state.get(f"{aid}_output", "")
            usage = state.get(f"{aid}_usage", {})
            tokens = usage.get("total_tokens", 0) if usage else 0
            words = len(output.split()) if output else 0
            print(f"--- {aid} ({words} words, {tokens} tokens) ---")
            print(output[:500] if output else "(no output)")
            print()
    else:
        print(f"Error: {session.error}")


if __name__ == "__main__":
    asyncio.run(main())
