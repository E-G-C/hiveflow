"""MCP Configuration Models Contract.

Defines the pydantic models for MCP server configuration,
loaded from a dedicated JSON file (default: .hiveflow/mcp.json).

These models are separate from HiveFlowConfig because MCP config
involves nested structures (server lists with per-server auth)
that do not fit the flat HIVEFLOW_-prefixed environment variable pattern.
"""

from typing import Any, Literal

# --- Authentication ---


class MCPAuthConfig:                                        # NEW
    """Authentication configuration for an HTTP MCP server.

    Currently supports bearer token auth. OAuth support may be
    added in a future release.

    Fields:
        type: Authentication type. Currently only "bearer".
        env: Name of the environment variable holding the token.
    """

    type: Literal["bearer"]
    env: str

    # Resolution: os.environ[self.env] at connection time.
    # Raises clear error if env var not set:
    #   "MCP server '{server_name}' requires bearer token in
    #    env var '{self.env}' but it is not set"


# --- Server Definition ---


class MCPServerDefinition:                                  # NEW
    """A single MCP server configuration entry.

    Fields:
        name: Unique server name (used in tool IDs: mcp:{name}/{tool}).
        transport: "stdio" (local process) or "http" (remote URL).
        url: Server URL (required for http transport).
        command: Executable to spawn (required for stdio transport).
        args: Arguments for spawned process (stdio only).
        env: Additional environment variables for process (stdio only).
        auth: Authentication config (http only).
        lazy: If True, defer connection until first tool use.
    """

    name: str
    transport: Literal["stdio", "http"]
    url: str | None = None
    command: str | None = None
    args: list[str] = []
    env: dict[str, str] | None = None
    auth: MCPAuthConfig | None = None
    lazy: bool = False

    # Validators:

    def _validate_http_fields(self) -> None:
        """url MUST be set when transport == 'http'.
        auth is only valid when transport == 'http'.
        """
        ...

    def _validate_stdio_fields(self) -> None:
        """command MUST be set when transport == 'stdio'.
        env and args are only valid when transport == 'stdio'.
        """
        ...


# --- Top-Level Config ---


class MCPConfig:                                            # NEW
    """Top-level MCP configuration.

    Loaded from a dedicated JSON file. Default location:
    .hiveflow/mcp.json, overridable via HIVEFLOW_MCP_CONFIG env var.

    Fields:
        strategy: Global MCP strategy mode.
        servers: List of configured MCP servers.
    """

    strategy: Literal["disabled", "fast", "deep"] = "disabled"
    servers: list[MCPServerDefinition] = []

    # Validators:
    #   - Server names MUST be unique
    #   - Warn if strategy != "disabled" but servers list is empty

    @classmethod
    def from_file(cls, path: str | None = None) -> "MCPConfig":
        """Load MCP configuration from a JSON file.

        Resolution order:
        1. Explicit path argument
        2. HIVEFLOW_MCP_CONFIG environment variable
        3. Default: .hiveflow/mcp.json

        If no file exists and no env var is set, returns
        MCPConfig(strategy="disabled") — MCP is silently off.

        If the file exists but is malformed, raises ValueError
        with a descriptive message.

        Args:
            path: Optional explicit file path.

        Returns:
            Parsed MCPConfig instance.
        """
        ...

    def get_server(self, name: str) -> MCPServerDefinition | None:
        """Look up a server definition by name.

        Args:
            name: Server name.

        Returns:
            MCPServerDefinition or None if not found.
        """
        ...

    def get_eager_servers(self) -> list[MCPServerDefinition]:
        """Return servers that should connect eagerly (lazy=False).

        Returns:
            List of non-lazy server definitions.
        """
        ...

    def get_lazy_servers(self) -> list[MCPServerDefinition]:
        """Return servers configured with lazy=True.

        Returns:
            List of lazy server definitions.
        """
        ...


# --- Example mcp.json ---

EXAMPLE_CONFIG: dict[str, Any] = {
    "strategy": "fast",
    "servers": [
        {
            "name": "company_db",
            "transport": "http",
            "url": "http://mcp-db-server:8080",
            "auth": {"type": "bearer", "env": "MCP_DB_TOKEN"},
        },
        {
            "name": "local_tools",
            "transport": "stdio",
            "command": "my-mcp-tool-server",
            "args": ["--verbose"],
        },
        {
            "name": "jira",
            "transport": "http",
            "url": "http://mcp-jira-server:8080",
            "lazy": True,
        },
    ],
}
