"""Tests for action_executor agent behavior and gated workflow steps."""

import json

import pytest

from hiveflow.core.agent import Agent, AgentBehaviorType
from hiveflow.core.workflow import (
    StepType,
    WorkflowEngine,
    WorkflowStatus,
    WorkflowStep,
)
from hiveflow.plugins.llm import LLMConfig, LLMMessage, LLMProvider, LLMResponse, TokenUsage


class MockToolPlugin:
    """Minimal tool plugin mock for testing."""

    def __init__(self, plugin_id: str, result: dict | None = None):
        self.plugin_id = plugin_id
        self._result = result or {"status": "done"}

    def to_llm_tool_spec(self):
        return {
            "type": "function",
            "function": {
                "name": self.plugin_id,
                "description": f"Test tool {self.plugin_id}",
                "parameters": {"type": "object", "properties": {}},
            },
        }

    async def execute(self, args):
        return self._result


class MockLLMProviderWithToolCalls(LLMProvider):
    """LLM provider that returns tool calls on first call, then a final response."""

    def __init__(self, tool_name: str = "send_email", final_content: str = "Done"):
        self._call_count = 0
        self._tool_name = tool_name
        self._final_content = final_content

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def plugin_id(self) -> str:
        return "mock_tool_llm"

    @property
    def description(self) -> str:
        return "Mock LLM with tool calls"

    async def chat(self, messages: list[LLMMessage], config: LLMConfig) -> LLMResponse:
        self._call_count += 1
        if self._call_count == 1:
            # First call: propose tool call
            return LLMResponse(
                content="I'll send the email now.",
                model="mock-model",
                tool_calls=[{
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": self._tool_name,
                        "arguments": json.dumps({"to": "user@example.com"}),
                    },
                }],
                usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            )
        else:
            # Subsequent calls: final response
            return LLMResponse(
                content=self._final_content,
                model="mock-model",
                tool_calls=None,
                usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            )


class MockLLMProvider(LLMProvider):
    """Simple mock that returns fixed text responses."""

    def __init__(self, responses: list[str]):
        self._responses = responses
        self._idx = 0

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def plugin_id(self) -> str:
        return "mock_simple"

    @property
    def description(self) -> str:
        return "Mock LLM provider"

    async def chat(self, messages: list[LLMMessage], config: LLMConfig) -> LLMResponse:
        r = self._responses[self._idx % len(self._responses)]
        self._idx += 1
        return LLMResponse(
            content=r,
            model="mock-model",
            tool_calls=None,
            usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )


class TestActionExecutorAutoPolicy:
    """Tests for action_executor with auto policy."""

    @pytest.mark.asyncio
    async def test_auto_executes_tools_immediately(self):
        """auto policy should execute tools without pausing."""
        tool = MockToolPlugin("send_email", {"sent": True})
        provider = MockLLMProviderWithToolCalls("send_email", "Email sent!")

        agent = Agent(
            agent_id="emailer",
            role="Email Sender",
            system_prompt="Send emails.",
            behavior_type=AgentBehaviorType.ACTION_EXECUTOR,
            tools=[tool],
            llm_provider=provider,
            action_policy="auto",
        )

        result = await agent.execute({"task": "Send welcome email"})

        assert "emailer_output" in result
        assert "emailer_action_records" in result
        assert len(result["emailer_action_records"]) == 1
        record = result["emailer_action_records"][0]
        assert record["tool"] == "send_email"
        assert record["status"] == "success"
        assert record["agent_id"] == "emailer"
        assert "awaiting_action_approval" not in result

    @pytest.mark.asyncio
    async def test_auto_records_audit_trail(self):
        """auto policy should record structured audit entries."""
        tool = MockToolPlugin("deploy", {"deployed": True})
        provider = MockLLMProviderWithToolCalls("deploy", "Deployed!")

        agent = Agent(
            agent_id="deployer",
            role="Deployer",
            system_prompt="Deploy apps.",
            behavior_type=AgentBehaviorType.ACTION_EXECUTOR,
            tools=[tool],
            llm_provider=provider,
            action_policy="auto",
        )

        result = await agent.execute({"task": "Deploy to production"})

        records = result["deployer_action_records"]
        assert len(records) == 1
        record = records[0]
        assert "agent_id" in record
        assert "tool" in record
        assert "arguments" in record
        assert "result" in record
        assert "status" in record


