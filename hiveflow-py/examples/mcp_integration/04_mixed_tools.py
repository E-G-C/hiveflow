#!/usr/bin/env python3
"""MCP Integration 04: Mixed Native + MCP Tools.

Demonstrates how to:
  1. Define a native ToolPlugin (e.g. web_search)
  2. Define MCP tool bridges from an external server
  3. Register both in the same ToolRegistry
  4. Build an Agent that sees both native and MCP tools
  5. Show the unified tool list the LLM receives

No MCP servers or API keys required -- uses mock tools and providers.

Usage:
    uv run python examples/mcp_integration/04_mixed_tools.py
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hiveflow.plugins.mcp.bridge import MCPToolBridge
from hiveflow.plugins.tools import ToolPlugin, ToolRegistry


# ---------------------------------------------------------------------------
# Native tool -- a simple web search plugin
# ---------------------------------------------------------------------------

class WebSearchTool(ToolPlugin):
    """Native tool plugin for web search."""

    @property
    def plugin_id(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return "Search the web for information on any topic"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results",
                    "default": 5,
                },
            },
            "required": ["query"],
        }

    @property
    def output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "results": {
                    "type": "array",
                    "items": {"type": "object"},
                },
            },
        }

    async def execute(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        query = tool_input["query"]
        return {
            "results": [
                {"title": f"Result for: {query}", "url": "https://example.com/1"},
                {"title": f"More on: {query}", "url": "https://example.com/2"},
            ]
        }


class DocumentRetrieverTool(ToolPlugin):
    """Native tool plugin for document retrieval."""

    @property
    def plugin_id(self) -> str:
        return "document_retriever"

    @property
    def description(self) -> str:
        return "Retrieve relevant sections from loaded documents"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
            },
            "required": ["query"],
        }

    @property
    def output_schema(self) -> dict[str, Any]:
        return {"type": "object"}

    async def execute(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        return {"chunks": ["Relevant document section..."]}


# ---------------------------------------------------------------------------
# MCP tool bridges -- simulating tools from an external server
# ---------------------------------------------------------------------------

def make_mcp_bridges() -> list[MCPToolBridge]:
    """Create mock MCP tool bridges from a 'company_db' server."""
    mock_call = AsyncMock(return_value=MagicMock(content=[], isError=False))

    return [
        MCPToolBridge(
            server_name="company_db",
            tool_name="query",
            description="Execute a read-only SQL query against the company database",
            input_schema={
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "SQL SELECT query"},
                },
                "required": ["sql"],
            },
            call_fn=mock_call,
        ),
        MCPToolBridge(
            server_name="company_db",
            tool_name="insert",
            description="Insert a new record into the company database",
            input_schema={
                "type": "object",
                "properties": {
                    "table": {"type": "string"},
                    "data": {"type": "object"},
                },
                "required": ["table", "data"],
            },
            call_fn=mock_call,
        ),
        MCPToolBridge(
            server_name="jira",
            tool_name="search",
            description="Search Jira issues by JQL query",
            input_schema={
                "type": "object",
                "properties": {
                    "jql": {"type": "string", "description": "JQL query"},
                },
                "required": ["jql"],
            },
            call_fn=mock_call,
        ),
    ]


# ---------------------------------------------------------------------------
# 1. Register both tool types
# ---------------------------------------------------------------------------

def demo_unified_registry() -> None:
    """Show native and MCP tools coexisting in one registry."""
    print("1. Unified Tool Registry")
    print("-" * 50)

    registry = ToolRegistry(drop_in_dir=None)

    # Register native tools
    registry.register(WebSearchTool())
    registry.register(DocumentRetrieverTool())

    # Register MCP tools
    for bridge in make_mcp_bridges():
        registry.register(bridge)

    # List all registered tools
    print("  All registered tools:")
    for pid in registry.list_ids():
        tool = registry.get(pid)
        origin = "MCP" if pid.startswith("mcp:") else "native"
        print(f"    [{origin:6s}]  {pid:40s}  {tool.description[:50]}")
    print()


# ---------------------------------------------------------------------------
# 2. LLM tool specs (what the model sees)
# ---------------------------------------------------------------------------

def demo_llm_specs() -> None:
    """Generate the function calling specs an LLM would receive."""
    print("2. LLM Function Calling Specs")
    print("-" * 50)

    registry = ToolRegistry(drop_in_dir=None)
    registry.register(WebSearchTool())
    for bridge in make_mcp_bridges():
        registry.register(bridge)

    # Agent's tool list would be: ["web_search", "mcp:company_db/query", ...]
    tool_ids = ["web_search", "mcp:company_db/query", "mcp:jira/search"]

    specs = registry.get_llm_tool_specs(tool_ids)
    print(f"  Specs for agent with {len(specs)} tools:")
    for spec in specs:
        fn = spec["function"]
        print(f"    name: {fn['name']:35s}  desc: {fn['description'][:45]}")
    print()
    print("  Note: native tools use plugin_id as function name,")
    print("        MCP tools use sanitized llm_name (mcp_server__tool).")
    print()

    # Show one full spec
    print("  Full spec for 'mcp:company_db/query':")
    db_spec = next(s for s in specs if "company_db" in s["function"]["name"])
    print(f"    {json.dumps(db_spec, indent=4)}")
    print()


# ---------------------------------------------------------------------------
# 3. Agent tool map (dual mapping)
# ---------------------------------------------------------------------------

def demo_agent_tool_map() -> None:
    """Show how agents build their internal tool map."""
    print("3. Agent Tool Map (Dual Mapping)")
    print("-" * 50)

    registry = ToolRegistry(drop_in_dir=None)

    native = WebSearchTool()
    mcp_tool = MCPToolBridge(
        server_name="github",
        tool_name="search_repos",
        description="Search repos",
        input_schema={"type": "object"},
        call_fn=AsyncMock(),
    )

    registry.register(native)
    registry.register(mcp_tool)

    # Simulate what Agent._build_tool_map() does:
    # It maps both plugin_id AND llm_name so either key resolves the tool
    tool_map: dict[str, ToolPlugin] = {}
    for tool in [native, mcp_tool]:
        tool_map[tool.plugin_id] = tool
        if hasattr(tool, "llm_name"):
            tool_map[tool.llm_name] = tool

    print("  Agent's internal _tool_map keys:")
    for key in tool_map:
        tool = tool_map[key]
        print(f"    '{key}' -> {tool.plugin_id}")
    print()
    print("  The agent can resolve MCP tools by either:")
    print(f"    plugin_id: '{mcp_tool.plugin_id}'")
    print(f"    llm_name:  '{mcp_tool.llm_name}'")
    print("  Both point to the same MCPToolBridge instance.")
    print()


# ---------------------------------------------------------------------------
# 4. Executing tools from the unified registry
# ---------------------------------------------------------------------------

async def demo_execute_mixed() -> None:
    """Execute both native and MCP tools through the same interface."""
    print("4. Executing Mixed Tools")
    print("-" * 50)

    registry = ToolRegistry(drop_in_dir=None)
    registry.register(WebSearchTool())
    for bridge in make_mcp_bridges():
        registry.register(bridge)

    # Execute native tool
    native_tool = registry.get("web_search")
    result1 = await native_tool.execute({"query": "Python frameworks"})
    print(f"  Native 'web_search':     {len(result1['results'])} results")

    # Execute MCP tool
    mcp_tool = registry.get("mcp:company_db/query")
    result2 = await mcp_tool.execute({"sql": "SELECT * FROM projects"})
    print(f"  MCP 'company_db/query':  {result2}")
    print()
    print("  Both tools use the same execute(input) -> dict interface.")
    print("  The agent does not need to know which is native vs MCP.")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    print("=" * 60)
    print("  HiveFlow -- Mixed Native + MCP Tools")
    print("=" * 60)
    print()

    demo_unified_registry()
    demo_llm_specs()
    demo_agent_tool_map()
    await demo_execute_mixed()

    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
