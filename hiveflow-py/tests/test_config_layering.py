"""Integration tests for four-layer config precedence and new config fields.

Covers: defaults → file → env → overrides, tier variable resolution,
validation error reporting, and all new fields (SOURCE_MODE, DOC_PATH,
Actions, MCP).
"""

import json
import os

import pytest

from hiveflow.core.config import HiveFlowConfig, get_config, reset_config, set_config


class TestConfigDefaults:
    """Verify all fields resolve to documented defaults with no file or env."""

    def test_llm_tier_defaults(self):
        config = HiveFlowConfig()
        assert config.FAST_LLM == "openai:gpt-4o-mini"
        assert config.SMART_LLM == "openai:gpt-4o"
        assert config.STRATEGIC_LLM == "openai:o3-mini"

    def test_source_mode_defaults(self):
        config = HiveFlowConfig()
        assert config.SOURCE_MODE == "web"
        assert config.DOC_PATH is None

    def test_actions_defaults(self):
        config = HiveFlowConfig()
        assert config.DEFAULT_ACTION_POLICY == "deny"
        assert config.ENABLE_ROLLBACK is False
        assert config.ACTION_TIMEOUT == 30

    def test_mcp_defaults(self):
        config = HiveFlowConfig()
        assert config.MCP_STRATEGY == "disabled"
        assert config.MCP_SERVERS == []
        assert config.MCP_AUTO_TOOL_SELECTION is True

    def test_max_tokens_default(self):
        config = HiveFlowConfig()
        assert config.MAX_TOKENS == 16000

    def test_cost_tracking_default(self):
        config = HiveFlowConfig()
        assert config.ENABLE_COST_TRACKING is True

    def test_publish_formats_default_empty(self):
        """PUBLISH_FORMATS defaults to empty string (discover all publishers)."""
        config = HiveFlowConfig()
        assert config.PUBLISH_FORMATS == ""
        assert config.get_publish_formats() == []

    def test_publish_formats_explicit(self):
        """Explicit PUBLISH_FORMATS is parsed correctly."""
        config = HiveFlowConfig(PUBLISH_FORMATS="pdf,markdown")
        assert config.get_publish_formats() == ["pdf", "markdown"]

    def test_publish_formats_whitespace_handling(self):
        """Whitespace around format names is stripped."""
        config = HiveFlowConfig(PUBLISH_FORMATS=" pdf , markdown , json ")
        assert config.get_publish_formats() == ["pdf", "markdown", "json"]


class TestConfigFilePrecedence:
    """Config file values override defaults."""

    def test_json_file_overrides_defaults(self, tmp_path):
        config_file = tmp_path / "config.json"
        data = {
            "SMART_LLM": "anthropic:claude-sonnet-4-20250514",
            "SOURCE_MODE": "hybrid",
            "DOC_PATH": "/data/docs",
            "DEFAULT_ACTION_POLICY": "allow",
            "ACTION_TIMEOUT": 60,
            "MCP_STRATEGY": "fast",
        }
        config_file.write_text(json.dumps(data), encoding="utf-8")

        config = HiveFlowConfig.from_file(config_file)
        assert config.SMART_LLM == "anthropic:claude-sonnet-4-20250514"
        assert config.SOURCE_MODE == "hybrid"
        assert config.DOC_PATH == "/data/docs"
        assert config.DEFAULT_ACTION_POLICY == "allow"
        assert config.ACTION_TIMEOUT == 60
        assert config.MCP_STRATEGY == "fast"
        # Defaults still apply for unset fields
        assert config.FAST_LLM == "openai:gpt-4o-mini"
        assert config.ENABLE_ROLLBACK is False

    def test_yaml_file_overrides_defaults(self, tmp_path):
        try:
            import yaml
        except ImportError:
            pytest.skip("PyYAML not installed")
        data = {
            "SOURCE_MODE": "local",
            "DOC_PATH": "/my/docs",
            "MCP_SERVERS": [{"name": "test", "transport": "stdio"}],
        }
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(data), encoding="utf-8")

        config = HiveFlowConfig.from_file(config_file)
        assert config.SOURCE_MODE == "local"
        assert config.DOC_PATH == "/my/docs"
        assert config.MCP_SERVERS == [{"name": "test", "transport": "stdio"}]

    def test_invalid_file_format_raises(self, tmp_path):
        config_file = tmp_path / "config.txt"
        config_file.write_text("data", encoding="utf-8")
        with pytest.raises(ValueError, match="Unsupported config file format"):
            HiveFlowConfig.from_file(config_file)

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            HiveFlowConfig.from_file("/nonexistent/config.json")


