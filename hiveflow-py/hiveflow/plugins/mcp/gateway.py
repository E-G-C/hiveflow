"""MCP Gateway — Expose HiveFlow workflows as MCP tools.

Design decision (T032): The gateway lives in ``hiveflow/plugins/mcp/gateway.py``
rather than a separate top-level package. Rationale:

1. It shares the ``mcp`` optional dependency already declared for the client side.
2. It re-uses existing HiveFlow internals (TeamTemplateLibrary, HiveFlow.run).
3. The "separately installable" requirement from FR-013 is satisfied by the
   existing ``mcp`` extras group — users who don't need gateway functionality
   simply don't install the ``mcp`` extras.

Usage::

    from hiveflow.plugins.mcp.gateway import MCPGateway

    gateway = MCPGateway(hiveflow_instance)
    gateway.run()  # starts stdio transport by default
"""

from typing import Any

import structlog

logger = structlog.get_logger(__name__)

try:
    from mcp.server.fastmcp import FastMCP

    _MCP_AVAILABLE = True
except ImportError:
    _MCP_AVAILABLE = False


class MCPGateway:
    """Expose registered HiveFlow team templates as MCP tools.

    Each team in the TeamTemplateLibrary is registered as an invocable
    MCP tool. When an external MCP client calls a tool, the gateway
    runs the corresponding workflow via ``HiveFlow.run()`` and returns
    the result.

    Args:
        hiveflow: A configured HiveFlow instance.
        name: Name for the MCP server (shown to clients).
        instructions: Optional instructions for the MCP server.
    """

    def __init__(
        self,
        hiveflow: Any,
        *,
        name: str = "hiveflow",
        instructions: str | None = None,
    ) -> None:
        if not _MCP_AVAILABLE:
            raise ImportError(
                "mcp is required for the MCP gateway. Install with: pip install 'hiveflow[mcp]'"
            )

        self._hiveflow = hiveflow
        self._server = FastMCP(
            name=name,
            instructions=instructions or "HiveFlow workflow execution server",
        )
        self._registered_tools: list[str] = []
        self._register_team_tools()

    # ------------------------------------------------------------------
    # Tool registration (T033)
    # ------------------------------------------------------------------

    def _register_team_tools(self) -> None:
        """Register each team template as an MCP tool."""
        library = self._hiveflow.team_library()
        template_names = library.list_templates()

        for template_name in template_names:
            template = library.get(template_name)
            if template is None:
                continue

            description = template.get("description", f"Run the {template_name} workflow")
            tool_name = f"hiveflow_{template_name}"

            handler = self._make_handler(template_name)
            self._server.add_tool(
                handler,
                name=tool_name,
                description=description,
            )
            self._registered_tools.append(tool_name)
            logger.debug(
                "mcp.gateway.tool_registered",
                tool_name=tool_name,
                template=template_name,
            )

        logger.info(
            "mcp.gateway.tools_registered",
            count=len(self._registered_tools),
        )

    def _make_handler(self, template_name: str):
        """Create an async handler function for a team template.

        Returns an async function that accepts ``task`` and optional
        ``initial_state`` parameters and invokes ``HiveFlow.run()``.
        """
        hiveflow = self._hiveflow

        async def handler(task: str, initial_state: dict[str, Any] | None = None) -> str:
            """Execute a HiveFlow workflow.

            Args:
                task: The task description for the workflow.
                initial_state: Optional initial state dict.

            Returns:
                Workflow result as a string.
            """
            return await _invoke_workflow(hiveflow, template_name, task, initial_state)

        handler.__name__ = f"run_{template_name}"
        handler.__qualname__ = f"MCPGateway.run_{template_name}"
        return handler

    # ------------------------------------------------------------------
    # Server lifecycle
    # ------------------------------------------------------------------

    @property
    def server(self) -> "FastMCP":
        """Access the underlying FastMCP server instance."""
        return self._server

    @property
    def registered_tools(self) -> list[str]:
        """List of registered MCP tool names."""
        return list(self._registered_tools)

    def run(self, transport: str = "stdio") -> None:
        """Start the MCP server.

        Args:
            transport: Transport mode — "stdio", "sse", or "streamable-http".
        """
        self._server.run(transport=transport)

    async def run_stdio_async(self) -> None:
        """Start the MCP server with stdio transport (async)."""
        await self._server.run_stdio_async()


# ------------------------------------------------------------------
# Workflow invocation handler (T034)
# ------------------------------------------------------------------


async def _invoke_workflow(
    hiveflow: Any,
    template_name: str,
    task: str,
    initial_state: dict[str, Any] | None = None,
) -> str:
    """Invoke a HiveFlow workflow and return the result as a string.

    Handles completed, paused, and failed workflow statuses.

    Args:
        hiveflow: HiveFlow instance.
        template_name: Team template name to run.
        task: Task description.
        initial_state: Optional initial state.

    Returns:
        String representation of the workflow result.
    """
    try:
        session = await hiveflow.run(
            team=template_name,
            task=task,
            initial_state=initial_state,
        )

        status = session.status.value if hasattr(session.status, "value") else str(session.status)

        if status == "completed":
            result = session.result
            if result is not None and hasattr(result, "state"):
                # Return the final state, focusing on the task output
                state = result.state
                # Prefer explicit output keys over the full state dump
                output = state.get("final_output") or state.get("result") or state.get("output")
                if output is not None:
                    return str(output)
                # Filter internal keys for cleaner output
                filtered = {
                    k: v
                    for k, v in state.items()
                    if not k.startswith("_") and k not in ("task", "documents", "document_summary")
                }
                return str(filtered)
            return f"Workflow completed (session: {session.session_id})"

        elif status == "paused":
            return (
                f"Workflow paused — awaiting approval "
                f"(session_id: {session.session_id}). "
                f"Pending requests: {len(session.pending_requests)}"
            )

        elif status == "failed":
            error = session.error or "Unknown error"
            return f"Workflow failed: {error}"

        else:
            return f"Workflow status: {status} (session: {session.session_id})"

    except Exception:
        logger.exception("mcp.gateway.invocation_error", template=template_name)
        return f"Error invoking workflow '{template_name}'. Check server logs for details."
