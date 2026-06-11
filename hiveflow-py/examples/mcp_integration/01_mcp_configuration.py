#!/usr/bin/env python3
"""MCP Integration 01: Configuration Models.

Demonstrates how to:
  1. Create MCP configuration programmatically
  2. Define stdio and HTTP server entries
  3. Configure authentication for remote servers
  4. Load configuration from a JSON file
  5. Query server lists (eager vs lazy)

No MCP servers or API keys required -- this example works with
pure Pydantic models and a temporary config file.

Usage:
    uv run python examples/mcp_integration/01_mcp_configuration.py
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hiveflow.plugins.mcp.config import (
    MCPAuthConfig,
    MCPConfig,
    MCPServerDefinition,
)


# ---------------------------------------------------------------------------
# 1. Programmatic configuration
# ---------------------------------------------------------------------------

def demo_programmatic_config() -> None:
    """Build MCP config objects in code."""
    print("1. Programmatic Configuration")
    print("-" * 50)

    # Define a local stdio server (spawns a subprocess)
    local_tools = MCPServerDefinition(
        name="local_tools",
        transport="stdio",
        command="my-mcp-tool-server",
        args=["--verbose", "--port", "0"],
    )

    # Define a remote HTTP server with bearer auth
    jira_server = MCPServerDefinition(
        name="jira",
        transport="http",
        url="http://mcp-jira-server:8080",
        auth=MCPAuthConfig(type="bearer", env="JIRA_MCP_TOKEN"),
    )

    # Define a lazy server (connects only when a tool is first used)
    analytics = MCPServerDefinition(
        name="heavy_analytics",
        transport="http",
        url="http://analytics-mcp:9090",
        lazy=True,
    )

    # Assemble the top-level config
    config = MCPConfig(
        strategy="fast",
        servers=[local_tools, jira_server, analytics],
    )

    print(f"  Strategy:       {config.strategy}")
    print(f"  Total servers:  {len(config.servers)}")
    print(f"  Eager servers:  {[s.name for s in config.get_eager_servers()]}")
    print(f"  Lazy servers:   {[s.name for s in config.get_lazy_servers()]}")
    print()

    # Look up a specific server
    jira = config.get_server("jira")
    if jira:
        print(f"  Jira transport: {jira.transport}")
        print(f"  Jira URL:       {jira.url}")
        print(f"  Jira auth env:  {jira.auth.env if jira.auth else 'none'}")

    missing = config.get_server("nonexistent")
    print(f"  Missing server: {missing}")
    print()


# ---------------------------------------------------------------------------
# 2. Loading from a JSON file
# ---------------------------------------------------------------------------

def demo_from_file() -> None:
    """Load config from a temporary mcp.json file."""
    print("2. Loading from JSON File")
    print("-" * 50)

    config_data = {
        "strategy": "deep",
        "servers": [
            {
                "name": "github",
                "transport": "stdio",
                "command": "github-mcp-server",
                "args": ["--token-env", "GITHUB_TOKEN"],
            },
            {
                "name": "slack",
                "transport": "http",
                "url": "http://slack-mcp:3000",
                "auth": {"type": "bearer", "env": "SLACK_BOT_TOKEN"},
                "lazy": True,
            },
        ],
    }

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(config_data, f, indent=2)
        temp_path = f.name

    try:
        config = MCPConfig.from_file(temp_path)
        print(f"  Loaded from:    {temp_path}")
        print(f"  Strategy:       {config.strategy}")
        print(f"  Server count:   {len(config.servers)}")
        for server in config.servers:
            print(f"    - {server.name} ({server.transport})"
                  f"{' [lazy]' if server.lazy else ''}")
    finally:
        Path(temp_path).unlink(missing_ok=True)

    print()


# ---------------------------------------------------------------------------
# 3. Default (disabled) configuration
# ---------------------------------------------------------------------------

def demo_disabled_config() -> None:
    """Show default config when no mcp.json exists."""
    print("3. Default (Disabled) Configuration")
    print("-" * 50)

    # When no config file exists, MCP is silently disabled
    config = MCPConfig()
    print(f"  Strategy:  {config.strategy}")
    print(f"  Servers:   {config.servers}")
    print(f"  Is active: {config.strategy != 'disabled'}")
    print()


# ---------------------------------------------------------------------------
# 4. Strategy comparison
# ---------------------------------------------------------------------------

def demo_strategies() -> None:
    """Show the three MCP strategies side by side."""
    print("4. Strategy Comparison")
    print("-" * 50)

    strategies = {
        "disabled": "MCP is off. No server connections, no tools.",
        "fast":     "Connect all servers, register all tools eagerly.",
        "deep":     "Connect all servers, then LLM selects relevant tools.",
    }

    for name, desc in strategies.items():
        config = MCPConfig(strategy=name)
        print(f"  {name:10s}  {desc}")
    print()


# ---------------------------------------------------------------------------
# 5. Validation
# ---------------------------------------------------------------------------

def demo_validation() -> None:
    """Show config validation catching common mistakes."""
    print("5. Validation Examples")
    print("-" * 50)

    # HTTP server missing URL
    try:
        MCPServerDefinition(name="bad", transport="http")
    except ValueError as e:
        print(f"  Missing URL:       {e}")

    # Stdio server missing command
    try:
        MCPServerDefinition(name="bad", transport="stdio")
    except ValueError as e:
        print(f"  Missing command:   {e}")

    # Duplicate server names
    try:
        server = MCPServerDefinition(name="dup", transport="stdio", command="x")
        MCPConfig(strategy="fast", servers=[server, server])
    except ValueError as e:
        print(f"  Duplicate name:    {e}")

    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 60)
    print("  HiveFlow -- MCP Configuration Models")
    print("=" * 60)
    print()

    demo_programmatic_config()
    demo_from_file()
    demo_disabled_config()
    demo_strategies()
    demo_validation()

    print("Done.")


if __name__ == "__main__":
    main()
