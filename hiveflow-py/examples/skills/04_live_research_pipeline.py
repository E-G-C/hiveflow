#!/usr/bin/env python3
"""Example 04: Live multi-agent research synthesis pipeline with skills.

Three agents collaborate in a sequential workflow:
  1. researcher  (llm_only + research-synthesis skill) -- researches the topic
  2. writer      (llm_only + document-writing skill)   -- writes a report
  3. extractor   (llm_only + structured-extraction skill) -- extracts key facts

Each agent has a different skill injected, demonstrating how skills
shape agent behavior without changing the underlying LLM.

Uses Azure OpenAI with Entra ID RBAC authentication.

Usage:
    uv run python examples/skills/04_live_research_pipeline.py

    # Custom topic:
    uv run python examples/skills/04_live_research_pipeline.py \
        --topic "Pros and cons of microservices vs monolithic architecture"
"""

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hiveflow import HiveFlow, WorkflowStatus
from hiveflow.plugins.llm import LLMProviderRegistry
from hiveflow.plugins.llm.azure_provider import AzureOpenAIProvider
from hiveflow.plugins.skills import SkillRegistry

AZURE_ENDPOINT = "https://foundry-aisbx-we.cognitiveservices.azure.com"
DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")


async def main(topic: str) -> None:
    os.environ.setdefault("AZURE_OPENAI_ENDPOINT", AZURE_ENDPOINT)

    # Point all LLM tiers at the Azure deployment so the fallback chain
    # uses valid deployment names (default tiers reference openai: models).
    azure_model = f"azure:{DEPLOYMENT}"
    for tier in ("HIVEFLOW_FAST_LLM", "HIVEFLOW_SMART_LLM", "HIVEFLOW_STRATEGIC_LLM"):
        os.environ.setdefault(tier, azure_model)

    # ---- Registries ----
    llm_registry = LLMProviderRegistry()
    llm_registry.register(AzureOpenAIProvider(azure_endpoint=AZURE_ENDPOINT))

    builtin_dir = Path(__file__).resolve().parent.parent.parent / "hiveflow" / "skills"
    skill_registry = SkillRegistry(builtin_dir=builtin_dir)
    skill_registry.discover()

    hf = HiveFlow(llm_registry=llm_registry, skill_registry=skill_registry)

    # ---- Team config: three agents, each with a different skill ----
    azure_model = f"azure:{DEPLOYMENT}"
    team_config = {
        "team_name": "skilled_research_pipeline",
        "description": "Research, write, and extract -- each agent uses a different skill",
        "agents": [
            {
                "id": "researcher",
                "role": "Research Analyst",
                "system_prompt": (
                    "You are a research analyst. Follow the research-synthesis "
                    "skill methodology: catalog sources, cross-reference, weigh "
                    "evidence, and identify gaps. Provide 3-5 key findings with "
                    "confidence levels."
                ),
                "behavior_type": "llm_only",
                "model": azure_model,
                "skills": ["research-synthesis"],
            },
            {
                "id": "writer",
                "role": "Report Writer",
                "system_prompt": (
                    "You are a professional report writer. Follow the "
                    "document-writing skill methodology to produce a well-structured "
                    "400-word report from the research findings. Target a technical "
                    "audience. Include sections with clear headings."
                ),
                "behavior_type": "llm_only",
                "model": azure_model,
                "skills": ["document-writing"],
            },
            {
                "id": "extractor",
                "role": "Data Extractor",
                "system_prompt": (
                    "You are a data extraction specialist. Follow the "
                    "structured-extraction skill methodology to extract key facts "
                    "from the report. Extract: title, key_findings (list), "
                    "recommendations (list), confidence_assessment, and word_count. "
                    "Return valid JSON."
                ),
                "behavior_type": "llm_only",
                "model": azure_model,
                "skills": ["structured-extraction"],
            },
        ],
        "workflow": {
            "steps": [
                {"agent": "researcher", "type": "sequential", "next": "writer"},
                {"agent": "writer", "type": "sequential", "next": "extractor"},
                {"agent": "extractor", "type": "sequential"},
            ],
        },
    }

    print(f"Endpoint:   {AZURE_ENDPOINT}")
    print(f"Deployment: {DEPLOYMENT}")
    print(f"Topic:      {topic}")
    print(f"Pipeline:   researcher -> writer -> extractor")
    print(f"Skills:     research-synthesis, document-writing, structured-extraction")
    print()

    # ---- Execute ----
    t0 = time.time()
    session = await hf.run(team=team_config, task=topic)
    elapsed = time.time() - t0

    print(f"Status:  {session.status.value}")
    print(f"Elapsed: {elapsed:.1f}s")
    print()

    if session.status != WorkflowStatus.COMPLETED:
        print(f"Error: {session.error}")
        return

    state = session.result.state

    # ---- Per-agent summary ----
    total_tokens = 0
    for agent_def in team_config["agents"]:
        aid = agent_def["id"]
        output = state.get(f"{aid}_output", "")
        usage = state.get(f"{aid}_usage", {})
        tokens = usage.get("total_tokens", 0) if usage else 0
        total_tokens += tokens
        words = len(output.split()) if isinstance(output, str) else 0
        skill_name = agent_def["skills"][0]
        print(f"  {aid:15s}  skill={skill_name:25s}  {words:4d} words  {tokens:5d} tokens")

    print(f"  {'TOTAL':15s}  {'':25s}  {'':4s}        {total_tokens:5d} tokens")
    print()

    # ---- Show each agent's output ----
    for agent_def in team_config["agents"]:
        aid = agent_def["id"]
        output = state.get(f"{aid}_output", "")
        if not output:
            continue
        print("=" * 60)
        print(f"{aid.upper()} ({agent_def['role']}) -- skill: {agent_def['skills'][0]}")
        print("=" * 60)
        print(output[:2000])
        if len(output) > 2000:
            print(f"\n  ... ({len(output)} chars total)")
        print()


def cli() -> None:
    parser = argparse.ArgumentParser(
        description="Live multi-agent research pipeline with skills",
    )
    parser.add_argument(
        "--topic",
        default="The impact of large language models on software engineering practices in 2024-2025",
        help="Research topic",
    )
    args = parser.parse_args()
    asyncio.run(main(topic=args.topic))


if __name__ == "__main__":
    cli()
