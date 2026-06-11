#!/usr/bin/env python3
"""MCP Integration 06: MCP Gateway.

Demonstrates how to:
  1. Create an MCPGateway from a HiveFlow instance
  2. Register team templates as MCP tools
  3. List available tools via the FastMCP server
  4. Invoke a workflow through the MCP tool interface
  5. Handle completed, paused, and failed workflow results

No MCP servers or API keys required -- uses mock HiveFlow and sessions.

Usage:
    uv run python examples/mcp_integration/06_mcp_gateway.py
"""

import asyncio
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hiveflow.plugins.mcp.gateway import MCPGateway, _invoke_workflow


# ---------------------------------------------------------------------------
# Mock HiveFlow
# ---------------------------------------------------------------------------

class FakeSession:
    """Minimal workflow session stub."""

    def __init__(
        self,
        status: str,
        state: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        self.session_id = "session-abc-123"
        self.status = MagicMock(value=status)
        self.error = error
        self.pending_requests = []
        if state is not None:
            self.result = MagicMock(state=state)
        else:
            self.result = None


def make_mock_hiveflow(
    templates: dict[str, dict[str, Any]] | None = None,
) -> MagicMock:
    """Build a mock HiveFlow instance with a team library."""
    hf = MagicMock()
    library = MagicMock()

    if templates is None:
        templates = {}

    library.list_templates.return_value = sorted(templates.keys())
    library.get.side_effect = lambda name: templates.get(name)
    hf.team_library.return_value = library
    hf.run = AsyncMock()
    return hf


# ---------------------------------------------------------------------------
# Sample team templates
# ---------------------------------------------------------------------------

TEMPLATES = {
    "research_report": {
        "team_name": "research_report",
        "description": "Research a topic and produce a structured report",
        "agents": [
            {"id": "researcher", "role": "Research analyst"},
            {"id": "writer", "role": "Report writer"},
        ],
        "workflow": {"steps": [{"agent": "researcher"}, {"agent": "writer"}]},
    },
    "code_review": {
        "team_name": "code_review",
        "description": "Review code for bugs, security issues, and style",
        "agents": [
            {"id": "reviewer", "role": "Code reviewer"},
        ],
        "workflow": {"steps": [{"agent": "reviewer"}]},
    },
    "data_pipeline": {
        "team_name": "data_pipeline",
        "description": "Extract, transform, and load data from various sources",
        "agents": [
            {"id": "extractor", "role": "Data extractor"},
            {"id": "transformer", "role": "Data transformer"},
            {"id": "loader", "role": "Data loader"},
        ],
        "workflow": {
            "steps": [
                {"agent": "extractor"},
                {"agent": "transformer"},
                {"agent": "loader"},
            ]
        },
    },
}


# ---------------------------------------------------------------------------
# 1. Basic gateway setup
# ---------------------------------------------------------------------------

def demo_basic_setup() -> None:
    """Create a gateway and inspect registered tools."""
    print("1. Basic Gateway Setup")
    print("-" * 50)

    hf = make_mock_hiveflow(TEMPLATES)
    gateway = MCPGateway(hf, name="my-hiveflow-server")

    print(f"  Server name:      {gateway.server.name}")
    print(f"  Tools registered: {len(gateway.registered_tools)}")
    print()
    print("  Available tools (exposed to MCP clients):")
    for tool_name in gateway.registered_tools:
        print(f"    {tool_name}")
    print()
    print("  Each 'hiveflow_<template>' tool accepts:")
    print("    task: str            -- the task description")
    print("    initial_state: dict  -- optional initial workflow state")
    print()


# ---------------------------------------------------------------------------
# 2. List tools via FastMCP server
# ---------------------------------------------------------------------------

async def demo_list_tools() -> None:
    """List tools through the FastMCP server API."""
    print("2. List Tools via FastMCP Server API")
    print("-" * 50)

    hf = make_mock_hiveflow(TEMPLATES)
    gateway = MCPGateway(hf)

    tools = await gateway.server.list_tools()
    print(f"  Tools returned by server.list_tools(): {len(tools)}")
    for tool in tools:
        print(f"    {tool.name:35s}  {tool.description[:50]}")
    print()


# ---------------------------------------------------------------------------
# 3. Invoke workflows through gateway
# ---------------------------------------------------------------------------

async def demo_invoke_completed() -> None:
    """Invoke a workflow that completes successfully."""
    print("3a. Invoking a Completed Workflow")
    print("-" * 50)

    hf = make_mock_hiveflow()
    session = FakeSession("completed", state={
        "task": "Analyze renewable energy trends",
        "researcher_output": "Found 15 peer-reviewed papers on solar efficiency.",
        "writer_output": "# Renewable Energy Report\n\nSolar panel efficiency ...",
        "final_output": "# Renewable Energy Report\n\nSolar panel efficiency has improved by 23% over the past decade.",
        "_step_order": ["researcher", "writer"],
    })
    hf.run.return_value = session

    result = await _invoke_workflow(hf, "research_report", "Analyze renewable energy trends")
    print(f"  Result: {result[:80]}...")
    print(f"  (Returns 'final_output' when present)")
    print()


async def demo_invoke_paused() -> None:
    """Invoke a workflow that pauses at a gate."""
    print("3b. Invoking a Paused Workflow (Gate)")
    print("-" * 50)

    hf = make_mock_hiveflow()
    session = FakeSession("paused")
    session.pending_requests = [{"id": "gate-1", "description": "Approve deployment"}]
    hf.run.return_value = session

    result = await _invoke_workflow(hf, "data_pipeline", "Load Q4 financial data")
    print(f"  Result: {result}")
    print(f"  (Contains session_id for resume, and pending request count)")
    print()


async def demo_invoke_failed() -> None:
    """Invoke a workflow that fails."""
    print("3c. Invoking a Failed Workflow")
    print("-" * 50)

    hf = make_mock_hiveflow()
    session = FakeSession("failed", error="Agent 'extractor' exceeded token limit")
    hf.run.return_value = session

    result = await _invoke_workflow(hf, "data_pipeline", "Extract all records")
    print(f"  Result: {result}")
    print()


async def demo_invoke_exception() -> None:
    """Handle exception during workflow execution."""
    print("3d. Handling Execution Exception")
    print("-" * 50)

    import io
    import structlog
    hf = make_mock_hiveflow()
    hf.run.side_effect = RuntimeError("Database connection lost")

    # Temporarily redirect structlog output to suppress traceback
    # (structlog.exception() includes Unicode chars that fail on
    # Windows cp1252 terminals)
    devnull = io.StringIO()
    structlog.configure(
        logger_factory=structlog.PrintLoggerFactory(file=devnull),
    )
    try:
        result = await _invoke_workflow(hf, "data_pipeline", "Load data")
    finally:
        structlog.reset_defaults()
    print(f"  Result: {result}")
    print(f"  (Exception is caught and returned as error string)")
    print()


# ---------------------------------------------------------------------------
# 4. Full lifecycle via FastMCP
# ---------------------------------------------------------------------------

async def demo_full_lifecycle() -> None:
    """Register -> list -> invoke through the FastMCP server."""
    print("4. Full Lifecycle via FastMCP")
    print("-" * 50)

    hf = make_mock_hiveflow(TEMPLATES)
    session = FakeSession("completed", state={
        "task": "Review the login module",
        "final_output": "Code review complete. Found 2 minor issues: unused import on line 15, missing type hint on line 42.",
    })
    hf.run.return_value = session

    gateway = MCPGateway(hf, name="ci-hiveflow", instructions="HiveFlow CI/CD workflows")

    # Step 1: List tools
    tools = await gateway.server.list_tools()
    print(f"  Step 1 - Listed {len(tools)} tools")

    # Step 2: Find the code_review tool
    review_tool = next(t for t in tools if "code_review" in t.name)
    print(f"  Step 2 - Found tool: {review_tool.name}")

    # Step 3: Invoke via call_tool
    result = await gateway.server.call_tool(
        "hiveflow_code_review",
        {"task": "Review the login module"},
    )
    # FastMCP call_tool returns (content_list, metadata_dict)
    content_list = result[0] if isinstance(result, tuple) else result
    if isinstance(content_list, list) and len(content_list) > 0:
        first = content_list[0]
        text = first.text if hasattr(first, "text") else str(first)
    else:
        text = str(content_list)
    print(f"  Step 3 - Result: {text[:70]}...")
    print()

    # Verify the HiveFlow.run() call
    hf.run.assert_awaited_once()
    call_kwargs = hf.run.call_args
    print(f"  HiveFlow.run() called with:")
    print(f"    team:  {call_kwargs.kwargs.get('team', call_kwargs.args[0] if call_kwargs.args else 'N/A')}")
    print(f"    task:  {call_kwargs.kwargs.get('task', 'N/A')}")
    print()


# ---------------------------------------------------------------------------
# 5. Custom server configuration
# ---------------------------------------------------------------------------

def demo_custom_server() -> None:
    """Show server name and instructions customization."""
    print("5. Custom Server Configuration")
    print("-" * 50)

    hf = make_mock_hiveflow({"summarizer": {
        "team_name": "summarizer",
        "description": "Summarize text",
        "agents": [],
        "workflow": {"steps": []},
    }})

    gateway = MCPGateway(
        hf,
        name="acme-hiveflow",
        instructions="ACME Corp workflow execution server. "
                     "Available workflows: summarizer.",
    )

    print(f"  Server name:    {gateway.server.name}")
    print(f"  Instructions:   {gateway.server.instructions[:60]}...")
    print(f"  Tools:          {gateway.registered_tools}")
    print()
    print("  To start the server (in production):")
    print("    gateway.run(transport='stdio')           # for CLI clients")
    print("    gateway.run(transport='sse')             # for web clients")
    print("    await gateway.run_stdio_async()          # async variant")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    print("=" * 60)
    print("  HiveFlow -- MCP Gateway")
    print("=" * 60)
    print()

    demo_basic_setup()
    await demo_list_tools()
    await demo_invoke_completed()
    await demo_invoke_paused()
    await demo_invoke_failed()
    await demo_invoke_exception()
    await demo_full_lifecycle()
    demo_custom_server()

    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
