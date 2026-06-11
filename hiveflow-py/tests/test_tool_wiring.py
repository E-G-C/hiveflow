"""Tests for tool wiring in TeamGenerator.build().

Verifies that:
- build() with tool_registry resolves tools from agent definitions
- build() without tool_registry preserves backward compatibility
- Missing tool IDs raise KeyError
- tool_user agents fall back to llm_only when no tools resolved
- tool_user agents keep behavior when tools are resolved
"""

from typing import Any
from unittest.mock import MagicMock

import pytest

from hiveflow.core.agent import AgentBehaviorType
from hiveflow.core.teams import TeamGenerator
from hiveflow.plugins.tools import ToolPlugin, ToolRegistry


class FakeTool(ToolPlugin):
    """Minimal tool for testing."""

    def __init__(self, tool_id: str) -> None:
        self._id = tool_id

    @property
    def plugin_id(self) -> str:
        return self._id

    @property
    def description(self) -> str:
        return f"Fake tool {self._id}"

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    @property
    def output_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        return {"result": "ok"}


def _minimal_config(
    *,
    agent_tools: list[str] | None = None,
    behavior_type: str = "llm_only",
) -> dict[str, Any]:
    """Build a minimal team config dict for build()."""
    agent = {
        "id": "agent_1",
        "name": "Test Agent",
        "role": "tester",
        "model": "gpt-4o",
        "system_prompt": "You are a test agent.",
        "behavior_type": behavior_type,
    }
    if agent_tools is not None:
        agent["tools"] = agent_tools
    return {
        "agents": [agent],
        "workflow": {
            "steps": [
                {"agent": "agent_1", "type": "sequential"},
            ],
        },
    }


def _make_registry(*tools: FakeTool) -> ToolRegistry:
    """Create a ToolRegistry pre-loaded with the given tools."""
    registry = ToolRegistry(drop_in_dir=None)
    for tool in tools:
        registry.register(tool)
    return registry


class TestBuildWithoutRegistry:
    """build() without tool_registry (backward compatibility)."""

    def test_agents_have_no_tools(self) -> None:
        gen = TeamGenerator()
        config = _minimal_config()
        agents, _engine = gen.build(config, MagicMock())
        assert agents["agent_1"].tools == []

    def test_tool_user_falls_back_to_llm_only(self) -> None:
        gen = TeamGenerator()
        config = _minimal_config(behavior_type="tool_user")
        agents, _engine = gen.build(config, MagicMock())
        assert agents["agent_1"].behavior_type == AgentBehaviorType.LLM_ONLY

    def test_tools_in_config_ignored_without_registry(self) -> None:
        gen = TeamGenerator()
        config = _minimal_config(agent_tools=["web_search"], behavior_type="tool_user")
        agents, _engine = gen.build(config, MagicMock())
        assert agents["agent_1"].tools == []
        assert agents["agent_1"].behavior_type == AgentBehaviorType.LLM_ONLY


class TestBuildWithRegistry:
    """build() with tool_registry resolves tools."""

    def test_resolves_tools_from_registry(self) -> None:
        tool = FakeTool("web_search")
        registry = _make_registry(tool)
        gen = TeamGenerator()
        config = _minimal_config(agent_tools=["web_search"], behavior_type="tool_user")
        agents, _engine = gen.build(config, MagicMock(), tool_registry=registry)
        assert len(agents["agent_1"].tools) == 1
        assert agents["agent_1"].tools[0].plugin_id == "web_search"

    def test_tool_user_keeps_behavior_with_tools(self) -> None:
        tool = FakeTool("web_search")
        registry = _make_registry(tool)
        gen = TeamGenerator()
        config = _minimal_config(agent_tools=["web_search"], behavior_type="tool_user")
        agents, _engine = gen.build(config, MagicMock(), tool_registry=registry)
        assert agents["agent_1"].behavior_type == AgentBehaviorType.TOOL_USER

    def test_agent_model_resolves_provider_from_model_ref(self) -> None:
        gen = TeamGenerator()
        config = {
            "agents": [
                {
                    "id": "agent_1",
                    "name": "Test Agent",
                    "role": "tester",
                    "model": "perplexity:sonar-pro",
                    "system_prompt": "You are a test agent.",
                    "behavior_type": "llm_only",
                }
            ],
            "workflow": {"steps": [{"agent": "agent_1", "type": "sequential"}]},
        }

        agents, _engine = gen.build(config, None, enable_summaries=False)
        assert agents["agent_1"].llm_provider is not None
        assert agents["agent_1"].llm_provider._fallback_chain._providers[0][0].provider_id == "perplexity"

    def test_multiple_tools_resolved(self) -> None:
        t1 = FakeTool("web_search")
        t2 = FakeTool("file_reader")
        registry = _make_registry(t1, t2)
        gen = TeamGenerator()
        config = _minimal_config(agent_tools=["web_search", "file_reader"], behavior_type="tool_user")
        agents, _engine = gen.build(config, MagicMock(), tool_registry=registry)
        tool_ids = {t.plugin_id for t in agents["agent_1"].tools}
        assert tool_ids == {"web_search", "file_reader"}

    def test_missing_tool_raises_key_error(self) -> None:
        registry = _make_registry()  # empty
        gen = TeamGenerator()
        config = _minimal_config(agent_tools=["nonexistent"], behavior_type="tool_user")
        with pytest.raises(KeyError, match="nonexistent"):
            gen.build(config, MagicMock(), tool_registry=registry)

    def test_no_tools_in_config_no_resolution(self) -> None:
        tool = FakeTool("web_search")
        registry = _make_registry(tool)
        gen = TeamGenerator()
        config = _minimal_config(behavior_type="llm_only")
        agents, _engine = gen.build(config, MagicMock(), tool_registry=registry)
        assert agents["agent_1"].tools == []

    def test_empty_tools_list_no_resolution(self) -> None:
        tool = FakeTool("web_search")
        registry = _make_registry(tool)
        gen = TeamGenerator()
        config = _minimal_config(agent_tools=[], behavior_type="tool_user")
        agents, _engine = gen.build(config, MagicMock(), tool_registry=registry)
        assert agents["agent_1"].tools == []
        assert agents["agent_1"].behavior_type == AgentBehaviorType.LLM_ONLY

    def test_tool_user_fallback_when_tools_not_in_registry(self) -> None:
        """tool_user with tool IDs but registry has none -> fallback to llm_only."""
        registry = _make_registry()  # empty
        gen = TeamGenerator()
        config = _minimal_config(agent_tools=["missing_tool"], behavior_type="tool_user")
        # get_tools_for_agent raises KeyError for missing tools
        with pytest.raises(KeyError):
            gen.build(config, MagicMock(), tool_registry=registry)


