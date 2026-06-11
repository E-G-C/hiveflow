#!/usr/bin/env python3
"""MCP Integration 05: Deep Mode Selection.

Demonstrates how to:
  1. Configure MCP with strategy="deep"
  2. See how the LLM selects relevant tools for a task
  3. Observe non-selected tools being unregistered
  4. Handle fallback when LLM selection fails
  5. Compare fast vs deep tool counts

No MCP servers or API keys required -- uses mock LLM and tools.

Usage:
    uv run python examples/mcp_integration/05_deep_mode_selection.py
"""

import asyncio
import json
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
# Mock helpers
# ---------------------------------------------------------------------------

def _make_bridge(server: str, tool: str, desc: str) -> MCPToolBridge:
    """Build a mock MCPToolBridge."""
    return MCPToolBridge(
        server_name=server,
        tool_name=tool,
        description=desc,
        input_schema={"type": "object", "properties": {"input": {"type": "string"}}},
        call_fn=AsyncMock(return_value=MagicMock(content=[], isError=False)),
    )


# All tools that the mock servers would discover
ALL_TOOLS = [
    ("github", "search_repos", "Search GitHub repositories by query"),
    ("github", "create_issue", "Create a new GitHub issue"),
    ("github", "list_prs", "List open pull requests"),
    ("github", "get_file", "Read a file from a repository"),
    ("slack", "send_message", "Send a Slack message to a channel"),
    ("slack", "list_channels", "List available Slack channels"),
    ("jira", "search_issues", "Search Jira issues by JQL"),
    ("jira", "create_issue", "Create a new Jira issue"),
    ("analytics", "run_query", "Execute an analytics SQL query"),
    ("analytics", "get_dashboard", "Retrieve dashboard metrics"),
]


async def mock_connect_server(
    self: Any,
    server_def: MCPServerDefinition,
) -> list[MCPToolBridge]:
    """Patch returning mock tools for the specified server."""
    bridges = []
    for server, tool, desc in ALL_TOOLS:
        if server == server_def.name:
            bridge = _make_bridge(server, tool, desc)
            bridges.append(bridge)
            self.tool_registry.register(bridge)
    self._tools.extend(bridges)
    self._connected_servers[server_def.name] = MagicMock()
    return bridges


def make_config() -> MCPConfig:
    """Config with all 4 mock servers."""
    return MCPConfig(
        strategy="deep",
        servers=[
            MCPServerDefinition(name="github", transport="stdio", command="gh-mcp"),
            MCPServerDefinition(name="slack", transport="http", url="http://slack:3000"),
            MCPServerDefinition(name="jira", transport="http", url="http://jira:8080"),
            MCPServerDefinition(name="analytics", transport="http", url="http://analytics:9090"),
        ],
    )


# ---------------------------------------------------------------------------
# Mock LLM provider for deep selection
# ---------------------------------------------------------------------------

class MockDeepSelectionLLM:
    """Mock LLM that selects tools based on task keywords."""

    def __init__(self, selected_ids: list[str] | None = None, should_fail: bool = False) -> None:
        self._selected_ids = selected_ids
        self._should_fail = should_fail
        self.last_prompt: str = ""

    async def generate(self, messages: list[dict], config: Any = None) -> dict:
        self.last_prompt = messages[0]["content"] if messages else ""

        if self._should_fail:
            raise RuntimeError("LLM service unavailable")

        if self._selected_ids is not None:
            return {"content": json.dumps(self._selected_ids)}

        # Auto-select based on keywords in the task
        task = self.last_prompt.lower()
        selected = []
        for server, tool, desc in ALL_TOOLS:
            pid = f"mcp:{server}/{tool}"
            if server in task or tool.split("_")[0] in task:
                selected.append(pid)
        return {"content": json.dumps(selected)}


# ---------------------------------------------------------------------------
# 1. Deep mode in action
# ---------------------------------------------------------------------------

async def demo_deep_selection() -> None:
    """Show deep mode filtering tools for a specific task."""
    print("1. Deep Mode -- Task-Specific Tool Selection")
    print("-" * 50)

    config = make_config()
    registry = ToolRegistry(drop_in_dir=None)

    # LLM will select only GitHub and Jira tools for this task
    llm = MockDeepSelectionLLM(selected_ids=[
        "mcp:github/search_repos",
        "mcp:github/create_issue",
        "mcp:jira/search_issues",
    ])

    with patch.object(MCPManager, "_connect_server", mock_connect_server):
        with patch.object(MCPManager, "is_available", new_callable=lambda: property(lambda s: True)):
            manager = MCPManager(config, registry, llm_provider=llm)

            task = "Find GitHub repos with open bugs and create Jira tickets for tracking"
            await manager.startup(task=task)

            tools = manager.get_tools()
            print(f"  Task: '{task}'")
            print(f"  Total tools available: {len(ALL_TOOLS)}")
            print(f"  Tools after deep selection: {len(tools)}")
            print()
            print("  Selected tools:")
            for tool in tools:
                print(f"    {tool.plugin_id:40s}  {tool.description}")
            print()
            print("  Removed tools (not relevant to task):")
            selected_ids = {t.plugin_id for t in tools}
            for server, tool_name, desc in ALL_TOOLS:
                pid = f"mcp:{server}/{tool_name}"
                if pid not in selected_ids:
                    print(f"    {pid:40s}  {desc}")

            await manager.shutdown()

    print()


