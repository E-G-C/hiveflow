#!/usr/bin/env python3
"""Example 03: Live code review using the code-review skill.

Sends a code snippet to an llm_only agent that has the code-review
skill injected into its system prompt. The agent follows the skill's
structured review methodology and returns a formatted review.

Uses Azure OpenAI with Entra ID RBAC authentication.

Usage:
    uv run python examples/skills/03_live_code_review.py
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

# Sample code to review
CODE_TO_REVIEW = '''
def process_user_data(request):
    """Process incoming user data from API request."""
    username = request.get("username")
    email = request.get("email")
    age = request.get("age")

    # Store in database
    query = f"INSERT INTO users (name, email, age) VALUES ('{username}', '{email}', {age})"
    db.execute(query)

    # Send welcome email
    import smtplib
    server = smtplib.SMTP("mail.company.com")
    server.sendmail("noreply@company.com", email, f"Welcome {username}!")

    # Log the event
    with open("/var/log/app.log", "a") as f:
        f.write(f"New user: {username}, {email}\\n")

    return {"status": "ok", "message": f"User {username} created"}
'''


async def main() -> None:
    os.environ.setdefault("AZURE_OPENAI_ENDPOINT", AZURE_ENDPOINT)

    # Point all LLM tiers at the Azure deployment so the fallback chain
    # uses valid deployment names (default tiers reference openai: models).
    azure_model = f"azure:{DEPLOYMENT}"
    for tier in ("HIVEFLOW_FAST_LLM", "HIVEFLOW_SMART_LLM", "HIVEFLOW_STRATEGIC_LLM"):
        os.environ.setdefault(tier, azure_model)

    # ---- Set up LLM registry ----
    llm_registry = LLMProviderRegistry()
    llm_registry.register(AzureOpenAIProvider(azure_endpoint=AZURE_ENDPOINT))

    # ---- Set up skill registry ----
    builtin_dir = Path(__file__).resolve().parent.parent.parent / "hiveflow" / "skills"
    skill_registry = SkillRegistry(builtin_dir=builtin_dir)
    skill_registry.discover()
    print(f"Skills available: {skill_registry.list_skills()}")

    # ---- Create HiveFlow with skill registry ----
    hf = HiveFlow(llm_registry=llm_registry, skill_registry=skill_registry)

    # ---- Team config: single agent with code-review skill ----
    team_config = {
        "team_name": "code_review",
        "description": "Code review with the code-review skill",
        "agents": [
            {
                "id": "reviewer",
                "role": "Senior Code Reviewer",
                "system_prompt": (
                    "You are a senior software engineer performing code reviews. "
                    "Follow the code-review skill methodology precisely. "
                    "Be specific with line references and provide actionable feedback."
                ),
                "behavior_type": "llm_only",
                "model": f"azure:{DEPLOYMENT}",
                "skills": ["code-review"],
            },
        ],
        "workflow": {
            "steps": [
                {"agent": "reviewer", "type": "sequential"},
            ],
        },
    }

    print(f"Endpoint:   {AZURE_ENDPOINT}")
    print(f"Deployment: {DEPLOYMENT}")
    print(f"Skill:      code-review")
    print(f"Code size:  {len(CODE_TO_REVIEW)} chars")
    print()

    # ---- Run workflow ----
    task = f"Review the following Python code:\n\n```python{CODE_TO_REVIEW}```"

    session = await hf.run(team=team_config, task=task)

    print(f"Status: {session.status.value}")
    print()

    if session.status == WorkflowStatus.COMPLETED:
        state = session.result.state
        output = state.get("reviewer_output", "")
        usage = state.get("reviewer_usage", {})
        tokens = usage.get("total_tokens", 0) if usage else 0
        print(f"Tokens used: {tokens}")
        print()
        print("=" * 60)
        print("CODE REVIEW RESULT")
        print("=" * 60)
        print(output)
    else:
        print(f"Error: {session.error}")


if __name__ == "__main__":
    asyncio.run(main())
