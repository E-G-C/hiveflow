"""T035: Integration tests for MCP Gateway.

Tests that MCPGateway correctly registers team templates as MCP tools
and invokes workflows when called.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytest.importorskip("mcp", reason="mcp package not installed")

from hiveflow.plugins.mcp.gateway import MCPGateway, _invoke_workflow


class _FakeSession:
    """Minimal workflow session stub."""

    def __init__(self, status: str, state: dict | None = None, error: str | None = None):
        self.session_id = "test-session-123"
        self.status = MagicMock(value=status)
        self.error = error
        self.pending_requests = []
        if state is not None:
            self.result = MagicMock(state=state)
        else:
            self.result = None


def _make_hiveflow(templates: dict[str, dict[str, Any]] | None = None) -> MagicMock:
    """Create a mock HiveFlow instance with a team library."""
    hf = MagicMock()
    library = MagicMock()

    if templates is None:
        templates = {}

    library.list_templates.return_value = sorted(templates.keys())
    library.get.side_effect = lambda name: templates.get(name)
    hf.team_library.return_value = library
    hf.run = AsyncMock()
    return hf


class TestMCPGatewayRegistration:
    """T033: Test that team templates are registered as MCP tools."""

    def test_registers_all_templates(self) -> None:
        """Each template in the library should become an MCP tool."""
        templates = {
            "research_report": {
                "team_name": "research_report",
                "description": "Research and write a report",
                "agents": [],
                "workflow": {"steps": []},
            },
            "code_review": {
                "team_name": "code_review",
                "description": "Review code for issues",
                "agents": [],
                "workflow": {"steps": []},
            },
        }
        hf = _make_hiveflow(templates)
        gateway = MCPGateway(hf, name="test-server")

        assert len(gateway.registered_tools) == 2
        assert "hiveflow_research_report" in gateway.registered_tools
        assert "hiveflow_code_review" in gateway.registered_tools

    def test_empty_library_registers_no_tools(self) -> None:
        """Empty library should result in no registered tools."""
        hf = _make_hiveflow({})
        gateway = MCPGateway(hf)

        assert gateway.registered_tools == []

    def test_tool_name_format(self) -> None:
        """Tool names should follow hiveflow_{template_name} format."""
        templates = {
            "my_team": {
                "team_name": "my_team",
                "description": "A team",
                "agents": [],
                "workflow": {"steps": []},
            },
        }
        hf = _make_hiveflow(templates)
        gateway = MCPGateway(hf)

        assert gateway.registered_tools == ["hiveflow_my_team"]

    def test_server_name_and_instructions(self) -> None:
        """Server name and instructions should be passed to FastMCP."""
        hf = _make_hiveflow({})
        gateway = MCPGateway(hf, name="custom-server", instructions="Custom instructions")

        assert gateway.server.name == "custom-server"
        assert gateway.server.instructions == "Custom instructions"

    def test_default_server_name(self) -> None:
        """Default server name should be 'hiveflow'."""
        hf = _make_hiveflow({})
        gateway = MCPGateway(hf)

        assert gateway.server.name == "hiveflow"


class TestWorkflowInvocation:
    """T034: Test workflow invocation handler."""

    @pytest.mark.asyncio
    async def test_completed_workflow_returns_state(self) -> None:
        """Completed workflow should return filtered state."""
        hf = _make_hiveflow()
        session = _FakeSession("completed", state={
            "task": "Write a report",
            "writer_output": "The report content",
            "_step_order": ["writer"],
        })
        hf.run.return_value = session

        result = await _invoke_workflow(hf, "research", "Write a report")

        assert "writer_output" in result
        assert "task" not in result  # Filtered out
        assert "_step_order" not in result  # Filtered out (internal key)

    @pytest.mark.asyncio
    async def test_completed_workflow_prefers_final_output(self) -> None:
        """Completed workflow should prefer 'final_output' key if present."""
        hf = _make_hiveflow()
        session = _FakeSession("completed", state={
            "task": "Write",
            "final_output": "The final answer",
            "other_key": "ignored",
        })
        hf.run.return_value = session

        result = await _invoke_workflow(hf, "research", "Write")

        assert result == "The final answer"

    @pytest.mark.asyncio
    async def test_paused_workflow_returns_pending_status(self) -> None:
        """Paused workflow should return session info and pending count."""
        hf = _make_hiveflow()
        session = _FakeSession("paused")
        session.pending_requests = [{"id": "req-1"}]
        hf.run.return_value = session

        result = await _invoke_workflow(hf, "review", "Review this")

        assert "paused" in result.lower()
        assert "test-session-123" in result
        assert "1" in result  # pending request count

    @pytest.mark.asyncio
    async def test_failed_workflow_returns_error(self) -> None:
        """Failed workflow should return error message."""
        hf = _make_hiveflow()
        session = _FakeSession("failed", error="Agent crashed")
        hf.run.return_value = session

        result = await _invoke_workflow(hf, "team", "Do something")

        assert "failed" in result.lower()
        assert "Agent crashed" in result

    @pytest.mark.asyncio
    async def test_exception_returns_error_string(self) -> None:
        """Exception during workflow execution should return error string."""
        hf = _make_hiveflow()
        hf.run.side_effect = RuntimeError("Connection lost")

        result = await _invoke_workflow(hf, "team", "Do something")

        assert "Error" in result
        assert "Connection lost" in result

    @pytest.mark.asyncio
    async def test_passes_initial_state(self) -> None:
        """Initial state should be passed through to HiveFlow.run()."""
        hf = _make_hiveflow()
        session = _FakeSession("completed", state={"output": "done"})
        hf.run.return_value = session

        await _invoke_workflow(hf, "team", "task", initial_state={"key": "val"})

        hf.run.assert_awaited_once_with(
            team="team",
            task="task",
            initial_state={"key": "val"},
        )


class TestGatewayIntegration:
    """End-to-end test: register tools, list them, invoke one."""

    @pytest.mark.asyncio
    async def test_full_lifecycle(self) -> None:
        """Register templates → list tools → invoke workflow → verify result."""
        templates = {
            "summarizer": {
                "team_name": "summarizer",
                "description": "Summarize text input",
                "agents": [],
                "workflow": {"steps": []},
            },
        }
        hf = _make_hiveflow(templates)
        session = _FakeSession("completed", state={
            "task": "Summarize this",
            "final_output": "This is a summary.",
        })
        hf.run.return_value = session

        gateway = MCPGateway(hf)

        # Step 1: List tools — verify template appears
        assert "hiveflow_summarizer" in gateway.registered_tools

        # Step 2: List tools via FastMCP server
        tools = await gateway.server.list_tools()
        tool_names = [t.name for t in tools]
        assert "hiveflow_summarizer" in tool_names

        # Step 3: Invoke workflow via FastMCP call_tool
        result = await gateway.server.call_tool(
            "hiveflow_summarizer",
            {"task": "Summarize this"},
        )

        # FastMCP wraps results in a list of content objects
        assert len(result) > 0
        text = result[0].text if hasattr(result[0], "text") else str(result[0])
        assert "summary" in text.lower()

        # Verify HiveFlow.run was called with correct args
        hf.run.assert_awaited_once_with(
            team="summarizer",
            task="Summarize this",
            initial_state=None,
        )
