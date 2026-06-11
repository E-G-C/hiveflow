#!/usr/bin/env python3
"""MCP Integration 03: Manager Lifecycle.

Demonstrates how to:
  1. Create an MCPManager from config and registry
  2. Run the startup/shutdown lifecycle
  3. Discover and register tools from MCP servers
  4. Distinguish eager vs lazy server connections
  5. Inspect registered tools after startup

No MCP servers required -- patches the connection layer with mocks.

Usage:
    uv run python examples/mcp_integration/03_manager_lifecycle.py
"""

import asyncio
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hiveflow.plugins.mcp.bridge import MCPToolBridge
from hiveflow.plugins.mcp.config import MCPConfig, MCPServerDefinition
from hiveflow.plugins.mcp.manager import MCPManager
from hiveflow.plugins.tools import ToolRegistry


# ---------------------------------------------------------------------------
# Mock helpers -- simulate MCP server tool discovery
# ---------------------------------------------------------------------------

def _make_mock_bridge(server_name: str, tool_name: str, desc: str) -> MCPToolBridge:
    """Build a mock MCPToolBridge without a real MCP session."""
    return MCPToolBridge(
        server_name=server_name,
        tool_name=tool_name,
        description=desc,
        input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
        call_fn=AsyncMock(return_value=MagicMock(content=[], isError=False)),
    )


# Tool catalogs per mock server
MOCK_SERVER_TOOLS: dict[str, list[tuple[str, str]]] = {
    "github": [
        ("search_repos", "Search GitHub repositories"),
        ("create_issue", "Create a new issue"),
        ("list_prs", "List open pull requests"),
    ],
    "slack": [
        ("send_message", "Send a Slack message"),
        ("list_channels", "List available channels"),
    ],
    "analytics": [
        ("run_query", "Execute an analytics SQL query"),
        ("get_dashboard", "Retrieve dashboard metrics"),
    ],
}


async def mock_connect_server(
    self: Any,
    server_def: MCPServerDefinition,
) -> list[MCPToolBridge]:
    """Patch for MCPManager._connect_server -- returns mock bridges."""
    tools_spec = MOCK_SERVER_TOOLS.get(server_def.name, [])
    bridges = []
    for tool_name, desc in tools_spec:
        bridge = _make_mock_bridge(server_def.name, tool_name, desc)
        bridges.append(bridge)
        self.tool_registry.register(bridge)
    self._tools.extend(bridges)
    self._connected_servers[server_def.name] = MagicMock()
    return bridges


# ---------------------------------------------------------------------------
# 1. Basic lifecycle
# ---------------------------------------------------------------------------

async def demo_basic_lifecycle() -> None:
    """Startup -> discover tools -> shutdown."""
    print("1. Basic Lifecycle (fast strategy)")
    print("-" * 50)

    config = MCPConfig(
        strategy="fast",
        servers=[
            MCPServerDefinition(name="github", transport="stdio", command="gh-mcp"),
            MCPServerDefinition(name="slack", transport="http", url="http://slack:3000"),
        ],
    )
    registry = ToolRegistry(drop_in_dir=None)

    with patch.object(MCPManager, "_connect_server", mock_connect_server):
        with patch.object(MCPManager, "is_available", new_callable=lambda: property(lambda s: True)):
            manager = MCPManager(config, registry)

            # Startup connects eager servers and discovers tools
            print("  Starting up...")
            await manager.startup(task="Search for issues and notify the team")
            print(f"  Tools discovered: {len(manager.get_tools())}")

            for tool in manager.get_tools():
                print(f"    {tool.plugin_id:40s}  {tool.description}")

            # Shutdown closes all connections
            print()
            print("  Shutting down...")
            await manager.shutdown()
            print("  Manager shut down cleanly.")

    print()


# ---------------------------------------------------------------------------
# 2. Eager vs lazy connections
# ---------------------------------------------------------------------------

async def demo_eager_vs_lazy() -> None:
    """Eager servers connect at startup; lazy servers connect on demand."""
    print("2. Eager vs Lazy Connections")
    print("-" * 50)

    config = MCPConfig(
        strategy="fast",
        servers=[
            # Eager -- connects immediately at startup
            MCPServerDefinition(name="github", transport="stdio", command="gh-mcp"),
            # Lazy -- connects only when a tool is first used
            MCPServerDefinition(
                name="analytics",
                transport="http",
                url="http://analytics:9090",
                lazy=True,
            ),
        ],
    )
    registry = ToolRegistry(drop_in_dir=None)

    with patch.object(MCPManager, "_connect_server", mock_connect_server):
        with patch.object(MCPManager, "is_available", new_callable=lambda: property(lambda s: True)):
            manager = MCPManager(config, registry)

            # After startup, only eager server tools are available
            await manager.startup(task="Analyze repository metrics")
            print(f"  After startup: {len(manager.get_tools())} tools registered")
            for tool in manager.get_tools():
                print(f"    {tool.plugin_id}")
            print()

            # Connect the lazy server on demand
            print("  Connecting lazy server 'analytics'...")
            await manager.ensure_server("analytics")
            print(f"  After ensure_server: {len(manager.get_tools())} tools registered")
            for tool in manager.get_tools():
                print(f"    {tool.plugin_id}")

            await manager.shutdown()

    print()


# ---------------------------------------------------------------------------
# 3. Tool registry integration
# ---------------------------------------------------------------------------

async def demo_registry_integration() -> None:
    """Show how MCP tools appear in the ToolRegistry alongside native tools."""
    print("3. Tool Registry Integration")
    print("-" * 50)

    config = MCPConfig(
        strategy="fast",
        servers=[
            MCPServerDefinition(name="github", transport="stdio", command="gh-mcp"),
        ],
    )
    registry = ToolRegistry(drop_in_dir=None)

    with patch.object(MCPManager, "_connect_server", mock_connect_server):
        with patch.object(MCPManager, "is_available", new_callable=lambda: property(lambda s: True)):
            manager = MCPManager(config, registry)
            await manager.startup()

            # Tools are now in the registry -- look them up by plugin_id
            print("  Registered plugin IDs:")
            for pid in registry.list_ids():
                tool = registry.get(pid)
                label = "(MCP)" if pid.startswith("mcp:") else "(native)"
                print(f"    {pid:40s}  {label}")

            # Retrieve specific tools
            search = registry.get("mcp:github/search_repos")
            if search:
                print()
                print(f"  Lookup 'mcp:github/search_repos':")
                print(f"    plugin_id:   {search.plugin_id}")
                print(f"    description: {search.description}")

            await manager.shutdown()

    print()


# ---------------------------------------------------------------------------
# 4. Disabled strategy
# ---------------------------------------------------------------------------

async def demo_disabled_strategy() -> None:
    """When strategy is disabled, startup is a no-op."""
    print("4. Disabled Strategy (no-op)")
    print("-" * 50)

    config = MCPConfig(strategy="disabled")
    registry = ToolRegistry(drop_in_dir=None)

    manager = MCPManager(config, registry)
    await manager.startup(task="This task is ignored")

    print(f"  Strategy:       {config.strategy}")
    print(f"  Tools found:    {len(manager.get_tools())}")
    print("  (Startup was a no-op because strategy is 'disabled')")

    await manager.shutdown()
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    print("=" * 60)
    print("  HiveFlow -- MCP Manager Lifecycle")
    print("=" * 60)
    print()

    await demo_basic_lifecycle()
    await demo_eager_vs_lazy()
    await demo_registry_integration()
    await demo_disabled_strategy()

    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
