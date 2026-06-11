"""MCP Tool Bridge.

Wraps a single MCP server tool as a ToolPlugin for transparent use by agents.
Each instance represents one tool from one MCP server.
"""

from typing import Any

import structlog

from hiveflow.plugins.tools import ToolPlugin

logger = structlog.get_logger(__name__)


class MCPToolBridge(ToolPlugin):
    """Bridges a single MCP server tool into the ToolPlugin contract.

    Registered in the ToolRegistry with plugin_id = "mcp:{server}/{tool}".
    Agents interact with MCP tools via the same _tool_map lookup and
    to_llm_tool_spec() flow used for native tools.
    """

    def __init__(
        self,
        server_name: str,
        tool_name: str,
        description: str,
        input_schema: dict[str, Any],
        call_fn: Any,
    ) -> None:
        self._server_name = server_name
        self._tool_name = tool_name
        self._description = description
        self._input_schema = input_schema
        self._call_fn = call_fn

    @property
    def plugin_id(self) -> str:
        return f"mcp:{self._server_name}/{self._tool_name}"

    @property
    def server_name(self) -> str:
        return self._server_name

    @property
    def tool_name(self) -> str:
        return self._tool_name

    @property
    def description(self) -> str:
        return self._description

    @property
    def input_schema(self) -> dict[str, Any]:
        return self._input_schema

    @property
    def output_schema(self) -> dict[str, Any]:
        return {"type": "object"}

    @property
    def llm_name(self) -> str:
        """Sanitized tool name for LLM function calling.

        Converts 'mcp:{server}/{tool}' to 'mcp_{server}__{tool}'.
        """
        return f"mcp_{self._server_name}__{self._tool_name}"

    async def execute(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        """Execute the MCP tool call and normalize the result.

        Calls the MCP server via call_fn, then normalizes the
        CallToolResult into a dict via normalize_call_result().
        """
        log = logger.bind(
            server_name=self._server_name,
            tool_name=self._tool_name,
        )
        try:
            result = await self._call_fn(self._tool_name, tool_input)
            normalized = normalize_call_result(result)
            if "error" in normalized:
                log.warning("mcp.tool.execute", success=False, error=normalized["error"])
            else:
                log.debug("mcp.tool.execute", success=True)
            return normalized
        except Exception as exc:
            log.error("mcp.tool.execute", success=False, error=str(exc))
            return {"error": f"MCP server '{self._server_name}' disconnected: {exc}"}

    def to_llm_tool_spec(self) -> dict[str, Any]:
        """Generate OpenAI-compatible function calling spec with sanitized name."""
        return {
            "type": "function",
            "function": {
                "name": self.llm_name,
                "description": self._description,
                "parameters": self._input_schema,
            },
        }


def normalize_call_result(result: Any) -> dict[str, Any]:
    """Normalize an MCP CallToolResult to a dict.

    Rules:
    - result.isError is True -> {"error": combined_text}
    - TextContent -> {"result": combined_text}
    - ImageContent present -> adds "images" list
    - EmbeddedResource present -> adds "resources" list
    - Empty content list -> {"result": ""}
    """
    from mcp.types import EmbeddedResource, ImageContent, TextContent

    content_items = result.content or []

    # Collect text parts
    texts: list[str] = []
    images: list[dict[str, str]] = []
    resources: list[dict[str, Any]] = []

    for item in content_items:
        if isinstance(item, TextContent):
            texts.append(item.text)
        elif isinstance(item, ImageContent):
            images.append({"data": item.data, "mimeType": item.mimeType})
        elif isinstance(item, EmbeddedResource):
            resource = item.resource
            resource_dict: dict[str, Any] = {"uri": str(resource.uri)}
            if hasattr(resource, "text"):
                resource_dict["text"] = resource.text
            if hasattr(resource, "blob"):
                resource_dict["blob"] = resource.blob
            if hasattr(resource, "mimeType") and resource.mimeType:
                resource_dict["mimeType"] = resource.mimeType
            resources.append(resource_dict)

    combined_text = "\n".join(texts) if texts else ""

    # Error case
    if result.isError:
        return {"error": combined_text or "Unknown MCP error"}

    # Build normalized output
    output: dict[str, Any] = {"result": combined_text}
    if images:
        output["images"] = images
    if resources:
        output["resources"] = resources

    return output