class TestActionExecutorRequireApproval:
    """Tests for action_executor with require_approval policy."""

    @pytest.mark.asyncio
    async def test_require_approval_pauses_workflow(self):
        """require_approval should pause and surface proposed actions."""
        tool = MockToolPlugin("send_email")
        provider = MockLLMProviderWithToolCalls("send_email")

        agent = Agent(
            agent_id="emailer",
            role="Email Sender",
            system_prompt="Send emails.",
            behavior_type=AgentBehaviorType.ACTION_EXECUTOR,
            tools=[tool],
            llm_provider=provider,
            action_policy="require_approval",
        )

        result = await agent.execute({"task": "Send welcome email"})

        assert result.get("awaiting_action_approval") is True
        assert "emailer_proposed_actions" in result
        actions = result["emailer_proposed_actions"]
        assert len(actions) == 1
        assert actions[0]["tool"] == "send_email"
        assert "emailer_action_records" not in result

    @pytest.mark.asyncio
    async def test_require_approval_surfaces_arguments(self):
        """require_approval should include tool arguments in proposed actions."""
        tool = MockToolPlugin("send_email")
        provider = MockLLMProviderWithToolCalls("send_email")

        agent = Agent(
            agent_id="emailer",
            role="Email Sender",
            system_prompt="Send emails.",
            behavior_type=AgentBehaviorType.ACTION_EXECUTOR,
            tools=[tool],
            llm_provider=provider,
            action_policy="require_approval",
        )

        result = await agent.execute({"task": "Send welcome email"})

        actions = result["emailer_proposed_actions"]
        assert actions[0]["arguments"] == {"to": "user@example.com"}


class TestGatedWorkflowStep:
    """Tests for gated step type in workflow engine."""

    @pytest.mark.asyncio
    async def test_gated_step_pauses_workflow(self):
        """Gated step should pause the workflow without executing an agent."""
        writer_provider = MockLLMProvider(["Draft content"])
        writer = Agent(
            agent_id="writer",
            role="Writer",
            system_prompt="Write.",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=writer_provider,
        )

        steps = [
            WorkflowStep(
                agent="writer",
                step_type=StepType.SEQUENTIAL,
                next_step="approval_gate",
            ),
            WorkflowStep(
                agent="approval_gate",
                step_type=StepType.GATED,
                gate_id="approval_gate",
                gate_description="Review draft before publishing",
            ),
        ]

        engine = WorkflowEngine(steps)
        result = await engine.execute({"writer": writer}, {"task": "Write a post"})

        assert result.status == WorkflowStatus.PAUSED
        assert result.state.get("awaiting_gate_approval") is True
        assert result.state.get("pending_gate_id") == "approval_gate"

    @pytest.mark.asyncio
    async def test_action_executor_pauses_in_workflow(self):
        """action_executor with require_approval should pause the workflow."""
        tool = MockToolPlugin("send_email")
        provider = MockLLMProviderWithToolCalls("send_email")

        emailer = Agent(
            agent_id="emailer",
            role="Email Sender",
            system_prompt="Send emails.",
            behavior_type=AgentBehaviorType.ACTION_EXECUTOR,
            tools=[tool],
            llm_provider=provider,
            action_policy="require_approval",
        )

        steps = [
            WorkflowStep(
                agent="emailer",
                step_type=StepType.SEQUENTIAL,
            ),
        ]

        engine = WorkflowEngine(steps)
        result = await engine.execute({"emailer": emailer}, {"task": "Send email"})

        assert result.status == WorkflowStatus.PAUSED
        assert result.state.get("awaiting_action_approval") is True


