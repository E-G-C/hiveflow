"""Shared utilities for document input pipeline examples.

Provides LLM provider factory (Azure or mock) and printing helpers
used across all example scripts.
"""

import os
from typing import Any

from hiveflow.plugins.llm import LLMConfig, LLMMessage, LLMProvider, LLMResponse, TokenUsage


# ---------------------------------------------------------------------------
# Azure deployment name — override via AZURE_OPENAI_DEPLOYMENT env var
# ---------------------------------------------------------------------------
DEFAULT_DEPLOYMENT = "gpt-4o-mini"


# ---------------------------------------------------------------------------
# Mock provider for offline use
# ---------------------------------------------------------------------------

class MockLLMProvider(LLMProvider):
    """Deterministic mock that returns plausible text for demos."""

    @property
    def plugin_id(self) -> str:
        return "mock"

    @property
    def description(self) -> str:
        return "Mock LLM for offline demos"

    async def chat(
        self, messages: list[LLMMessage], config: LLMConfig
    ) -> LLMResponse:
        system = next((m.content for m in messages if m.role == "system"), "")
        user = next((m.content for m in messages if m.role == "user"), "")

        # Summary requests
        if "summar" in system.lower():
            content = (
                "This document discusses key topics including planning, "
                "technical architecture, and action items. The main findings "
                "are that the project is on track with several deliverables "
                "completed and a few pending items requiring attention."
            )
        # Analyst / metrics role
        elif "analyst" in system.lower() or "metric" in system.lower():
            content = (
                "## Key Findings\n\n"
                "- Revenue growth: 15% YoY\n"
                "- Customer retention: 92%\n"
                "- Active users: 2.1M monthly\n\n"
                "## Recommendations\n\n"
                "1. Invest in mobile experience (drives 60% of traffic)\n"
                "2. Expand into APAC markets\n"
                "3. Increase R&D investment to 20% of revenue"
            )
        # Writer / summary role
        elif "writer" in system.lower() or "executive" in system.lower():
            content = (
                "# Executive Summary\n\n"
                "The analysis reveals strong performance across key metrics. "
                "Revenue grew 15% year-over-year, customer retention stands "
                "at 92%, and monthly active users reached 2.1 million. "
                "Strategic priorities for next quarter include mobile "
                "optimization, APAC expansion, and increased R&D investment."
            )
        # Planner / reviewer
        elif "plan" in system.lower() or "review" in system.lower():
            content = (
                "## Action Plan\n\n"
                "1. **Immediate** (this week): Finalize API contracts\n"
                "2. **Short-term** (2 weeks): Mobile wireframes and testing\n"
                "3. **Medium-term** (1 month): Launch v2.0 beta\n"
                "4. **Deferred** (Q1 next year): Internationalization"
            )
        else:
            content = (
                "Based on the provided documents, here is my analysis:\n\n"
                "The documents cover organizational planning and technical "
                "implementation details. Key themes include project timelines, "
                "resource allocation, and risk mitigation strategies."
            )

        return LLMResponse(
            content=content,
            model="mock-model",
            usage=TokenUsage(
                prompt_tokens=len(user.split()),
                completion_tokens=len(content.split()),
                total_tokens=len(user.split()) + len(content.split()),
            ),
        )


# ---------------------------------------------------------------------------
# Provider factory
# ---------------------------------------------------------------------------

def get_provider() -> tuple[LLMProvider, str]:
    """Return Azure OpenAI provider if endpoint is configured, else mock.

    Also sets the global HiveFlowConfig so that all LLM tiers resolve to
    the selected deployment, avoiding DeploymentNotFound errors from the
    fallback chain trying o3-mini or other unconfigured deployments.

    Returns:
        Tuple of (provider instance, deployment/model name).
    """
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    if endpoint:
        from hiveflow.plugins.llm.azure_provider import AzureOpenAIProvider

        deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", DEFAULT_DEPLOYMENT)
        provider = AzureOpenAIProvider(azure_endpoint=endpoint)

        # Pin all tiers to the same deployment so the fallback chain and
        # summary generation use the correct model.
        from hiveflow.core.config import HiveFlowConfig, set_config
        model_ref = f"azure:{deployment}"
        set_config(HiveFlowConfig(
            FAST_LLM=model_ref,
            SMART_LLM=model_ref,
            STRATEGIC_LLM=model_ref,
        ))

        return provider, deployment

    return MockLLMProvider(), "mock-model"


def is_live() -> bool:
    """Check whether we are using a live LLM provider."""
    return bool(os.environ.get("AZURE_OPENAI_ENDPOINT"))


# ---------------------------------------------------------------------------
# Print helpers
# ---------------------------------------------------------------------------

def print_section(title: str) -> None:
    """Print a styled section header."""
    print(f"\n{'=' * 64}")
    print(f"  {title}")
    print(f"{'=' * 64}\n")


def print_kv(label: str, value: Any, indent: int = 2) -> None:
    """Print a key-value pair with indentation."""
    prefix = " " * indent
    print(f"{prefix}{label}: {value}")
