#!/usr/bin/env python3
"""Example 02: Per-agent failure policies (on_failure: fail, retry, skip).

Demonstrates the on_failure field on AgentDefinition:
  - 'fail'  (default): agent error halts the workflow
  - 'retry': retries up to max_retries before failing
  - 'skip':  logs warning and proceeds with state unmodified

Also shows automatic exponential backoff for transient LLM errors (429/5xx)
which happens transparently before on_failure is triggered.

Uses Azure OpenAI with RBAC authentication.

Usage:
    uv run python examples/agents_and_teams/02_failure_policies.py
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

    # Team with different failure policies per agent
    team_config = {
        "team_name": "resilient_pipeline",
        "description": "Pipeline with mixed failure policies",
        "agents": [
            {
                "id": "analyst",
                "role": "Data Analyst",
                "system_prompt": "Analyze the given topic and provide key data points.",
                "behavior_type": "llm_only",
                "model": f"azure:{DEPLOYMENT}",
                # on_failure='retry' -- retries up to 3 times on failure
                "on_failure": "retry",
                "max_retries": 3,
            },
            {
                "id": "enricher",
                "role": "Context Enricher",
                "system_prompt": (
                    "Add context and real-world examples to the analysis. "
                    "If the analysis is thin, do your best."
                ),
                "behavior_type": "llm_only",
                "model": f"azure:{DEPLOYMENT}",
                # on_failure='skip' -- if this agent fails, workflow continues
                "on_failure": "skip",
            },
            {
                "id": "writer",
                "role": "Report Writer",
                "system_prompt": "Write a clean report based on the analysis and context.",
                "behavior_type": "llm_only",
                "model": f"azure:{DEPLOYMENT}",
                # on_failure='fail' (default) -- failure halts workflow
                "on_failure": "fail",
            },
        ],
        "workflow": {
            "steps": [
                {"agent": "analyst", "type": "sequential", "next": "enricher"},
                {"agent": "enricher", "type": "sequential", "next": "writer"},
                {"agent": "writer", "type": "sequential"},
            ],
        },
    }

    print("Failure Policies:")
    for agent in team_config["agents"]:
        policy = agent.get("on_failure", "fail (default)")
        retries = agent.get("max_retries", 1)
        print(f"  {agent['id']:12s} -> on_failure={policy}, max_retries={retries}")
    print()

    session = await hf.run(
        team=team_config,
        task="Analyze the impact of AI on software engineering jobs",
    )

    print(f"Status: {session.status.value}")
    if session.status == WorkflowStatus.COMPLETED:
        state = session.result.state
        for agent in team_config["agents"]:
            aid = agent["id"]
            output = state.get(f"{aid}_output", "")
            words = len(output.split()) if output else 0
            skipped = "(skipped)" if not output else ""
            print(f"  {aid}: {words} words {skipped}")
        print()
        print("--- writer output ---")
        print(state.get("writer_output", "(no output)")[:600])
    else:
        print(f"Error: {session.error}")


if __name__ == "__main__":
    asyncio.run(main())
