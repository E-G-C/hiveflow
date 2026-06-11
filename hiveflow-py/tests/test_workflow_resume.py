"""Integration tests for workflow resume from checkpoint (US1)."""

import tempfile

import pytest

from hiveflow.core.agent import Agent, AgentBehaviorType
from hiveflow.core.checkpoint import (
    CheckpointError,
    FileCheckpointStorage,
    WorkflowCheckpoint,
)
from hiveflow.core.workflow import (
    StepType,
    WorkflowEngine,
    WorkflowResult,
    WorkflowStatus,
    WorkflowStep,
)
from hiveflow.plugins.llm import LLMProvider, LLMResponse, TokenUsage


class MockProvider(LLMProvider):
    """Mock LLM provider that returns configurable responses."""

    def __init__(self, responses: list[str] | None = None):
        self._responses = list(responses or ["output"])
        self._call_count = 0

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def plugin_id(self) -> str:
        return "mock"

    @property
    def description(self) -> str:
        return "Mock"

    async def chat(self, messages, config):
        idx = min(self._call_count, len(self._responses) - 1)
        self._call_count += 1
        return LLMResponse(
            content=self._responses[idx],
            model="mock",
            usage=TokenUsage(prompt_tokens=5, completion_tokens=5, total_tokens=10),
        )


def make_agent(agent_id: str, responses: list[str] | None = None) -> Agent:
    """Helper to create a mock agent."""
    return Agent(
        agent_id=agent_id,
        role=agent_id.title(),
        system_prompt=f"You are {agent_id}.",
        behavior_type=AgentBehaviorType.LLM_ONLY,
        llm_provider=MockProvider(responses),
    )


class TestResumeFromGatedStep:
    """Tests for resuming from a GATED step checkpoint."""

    @pytest.mark.asyncio
    async def test_resume_from_gated_step_completes(self):
        """Resume from a gated step should continue to subsequent steps."""
        writer = make_agent("writer")
        reviewer = make_agent("reviewer")

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
                gate_description="Review draft",
                next_step="reviewer",
            ),
            WorkflowStep(
                agent="reviewer",
                step_type=StepType.SEQUENTIAL,
            ),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileCheckpointStorage(directory=tmpdir)
            engine = WorkflowEngine(steps)

            # Phase 1: Execute until gate
            result = await engine.execute(
                {"writer": writer, "reviewer": reviewer},
                {"task": "Write and review"},
                checkpoint_storage=storage,
                session_id="sess-1",
            )
            assert result.status == WorkflowStatus.PAUSED

            # Load checkpoint
            checkpoint = await storage.load("sess-1")
            assert checkpoint is not None
            assert checkpoint.step_index == 1  # gated step

            # Phase 2: Resume from checkpoint
            result2 = await engine.resume(
                {"writer": writer, "reviewer": reviewer},
                checkpoint,
                responses={"approval": True},
            )
            assert result2.status == WorkflowStatus.COMPLETED
            assert "reviewer_output" in result2.state


