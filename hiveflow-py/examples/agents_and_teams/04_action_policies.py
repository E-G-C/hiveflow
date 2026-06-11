#!/usr/bin/env python3
"""Example 04: Action executor with dry_run and require_approval policies.

Demonstrates User Story 3 -- Action Safety Policies:
  - dry_run:          LLM proposes tool calls but tools are NOT executed.
                      Plan is stored in {agent}_dry_run_plan.
  - require_approval: LLM proposes tool calls, workflow pauses for human
                      approval before executing.
  - auto:             Tools execute immediately with full audit trail.

Each action records enhanced fields: policy, reversible, rollback_action,
workflow_run_id.

Usage:
    uv run python examples/agents_and_teams/04_action_policies.py
"""

import asyncio
import json
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

    # Team with a dry_run action executor.
    # The agent will propose tool calls but NOT execute them.
    team_config = {
        "team_name": "safe_deployment",
        "description": "Deployment pipeline with dry-run safety",
        "agents": [
            {
                "id": "planner",
                "role": "Deployment Planner",
                "system_prompt": (
                    "Plan the deployment steps for the given task. "
                    "List each step clearly with the action to take."
                ),
                "behavior_type": "llm_only",
                "model": f"azure:{DEPLOYMENT}",
            },
            {
                "id": "deployer",
                "role": "Deployment Executor",
                "system_prompt": (
                    "Execute the deployment plan. You have tools available "
                    "but this is a DRY RUN -- actions will be recorded but "
                    "not actually executed."
                ),
                "behavior_type": "action_executor",
                "action_policy": "dry_run",
                "model": f"azure:{DEPLOYMENT}",
                "rollback_on_failure": True,
                "rollback_action": "undo_deploy",
            },
            {
                "id": "reporter",
                "role": "Status Reporter",
                "system_prompt": (
                    "Summarize what the deployment plan would do based on "
                    "the dry-run results. Report any concerns."
                ),
                "behavior_type": "llm_only",
                "model": f"azure:{DEPLOYMENT}",
            },
        ],
        "workflow": {
            "steps": [
                {"agent": "planner", "type": "sequential", "next": "deployer"},
                {"agent": "deployer", "type": "sequential", "next": "reporter"},
                {"agent": "reporter", "type": "sequential"},
            ],
        },
    }

    print("Action Policies:")
    for agent in team_config["agents"]:
        policy = agent.get("action_policy", "n/a")
        behavior = agent["behavior_type"]
        rollback = agent.get("rollback_on_failure", False)
        print(f"  {agent['id']:12s} behavior={behavior:20s} policy={policy} rollback={rollback}")
    print()

    session = await hf.run(
        team=team_config,
        task="Deploy the new API version v2.1 to staging environment",
    )

    print(f"Status: {session.status.value}")
    if session.status == WorkflowStatus.COMPLETED:
        state = session.result.state

        # Show dry-run plan (proposed actions that were NOT executed)
        dry_run_plan = state.get("deployer_dry_run_plan")
        if dry_run_plan:
            print(f"\nDry-run plan ({len(dry_run_plan)} proposed actions):")
            for action in dry_run_plan:
                print(f"  Tool: {action.get('tool', 'unknown')}")
                print(f"  Args: {json.dumps(action.get('arguments', {}))}")

        # Show action records with enhanced fields
        records = state.get("deployer_action_records", [])
        if records:
            print(f"\nAction records ({len(records)} entries):")
            for rec in records:
                print(f"  tool={rec.get('tool')} status={rec.get('status')} "
                      f"policy={rec.get('policy')} reversible={rec.get('reversible')}")

        print("\n--- reporter output ---")
        print(state.get("reporter_output", "(no output)")[:500])
    elif session.status == WorkflowStatus.PAUSED:
        print("Workflow paused -- awaiting approval")
        print(f"Proposed actions: {session.result.state.get('deployer_proposed_actions', [])}")
    else:
        print(f"Error: {session.error}")


if __name__ == "__main__":
    asyncio.run(main())
