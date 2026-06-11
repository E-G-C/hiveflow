#!/usr/bin/env python3
"""Example: Discovery APIs -- enumerate teams, archetypes, tools, and models.

Demonstrates how to:
1. List available team templates
2. Browse the archetype library (built-in agent definitions)
3. Inspect the tool registry
4. Query the model/LLM provider registry

These APIs let you explore what's available in the framework at runtime.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hiveflow import (
    ArchetypeLibrary,
    HiveFlow,
    TeamTemplateLibrary,
)


def main() -> None:
    """Demonstrate HiveFlow discovery APIs."""
    print("Discovery APIs Example")
    print("=" * 60)

    hf = HiveFlow()

    # -- Team template library --------------------------------------------------
    print("\n1. Team Templates:")
    templates = hf.team_library().list_templates()
    print(f"   Available templates: {templates}")
    if templates:
        first = templates[0]
        config = hf.team_library().get(first)
        print(f"   '{first}' config keys: {list(config.keys()) if config else 'N/A'}")

    # -- Archetype library (built-in agent definitions) -------------------------
    print("\n2. Agent Archetypes (built-in):")
    archetypes = hf.archetype_library().list_archetypes()
    print(f"   Available: {archetypes}")
    for name in archetypes[:3]:  # Show first 3
        archetype = hf.archetype_library().get(name)
        if archetype:
            print(f"   '{name}': role={archetype.get('role', 'N/A')}")

    # -- Custom archetype library -----------------------------------------------
    print("\n3. Custom Archetypes:")
    custom_lib = ArchetypeLibrary()
    custom_lib.register("data_scientist", {
        "role": "Data Scientist",
        "system_prompt": "Analyze data and build statistical models.",
        "behavior_type": "tool_user",
        "tools": ["python_executor", "data_visualizer"],
    })
    custom_lib.register("devops_engineer", {
        "role": "DevOps Engineer",
        "system_prompt": "Manage infrastructure and CI/CD pipelines.",
        "behavior_type": "action_executor",
        "action_policy": "require_approval",
    })
    print(f"   Registered: {custom_lib.list_archetypes()}")
    ds = custom_lib.get("data_scientist")
    print(f"   data_scientist tools: {ds['tools']}")

    # -- Custom team template library -------------------------------------------
    print("\n4. Custom Team Templates:")
    lib = TeamTemplateLibrary()
    lib.register("code_review", {
        "team_name": "code_review",
        "description": "Review pull requests",
        "agents": [
            {"id": "reviewer", "role": "Reviewer", "behavior_type": "llm_only",
             "system_prompt": "Review code for correctness and style."},
            {"id": "security_checker", "role": "Security", "behavior_type": "tool_user",
             "system_prompt": "Check for security vulnerabilities.",
             "tools": ["semgrep"]},
        ],
        "workflow": {
            "steps": [
                {"agent": "reviewer", "type": "sequential", "next": "security_checker"},
                {"agent": "security_checker", "type": "sequential"},
            ],
        },
    })
    print(f"   Templates: {lib.list_templates()}")

    # -- Tool registry ----------------------------------------------------------
    print("\n5. Tool Registry:")
    tool_ids = hf.tool_registry().list_ids()
    print(f"   Registered tools: {tool_ids if tool_ids else '(none -- install tool plugins)'}")

    # -- Model registry ---------------------------------------------------------
    print("\n6. Model Registry:")
    provider_ids = hf.model_registry().list_ids()
    print(f"   Registered providers: {provider_ids if provider_ids else '(none -- install LLM plugins)'}")
    print("   Providers are discovered via entry points in pyproject.toml")


if __name__ == "__main__":
    main()
