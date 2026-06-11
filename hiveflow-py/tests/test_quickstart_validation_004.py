"""Validate quickstart.md scenarios for 004-workflow-engine.

These tests verify that the API patterns documented in
specs/004-workflow-engine/quickstart.md work end-to-end against the
actual implementation.
"""

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
    """Mock LLM provider for quickstart validation."""

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
    return Agent(
        agent_id=agent_id,
        role=agent_id.title(),
        system_prompt=f"You are {agent_id}.",
        behavior_type=AgentBehaviorType.LLM_ONLY,
        llm_provider=MockProvider(responses),
    )


class TestQuickstartScenario1:
    """Scenario 1: Enable checkpointing on a workflow run."""

    @pytest.mark.asyncio
    async def test_checkpoint_enabled_run_pauses_at_gate(self):
        """Quickstart §1: run with checkpoint=True pauses at gated step."""
        investigator = make_agent("investigator")

        steps = [
            WorkflowStep(
                agent="investigator",
                step_type=StepType.SEQUENTIAL,
                next_step="approval_gate",
            ),
            WorkflowStep(
                agent="approval_gate",
                step_type=StepType.GATED,
                gate_id="approval_gate",
                gate_description="Review findings before remediation",
            ),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileCheckpointStorage(directory=tmpdir)
            engine = WorkflowEngine(steps)

            result = await engine.execute(
                {"investigator": investigator},
                {"task": "Investigate API latency spike"},
                checkpoint_storage=storage,
                session_id="qs-session-1",
            )

            # Quickstart asserts: session.status == "paused"
            assert result.status == WorkflowStatus.PAUSED
            assert result.state.get("awaiting_gate_approval") is True


class TestQuickstartScenario2:
    """Scenario 2: List available checkpoints."""

    @pytest.mark.asyncio
    async def test_list_checkpoints_returns_metadata(self):
        """Quickstart §2: list_checkpoints() returns checkpoint dicts with expected keys."""
        investigator = make_agent("investigator")

        steps = [
            WorkflowStep(
                agent="investigator",
                step_type=StepType.SEQUENTIAL,
                next_step="gate",
            ),
            WorkflowStep(
                agent="gate",
                step_type=StepType.GATED,
                gate_id="gate",
            ),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileCheckpointStorage(directory=tmpdir)
            engine = WorkflowEngine(steps)

            await engine.execute(
                {"investigator": investigator},
                {"task": "test"},
                checkpoint_storage=storage,
                session_id="qs-list",
            )

            # Quickstart pattern: list_checkpoints(session_id)
            checkpoints = await storage.list_checkpoints("qs-list")
            assert len(checkpoints) == 1

            cp = checkpoints[0]
            # Quickstart references these keys
            assert cp.checkpoint_id  # non-empty UUID
            assert cp.session_id == "qs-list"
            assert cp.step_index == 1  # gated step index
            assert cp.current_agent_id == "gate"
            assert cp.created_at > 0


class TestQuickstartScenario3:
    """Scenario 3: Resume a paused workflow."""

    @pytest.mark.asyncio
    async def test_resume_with_approval_completes(self):
        """Quickstart §3: resume with approval responses completes workflow."""
        reviewer = make_agent("reviewer")

        steps = [
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

        engine = WorkflowEngine(steps)

        # Create checkpoint at gated step
        checkpoint = WorkflowCheckpoint(
            session_id="qs-resume",
            step_index=0,
            state={
                "task": "test",
                "awaiting_gate_approval": True,
                "pending_gate_id": "gate",
            },
            current_agent_id="gate",
            current_step_type="gated",
        )

        # Quickstart pattern: resume with responses
        result = await engine.resume(
            {"reviewer": reviewer},
            checkpoint,
            responses={"approval": True},
        )

        assert result.status == WorkflowStatus.COMPLETED


class TestQuickstartScenario4:
    """Scenario 4: Resume from a specific checkpoint (rewind)."""

    @pytest.mark.asyncio
    async def test_resume_from_specific_checkpoint_id(self):
        """Quickstart §4: resume with checkpoint_id loads that specific checkpoint."""
        investigator = make_agent("investigator")
        reviewer = make_agent("reviewer")

        steps = [
            WorkflowStep(
                agent="investigator",
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

            # Execute until gate
            result = await engine.execute(
                {"investigator": investigator, "reviewer": reviewer},
                {"task": "test"},
                checkpoint_storage=storage,
                session_id="qs-rewind",
            )
            assert result.status == WorkflowStatus.PAUSED

            # Get the specific checkpoint_id
            checkpoints = await storage.list_checkpoints("qs-rewind")
            specific_id = checkpoints[0].checkpoint_id

            # Quickstart pattern: load with checkpoint_id
            loaded = await storage.load("qs-rewind", specific_id)
            assert loaded is not None
            assert loaded.checkpoint_id == specific_id

            # Resume from it
            result2 = await engine.resume(
                {"investigator": investigator, "reviewer": reviewer},
                loaded,
                responses={"approval": True},
            )
            assert result2.status == WorkflowStatus.COMPLETED


class TestQuickstartScenario5:
    """Scenario 5: Monitor events during execution."""

    @pytest.mark.asyncio
    async def test_event_callbacks_receive_all_event_types(self):
        """Quickstart §5: on_event() receives expected event types."""
        events: list[tuple[str, str, dict]] = []

        writer = make_agent("writer")
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
                next_step="finisher",
            ),
            WorkflowStep(
                agent="finisher",
                step_type=StepType.SEQUENTIAL,
            ),
        ]

        finisher = make_agent("finisher")

        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileCheckpointStorage(directory=tmpdir)
            engine = WorkflowEngine(steps)

            # Quickstart pattern: register event callback
            engine.on_event(lambda t, a, d: events.append((t, a, d)))

            # Execute until gate
            await engine.execute(
                {"writer": writer, "finisher": finisher},
                {"task": "test"},
                checkpoint_storage=storage,
                session_id="qs-events",
            )

            event_types = {e[0] for e in events}
            assert "step_start" in event_types
            assert "step_complete" in event_types
            assert "gate_requested" in event_types
            assert "checkpoint_saved" in event_types

            # Resume and check approval + output events
            events.clear()
            checkpoint = await storage.load("qs-events")
            await engine.resume(
                {"writer": writer, "finisher": finisher},
                checkpoint,
                responses={"approval": True},
            )

            event_types_phase2 = {e[0] for e in events}
            assert "approval" in event_types_phase2
            assert "step_start" in event_types_phase2
            assert "step_complete" in event_types_phase2
            assert "output" in event_types_phase2


class TestQuickstartErrorHandling:
    """Quickstart §Error Handling: verify exception types."""

    @pytest.mark.asyncio
    async def test_checkpoint_error_on_invalid_checkpoint(self):
        """CheckpointError raised for mismatched checkpoint."""
        steps = [
            WorkflowStep(agent="writer", step_type=StepType.SEQUENTIAL),
        ]
        engine = WorkflowEngine(steps)

        checkpoint = WorkflowCheckpoint(
            session_id="bad",
            step_index=0,
            state={},
            current_agent_id="wrong_agent",
            current_step_type="sequential",
        )

        with pytest.raises(CheckpointError):
            await engine.resume(
                {"writer": make_agent("writer")},
                checkpoint,
            )

    @pytest.mark.asyncio
    async def test_checkpoint_error_on_out_of_range(self):
        """CheckpointError raised for out-of-range step_index."""
        steps = [
            WorkflowStep(agent="writer", step_type=StepType.SEQUENTIAL),
        ]
        engine = WorkflowEngine(steps)

        checkpoint = WorkflowCheckpoint(
            session_id="bad",
            step_index=99,
            state={},
        )

        with pytest.raises(CheckpointError):
            await engine.resume(
                {"writer": make_agent("writer")},
                checkpoint,
            )
