"""MCPManager Contract.

Manages the lifecycle of MCP server connections within a workflow run.
Reads MCP configuration, establishes connections, discovers tools,
registers them in the ToolRegistry, and ensures cleanup on shutdown.

This is the main orchestration component for MCP integration. It is
created by HiveFlow.run() and its lifetime matches the workflow run.
"""

from typing import Any


# --- Manager ---


class MCPManager:                                           # NEW
    """Manages MCP server connections and tool registration.

    Lifecycle:
    1. __init__(config, tool_registry) — stores config, creates AsyncExitStack
    2. startup(task) — connects eager servers, discovers tools, registers them
    3. [workflow runs, agents call MCP tools via MCPToolBridge]
    4. shutdown() — closes all connections, terminates stdio processes

    The MCPManager does NOT own the ToolRegistry. It receives one and
    registers MCP tools into it alongside native tools.
    """

    def __init__(
        self,
        config: Any,        # MCPConfig
        tool_registry: Any,  # ToolRegistry
    ) -> None:
        """Initialize the MCP manager.

        Creates an AsyncExitStack for managing connection lifecycles.
        Does NOT establish any connections — that happens in startup().

        Args:
            config: Parsed MCPConfig from mcp.json.
            tool_registry: The workflow's tool registry (shared with native tools).
        """
        ...

    @property
    def is_available(self) -> bool:
        """Check if the mcp package is importable.

        Returns False if the mcp package is not installed, allowing
        graceful degradation. When False, startup() is a no-op.
        """
        ...

    async def startup(self, task: str = "") -> None:
        """Connect to MCP servers and register their tools.

        For each non-lazy server in config.servers:
        1. Establish transport connection (stdio or HTTP)
        2. Initialize ClientSession
        3. Discover tools via session.list_tools()
        4. Create MCPToolBridge per tool
        5. Register each bridge in tool_registry

        If a server is unreachable:
        - Log error with server name and transport details
        - Skip server, continue with remaining servers
        - Do NOT raise — workflow must not be blocked (FR-009)

        For 'deep' strategy: after all connections, run LLM-based
        tool selection and unregister non-selected tools.

        Args:
            task: Task description (used for deep mode tool selection).

        Logs:
            mcp.startup — strategy, server_count
            mcp.server.connected — server_name, tool_count
            mcp.server.failed — server_name, error
            mcp.startup.complete — total_tools_registered
        """
        ...

    async def ensure_server(self, server_name: str) -> None:
        """Connect a lazy server on first tool use.

        Called when an agent references a tool from a server that
        was configured with lazy=True and has not yet been connected.

        Unlike startup(), failures here DO raise MCPConnectionError
        because the tool was explicitly referenced and is needed.

        Args:
            server_name: Name of the server to connect.

        Raises:
            MCPConnectionError: If the server cannot be reached.
            KeyError: If the server name is not in the config.

        Logs:
            mcp.server.lazy_connect — server_name
            mcp.server.connected — server_name, tool_count
        """
        ...

    async def shutdown(self) -> None:
        """Close all MCP connections and terminate stdio processes.

        Calls self._exit_stack.aclose() which tears down all
        connections in reverse order. For stdio servers, this
        terminates the spawned process.

        Safe to call multiple times (idempotent).
        Safe to call even if startup() was never called.

        Logs:
            mcp.shutdown — servers_closed
        """
        ...

    def get_tools(self) -> list[Any]:
        """Return all discovered MCPToolBridge instances.

        Returns:
            List of MCPToolBridge instances registered during
            startup() and ensure_server() calls.
        """
        ...

    # --- Internal Methods ---

    async def _connect_server(
        self,
        server_def: Any,  # MCPServerDefinition
    ) -> list[Any]:
        """Connect to a single MCP server and discover its tools.

        Steps:
        1. Create transport (stdio_client or streamable_http_client)
        2. Push transport context manager into AsyncExitStack
        3. Create and initialize ClientSession
        4. Push session into AsyncExitStack
        5. Call session.list_tools() to discover tools
        6. Create MCPToolBridge per tool with call_fn closure
        7. Register each bridge in tool_registry

        For stdio: StdioServerParameters(command, args, env)
        For http: streamable_http_client(url), with optional
                  auth via httpx.AsyncClient bearer header

        Args:
            server_def: Server configuration.

        Returns:
            List of MCPToolBridge instances created for this server.

        Raises:
            MCPConnectionError: On transport or session failure.
        """
        ...

    async def _connect_stdio(
        self,
        server_def: Any,  # MCPServerDefinition
    ) -> tuple[Any, Any]:
        """Establish a stdio transport connection.

        Spawns the configured command as a subprocess and establishes
        MCP communication via stdin/stdout.

        Returns:
            Tuple of (read_stream, write_stream) for ClientSession.
        """
        ...

    async def _connect_http(
        self,
        server_def: Any,  # MCPServerDefinition
    ) -> tuple[Any, Any]:
        """Establish an HTTP/SSE transport connection.

        Connects to the configured URL. If auth is configured,
        creates an httpx.AsyncClient with bearer token header.

        Returns:
            Tuple of (read_stream, write_stream) for ClientSession.
        """
        ...

    async def _run_deep_selection(self, task: str) -> None:
        """LLM-based tool selection for deep mode (Phase 2).

        Fetches the full tool catalog, passes it to FAST_LLM along
        with the task description, and unregisters non-selected tools.

        If selection fails, falls back to fast mode (keep all tools)
        and logs a warning.

        Depends on ToolRegistry.describe() from 04-plugins.md.

        Args:
            task: Task description for relevance scoring.

        Logs:
            mcp.deep.selection — selected_count, total_count
            mcp.deep.fallback — reason (on failure)
        """
        ...


# --- Exceptions ---


class MCPConnectionError(Exception):                        # NEW
    """Raised when an MCP server connection fails.

    Attributes:
        server_name: Name of the server that failed.
        transport: Transport type ("stdio" or "http").
        detail: Underlying error message.
    """

    def __init__(
        self,
        server_name: str,
        transport: str,
        detail: str,
    ) -> None:
        ...


class MCPToolExecutionError(Exception):                     # NEW
    """Raised when an MCP tool call fails.

    Attributes:
        server_name: Name of the server.
        tool_name: Name of the tool that failed.
        detail: Underlying error message.
    """

    def __init__(
        self,
        server_name: str,
        tool_name: str,
        detail: str,
    ) -> None:
        ...


# --- Integration Points ---

# HiveFlow.run() integration (pseudocode):
#
#   mcp_config = MCPConfig.from_file()
#   effective_strategy = team_config.mcp_strategy or mcp_config.strategy
#
#   if effective_strategy != "disabled":
#       mcp_config = mcp_config.model_copy(update={"strategy": effective_strategy})
#       mcp_manager = MCPManager(mcp_config, self._tool_registry)
#       try:
#           await mcp_manager.startup(task=task)
#           # ... build agents, run workflow ...
#       finally:
#           await mcp_manager.shutdown()
#   else:
#       # ... build agents, run workflow (no MCP) ...
