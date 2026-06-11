"""MCP (Model Context Protocol) Integration Plugin.

Provides MCP client support for connecting to external MCP tool servers,
and an MCP gateway for exposing HiveFlow workflows as MCP tools.

Components:
  MCPConfig           - Configuration models for mcp.json
  MCPToolBridge       - Wraps a single MCP tool as a ToolPlugin
  MCPManager          - Manages MCP server connections and tool registration
  MCPGateway          - Exposes HiveFlow workflows as MCP tools for external clients
  MCPConnectionError  - Raised on server connection failure
  MCPToolExecutionError - Raised on tool call failure

The mcp package (mcp>=1.26.0) is an optional dependency. When not installed,
this module logs a warning and exposes only the config models (which do not
require the mcp SDK). The bridge and manager components will not be available.

Install with: uv add 'hiveflow[mcp]'
"""

import structlog

logger = structlog.get_logger(__name__)

# Config models are always available (pure pydantic, no mcp dependency)
from hiveflow.plugins.mcp.config import MCPAuthConfig, MCPConfig, MCPServerDefinition  # noqa: E402

# Bridge and manager require the mcp package
try:
    import mcp  # noqa: F401

    _MCP_AVAILABLE = True
except ImportError:
    _MCP_AVAILABLE = False
    logger.debug(
        "mcp.package_not_installed",
        hint="Install with: uv add 'hiveflow[mcp]'",
    )

if _MCP_AVAILABLE:
    from hiveflow.plugins.mcp.bridge import MCPToolBridge, normalize_call_result
    from hiveflow.plugins.mcp.gateway import MCPGateway
    from hiveflow.plugins.mcp.manager import (
        MCPConnectionError,
        MCPManager,
        MCPToolExecutionError,
    )

__all__ = [
    "MCPAuthConfig",
    "MCPConfig",
    "MCPServerDefinition",
]

if _MCP_AVAILABLE:
    __all__ += [
        "MCPConnectionError",
        "MCPGateway",
        "MCPManager",
        "MCPToolBridge",
        "MCPToolExecutionError",
        "normalize_call_result",
    ]


def is_mcp_available() -> bool:
    """Check if the mcp package is installed and importable."""
    return _MCP_AVAILABLE
