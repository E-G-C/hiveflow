"""Tests for workflow event emission (US3)."""

import tempfile

import pytest

from hiveflow.core.agent import Agent, AgentBehaviorType
from hiveflow.core.checkpoint import FileCheckpointStorage, WorkflowCheckpoint
from hiveflow.core.workflow import (
    StepType,
    WorkflowEngine,
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


class TestOutputEvent:
    """Tests for OUTPUT event emission on workflow completion."""

    @pytest.mark.asyncio
    async def test_output_event_emitted_on_completion(self):
        """output event should be emitted when workflow completes."""
        events: list[tuple[str, str, dict]] = []

        writer = make_agent("writer")
        steps = [
            WorkflowStep(agent="writer", step_type=StepType.SEQUENTIAL),
        ]
        engine = WorkflowEngine(steps)
        engine.on_event(lambda t, a, d: events.append((t, a, d)))

        result = await engine.execute({"writer": writer}, {"task": "test"})

        assert result.status == WorkflowStatus.COMPLETED
        output_events = [e for e in events if e[0] == "output"]
        assert len(output_events) == 1
        assert "result" in output_events[0][2]

    @pytest.mark.asyncio
    async def test_step_start_and_complete_events(self):
        """step_start and step_complete events should be emitted."""
        events: list[tuple[str, str, dict]] = []

        writer = make_agent("writer")
        steps = [
            WorkflowStep(agent="writer", step_type=StepType.SEQUENTIAL),
        ]
        engine = WorkflowEngine(steps)
        engine.on_event(lambda t, a, d: events.append((t, a, d)))

        await engine.execute({"writer": writer}, {"task": "test"})

        event_types = [e[0] for e in events]
        assert "step_start" in event_types
        assert "step_complete" in event_types

    @pytest.mark.asyncio
    async def test_event_order_on_simple_workflow(self):
        """Events should follow: step_start → step_complete → output."""
        events: list[tuple[str, str, dict]] = []

        writer = make_agent("writer")
        steps = [
            WorkflowStep(agent="writer", step_type=StepType.SEQUENTIAL),
        ]
        engine = WorkflowEngine(steps)
        engine.on_event(lambda t, a, d: events.append((t, a, d)))

        await engine.execute({"writer": writer}, {"task": "test"})

        event_types = [e[0] for e in events]
        # step_start should come before step_complete
        assert event_types.index("step_start") < event_types.index("step_complete")
        # step_complete should come before output
        assert event_types.index("step_complete") < event_types.index("output")


class TestCheckpointSavedEvent:
    """Tests for CHECKPOINT_SAVED event emission."""

    @pytest.mark.asyncio
    async def test_checkpoint_saved_event_emitted(self):
        """checkpoint_saved event should be emitted when checkpoint is saved."""
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
            ),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileCheckpointStorage(directory=tmpdir)
            engine = WorkflowEngine(steps)
            engine.on_event(lambda t, a, d: events.append((t, a, d)))

            result = await engine.execute(
                {"writer": writer},
                {"task": "test"},
                checkpoint_storage=storage,
                session_id="sess-evt",
            )

            assert result.status == WorkflowStatus.PAUSED

            cp_events = [e for e in events if e[0] == "checkpoint_saved"]
            assert len(cp_events) == 1
            assert "checkpoint_id" in cp_events[0][2]
            assert cp_events[0][2]["session_id"] == "sess-evt"
            assert cp_events[0][2]["step_index"] == 1

    @pytest.mark.asyncio
    async def test_gate_requested_event_still_works(self):
        """gate_requested event should still be emitted for gated steps."""
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
                gate_description="Review",
            ),
        ]

        engine = WorkflowEngine(steps)
        engine.on_event(lambda t, a, d: events.append((t, a, d)))

        await engine.execute({"writer": writer}, {"task": "test"})

        gate_events = [e for e in events if e[0] == "gate_requested"]
        assert len(gate_events) == 1
        assert gate_events[0][2]["gate_id"] == "gate"


class TestApprovalEvent:
    """Tests for APPROVAL event emission during resume."""

    @pytest.mark.asyncio
    async def test_approval_event_emitted_on_resume(self):
        """approval event should be emitted when responses are applied during resume."""
        events: list[tuple[str, str, dict]] = []

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
        engine.on_event(lambda t, a, d: events.append((t, a, d)))

        # Create a checkpoint at the gated step
        checkpoint = WorkflowCheckpoint(
            session_id="sess-appr",
            step_index=0,
            state={
                "task": "test",
                "awaiting_gate_approval": True,
                "pending_gate_id": "gate",
            },
            current_agent_id="gate",
            current_step_type="gated",
        )

        result = await engine.resume(
            {"reviewer": reviewer},
            checkpoint,
            responses={"approval": True},
        )

        assert result.status == WorkflowStatus.COMPLETED

        approval_events = [e for e in events if e[0] == "approval"]
        assert len(approval_events) == 1
        assert approval_events[0][1] == "gate"  # agent_id
        assert approval_events[0][2]["gate_id"] == "gate"
        assert approval_events[0][2]["responses"] == {"approval": True}

    @pytest.mark.asyncio
    async def test_no_approval_event_without_responses(self):
        """No approval event should be emitted when resume has no responses."""
        events: list[tuple[str, str, dict]] = []

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
        engine.on_event(lambda t, a, d: events.append((t, a, d)))

        checkpoint = WorkflowCheckpoint(
            session_id="sess-no-appr",
            step_index=0,
            state={"task": "test"},
            current_agent_id="gate",
            current_step_type="gated",
        )

        await engine.resume(
            {"reviewer": reviewer},
            checkpoint,
        )

        approval_events = [e for e in events if e[0] == "approval"]
        assert len(approval_events) == 0


class TestEventOrderFullFlow:
    """Tests for complete event ordering across execute+resume."""

    @pytest.mark.asyncio
    async def test_full_execute_event_sequence(self):
        """Full workflow should emit events in correct order."""
        events: list[tuple[str, str, dict]] = []

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
            engine.on_event(lambda t, a, d: events.append((t, a, d)))

            # Phase 1: Execute until gate
            result = await engine.execute(
                {"writer": writer, "reviewer": reviewer},
                {"task": "test"},
                checkpoint_storage=storage,
                session_id="sess-full",
            )
            assert result.status == WorkflowStatus.PAUSED

            event_types_phase1 = [e[0] for e in events]
            assert "step_start" in event_types_phase1
            assert "step_complete" in event_types_phase1
            assert "gate_requested" in event_types_phase1
            assert "checkpoint_saved" in event_types_phase1

            # Phase 2: Resume
            events.clear()
            checkpoint = await storage.load("sess-full")
            result2 = await engine.resume(
                {"writer": writer, "reviewer": reviewer},
                checkpoint,
                responses={"approval": True},
            )
            assert result2.status == WorkflowStatus.COMPLETED

            event_types_phase2 = [e[0] for e in events]
            assert "approval" in event_types_phase2
            assert "step_start" in event_types_phase2
            assert "step_complete" in event_types_phase2
            assert "output" in event_types_phase2

            # approval should come before step_start (of the next step)
            assert event_types_phase2.index("approval") < event_types_phase2.index("step_start")
            # output should be last
            assert event_types_phase2.index("output") == len(event_types_phase2) - 1
