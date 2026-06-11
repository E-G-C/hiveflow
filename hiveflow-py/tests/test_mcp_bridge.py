"""Tests for MCPToolBridge and normalize_call_result.

Covers:
- plugin_id format (mcp:{server}/{tool})
- description/input_schema passthrough
- execute() with mock call_fn returning TextContent
- execute() with isError=True returns error dict
- execute() with disconnected server returns error
- to_llm_tool_spec() returns sanitized name
- llm_name property
- normalize_call_result for all content types
"""

from typing import Any
from unittest.mock import AsyncMock

import pytest

mcp_types = pytest.importorskip("mcp.types", reason="mcp package not installed")
from mcp.types import (
    CallToolResult,
    EmbeddedResource,
    ImageContent,
    TextContent,
    TextResourceContents,
)

from hiveflow.plugins.mcp.bridge import MCPToolBridge, normalize_call_result


def _make_bridge(
    server: str = "github",
    tool: str = "search",
    desc: str = "Search repos",
    schema: dict[str, Any] | None = None,
    call_fn: Any = None,
) -> MCPToolBridge:
    return MCPToolBridge(
        server_name=server,
        tool_name=tool,
        description=desc,
        input_schema=schema or {"type": "object", "properties": {"q": {"type": "string"}}},
        call_fn=call_fn or AsyncMock(),
    )


# --- MCPToolBridge property tests ---


class TestMCPToolBridgeProperties:
    def test_plugin_id_format(self) -> None:
        bridge = _make_bridge(server="github", tool="search")
        assert bridge.plugin_id == "mcp:github/search"

    def test_plugin_id_with_special_chars(self) -> None:
        bridge = _make_bridge(server="my-server", tool="do_thing")
        assert bridge.plugin_id == "mcp:my-server/do_thing"

    def test_llm_name_sanitized(self) -> None:
        bridge = _make_bridge(server="github", tool="search")
        assert bridge.llm_name == "mcp_github__search"

    def test_description_passthrough(self) -> None:
        bridge = _make_bridge(desc="Find code in repos")
        assert bridge.description == "Find code in repos"

    def test_input_schema_passthrough(self) -> None:
        schema = {"type": "object", "properties": {"query": {"type": "string"}}}
        bridge = _make_bridge(schema=schema)
        assert bridge.input_schema == schema

    def test_output_schema_generic(self) -> None:
        bridge = _make_bridge()
        assert bridge.output_schema == {"type": "object"}

    def test_server_name(self) -> None:
        bridge = _make_bridge(server="my_server")
        assert bridge.server_name == "my_server"

    def test_tool_name(self) -> None:
        bridge = _make_bridge(tool="list_repos")
        assert bridge.tool_name == "list_repos"


class TestToLLMToolSpec:
    def test_spec_structure(self) -> None:
        bridge = _make_bridge(server="gh", tool="search", desc="Search repos")
        spec = bridge.to_llm_tool_spec()
        assert spec["type"] == "function"
        assert spec["function"]["name"] == "mcp_gh__search"
        assert spec["function"]["description"] == "Search repos"
        assert spec["function"]["parameters"] == bridge.input_schema

    def test_spec_uses_llm_name_not_plugin_id(self) -> None:
        bridge = _make_bridge(server="gh", tool="search")
        spec = bridge.to_llm_tool_spec()
        assert ":" not in spec["function"]["name"]
        assert "/" not in spec["function"]["name"]


# --- execute() tests ---


