"""Tests for MCPManager.

Covers:
- startup/shutdown lifecycle with mock MCP sessions
- Eager server failure logs and continues
- Disabled strategy is no-op
- Tool registration in ToolRegistry after startup
- ensure_server for lazy connections
- ensure_server raises MCPConnectionError on failure
- ensure_server raises KeyError for unknown server
- is_available property
"""

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("mcp", reason="mcp package not installed")
from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool

from hiveflow.plugins.mcp.config import MCPConfig, MCPServerDefinition
from hiveflow.plugins.mcp.manager import MCPConnectionError, MCPManager
from hiveflow.plugins.tools import ToolRegistry


def _make_config(
    strategy: str = "fast",
    servers: list[dict[str, Any]] | None = None,
) -> MCPConfig:
    if servers is None:
        servers = []
    return MCPConfig(
        strategy=strategy,
        servers=[MCPServerDefinition(**s) for s in servers],
    )


def _mock_tools(names: list[str]) -> ListToolsResult:
    """Create a mock ListToolsResult with the given tool names."""
    tools = [
        Tool(
            name=name,
            description=f"Tool {name}",
            inputSchema={"type": "object", "properties": {}},
        )
        for name in names
    ]
    return ListToolsResult(tools=tools)


class TestStartupShutdown:
    @pytest.mark.asyncio
    async def test_disabled_strategy_is_noop(self) -> None:
        config = _make_config(
            strategy="disabled",
            servers=[{"name": "s1", "transport": "stdio", "command": "echo"}],
        )
        registry = ToolRegistry(drop_in_dir=None)
        mgr = MCPManager(config, registry)

        await mgr.startup()
        assert mgr.get_tools() == []
        assert len(registry.list_ids()) == 0
        await mgr.shutdown()

    @pytest.mark.asyncio
    async def test_startup_connects_eager_servers(self) -> None:
        config = _make_config(
            strategy="fast",
            servers=[{"name": "s1", "transport": "stdio", "command": "echo"}],
        )
        registry = ToolRegistry(drop_in_dir=None)
        mgr = MCPManager(config, registry)

        with patch.object(mgr, "_connect_server") as mock_connect:
            async def side_effect(server_def):
                from hiveflow.plugins.mcp.bridge import MCPToolBridge
                bridges = []
                for name in ["tool_a", "tool_b"]:
                    bridge = MCPToolBridge(
                        server_name=server_def.name,
                        tool_name=name,
                        description=f"Tool {name}",
                        input_schema={"type": "object"},
                        call_fn=AsyncMock(),
                    )
                    bridges.append(bridge)
                    registry.register(bridge)
                mgr._tools.extend(bridges)
                mgr._connected_servers[server_def.name] = AsyncMock()
                return bridges

            mock_connect.side_effect = side_effect
            await mgr.startup()

        assert len(mgr.get_tools()) == 2
        tool_ids = {t.plugin_id for t in mgr.get_tools()}
        assert tool_ids == {"mcp:s1/tool_a", "mcp:s1/tool_b"}
        # Tools should also be in registry
        assert "mcp:s1/tool_a" in registry.list_ids()
        assert "mcp:s1/tool_b" in registry.list_ids()

        await mgr.shutdown()

    @pytest.mark.asyncio
    async def test_eager_failure_logs_and_continues(self) -> None:
        config = _make_config(
            strategy="fast",
            servers=[
                {"name": "bad_server", "transport": "stdio", "command": "nonexistent"},
                {"name": "good_server", "transport": "stdio", "command": "echo"},
            ],
        )
        registry = ToolRegistry(drop_in_dir=None)
        mgr = MCPManager(config, registry)

        async def connect_side_effect(server_def):
            if server_def.name == "bad_server":
                raise ConnectionError("refused")
            # Return mock (read, write) for good server
            return (MagicMock(), MagicMock())

        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session.list_tools = AsyncMock(return_value=_mock_tools(["tool_x"]))

        with patch.object(mgr, "_connect_server") as mock_connect:
            async def side_effect(server_def):
                if server_def.name == "bad_server":
                    raise ConnectionError("refused")
                # Simulate successful connection
                from hiveflow.plugins.mcp.bridge import MCPToolBridge
                bridge = MCPToolBridge(
                    server_name=server_def.name,
                    tool_name="tool_x",
                    description="Tool x",
                    input_schema={"type": "object"},
                    call_fn=AsyncMock(),
                )
                registry.register(bridge)
                mgr._tools.append(bridge)
                mgr._connected_servers[server_def.name] = mock_session
                return [bridge]

            mock_connect.side_effect = side_effect
            await mgr.startup()

        # bad_server failed but good_server succeeded
        assert len(mgr.get_tools()) == 1
        assert mgr.get_tools()[0].server_name == "good_server"

        await mgr.shutdown()

    @pytest.mark.asyncio
    async def test_lazy_servers_skipped_during_startup(self) -> None:
        config = _make_config(
            strategy="fast",
            servers=[
                {"name": "eager", "transport": "stdio", "command": "echo"},
                {"name": "lazy_one", "transport": "stdio", "command": "echo", "lazy": True},
            ],
        )
        registry = ToolRegistry(drop_in_dir=None)
        mgr = MCPManager(config, registry)

        connected_servers: list[str] = []

        with patch.object(mgr, "_connect_server") as mock_connect:
            async def side_effect(server_def):
                connected_servers.append(server_def.name)
                from hiveflow.plugins.mcp.bridge import MCPToolBridge
                bridge = MCPToolBridge(
                    server_name=server_def.name,
                    tool_name="t1",
                    description="T1",
                    input_schema={"type": "object"},
                    call_fn=AsyncMock(),
                )
                registry.register(bridge)
                mgr._tools.append(bridge)
                mgr._connected_servers[server_def.name] = AsyncMock()
                return [bridge]

            mock_connect.side_effect = side_effect
            await mgr.startup()

        # Only eager was connected
        assert connected_servers == ["eager"]

        await mgr.shutdown()


