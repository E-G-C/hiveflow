"""Tests for schema additions: action_executor, gated steps, model_requirements, enforcement_mode."""

import pytest

from hiveflow.core.schema import (
    AgentBehaviorTypeSchema,
    AgentDefinition,
    ModelRequirements,
    StateSchema,
    TeamConfiguration,
    WorkflowGraph,
    WorkflowStepDefinition,
    WorkflowStepType,
)


class TestAgentDefinitionActionExecutor:
    """Tests for action_executor behavior type and action_policy."""

    def test_action_executor_requires_action_policy(self):
        """action_executor without action_policy should fail validation."""
        with pytest.raises(ValueError, match="action_policy is required"):
            AgentDefinition(
                id="emailer",
                role="Email Sender",
                system_prompt="Send emails.",
                behavior_type=AgentBehaviorTypeSchema.ACTION_EXECUTOR,
            )

    def test_action_executor_with_auto_policy(self):
        """action_executor with auto policy should validate."""
        agent = AgentDefinition(
            id="emailer",
            role="Email Sender",
            system_prompt="Send emails.",
            behavior_type=AgentBehaviorTypeSchema.ACTION_EXECUTOR,
            action_policy="auto",
        )
        assert agent.action_policy == "auto"

    def test_action_executor_with_require_approval_policy(self):
        """action_executor with require_approval policy should validate."""
        agent = AgentDefinition(
            id="emailer",
            role="Email Sender",
            system_prompt="Send emails.",
            behavior_type=AgentBehaviorTypeSchema.ACTION_EXECUTOR,
            action_policy="require_approval",
        )
        assert agent.action_policy == "require_approval"

    def test_action_policy_rejected_for_non_action_executor(self):
        """action_policy on non-action_executor agent should fail."""
        with pytest.raises(ValueError, match="action_policy must be None"):
            AgentDefinition(
                id="writer",
                role="Writer",
                system_prompt="Write.",
                behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
                action_policy="auto",
            )

    def test_invalid_action_policy_value(self):
        """Invalid action_policy value should fail."""
        with pytest.raises(ValueError, match="action_policy"):
            AgentDefinition(
                id="emailer",
                role="Email Sender",
                system_prompt="Send emails.",
                behavior_type=AgentBehaviorTypeSchema.ACTION_EXECUTOR,
                action_policy="invalid",
            )


class TestModelRequirements:
    """Tests for ModelRequirements pydantic model."""

    def test_valid_model_requirements(self):
        """Valid requirements should pass."""
        reqs = ModelRequirements(
            cost_tier="smart",
            supports_tools=True,
            supports_vision=False,
            strengths=["reasoning", "coding"],
        )
        assert reqs.cost_tier == "smart"
        assert reqs.supports_tools is True
        assert reqs.strengths == ["reasoning", "coding"]

    def test_invalid_cost_tier(self):
        """Invalid cost_tier should fail."""
        with pytest.raises(ValueError, match="cost_tier"):
            ModelRequirements(cost_tier="invalid")

    def test_empty_model_requirements(self):
        """Empty requirements should have defaults."""
        reqs = ModelRequirements()
        assert reqs.cost_tier is None
        assert reqs.supports_tools is None
        assert reqs.strengths == []

    def test_agent_with_model_requirements(self):
        """AgentDefinition should accept model_requirements."""
        agent = AgentDefinition(
            id="analyzer",
            role="Analyzer",
            system_prompt="Analyze data.",
            behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
            model_requirements=ModelRequirements(cost_tier="fast"),
        )
        assert agent.model_requirements is not None
        assert agent.model_requirements.cost_tier == "fast"


class TestOutputType:
    """Tests for output_type field and inference."""

    def test_explicit_output_type(self):
        """Explicit output_type should be stored."""
        agent = AgentDefinition(
            id="writer",
            role="Writer",
            system_prompt="Write.",
            behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
            output_type="structured_data",
        )
        assert agent.output_type == "structured_data"

    def test_invalid_output_type(self):
        """Invalid output_type should fail."""
        with pytest.raises(ValueError, match="output_type"):
            AgentDefinition(
                id="writer",
                role="Writer",
                system_prompt="Write.",
                behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
                output_type="invalid",
            )

    def test_inferred_output_type_llm_only(self):
        """llm_only should infer text output type."""
        agent = AgentDefinition(
            id="writer",
            role="Writer",
            system_prompt="Write.",
            behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
        )
        assert agent.get_output_type() == "text"

    def test_inferred_output_type_action_executor(self):
        """action_executor should infer side_effect output type."""
        agent = AgentDefinition(
            id="emailer",
            role="Emailer",
            system_prompt="Send.",
            behavior_type=AgentBehaviorTypeSchema.ACTION_EXECUTOR,
            action_policy="auto",
        )
        assert agent.get_output_type() == "side_effect"

    def test_inferred_output_type_orchestrator(self):
        """orchestrator should infer structured_data output type."""
        agent = AgentDefinition(
            id="planner",
            role="Planner",
            system_prompt="Plan.",
            behavior_type=AgentBehaviorTypeSchema.ORCHESTRATOR,
        )
        assert agent.get_output_type() == "structured_data"