class TestResumeFromHumanGate:
    """Tests for resuming from a HUMAN_GATE step checkpoint."""

    @pytest.mark.asyncio
    async def test_resume_from_human_gate_approve(self):
        """Resume from human_gate with approval should complete."""
        # Agent that sets awaiting_human_input
        class HumanGateProvider(LLMProvider):
            @property
            def provider_name(self) -> str:
                return "mock"
            @property
            def plugin_id(self) -> str:
                return "mock"
            @property
            def description(self) -> str:
                return "Mock"
            async def chat(self, messages, config):
                return LLMResponse(
                    content="Please review",
                    model="mock",
                    usage=TokenUsage(prompt_tokens=5, completion_tokens=5, total_tokens=10),
                    metadata={"awaiting_human_input": True},
                )

        gatekeeper = Agent(
            agent_id="gatekeeper",
            role="Gatekeeper",
            system_prompt="Request human approval.",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=HumanGateProvider(),
        )
        finalizer = make_agent("finalizer")

        steps = [
            WorkflowStep(
                agent="gatekeeper",
                step_type=StepType.HUMAN_GATE,
                next_step="finalizer",
            ),
            WorkflowStep(
                agent="finalizer",
                step_type=StepType.SEQUENTIAL,
            ),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileCheckpointStorage(directory=tmpdir)
            engine = WorkflowEngine(steps)

            # Execute — should pause at human_gate
            result = await engine.execute(
                {"gatekeeper": gatekeeper, "finalizer": finalizer},
                {"task": "Review and finalize"},
                checkpoint_storage=storage,
                session_id="sess-hg",
            )

            # If it paused at human_gate, verify and resume
            if result.status == WorkflowStatus.PAUSED:
                checkpoint = await storage.load("sess-hg")
                assert checkpoint is not None

                result2 = await engine.resume(
                    {"gatekeeper": gatekeeper, "finalizer": finalizer},
                    checkpoint,
                    responses={"approval": True, "awaiting_human_input": False},
                )
                assert result2.status == WorkflowStatus.COMPLETED


class TestResumeSkipsCompletedSteps:
    """Tests verifying resume doesn't re-execute prior steps."""

    @pytest.mark.asyncio
    async def test_resume_does_not_re_execute_prior_steps(self):
        """Agent execute should NOT be called for steps before the checkpoint."""
        tracking_provider = MockProvider(["output"])
        writer = make_agent("writer")
        reviewer = make_agent("reviewer")

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
                next_step="reviewer",
            ),
            WorkflowStep(
                agent="reviewer",
                step_type=StepType.SEQUENTIAL,
            ),
        ]

        engine = WorkflowEngine(steps)

        # Create checkpoint at the gated step (index 1)
        checkpoint = WorkflowCheckpoint(
            session_id="sess-skip",
            step_index=1,
            state={"task": "test", "writer_output": "already done"},
            current_agent_id="approval_gate",
            current_step_type="gated",
        )

        # Track writer calls — provider may be wrapped by ResilientLLMProvider
        writer_provider = writer.llm_provider
        if hasattr(writer_provider, "_fallback_chain"):
            # Unwrap resilient provider to get the underlying mock
            writer_provider = writer_provider._fallback_chain._providers[0][0]
        assert isinstance(writer_provider, MockProvider)
        initial_count = writer_provider._call_count

        result = await engine.resume(
            {"writer": writer, "reviewer": reviewer},
            checkpoint,
            responses={"approval": True},
        )

        assert result.status == WorkflowStatus.COMPLETED
        # Writer should NOT have been called (we resumed past it)
        assert writer_provider._call_count == initial_count
        # Reviewer should have been called
        assert "reviewer_output" in result.state


class TestValidateCheckpoint:
    """Tests for _validate_checkpoint() error cases."""

    def test_rejects_out_of_range_step_index(self):
        """Should reject step_index that's out of range."""
        steps = [
            WorkflowStep(agent="writer", step_type=StepType.SEQUENTIAL),
        ]
        engine = WorkflowEngine(steps)

        checkpoint = WorkflowCheckpoint(
            session_id="test",
            step_index=5,
            state={},
            current_agent_id="writer",
            current_step_type="sequential",
        )

        with pytest.raises(CheckpointError, match="out of range"):
            engine._validate_checkpoint(checkpoint)

    def test_rejects_mismatched_agent_id(self):
        """Should reject when agent_id doesn't match workflow step."""
        steps = [
            WorkflowStep(agent="writer", step_type=StepType.SEQUENTIAL),
        ]
        engine = WorkflowEngine(steps)

        checkpoint = WorkflowCheckpoint(
            session_id="test",
            step_index=0,
            state={},
            current_agent_id="wrong_agent",
            current_step_type="sequential",
        )

        with pytest.raises(CheckpointError, match="agent_id mismatch"):
            engine._validate_checkpoint(checkpoint)

    def test_rejects_mismatched_step_type(self):
        """Should reject when step_type doesn't match workflow step."""
        steps = [
            WorkflowStep(agent="writer", step_type=StepType.SEQUENTIAL),
        ]
        engine = WorkflowEngine(steps)

        checkpoint = WorkflowCheckpoint(
            session_id="test",
            step_index=0,
            state={},
            current_agent_id="writer",
            current_step_type="human_gate",
        )

        with pytest.raises(CheckpointError, match="step_type mismatch"):
            engine._validate_checkpoint(checkpoint)

    def test_allows_empty_agent_id(self):
        """Empty agent_id in checkpoint should pass validation (backward compat)."""
        steps = [
            WorkflowStep(agent="writer", step_type=StepType.SEQUENTIAL),
        ]
        engine = WorkflowEngine(steps)

        checkpoint = WorkflowCheckpoint(
            session_id="test",
            step_index=0,
            state={},
            current_agent_id="",
            current_step_type="",
        )

        # Should not raise
        engine._validate_checkpoint(checkpoint)


