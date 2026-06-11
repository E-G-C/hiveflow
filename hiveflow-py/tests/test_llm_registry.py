"""Tests for LLM provider registry discovery and resolution (T008).

Covers:
- Singleton behaviour of ``get_llm_registry()``
- Entry-point-based discovery (``openai``, ``anthropic``)
- ``resolve_model()`` happy path and error paths
- Graceful skip when entry point import fails (FR-014)
"""

import pytest

from hiveflow.plugins.llm import (
    LLMProviderRegistry,
    get_llm_registry,
    reset_llm_registry,
)
from hiveflow.plugins.llm.openai_provider import OpenAIProvider
from hiveflow.plugins.llm.perplexity_provider import PerplexityProvider

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_registry():
    """Ensure a fresh registry for every test."""
    reset_llm_registry()
    yield
    reset_llm_registry()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGetLLMRegistry:
    """get_llm_registry() singleton semantics."""

    def test_returns_singleton(self):
        reg1 = get_llm_registry()
        reg2 = get_llm_registry()
        assert reg1 is reg2

    def test_returns_registry_instance(self):
        reg = get_llm_registry()
        assert isinstance(reg, LLMProviderRegistry)


class TestDiscovery:
    """Entry-point-based auto-discovery."""

    def test_openai_discovered(self):
        reg = get_llm_registry()
        assert "openai" in reg.list_ids()

    def test_anthropic_discovered(self):
        reg = get_llm_registry()
        assert "anthropic" in reg.list_ids()

    def test_perplexity_discovered(self):
        reg = get_llm_registry()
        assert "perplexity" in reg.list_ids()

    def test_list_ids_sorted(self):
        reg = get_llm_registry()
        ids = reg.list_ids()
        assert ids == sorted(ids)

    def test_azure_gracefully_skipped(self):
        """Azure entry point should fail gracefully (module not yet created or import error)."""
        reg = get_llm_registry()
        # The azure entry point is registered in pyproject.toml but the module
        # may or may not exist yet.  Either way, no crash occurs (FR-014).
        assert isinstance(reg, LLMProviderRegistry)


class TestResolveModel:
    """resolve_model() happy path and errors."""

    def test_resolve_openai(self):
        reg = get_llm_registry()
        provider, model = reg.resolve_model("openai:gpt-4o")
        assert isinstance(provider, OpenAIProvider)
        assert model == "gpt-4o"

    def test_resolve_model_preserves_colons(self):
        """Model names with colons (e.g. ollama:custom:tag) keep the full tail."""
        reg = get_llm_registry()
        provider, model = reg.resolve_model("openai:custom:v2")
        assert model == "custom:v2"

    def test_resolve_perplexity(self):
        reg = get_llm_registry()
        provider, model = reg.resolve_model("perplexity:sonar-pro")
        assert isinstance(provider, PerplexityProvider)
        assert model == "sonar-pro"

    def test_invalid_format_raises_value_error(self):
        reg = get_llm_registry()
        with pytest.raises(ValueError, match="provider:model"):
            reg.resolve_model("gpt-4o")

    def test_unknown_provider_raises_key_error(self):
        reg = get_llm_registry()
        with pytest.raises(KeyError, match="not found"):
            reg.resolve_model("unknown:model")

    def test_known_extras_suggest_install(self):
        reg = get_llm_registry()
        with pytest.raises(KeyError, match="uv add hiveflow\\[llm-google\\]"):
            reg.resolve_model("google:gemini-2.0-flash")

    def test_unknown_extras_no_install_suggestion(self):
        reg = get_llm_registry()
        with pytest.raises(KeyError) as exc_info:
            reg.resolve_model("random:model")
        assert "Install with" not in str(exc_info.value)


class TestProviderProperties:
    """Basic provider properties after discovery."""

    def test_openai_provider_id(self):
        reg = get_llm_registry()
        provider = reg.get("openai")
        assert provider is not None
        assert provider.provider_id == "openai"
        assert provider.plugin_id == "openai"

    def test_anthropic_provider_id(self):
        reg = get_llm_registry()
        provider = reg.get("anthropic")
        assert provider is not None
        assert provider.provider_id == "anthropic"

    def test_perplexity_provider_id(self):
        reg = get_llm_registry()
        provider = reg.get("perplexity")
        assert provider is not None
        assert provider.provider_id == "perplexity"

    def test_capability_flags(self):
        reg = get_llm_registry()
        for pid in ("openai", "anthropic"):
            provider = reg.get(pid)
            assert provider is not None
            assert provider.supports_streaming is True
            assert provider.supports_function_calling is True
            assert provider.supports_json_mode is True
            assert provider.supports_vision is True

    def test_perplexity_capability_flags(self):
        reg = get_llm_registry()
        provider = reg.get("perplexity")
        assert provider is not None
        assert provider.supports_streaming is True
        assert provider.supports_function_calling is False
        assert provider.supports_json_mode is True
        assert provider.supports_vision is False