class TestConditionalLoopFailure:
    """Tests for conditional loop iteration limits and failure behavior."""

    @pytest.mark.asyncio
    async def test_per_step_max_iterations(self):
        """Per-step max_iterations should override global."""
        provider = MockLLMProvider(["needs revision"] * 20)

        reviewer = Agent(
            agent_id="reviewer",
            role="Reviewer",
            system_prompt="Review.",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=provider,
        )
        writer = Agent(
            agent_id="writer",
            role="Writer",
            system_prompt="Write.",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=MockLLMProvider(["content"]),
        )

        steps = [
            WorkflowStep(
                agent="reviewer",
                step_type=StepType.CONDITIONAL,
                next_on_accept=None,
                next_on_reject="writer",
                max_iterations=2,  # Override global
            ),
            WorkflowStep(
                agent="writer",
                step_type=StepType.SEQUENTIAL,
                next_step="reviewer",
            ),
        ]

        engine = WorkflowEngine(steps, max_conditional_loops=10)  # Global is higher
        result = await engine.execute(
            {"reviewer": reviewer, "writer": writer},
            {"task": "review"},
        )

        assert result.status == WorkflowStatus.FAILED
        assert "exceeded maximum iterations (2)" in result.error

    @pytest.mark.asyncio
    async def test_conditional_loop_fails_with_error(self):
        """Exceeding max iterations should fail with descriptive error."""
        provider = MockLLMProvider(["rejected, needs revision"] * 10)

        reviewer = Agent(
            agent_id="reviewer",
            role="Reviewer",
            system_prompt="Review.",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=provider,
        )
        writer = Agent(
            agent_id="writer",
            role="Writer",
            system_prompt="Write.",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=MockLLMProvider(["revised content"]),
        )

        steps = [
            WorkflowStep(
                agent="reviewer",
                step_type=StepType.CONDITIONAL,
                next_on_accept=None,
                next_on_reject="writer",
                max_iterations=3,
            ),
            WorkflowStep(
                agent="writer",
                step_type=StepType.SEQUENTIAL,
                next_step="reviewer",
            ),
        ]

        engine = WorkflowEngine(steps)
        result = await engine.execute(
            {"reviewer": reviewer, "writer": writer},
            {"task": "review"},
        )

        assert result.status == WorkflowStatus.FAILED
        assert "reviewer" in result.error
        assert "exceeded maximum iterations" in result.error


class MockFailingToolPlugin:
    """Tool plugin that raises an exception on execute."""

    def __init__(self, plugin_id: str, error_msg: str = "Tool execution failed"):
        self.plugin_id = plugin_id
        self._error_msg = error_msg

    def to_llm_tool_spec(self):
        return {
            "type": "function",
            "function": {
                "name": self.plugin_id,
                "description": f"Failing tool {self.plugin_id}",
                "parameters": {"type": "object", "properties": {}},
            },
        }

    async def execute(self, args):
        raise RuntimeError(self._error_msg)


class TestDryRunPolicy:
    """Tests for dry_run action policy (T027)."""

    @pytest.mark.asyncio
    async def test_dry_run_records_actions_without_executing(self):
        """dry_run should record proposed actions with status='dry_run' but NOT execute tools."""
        tool = MockToolPlugin("send_email")
        llm = MockLLMProviderWithToolCalls(tool_name="send_email")

        agent = Agent(
            agent_id="mailer",
            role="Email Sender",
            system_prompt="Send emails.",
            behavior_type=AgentBehaviorType.ACTION_EXECUTOR,
            tools=[tool],
            llm_provider=llm,
            action_policy="dry_run",
        )

        state = await agent.execute({"task": "send email"})

        # Tool should NOT have been executed (LLM only called once for dry_run)
        assert llm._call_count == 1

        # dry_run_plan should be populated
        plan = state.get("mailer_dry_run_plan")
        assert plan is not None
        assert len(plan) == 1
        assert plan[0]["tool"] == "send_email"

        # Action records should have status="dry_run"
        records = state.get("mailer_action_records", [])
        assert len(records) == 1
        assert records[0]["status"] == "dry_run"
        assert records[0]["result"] is None

    @pytest.mark.asyncio
    async def test_dry_run_has_enhanced_fields(self):
        """dry_run records should include enhanced ActionRecord fields."""
        tool = MockToolPlugin("deploy")
        llm = MockLLMProviderWithToolCalls(tool_name="deploy")

        from unittest.mock import MagicMock
        agent_def = MagicMock()
        agent_def.rollback_on_failure = True
        agent_def.rollback_action = "undo_deploy"

        agent = Agent(
            agent_id="deployer",
            role="Deployer",
            system_prompt="Deploy.",
            behavior_type=AgentBehaviorType.ACTION_EXECUTOR,
            tools=[tool],
            llm_provider=llm,
            action_policy="dry_run",
            agent_definition=agent_def,
        )

        state = await agent.execute({"task": "deploy", "workflow_run_id": "run-123"})
        records = state.get("deployer_action_records", [])
        assert len(records) == 1
        assert records[0]["policy"] == "dry_run"
        assert records[0]["reversible"] is True
        assert records[0]["rollback_action"] == "undo_deploy"
        assert records[0]["workflow_run_id"] == "run-123"


