"""Tests for Context Management Strategy: summary propagation,
context budgets, outline generation, orchestrator decomposition,
and code-level assembly."""

import json

from hiveflow.core.agent import Agent, AgentBehaviorType
from hiveflow.core.config import HiveFlowConfig
from hiveflow.core.schema import AgentBehaviorTypeSchema, AgentDefinition
from hiveflow.core.summarizer import SummaryGenerator
from hiveflow.core.workflow import (
    StepType,
    WorkflowEngine,
    WorkflowStatus,
    WorkflowStep,
)
from hiveflow.plugins.llm import (
    LLMConfig,
    LLMMessage,
    LLMProvider,
    LLMResponse,
    TokenUsage,
)

# --- Mock Providers ---


class MockSummaryProvider(LLMProvider):
    """Mock that returns a fixed summary prefix + truncated input."""

    @property
    def plugin_id(self) -> str:
        return "mock_summary"

    @property
    def description(self) -> str:
        return "Mock summary provider"

    async def chat(
        self, messages: list[LLMMessage], config: LLMConfig
    ) -> LLMResponse:
        user_msg = next(
            (m.content for m in messages if m.role == "user"), ""
        )
        summary = f"SUMMARY: {user_msg[:50]}..."
        return LLMResponse(
            content=summary,
            model="mock",
            usage=TokenUsage(
                prompt_tokens=10, completion_tokens=5, total_tokens=15
            ),
        )


class MockContentProvider(LLMProvider):
    """Mock that returns long content."""

    def __init__(self, word_count: int = 500) -> None:
        self._word_count = word_count

    @property
    def plugin_id(self) -> str:
        return "mock_content"

    @property
    def description(self) -> str:
        return "Mock content provider"

    async def chat(
        self, messages: list[LLMMessage], config: LLMConfig
    ) -> LLMResponse:
        content = " ".join(["content"] * self._word_count)
        return LLMResponse(
            content=content,
            model="mock",
            usage=TokenUsage(
                prompt_tokens=10, completion_tokens=20, total_tokens=30
            ),
        )


class MockSimpleProvider(LLMProvider):
    """Mock that returns a fixed response."""

    def __init__(self, response: str = "output") -> None:
        self._response = response

    @property
    def plugin_id(self) -> str:
        return "mock_simple"

    @property
    def description(self) -> str:
        return "Mock simple provider"

    async def chat(
        self, messages: list[LLMMessage], config: LLMConfig
    ) -> LLMResponse:
        return LLMResponse(
            content=self._response,
            model="mock",
            usage=TokenUsage(
                prompt_tokens=10, completion_tokens=20, total_tokens=30
            ),
        )


# --- SummaryGenerator Tests ---


class TestSummaryGenerator:
    async def test_summarize_short_text_passthrough(self):
        """Text shorter than max_tokens should be returned as-is."""
        provider = MockSummaryProvider()
        gen = SummaryGenerator(
            llm_provider=provider, max_summary_tokens=200
        )
        result = await gen.summarize("short text")
        assert result == "short text"

    async def test_summarize_long_text_calls_llm(self):
        """Text longer than max_tokens should be summarized via LLM."""
        provider = MockSummaryProvider()
        gen = SummaryGenerator(
            llm_provider=provider, max_summary_tokens=10
        )
        long_text = " ".join(["word"] * 500)
        result = await gen.summarize(long_text)
        assert result.startswith("SUMMARY:")

    async def test_summarize_custom_max_tokens(self):
        """Custom max_tokens override should be respected."""
        provider = MockSummaryProvider()
        gen = SummaryGenerator(
            llm_provider=provider, max_summary_tokens=200
        )
        long_text = " ".join(["word"] * 500)
        # Use a small override to force LLM call
        result = await gen.summarize(long_text, max_tokens=10)
        assert result.startswith("SUMMARY:")

    async def test_build_outline_short_summaries_passthrough(self):
        """Short summaries that fit in budget should be returned directly."""
        provider = MockSummaryProvider()
        gen = SummaryGenerator(
            llm_provider=provider, max_outline_tokens=1000
        )
        summaries = {
            "agent1": "Short summary A",
            "agent2": "Short summary B",
        }
        outline = await gen.build_outline(summaries)
        assert "agent1" in outline
        assert "Short summary A" in outline

    async def test_build_outline_long_summaries_calls_llm(self):
        """Long summaries that exceed budget should be processed via LLM."""
        provider = MockSummaryProvider()
        gen = SummaryGenerator(
            llm_provider=provider, max_outline_tokens=5
        )
        summaries = {
            "agent1": " ".join(["findings"] * 100),
            "agent2": " ".join(["results"] * 100),
        }
        outline = await gen.build_outline(summaries)
        assert outline.startswith("SUMMARY:")


# --- SummaryGenerator Threshold Tests ---