class TestEnsureServer:
    @pytest.mark.asyncio
    async def test_ensure_server_connects_lazy(self) -> None:
        config = _make_config(
            strategy="fast",
            servers=[
                {"name": "lazy_s", "transport": "stdio", "command": "echo", "lazy": True},
            ],
        )
        registry = ToolRegistry(drop_in_dir=None)
        mgr = MCPManager(config, registry)

        with patch.object(mgr, "_connect_server") as mock_connect:
            async def side_effect(server_def):
                from hiveflow.plugins.mcp.bridge import MCPToolBridge
                bridge = MCPToolBridge(
                    server_name=server_def.name,
                    tool_name="t1",
                    description="T1",
                    input_schema={"type": "object"},
                    call_fn=AsyncMock(),
                )
                registry.register(bridge)
                mgr._tools.append(bridge)
                mgr._connected_servers[server_def.name] = AsyncMock()
                return [bridge]

            mock_connect.side_effect = side_effect
            await mgr.ensure_server("lazy_s")

        assert "lazy_s" in mgr._connected_servers
        assert len(mgr.get_tools()) == 1

        await mgr.shutdown()

    @pytest.mark.asyncio
    async def test_ensure_server_noop_if_already_connected(self) -> None:
        config = _make_config(strategy="fast", servers=[])
        registry = ToolRegistry(drop_in_dir=None)
        mgr = MCPManager(config, registry)
        mgr._connected_servers["s1"] = AsyncMock()

        # Should not raise or do anything
        await mgr.ensure_server("s1")

    @pytest.mark.asyncio
    async def test_ensure_server_raises_key_error_for_unknown(self) -> None:
        config = _make_config(strategy="fast", servers=[])
        registry = ToolRegistry(drop_in_dir=None)
        mgr = MCPManager(config, registry)

        with pytest.raises(KeyError, match="not_in_config"):
            await mgr.ensure_server("not_in_config")

    @pytest.mark.asyncio
    async def test_ensure_server_raises_connection_error_on_failure(self) -> None:
        config = _make_config(
            strategy="fast",
            servers=[
                {"name": "flaky", "transport": "stdio", "command": "echo"},
            ],
        )
        registry = ToolRegistry(drop_in_dir=None)
        mgr = MCPManager(config, registry)

        with patch.object(mgr, "_connect_server", side_effect=ConnectionError("refused")):
            with pytest.raises(MCPConnectionError) as exc_info:
                await mgr.ensure_server("flaky")
            assert exc_info.value.server_name == "flaky"
            assert exc_info.value.transport == "stdio"