class TestGatedStepType:
    """Tests for gated step type in WorkflowStepDefinition."""

    def test_gated_step_requires_gate_id(self):
        """Gated step without gate_id should fail."""
        with pytest.raises(ValueError, match="Gated steps must define gate_id"):
            WorkflowStepDefinition(
                agent="",
                type=WorkflowStepType.GATED,
            )

    def test_gated_step_with_gate_id(self):
        """Gated step with gate_id should validate."""
        step = WorkflowStepDefinition(
            agent="",
            type=WorkflowStepType.GATED,
            gate_id="approval_gate",
            gate_description="Review before publishing",
        )
        assert step.gate_id == "approval_gate"
        assert step.gate_description == "Review before publishing"

    def test_gated_step_allows_empty_agent(self):
        """Gated step should allow empty agent string."""
        step = WorkflowStepDefinition(
            agent="",
            type=WorkflowStepType.GATED,
            gate_id="my_gate",
        )
        assert step.agent == ""

    def test_max_iterations_on_conditional(self):
        """Conditional step should accept max_iterations."""
        step = WorkflowStepDefinition(
            agent="reviewer",
            type=WorkflowStepType.CONDITIONAL,
            next_on_accept="publisher",
            next_on_reject="writer",
            max_iterations=5,
        )
        assert step.max_iterations == 5


class TestStateSchemaEnforcement:
    """Tests for enforcement_mode on StateSchema."""

    def test_default_enforcement_mode(self):
        """Default enforcement_mode should be warn."""
        schema = StateSchema()
        assert schema.enforcement_mode == "warn"

    def test_valid_enforcement_modes(self):
        """All valid modes should be accepted."""
        for mode in ("warn", "strict", "off"):
            schema = StateSchema(enforcement_mode=mode)
            assert schema.enforcement_mode == mode

    def test_invalid_enforcement_mode(self):
        """Invalid mode should fail."""
        with pytest.raises(ValueError, match="enforcement_mode must be one of"):
            StateSchema(enforcement_mode="invalid")


class TestTeamConfigurationWithGatedSteps:
    """Tests for TeamConfiguration with gated steps."""

    def test_gated_step_with_empty_agent_allowed(self):
        """TeamConfiguration should allow gated steps with empty agent."""
        config = TeamConfiguration(
            team_name="test_team",
            description="Test",
            agents=[
                AgentDefinition(
                    id="writer",
                    role="Writer",
                    system_prompt="Write.",
                    behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
                ),
            ],
            workflow=WorkflowGraph(steps=[
                WorkflowStepDefinition(
                    agent="writer",
                    type=WorkflowStepType.SEQUENTIAL,
                    next="approval_gate",
                ),
                WorkflowStepDefinition(
                    agent="",
                    type=WorkflowStepType.GATED,
                    gate_id="approval_gate",
                    gate_description="Review before publishing",
                ),
            ]),
        )
        assert len(config.workflow.steps) == 2