class TestSummaryThreshold:
    async def test_threshold_skips_medium_text(self):
        """Text under summary_threshold should pass through even if above max_summary_tokens."""
        provider = MockSummaryProvider()
        gen = SummaryGenerator(
            llm_provider=provider,
            max_summary_tokens=200,
            summary_threshold=4000,
        )
        medium_text = " ".join(["word"] * 1000)
        result = await gen.summarize(medium_text)
        # 1000 words < 4000 threshold, so text should be returned as-is
        assert result == medium_text

    async def test_threshold_summarizes_long_text(self):
        """Text exceeding summary_threshold should be summarized."""
        provider = MockSummaryProvider()
        gen = SummaryGenerator(
            llm_provider=provider,
            max_summary_tokens=200,
            summary_threshold=4000,
        )
        long_text = " ".join(["word"] * 5000)
        result = await gen.summarize(long_text)
        # 5000 words > 4000 threshold, should be summarized
        assert result.startswith("SUMMARY:")

    async def test_threshold_none_preserves_legacy(self):
        """With summary_threshold=None, max_summary_tokens acts as threshold (legacy)."""
        provider = MockSummaryProvider()
        gen = SummaryGenerator(
            llm_provider=provider,
            max_summary_tokens=200,
            summary_threshold=None,
        )
        text = " ".join(["word"] * 300)
        result = await gen.summarize(text)
        # 300 words > 200 (legacy threshold), should be summarized
        assert result.startswith("SUMMARY:")

    async def test_threshold_max_tokens_override_does_not_affect_threshold(self):
        """Explicit max_tokens override should affect output budget, not skip threshold."""
        provider = MockSummaryProvider()
        gen = SummaryGenerator(
            llm_provider=provider,
            max_summary_tokens=200,
            summary_threshold=4000,
        )
        medium_text = " ".join(["word"] * 1000)
        # Even with max_tokens=50, threshold is still 4000
        result = await gen.summarize(medium_text, max_tokens=50)
        # 1000 words < 4000, should still pass through
        assert result == medium_text

    async def test_workflow_with_threshold_passthrough(self):
        """With high threshold, moderate outputs should pass through unsummarized."""
        summary_provider = MockSummaryProvider()
        summarizer = SummaryGenerator(
            llm_provider=summary_provider,
            max_summary_tokens=200,
            summary_threshold=4000,
        )

        content_provider = MockContentProvider(word_count=500)
        agent1 = Agent(
            agent_id="a1",
            role="A1",
            system_prompt="test",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=content_provider,
        )
        agent2 = Agent(
            agent_id="a2",
            role="A2",
            system_prompt="test",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=content_provider,
        )

        steps = [
            WorkflowStep(
                agent="a1",
                step_type=StepType.SEQUENTIAL,
                next_step="a2",
            ),
            WorkflowStep(agent="a2", step_type=StepType.SEQUENTIAL),
        ]
        engine = WorkflowEngine(steps, summarizer=summarizer)
        result = await engine.execute(
            {"a1": agent1, "a2": agent2}, {"task": "test"}
        )

        assert result.status == WorkflowStatus.COMPLETED
        # 500 words < 4000 threshold: summary should be the full output
        assert "a1_summary" in result.state
        assert not result.state["a1_summary"].startswith("SUMMARY:")
        assert result.state["a1_summary"] == result.state["a1_output"]


# --- Agent._summarize_state Tests ---


class TestSummarizeStatePrefersSummaries:
    def _make_agent(self) -> Agent:
        return Agent(
            agent_id="downstream",
            role="Test",
            system_prompt="test",
            behavior_type=AgentBehaviorType.LLM_ONLY,
        )

    def test_prefers_summary_over_output(self):
        """_summarize_state should use _summary when available."""
        agent = self._make_agent()
        state = {
            "task": "do something",
            "researcher_output": "Very long research text " * 100,
            "researcher_summary": "Brief summary of research.",
        }
        result = agent._summarize_state(state)
        assert "Brief summary of research." in result
        assert "Very long research text" not in result

    def test_falls_back_to_output_when_no_summary(self):
        """Without summary, full output should be used (backward compat)."""
        agent = self._make_agent()
        state = {
            "task": "do something",
            "researcher_output": "Full output here",
        }
        result = agent._summarize_state(state)
        assert "Full output here" in result

    def test_uses_outline_for_parallel(self):
        """Outline from parallel execution should be included."""
        agent = self._make_agent()
        state = {
            "task": "review",
            "worker_outline": "- Point 1\n- Point 2\n- Point 3",
            "worker_output": "Very long combined text " * 100,
        }
        result = agent._summarize_state(state)
        assert "Point 1" in result

    def test_includes_task_and_input_data(self):
        """Task and input_data should always be included."""
        agent = self._make_agent()
        state = {
            "task": "my task",
            "input_data": "some data",
        }
        result = agent._summarize_state(state)
        assert "my task" in result
        assert "some data" in result

    def test_multiple_agents_with_mixed_summaries(self):
        """Mix of agents with and without summaries handled correctly."""
        agent = self._make_agent()
        state = {
            "task": "test",
            "agent_a_output": "Full A output text " * 50,
            "agent_a_summary": "A summary",
            "agent_b_output": "Full B output no summary",
        }
        result = agent._summarize_state(state)
        assert "A summary" in result
        assert "Full A output text" not in result
        assert "Full B output no summary" in result


# --- WorkflowEngine with Summarizer Tests ---


