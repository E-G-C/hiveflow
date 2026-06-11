"""Tests for Universal Agent, Workflow Engine, and Plugin Architecture."""

import pytest

from hiveflow.core.agent import Agent, AgentBehaviorType
from hiveflow.core.registry import PluginRegistry
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
    LLMProviderRegistry,
    LLMResponse,
    TokenUsage,
)
from hiveflow.plugins.tools import ToolPlugin, ToolRegistry

# --- Mock Implementations ---


class MockLLMProvider(LLMProvider):
    """Mock LLM provider for testing."""

    def __init__(self, responses: list[str] | None = None) -> None:
        self._responses = responses or ["Mock LLM response"]
        self._call_count = 0

    @property
    def plugin_id(self) -> str:
        return "mock"

    @property
    def description(self) -> str:
        return "Mock provider for testing"

    @property
    def supports_streaming(self) -> bool:
        return True

    @property
    def supports_function_calling(self) -> bool:
        return True

    async def chat(self, messages: list[LLMMessage], config: LLMConfig) -> LLMResponse:
        idx = min(self._call_count, len(self._responses) - 1)
        content = self._responses[idx]
        self._call_count += 1
        return LLMResponse(
            content=content,
            model="mock-model",
            usage=TokenUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
        )


class MockToolPlugin(ToolPlugin):
    """Mock tool plugin for testing."""

    def __init__(self, tool_id: str = "mock_tool", result: dict | None = None) -> None:
        self._tool_id = tool_id
        self._result = result or {"data": "mock result"}

    @property
    def plugin_id(self) -> str:
        return self._tool_id

    @property
    def description(self) -> str:
        return f"Mock tool: {self._tool_id}"

    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {"query": {"type": "string"}}}

    @property
    def output_schema(self) -> dict:
        return {"type": "object", "properties": {"data": {"type": "string"}}}

    async def execute(self, tool_input: dict) -> dict:
        return self._result


# --- Plugin Registry Tests ---


class TestPluginRegistry:
    def test_register_and_get(self):
        registry = PluginRegistry[MockToolPlugin](
            entry_point_group="test.tools", drop_in_dir=None
        )
        tool = MockToolPlugin("test_tool")
        registry.register(tool)

        assert registry.get("test_tool") is tool
        assert len(registry) == 1
        assert "test_tool" in registry

    def test_get_or_raise_not_found(self):
        registry = PluginRegistry[MockToolPlugin](
            entry_point_group="test.tools", drop_in_dir=None
        )
        with pytest.raises(KeyError, match="not found"):
            registry.get_or_raise("nonexistent")

    def test_list_ids(self):
        registry = PluginRegistry[MockToolPlugin](
            entry_point_group="test.tools", drop_in_dir=None
        )
        registry.register(MockToolPlugin("tool_b"))
        registry.register(MockToolPlugin("tool_a"))

        assert registry.list_ids() == ["tool_a", "tool_b"]

    def test_discover_with_no_dir(self):
        registry = PluginRegistry[MockToolPlugin](
            entry_point_group="test.nonexistent", drop_in_dir=None
        )
        registry.discover()
        assert len(registry) == 0


# --- Tool Registry Tests ---


class TestToolRegistry:
    def test_get_tools_for_agent(self):
        registry = ToolRegistry(drop_in_dir=None)
        tool1 = MockToolPlugin("search")
        tool2 = MockToolPlugin("scraper")
        registry.register(tool1)
        registry.register(tool2)

        tools = registry.get_tools_for_agent(["search", "scraper"])
        assert len(tools) == 2
        assert tools[0].plugin_id == "search"
        assert tools[1].plugin_id == "scraper"

    def test_get_tools_missing(self):
        registry = ToolRegistry(drop_in_dir=None)
        with pytest.raises(KeyError):
            registry.get_tools_for_agent(["nonexistent"])

    def test_get_llm_tool_specs(self):
        registry = ToolRegistry(drop_in_dir=None)
        tool = MockToolPlugin("search")
        registry.register(tool)

        specs = registry.get_llm_tool_specs(["search"])
        assert len(specs) == 1
        assert specs[0]["type"] == "function"
        assert specs[0]["function"]["name"] == "search"


