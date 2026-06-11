"""Tests for Source Mode — enum, routing, and pipeline activation."""

import pytest

from hiveflow.core.source_mode import (
    SourceMode,
    SourceModeRouter,
    SourceOptions,
    WebSourceOptions,
    LocalSourceOptions,
    CloudSourceOptions,
)


# ── SourceMode enum ──────────────────────────────────────────────────

class TestSourceModeEnum:
    def test_all_modes_exist(self):
        assert SourceMode.WEB == "web"
        assert SourceMode.LOCAL == "local"
        assert SourceMode.HYBRID == "hybrid"
        assert SourceMode.CLOUD == "cloud"
        assert SourceMode.MCP == "mcp"
        assert SourceMode.CUSTOM == "custom"

    def test_from_string(self):
        assert SourceMode("web") == SourceMode.WEB
        assert SourceMode("hybrid") == SourceMode.HYBRID

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError):
            SourceMode("invalid_mode")


# ── SourceOptions models ─────────────────────────────────────────────

class TestSourceOptions:
    def test_defaults(self):
        opts = SourceOptions()
        assert opts.web is None
        assert opts.local is None
        assert opts.cloud is None
        assert opts.custom_plugins == []

    def test_web_options(self):
        opts = WebSourceOptions(
            retrievers=["tavily", "duckduckgo"],
            max_results_per_query=5,
        )
        assert opts.retrievers == ["tavily", "duckduckgo"]
        assert opts.max_results_per_query == 5

    def test_local_options(self):
        opts = LocalSourceOptions(
            doc_path="./docs",
            formats=["pdf", "md"],
        )
        assert opts.doc_path == "./docs"
        assert opts.formats == ["pdf", "md"]

    def test_cloud_options(self):
        opts = CloudSourceOptions(
            provider="azure_blob",
            container="reports",
            path_prefix="2024/",
        )
        assert opts.provider == "azure_blob"
        assert opts.container == "reports"

    def test_from_dict(self):
        opts = SourceOptions(**{
            "web": {"retrievers": ["tavily"], "max_results_per_query": 10},
            "local": {"doc_path": "./docs"},
        })
        assert opts.web is not None
        assert opts.web.retrievers == ["tavily"]
        assert opts.local is not None
        assert opts.local.doc_path == "./docs"


# ── SourceModeRouter ─────────────────────────────────────────────────

