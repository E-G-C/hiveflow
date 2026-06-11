"""Unit tests for MCP configuration models."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from hiveflow.plugins.mcp.config import (
    MCPAuthConfig,
    MCPConfig,
    MCPServerDefinition,
    MCP_CONFIG_ENV_VAR,
)


# --- MCPAuthConfig ---


class TestMCPAuthConfig:
    def test_bearer_auth(self):
        auth = MCPAuthConfig(type="bearer", env="MY_TOKEN")
        assert auth.type == "bearer"
        assert auth.env == "MY_TOKEN"

    def test_bearer_default_type(self):
        auth = MCPAuthConfig(env="MY_TOKEN")
        assert auth.type == "bearer"

    def test_invalid_type_rejected(self):
        with pytest.raises(ValidationError):
            MCPAuthConfig(type="oauth", env="TOKEN")


# --- MCPServerDefinition ---


class TestMCPServerDefinition:
    def test_valid_stdio_server(self):
        server = MCPServerDefinition(
            name="local", transport="stdio", command="my-cmd", args=["--flag"]
        )
        assert server.name == "local"
        assert server.transport == "stdio"
        assert server.command == "my-cmd"
        assert server.args == ["--flag"]
        assert server.url is None
        assert server.auth is None
        assert server.lazy is False

    def test_valid_http_server(self):
        server = MCPServerDefinition(
            name="remote", transport="http", url="http://localhost:8080"
        )
        assert server.name == "remote"
        assert server.transport == "http"
        assert server.url == "http://localhost:8080"
        assert server.command is None

    def test_http_with_auth(self):
        server = MCPServerDefinition(
            name="authed",
            transport="http",
            url="http://x:8080",
            auth=MCPAuthConfig(env="TOKEN"),
        )
        assert server.auth is not None
        assert server.auth.env == "TOKEN"

    def test_lazy_flag(self):
        server = MCPServerDefinition(
            name="lazy", transport="stdio", command="cmd", lazy=True
        )
        assert server.lazy is True

    def test_stdio_with_env(self):
        server = MCPServerDefinition(
            name="env", transport="stdio", command="cmd", env={"FOO": "bar"}
        )
        assert server.env == {"FOO": "bar"}

    # --- Validation errors ---

    def test_http_requires_url(self):
        with pytest.raises(ValidationError, match="'url' is required for http transport"):
            MCPServerDefinition(name="bad", transport="http")

    def test_stdio_requires_command(self):
        with pytest.raises(ValidationError, match="'command' is required for stdio transport"):
            MCPServerDefinition(name="bad", transport="stdio")

    def test_http_rejects_command(self):
        with pytest.raises(ValidationError, match="'command' is not valid for http transport"):
            MCPServerDefinition(
                name="bad", transport="http", url="http://x", command="should-not-be-here"
            )

    def test_stdio_rejects_url(self):
        with pytest.raises(ValidationError, match="'url' is not valid for stdio transport"):
            MCPServerDefinition(
                name="bad", transport="stdio", command="cmd", url="http://should-not-be-here"
            )

    def test_stdio_rejects_auth(self):
        with pytest.raises(ValidationError, match="'auth' is not valid for stdio transport"):
            MCPServerDefinition(
                name="bad",
                transport="stdio",
                command="cmd",
                auth=MCPAuthConfig(env="TOKEN"),
            )

    def test_invalid_transport(self):
        with pytest.raises(ValidationError):
            MCPServerDefinition(name="bad", transport="grpc", command="cmd")


# --- MCPConfig ---


class TestMCPConfig:
    def test_default_config(self):
        cfg = MCPConfig()
        assert cfg.strategy == "disabled"
        assert cfg.servers == []

    def test_valid_fast_config(self):
        cfg = MCPConfig(
            strategy="fast",
            servers=[
                MCPServerDefinition(name="a", transport="stdio", command="x"),
                MCPServerDefinition(name="b", transport="http", url="http://y"),
            ],
        )
        assert cfg.strategy == "fast"
        assert len(cfg.servers) == 2

    def test_deep_strategy(self):
        cfg = MCPConfig(
            strategy="deep",
            servers=[MCPServerDefinition(name="a", transport="stdio", command="x")],
        )
        assert cfg.strategy == "deep"

    def test_invalid_strategy(self):
        with pytest.raises(ValidationError):
            MCPConfig(strategy="turbo")

    def test_duplicate_server_names_rejected(self):
        with pytest.raises(ValidationError, match="Duplicate MCP server name: 'dupe'"):
            MCPConfig(
                strategy="fast",
                servers=[
                    MCPServerDefinition(name="dupe", transport="stdio", command="x"),
                    MCPServerDefinition(name="dupe", transport="stdio", command="y"),
                ],
            )

    def test_get_server(self):
        cfg = MCPConfig(
            strategy="fast",
            servers=[
                MCPServerDefinition(name="a", transport="stdio", command="x"),
                MCPServerDefinition(name="b", transport="http", url="http://y"),
            ],
        )
        assert cfg.get_server("a") is not None
        assert cfg.get_server("a").name == "a"
        assert cfg.get_server("missing") is None

    def test_get_eager_servers(self):
        cfg = MCPConfig(
            strategy="fast",
            servers=[
                MCPServerDefinition(name="eager", transport="stdio", command="x"),
                MCPServerDefinition(name="lazy", transport="stdio", command="y", lazy=True),
            ],
        )
        eager = cfg.get_eager_servers()
        assert len(eager) == 1
        assert eager[0].name == "eager"

    def test_get_lazy_servers(self):
        cfg = MCPConfig(
            strategy="fast",
            servers=[
                MCPServerDefinition(name="eager", transport="stdio", command="x"),
                MCPServerDefinition(name="lazy", transport="stdio", command="y", lazy=True),
            ],
        )
        lazy = cfg.get_lazy_servers()
        assert len(lazy) == 1
        assert lazy[0].name == "lazy"


# --- MCPConfig.from_file ---


class TestMCPConfigFromFile:
    def test_no_file_returns_disabled(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv(MCP_CONFIG_ENV_VAR, raising=False)
        cfg = MCPConfig.from_file()
        assert cfg.strategy == "disabled"
        assert cfg.servers == []

    def test_load_from_explicit_path(self, tmp_path):
        config_data = {
            "strategy": "fast",
            "servers": [
                {"name": "s1", "transport": "stdio", "command": "cmd1"}
            ],
        }
        path = tmp_path / "mcp.json"
        path.write_text(json.dumps(config_data))

        cfg = MCPConfig.from_file(str(path))
        assert cfg.strategy == "fast"
        assert len(cfg.servers) == 1
        assert cfg.servers[0].name == "s1"

    def test_load_from_env_var(self, tmp_path, monkeypatch):
        config_data = {
            "strategy": "deep",
            "servers": [
                {"name": "s2", "transport": "http", "url": "http://x"}
            ],
        }
        path = tmp_path / "custom-mcp.json"
        path.write_text(json.dumps(config_data))
        monkeypatch.setenv(MCP_CONFIG_ENV_VAR, str(path))

        cfg = MCPConfig.from_file()
        assert cfg.strategy == "deep"
        assert cfg.servers[0].name == "s2"

    def test_load_from_default_path(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv(MCP_CONFIG_ENV_VAR, raising=False)
        default_dir = tmp_path / ".hiveflow"
        default_dir.mkdir()
        config_data = {"strategy": "fast", "servers": []}
        (default_dir / "mcp.json").write_text(json.dumps(config_data))

        cfg = MCPConfig.from_file()
        assert cfg.strategy == "fast"

    def test_explicit_path_not_found_raises(self):
        with pytest.raises(ValueError, match="not found"):
            MCPConfig.from_file("/nonexistent/mcp.json")

    def test_env_var_path_not_found_raises(self, monkeypatch):
        monkeypatch.setenv(MCP_CONFIG_ENV_VAR, "/nonexistent/mcp.json")
        with pytest.raises(ValueError, match="not found"):
            MCPConfig.from_file()

    def test_malformed_json_raises(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("not valid json {{{{")

        with pytest.raises(ValueError, match="not valid JSON"):
            MCPConfig.from_file(str(path))

    def test_json_array_raises(self, tmp_path):
        path = tmp_path / "array.json"
        path.write_text("[]")

        with pytest.raises(ValueError, match="must contain a JSON object"):
            MCPConfig.from_file(str(path))

    def test_explicit_path_takes_precedence_over_env(self, tmp_path, monkeypatch):
        """Explicit path wins over env var."""
        env_data = {"strategy": "deep", "servers": []}
        env_path = tmp_path / "env.json"
        env_path.write_text(json.dumps(env_data))
        monkeypatch.setenv(MCP_CONFIG_ENV_VAR, str(env_path))

        explicit_data = {"strategy": "fast", "servers": []}
        explicit_path = tmp_path / "explicit.json"
        explicit_path.write_text(json.dumps(explicit_data))

        cfg = MCPConfig.from_file(str(explicit_path))
        assert cfg.strategy == "fast"

    def test_full_config_round_trip(self, tmp_path):
        """Full config with all options parses correctly."""
        config_data = {
            "strategy": "fast",
            "servers": [
                {
                    "name": "local_tools",
                    "transport": "stdio",
                    "command": "my-mcp-server",
                    "args": ["--verbose"],
                    "env": {"DEBUG": "1"},
                },
                {
                    "name": "jira",
                    "transport": "http",
                    "url": "http://mcp-jira:8080",
                    "auth": {"type": "bearer", "env": "JIRA_TOKEN"},
                    "lazy": True,
                },
            ],
        }
        path = tmp_path / "mcp.json"
        path.write_text(json.dumps(config_data))

        cfg = MCPConfig.from_file(str(path))
        assert cfg.strategy == "fast"
        assert len(cfg.servers) == 2

        local = cfg.get_server("local_tools")
        assert local.transport == "stdio"
        assert local.command == "my-mcp-server"
        assert local.args == ["--verbose"]
        assert local.env == {"DEBUG": "1"}
        assert local.lazy is False

        jira = cfg.get_server("jira")
        assert jira.transport == "http"
        assert jira.url == "http://mcp-jira:8080"
        assert jira.auth.type == "bearer"
        assert jira.auth.env == "JIRA_TOKEN"
        assert jira.lazy is True