# --- LLM Provider Registry Tests ---


class TestLLMProviderRegistry:
    def test_resolve_model(self):
        registry = LLMProviderRegistry(drop_in_dir=None)
        provider = MockLLMProvider()
        registry.register(provider)

        resolved_provider, model = registry.resolve_model("mock:gpt-test")
        assert resolved_provider is provider
        assert model == "gpt-test"

    def test_resolve_model_invalid_format(self):
        registry = LLMProviderRegistry(drop_in_dir=None)
        with pytest.raises(ValueError, match="Invalid model reference"):
            registry.resolve_model("no-colon-format")


# --- Tool Plugin Tests ---


class TestToolPlugin:
    def test_to_llm_tool_spec(self):
        tool = MockToolPlugin("web_search")
        spec = tool.to_llm_tool_spec()

        assert spec["type"] == "function"
        assert spec["function"]["name"] == "web_search"
        assert "parameters" in spec["function"]
        assert "description" in spec["function"]

    async def test_execute(self):
        tool = MockToolPlugin("test", result={"answer": 42})
        result = await tool.execute({"query": "test"})
        assert result == {"answer": 42}


# --- Agent Tests ---


class TestAgent:
    async def test_llm_only_execution(self):
        provider = MockLLMProvider(["Hello from the agent!"])
        agent = Agent(
            agent_id="test_agent",
            role="Test Agent",
            system_prompt="You are a test agent.",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=provider,
        )

        result = await agent.execute({"task": "Say hello"})
        assert "test_agent_output" in result
        assert result["test_agent_output"] == "Hello from the agent!"
        assert result["test_agent_usage"]["total_tokens"] == 30

    async def test_human_gate_no_input(self):
        agent = Agent(
            agent_id="human",
            role="Human Gate",
            system_prompt="",
            behavior_type=AgentBehaviorType.HUMAN_GATE,
        )

        result = await agent.execute({"task": "Review this"})
        assert result["awaiting_human_input"] is True

    async def test_human_gate_with_input(self):
        agent = Agent(
            agent_id="human",
            role="Human Gate",
            system_prompt="",
            behavior_type=AgentBehaviorType.HUMAN_GATE,
        )

        result = await agent.execute({"task": "Review", "human_input": "Approved!"})
        assert result["human_approved"] is True
        assert result["human_output"] == "Approved!"

    async def test_no_provider_raises(self):
        agent = Agent(
            agent_id="test",
            role="Test",
            system_prompt="test",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            model="gpt-4o",
        )

        with pytest.raises(RuntimeError, match="no LLM provider"):
            await agent.execute({"task": "test"})

    def test_provider_model_auto_resolves_provider(self):
        agent = Agent(
            agent_id="test",
            role="Test",
            system_prompt="test",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            model="perplexity:sonar-pro",
        )

        assert agent.llm_provider is not None
        assert agent.llm_provider._fallback_chain._providers[0][0].provider_id == "perplexity"

    def test_build_config_resolves_tier_variable(self):
        agent = Agent(
            agent_id="test",
            role="Test",
            system_prompt="test",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            model="$SMART_LLM",
            llm_provider=MockLLMProvider(),
        )

        assert agent._build_config().model == "gpt-4o"

    def test_from_definition(self):
        from hiveflow.core.schema import AgentBehaviorTypeSchema, AgentDefinition

        definition = AgentDefinition(
            id="researcher",
            role="Deep Researcher",
            system_prompt="You research things.",
            behavior_type=AgentBehaviorTypeSchema.TOOL_USER,
            tools=["web_search"],
            model="openai:gpt-4o",
        )

        provider = MockLLMProvider()
        tool = MockToolPlugin("web_search")
        agent = Agent.from_definition(
            definition, llm_provider=provider, tools=[tool]
        )

        assert agent.agent_id == "researcher"
        assert agent.behavior_type == AgentBehaviorType.TOOL_USER
        assert len(agent.tools) == 1