class TestSourceModeRouter:

    def test_no_mode_passes_all_tools(self):
        router = SourceModeRouter(source_mode=None)
        assert not router.is_active
        tools = ["web_search", "document_retriever", "custom_tool"]
        assert router.filter_tools(tools) == tools

    def test_web_mode_filters_to_web_tools(self):
        router = SourceModeRouter(source_mode="web")
        assert router.is_active
        tools = ["web_search", "document_retriever", "scraper_bs4"]
        result = router.filter_tools(tools)
        assert "web_search" in result
        assert "scraper_bs4" in result
        assert "document_retriever" not in result

    def test_local_mode_filters_to_local_tools(self):
        router = SourceModeRouter(source_mode="local")
        tools = ["web_search", "document_retriever", "vector_store_search"]
        result = router.filter_tools(tools)
        assert "document_retriever" in result
        assert "vector_store_search" in result
        assert "web_search" not in result

    def test_hybrid_mode_allows_both(self):
        router = SourceModeRouter(source_mode="hybrid")
        tools = ["web_search", "document_retriever", "scraper_bs4", "vector_store_search"]
        result = router.filter_tools(tools)
        assert len(result) == 4  # All pass through in hybrid

    def test_custom_mode_uses_explicit_list(self):
        router = SourceModeRouter(
            source_mode="custom",
            source_options={"custom_plugins": ["my_tool", "special_retriever"]},
        )
        tools = ["my_tool", "web_search", "special_retriever"]
        result = router.filter_tools(tools)
        assert result == ["my_tool", "special_retriever"]

    def test_framework_tools_always_pass(self):
        """Internal tools like delegate_task should never be filtered."""
        router = SourceModeRouter(source_mode="web")
        tools = ["delegate_task", "send_message", "read_messages", "spawn_agent",
                 "plan_and_execute", "skill_activation", "web_search"]
        result = router.filter_tools(tools)
        assert "delegate_task" in result
        assert "send_message" in result
        assert "read_messages" in result
        assert "spawn_agent" in result
        assert "plan_and_execute" in result
        assert "skill_activation" in result
        assert "web_search" in result

    def test_cloud_mode(self):
        router = SourceModeRouter(source_mode="cloud")
        tools = ["cloud_source_s3", "document_retriever", "web_search"]
        result = router.filter_tools(tools)
        assert "cloud_source_s3" in result
        assert "document_retriever" in result
        assert "web_search" not in result

    def test_mcp_mode(self):
        router = SourceModeRouter(source_mode="mcp")
        tools = ["mcp_tool_fetch", "web_search", "document_retriever"]
        result = router.filter_tools(tools)
        assert "mcp_tool_fetch" in result
        assert "web_search" not in result

    def test_source_options_dict(self):
        """Router accepts source_options as a dict."""
        router = SourceModeRouter(
            source_mode="web",
            source_options={"web": {"retrievers": ["tavily"]}},
        )
        assert router.options.web is not None
        assert router.options.web.retrievers == ["tavily"]

    def test_source_options_model(self):
        """Router accepts source_options as a SourceOptions instance."""
        opts = SourceOptions(web=WebSourceOptions(retrievers=["duckduckgo"]))
        router = SourceModeRouter(source_mode="web", source_options=opts)
        assert router.options.web.retrievers == ["duckduckgo"]

    def test_get_allowed_categories_none_mode(self):
        router = SourceModeRouter()
        assert router.get_allowed_categories() == set()

    def test_mode_property(self):
        router = SourceModeRouter(source_mode="local")
        assert router.mode == SourceMode.LOCAL


# ── TeamConfiguration schema integration ─────────────────────────────

class TestTeamConfigurationSourceMode:

    def _minimal_config(self, **overrides):
        base = {
            "team_name": "test_team",
            "description": "A test team",
            "agents": [{
                "id": "agent1",
                "role": "Test agent",
                "system_prompt": "You are a test agent.",
                "behavior_type": "llm_only",
            }],
            "workflow": {
                "steps": [{"agent": "agent1", "type": "sequential"}],
            },
        }
        base.update(overrides)
        return base

    def test_source_mode_none_default(self):
        from hiveflow.core.schema import TeamConfiguration
        config = TeamConfiguration(**self._minimal_config())
        assert config.source_mode is None
        assert config.source_options is None

    def test_source_mode_web(self):
        from hiveflow.core.schema import TeamConfiguration
        config = TeamConfiguration(**self._minimal_config(source_mode="web"))
        assert config.source_mode == "web"

    def test_source_mode_hybrid_with_options(self):
        from hiveflow.core.schema import TeamConfiguration
        config = TeamConfiguration(**self._minimal_config(
            source_mode="hybrid",
            source_options={
                "web": {"retrievers": ["tavily"]},
                "local": {"doc_path": "./docs"},
            },
        ))
        assert config.source_mode == "hybrid"
        assert config.source_options["web"]["retrievers"] == ["tavily"]

    def test_invalid_source_mode_rejected(self):
        from hiveflow.core.schema import TeamConfiguration
        with pytest.raises(Exception):
            TeamConfiguration(**self._minimal_config(source_mode="ftp"))

    def test_all_valid_modes_accepted(self):
        from hiveflow.core.schema import TeamConfiguration
        for mode in ("web", "local", "hybrid", "cloud", "mcp", "custom"):
            config = TeamConfiguration(**self._minimal_config(source_mode=mode))
            assert config.source_mode == mode

    def test_existing_configs_unaffected(self):
        """Configs without source_mode continue to work."""
        from hiveflow.core.schema import TeamConfiguration
        config = TeamConfiguration(**self._minimal_config(
            publish={"formats": ["markdown"], "output_dir": "./out"},
            tone="formal",
        ))
        assert config.source_mode is None
        assert config.publish is not None
        assert config.tone == "formal"