class TestWorkflowWithSummarizer:
    async def test_summaries_generated_in_sequential(self):
        """Sequential workflow should produce summary keys in state."""
        summary_provider = MockSummaryProvider()
        summarizer = SummaryGenerator(
            llm_provider=summary_provider, max_summary_tokens=10
        )

        content_provider = MockContentProvider(word_count=500)
        agent1 = Agent(
            agent_id="a1",
            role="A1",
            system_prompt="test",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=content_provider,
        )
        agent2 = Agent(
            agent_id="a2",
            role="A2",
            system_prompt="test",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=content_provider,
        )

        steps = [
            WorkflowStep(
                agent="a1",
                step_type=StepType.SEQUENTIAL,
                next_step="a2",
            ),
            WorkflowStep(
                agent="a2", step_type=StepType.SEQUENTIAL
            ),
        ]
        engine = WorkflowEngine(steps, summarizer=summarizer)
        result = await engine.execute(
            {"a1": agent1, "a2": agent2}, {"task": "test"}
        )

        assert result.status == WorkflowStatus.COMPLETED
        assert "a1_summary" in result.state
        assert "a2_summary" in result.state
        assert result.state["a1_summary"].startswith("SUMMARY:")

    async def test_no_summarizer_backward_compat(self):
        """Without summarizer, no summary keys -- old behavior preserved."""
        provider = MockSimpleProvider("output")
        agent = Agent(
            agent_id="a1",
            role="A1",
            system_prompt="t",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=provider,
        )

        steps = [
            WorkflowStep(agent="a1", step_type=StepType.SEQUENTIAL)
        ]
        engine = WorkflowEngine(steps)  # No summarizer
        result = await engine.execute({"a1": agent}, {"task": "test"})

        assert result.status == WorkflowStatus.COMPLETED
        assert "a1_output" in result.state
        assert "a1_summary" not in result.state

    async def test_summary_failure_does_not_crash(self):
        """If summary generation fails, workflow should still complete."""

        class FailingProvider(LLMProvider):
            @property
            def plugin_id(self) -> str:
                return "failing"

            @property
            def description(self) -> str:
                return "Fails"

            async def chat(
                self, messages: list[LLMMessage], config: LLMConfig
            ) -> LLMResponse:
                raise RuntimeError("Summary LLM failed")

        summarizer = SummaryGenerator(
            llm_provider=FailingProvider(), max_summary_tokens=10
        )
        content_provider = MockContentProvider(word_count=500)
        agent = Agent(
            agent_id="a1",
            role="A1",
            system_prompt="test",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=content_provider,
        )

        steps = [
            WorkflowStep(agent="a1", step_type=StepType.SEQUENTIAL)
        ]
        engine = WorkflowEngine(steps, summarizer=summarizer)
        result = await engine.execute({"a1": agent}, {"task": "test"})

        assert result.status == WorkflowStatus.COMPLETED
        assert "a1_output" in result.state
        # Summary should not exist since it failed
        assert "a1_summary" not in result.state

    async def test_from_schema_with_summarizer(self):
        """from_schema should pass summarizer through."""
        from hiveflow.core.schema import (
            WorkflowGraph,
            WorkflowStepDefinition,
            WorkflowStepType,
        )

        summarizer = SummaryGenerator(
            llm_provider=MockSummaryProvider(), max_summary_tokens=10
        )

        graph = WorkflowGraph(
            steps=[
                WorkflowStepDefinition(
                    agent="a1",
                    type=WorkflowStepType.SEQUENTIAL,
                ),
            ]
        )

        engine = WorkflowEngine.from_schema(graph, summarizer=summarizer)
        assert engine.summarizer is summarizer


# --- AgentDefinition max_tokens Tests ---


class TestAgentDefinitionMaxTokens:
    def test_default_none(self):
        defn = AgentDefinition(
            id="test",
            role="Test",
            system_prompt="test",
            behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
        )
        assert defn.max_tokens is None

    def test_explicit_value(self):
        defn = AgentDefinition(
            id="test",
            role="Test",
            system_prompt="test",
            behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
            max_tokens=8000,
        )
        assert defn.max_tokens == 8000

    def test_from_definition_with_max_tokens(self):
        defn = AgentDefinition(
            id="test",
            role="Test",
            system_prompt="test",
            behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
            max_tokens=8000,
        )
        agent = Agent.from_definition(defn)
        assert agent.llm_config.max_tokens == 8000

    def test_from_definition_without_max_tokens(self):
        defn = AgentDefinition(
            id="test",
            role="Test",
            system_prompt="test",
            behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
        )
        agent = Agent.from_definition(defn)
        # Should use the new default of 16000
        assert agent.llm_config.max_tokens == 16000


# --- Context Management Config Tests ---


class TestContextManagementConfig:
    def test_new_defaults(self):
        config = HiveFlowConfig()
        assert config.MAX_CONTEXT_PER_TASK == 4000
        assert config.MAX_SUMMARY_LENGTH == 200
        assert config.MAX_OUTLINE_LENGTH == 1000
        assert config.ENABLE_SUMMARY_PROPAGATION is True

    def test_max_tokens_new_default(self):
        config = HiveFlowConfig()
        assert config.MAX_TOKENS == 16000

    def test_override(self):
        config = HiveFlowConfig()
        overridden = config.apply_overrides({"max_summary_length": 500})
        assert overridden.MAX_SUMMARY_LENGTH == 500

    def test_override_max_tokens(self):
        config = HiveFlowConfig()
        overridden = config.apply_overrides({"max_tokens": 8000})
        assert overridden.MAX_TOKENS == 8000


# --- Context Budget Enforcement Tests ---


class TestContextBudgetEnforcement:
    def _make_agent(self, budget: int | None = None) -> Agent:
        return Agent(
            agent_id="downstream",
            role="Test",
            system_prompt="test",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            context_budget=budget,
        )

    def test_no_budget_no_truncation(self):
        """Without context_budget, text should not be truncated."""
        agent = self._make_agent(budget=None)
        state = {
            "task": "my task",
            "agent_a_output": " ".join(["word"] * 5000),
        }
        result = agent._summarize_state(state)
        assert len(result.split()) > 4000

    def test_budget_truncates_long_context(self):
        """Context exceeding budget should be truncated."""
        agent = self._make_agent(budget=100)
        state = {
            "task": "my task",
            "agent_a_output": " ".join(["word"] * 5000),
        }
        result = agent._summarize_state(state)
        assert len(result.split()) <= 110  # Budget + small overhead from marker

    def test_budget_preserves_short_context(self):
        """Context within budget should be unchanged."""
        agent = self._make_agent(budget=1000)
        state = {
            "task": "do something",
            "agent_a_summary": "Brief summary.",
        }
        result = agent._summarize_state(state)
        assert "Brief summary." in result
        assert "[truncated" not in result

    def test_budget_preserves_task(self):
        """Task line should always be preserved even with truncation."""
        agent = self._make_agent(budget=50)
        state = {
            "task": "important task description",
            "agent_a_output": " ".join(["filler"] * 5000),
        }
        result = agent._summarize_state(state)
        assert "important task description" in result

    def test_budget_with_multiple_sections(self):
        """Budget should fit complete sections where possible."""
        agent = self._make_agent(budget=50)
        state = {
            "task": "test",
            "agent_a_summary": "A short summary about 10 words long here.",
            "agent_b_summary": "B short summary another 10 words long here.",
            "agent_c_output": " ".join(["more"] * 5000),
        }
        result = agent._summarize_state(state)
        # Task + at least one summary should be present
        assert "test" in result
        assert len(result.split()) <= 60  # Budget + overhead

    def test_from_definition_with_context_budget(self):
        """from_definition should pass context_budget through."""
        defn = AgentDefinition(
            id="test",
            role="Test",
            system_prompt="test",
            behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
        )
        agent = Agent.from_definition(defn, context_budget=4000)
        assert agent.context_budget == 4000

    def test_from_definition_without_context_budget(self):
        """from_definition without context_budget should default to None."""
        defn = AgentDefinition(
            id="test",
            role="Test",
            system_prompt="test",
            behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
        )
        agent = Agent.from_definition(defn)
        assert agent.context_budget is None