class TestResumeFromSpecificCheckpoint:
    """Tests for resuming from a specific checkpoint_id."""

    @pytest.mark.asyncio
    async def test_resume_from_specific_checkpoint_id(self):
        """Should be able to load and resume from a specific checkpoint."""
        writer = make_agent("writer")
        reviewer = make_agent("reviewer")

        steps = [
            WorkflowStep(
                agent="writer",
                step_type=StepType.SEQUENTIAL,
                next_step="gate",
            ),
            WorkflowStep(
                agent="gate",
                step_type=StepType.GATED,
                gate_id="gate",
                next_step="reviewer",
            ),
            WorkflowStep(
                agent="reviewer",
                step_type=StepType.SEQUENTIAL,
            ),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileCheckpointStorage(directory=tmpdir)
            engine = WorkflowEngine(steps)

            # Execute to create checkpoint
            result = await engine.execute(
                {"writer": writer, "reviewer": reviewer},
                {"task": "test"},
                checkpoint_storage=storage,
                session_id="sess-cp",
            )
            assert result.status == WorkflowStatus.PAUSED

            # Get the specific checkpoint_id
            checkpoints = await storage.list_checkpoints("sess-cp")
            assert len(checkpoints) == 1
            specific_id = checkpoints[0].checkpoint_id

            # Load by specific ID
            specific = await storage.load("sess-cp", specific_id)
            assert specific is not None
            assert specific.checkpoint_id == specific_id

            # Resume from it
            result2 = await engine.resume(
                {"writer": writer, "reviewer": reviewer},
                specific,
                responses={"approval": True},
            )
            assert result2.status == WorkflowStatus.COMPLETED


class TestResumeErrorCases:
    """Tests for resume error handling."""

    @pytest.mark.asyncio
    async def test_resume_with_invalid_session_raises(self):
        """Resuming with nonexistent session should raise KeyError."""
        from hiveflow.core.hiveflow import HiveFlow

        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileCheckpointStorage(directory=tmpdir)
            hf = HiveFlow(checkpoint_storage=storage)

            with pytest.raises(KeyError, match="not found"):
                await hf.resume("nonexistent-session", {"approval": True})

    @pytest.mark.asyncio
    async def test_resume_corrupted_checkpoint_raises(self):
        """Loading a corrupted checkpoint should raise CheckpointError."""
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileCheckpointStorage(directory=tmpdir)
            fake_uuid = "00000000-0000-0000-0000-000000000000"
            path = Path(tmpdir) / f"bad-session_{fake_uuid}.json"
            path.write_text("{corrupt!!!", encoding="utf-8")

            with pytest.raises(CheckpointError, match="Corrupted"):
                await storage.load("bad-session", fake_uuid)

    @pytest.mark.asyncio
    async def test_resume_with_checkpoint_validation_error(self):
        """Resume with mismatched checkpoint should raise CheckpointError."""
        steps = [
            WorkflowStep(agent="writer", step_type=StepType.SEQUENTIAL),
        ]
        engine = WorkflowEngine(steps)

        # Checkpoint references wrong agent
        checkpoint = WorkflowCheckpoint(
            session_id="test",
            step_index=0,
            state={},
            current_agent_id="nonexistent",
            current_step_type="sequential",
        )

        with pytest.raises(CheckpointError, match="agent_id mismatch"):
            await engine.resume(
                {"writer": make_agent("writer")},
                checkpoint,
            )
