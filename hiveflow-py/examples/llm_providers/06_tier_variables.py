"""Example: Tier Variable Resolution ($SMART_LLM, $FAST_LLM, $STRATEGIC_LLM).

Demonstrates how to:
1. Resolve tier variables to provider:model strings via HiveFlowConfig
2. Use the defaults ($SMART_LLM -> openai:gpt-4o, etc.)
3. Override tiers via environment variables
4. Override tiers programmatically at runtime
5. Chain tier resolution through the registry to get a provider instance

No API keys needed -- this uses config resolution only, no live calls.

Usage:
    uv run python examples/llm_providers/06_tier_variables.py

    # Or override a tier:
    HIVEFLOW_SMART_LLM=anthropic:claude-sonnet-4-20250514 \\
        uv run python examples/llm_providers/06_tier_variables.py
"""

import os

from hiveflow.core.config import HiveFlowConfig, LLMTier, get_config, reset_config
from hiveflow.plugins.llm import get_llm_registry


def main() -> None:
    reset_config()  # start fresh

    # -- 1. Default tier values -----------------------------------------------
    print("1. Default tier values")
    config = get_config()
    for tier in LLMTier:
        resolved = config.resolve_model(f"${tier.value}")
        print(f"   ${tier.value:15s} -> {resolved}")

    # -- 2. Direct references pass through unchanged --------------------------
    print("\n2. Direct references (no tier)")
    for ref in ["openai:gpt-4o-mini", "azure:my-deployment", "anthropic:claude-haiku-4-20250414"]:
        print(f"   {ref:40s} -> {config.resolve_model(ref)}")

    # -- 3. Override via environment variable ----------------------------------
    print("\n3. Environment variable override")
    os.environ["HIVEFLOW_SMART_LLM"] = "azure:gpt-4o-eastus"
    reset_config()
    config = get_config()
    print(f"   HIVEFLOW_SMART_LLM=azure:gpt-4o-eastus")
    print(f"   $SMART_LLM -> {config.resolve_model('$SMART_LLM')}")
    del os.environ["HIVEFLOW_SMART_LLM"]

    # -- 4. Programmatic override ---------------------------------------------
    print("\n4. Programmatic override")
    reset_config()
    config = HiveFlowConfig(
        FAST_LLM="anthropic:claude-haiku-4-20250414",
        SMART_LLM="anthropic:claude-sonnet-4-20250514",
        STRATEGIC_LLM="openai:o3-mini",
    )
    for tier in LLMTier:
        resolved = config.resolve_model(f"${tier.value}")
        print(f"   ${tier.value:15s} -> {resolved}")

    # -- 5. End-to-end: tier -> config -> registry -> provider ----------------
    print("\n5. End-to-end: tier -> provider instance")
    reset_config()
    config = get_config()  # default tiers
    registry = get_llm_registry()

    model_ref = config.resolve_model("$SMART_LLM")
    provider, model = registry.resolve_model(model_ref)
    print(f"   $SMART_LLM -> '{model_ref}' -> provider={provider.provider_id}, model={model}")

    model_ref = config.resolve_model("$FAST_LLM")
    provider, model = registry.resolve_model(model_ref)
    print(f"   $FAST_LLM  -> '{model_ref}' -> provider={provider.provider_id}, model={model}")


if __name__ == "__main__":
    main()