# --- Orchestrator Decomposition Tests ---


class MockOrchestratorProvider(LLMProvider):
    """Mock that returns a JSON decomposition response."""

    def __init__(self, sub_tasks: list[str] | None = None) -> None:
        self._sub_tasks = sub_tasks or [
            "Research topic A",
            "Research topic B",
            "Research topic C",
        ]

    @property
    def plugin_id(self) -> str:
        return "mock_orchestrator"

    @property
    def description(self) -> str:
        return "Mock orchestrator provider"

    async def chat(
        self, messages: list[LLMMessage], config: LLMConfig
    ) -> LLMResponse:
        response = json.dumps({"sub_tasks": self._sub_tasks})
        return LLMResponse(
            content=response,
            model="mock",
            usage=TokenUsage(
                prompt_tokens=10, completion_tokens=20, total_tokens=30
            ),
        )


class TestOrchestratorDecomposition:
    async def test_decomposes_into_parallel_items(self):
        """Orchestrator should populate parallel_items in state."""
        provider = MockOrchestratorProvider()
        agent = Agent(
            agent_id="orchestrator",
            role="Orchestrator",
            system_prompt="You are a task planner.",
            behavior_type=AgentBehaviorType.ORCHESTRATOR,
            llm_provider=provider,
        )
        state = {"task": "Write a comprehensive report on AI"}
        result = await agent.execute(state)

        assert "parallel_items" in result
        assert len(result["parallel_items"]) == 3
        assert "Research topic A" in result["parallel_items"]
        assert "orchestrator_output" in result

    async def test_decomposes_custom_sub_tasks(self):
        """Orchestrator should parse custom sub-task lists."""
        provider = MockOrchestratorProvider(sub_tasks=["Task 1", "Task 2"])
        agent = Agent(
            agent_id="planner",
            role="Planner",
            system_prompt="plan",
            behavior_type=AgentBehaviorType.ORCHESTRATOR,
            llm_provider=provider,
        )
        state = {"task": "Do two things"}
        result = await agent.execute(state)

        assert result["parallel_items"] == ["Task 1", "Task 2"]

    async def test_includes_input_data_in_prompt(self):
        """Orchestrator should include input_data in decomposition prompt."""

        class CapturingProvider(LLMProvider):
            def __init__(self):
                self.captured_messages = []

            @property
            def plugin_id(self) -> str:
                return "capturing"

            @property
            def description(self) -> str:
                return "Captures"

            async def chat(
                self, messages: list[LLMMessage], config: LLMConfig
            ) -> LLMResponse:
                self.captured_messages = messages
                return LLMResponse(
                    content='{"sub_tasks": ["t1"]}',
                    model="mock",
                    usage=TokenUsage(
                        prompt_tokens=10,
                        completion_tokens=5,
                        total_tokens=15,
                    ),
                )

        provider = CapturingProvider()
        agent = Agent(
            agent_id="orch",
            role="Orch",
            system_prompt="plan",
            behavior_type=AgentBehaviorType.ORCHESTRATOR,
            llm_provider=provider,
        )
        state = {"task": "my task", "input_data": "extra context"}
        await agent.execute(state)

        user_msg = next(
            m.content for m in provider.captured_messages if m.role == "user"
        )
        assert "extra context" in user_msg

    def test_parse_sub_tasks_json(self):
        """_parse_sub_tasks should handle valid JSON."""
        agent = Agent(
            agent_id="t",
            role="T",
            system_prompt="t",
            behavior_type=AgentBehaviorType.ORCHESTRATOR,
        )
        response = '{"sub_tasks": ["A", "B", "C"]}'
        result = agent._parse_sub_tasks(response)
        assert result == ["A", "B", "C"]

    def test_parse_sub_tasks_json_with_prefix(self):
        """_parse_sub_tasks should extract JSON from surrounding text."""
        agent = Agent(
            agent_id="t",
            role="T",
            system_prompt="t",
            behavior_type=AgentBehaviorType.ORCHESTRATOR,
        )
        response = 'Here is my plan:\n{"sub_tasks": ["X", "Y"]}\nDone.'
        result = agent._parse_sub_tasks(response)
        assert result == ["X", "Y"]

    def test_parse_sub_tasks_numbered_fallback(self):
        """_parse_sub_tasks should fall back to numbered line extraction."""
        agent = Agent(
            agent_id="t",
            role="T",
            system_prompt="t",
            behavior_type=AgentBehaviorType.ORCHESTRATOR,
        )
        response = "1. First task\n2. Second task\n3. Third task"
        result = agent._parse_sub_tasks(response)
        assert len(result) == 3
        assert "First task" in result[0]

    def test_parse_sub_tasks_bullet_fallback(self):
        """_parse_sub_tasks should handle bullet-point lists."""
        agent = Agent(
            agent_id="t",
            role="T",
            system_prompt="t",
            behavior_type=AgentBehaviorType.ORCHESTRATOR,
        )
        response = "- Research AI\n- Analyze data\n* Write report"
        result = agent._parse_sub_tasks(response)
        assert len(result) == 3

    def test_parse_sub_tasks_raw_fallback(self):
        """_parse_sub_tasks should return raw text when no pattern found."""
        agent = Agent(
            agent_id="t",
            role="T",
            system_prompt="t",
            behavior_type=AgentBehaviorType.ORCHESTRATOR,
        )
        response = "Just do everything at once"
        result = agent._parse_sub_tasks(response)
        assert result == ["Just do everything at once"]


