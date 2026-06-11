#!/usr/bin/env python3
"""Example 07: LLM-generated team composition.

Demonstrates User Story 5 -- LLM-based team generation:
  1. Provide only a task description (no pre-built config)
  2. LLM generates a complete TeamConfiguration
  3. Capability gaps are detected and reported
  4. auto_approve=True rejects configs with blocking gaps
  5. New archetypes invented by the LLM are identified

Uses Azure OpenAI with RBAC authentication.

Usage:
    uv run python examples/agents_and_teams/07_llm_team_generation.py
"""

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hiveflow import TeamGenerator, WorkflowStatus
from hiveflow.core.teams import ArchetypeLibrary

AZURE_ENDPOINT = "https://foundry-aisbx-we.cognitiveservices.azure.com"
DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")


async def main() -> None:
    os.environ.setdefault("AZURE_OPENAI_ENDPOINT", AZURE_ENDPOINT)

    # Initialize Azure provider
    from hiveflow.plugins.llm.azure_provider import AzureOpenAIProvider

    provider = AzureOpenAIProvider(azure_endpoint=AZURE_ENDPOINT)

    # Initialize generator with archetype library for context
    generator = TeamGenerator()
    archetype_library = ArchetypeLibrary.default()

    print(f"Endpoint:   {AZURE_ENDPOINT}")
    print(f"Deployment: {DEPLOYMENT}")
    print()

    # -- Step 1: Generate team from LLM (auto_approve=False for inspection) ----
    task = "Build a comprehensive competitive analysis report for a SaaS product"
    print(f"Task: {task}")
    print("Generating team via LLM...\n")

    result = await generator.generate_team_from_llm(
        task_description=task,
        llm_provider=provider,
        model=DEPLOYMENT,
        archetype_library=archetype_library,
        auto_approve=False,  # Return for inspection even with gaps
    )

    # -- Step 2: Inspect the generated configuration ---------------------------
    config = result.config
    print(f"Generated team: {config.get('team_name', 'unnamed')}")
    print(f"Description:    {config.get('description', '')[:100]}")
    print(f"Agents:         {[a['id'] for a in config.get('agents', [])]}")
    print()

    # Show agent details
    print("Agent details:")
    for agent in config.get("agents", []):
        print(f"  {agent['id']:20s} role={agent.get('role', ''):30s} "
              f"type={agent.get('behavior_type', '')}")
    print()

    # Show workflow
    print("Workflow:")
    for step in config.get("workflow", {}).get("steps", []):
        nxt = step.get("next") or step.get("next_on_accept", "(end)")
        print(f"  {step['agent']:20s} [{step['type']}] -> {nxt}")
    print()

    # -- Step 3: Check capability gaps -----------------------------------------
    if result.capability_gaps:
        print(f"Capability gaps ({len(result.capability_gaps)}):")
        for gap in result.capability_gaps:
            print(f"  [{gap.severity:>10s}] {gap.resource_type}:{gap.resource_id}")
            print(f"              {gap.description}")
            if gap.fallback_strategy:
                print(f"              Fallback: {gap.fallback_strategy}")
        print()
        print(f"Has blocking gaps: {result.has_blocking_gaps}")
    else:
        print("No capability gaps detected *")
    print()

    # -- Step 4: Check new archetypes ------------------------------------------
    if result.new_archetypes:
        print(f"New archetypes invented by LLM ({len(result.new_archetypes)}):")
        for arch in result.new_archetypes:
            print(f"  {arch.get('id', 'unknown'):20s} role={arch.get('role', '')}")
    else:
        print("No new archetypes (all agents match known archetypes)")
    print()

    # -- Step 5: Show full config as JSON --------------------------------------
    print("Full generated config:")
    print(json.dumps(config, indent=2)[:1500])
    if len(json.dumps(config, indent=2)) > 1500:
        print("...")

    # -- Step 6: Demonstrate auto_approve blocking gap rejection ---------------
    print("\n--- auto_approve=True with blocking gaps ---")
    print("If the generated team requires unavailable tools and auto_approve=True,")
    print("a ValueError is raised to prevent running broken configurations.")


if __name__ == "__main__":
    asyncio.run(main())
