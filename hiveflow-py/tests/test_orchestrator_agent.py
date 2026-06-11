"""Tests for OrchestratorAgent: depth limits, breadth, progress, result merging."""

from typing import Any

import pytest

from hiveflow.core.orchestrator import OrchestratorAgent
from hiveflow.core.research import DeepResearchConfig


async def mock_research_fn(query: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Mock research function that returns query-based findings."""
    return {"findings": f"Findings for: {query}", "citations": []}


async def mock_query_generator(topic: str, breadth: int) -> list[str]:
    """Mock query generator that creates sub-queries."""
    return [f"{topic} - aspect {i+1}" for i in range(breadth)]


class TestOrchestratorAgentCreation:

    def test_default_creation(self):
        agent = OrchestratorAgent()
        assert agent.agent_id == "orchestrator"
        assert agent.role == "Deep research orchestrator"

    def test_custom_config(self):
        config = DeepResearchConfig(breadth=5, depth=3)
        agent = OrchestratorAgent(
            agent_id="explorer",
            config=config,
            research_fn=mock_research_fn,
            query_generator_fn=mock_query_generator,
        )
        assert agent.agent_id == "explorer"
        assert agent._config.breadth == 5
        assert agent._config.depth == 3


class TestOrchestratorAgentExecution:

    async def test_execute_produces_output(self):
        agent = OrchestratorAgent(
            config=DeepResearchConfig(breadth=2, depth=1),
            research_fn=mock_research_fn,
            query_generator_fn=mock_query_generator,
        )
        state = {"task": "Analyze AI safety"}
        result = await agent.execute(state)
        assert f"{agent.agent_id}_output" in result
        assert result[f"{agent.agent_id}_output"]  # Non-empty

    async def test_execute_preserves_state(self):
        agent = OrchestratorAgent(
            config=DeepResearchConfig(breadth=2, depth=1),
            research_fn=mock_research_fn,
            query_generator_fn=mock_query_generator,
        )
        state = {"task": "Test", "existing_key": "preserved"}
        result = await agent.execute(state)
        assert result["existing_key"] == "preserved"

    async def test_execute_handles_failure(self):
        async def failing_research(query, context=None):
            raise ValueError("research failed")

        agent = OrchestratorAgent(
            config=DeepResearchConfig(breadth=1, depth=1),
            research_fn=failing_research,
            query_generator_fn=mock_query_generator,
        )
        state = {"task": "Test failure"}
        result = await agent.execute(state)
        assert "error" in result.get(f"{agent.agent_id}_output", "").lower() or \
               f"{agent.agent_id}_error" in result


class TestOrchestratorProgress:

    def test_initial_progress_zero(self):
        agent = OrchestratorAgent()
        assert agent.get_progress() == 0.0

    async def test_progress_after_completion(self):
        agent = OrchestratorAgent(
            config=DeepResearchConfig(breadth=2, depth=1),
            research_fn=mock_research_fn,
            query_generator_fn=mock_query_generator,
        )
        await agent.execute({"task": "Test"})
        assert agent.get_progress() == 1.0


class TestOrchestratorConfig:
    """Config values affect behavior."""

    async def test_breadth_affects_sub_tasks(self):
        queries_generated = []

        async def tracking_query_gen(topic, breadth):
            queries = [f"{topic} - {i}" for i in range(breadth)]
            queries_generated.extend(queries)
            return queries

        agent = OrchestratorAgent(
            config=DeepResearchConfig(breadth=4, depth=1),
            research_fn=mock_research_fn,
            query_generator_fn=tracking_query_gen,
        )
        await agent.execute({"task": "Test breadth"})
        # With breadth=4, should generate 4 sub-queries at depth 0
        assert len(queries_generated) >= 4

    async def test_depth_limits_recursion(self):
        call_count = 0

        async def counting_research(query, context=None):
            nonlocal call_count
            call_count += 1
            return {"findings": f"Result {call_count}", "citations": []}

        agent = OrchestratorAgent(
            config=DeepResearchConfig(breadth=2, depth=1),
            research_fn=counting_research,
            query_generator_fn=mock_query_generator,
        )
        await agent.execute({"task": "Test depth"})
        # depth=1 means max 1 level of recursion, breadth=2 per level
        # Total calls should be bounded
        assert call_count <= 10  # Generous upper bound