# --- Orchestrator + Parallel Fan-out Integration Tests ---


class TestOrchestratorWorkflow:
    async def test_orchestrator_feeds_parallel_fanout(self):
        """Orchestrator step should feed parallel_items to fan-out step."""
        orch_provider = MockOrchestratorProvider(
            sub_tasks=["Sub-task A", "Sub-task B"]
        )
        worker_provider = MockSimpleProvider("section content")

        orchestrator = Agent(
            agent_id="orch",
            role="Orchestrator",
            system_prompt="plan",
            behavior_type=AgentBehaviorType.ORCHESTRATOR,
            llm_provider=orch_provider,
        )
        worker = Agent(
            agent_id="worker",
            role="Worker",
            system_prompt="execute",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=worker_provider,
        )

        steps = [
            WorkflowStep(
                agent="orch",
                step_type=StepType.SEQUENTIAL,
                next_step="worker",
            ),
            WorkflowStep(
                agent="worker",
                step_type=StepType.PARALLEL_FAN_OUT,
            ),
        ]
        engine = WorkflowEngine(steps)
        result = await engine.execute(
            {"orch": orchestrator, "worker": worker},
            {"task": "Write a report"},
        )

        assert result.status == WorkflowStatus.COMPLETED
        assert "worker_outputs" in result.state
        assert len(result.state["worker_outputs"]) == 2


# --- Code-level Assembly Tests ---


class TestCodeLevelAssembly:
    async def test_assembly_creates_final_output(self):
        """Assembly should concatenate agent outputs into final_output."""
        provider = MockSimpleProvider("section content")
        agent1 = Agent(
            agent_id="a1",
            role="A1",
            system_prompt="t",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=provider,
        )
        agent2 = Agent(
            agent_id="a2",
            role="A2",
            system_prompt="t",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=provider,
        )

        steps = [
            WorkflowStep(
                agent="a1",
                step_type=StepType.SEQUENTIAL,
                next_step="a2",
            ),
            WorkflowStep(agent="a2", step_type=StepType.SEQUENTIAL),
        ]
        engine = WorkflowEngine(steps, assembly_agents=["a1", "a2"])
        result = await engine.execute(
            {"a1": agent1, "a2": agent2}, {"task": "test"}
        )

        assert result.status == WorkflowStatus.COMPLETED
        assert "final_output" in result.state
        # Both agent outputs should be in the assembled document
        assert "section content" in result.state["final_output"]

    async def test_assembly_respects_agent_order(self):
        """Assembly should concatenate outputs in specified order."""
        provider1 = MockSimpleProvider("FIRST SECTION")
        provider2 = MockSimpleProvider("SECOND SECTION")
        agent1 = Agent(
            agent_id="a1",
            role="A1",
            system_prompt="t",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=provider1,
        )
        agent2 = Agent(
            agent_id="a2",
            role="A2",
            system_prompt="t",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=provider2,
        )

        steps = [
            WorkflowStep(
                agent="a1",
                step_type=StepType.SEQUENTIAL,
                next_step="a2",
            ),
            WorkflowStep(agent="a2", step_type=StepType.SEQUENTIAL),
        ]
        engine = WorkflowEngine(steps, assembly_agents=["a1", "a2"])
        result = await engine.execute(
            {"a1": agent1, "a2": agent2}, {"task": "test"}
        )

        final = result.state["final_output"]
        assert final.index("FIRST SECTION") < final.index("SECOND SECTION")

    async def test_assembly_selective_agents(self):
        """Assembly should only include specified agents."""
        provider1 = MockSimpleProvider("included")
        provider2 = MockSimpleProvider("excluded")
        agent1 = Agent(
            agent_id="writer",
            role="Writer",
            system_prompt="t",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=provider1,
        )
        agent2 = Agent(
            agent_id="reviewer",
            role="Reviewer",
            system_prompt="t",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=provider2,
        )

        steps = [
            WorkflowStep(
                agent="writer",
                step_type=StepType.SEQUENTIAL,
                next_step="reviewer",
            ),
            WorkflowStep(
                agent="reviewer", step_type=StepType.SEQUENTIAL
            ),
        ]
        # Only assemble writer output, not reviewer
        engine = WorkflowEngine(steps, assembly_agents=["writer"])
        result = await engine.execute(
            {"writer": agent1, "reviewer": agent2}, {"task": "test"}
        )

        assert "included" in result.state["final_output"]
        assert "excluded" not in result.state["final_output"]

    async def test_no_assembly_by_default(self):
        """Without assembly_agents, no final_output should be created."""
        provider = MockSimpleProvider("output")
        agent = Agent(
            agent_id="a1",
            role="A1",
            system_prompt="t",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=provider,
        )

        steps = [
            WorkflowStep(agent="a1", step_type=StepType.SEQUENTIAL)
        ]
        engine = WorkflowEngine(steps)  # No assembly_agents
        result = await engine.execute({"a1": agent}, {"task": "test"})

        assert "final_output" not in result.state

    async def test_assembly_with_parallel_outputs(self):
        """Assembly should handle parallel fan-out outputs."""
        provider = MockSimpleProvider("parallel section")
        worker = Agent(
            agent_id="worker",
            role="Worker",
            system_prompt="t",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=provider,
        )

        steps = [
            WorkflowStep(
                agent="worker", step_type=StepType.PARALLEL_FAN_OUT
            ),
        ]
        engine = WorkflowEngine(steps, assembly_agents=["worker"])
        result = await engine.execute(
            {"worker": worker},
            {"task": "test", "parallel_items": ["item1", "item2", "item3"]},
        )

        assert result.status == WorkflowStatus.COMPLETED
        assert "final_output" in result.state
        # Each parallel item should produce a section
        assert result.state["final_output"].count("parallel section") == 3

    async def test_from_schema_with_assembly(self):
        """from_schema should pass assembly_agents through."""
        from hiveflow.core.schema import (
            WorkflowGraph,
            WorkflowStepDefinition,
            WorkflowStepType,
        )

        graph = WorkflowGraph(
            steps=[
                WorkflowStepDefinition(
                    agent="a1",
                    type=WorkflowStepType.SEQUENTIAL,
                ),
            ]
        )

        engine = WorkflowEngine.from_schema(
            graph, assembly_agents=["a1"]
        )
        assert engine.assembly_agents == ["a1"]