# --- Workflow Engine Tests ---


class TestWorkflowEngine:
    async def test_empty_workflow(self):
        engine = WorkflowEngine([])
        result = await engine.execute({}, {"task": "test"})
        assert result.status == WorkflowStatus.COMPLETED
        assert len(result.step_results) == 0

    async def test_sequential_workflow(self):
        provider = MockLLMProvider(["Step 1 output", "Step 2 output"])

        agent1 = Agent(
            agent_id="agent1",
            role="Agent 1",
            system_prompt="You are agent 1.",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=provider,
        )
        agent2 = Agent(
            agent_id="agent2",
            role="Agent 2",
            system_prompt="You are agent 2.",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=provider,
        )

        steps = [
            WorkflowStep(agent="agent1", step_type=StepType.SEQUENTIAL, next_step="agent2"),
            WorkflowStep(agent="agent2", step_type=StepType.SEQUENTIAL),
        ]

        engine = WorkflowEngine(steps)
        result = await engine.execute(
            {"agent1": agent1, "agent2": agent2},
            {"task": "test"},
        )

        assert result.status == WorkflowStatus.COMPLETED
        assert len(result.step_results) == 2
        assert "agent1_output" in result.state
        assert "agent2_output" in result.state

    async def test_conditional_accept(self):
        provider = MockLLMProvider(["This is approved and satisfactory"])

        reviewer = Agent(
            agent_id="reviewer",
            role="Reviewer",
            system_prompt="Review content.",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=provider,
        )
        writer = Agent(
            agent_id="writer",
            role="Writer",
            system_prompt="Write content.",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=provider,
        )

        steps = [
            WorkflowStep(
                agent="reviewer",
                step_type=StepType.CONDITIONAL,
                next_on_accept="writer",
                next_on_reject=None,
            ),
            WorkflowStep(agent="writer", step_type=StepType.SEQUENTIAL),
        ]

        engine = WorkflowEngine(steps)
        result = await engine.execute(
            {"reviewer": reviewer, "writer": writer},
            {"task": "review and write"},
        )

        assert result.status == WorkflowStatus.COMPLETED
        assert len(result.step_results) == 2

    async def test_conditional_reject(self):
        provider = MockLLMProvider([
            "This needs revision and is insufficient",
            "Revised content",
        ])

        reviewer = Agent(
            agent_id="reviewer",
            role="Reviewer",
            system_prompt="Review.",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=provider,
        )
        reviser = Agent(
            agent_id="reviser",
            role="Reviser",
            system_prompt="Revise.",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=MockLLMProvider(["Revised version"]),
        )

        steps = [
            WorkflowStep(
                agent="reviewer",
                step_type=StepType.CONDITIONAL,
                next_on_accept=None,
                next_on_reject="reviser",
            ),
            WorkflowStep(agent="reviser", step_type=StepType.SEQUENTIAL),
        ]

        engine = WorkflowEngine(steps)
        result = await engine.execute(
            {"reviewer": reviewer, "reviser": reviser},
            {"task": "review"},
        )

        assert result.status == WorkflowStatus.COMPLETED
        assert "reviser_output" in result.state

    async def test_missing_agent_fails(self):
        steps = [
            WorkflowStep(agent="nonexistent", step_type=StepType.SEQUENTIAL),
        ]

        engine = WorkflowEngine(steps)
        result = await engine.execute({}, {"task": "test"})
        assert result.status == WorkflowStatus.FAILED
        assert "not found" in result.error

    async def test_human_gate_pauses(self):
        agent = Agent(
            agent_id="human",
            role="Human",
            system_prompt="",
            behavior_type=AgentBehaviorType.HUMAN_GATE,
        )

        steps = [
            WorkflowStep(agent="human", step_type=StepType.HUMAN_GATE),
        ]

        engine = WorkflowEngine(steps)
        result = await engine.execute({"human": agent}, {"task": "review"})
        assert result.status == WorkflowStatus.PAUSED

    async def test_event_callbacks(self):
        events = []

        def callback(event_type, agent_id, data):
            events.append((event_type, agent_id))

        provider = MockLLMProvider(["output"])
        agent = Agent(
            agent_id="agent1",
            role="Agent",
            system_prompt="test",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=provider,
        )

        steps = [WorkflowStep(agent="agent1", step_type=StepType.SEQUENTIAL)]
        engine = WorkflowEngine(steps)
        engine.on_event(callback)

        await engine.execute({"agent1": agent}, {"task": "test"})

        assert ("step_start", "agent1") in events
        assert ("step_complete", "agent1") in events

    async def test_from_schema(self):
        from hiveflow.core.schema import WorkflowGraph, WorkflowStepDefinition, WorkflowStepType

        graph = WorkflowGraph(
            steps=[
                WorkflowStepDefinition(
                    agent="agent1",
                    type=WorkflowStepType.SEQUENTIAL,
                    next="agent2",
                ),
                WorkflowStepDefinition(
                    agent="agent2",
                    type=WorkflowStepType.SEQUENTIAL,
                ),
            ]
        )

        engine = WorkflowEngine.from_schema(graph)
        assert len(engine.steps) == 2
        assert engine.steps[0].agent == "agent1"
        assert engine.steps[0].next_step == "agent2"

    async def test_max_conditional_loops(self):
        provider = MockLLMProvider(["needs revision"] * 10)

        reviewer = Agent(
            agent_id="reviewer",
            role="Reviewer",
            system_prompt="Review.",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=provider,
        )
        reviser = Agent(
            agent_id="reviser",
            role="Reviser",
            system_prompt="Revise.",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=MockLLMProvider(["revised"]),
        )

        steps = [
            WorkflowStep(
                agent="reviewer",
                step_type=StepType.CONDITIONAL,
                next_on_accept=None,
                next_on_reject="reviser",
            ),
            WorkflowStep(
                agent="reviser",
                step_type=StepType.SEQUENTIAL,
                next_step="reviewer",
            ),
        ]

        engine = WorkflowEngine(steps, max_conditional_loops=3)
        result = await engine.execute(
            {"reviewer": reviewer, "reviser": reviser},
            {"task": "review loop"},
        )

        # Should fail after max_conditional_loops exceeded (changed from forced accept)
        assert result.status == WorkflowStatus.FAILED
        assert "exceeded maximum iterations" in result.error


