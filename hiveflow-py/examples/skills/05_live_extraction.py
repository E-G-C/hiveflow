#!/usr/bin/env python3
"""Example 05: Live structured extraction from unstructured text.

Sends a messy meeting transcript to an llm_only agent equipped with
the structured-extraction skill. The skill's methodology guides the
LLM to produce clean JSON with confidence annotations.

Uses Azure OpenAI with Entra ID RBAC authentication.

Usage:
    uv run python examples/skills/05_live_extraction.py
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hiveflow import HiveFlow, WorkflowStatus
from hiveflow.plugins.llm import LLMProviderRegistry
from hiveflow.plugins.llm.azure_provider import AzureOpenAIProvider
from hiveflow.plugins.skills import SkillRegistry

AZURE_ENDPOINT = "https://foundry-aisbx-we.cognitiveservices.azure.com"
DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")

# Unstructured meeting transcript to extract from
MEETING_TRANSCRIPT = """
Team standup - March 1, 2025 (10:00 AM EST)

Participants: Sarah Chen (PM), Marcus Johnson (Backend Lead), Priya Patel
(Frontend), Dave Kim (QA), Lisa Wong (Design)

Sarah: Good morning everyone. Let's start with updates. Marcus, where are
we on the payment integration?

Marcus: The Stripe integration is about 80% done. I finished the webhook
handlers yesterday and started on the retry logic. Main blocker is that
we still need the production API keys from finance - I sent the request
last Wednesday but haven't heard back. ETA is end of next week if I get
the keys by Friday.

Priya: On my end, the new dashboard redesign is in code review. Lisa and I
finalized the mobile responsive layouts on Monday. I have two PRs open -
PR #447 for the chart components and PR #452 for the settings page. The
chart PR needs Marcus to review the API integration part.

Dave: I found 3 critical bugs in the checkout flow yesterday. Bug #1201
is a race condition when users double-click the submit button - it creates
duplicate orders. Bug #1203 is an XSS vulnerability in the product search.
Bug #1205 is a memory leak in the WebSocket connection handler that
crashes the server after about 6 hours. I'd say #1203 is the highest
priority since it's a security issue.

Lisa: Design specs for the onboarding flow v2 are ready. I uploaded them
to Figma yesterday - 12 screens total. I also need feedback on the two
color palette options I shared in Slack. We need to decide by Wednesday
so I can finalize the design system tokens.

Sarah: OK great. Action items: Marcus, follow up with finance today on
those API keys. Priya, can you get those PRs merged by Thursday? Dave,
file the XSS bug as P0 and assign it to Marcus. Lisa, set up a 30-minute
meeting to review the color options tomorrow. I'll escalate the API key
issue if we don't hear back by EOD. Next standup is Wednesday same time.
"""


async def main() -> None:
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

    # ---- Team config ----
    team_config = {
        "team_name": "meeting_extraction",
        "description": "Extract structured data from meeting transcripts",
        "agents": [
            {
                "id": "extractor",
                "role": "Meeting Data Extractor",
                "system_prompt": (
                    "You are a meeting intelligence specialist. Follow the "
                    "structured-extraction skill methodology precisely. "
                    "Extract these fields from the meeting transcript:\n"
                    "- meeting_date (ISO format)\n"
                    "- participants (list of {name, role})\n"
                    "- topics_discussed (list of strings)\n"
                    "- action_items (list of {assignee, task, deadline})\n"
                    "- blockers (list of {description, owner, severity})\n"
                    "- bugs_reported (list of {id, description, priority, assignee})\n"
                    "- decisions_made (list of strings)\n"
                    "- next_meeting (date/time if mentioned)\n\n"
                    "Return valid JSON following the skill's output format."
                ),
                "behavior_type": "llm_only",
                "model": f"azure:{DEPLOYMENT}",
                "skills": ["structured-extraction"],
            },
        ],
        "workflow": {
            "steps": [
                {"agent": "extractor", "type": "sequential"},
            ],
        },
    }

    print(f"Endpoint:   {AZURE_ENDPOINT}")
    print(f"Deployment: {DEPLOYMENT}")
    print(f"Skill:      structured-extraction")
    print(f"Transcript: {len(MEETING_TRANSCRIPT)} chars")
    print()

    # ---- Run ----
    task = (
        "Extract structured data from this meeting transcript. "
        "Follow the structured-extraction methodology.\n\n"
        f"{MEETING_TRANSCRIPT}"
    )
    session = await hf.run(team=team_config, task=task)

    print(f"Status: {session.status.value}")
    print()

    if session.status == WorkflowStatus.COMPLETED:
        state = session.result.state
        output = state.get("extractor_output", "")
        usage = state.get("extractor_usage", {})
        tokens = usage.get("total_tokens", 0) if usage else 0
        print(f"Tokens used: {tokens}")
        print()
        print("=" * 60)
        print("EXTRACTION RESULT")
        print("=" * 60)
        print(output)
    else:
        print(f"Error: {session.error}")


if __name__ == "__main__":
    asyncio.run(main())