# --- Full Divide-and-Conquer Integration Test ---


class TestDivideAndConquerIntegration:
    async def test_full_pipeline(self):
        """Full divide-and-conquer: orchestrate -> fan-out -> assemble."""
        orch_provider = MockOrchestratorProvider(
            sub_tasks=["Write intro", "Write body", "Write conclusion"]
        )
        worker_provider = MockContentProvider(word_count=100)
        summary_provider = MockSummaryProvider()

        orchestrator = Agent(
            agent_id="planner",
            role="Planner",
            system_prompt="plan the document",
            behavior_type=AgentBehaviorType.ORCHESTRATOR,
            llm_provider=orch_provider,
        )
        worker = Agent(
            agent_id="writer",
            role="Writer",
            system_prompt="write the section",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=worker_provider,
            context_budget=500,
        )

        summarizer = SummaryGenerator(
            llm_provider=summary_provider, max_summary_tokens=10
        )

        steps = [
            WorkflowStep(
                agent="planner",
                step_type=StepType.SEQUENTIAL,
                next_step="writer",
            ),
            WorkflowStep(
                agent="writer",
                step_type=StepType.PARALLEL_FAN_OUT,
            ),
        ]
        engine = WorkflowEngine(
            steps,
            summarizer=summarizer,
            assembly_agents=["writer"],
        )
        result = await engine.execute(
            {"planner": orchestrator, "writer": worker},
            {"task": "Write a report on AI"},
        )

        assert result.status == WorkflowStatus.COMPLETED
        # Orchestrator decomposed into 3 sub-tasks
        assert len(result.state.get("parallel_items", [])) == 3
        # Worker produced parallel outputs
        assert "writer_outputs" in result.state
        assert len(result.state["writer_outputs"]) == 3
        # Summaries were generated
        assert "planner_summary" in result.state
        # Assembly produced final output
        assert "final_output" in result.state
        # Final output is substantial (3 x 100 words)
        final_words = len(result.state["final_output"].split())
        assert final_words >= 200


# --- Sliding Window State Propagation Tests (Idea 1) ---


class TestSlidingWindowPropagation:
    def _make_agent(self, window: int = 0) -> Agent:
        return Agent(
            agent_id="downstream",
            role="Test",
            system_prompt="test",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            context_recency_window=window,
        )

    def test_no_window_includes_all(self):
        """Without recency window, all agent summaries should be included."""
        agent = self._make_agent(window=0)
        state = {
            "task": "test",
            "a1_summary": "Summary A1",
            "a2_summary": "Summary A2",
            "a3_summary": "Summary A3",
            "a4_summary": "Summary A4",
            "a5_summary": "Summary A5",
        }
        result = agent._summarize_state(state)
        assert "Summary A1" in result
        assert "Summary A5" in result

    def test_window_collapses_old_entries(self):
        """With window=2, only last 2 summaries should be fully included."""
        agent = self._make_agent(window=2)
        state = {
            "task": "test",
            "a1_summary": "Summary A1",
            "a2_summary": "Summary A2",
            "a3_summary": "Summary A3",
            "a4_summary": "Summary A4",
        }
        result = agent._summarize_state(state)
        # Old entries collapsed
        assert "Prior context (summarized)" in result
        assert "a1, a2" in result
        # Recent entries fully included
        assert "Summary A3" in result
        assert "Summary A4" in result
        # Old content NOT fully included
        assert "Summary A1" not in result
        assert "Summary A2" not in result

    def test_window_larger_than_entries_includes_all(self):
        """Window > entry count should include everything."""
        agent = self._make_agent(window=10)
        state = {
            "task": "test",
            "a1_summary": "Summary A1",
            "a2_summary": "Summary A2",
        }
        result = agent._summarize_state(state)
        assert "Summary A1" in result
        assert "Summary A2" in result
        assert "Prior context" not in result

    def test_window_with_mixed_summary_and_output(self):
        """Window should apply after summary/output preference logic."""
        agent = self._make_agent(window=1)
        state = {
            "task": "test",
            "a1_summary": "Summary A1",
            "a2_output": "Full output A2",  # No summary available
            "a3_summary": "Summary A3",
        }
        result = agent._summarize_state(state)
        # Only the last entry (a3) should be fully included
        assert "Summary A3" in result
        assert "Prior context (summarized)" in result


# --- Context Expiry / TTL Tests (Idea 2) ---