class TestExecute:
    @pytest.mark.asyncio
    async def test_execute_text_content(self) -> None:
        call_fn = AsyncMock(return_value=CallToolResult(
            content=[TextContent(type="text", text="found 3 repos")],
            isError=False,
        ))
        bridge = _make_bridge(call_fn=call_fn)
        result = await bridge.execute({"q": "hiveflow"})
        assert result == {"result": "found 3 repos"}
        call_fn.assert_awaited_once_with("search", {"q": "hiveflow"})

    @pytest.mark.asyncio
    async def test_execute_error_result(self) -> None:
        call_fn = AsyncMock(return_value=CallToolResult(
            content=[TextContent(type="text", text="rate limited")],
            isError=True,
        ))
        bridge = _make_bridge(call_fn=call_fn)
        result = await bridge.execute({"q": "test"})
        assert result == {"error": "rate limited"}

    @pytest.mark.asyncio
    async def test_execute_server_disconnect(self) -> None:
        call_fn = AsyncMock(side_effect=ConnectionError("pipe broken"))
        bridge = _make_bridge(server="gh", call_fn=call_fn)
        result = await bridge.execute({"q": "test"})
        assert "error" in result
        assert "gh" in result["error"]
        assert "pipe broken" in result["error"]

    @pytest.mark.asyncio
    async def test_execute_passes_tool_input(self) -> None:
        call_fn = AsyncMock(return_value=CallToolResult(content=[], isError=False))
        bridge = _make_bridge(tool="create_issue", call_fn=call_fn)
        await bridge.execute({"title": "Bug", "body": "Details"})
        call_fn.assert_awaited_once_with("create_issue", {"title": "Bug", "body": "Details"})


# --- normalize_call_result() tests ---


class TestNormalizeCallResult:
    def test_single_text(self) -> None:
        result = CallToolResult(
            content=[TextContent(type="text", text="hello")],
            isError=False,
        )
        assert normalize_call_result(result) == {"result": "hello"}

    def test_multiple_text_joined(self) -> None:
        result = CallToolResult(
            content=[
                TextContent(type="text", text="line 1"),
                TextContent(type="text", text="line 2"),
            ],
            isError=False,
        )
        assert normalize_call_result(result) == {"result": "line 1\nline 2"}

    def test_empty_content(self) -> None:
        result = CallToolResult(content=[], isError=False)
        assert normalize_call_result(result) == {"result": ""}

    def test_error_with_text(self) -> None:
        result = CallToolResult(
            content=[TextContent(type="text", text="bad request")],
            isError=True,
        )
        assert normalize_call_result(result) == {"error": "bad request"}

    def test_error_without_text(self) -> None:
        result = CallToolResult(content=[], isError=True)
        assert normalize_call_result(result) == {"error": "Unknown MCP error"}

    def test_image_content(self) -> None:
        result = CallToolResult(
            content=[
                TextContent(type="text", text="chart"),
                ImageContent(type="image", data="base64data", mimeType="image/png"),
            ],
            isError=False,
        )
        normalized = normalize_call_result(result)
        assert normalized["result"] == "chart"
        assert normalized["images"] == [{"data": "base64data", "mimeType": "image/png"}]

    def test_embedded_resource_text(self) -> None:
        resource = TextResourceContents(
            uri="file:///readme.md",
            text="# README",
            mimeType="text/markdown",
        )
        result = CallToolResult(
            content=[EmbeddedResource(type="resource", resource=resource)],
            isError=False,
        )
        normalized = normalize_call_result(result)
        assert normalized["result"] == ""
        assert len(normalized["resources"]) == 1
        assert normalized["resources"][0]["uri"] == "file:///readme.md"
        assert normalized["resources"][0]["text"] == "# README"

    def test_mixed_content_types(self) -> None:
        result = CallToolResult(
            content=[
                TextContent(type="text", text="summary"),
                ImageContent(type="image", data="img1", mimeType="image/jpeg"),
                TextContent(type="text", text="more details"),
            ],
            isError=False,
        )
        normalized = normalize_call_result(result)
        assert normalized["result"] == "summary\nmore details"
        assert len(normalized["images"]) == 1

    def test_no_images_key_when_no_images(self) -> None:
        result = CallToolResult(
            content=[TextContent(type="text", text="just text")],
            isError=False,
        )
        normalized = normalize_call_result(result)
        assert "images" not in normalized
        assert "resources" not in normalized
