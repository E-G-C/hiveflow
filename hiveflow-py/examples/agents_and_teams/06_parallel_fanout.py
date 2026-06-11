#!/usr/bin/env python3
"""Example 06: Parallel fan-out with namespaced results.

Demonstrates User Story 4 -- Parallel fan-out:
  - An orchestrator agent decomposes a task into sub-tasks
  - A researcher agent runs in parallel on each sub-task
  - Results are collected in {agent}_parallel_results dict with item_N keys
  - Backward-compatible _outputs list and _output concatenated string

Uses Azure OpenAI with RBAC authentication.

Usage:
    uv run python examples/agents_and_teams/06_parallel_fanout.py
"""

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hiveflow import HiveFlow, TeamGenerator, WorkflowStatus

AZURE_ENDPOINT = "https://foundry-aisbx-we.cognitiveservices.azure.com"
DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")


async def main() -> None:
    os.environ.setdefault("AZURE_OPENAI_ENDPOINT", AZURE_ENDPOINT)

    # Use TeamGenerator for a planner -> researcher -> writer pipeline.
    # The planner (orchestrator) decomposes into sub-tasks, then the
    # researcher runs in parallel on each sub-task (parallel_fan_out).
    generator = TeamGenerator()
    config = generator.generate_team(
        task_description="Compare renewable energy sources",
        agent_types=["planner", "researcher", "writer"],
        model=f"azure:{DEPLOYMENT}",
        include_review=False,
    )

    print("Generated team config:")
    for step in config["workflow"]["steps"]:
        stype = step["type"]
        agent = step["agent"]
        nxt = step.get("next", "(end)")
        print(f"  {agent:12s} [{stype}] -> {nxt}")
    print()

    # Build and execute
    from hiveflow.plugins.llm.azure_provider import AzureOpenAIProvider

    provider = AzureOpenAIProvider(azure_endpoint=AZURE_ENDPOINT)
    agents, engine = generator.build(config, provider, model=f"azure:{DEPLOYMENT}")

    result = await engine.execute(
        agents=agents,
        initial_state={"task": "Compare solar, wind, and hydroelectric energy sources"},
    )

    print(f"Status: {result.status.value}")
    print(f"Steps:  {len(result.step_results)}")
    print()

    if result.status == WorkflowStatus.COMPLETED:
        state = result.state

        # Show the planner's decomposed sub-tasks
        planner_output = state.get("planner_output", "")
        print(f"--- planner ({len(planner_output.split())} words) ---")
        print(planner_output[:300])
        print()

        # Show parallel results (namespaced)
        parallel_results = state.get("researcher_parallel_results", {})
        if parallel_results:
            print(f"Parallel results: {len(parallel_results)} items")
            for key in sorted(parallel_results.keys()):
                item = parallel_results[key]
                output = item.get("researcher_output", "") if isinstance(item, dict) else ""
                words = len(output.split()) if output else 0
                print(f"  {key}: {words} words")
            print()

        # Backward-compatible list access
        outputs_list = state.get("researcher_outputs", [])
        print(f"researcher_outputs (list): {len(outputs_list)} items")

        # Concatenated string
        concat_output = state.get("researcher_output", "")
        print(f"researcher_output (concat): {len(concat_output.split())} words")
        print()

        # Final writer output
        writer_output = state.get("writer_output", "")
        print(f"--- writer ({len(writer_output.split())} words) ---")
        print(writer_output[:600])
    else:
        print(f"Error: {result.error}")


if __name__ == "__main__":
    asyncio.run(main())