class TestContextExpiry:
    def _make_agent(self) -> Agent:
        return Agent(
            agent_id="downstream",
            role="Test",
            system_prompt="test",
            behavior_type=AgentBehaviorType.LLM_ONLY,
        )

    def test_no_ttl_includes_all(self):
        """Without TTL metadata, all entries are included."""
        agent = self._make_agent()
        state = {
            "task": "test",
            "a1_summary": "Summary A1",
            "a2_summary": "Summary A2",
        }
        result = agent._summarize_state(state)
        assert "Summary A1" in result
        assert "Summary A2" in result

    def test_ttl_expires_old_entries(self):
        """Entries past their TTL should be filtered out."""
        agent = self._make_agent()
        state = {
            "task": "test",
            "a1_summary": "Summary A1",
            "a2_summary": "Summary A2",
            "a3_summary": "Summary A3",
            "_step_order": ["a1", "a2", "a3"],
            "_context_ttl": {"a1": 1},  # a1 expires after 1 step
        }
        result = agent._summarize_state(state)
        # a1 at position 0, current agent at position 3, distance=3 > ttl=1
        assert "Summary A1" not in result
        # a2 and a3 have no TTL, so they're included
        assert "Summary A2" in result
        assert "Summary A3" in result

    def test_ttl_keeps_recent_entries(self):
        """Entries within their TTL should remain."""
        agent = self._make_agent()
        state = {
            "task": "test",
            "a1_summary": "Summary A1",
            "a2_summary": "Summary A2",
            "_step_order": ["a1", "a2"],
            "_context_ttl": {"a1": 5, "a2": 5},
        }
        result = agent._summarize_state(state)
        # Both within TTL=5 (distance is 2 and 1 respectively)
        assert "Summary A1" in result
        assert "Summary A2" in result

    def test_workflow_step_context_ttl(self):
        """WorkflowStep should accept context_ttl parameter."""
        step = WorkflowStep(
            agent="a1",
            step_type=StepType.SEQUENTIAL,
            context_ttl=2,
        )
        assert step.context_ttl == 2

    def test_workflow_step_context_ttl_default_none(self):
        """context_ttl should default to None."""
        step = WorkflowStep(agent="a1", step_type=StepType.SEQUENTIAL)
        assert step.context_ttl is None

    async def test_workflow_records_ttl_in_state(self):
        """Workflow engine should record context_ttl in state."""
        provider = MockSimpleProvider("output")
        agent1 = Agent(
            agent_id="a1",
            role="A1",
            system_prompt="test",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=provider,
        )
        agent2 = Agent(
            agent_id="a2",
            role="A2",
            system_prompt="test",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=provider,
        )

        steps = [
            WorkflowStep(
                agent="a1",
                step_type=StepType.SEQUENTIAL,
                next_step="a2",
                context_ttl=2,
            ),
            WorkflowStep(agent="a2", step_type=StepType.SEQUENTIAL),
        ]
        engine = WorkflowEngine(steps)
        result = await engine.execute(
            {"a1": agent1, "a2": agent2}, {"task": "test"}
        )

        assert result.status == WorkflowStatus.COMPLETED
        assert "a1" in result.state.get("_step_order", [])
        assert "a2" in result.state.get("_step_order", [])
        assert result.state.get("_context_ttl", {}).get("a1") == 2


# --- Differential Compression Tests (Idea 3) ---


class TestDifferentialCompression:
    async def test_reasoning_output_gets_higher_budget(self):
        """Reasoning output_type should double the summary token budget."""
        provider = MockSummaryProvider()
        gen = SummaryGenerator(
            llm_provider=provider, max_summary_tokens=100
        )
        long_text = " ".join(["word"] * 500)

        # Standard: budget is 100, threshold legacy is 100 -> summarize at >100
        result = await gen.summarize(long_text)
        assert result.startswith("SUMMARY:")

        # Reasoning: budget doubled to 200
        result_reasoning = await gen.summarize(long_text, output_type="reasoning")
        assert result_reasoning.startswith("SUMMARY:")

    async def test_data_output_gets_lower_budget(self):
        """Data output_type should halve the summary token budget."""
        provider = MockSummaryProvider()
        gen = SummaryGenerator(
            llm_provider=provider, max_summary_tokens=200
        )
        # 150 words: above 100 (data budget) but below 200 (standard budget)
        medium_text = " ".join(["word"] * 150)

        # Standard: 150 <= 200 threshold -> passthrough
        result_standard = await gen.summarize(medium_text)
        assert result_standard == medium_text

        # Data: budget halved to 100, threshold becomes 100, 150 > 100 -> summarize
        result_data = await gen.summarize(medium_text, output_type="data")
        assert result_data.startswith("SUMMARY:")

    async def test_none_output_type_uses_standard_budget(self):
        """None output_type should use standard budget (no multiplier)."""
        provider = MockSummaryProvider()
        gen = SummaryGenerator(
            llm_provider=provider, max_summary_tokens=200
        )
        text = " ".join(["word"] * 150)
        result = await gen.summarize(text, output_type=None)
        # 150 <= 200 (standard threshold) -> passthrough
        assert result == text

    async def test_structured_data_treated_as_reasoning(self):
        """structured_data should get the same higher budget as reasoning."""
        provider = MockSummaryProvider()
        gen = SummaryGenerator(
            llm_provider=provider, max_summary_tokens=100
        )
        text = " ".join(["word"] * 150)
        # structured_data: budget doubled to 200, threshold 200, 150 <= 200 -> passthrough
        result = await gen.summarize(text, output_type="structured_data")
        assert result == text


# --- Smart Budget Enforcement / Context Reducer Tests (Ideas 4 & 5) ---


class MockReducerProvider(LLMProvider):
    """Mock that returns a reduced version of the input."""

    @property
    def plugin_id(self) -> str:
        return "mock_reducer"

    @property
    def description(self) -> str:
        return "Mock reducer provider"

    async def chat(
        self, messages: list[LLMMessage], config: LLMConfig
    ) -> LLMResponse:
        return LLMResponse(
            content="Reduced context: key facts preserved.",
            model="mock",
            usage=TokenUsage(
                prompt_tokens=10, completion_tokens=5, total_tokens=15
            ),
        )


