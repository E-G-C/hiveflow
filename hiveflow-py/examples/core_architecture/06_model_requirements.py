#!/usr/bin/env python3
"""Example: Declarative model requirements and tier variables.

Demonstrates how to:
1. Define ModelRequirements on an agent (cost_tier, supports_tools, etc.)
2. Resolve tier variables ($SMART_LLM, $FAST_LLM, $STRATEGIC_LLM)
3. Understand the resolution chain: tier var -> config -> provider

ModelRequirements let agents declare what they need (fast, smart, strategic)
rather than specifying a concrete model name. This makes team configurations
portable across providers and environments.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hiveflow import (
    HiveFlowConfig,
    ModelRequirements,
    TeamConfiguration,
)


def main() -> None:
    """Demonstrate model requirements and tier variable resolution."""
    print("Model Requirements & Tier Variables Example")
    print("=" * 60)

    # -- ModelRequirements: declare what you need -------------------------------
    print("\n1. ModelRequirements -- declarative model selection:")
    reqs = ModelRequirements(
        cost_tier="smart",
        supports_tools=True,
        supports_vision=False,
        strengths=["reasoning", "coding"],
    )
    print(f"   cost_tier: {reqs.cost_tier}")
    print(f"   supports_tools: {reqs.supports_tools}")
    print(f"   supports_vision: {reqs.supports_vision}")
    print(f"   strengths: {reqs.strengths}")

    # -- Tier variable resolution -----------------------------------------------
    print("\n2. Tier variable resolution:")
    config = HiveFlowConfig()
    print(f"   Default FAST_LLM:      {config.FAST_LLM}")
    print(f"   Default SMART_LLM:     {config.SMART_LLM}")
    print(f"   Default STRATEGIC_LLM: {config.STRATEGIC_LLM}")

    resolved = config.resolve_model("$SMART_LLM")
    print(f"\n   resolve_model('$SMART_LLM') -> '{resolved}'")

    # Direct references pass through unchanged
    direct = config.resolve_model("azure:gpt-4o-eastus")
    print(f"   resolve_model('azure:gpt-4o-eastus') -> '{direct}'")

    # -- Override tiers via constructor -----------------------------------------
    print("\n3. Override tiers:")
    custom = HiveFlowConfig(SMART_LLM="anthropic:claude-sonnet-4-20250514")
    print(f"   Custom SMART_LLM: {custom.SMART_LLM}")
    print(f"   resolve_model('$SMART_LLM') -> '{custom.resolve_model('$SMART_LLM')}'")

    # -- Agent config with model_requirements -----------------------------------
    print("\n4. Agent config with model_requirements (JSON):")
    agent_config = {
        "id": "analyzer",
        "role": "Code Analyzer",
        "system_prompt": "Analyze code for bugs and improvements.",
        "behavior_type": "tool_user",
        "model_requirements": {
            "cost_tier": "smart",
            "supports_tools": True,
            "supports_vision": False,
            "strengths": ["reasoning", "coding"],
        },
    }
    print(f"   Agent: {agent_config['id']}")
    print(f"   cost_tier: {agent_config['model_requirements']['cost_tier']}")
    print(f"   When model is not set, framework resolves via tier mapping")

    # -- Precedence: model > model_requirements ---------------------------------
    print("\n5. Precedence rules:")
    print("   If both model and model_requirements are set, model wins.")
    print("   model='openai:gpt-4o' + model_requirements.cost_tier='fast'")
    print("   -> uses 'openai:gpt-4o' (explicit model takes priority)")


if __name__ == "__main__":
    main()