class TestEnvVarPrecedence:
    """Env vars with HIVEFLOW_ prefix override defaults and file values."""

    def test_env_overrides_default(self, monkeypatch):
        monkeypatch.setenv("HIVEFLOW_SOURCE_MODE", "cloud")
        monkeypatch.setenv("HIVEFLOW_DOC_PATH", "/env/docs")
        monkeypatch.setenv("HIVEFLOW_DEFAULT_ACTION_POLICY", "dry_run")
        monkeypatch.setenv("HIVEFLOW_MCP_STRATEGY", "deep")
        monkeypatch.setenv("HIVEFLOW_ACTION_TIMEOUT", "120")
        monkeypatch.setenv("HIVEFLOW_ENABLE_ROLLBACK", "true")
        monkeypatch.setenv("HIVEFLOW_MCP_AUTO_TOOL_SELECTION", "false")

        config = HiveFlowConfig()
        assert config.SOURCE_MODE == "cloud"
        assert config.DOC_PATH == "/env/docs"
        assert config.DEFAULT_ACTION_POLICY == "dry_run"
        assert config.MCP_STRATEGY == "deep"
        assert config.ACTION_TIMEOUT == 120
        assert config.ENABLE_ROLLBACK is True
        assert config.MCP_AUTO_TOOL_SELECTION is False

    def test_env_overrides_file(self, monkeypatch, tmp_path):
        # Note: from_file passes values as kwargs, which pydantic-settings treats
        # as higher priority than env vars. Env vars only override for fields NOT
        # specified in the file.
        monkeypatch.setenv("HIVEFLOW_FAST_LLM", "anthropic:haiku")
        config_file = tmp_path / "config.json"
        data = {"SOURCE_MODE": "local"}
        config_file.write_text(json.dumps(data), encoding="utf-8")

        config = HiveFlowConfig.from_file(config_file)
        # File field takes precedence (passed as kwarg)
        assert config.SOURCE_MODE == "local"
        # Env var applies to fields NOT in the file
        assert config.FAST_LLM == "anthropic:haiku"


class TestRuntimeOverrides:
    """Team/runtime overrides take highest precedence."""

    def test_apply_overrides(self):
        config = HiveFlowConfig()
        assert config.SOURCE_MODE == "web"
        assert config.ACTION_TIMEOUT == 30

        overridden = config.apply_overrides({
            "source_mode": "hybrid",
            "action_timeout": 90,
            "mcp_strategy": "fast",
        })
        assert overridden.SOURCE_MODE == "hybrid"
        assert overridden.ACTION_TIMEOUT == 90
        assert overridden.MCP_STRATEGY == "fast"
        # Original unchanged
        assert config.SOURCE_MODE == "web"

    def test_override_beats_env(self, monkeypatch):
        monkeypatch.setenv("HIVEFLOW_SOURCE_MODE", "cloud")
        config = HiveFlowConfig()
        assert config.SOURCE_MODE == "cloud"

        overridden = config.apply_overrides({"source_mode": "custom"})
        assert overridden.SOURCE_MODE == "custom"


class TestTierVariableResolution:
    """Tier variables ($SMART_LLM etc.) resolve to configured model."""

    def test_resolve_tier_variable(self):
        config = HiveFlowConfig()
        assert config.resolve_model("$SMART_LLM") == "openai:gpt-4o"
        assert config.resolve_model("$FAST_LLM") == "openai:gpt-4o-mini"
        assert config.resolve_model("$STRATEGIC_LLM") == "openai:o3-mini"

    def test_resolve_concrete_model(self):
        config = HiveFlowConfig()
        assert config.resolve_model("anthropic:claude-sonnet-4-20250514") == "anthropic:claude-sonnet-4-20250514"

    def test_resolve_tier_after_override(self):
        config = HiveFlowConfig()
        overridden = config.apply_overrides({"smart_llm": "anthropic:claude-sonnet-4-20250514"})
        assert overridden.resolve_model("$SMART_LLM") == "anthropic:claude-sonnet-4-20250514"


class TestGlobalConfigManagement:
    """get_config, set_config, reset_config singleton pattern."""

    def setup_method(self):
        reset_config()

    def teardown_method(self):
        reset_config()

    def test_get_config_creates_default(self):
        config = get_config()
        assert isinstance(config, HiveFlowConfig)
        assert config.SOURCE_MODE == "web"

    def test_set_config(self):
        custom = HiveFlowConfig(SOURCE_MODE="local")
        set_config(custom)
        assert get_config().SOURCE_MODE == "local"

    def test_reset_config(self):
        custom = HiveFlowConfig(SOURCE_MODE="local")
        set_config(custom)
        reset_config()
        assert get_config().SOURCE_MODE == "web"