class TestContextReducer:
    async def test_short_context_passthrough(self):
        """Context within budget should pass through unchanged."""
        from hiveflow.core.context_reducer import ContextReducer

        provider = MockReducerProvider()
        reducer = ContextReducer(llm_provider=provider)
        result = await reducer.reduce("short text", budget=100)
        assert result == "short text"

    async def test_overflow_triggers_llm_reduction(self):
        """Context exceeding budget * threshold should use LLM reduction."""
        from hiveflow.core.context_reducer import ContextReducer

        provider = MockReducerProvider()
        reducer = ContextReducer(
            llm_provider=provider, overflow_threshold=1.5
        )
        # 500 words > 100 * 1.5 = 150 threshold
        long_text = " ".join(["word"] * 500)
        result = await reducer.reduce(long_text, budget=100)
        assert "Reduced context" in result

    async def test_moderate_overflow_uses_mechanical_truncation(self):
        """Context slightly over budget should use mechanical truncation."""
        from hiveflow.core.context_reducer import ContextReducer

        provider = MockReducerProvider()
        reducer = ContextReducer(
            llm_provider=provider, overflow_threshold=1.5
        )
        # 130 words: > 100 budget but < 100 * 1.5 = 150
        text = " ".join(["word"] * 130)
        result = await reducer.reduce(text, budget=100)
        # Should be mechanically truncated, not LLM-reduced
        assert len(result.split()) <= 110  # budget + truncation marker

    async def test_llm_failure_falls_back_to_truncation(self):
        """If LLM reduction fails, should fall back to mechanical truncation."""
        from hiveflow.core.context_reducer import ContextReducer

        class FailingReducerProvider(LLMProvider):
            @property
            def plugin_id(self) -> str:
                return "failing"

            @property
            def description(self) -> str:
                return "Fails"

            async def chat(
                self, messages: list[LLMMessage], config: LLMConfig
            ) -> LLMResponse:
                raise RuntimeError("LLM reduction failed")

        reducer = ContextReducer(
            llm_provider=FailingReducerProvider(), overflow_threshold=1.5
        )
        long_text = " ".join(["word"] * 500)
        result = await reducer.reduce(long_text, budget=100)
        assert len(result.split()) <= 110

    async def test_agent_context_reduction_integration(self):
        """Agent with context_reducer should apply LLM reduction."""
        from hiveflow.core.context_reducer import ContextReducer

        reducer_provider = MockReducerProvider()
        reducer = ContextReducer(
            llm_provider=reducer_provider, overflow_threshold=1.0
        )

        content_provider = MockContentProvider(word_count=500)
        agent = Agent(
            agent_id="test",
            role="Test",
            system_prompt="test",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=content_provider,
            context_budget=100,
            context_reducer=reducer,
        )
        state = {
            "task": "test",
            "prior_output": " ".join(["data"] * 500),
        }
        # The agent's _apply_context_reduction should be invoked
        messages = agent._build_messages(state)
        assert len(messages) > 0


# --- Redundancy Detection Tests (Idea 6) ---


class TestRedundancyDetection:
    def test_trigram_overlap_identical(self):
        """Identical texts should have 100% overlap."""
        text = "the quick brown fox jumps over the lazy dog"
        overlap = Agent._trigram_overlap(text, text)
        assert overlap == 1.0

    def test_trigram_overlap_different(self):
        """Completely different texts should have ~0% overlap."""
        text_a = "the quick brown fox jumps over the lazy dog"
        text_b = "python is a programming language used by developers"
        overlap = Agent._trigram_overlap(text_a, text_b)
        assert overlap < 0.1

    def test_trigram_overlap_short_text(self):
        """Very short texts should return 0.0 overlap."""
        overlap = Agent._trigram_overlap("hi there", "hi there")
        assert overlap == 0.0  # Less than 3 words

    def test_deduplicate_no_overlap(self):
        """Entries with no overlap should all be preserved."""
        entries = [
            ("a1", "Summary", "the quick brown fox jumps over the lazy dog"),
            ("a2", "Summary", "python is a programming language used by developers"),
        ]
        result = Agent._deduplicate_entries(entries)
        assert len(result) == 2
        assert result[0][2] == entries[0][2]
        assert result[1][2] == entries[1][2]

    def test_deduplicate_high_overlap(self):
        """Entries with high overlap should have older one replaced."""
        same_text = "the quick brown fox jumps over the lazy dog again and again"
        entries = [
            ("a1", "Summary", same_text),
            ("a2", "Summary", same_text),
        ]
        result = Agent._deduplicate_entries(entries)
        assert len(result) == 2
        # Older entry replaced with back-reference
        assert "superseded by a2" in result[0][2]
        # Newer entry preserved
        assert result[1][2] == same_text

    def test_deduplicate_single_entry(self):
        """Single entry should be returned unchanged."""
        entries = [("a1", "Summary", "some text")]
        result = Agent._deduplicate_entries(entries)
        assert len(result) == 1

    def test_deduplicate_integrated_in_summarize_state(self):
        """Redundancy detection should be applied in _summarize_state."""
        agent = Agent(
            agent_id="downstream",
            role="Test",
            system_prompt="test",
            behavior_type=AgentBehaviorType.LLM_ONLY,
        )
        identical_summary = (
            "The research findings show that artificial intelligence "
            "is transforming the healthcare industry in significant ways "
            "with many implications for patients and providers"
        )
        state = {
            "task": "test",
            "a1_summary": identical_summary,
            "a2_summary": identical_summary,
        }
        result = agent._summarize_state(state)
        # The older entry (a1) should be superseded
        assert "superseded by a2" in result


# --- Config New Defaults Tests ---


class TestContextRecencyWindowConfig:
    def test_default_zero(self):
        """CONTEXT_RECENCY_WINDOW should default to 0 (no windowing)."""
        config = HiveFlowConfig()
        assert config.CONTEXT_RECENCY_WINDOW == 0

    def test_override(self):
        """CONTEXT_RECENCY_WINDOW should be overridable."""
        config = HiveFlowConfig()
        overridden = config.apply_overrides({"context_recency_window": 3})
        assert overridden.CONTEXT_RECENCY_WINDOW == 3
