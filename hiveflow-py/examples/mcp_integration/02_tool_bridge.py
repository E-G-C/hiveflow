#!/usr/bin/env python3
"""MCP Integration 02: Tool Bridge.

Demonstrates how to:
  1. Construct an MCPToolBridge manually (without a live MCP server)
  2. Inspect tool properties: plugin_id, llm_name, schemas
  3. Generate OpenAI-compatible tool specs for LLM function calling
  4. Execute a bridged tool and inspect the normalized result
  5. Understand the dual-mapping between plugin_id and llm_name

No MCP servers required -- uses a mock call function.

Usage:
    uv run python examples/mcp_integration/02_tool_bridge.py
"""

import asyncio
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hiveflow.plugins.mcp.bridge import MCPToolBridge


# ---------------------------------------------------------------------------
# Mock call function (simulates MCP server response)
# ---------------------------------------------------------------------------

def _make_text_content(text: str) -> MagicMock:
    """Create a mock TextContent object."""
    from mcp.types import TextContent
    return TextContent(type="text", text=text)


def _make_call_result(text: str, is_error: bool = False) -> MagicMock:
    """Create a mock CallToolResult."""
    result = MagicMock()
    result.content = [_make_text_content(text)]
    result.isError = is_error
    return result


async def mock_search_repos(tool_name: str, arguments: dict[str, Any]) -> Any:
    """Simulate calling an MCP tool that searches GitHub repositories."""
    query = arguments.get("query", "")
    return _make_call_result(
        f'{{"repos": ['
        f'{{"name": "hiveflow", "stars": 1200, "description": "Multi-agent workflow framework"}}, '
        f'{{"name": "mcp-server", "stars": 850, "description": "MCP reference server"}}'
        f'], "query": "{query}"}}'
    )


async def mock_create_issue(tool_name: str, arguments: dict[str, Any]) -> Any:
    """Simulate calling an MCP tool that creates a GitHub issue."""
    title = arguments.get("title", "Untitled")
    return _make_call_result(
        f'{{"issue_number": 42, "title": "{title}", "url": "https://github.com/org/repo/issues/42"}}'
    )


async def mock_failing_tool(tool_name: str, arguments: dict[str, Any]) -> Any:
    """Simulate an MCP tool that returns an error."""
    return _make_call_result("Rate limit exceeded (429)", is_error=True)


# ---------------------------------------------------------------------------
# 1. Constructing tool bridges
# ---------------------------------------------------------------------------

def demo_construction() -> None:
    """Build MCPToolBridge instances and inspect properties."""
    print("1. Constructing Tool Bridges")
    print("-" * 50)

    search_bridge = MCPToolBridge(
        server_name="github",
        tool_name="search_repos",
        description="Search GitHub repositories by query",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "max_results": {"type": "integer", "default": 10},
            },
            "required": ["query"],
        },
        call_fn=mock_search_repos,
    )

    print(f"  plugin_id:    {search_bridge.plugin_id}")
    print(f"  llm_name:     {search_bridge.llm_name}")
    print(f"  server_name:  {search_bridge.server_name}")
    print(f"  tool_name:    {search_bridge.tool_name}")
    print(f"  description:  {search_bridge.description}")
    print(f"  input_schema: {search_bridge.input_schema}")
    print(f"  output_schema: {search_bridge.output_schema}")
    print()

    # Dual-mapping explanation
    print("  Naming Convention:")
    print(f"    plugin_id  = 'mcp:{{server}}/{{tool}}'  -> {search_bridge.plugin_id}")
    print(f"    llm_name   = 'mcp_{{server}}__{{tool}}' -> {search_bridge.llm_name}")
    print("    plugin_id is used in ToolRegistry and team configs")
    print("    llm_name is used in LLM function calling (no special chars)")
    print()


# ---------------------------------------------------------------------------
# 2. LLM tool spec generation
# ---------------------------------------------------------------------------

def demo_tool_spec() -> None:
    """Generate OpenAI-compatible function calling spec."""
    print("2. LLM Tool Spec Generation")
    print("-" * 50)

    bridge = MCPToolBridge(
        server_name="github",
        tool_name="create_issue",
        description="Create a new GitHub issue",
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "body": {"type": "string"},
                "labels": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["title"],
        },
        call_fn=mock_create_issue,
    )

    spec = bridge.to_llm_tool_spec()
    import json
    print(f"  {json.dumps(spec, indent=4)}")
    print()
    print("  The spec uses llm_name (sanitized) as the function name,")
    print("  so the LLM sees 'mcp_github__create_issue' in its tool list.")
    print()


# ---------------------------------------------------------------------------
# 3. Executing bridged tools
# ---------------------------------------------------------------------------

async def demo_execution() -> None:
    """Call bridged tools and inspect results."""
    print("3. Executing Bridged Tools")
    print("-" * 50)

    # Successful call
    search = MCPToolBridge(
        server_name="github",
        tool_name="search_repos",
        description="Search repos",
        input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
        call_fn=mock_search_repos,
    )

    result = await search.execute({"query": "python agent framework"})
    print(f"  Search result: {result}")
    print(f"  Has 'result' key: {'result' in result}")
    print()

    # Error case
    failing = MCPToolBridge(
        server_name="github",
        tool_name="rate_limited",
        description="A tool that fails",
        input_schema={"type": "object"},
        call_fn=mock_failing_tool,
    )

    error_result = await failing.execute({})
    print(f"  Error result:  {error_result}")
    print(f"  Has 'error' key: {'error' in error_result}")
    print()


# ---------------------------------------------------------------------------
# 4. Multiple bridges from one server
# ---------------------------------------------------------------------------

def demo_multiple_bridges() -> None:
    """Show multiple tools from the same MCP server."""
    print("4. Multiple Tools from One Server")
    print("-" * 50)

    tools = [
        ("search_repos", "Search GitHub repositories"),
        ("create_issue", "Create a new issue"),
        ("list_prs", "List pull requests"),
        ("get_file", "Read a file from a repository"),
    ]

    bridges = []
    for name, desc in tools:
        bridge = MCPToolBridge(
            server_name="github",
            tool_name=name,
            description=desc,
            input_schema={"type": "object"},
            call_fn=mock_search_repos,  # Same mock for demo
        )
        bridges.append(bridge)

    print("  Tools from 'github' server:")
    for b in bridges:
        print(f"    {b.plugin_id:35s}  ->  llm: {b.llm_name}")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    print("=" * 60)
    print("  HiveFlow -- MCP Tool Bridge")
    print("=" * 60)
    print()

    demo_construction()
    demo_tool_spec()
    await demo_execution()
    demo_multiple_bridges()

    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