# ---------------------------------------------------------------------------
# 2. Compare fast vs deep
# ---------------------------------------------------------------------------

async def demo_fast_vs_deep() -> None:
    """Compare tool counts between fast and deep strategies."""
    print("2. Fast vs Deep Strategy Comparison")
    print("-" * 50)

    task = "Send a Slack message to the engineering channel"

    # Fast mode: all tools
    fast_config = MCPConfig(
        strategy="fast",
        servers=make_config().servers,
    )
    fast_registry = ToolRegistry(drop_in_dir=None)

    with patch.object(MCPManager, "_connect_server", mock_connect_server):
        with patch.object(MCPManager, "is_available", new_callable=lambda: property(lambda s: True)):
            fast_manager = MCPManager(fast_config, fast_registry)
            await fast_manager.startup(task=task)
            fast_count = len(fast_manager.get_tools())
            await fast_manager.shutdown()

    # Deep mode: LLM selects only Slack tools
    deep_config = make_config()
    deep_registry = ToolRegistry(drop_in_dir=None)
    llm = MockDeepSelectionLLM(selected_ids=[
        "mcp:slack/send_message",
        "mcp:slack/list_channels",
    ])

    with patch.object(MCPManager, "_connect_server", mock_connect_server):
        with patch.object(MCPManager, "is_available", new_callable=lambda: property(lambda s: True)):
            deep_manager = MCPManager(deep_config, deep_registry, llm_provider=llm)
            await deep_manager.startup(task=task)
            deep_count = len(deep_manager.get_tools())
            await deep_manager.shutdown()

    print(f"  Task: '{task}'")
    print(f"  Fast mode tools: {fast_count}")
    print(f"  Deep mode tools: {deep_count}")
    print(f"  Reduction:       {fast_count - deep_count} tools removed ({100*(fast_count-deep_count)//fast_count}%)")
    print()
    print("  Deep mode reduces noise in the LLM's tool list,")
    print("  improving accuracy for task-specific workflows.")
    print()


# ---------------------------------------------------------------------------
# 3. Fallback on LLM failure
# ---------------------------------------------------------------------------

async def demo_fallback() -> None:
    """When LLM selection fails, all tools are kept (fast mode fallback)."""
    print("3. Fallback on LLM Failure")
    print("-" * 50)

    config = make_config()
    registry = ToolRegistry(drop_in_dir=None)

    # LLM that will fail
    llm = MockDeepSelectionLLM(should_fail=True)

    with patch.object(MCPManager, "_connect_server", mock_connect_server):
        with patch.object(MCPManager, "is_available", new_callable=lambda: property(lambda s: True)):
            manager = MCPManager(config, registry, llm_provider=llm)
            await manager.startup(task="Any task")

            tools = manager.get_tools()
            print(f"  LLM threw RuntimeError during selection")
            print(f"  Tools kept (fallback to fast): {len(tools)}")
            print(f"  All {len(ALL_TOOLS)} tools remain available")
            print()
            print("  Deep mode gracefully degrades to fast mode when:")
            print("    - LLM provider is unavailable")
            print("    - LLM returns invalid JSON")
            print("    - Any exception during selection")

            await manager.shutdown()

    print()


# ---------------------------------------------------------------------------
# 4. No LLM provider
# ---------------------------------------------------------------------------

async def demo_no_llm() -> None:
    """Deep mode without LLM provider falls back to fast mode."""
    print("4. Deep Mode Without LLM Provider")
    print("-" * 50)

    config = make_config()
    registry = ToolRegistry(drop_in_dir=None)

    with patch.object(MCPManager, "_connect_server", mock_connect_server):
        with patch.object(MCPManager, "is_available", new_callable=lambda: property(lambda s: True)):
            # No llm_provider passed
            manager = MCPManager(config, registry, llm_provider=None)
            await manager.startup(task="Search for issues")

            print(f"  Strategy: deep (but no LLM provider)")
            print(f"  Tools: {len(manager.get_tools())} (all kept, same as fast)")
            print("  Logs warning: 'no LLM provider available for deep selection'")

            await manager.shutdown()

    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    print("=" * 60)
    print("  HiveFlow -- Deep Mode Tool Selection")
    print("=" * 60)
    print()

    await demo_deep_selection()
    await demo_fast_vs_deep()
    await demo_fallback()
    await demo_no_llm()

    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
