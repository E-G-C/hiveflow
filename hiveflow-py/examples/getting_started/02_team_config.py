#!/usr/bin/env python3
"""Getting Started 02: Load and validate a team configuration.

Demonstrates how to:
  1. Load a team configuration from a JSON file (built-in template)
  2. Inspect agents, workflow steps, state schema, and publish settings
  3. Export the JSON Schema for documentation
  4. Create a team configuration from an inline dictionary

No LLM provider needed -- this is pure configuration inspection.

Usage:
    uv run python examples/getting_started/02_team_config.py

Expected output:
    See sample_output/getting_started/02_team_config.txt
"""

import json
from pathlib import Path

from hiveflow import TeamConfiguration


def demo_from_file() -> None:
    """Load and display a team configuration from a JSON template file."""
    print("=" * 60)
    print("  Load Team Configuration from File")
    print("=" * 60)

    template_path = (
        Path(__file__).resolve().parents[2]
        / "hiveflow" / "templates" / "research_report.json"
    )

    if not template_path.exists():
        print(f"  Template not found: {template_path}")
        print("  (This is expected if templates haven't been created yet)")
        return

    config = TeamConfiguration.from_json_file(str(template_path))

    print(f"\nTeam:        {config.team_name}")
    print(f"Description: {config.description}")

    print(f"\nAgents ({len(config.agents)}):")
    for agent in config.agents:
        print(f"  - {agent.id:20s}  role={agent.role}")
        print(f"    behavior={agent.behavior_type.value}  model={agent.model or '(default)'}")
        if agent.tools:
            print(f"    tools: {', '.join(agent.tools)}")

    print(f"\nWorkflow ({len(config.workflow.steps)} steps):")
    for i, step in enumerate(config.workflow.steps, 1):
        step_info = f"  {i}. {step.agent} [{step.type.value}]"
        if step.next:
            step_info += f" -> {step.next}"
        elif step.next_on_accept or step.next_on_reject:
            step_info += f" (accept->{step.next_on_accept}, reject->{step.next_on_reject})"
        print(step_info)

    if config.state_schema:
        print(f"\nState Schema:")
        print(f"  Required keys:    {', '.join(config.state_schema.required_keys)}")
        print(f"  Agent I/O maps:   {len(config.state_schema.agent_io)} agents")
        print(f"  Enforcement mode: {config.state_schema.enforcement_mode}")

    if config.publish:
        print(f"\nPublish Configuration:")
        print(f"  Formats: {', '.join(config.publish.formats)}")
        print(f"  Style:   {config.publish.style}")
        print(f"  Output:  {config.publish.output_dir}")

    # Export JSON Schema
    schema = config.to_json_schema()
    print(f"\nJSON Schema: {len(schema.get('properties', {}))} top-level properties")


def demo_from_dict() -> None:
    """Create a team configuration from an inline dictionary."""
    print(f"\n{'=' * 60}")
    print("  Create Team Configuration from Dictionary")
    print("=" * 60)

    team_dict = {
        "team_name": "quick_summarizer",
        "description": "Summarize a topic in two steps",
        "agents": [
            {
                "id": "researcher",
                "role": "Researcher",
                "system_prompt": "Research the given topic thoroughly.",
                "behavior_type": "llm_only",
                "model": "openai:gpt-4o-mini",
            },
            {
                "id": "writer",
                "role": "Writer",
                "system_prompt": "Write a concise summary from the research.",
                "behavior_type": "llm_only",
                "model": "openai:gpt-4o-mini",
            },
        ],
        "workflow": {
            "steps": [
                {"agent": "researcher", "type": "sequential", "next": "writer"},
                {"agent": "writer", "type": "sequential"},
            ],
        },
    }

    config = TeamConfiguration(**team_dict)

    print(f"\nTeam:   {config.team_name}")
    print(f"Agents: {[a.id for a in config.agents]}")
    print(f"Steps:  {len(config.workflow.steps)}")

    # Round-trip: serialize back to dict
    exported = config.model_dump(mode="json")
    print(f"\nRound-trip JSON (first 500 chars):")
    print(json.dumps(exported, indent=2)[:500])

    # Validate: TeamConfiguration catches invalid configs
    print(f"\nValidation: TeamConfiguration enforces schema constraints.")
    print(f"  Try adding an invalid behavior_type -- pydantic will raise.")


def main() -> None:
    """Run both demonstrations."""
    demo_from_file()
    demo_from_dict()

    print(f"\n{'=' * 60}")
    print("  Summary")
    print("=" * 60)
    print("  TeamConfiguration is the validated schema for team definitions.")
    print("  It can be loaded from JSON files, dicts, or constructed in code.")
    print("  Use it to validate configs before executing workflows.")


if __name__ == "__main__":
    main()