class TestIsAvailable:
    def test_is_available_when_mcp_installed(self) -> None:
        config = _make_config(strategy="disabled")
        registry = ToolRegistry(drop_in_dir=None)
        mgr = MCPManager(config, registry)
        assert mgr.is_available is True

    def test_is_available_false_when_mcp_missing(self) -> None:
        config = _make_config(strategy="disabled")
        registry = ToolRegistry(drop_in_dir=None)
        mgr = MCPManager(config, registry)
        with patch.dict("sys.modules", {"mcp": None}):
            with patch("builtins.__import__", side_effect=ImportError("no mcp")):
                assert mgr.is_available is False


class TestMCPManagerIntegration:
    """Integration test: full lifecycle with mocked transport."""

    @pytest.mark.asyncio
    async def test_full_lifecycle_mock_stdio(self) -> None:
        """Test startup -> discover tools -> call tool -> shutdown."""
        config = _make_config(
            strategy="fast",
            servers=[{"name": "test_srv", "transport": "stdio", "command": "echo"}],
        )
        registry = ToolRegistry(drop_in_dir=None)
        mgr = MCPManager(config, registry)

        # Prepare mock session
        call_result = CallToolResult(
            content=[TextContent(type="text", text="tool output")],
            isError=False,
        )
        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()
        mock_session.list_tools = AsyncMock(return_value=_mock_tools(["greet", "farewell"]))
        mock_session.call_tool = AsyncMock(return_value=call_result)

        # Mock _connect_stdio to return fake streams
        mock_read = AsyncMock()
        mock_write = AsyncMock()

        with patch.object(mgr, "_connect_stdio", new_callable=AsyncMock) as mock_stdio:
            mock_stdio.return_value = (mock_read, mock_write)
            with patch("mcp.client.session.ClientSession") as MockSessionCls:
                # Make ClientSession work as async context manager
                MockSessionCls.return_value = mock_session
                mock_session.__aenter__ = AsyncMock(return_value=mock_session)
                mock_session.__aexit__ = AsyncMock(return_value=False)

                await mgr.startup()

        # Verify tools discovered
        assert len(mgr.get_tools()) == 2
        assert {t.plugin_id for t in mgr.get_tools()} == {
            "mcp:test_srv/greet",
            "mcp:test_srv/farewell",
        }

        # Verify tools registered in registry
        assert "mcp:test_srv/greet" in registry.list_ids()
        assert "mcp:test_srv/farewell" in registry.list_ids()

        # Call a tool through the bridge
        greet_tool = registry.get_or_raise("mcp:test_srv/greet")
        result = await greet_tool.execute({"name": "World"})
        assert result == {"result": "tool output"}

        # Verify the session's call_tool was invoked
        mock_session.call_tool.assert_awaited_once_with("greet", {"name": "World"})

        # Verify llm_name works for lookup
        assert greet_tool.llm_name == "mcp_test_srv__greet"

        # Shutdown
        await mgr.shutdown()

    @pytest.mark.asyncio
    async def test_lifecycle_lazy_then_ensure(self) -> None:
        """Test: lazy server skipped at startup, connected via ensure_server."""
        config = _make_config(
            strategy="fast",
            servers=[
                {"name": "lazy_srv", "transport": "stdio", "command": "echo", "lazy": True},
            ],
        )
        registry = ToolRegistry(drop_in_dir=None)
        mgr = MCPManager(config, registry)

        # Startup should not connect lazy servers
        with patch.object(mgr, "_connect_server") as mock_connect:
            mock_connect.side_effect = AssertionError("should not be called")
            await mgr.startup()

        assert len(mgr.get_tools()) == 0

        # Now ensure_server should connect
        with patch.object(mgr, "_connect_server") as mock_connect:
            async def side_effect(server_def):
                from hiveflow.plugins.mcp.bridge import MCPToolBridge
                bridge = MCPToolBridge(
                    server_name=server_def.name,
                    tool_name="lazy_tool",
                    description="A lazy tool",
                    input_schema={"type": "object"},
                    call_fn=AsyncMock(),
                )
                registry.register(bridge)
                mgr._tools.append(bridge)
                mgr._connected_servers[server_def.name] = AsyncMock()
                return [bridge]

            mock_connect.side_effect = side_effect
            await mgr.ensure_server("lazy_srv")

        assert len(mgr.get_tools()) == 1
        assert mgr.get_tools()[0].plugin_id == "mcp:lazy_srv/lazy_tool"

        await mgr.shutdown()