# ---------------------------------------------------------------------------
# PublishConfig
# ---------------------------------------------------------------------------


class TestPublishConfig:
    """Tests for PublishConfig Pydantic model."""

    def test_default_values(self) -> None:
        from hiveflow.core.schema import PublishConfig
        config = PublishConfig()
        assert config.formats == []
        assert config.layout == "default"
        assert config.style is None
        assert config.output_dir == "./output"
        assert config.filename == "output"

    def test_custom_values(self) -> None:
        from hiveflow.core.schema import PublishConfig
        config = PublishConfig(
            formats=["pdf", "docx"],
            layout="executive-brief",
            style="apa",
            output_dir="./reports",
            filename="report",
        )
        assert config.formats == ["pdf", "docx"]
        assert config.layout == "executive-brief"
        assert config.style == "apa"
        assert config.output_dir == "./reports"
        assert config.filename == "report"

    def test_team_config_with_publish(self) -> None:
        from hiveflow.core.schema import TeamConfiguration
        config_data = {
            "team_name": "test_team",
            "description": "A test team",
            "agents": [{
                "id": "agent1",
                "role": "Test Agent",
                "system_prompt": "You are a test agent.",
                "behavior_type": "llm_only",
            }],
            "workflow": {
                "steps": [{
                    "agent": "agent1",
                    "type": "sequential",
                }],
            },
            "publish": {
                "formats": ["markdown", "pdf"],
                "layout": "default",
                "output_dir": "./output",
            },
        }
        team = TeamConfiguration(**config_data)
        assert team.publish is not None
        assert team.publish.formats == ["markdown", "pdf"]
        assert team.publish.filename == "output"

    def test_team_config_without_publish(self) -> None:
        from hiveflow.core.schema import TeamConfiguration
        config_data = {
            "team_name": "test_team",
            "description": "A test team",
            "agents": [{
                "id": "agent1",
                "role": "Test Agent",
                "system_prompt": "You are a test agent.",
                "behavior_type": "llm_only",
            }],
            "workflow": {
                "steps": [{
                    "agent": "agent1",
                    "type": "sequential",
                }],
            },
        }
        team = TeamConfiguration(**config_data)
        assert team.publish is None


