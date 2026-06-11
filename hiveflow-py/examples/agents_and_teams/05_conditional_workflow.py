#!/usr/bin/env python3
"""Example 05: Conditional workflow with review loop.

Demonstrates User Story 4 -- Conditional steps:
  - Reviewer evaluates content and accepts or rejects
  - On reject, loops back to the writer for revision
  - max_iterations prevents infinite loops (default: 3)
  - Ambiguous results (tied accept/reject scores) default to reject path

Uses Azure OpenAI with RBAC authentication.

Usage:
    uv run python examples/agents_and_teams/05_conditional_workflow.py
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

    # Team with a conditional review loop
    team_config = {
        "team_name": "review_loop_team",
        "description": "Writer -> Reviewer loop with conditional branching",
        "agents": [
            {
                "id": "writer",
                "role": "Technical Writer",
                "system_prompt": (
                    "Write clear, accurate technical content on the given topic. "
                    "If you receive feedback from a reviewer, address ALL their "
                    "concerns in your revision."
                ),
                "behavior_type": "llm_only",
                "model": f"azure:{DEPLOYMENT}",
            },
            {
                "id": "reviewer",
                "role": "Quality Reviewer",
                "system_prompt": (
                    "Review the content for accuracy, clarity, and completeness. "
                    "If the content meets your standards, respond with: APPROVED\n"
                    "If it needs work, respond with: NEEDS REVISION followed by "
                    "specific feedback."
                ),
                "behavior_type": "llm_only",
                "model": f"azure:{DEPLOYMENT}",
            },
            {
                "id": "publisher",
                "role": "Publisher",
                "system_prompt": "Format the approved content for publication. Add a title and section headers.",
                "behavior_type": "llm_only",
                "model": f"azure:{DEPLOYMENT}",
            },
        ],
        "workflow": {
            "steps": [
                {"agent": "writer", "type": "sequential", "next": "reviewer"},
                {
                    "agent": "reviewer",
                    "type": "conditional",
                    "next_on_accept": "publisher",
                    "next_on_reject": "writer",
                    "max_iterations": 3,
                },
                {"agent": "publisher", "type": "sequential"},
            ],
        },
    }

    print("Workflow: writer -> reviewer (conditional) -> publisher")
    print("  - Accept -> publisher")
    print("  - Reject -> writer (up to 3 iterations)")
    print("  - Ambiguous -> reject path (conservative default)")
    print()

    session = await hf.run(
        team=team_config,
        task="Explain how HTTPS/TLS encryption works in simple terms",
    )

    print(f"Status: {session.status.value}")
    print(f"Steps executed: {len(session.result.step_results)}")
    print()

    if session.status == WorkflowStatus.COMPLETED:
        state = session.result.state

        # Show each step's result
        for step in session.result.step_results:
            output = state.get(f"{step.agent_id}_output", "")
            words = len(output.split()) if isinstance(output, str) else 0
            print(f"  {step.agent_id:12s} [{step.step_type}] -> {words} words")

        print()
        print("--- publisher output ---")
        print(state.get("publisher_output", "(no output)")[:800])
    elif session.status == WorkflowStatus.FAILED:
        if "exceeded maximum iterations" in (session.error or ""):
            print("Review loop exceeded max iterations (reviewer kept rejecting)")
        print(f"Error: {session.error}")


if __name__ == "__main__":
    asyncio.run(main())