class TestDeepModeSelection:
    """T025: Unit tests for deep mode LLM-assisted tool selection."""

    def _setup_manager_with_tools(
        self,
        *,
        llm_provider: Any = None,
    ) -> tuple["MCPManager", "ToolRegistry"]:
        """Create an MCPManager pre-loaded with 4 tools for deep mode tests."""
        from hiveflow.plugins.mcp.bridge import MCPToolBridge

        config = _make_config(strategy="deep")
        registry = ToolRegistry(drop_in_dir=None)
        mgr = MCPManager(config, registry, llm_provider=llm_provider)

        tool_names = ["search", "calculator", "weather", "email"]
        for name in tool_names:
            bridge = MCPToolBridge(
                server_name="test_srv",
                tool_name=name,
                description=f"Tool for {name}",
                input_schema={"type": "object"},
                call_fn=AsyncMock(),
            )
            registry.register(bridge)
            mgr._tools.append(bridge)
            mgr._connected_servers["test_srv"] = AsyncMock()

        return mgr, registry

    @pytest.mark.asyncio
    async def test_deep_selection_keeps_only_selected_tools(self) -> None:
        """LLM selects a subset of tools; unselected are removed from _tools."""
        mock_provider = AsyncMock()
        mock_provider.generate = AsyncMock(return_value={
            "content": '["mcp:test_srv/search", "mcp:test_srv/weather"]',
        })
        mgr, registry = self._setup_manager_with_tools(llm_provider=mock_provider)

        assert len(mgr.get_tools()) == 4

        await mgr._run_deep_selection("Find weather information")

        # Only 2 tools should remain
        assert len(mgr.get_tools()) == 2
        remaining_ids = {t.plugin_id for t in mgr.get_tools()}
        assert remaining_ids == {"mcp:test_srv/search", "mcp:test_srv/weather"}

    @pytest.mark.asyncio
    async def test_deep_selection_calls_llm_with_catalog(self) -> None:
        """Verify the LLM is called with the tool catalog."""
        mock_provider = AsyncMock()
        mock_provider.generate = AsyncMock(return_value={
            "content": '["mcp:test_srv/search"]',
        })
        mgr, _ = self._setup_manager_with_tools(llm_provider=mock_provider)

        await mgr._run_deep_selection("Search for something")

        mock_provider.generate.assert_awaited_once()
        call_args = mock_provider.generate.call_args
        messages = call_args[1].get("messages") or call_args[0][0]
        prompt = messages[0]["content"]
        assert "mcp:test_srv/search" in prompt
        assert "mcp:test_srv/calculator" in prompt
        assert "Search for something" in prompt

    @pytest.mark.asyncio
    async def test_deep_fallback_on_llm_failure(self) -> None:
        """LLM failure falls back to fast mode — all tools kept."""
        mock_provider = AsyncMock()
        mock_provider.generate = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
        mgr, _ = self._setup_manager_with_tools(llm_provider=mock_provider)

        await mgr._run_deep_selection("Some task")

        # All 4 tools should be kept (fallback)
        assert len(mgr.get_tools()) == 4

    @pytest.mark.asyncio
    async def test_deep_fallback_on_invalid_json(self) -> None:
        """Invalid JSON from LLM falls back to fast mode — all tools kept."""
        mock_provider = AsyncMock()
        mock_provider.generate = AsyncMock(return_value={
            "content": "not valid json at all",
        })
        mgr, _ = self._setup_manager_with_tools(llm_provider=mock_provider)

        await mgr._run_deep_selection("Some task")

        # All 4 tools should be kept (fallback)
        assert len(mgr.get_tools()) == 4

    @pytest.mark.asyncio
    async def test_deep_no_llm_provider_keeps_all_tools(self) -> None:
        """No LLM provider → warning, all tools kept."""
        mgr, _ = self._setup_manager_with_tools(llm_provider=None)

        await mgr._run_deep_selection("Some task")

        # All 4 tools should be kept
        assert len(mgr.get_tools()) == 4

    @pytest.mark.asyncio
    async def test_deep_handles_markdown_code_fences(self) -> None:
        """LLM response wrapped in code fences is parsed correctly."""
        mock_provider = AsyncMock()
        mock_provider.generate = AsyncMock(return_value={
            "content": '```json\n["mcp:test_srv/email"]\n```',
        })
        mgr, _ = self._setup_manager_with_tools(llm_provider=mock_provider)

        await mgr._run_deep_selection("Send an email")

        assert len(mgr.get_tools()) == 1
        assert mgr.get_tools()[0].plugin_id == "mcp:test_srv/email"

    @pytest.mark.asyncio
    async def test_deep_startup_triggers_selection(self) -> None:
        """startup() with deep strategy triggers _run_deep_selection."""
        mock_provider = AsyncMock()
        mock_provider.generate = AsyncMock(return_value={
            "content": '["mcp:test_srv/search"]',
        })
        config = _make_config(
            strategy="deep",
            servers=[{"name": "test_srv", "transport": "stdio", "command": "echo"}],
        )
        registry = ToolRegistry(drop_in_dir=None)
        mgr = MCPManager(config, registry, llm_provider=mock_provider)

        with patch.object(mgr, "_connect_server") as mock_connect:
            async def side_effect(server_def):
                from hiveflow.plugins.mcp.bridge import MCPToolBridge
                bridges = []
                for name in ["search", "calculator"]:
                    bridge = MCPToolBridge(
                        server_name=server_def.name,
                        tool_name=name,
                        description=f"Tool {name}",
                        input_schema={"type": "object"},
                        call_fn=AsyncMock(),
                    )
                    bridges.append(bridge)
                    registry.register(bridge)
                mgr._tools.extend(bridges)
                mgr._connected_servers[server_def.name] = AsyncMock()
                return bridges

            mock_connect.side_effect = side_effect
            await mgr.startup(task="Search for something")

        # Deep mode should have pruned to only 'search'
        assert len(mgr.get_tools()) == 1
        assert mgr.get_tools()[0].plugin_id == "mcp:test_srv/search"

        await mgr.shutdown()

    @pytest.mark.asyncio
    async def test_deep_selects_all_keeps_all(self) -> None:
        """If LLM selects all tools, none are removed."""
        mock_provider = AsyncMock()
        all_ids = [
            "mcp:test_srv/search",
            "mcp:test_srv/calculator",
            "mcp:test_srv/weather",
            "mcp:test_srv/email",
        ]
        mock_provider.generate = AsyncMock(return_value={
            "content": str(all_ids).replace("'", '"'),
        })
        mgr, _ = self._setup_manager_with_tools(llm_provider=mock_provider)

        await mgr._run_deep_selection("Use everything")

        assert len(mgr.get_tools()) == 4
