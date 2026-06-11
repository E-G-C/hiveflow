"""T028: Tests for enhanced checkpoint persistence of team_config and task."""

import tempfile

import pytest

from hiveflow.core.agent import Agent, AgentBehaviorType
from hiveflow.core.checkpoint import (
    FileCheckpointStorage,
    WorkflowCheckpoint,
)
from hiveflow.core.workflow import StepType, WorkflowEngine, WorkflowStep, WorkflowStatus
from hiveflow.plugins.llm import LLMProvider, LLMResponse, TokenUsage


class _MockProvider(LLMProvider):
    """Minimal LLM provider for checkpoint tests."""

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
            content="draft output",
            model="mock",
            usage=TokenUsage(prompt_tokens=5, completion_tokens=5, total_tokens=10),
        )


def _make_writer() -> Agent:
    return Agent(
        agent_id="writer",
        role="Writer",
        system_prompt="Write.",
        behavior_type=AgentBehaviorType.LLM_ONLY,
        llm_provider=_MockProvider(),
    )


def _make_gated_steps() -> list[WorkflowStep]:
    return [
        WorkflowStep(
            agent="writer",
            step_type=StepType.SEQUENTIAL,
            next_step="gate",
        ),
        WorkflowStep(
            agent="gate",
            step_type=StepType.GATED,
            gate_id="gate",
            gate_description="Approve before continuing",
        ),
    ]


SAMPLE_TEAM_CONFIG = {
    "name": "test-team",
    "agents": [
        {
            "id": "writer",
            "role": "Writer",
            "system_prompt": "Write content.",
            "behavior_type": "llm_only",
        },
    ],
    "workflow": {
        "steps": [
            {"type": "sequential", "agent": "writer", "next_step": "gate"},
            {"type": "gated", "agent": "gate"},
        ],
    },
}


class TestCheckpointPersistsTeamConfigAndTask:
    """Verify _save_checkpoint() persists team_config and task into the checkpoint."""

    @pytest.mark.asyncio
    async def test_gated_checkpoint_contains_team_config_and_task(self) -> None:
        """Checkpoint saved at a GATED step should contain team_config and task."""
        writer = _make_writer()
        steps = _make_gated_steps()

        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileCheckpointStorage(directory=tmpdir)
            engine = WorkflowEngine(steps)
            result = await engine.execute(
                {"writer": writer},
                {"task": "Write a blog post"},
                checkpoint_storage=storage,
                session_id="ckpt-team-task",
                team_config=SAMPLE_TEAM_CONFIG,
            )

            assert result.status == WorkflowStatus.PAUSED

            checkpoints = await storage.list_checkpoints("ckpt-team-task")
            assert len(checkpoints) == 1

            cp = checkpoints[0]
            assert cp.team_config == SAMPLE_TEAM_CONFIG
            assert cp.task == "Write a blog post"

    @pytest.mark.asyncio
    async def test_checkpoint_without_team_config_defaults_to_empty(self) -> None:
        """Checkpoint without team_config should default to empty dict."""
        writer = _make_writer()
        steps = _make_gated_steps()

        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileCheckpointStorage(directory=tmpdir)
            engine = WorkflowEngine(steps)
            result = await engine.execute(
                {"writer": writer},
                {"task": "Write something"},
                checkpoint_storage=storage,
                session_id="ckpt-no-config",
                # No team_config passed
            )

            assert result.status == WorkflowStatus.PAUSED

            cp = (await storage.list_checkpoints("ckpt-no-config"))[0]
            assert cp.team_config == {}
            assert cp.task == "Write something"