class TestConfirmOnErrorPolicy:
    """Tests for confirm_on_error action policy (T028)."""

    @pytest.mark.asyncio
    async def test_confirm_on_error_executes_on_success(self):
        """confirm_on_error should execute tools normally when they succeed."""
        tool = MockToolPlugin("send_email", result={"sent": True})
        llm = MockLLMProviderWithToolCalls(tool_name="send_email")

        agent = Agent(
            agent_id="mailer",
            role="Email Sender",
            system_prompt="Send emails.",
            behavior_type=AgentBehaviorType.ACTION_EXECUTOR,
            tools=[tool],
            llm_provider=llm,
            action_policy="confirm_on_error",
        )

        state = await agent.execute({"task": "send email"})

        # Should have executed fully (2 LLM calls: tool call + final)
        assert llm._call_count == 2
        assert "awaiting_error_resolution" not in state

        records = state.get("mailer_action_records", [])
        assert len(records) == 1
        assert records[0]["status"] == "success"

    @pytest.mark.asyncio
    async def test_confirm_on_error_pauses_on_tool_error(self):
        """confirm_on_error should pause workflow when a tool fails."""
        tool = MockFailingToolPlugin("send_email", "SMTP connection refused")
        llm = MockLLMProviderWithToolCalls(tool_name="send_email")

        agent = Agent(
            agent_id="mailer",
            role="Email Sender",
            system_prompt="Send emails.",
            behavior_type=AgentBehaviorType.ACTION_EXECUTOR,
            tools=[tool],
            llm_provider=llm,
            action_policy="confirm_on_error",
        )

        state = await agent.execute({"task": "send email"})

        # Should have paused
        assert state.get("awaiting_error_resolution") is True

        # Error details should be present
        error_details = state.get("mailer_error_details")
        assert error_details is not None
        assert error_details["tool"] == "send_email"
        assert "SMTP connection refused" in str(error_details["error"])

        # Action records should show the error
        records = state.get("mailer_action_records", [])
        assert len(records) == 1
        assert records[0]["status"] == "error"


class TestRollback:
    """Tests for rollback behavior (T029)."""

    @pytest.mark.asyncio
    async def test_rollback_triggers_on_failure(self):
        """When rollback_on_failure=True, _trigger_rollback should be called on step failure."""
        from unittest.mock import AsyncMock, MagicMock, patch

        engine = WorkflowEngine([WorkflowStep(agent="deployer", step_type="sequential")])
        agent = MagicMock(spec=Agent)
        agent.agent_id = "deployer"
        agent.agent_definition = MagicMock()
        agent.agent_definition.rollback_on_failure = True
        agent.agent_definition.rollback_action = "undo_deploy"

        with patch.object(engine, "_execute_agent_with_failure_policy", new_callable=AsyncMock, side_effect=RuntimeError("Deploy failed")):
            with patch.object(engine, "_trigger_rollback", new_callable=AsyncMock) as mock_rollback:
                result = await engine.execute(
                    {"deployer": agent},
                    {"task": "deploy"},
                )

        assert result.status == WorkflowStatus.FAILED
        mock_rollback.assert_called_once_with(agent, {"task": "deploy"})

    @pytest.mark.asyncio
    async def test_rollback_failure_logged_not_raised(self):
        """If rollback itself fails, it should be logged and not re-raised."""
        from unittest.mock import AsyncMock, MagicMock

        engine = WorkflowEngine([WorkflowStep(agent="test", step_type="sequential")])
        agent = MagicMock(spec=Agent)
        agent.agent_id = "test"
        agent._tool_map = {"undo": MagicMock()}
        agent._tool_map["undo"].execute = AsyncMock(side_effect=RuntimeError("Rollback failed"))
        agent.agent_definition = MagicMock()
        agent.agent_definition.rollback_action = "undo"

        # Should not raise
        await engine._trigger_rollback(agent, {"task": "test"})
        # Verify the rollback tool was actually called (even though it failed)
        agent._tool_map["undo"].execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_rollback_skipped_when_disabled(self):
        """When rollback_on_failure=False, _trigger_rollback should NOT be called."""
        from unittest.mock import AsyncMock, MagicMock, patch

        engine = WorkflowEngine([WorkflowStep(agent="deployer", step_type="sequential")])
        agent = MagicMock(spec=Agent)
        agent.agent_id = "deployer"
        agent.agent_definition = MagicMock()
        agent.agent_definition.rollback_on_failure = False

        with patch.object(engine, "_execute_agent_with_failure_policy", new_callable=AsyncMock, side_effect=RuntimeError("Failed")):
            with patch.object(engine, "_trigger_rollback", new_callable=AsyncMock) as mock_rollback:
                result = await engine.execute(
                    {"deployer": agent},
                    {"task": "deploy"},
                )

        assert result.status == WorkflowStatus.FAILED
        mock_rollback.assert_not_called()
