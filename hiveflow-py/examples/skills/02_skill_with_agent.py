"""Example: Using Skills with Agents in a Team Configuration.

Demonstrates how to wire skills into agents through team configs.
Shows both llm_only (full instructions in prompt) and tool_user
(progressive disclosure via SkillActivationTool) patterns.

Requirements:
    - Azure OpenAI endpoint configured via AZURE_OPENAI_ENDPOINT env var
      or set endpoint below.
"""

import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock

from hiveflow.plugins.skills import SkillRegistry


def main() -> None:
    """Demonstrate skill wiring — no live LLM required."""
    from hiveflow.core.agent import Agent, AgentBehaviorType
    from hiveflow.plugins.skills import SkillActivationTool

    # ------------------------------------------------------------------
    # 1. Set up skill registry
    # ------------------------------------------------------------------
    builtin_dir = Path(__file__).resolve().parent.parent.parent / "hiveflow" / "skills"
    registry = SkillRegistry(builtin_dir=builtin_dir)
    registry.discover()
    print(f"Available skills: {registry.list_skills()}")

    # ------------------------------------------------------------------
    # 2. Create an llm_only agent with the code-review skill
    #    Full instructions are injected directly into the system prompt.
    # ------------------------------------------------------------------
    review_skill = registry.get_or_raise("code-review")
    reviewer = Agent(
        agent_id="reviewer",
        role="Code Reviewer",
        system_prompt="You are a senior code reviewer.",
        behavior_type=AgentBehaviorType.LLM_ONLY,
        skills=[review_skill],
    )
    messages = reviewer._build_messages({"task": "Review the auth module"})
    system_prompt = messages[0].content
    print("\n--- llm_only agent system prompt ---")
    print(f"Length: {len(system_prompt)} chars")
    assert '<skill name="code-review">' in system_prompt
    assert "Review process" in system_prompt
    print("Full skill instructions are in the system prompt.")

    # ------------------------------------------------------------------
    # 3. Create a tool_user agent with skills (progressive disclosure)
    #    Only metadata XML is in the prompt; SkillActivationTool is
    #    auto-injected for on-demand loading.
    # ------------------------------------------------------------------
    research_skill = registry.get_or_raise("research-synthesis")
    activation_tool = SkillActivationTool(
        available_skills={"research-synthesis": research_skill}
    )
    researcher = Agent(
        agent_id="researcher",
        role="Deep Researcher",
        system_prompt="You are a research specialist.",
        behavior_type=AgentBehaviorType.TOOL_USER,
        tools=[activation_tool],
        skills=[research_skill],
    )
    messages = researcher._build_messages({"task": "Research AI trends"})
    system_prompt = messages[0].content
    print("\n--- tool_user agent system prompt ---")
    print(f"Length: {len(system_prompt)} chars")
    assert "<available_skills>" in system_prompt
    assert "activate_skill" in system_prompt
    # Full instructions are NOT in the prompt
    assert "Source cataloging" not in system_prompt
    print("Only skill metadata is in the system prompt.")
    print("The LLM calls activate_skill tool to load full instructions.")

    # ------------------------------------------------------------------
    # 4. Simulate skill activation via the tool
    # ------------------------------------------------------------------
    result = asyncio.run(
        activation_tool.execute({"skill_name": "research-synthesis"})
    )
    print(f"\n--- Skill activation result ---")
    print(f"Skill: {result['skill_name']}")
    print(f"Instructions length: {len(result['instructions'])} chars")
    print(f"Base dir: {result['base_dir']}")

    # ------------------------------------------------------------------
    # 5. Team configuration example (dict format, like JSON/YAML config)
    # ------------------------------------------------------------------
    team_config = {
        "team_name": "review_team",
        "description": "Code review with research",
        "agents": [
            {
                "id": "researcher",
                "role": "Researcher",
                "system_prompt": "You research code patterns and best practices.",
                "behavior_type": "tool_user",
                "skills": ["research-synthesis"],
            },
            {
                "id": "reviewer",
                "role": "Code Reviewer",
                "system_prompt": "You review code thoroughly.",
                "behavior_type": "llm_only",
                "skills": ["code-review"],
            },
        ],
        "workflow": {
            "steps": [
                {"agent": "researcher", "type": "sequential", "next": "reviewer"},
                {"agent": "reviewer", "type": "sequential"},
            ]
        },
    }
    print("\n--- Team config with skills ---")
    for agent_def in team_config["agents"]:
        print(
            f"  Agent '{agent_def['id']}' ({agent_def['behavior_type']})"
            f" -> skills: {agent_def['skills']}"
        )

    print("\nDone. Skills are ready to use with live LLM providers.")


if __name__ == "__main__":
    main()
