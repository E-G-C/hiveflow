"""MCP Configuration Models.

Pydantic models for parsing the MCP configuration file (mcp.json).
These models have no dependency on the mcp SDK package.

Default config path: .hiveflow/mcp.json
Override via: HIVEFLOW_MCP_CONFIG environment variable
"""

import json
import os
from pathlib import Path
from typing import Literal

import structlog
from pydantic import BaseModel, model_validator

logger = structlog.get_logger(__name__)

DEFAULT_MCP_CONFIG_PATH = ".hiveflow/mcp.json"
MCP_CONFIG_ENV_VAR = "HIVEFLOW_MCP_CONFIG"


class MCPAuthConfig(BaseModel):
    """Authentication configuration for an HTTP MCP server.

    Currently supports bearer token auth. The token value is resolved
    from an environment variable at connection time, not at config load.
    """

    type: Literal["bearer"] = "bearer"
    env: str


class MCPServerDefinition(BaseModel):
    """A single MCP server configuration entry.

    Attributes:
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

    @model_validator(mode="after")
    def _validate_transport_fields(self) -> "MCPServerDefinition":
        if self.transport == "http":
            if not self.url:
                raise ValueError(f"MCP server '{self.name}': 'url' is required for http transport")
            if self.command is not None:
                raise ValueError(
                    f"MCP server '{self.name}': 'command' is not valid for http transport"
                )
        elif self.transport == "stdio":
            if not self.command:
                raise ValueError(
                    f"MCP server '{self.name}': 'command' is required for stdio transport"
                )
            if self.url is not None:
                raise ValueError(
                    f"MCP server '{self.name}': 'url' is not valid for stdio transport"
                )
            if self.auth is not None:
                raise ValueError(
                    f"MCP server '{self.name}': 'auth' is not valid for stdio transport"
                )
        return self


class MCPConfig(BaseModel):
    """Top-level MCP configuration.

    Loaded from a dedicated JSON file. Default location:
    .hiveflow/mcp.json, overridable via HIVEFLOW_MCP_CONFIG env var.

    Attributes:
        strategy: Global MCP strategy mode.
        servers: List of configured MCP servers.
    """

    strategy: Literal["disabled", "fast", "deep"] = "disabled"
    servers: list[MCPServerDefinition] = []

    @model_validator(mode="after")
    def _validate_servers(self) -> "MCPConfig":
        # Check for duplicate server names
        names = [s.name for s in self.servers]
        seen: set[str] = set()
        for name in names:
            if name in seen:
                raise ValueError(f"Duplicate MCP server name: '{name}'")
            seen.add(name)

        # Warn if strategy is active but no servers configured
        if self.strategy != "disabled" and not self.servers:
            logger.warning(
                "mcp.config.no_servers",
                strategy=self.strategy,
                hint="MCP strategy is active but no servers are configured",
            )

        return self

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

        Raises:
            ValueError: If the config file exists but cannot be parsed.
        """
        config_path = _resolve_config_path(path)

        if config_path is None:
            return cls()

        try:
            raw = Path(config_path).read_text(encoding="utf-8")
        except OSError as e:
            raise ValueError(f"Cannot read MCP config file '{config_path}': {e}") from e

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"MCP config file '{config_path}' is not valid JSON: {e}") from e

        if not isinstance(data, dict):
            raise ValueError(
                f"MCP config file '{config_path}' must contain a JSON object, "
                f"got {type(data).__name__}"
            )

        logger.info(
            "mcp.config.loaded",
            path=str(config_path),
            strategy=data.get("strategy", "disabled"),
            server_count=len(data.get("servers", [])),
        )

        return cls.model_validate(data)

    def get_server(self, name: str) -> MCPServerDefinition | None:
        """Look up a server definition by name."""
        for server in self.servers:
            if server.name == name:
                return server
        return None

    def get_eager_servers(self) -> list[MCPServerDefinition]:
        """Return servers that should connect eagerly (lazy=False)."""
        return [s for s in self.servers if not s.lazy]

    def get_lazy_servers(self) -> list[MCPServerDefinition]:
        """Return servers configured with lazy=True."""
        return [s for s in self.servers if s.lazy]


def _resolve_config_path(explicit_path: str | None) -> str | None:
    """Resolve the MCP config file path.

    Returns None if no config file is found (MCP silently disabled).
    """
    if explicit_path:
        path = Path(explicit_path)
        if not path.exists():
            raise ValueError(f"MCP config file not found: '{explicit_path}'")
        return explicit_path

    env_path = os.environ.get(MCP_CONFIG_ENV_VAR)
    if env_path:
        path = Path(env_path)
        if not path.exists():
            raise ValueError(
                f"MCP config file specified by {MCP_CONFIG_ENV_VAR} not found: '{env_path}'"
            )
        return env_path

    default_path = Path(DEFAULT_MCP_CONFIG_PATH)
    if default_path.exists():
        return str(default_path)

    return None