class TestMixedNativeAndMCPTools:
    """T022+T023+T024: Mixed native and MCP tools in team configs."""

    def test_mixed_native_and_mcp_tools_in_one_agent(self) -> None:
        """Build a team config with native and MCP tools, verify both resolved."""
        from hiveflow.plugins.mcp.bridge import MCPToolBridge

        native_tool = FakeTool("web_search")
        mcp_tool = MCPToolBridge(
            server_name="local_tools",
            tool_name="file_read",
            description="Read a file",
            input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
            call_fn=MagicMock(),
        )
        registry = _make_registry(native_tool)
        registry.register(mcp_tool)

        gen = TeamGenerator()
        config = _minimal_config(
            agent_tools=["web_search", "mcp:local_tools/file_read"],
            behavior_type="tool_user",
        )
        agents, _engine = gen.build(config, MagicMock(), tool_registry=registry)

        agent = agents["agent_1"]
        assert len(agent.tools) == 2
        tool_ids = {t.plugin_id for t in agent.tools}
        assert tool_ids == {"web_search", "mcp:local_tools/file_read"}
        assert agent.behavior_type == AgentBehaviorType.TOOL_USER

        # Verify _tool_map has both plugin_id and llm_name entries
        assert "web_search" in agent._tool_map
        assert "mcp:local_tools/file_read" in agent._tool_map
        assert "mcp_local_tools__file_read" in agent._tool_map  # sanitized llm_name

    def test_native_and_mcp_tool_name_collision(self) -> None:
        """Native 'search' and MCP 'mcp:serverA/search' coexist."""
        from hiveflow.plugins.mcp.bridge import MCPToolBridge

        native_search = FakeTool("search")
        mcp_search = MCPToolBridge(
            server_name="serverA",
            tool_name="search",
            description="MCP search",
            input_schema={"type": "object"},
            call_fn=MagicMock(),
        )
        registry = _make_registry(native_search)
        registry.register(mcp_search)

        gen = TeamGenerator()
        config = _minimal_config(
            agent_tools=["search", "mcp:serverA/search"],
            behavior_type="tool_user",
        )
        agents, _engine = gen.build(config, MagicMock(), tool_registry=registry)

        agent = agents["agent_1"]
        assert len(agent.tools) == 2

        # Both are in _tool_map under their own plugin_id
        assert "search" in agent._tool_map
        assert "mcp:serverA/search" in agent._tool_map

        # They are different tool instances
        assert agent._tool_map["search"] is not agent._tool_map["mcp:serverA/search"]

        # MCP also has sanitized name
        assert "mcp_serverA__search" in agent._tool_map

    def test_unconfigured_mcp_server_raises_clear_error(self) -> None:
        """Referencing mcp:missing/tool when not in registry gives KeyError."""
        registry = _make_registry()  # empty
        gen = TeamGenerator()
        config = _minimal_config(
            agent_tools=["mcp:missing/tool"],
            behavior_type="tool_user",
        )
        with pytest.raises(KeyError, match="mcp:missing/tool"):
            gen.build(config, MagicMock(), tool_registry=registry)