class TestAgentDefinitionFailureFields:
    """Tests for on_failure, max_retries, rollback_on_failure, rollback_action fields (T006)."""

    def test_on_failure_accepts_fail(self):
        agent = AgentDefinition(
            id="test", role="Test", system_prompt="Test.",
            behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
            on_failure="fail",
        )
        assert agent.on_failure == "fail"

    def test_on_failure_accepts_retry(self):
        agent = AgentDefinition(
            id="test", role="Test", system_prompt="Test.",
            behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
            on_failure="retry",
        )
        assert agent.on_failure == "retry"

    def test_on_failure_accepts_skip(self):
        agent = AgentDefinition(
            id="test", role="Test", system_prompt="Test.",
            behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
            on_failure="skip",
        )
        assert agent.on_failure == "skip"

    def test_on_failure_accepts_none(self):
        agent = AgentDefinition(
            id="test", role="Test", system_prompt="Test.",
            behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
        )
        assert agent.on_failure is None

    def test_on_failure_rejects_invalid(self):
        with pytest.raises(ValueError, match="on_failure"):
            AgentDefinition(
                id="test", role="Test", system_prompt="Test.",
                behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
                on_failure="crash",
            )

    def test_max_retries_default(self):
        agent = AgentDefinition(
            id="test", role="Test", system_prompt="Test.",
            behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
        )
        assert agent.max_retries == 1

    def test_max_retries_accepts_positive(self):
        agent = AgentDefinition(
            id="test", role="Test", system_prompt="Test.",
            behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
            max_retries=5,
        )
        assert agent.max_retries == 5

    def test_max_retries_rejects_zero(self):
        with pytest.raises(ValueError):
            AgentDefinition(
                id="test", role="Test", system_prompt="Test.",
                behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
                max_retries=0,
            )

    def test_max_retries_rejects_negative(self):
        with pytest.raises(ValueError):
            AgentDefinition(
                id="test", role="Test", system_prompt="Test.",
                behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
                max_retries=-1,
            )

    def test_rollback_fields_defaults(self):
        agent = AgentDefinition(
            id="test", role="Test", system_prompt="Test.",
            behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
        )
        assert agent.rollback_on_failure is False
        assert agent.rollback_action is None

    def test_rollback_fields_on_action_executor(self):
        agent = AgentDefinition(
            id="deployer", role="Deployer", system_prompt="Deploy.",
            behavior_type=AgentBehaviorTypeSchema.ACTION_EXECUTOR,
            action_policy="auto",
            rollback_on_failure=True,
            rollback_action="undo_deploy",
        )
        assert agent.rollback_on_failure is True
        assert agent.rollback_action == "undo_deploy"


class TestExpandedActionPolicy:
    """Tests for expanded action_policy validator accepting dry_run and confirm_on_error (T007)."""

    def test_action_policy_accepts_dry_run(self):
        agent = AgentDefinition(
            id="deployer", role="Deployer", system_prompt="Deploy.",
            behavior_type=AgentBehaviorTypeSchema.ACTION_EXECUTOR,
            action_policy="dry_run",
        )
        assert agent.action_policy == "dry_run"

    def test_action_policy_accepts_confirm_on_error(self):
        agent = AgentDefinition(
            id="deployer", role="Deployer", system_prompt="Deploy.",
            behavior_type=AgentBehaviorTypeSchema.ACTION_EXECUTOR,
            action_policy="confirm_on_error",
        )
        assert agent.action_policy == "confirm_on_error"

    def test_action_policy_rejects_unknown_value(self):
        with pytest.raises(ValueError, match="action_policy"):
            AgentDefinition(
                id="deployer", role="Deployer", system_prompt="Deploy.",
                behavior_type=AgentBehaviorTypeSchema.ACTION_EXECUTOR,
                action_policy="yolo",
            )


class TestSubWorkflowEnumAndValidation:
    """Tests for SUB_WORKFLOW enum member and sub_workflow step validation (T007)."""

    def test_sub_workflow_enum_member_exists(self):
        assert WorkflowStepType.SUB_WORKFLOW == "sub_workflow"
        assert "sub_workflow" in [e.value for e in WorkflowStepType]

    def test_sub_workflow_step_requires_team(self):
        with pytest.raises(ValueError, match="sub_workflow steps must define 'team'"):
            WorkflowStepDefinition(
                agent="inner_runner",
                type=WorkflowStepType.SUB_WORKFLOW,
            )

    def test_sub_workflow_step_with_team_validates(self):
        step = WorkflowStepDefinition(
            agent="inner_runner",
            type=WorkflowStepType.SUB_WORKFLOW,
            team="research_team",
        )
        assert step.team == "research_team"

    def test_sub_workflow_step_with_mappings(self):
        step = WorkflowStepDefinition(
            agent="inner_runner",
            type=WorkflowStepType.SUB_WORKFLOW,
            team="research_team",
            input_mapping={"query": "research_topic"},
            output_mapping={"result": "research_output"},
        )
        assert step.input_mapping == {"query": "research_topic"}
        assert step.output_mapping == {"result": "research_output"}

    def test_non_sub_workflow_step_ignores_team(self):
        step = WorkflowStepDefinition(
            agent="writer",
            type=WorkflowStepType.SEQUENTIAL,
            team="some_team",
        )
        assert step.team == "some_team"
