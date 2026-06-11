"""Integration tests for multi-provider model assignment and fallback chains (T013/T014).

T013: Multi-provider model assignment
- Resolving different provider:model strings returns different provider instances
- FallbackChain with two providers (first fails, second succeeds)
- Per-agent model resolution scenario

T014: Tier variable resolution
- HiveFlowConfig.resolve_model("$SMART_LLM") defaults
- Tier → registry.resolve_model() end-to-end chain
- Custom tier override via env var
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from hiveflow.core.config import HiveFlowConfig, get_config, reset_config
from hiveflow.core.fallback import FallbackChain, LLMFallbackExhaustedError, RetryProvider, build_fallback_chain
from hiveflow.plugins.llm.errors import (
    LLMAuthError,
    LLMConnectionError,
    LLMModelNotFoundError,
    LLMRateLimitError,
)
from hiveflow.plugins.llm import (
    LLMConfig,
    LLMMessage,
    LLMResponse,
    TokenUsage,
    get_llm_registry,
    reset_llm_registry,
)
from hiveflow.plugins.llm.openai_provider import OpenAIProvider
from hiveflow.plugins.llm.anthropic_provider import AnthropicProvider


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_globals():
    reset_llm_registry()
    reset_config()
    yield
    reset_llm_registry()
    reset_config()


def _make_mock_response(content: str = "Hello", model: str = "test") -> LLMResponse:
    return LLMResponse(
        content=content,
        model=model,
        usage=TokenUsage(prompt_tokens=5, completion_tokens=3, total_tokens=8),
    )


# ---------------------------------------------------------------------------
# T013: Multi-provider model assignment
# ---------------------------------------------------------------------------

class TestMultiProviderResolution:
    """Resolving different providers returns distinct instances."""

    def test_different_providers_different_instances(self):
        reg = get_llm_registry()
        openai_provider, openai_model = reg.resolve_model("openai:gpt-4o")
        anthropic_provider, anthropic_model = reg.resolve_model("anthropic:claude-sonnet-4-20250514")

        assert isinstance(openai_provider, OpenAIProvider)
        assert isinstance(anthropic_provider, AnthropicProvider)
        assert openai_provider is not anthropic_provider
        assert openai_model == "gpt-4o"
        assert anthropic_model == "claude-sonnet-4-20250514"

    def test_same_provider_same_instance(self):
        reg = get_llm_registry()
        p1, m1 = reg.resolve_model("openai:gpt-4o")
        p2, m2 = reg.resolve_model("openai:gpt-4o-mini")
        assert p1 is p2  # same provider instance, different models
        assert m1 == "gpt-4o"
        assert m2 == "gpt-4o-mini"

    def test_all_three_providers_distinct(self):
        reg = get_llm_registry()
        providers = set()
        for ref in ("openai:gpt-4o", "anthropic:claude", "azure:deploy-1"):
            p, _ = reg.resolve_model(ref)
            providers.add(p.provider_id)
        assert providers == {"openai", "anthropic", "azure"}


class TestPerAgentResolution:
    """Per-agent model resolution scenario."""

    def test_multiple_agents_each_get_own_provider(self):
        reg = get_llm_registry()

        # Simulate agent configs
        agent_configs = {
            "researcher": "openai:gpt-4o",
            "reviewer": "anthropic:claude-sonnet-4-20250514",
            "summarizer": "openai:gpt-4o-mini",
        }

        resolved = {}
        for agent_name, model_ref in agent_configs.items():
            provider, model = reg.resolve_model(model_ref)
            resolved[agent_name] = (provider, model)

        assert resolved["researcher"][0].provider_id == "openai"
        assert resolved["researcher"][1] == "gpt-4o"
        assert resolved["reviewer"][0].provider_id == "anthropic"
        assert resolved["summarizer"][0].provider_id == "openai"
        assert resolved["summarizer"][1] == "gpt-4o-mini"
        # researcher and summarizer share the same OpenAI provider instance
        assert resolved["researcher"][0] is resolved["summarizer"][0]


class TestFallbackChain:
    """FallbackChain with multiple providers."""

    @pytest.mark.asyncio
    async def test_first_provider_succeeds(self):
        p1 = MagicMock(spec=OpenAIProvider)
        p1.plugin_id = "openai"
        p1.chat = AsyncMock(return_value=_make_mock_response("from-p1", "gpt-4o"))

        chain = FallbackChain([(p1, "gpt-4o")])
        messages = [LLMMessage(role="user", content="Hello")]
        config = LLMConfig(model="gpt-4o")
        response = await chain.chat(messages, config)
        assert response.content == "from-p1"

    @pytest.mark.asyncio
    async def test_fallback_on_failure(self):
        p1 = MagicMock(spec=OpenAIProvider)
        p1.plugin_id = "azure"
        p1.chat = AsyncMock(side_effect=LLMConnectionError("Azure down", provider_id="azure"))

        p2 = MagicMock(spec=OpenAIProvider)
        p2.plugin_id = "openai"
        p2.chat = AsyncMock(return_value=_make_mock_response("from-openai", "gpt-4o"))

        chain = FallbackChain([(p1, "deploy-1"), (p2, "gpt-4o")])
        messages = [LLMMessage(role="user", content="Hello")]
        config = LLMConfig(model="gpt-4o")
        response = await chain.chat(messages, config)
        assert response.content == "from-openai"

    @pytest.mark.asyncio
    async def test_all_providers_fail(self):
        p1 = MagicMock(spec=OpenAIProvider)
        p1.plugin_id = "p1"
        p1.chat = AsyncMock(side_effect=LLMConnectionError("fail-1", provider_id="p1"))

        p2 = MagicMock(spec=OpenAIProvider)
        p2.plugin_id = "p2"
        p2.chat = AsyncMock(side_effect=LLMConnectionError("fail-2", provider_id="p2"))

        chain = FallbackChain([(p1, "m1"), (p2, "m2")])
        messages = [LLMMessage(role="user", content="Hello")]
        config = LLMConfig()

        with pytest.raises(LLMFallbackExhaustedError):
            await chain.chat(messages, config)

    @pytest.mark.asyncio
    async def test_build_fallback_chain_with_retries(self):
        p1 = MagicMock(spec=OpenAIProvider)
        p1.plugin_id = "azure"
        p1.chat = AsyncMock(side_effect=LLMConnectionError("fail", provider_id="azure"))

        p2 = MagicMock(spec=OpenAIProvider)
        p2.plugin_id = "openai"
        p2.chat = AsyncMock(return_value=_make_mock_response("ok", "gpt-4o"))

        chain = build_fallback_chain([(p1, "deploy"), (p2, "gpt-4o")], max_retries_per_provider=2)
        messages = [LLMMessage(role="user", content="Hello")]
        config = LLMConfig()
        response = await chain.chat(messages, config)
        assert response.content == "ok"
        # p1 should have been called max_retries_per_provider times
        assert p1.chat.call_count == 2


# ---------------------------------------------------------------------------
# T014: Tier variable resolution
# ---------------------------------------------------------------------------

class TestTierVariableResolution:
    """HiveFlowConfig tier variables resolve to provider:model."""

    def test_smart_llm_default(self):
        config = HiveFlowConfig()
        resolved = config.resolve_model("$SMART_LLM")
        assert resolved == "openai:gpt-4o"

    def test_fast_llm_default(self):
        config = HiveFlowConfig()
        resolved = config.resolve_model("$FAST_LLM")
        assert resolved == "openai:gpt-4o-mini"

    def test_strategic_llm_default(self):
        config = HiveFlowConfig()
        resolved = config.resolve_model("$STRATEGIC_LLM")
        assert resolved == "openai:o3-mini"

    def test_direct_ref_passthrough(self):
        config = HiveFlowConfig()
        resolved = config.resolve_model("anthropic:claude-sonnet-4-20250514")
        assert resolved == "anthropic:claude-sonnet-4-20250514"

    def test_custom_tier_override(self):
        config = HiveFlowConfig(SMART_LLM="azure:gpt-4o-deploy")
        resolved = config.resolve_model("$SMART_LLM")
        assert resolved == "azure:gpt-4o-deploy"

    def test_tier_to_provider_end_to_end(self):
        """Full chain: tier variable → config → registry → provider instance."""
        config = HiveFlowConfig()
        model_ref = config.resolve_model("$SMART_LLM")
        assert model_ref == "openai:gpt-4o"

        reg = get_llm_registry()
        provider, model = reg.resolve_model(model_ref)
        assert provider.provider_id == "openai"
        assert model == "gpt-4o"

    def test_tier_override_to_azure(self):
        """Override $SMART_LLM to azure, resolve through registry."""
        config = HiveFlowConfig(SMART_LLM="azure:gpt-4o-eastus")
        model_ref = config.resolve_model("$SMART_LLM")

        reg = get_llm_registry()
        provider, model = reg.resolve_model(model_ref)
        assert provider.provider_id == "azure"
        assert model == "gpt-4o-eastus"


# ---------------------------------------------------------------------------
# T024: Transient-only fallback behavior (FR-019)
# ---------------------------------------------------------------------------


class TestTransientOnlyFallback:
    """Verify FallbackChain only cascades on transient errors in integration context."""

    def _make_provider(self, plugin_id: str) -> MagicMock:
        p = MagicMock()
        p.plugin_id = plugin_id
        p.supports_streaming = False
        p.supports_function_calling = False
        return p

    @pytest.mark.asyncio
    async def test_auth_error_fails_immediately(self):
        """LLMAuthError should NOT cascade — fails on first provider."""
        p1 = self._make_provider("p1")
        p1.chat = AsyncMock(side_effect=LLMAuthError("bad key", provider_id="p1"))
        p2 = self._make_provider("p2")
        p2.chat = AsyncMock(return_value=_make_mock_response("ok", "m2"))

        chain = FallbackChain([(p1, "m1"), (p2, "m2")])
        with pytest.raises(LLMAuthError):
            await chain.chat([], LLMConfig())
        assert p2.chat.call_count == 0

    @pytest.mark.asyncio
    async def test_model_not_found_fails_immediately(self):
        """LLMModelNotFoundError should NOT cascade."""
        p1 = self._make_provider("p1")
        p1.chat = AsyncMock(side_effect=LLMModelNotFoundError("no model", provider_id="p1"))
        p2 = self._make_provider("p2")
        p2.chat = AsyncMock(return_value=_make_mock_response("ok", "m2"))

        chain = FallbackChain([(p1, "m1"), (p2, "m2")])
        with pytest.raises(LLMModelNotFoundError):
            await chain.chat([], LLMConfig())
        assert p2.chat.call_count == 0

    @pytest.mark.asyncio
    async def test_connection_error_cascades(self):
        """LLMConnectionError should cascade to next provider."""
        p1 = self._make_provider("p1")
        p1.chat = AsyncMock(side_effect=LLMConnectionError("timeout", provider_id="p1"))
        p2 = self._make_provider("p2")
        p2.chat = AsyncMock(return_value=_make_mock_response("from-p2", "m2"))

        chain = FallbackChain([(p1, "m1"), (p2, "m2")])
        response = await chain.chat([], LLMConfig())
        assert response.content == "from-p2"
        assert p2.chat.call_count == 1

    @pytest.mark.asyncio
    async def test_rate_limit_cascades(self):
        """LLMRateLimitError should cascade to next provider."""
        p1 = self._make_provider("p1")
        p1.chat = AsyncMock(side_effect=LLMRateLimitError("429", provider_id="p1"))
        p2 = self._make_provider("p2")
        p2.chat = AsyncMock(return_value=_make_mock_response("from-p2", "m2"))

        chain = FallbackChain([(p1, "m1"), (p2, "m2")])
        response = await chain.chat([], LLMConfig())
        assert response.content == "from-p2"

    @pytest.mark.asyncio
    async def test_build_fallback_chain_uses_transient_default(self):
        """build_fallback_chain() wraps with RetryProvider that only retries transient."""
        p1 = self._make_provider("p1")
        p1.chat = AsyncMock(side_effect=LLMConnectionError("fail", provider_id="p1"))
        p2 = self._make_provider("p2")
        p2.chat = AsyncMock(return_value=_make_mock_response("ok", "m2"))

        chain = build_fallback_chain([(p1, "m1"), (p2, "m2")], max_retries_per_provider=2)
        response = await chain.chat([], LLMConfig())
        assert response.content == "ok"
        # p1 retried 2 times (max_retries_per_provider), then cascaded to p2
        assert p1.chat.call_count == 2

    @pytest.mark.asyncio
    async def test_retry_provider_only_retries_transient(self):
        """RetryProvider default only retries on transient errors."""
        p1 = self._make_provider("p1")
        p1.chat = AsyncMock(side_effect=LLMAuthError("bad key", provider_id="p1"))

        retry = RetryProvider(p1, max_retries=3)
        with pytest.raises(LLMAuthError):
            await retry.chat([], LLMConfig())
        # Should NOT retry auth errors — only one call
        assert p1.chat.call_count == 1