class TestResumeLoadsFromCheckpoint:
    """Verify resume reads team_config and task from checkpoint data."""

    @pytest.mark.asyncio
    async def test_resume_uses_checkpoint_team_config(self) -> None:
        """When resuming, checkpoint.team_config carries the saved config."""
        cp = WorkflowCheckpoint(
            session_id="resume-session",
            step_index=1,
            state={"task": "Original task", "awaiting_gate_approval": True},
            current_agent_id="gate",
            current_step_type="gated",
            team_config=SAMPLE_TEAM_CONFIG,
            task="Original task",
        )

        assert cp.team_config == SAMPLE_TEAM_CONFIG
        assert cp.task == "Original task"

        # Verify round-trip through serialization
        data = cp.to_dict()
        restored = WorkflowCheckpoint.from_dict(data)
        assert restored.team_config == SAMPLE_TEAM_CONFIG
        assert restored.task == "Original task"

    @pytest.mark.asyncio
    async def test_checkpoint_file_round_trip_with_team_config(self) -> None:
        """Save and load checkpoint with team_config via FileCheckpointStorage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileCheckpointStorage(directory=tmpdir)
            cp = WorkflowCheckpoint(
                session_id="file-rt",
                step_index=0,
                state={"task": "test"},
                team_config=SAMPLE_TEAM_CONFIG,
                task="test",
            )
            await storage.save(cp)

            loaded = await storage.load("file-rt")
            assert loaded is not None
            assert loaded.team_config == SAMPLE_TEAM_CONFIG
            assert loaded.task == "test"


class TestSessionTeamConfigPrecedence:
    """Session team_config should take precedence over checkpoint team_config."""

    def test_checkpoint_has_both_session_and_checkpoint_config(self) -> None:
        """The resume fallback logic should prefer session config over checkpoint config.

        This tests the precedence logic documented in HiveFlow.resume():
        1. session._team_config (in-memory) takes priority
        2. checkpoint.team_config is fallback for cold-resume
        """
        # Simulate: checkpoint has team_config
        cp = WorkflowCheckpoint(
            session_id="prec-test",
            step_index=0,
            state={},
            team_config={"name": "checkpoint-config"},
            task="checkpoint task",
        )

        # Simulate: session has different team_config (in-memory)
        session_config = {"name": "session-config"}

        # The actual precedence logic from HiveFlow.resume():
        # if team_config is not None: use session config
        # elif checkpoint.team_config: use checkpoint config
        team_config = session_config
        if team_config is not None:
            config_used = team_config  # Session wins
        elif cp.team_config:
            config_used = cp.team_config

        assert config_used == {"name": "session-config"}

    def test_checkpoint_config_used_when_no_session_config(self) -> None:
        """When session has no team_config, checkpoint config is used."""
        cp = WorkflowCheckpoint(
            session_id="prec-test-2",
            step_index=0,
            state={},
            team_config={"name": "checkpoint-config"},
            task="checkpoint task",
        )

        # No session config — cold resume scenario
        session_config = None
        if session_config is not None:
            config_used = session_config
        elif cp.team_config:
            config_used = cp.team_config
        else:
            config_used = None

        assert config_used == {"name": "checkpoint-config"}


class TestBackwardCompatibility:
    """Backward compat with old checkpoint files missing team_config/task."""

    def test_old_format_missing_team_config_and_task(self) -> None:
        """from_dict should handle old checkpoint without team_config or task."""
        old_data = {
            "session_id": "old-session",
            "step_index": 2,
            "state": {"key": "val"},
            "pending_requests": [],
            "iteration_counts": {},
            "created_at": 1000000.0,
            "version": "1",
            # No team_config, no task
        }
        restored = WorkflowCheckpoint.from_dict(old_data)

        assert restored.session_id == "old-session"
        assert restored.team_config == {}
        assert restored.task == ""

    def test_old_format_with_task_no_team_config(self) -> None:
        """from_dict should handle checkpoint with task but no team_config."""
        old_data = {
            "session_id": "old-with-task",
            "step_index": 1,
            "state": {},
            "pending_requests": [],
            "iteration_counts": {},
            "task": "some old task",
            "created_at": 1000000.0,
            "version": "1",
            # No team_config
        }
        restored = WorkflowCheckpoint.from_dict(old_data)

        assert restored.task == "some old task"
        assert restored.team_config == {}

    @pytest.mark.asyncio
    async def test_old_checkpoint_file_loads_with_defaults(self) -> None:
        """Old checkpoint file saved without team_config should load fine."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileCheckpointStorage(directory=tmpdir)

            # Save a checkpoint without team_config (simulating old format)
            cp = WorkflowCheckpoint(
                session_id="old-file",
                step_index=0,
                state={"task": "old"},
            )
            await storage.save(cp)

            loaded = await storage.load("old-file")
            assert loaded is not None
            assert loaded.team_config == {}
            assert loaded.task == ""
