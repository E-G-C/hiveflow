"""MCPToolBridge Contract.

Bridges a single MCP server tool into the HiveFlow tool registry
by implementing the existing ToolPlugin interface. Agents interact
with MCP tools via the same _tool_map lookup and to_llm_tool_spec()
flow used for native tools — no agent code changes required.

NOTE: This wraps the existing ToolPlugin at hiveflow/plugins/tools/__init__.py.
No changes to the base ToolPlugin interface are needed.
"""

from typing import Any


# --- Bridge Implementation ---


class MCPToolBridge:                                        # NEW
    """Bridges a single MCP server tool into the ToolPlugin contract.

    Extends ToolPlugin. Each instance represents one tool from one
    MCP server. The tool is registered in the ToolRegistry with
    plugin_id = "mcp:{server_name}/{tool_name}".

    Construction args:
        server_name: Name of the MCP server (from config).
        tool_name: Tool name as reported by the MCP server.
        description: Tool description from MCP server.
        input_schema: JSON Schema dict from MCP tool inputSchema.
        call_fn: Async callable for executing tool calls.
            Signature: async (tool_name: str, arguments: dict) -> CallToolResult
    """

    def __init__(
        self,
        server_name: str,
        tool_name: str,
        description: str,
        input_schema: dict[str, Any],
        call_fn: Any,  # async callable
    ) -> None:
        """
        Args:
            server_name: MCP server name from configuration.
            tool_name: Tool name within the MCP server.
            description: Human-readable tool description.
            input_schema: JSON Schema for tool input parameters.
            call_fn: Async callable that executes the tool call
                     via the MCP ClientSession. Signature:
                     async (name: str, arguments: dict) -> CallToolResult
        """
        ...

    # --- ToolPlugin interface ---

    @property
    def plugin_id(self) -> str:
        """Always server-qualified: 'mcp:{server_name}/{tool_name}'.

        Examples:
            mcp:jira/search
            mcp:company_db/query
            mcp:local_tools/file_read
        """
        ...

    @property
    def server_name(self) -> str:
        """The MCP server this tool belongs to."""
        ...

    @property
    def tool_name(self) -> str:
        """The tool name within the MCP server."""
        ...

    @property
    def description(self) -> str:
        """Tool description from the MCP server."""
        ...

    @property
    def input_schema(self) -> dict[str, Any]:
        """JSON Schema for input parameters, from MCP tool spec."""
        ...

    @property
    def output_schema(self) -> dict[str, Any]:
        """Generic object schema.

        MCP tools return flexible content (text, images, resources).
        The normalized output is always a dict.
        """
        return {"type": "object"}

    async def execute(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        """Execute the MCP tool call and normalize the result.

        Calls the MCP server via call_fn, then normalizes the
        CallToolResult into a dict:

        - TextContent → {"result": combined_text}
        - ImageContent → adds "images" list
        - isError=True → {"error": error_text}
        - Connection failure → {"error": "MCP server '{server}' disconnected..."}

        Args:
            tool_input: Tool arguments matching input_schema.

        Returns:
            Normalized result dict.

        Logs:
            mcp.tool.execute — server_name, tool_name, success/error
        """
        ...

    def to_llm_tool_spec(self) -> dict[str, Any]:
        """Generate OpenAI-compatible function calling spec.

        Returns a spec with a SANITIZED function name suitable for
        LLM providers that restrict names to [a-zA-Z0-9_-]:

            plugin_id: mcp:jira/search       (registry ID)
            LLM name:  mcp_jira__search      (: → _, / → __)

        The agent's _tool_map maps BOTH the plugin_id and the
        sanitized LLM name to this bridge instance, so LLM tool
        calls using the sanitized name dispatch correctly.

        Returns:
            Dict with "type": "function" and "function" spec.
        """
        ...

    @property
    def llm_name(self) -> str:
        """Sanitized tool name for LLM function calling.

        Converts 'mcp:{server}/{tool}' to 'mcp_{server}__{tool}'.
        """
        ...


# --- Output Normalization ---

def normalize_call_result(result: Any) -> dict[str, Any]:   # NEW
    """Normalize an MCP CallToolResult to a dict.

    Rules:
    - result.isError is True → {"error": combined_text}
    - Single TextContent → {"result": content.text}
    - Multiple TextContent → {"result": "\\n".join(texts)}
    - ImageContent present → {"result": text, "images": [...]}
    - EmbeddedResource present → {"result": text, "resources": [...]}
    - Empty content list → {"result": ""}

    Args:
        result: MCP CallToolResult object.

    Returns:
        Normalized dict suitable for ToolPlugin.execute() return.
    """
    ...