class TestExecuteAgentWithFailurePolicy:
    """Tests for WorkflowEngine._execute_agent_with_failure_policy (T012)."""

    @pytest.mark.asyncio
    async def test_on_failure_fail_halts_workflow(self):
        """on_failure='fail' should re-raise the exception."""
        from unittest.mock import AsyncMock, MagicMock, patch

        engine = WorkflowEngine([WorkflowStep(agent="test", step_type="sequential")])
        agent = MagicMock(spec=Agent)
        agent.agent_id = "test"
        agent.agent_definition = MagicMock()
        agent.agent_definition.on_failure = "fail"
        agent.agent_definition.max_retries = 1

        with patch.object(engine, "_execute_agent", new_callable=AsyncMock, side_effect=RuntimeError("Agent failed")):
            with pytest.raises(RuntimeError, match="Agent failed"):
                await engine._execute_agent_with_failure_policy(agent, {"task": "x"})

    @pytest.mark.asyncio
    async def test_on_failure_none_defaults_to_fail(self):
        """on_failure=None should default to fail behavior (re-raise)."""
        from unittest.mock import AsyncMock, MagicMock, patch

        engine = WorkflowEngine([WorkflowStep(agent="test", step_type="sequential")])
        agent = MagicMock(spec=Agent)
        agent.agent_id = "test"
        agent.agent_definition = MagicMock()
        agent.agent_definition.on_failure = None
        agent.agent_definition.max_retries = 1

        with patch.object(engine, "_execute_agent", new_callable=AsyncMock, side_effect=RuntimeError("Boom")):
            with pytest.raises(RuntimeError, match="Boom"):
                await engine._execute_agent_with_failure_policy(agent, {"task": "x"})

    @pytest.mark.asyncio
    async def test_on_failure_retry_retries_up_to_max(self):
        """on_failure='retry' should retry up to max_retries then raise."""
        from unittest.mock import AsyncMock, MagicMock, patch

        engine = WorkflowEngine([WorkflowStep(agent="test", step_type="sequential")])
        agent = MagicMock(spec=Agent)
        agent.agent_id = "test"
        agent.agent_definition = MagicMock()
        agent.agent_definition.on_failure = "retry"
        agent.agent_definition.max_retries = 3

        call_count = 0

        async def fail_execute(a, s):
            nonlocal call_count
            call_count += 1
            raise ValueError("Persistent failure")

        with patch.object(engine, "_execute_agent", side_effect=fail_execute):
            with pytest.raises(ValueError, match="Persistent failure"):
                await engine._execute_agent_with_failure_policy(agent, {"task": "x"})

        assert call_count == 3  # max_retries = 3 attempts

    @pytest.mark.asyncio
    async def test_on_failure_retry_succeeds_eventually(self):
        """on_failure='retry' should succeed if a retry works."""
        from unittest.mock import AsyncMock, MagicMock, patch

        engine = WorkflowEngine([WorkflowStep(agent="test", step_type="sequential")])
        agent = MagicMock(spec=Agent)
        agent.agent_id = "test"
        agent.agent_definition = MagicMock()
        agent.agent_definition.on_failure = "retry"
        agent.agent_definition.max_retries = 3

        call_count = 0

        async def fail_then_succeed(a, s):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("Transient")
            return {**s, "done": True}

        with patch.object(engine, "_execute_agent", side_effect=fail_then_succeed):
            result = await engine._execute_agent_with_failure_policy(agent, {"task": "x"})

        assert result["done"] is True
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_on_failure_skip_returns_state_unmodified(self):
        """on_failure='skip' should return state unmodified on error."""
        from unittest.mock import AsyncMock, MagicMock, patch

        engine = WorkflowEngine([WorkflowStep(agent="test", step_type="sequential")])
        agent = MagicMock(spec=Agent)
        agent.agent_id = "test"
        agent.agent_definition = MagicMock()
        agent.agent_definition.on_failure = "skip"
        agent.agent_definition.max_retries = 1

        original_state = {"task": "x", "existing_data": "keep"}

        with patch.object(engine, "_execute_agent", new_callable=AsyncMock, side_effect=RuntimeError("Skip me")):
            result = await engine._execute_agent_with_failure_policy(agent, original_state)

        assert result is original_state

    @pytest.mark.asyncio
    async def test_on_failure_skip_succeeds_when_no_error(self):
        """on_failure='skip' should return result normally when no error."""
        from unittest.mock import AsyncMock, MagicMock, patch

        engine = WorkflowEngine([WorkflowStep(agent="test", step_type="sequential")])
        agent = MagicMock(spec=Agent)
        agent.agent_id = "test"
        agent.agent_definition = MagicMock()
        agent.agent_definition.on_failure = "skip"
        agent.agent_definition.max_retries = 1

        async def succeed(a, s):
            return {**s, "done": True}

        with patch.object(engine, "_execute_agent", side_effect=succeed):
            result = await engine._execute_agent_with_failure_policy(agent, {"task": "x"})

        assert result["done"] is True

    @pytest.mark.asyncio
    async def test_no_agent_definition_defaults_to_fail(self):
        """Agent with no agent_definition should default to fail behavior."""
        from unittest.mock import AsyncMock, MagicMock, patch

        engine = WorkflowEngine([WorkflowStep(agent="test", step_type="sequential")])
        agent = MagicMock(spec=Agent)
        agent.agent_id = "test"
        agent.agent_definition = None

        with patch.object(engine, "_execute_agent", new_callable=AsyncMock, side_effect=RuntimeError("No def")):
            with pytest.raises(RuntimeError, match="No def"):
                await engine._execute_agent_with_failure_policy(agent, {"task": "x"})


