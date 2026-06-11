"""MCP Manager.

Manages the lifecycle of MCP server connections within a workflow run.
Reads MCP configuration, establishes connections, discovers tools,
registers them in the ToolRegistry, and ensures cleanup on shutdown.
"""

import contextlib
import os
from contextlib import AsyncExitStack
from functools import partial
from typing import Any

import structlog

from hiveflow.plugins.mcp.bridge import MCPToolBridge
from hiveflow.plugins.mcp.config import MCPConfig, MCPServerDefinition
from hiveflow.plugins.tools import ToolRegistry

logger = structlog.get_logger(__name__)


class MCPConnectionError(Exception):
    """Raised when an MCP server connection fails."""

    def __init__(self, server_name: str, transport: str, detail: str) -> None:
        self.server_name = server_name
        self.transport = transport
        self.detail = detail
        super().__init__(f"MCP server '{server_name}' ({transport}): {detail}")


class MCPToolExecutionError(Exception):
    """Raised when an MCP tool call fails."""

    def __init__(self, server_name: str, tool_name: str, detail: str) -> None:
        self.server_name = server_name
        self.tool_name = tool_name
        self.detail = detail
        super().__init__(f"MCP tool '{server_name}/{tool_name}': {detail}")


class MCPManager:
    """Manages MCP server connections and tool registration.

    Lifecycle:
    1. __init__(config, tool_registry) — stores config, creates AsyncExitStack
    2. startup(task) — connects eager servers, discovers tools, registers them
    3. [workflow runs, agents call MCP tools via MCPToolBridge]
    4. shutdown() — closes all connections, terminates stdio processes
    """

    def __init__(
        self,
        config: MCPConfig,
        tool_registry: ToolRegistry,
        llm_provider: Any | None = None,
    ) -> None:
        self.config = config
        self.tool_registry = tool_registry
        self._llm_provider = llm_provider
        self._exit_stack = AsyncExitStack()
        self._tools: list[MCPToolBridge] = []
        self._connected_servers: dict[str, Any] = {}

    @property
    def is_available(self) -> bool:
        """Check if the mcp package is importable."""
        try:
            import mcp  # noqa: F401

            return True
        except ImportError:
            return False

    async def startup(self, task: str = "") -> None:
        """Connect to eager MCP servers and register their tools.

        Servers configured with lazy=True are skipped — they connect
        on first tool use via ensure_server().

        If a server is unreachable, it is logged and skipped without
        raising (workflow must not be blocked).
        """
        logger.info(
            "mcp.startup",
            strategy=self.config.strategy,
            server_count=len(self.config.servers),
        )

        if not self.is_available:
            logger.warning("mcp.startup.skipped", reason="mcp package not installed")
            return

        if self.config.strategy == "disabled":
            return

        for server_def in self.config.get_eager_servers():
            try:
                tools = await self._connect_server(server_def)
                logger.info(
                    "mcp.server.connected",
                    server_name=server_def.name,
                    tool_count=len(tools),
                )
            except Exception as exc:
                logger.error(
                    "mcp.server.failed",
                    server_name=server_def.name,
                    error=str(exc),
                )

        logger.info(
            "mcp.startup.complete",
            total_tools_registered=len(self._tools),
        )

        # Deep mode: LLM-based tool selection after all connections
        if self.config.strategy == "deep" and self._tools:
            await self._run_deep_selection(task)

    async def ensure_server(self, server_name: str) -> None:
        """Connect a lazy server on first tool use.

        Unlike startup(), failures here DO raise MCPConnectionError
        because the tool was explicitly referenced and is needed.
        """
        if server_name in self._connected_servers:
            return

        server_def = self.config.get_server(server_name)
        if server_def is None:
            raise KeyError(f"MCP server '{server_name}' not found in config")

        logger.info("mcp.server.lazy_connect", server_name=server_name)

        try:
            tools = await self._connect_server(server_def)
            logger.info(
                "mcp.server.connected",
                server_name=server_name,
                tool_count=len(tools),
            )
        except Exception as exc:
            raise MCPConnectionError(
                server_name=server_name,
                transport=server_def.transport,
                detail=str(exc),
            ) from exc

    async def shutdown(self) -> None:
        """Close all MCP connections and terminate stdio processes."""
        await self._exit_stack.aclose()
        logger.info("mcp.shutdown", servers_closed=len(self._connected_servers))

    def get_tools(self) -> list[MCPToolBridge]:
        """Return all discovered MCPToolBridge instances."""
        return list(self._tools)

    # --- Internal Methods ---

    async def _connect_server(
        self,
        server_def: MCPServerDefinition,
    ) -> list[MCPToolBridge]:
        """Connect to a single MCP server and discover its tools.

        Steps:
        1. Create transport (stdio or http)
        2. Create and initialize ClientSession
        3. Discover tools via session.list_tools()
        4. Create MCPToolBridge per tool
        5. Register each bridge in tool_registry
        """
        from mcp.client.session import ClientSession

        # Establish transport
        if server_def.transport == "stdio":
            read_stream, write_stream = await self._connect_stdio(server_def)
        else:
            read_stream, write_stream = await self._connect_http(server_def)

        # Create and initialize session
        session = await self._exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await session.initialize()

        # Discover tools
        tools_result = await session.list_tools()
        bridges: list[MCPToolBridge] = []

        for tool in tools_result.tools:
            # Create a call_fn closure bound to this session
            call_fn = partial(session.call_tool)
            bridge = MCPToolBridge(
                server_name=server_def.name,
                tool_name=tool.name,
                description=tool.description or "",
                input_schema=tool.inputSchema,
                call_fn=call_fn,
            )
            bridges.append(bridge)
            self.tool_registry.register(bridge)

        self._tools.extend(bridges)
        self._connected_servers[server_def.name] = session
        return bridges

    async def _connect_stdio(
        self,
        server_def: MCPServerDefinition,
    ) -> tuple[Any, Any]:
        """Establish a stdio transport connection.

        Spawns the configured command as a subprocess via MCP's stdio_client.
        """
        from mcp.client.stdio import StdioServerParameters, stdio_client

        params = StdioServerParameters(
            command=server_def.command,
            args=server_def.args,
            env=server_def.env,
        )

        # stdio_client is an async context manager yielding (read, write)
        transport = await self._exit_stack.enter_async_context(stdio_client(params))
        read_stream, write_stream = transport
        return read_stream, write_stream

    async def _connect_http(
        self,
        server_def: MCPServerDefinition,
    ) -> tuple[Any, Any]:
        """Establish an HTTP/SSE transport connection.

        If auth is configured, resolves the bearer token (supporting
        env var references) and passes it as a header.
        """
        from mcp.client.streamable_http import streamablehttp_client

        headers: dict[str, str] | None = None

        if server_def.auth is not None:
            env_var = server_def.auth.env
            token = os.environ.get(env_var, "")
            if not token:
                raise MCPConnectionError(
                    server_name=server_def.name,
                    transport="http",
                    detail=f"Environment variable '{env_var}' not set for auth token",
                )
            headers = {"Authorization": f"Bearer {token}"}

        transport = await self._exit_stack.enter_async_context(
            streamablehttp_client(url=server_def.url, headers=headers)
        )
        read_stream, write_stream, _get_session_id = transport
        return read_stream, write_stream

    async def _run_deep_selection(self, task: str) -> None:
        """LLM-based tool selection for deep mode.

        Builds a tool catalog, asks the LLM to select relevant tools
        for the task, and unregisters non-selected tools.
        Falls back to fast mode (keep all tools) on any failure.
        """
        if not self._llm_provider:
            logger.warning(
                "mcp.deep.fallback",
                reason="no LLM provider available for deep selection",
            )
            return

        # Build tool catalog
        catalog_lines: list[str] = []
        for tool in self._tools:
            catalog_lines.append(f"- {tool.plugin_id}: {tool.description}")
        catalog = "\n".join(catalog_lines)

        prompt = (
            f"Given this task:\n{task}\n\n"
            f"Select ONLY the tools relevant to this task from the catalog below. "
            f"Return a JSON array of tool IDs (plugin_id values) that should be kept. "
            f"Return ONLY the JSON array, no explanation.\n\n"
            f"Tool catalog:\n{catalog}"
        )

        try:
            from hiveflow.plugins.llm import LLMConfig

            config = LLMConfig(model="$FAST_LLM", max_tokens=2000)
            response = await self._llm_provider.generate(
                messages=[{"role": "user", "content": prompt}],
                config=config,
            )

            # Parse the JSON array from response
            import json as json_mod

            content = response.get("content", "")
            # Strip markdown code fences if present
            if "```" in content:
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            selected_ids = set(json_mod.loads(content.strip()))

            # Unregister non-selected tools
            removed_count = 0
            for tool in list(self._tools):
                if tool.plugin_id not in selected_ids:
                    with contextlib.suppress(KeyError, AttributeError):
                        self.tool_registry.unregister(tool.plugin_id)
                    self._tools.remove(tool)
                    removed_count += 1

            logger.info(
                "mcp.deep.selection",
                selected_count=len(self._tools),
                total_count=len(self._tools) + removed_count,
            )

        except Exception as exc:
            logger.warning(
                "mcp.deep.fallback",
                reason=str(exc),
            )
