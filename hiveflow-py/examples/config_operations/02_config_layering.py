"""Example: Four-Layer Configuration Precedence.

Demonstrates how to:
1. See default configuration values
2. Override via JSON/YAML config files
3. Override via HIVEFLOW_ environment variables
4. Override via runtime apply_overrides()
5. Resolve tier variables ($SMART_LLM, etc.)

No live LLM needed — this is purely about configuration resolution.

Usage:
    uv run python examples/config_operations/02_config_layering.py
"""

import asyncio
import json
import os
import tempfile
from pathlib import Path

from hiveflow.core.config import HiveFlowConfig, get_config, reset_config


async def main() -> None:
    # -- 1. Defaults -----------------------------------------------------------
    print("--- 1. Default configuration ---")
    config = HiveFlowConfig()
    print(f"  SMART_LLM:            {config.SMART_LLM}")
    print(f"  MAX_TOKENS:           {config.MAX_TOKENS}")
    print(f"  SOURCE_MODE:          {config.SOURCE_MODE}")
    print(f"  DOC_PATH:             {config.DOC_PATH}")
    print(f"  DEFAULT_ACTION_POLICY:{config.DEFAULT_ACTION_POLICY}")
    print(f"  ENABLE_ROLLBACK:      {config.ENABLE_ROLLBACK}")
    print(f"  ACTION_TIMEOUT:       {config.ACTION_TIMEOUT}")
    print(f"  MCP_STRATEGY:         {config.MCP_STRATEGY}")
    print(f"  MCP_AUTO_TOOL_SEL:    {config.MCP_AUTO_TOOL_SELECTION}")

    # -- 2. Config file override -----------------------------------------------
    print("\n--- 2. JSON config file override ---")
    config_data = {
        "SMART_LLM": "anthropic:claude-sonnet-4-20250514",
        "SOURCE_MODE": "hybrid",
        "DOC_PATH": "/data/documents",
        "ACTION_TIMEOUT": 60,
        "MCP_STRATEGY": "fast",
    }
    config_file = Path(tempfile.mktemp(suffix=".json"))
    config_file.write_text(json.dumps(config_data, indent=2))
    try:
        config = HiveFlowConfig.from_file(config_file)
        print(f"  SMART_LLM:     {config.SMART_LLM} (was openai:gpt-4o)")
        print(f"  SOURCE_MODE:   {config.SOURCE_MODE} (was web)")
        print(f"  DOC_PATH:      {config.DOC_PATH} (was None)")
        print(f"  ACTION_TIMEOUT:{config.ACTION_TIMEOUT} (was 30)")
        print(f"  MCP_STRATEGY:  {config.MCP_STRATEGY} (was disabled)")
        print(f"  FAST_LLM:      {config.FAST_LLM} (still default -- not in file)")
    finally:
        config_file.unlink()

    # -- 3. Environment variable override --------------------------------------
    print("\n--- 3. Environment variable override ---")
    os.environ["HIVEFLOW_SOURCE_MODE"] = "cloud"
    os.environ["HIVEFLOW_ACTION_TIMEOUT"] = "120"
    try:
        config = HiveFlowConfig()
        print(f"  SOURCE_MODE:    {config.SOURCE_MODE} (from HIVEFLOW_SOURCE_MODE)")
        print(f"  ACTION_TIMEOUT: {config.ACTION_TIMEOUT} (from HIVEFLOW_ACTION_TIMEOUT)")
    finally:
        del os.environ["HIVEFLOW_SOURCE_MODE"]
        del os.environ["HIVEFLOW_ACTION_TIMEOUT"]

    # -- 4. Runtime overrides (team config layer) ------------------------------
    print("\n--- 4. Runtime overrides (highest precedence) ---")
    base = HiveFlowConfig()
    overridden = base.apply_overrides({
        "smart_llm": "azure:gpt-4o",
        "source_mode": "local",
        "mcp_strategy": "deep",
    })
    print(f"  SMART_LLM:   {overridden.SMART_LLM} (overridden)")
    print(f"  SOURCE_MODE: {overridden.SOURCE_MODE} (overridden)")
    print(f"  MCP_STRATEGY:{overridden.MCP_STRATEGY} (overridden)")
    print(f"  FAST_LLM:    {overridden.FAST_LLM} (unchanged)")
    # Original config is immutable
    print(f"  Base SMART_LLM still: {base.SMART_LLM}")

    # -- 5. Tier variable resolution -------------------------------------------
    print("\n--- 5. Tier variable resolution ---")
    config = HiveFlowConfig()
    print(f"  $SMART_LLM     -> {config.resolve_model('$SMART_LLM')}")
    print(f"  $FAST_LLM      -> {config.resolve_model('$FAST_LLM')}")
    print(f"  $STRATEGIC_LLM -> {config.resolve_model('$STRATEGIC_LLM')}")
    print(f"  openai:gpt-4o  -> {config.resolve_model('openai:gpt-4o')} (pass-through)")


if __name__ == "__main__":
    asyncio.run(main())