# ---------------------------------------------------------------------------
# T037 – Sub-workflow execution guards
# ---------------------------------------------------------------------------


class TestSubWorkflow:
    """Tests for WorkflowEngine._execute_sub_workflow (T037)."""

    @pytest.mark.asyncio
    async def test_recursion_depth_exceeds_max_raises(self):
        """_depth >= 5 must raise RuntimeError."""
        from unittest.mock import MagicMock

        engine = WorkflowEngine([WorkflowStep(agent="inner", step_type="sub_workflow")])
        engine._team_library = MagicMock()

        step = WorkflowStep(agent="inner", step_type="sub_workflow")
        step.team = "some_team"

        with pytest.raises(RuntimeError, match="recursion depth exceeded"):
            await engine._execute_sub_workflow(step, {}, {}, _depth=5)

    @pytest.mark.asyncio
    async def test_recursion_depth_6_also_raises(self):
        """_depth > 5 must also raise RuntimeError."""
        from unittest.mock import MagicMock

        engine = WorkflowEngine([WorkflowStep(agent="inner", step_type="sub_workflow")])
        engine._team_library = MagicMock()

        step = WorkflowStep(agent="inner", step_type="sub_workflow")
        step.team = "some_team"

        with pytest.raises(RuntimeError, match="recursion depth exceeded"):
            await engine._execute_sub_workflow(step, {}, {}, _depth=6)

    @pytest.mark.asyncio
    async def test_no_team_library_raises(self):
        """Missing TeamLibrary must raise RuntimeError."""
        engine = WorkflowEngine([WorkflowStep(agent="inner", step_type="sub_workflow")])
        # _team_library defaults to None

        step = WorkflowStep(agent="inner", step_type="sub_workflow")
        step.team = "some_team"

        with pytest.raises(RuntimeError, match="no TeamLibrary configured"):
            await engine._execute_sub_workflow(step, {}, {})
