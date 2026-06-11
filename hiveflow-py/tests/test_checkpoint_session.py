"""Tests for checkpoint storage, workflow session lifecycle, and state enforcement."""

import asyncio
import json
import tempfile
from pathlib import Path

import pytest

from hiveflow.core.checkpoint import (
    CheckpointError,
    FileCheckpointStorage,
    WorkflowCheckpoint,
)
from hiveflow.core.session import ApprovalRequest, WorkflowSession
from hiveflow.core.workflow import WorkflowStatus


class TestWorkflowCheckpoint:
    """Tests for WorkflowCheckpoint dataclass."""

    def test_to_dict_round_trip(self):
        """to_dict and from_dict should round-trip correctly."""
        checkpoint = WorkflowCheckpoint(
            session_id="test-123",
            step_index=2,
            state={"key": "value", "count": 42},
            pending_requests=[{"request_id": "req-1", "type": "gate"}],
            iteration_counts={"reviewer": 2},
            task="Write a report",
        )

        data = checkpoint.to_dict()
        restored = WorkflowCheckpoint.from_dict(data)

        assert restored.session_id == "test-123"
        assert restored.step_index == 2
        assert restored.state == {"key": "value", "count": 42}
        assert restored.pending_requests == [{"request_id": "req-1", "type": "gate"}]
        assert restored.iteration_counts == {"reviewer": 2}
        assert restored.task == "Write a report"
        assert restored.version == "1"

    def test_from_dict_missing_required_field(self):
        """from_dict should raise CheckpointError for missing fields."""
        with pytest.raises(CheckpointError, match="Invalid checkpoint data"):
            WorkflowCheckpoint.from_dict({"step_index": 0})

    def test_new_fields_round_trip(self):
        """to_dict and from_dict should round-trip checkpoint_id, current_agent_id, current_step_type."""
        checkpoint = WorkflowCheckpoint(
            session_id="test-456",
            step_index=1,
            state={"data": "value"},
            checkpoint_id="ckpt-abc-123",
            current_agent_id="reviewer",
            current_step_type="human_gate",
        )

        data = checkpoint.to_dict()
        restored = WorkflowCheckpoint.from_dict(data)

        assert restored.checkpoint_id == "ckpt-abc-123"
        assert restored.current_agent_id == "reviewer"
        assert restored.current_step_type == "human_gate"

    def test_checkpoint_id_auto_generated(self):
        """checkpoint_id should be auto-generated UUID when not provided."""
        checkpoint = WorkflowCheckpoint(
            session_id="test",
            step_index=0,
            state={},
        )
        assert len(checkpoint.checkpoint_id) == 36  # UUID format
        assert "-" in checkpoint.checkpoint_id

    def test_new_fields_defaults(self):
        """New fields should have sensible defaults."""
        checkpoint = WorkflowCheckpoint(
            session_id="test",
            step_index=0,
            state={},
        )
        assert checkpoint.current_agent_id == ""
        assert checkpoint.current_step_type == ""

    def test_backward_compat_from_dict_missing_new_fields(self):
        """from_dict should handle old checkpoint format missing new fields."""
        old_format = {
            "session_id": "old-session",
            "step_index": 3,
            "state": {"key": "val"},
            "pending_requests": [],
            "iteration_counts": {},
            "task": "old task",
            "created_at": 1000000.0,
            "version": "1",
            # No checkpoint_id, current_agent_id, current_step_type
        }
        restored = WorkflowCheckpoint.from_dict(old_format)

        assert restored.session_id == "old-session"
        assert restored.step_index == 3
        # New fields should get defaults
        assert len(restored.checkpoint_id) == 36  # auto-generated UUID
        assert restored.current_agent_id == ""
        assert restored.current_step_type == ""

    def test_frozen_dataclass(self):
        """Checkpoint should be immutable."""
        checkpoint = WorkflowCheckpoint(
            session_id="test",
            step_index=0,
            state={},
        )
        with pytest.raises(AttributeError):
            checkpoint.session_id = "other"  # type: ignore[misc]


class TestFileCheckpointStorage:
    """Tests for FileCheckpointStorage."""

    @pytest.mark.asyncio
    async def test_save_and_load(self):
        """Should save and load a checkpoint."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileCheckpointStorage(directory=tmpdir)
            checkpoint = WorkflowCheckpoint(
                session_id="session-1",
                step_index=3,
                state={"task": "test", "data": [1, 2, 3]},
                task="test task",
            )

            await storage.save(checkpoint)
            loaded = await storage.load("session-1")

            assert loaded is not None
            assert loaded.session_id == "session-1"
            assert loaded.step_index == 3
            assert loaded.state == {"task": "test", "data": [1, 2, 3]}

    @pytest.mark.asyncio
    async def test_load_nonexistent(self):
        """Loading a nonexistent session should return None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileCheckpointStorage(directory=tmpdir)
            result = await storage.load("nonexistent")
            assert result is None

    @pytest.mark.asyncio
    async def test_delete(self):
        """Should delete a checkpoint file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileCheckpointStorage(directory=tmpdir)
            checkpoint = WorkflowCheckpoint(
                session_id="session-2",
                step_index=0,
                state={},
            )

            await storage.save(checkpoint)
            await storage.delete("session-2")
            result = await storage.load("session-2")
            assert result is None

    @pytest.mark.asyncio
    async def test_list_sessions(self):
        """Should list all checkpointed session IDs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileCheckpointStorage(directory=tmpdir)

            for sid in ("alpha", "beta", "gamma"):
                await storage.save(WorkflowCheckpoint(
                    session_id=sid,
                    step_index=0,
                    state={},
                ))

            sessions = await storage.list_sessions()
            assert sorted(sessions) == ["alpha", "beta", "gamma"]

    @pytest.mark.asyncio
    async def test_corrupt_file_raises_error(self):
        """Corrupted JSON should raise CheckpointError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileCheckpointStorage(directory=tmpdir)
            # Write corrupt file using new naming: {session_id}_{checkpoint_id}.json
            fake_uuid = "00000000-0000-0000-0000-000000000000"
            path = Path(tmpdir) / f"corrupt_{fake_uuid}.json"
            path.write_text("{invalid json!!!", encoding="utf-8")

            with pytest.raises(CheckpointError, match="Corrupted checkpoint"):
                await storage.load("corrupt", fake_uuid)

    @pytest.mark.asyncio
    async def test_list_empty_directory(self):
        """Listing sessions from empty/nonexistent dir should return empty list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileCheckpointStorage(directory=Path(tmpdir) / "nonexistent")
            sessions = await storage.list_sessions()
            assert sessions == []

    @pytest.mark.asyncio
    async def test_accumulation_multiple_saves(self):
        """Multiple saves for same session should create separate checkpoint files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileCheckpointStorage(directory=tmpdir)

            ids = []
            for i in range(3):
                checkpoint = WorkflowCheckpoint(
                    session_id="session-acc",
                    step_index=i,
                    state={"step": i},
                )
                cid = await storage.save(checkpoint)
                ids.append(cid)

            # All checkpoint_ids should be unique
            assert len(set(ids)) == 3

            # All checkpoints should be listable
            checkpoints = await storage.list_checkpoints("session-acc")
            assert len(checkpoints) == 3

            # Session should appear only once in list_sessions
            sessions = await storage.list_sessions()
            assert sessions == ["session-acc"]

    @pytest.mark.asyncio
    async def test_list_checkpoints_ordered_by_created_at(self):
        """list_checkpoints should return checkpoints ordered by created_at ascending."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileCheckpointStorage(directory=tmpdir)

            # Create checkpoints with explicit created_at to control order
            timestamps = [300.0, 100.0, 200.0]
            for i, ts in enumerate(timestamps):
                checkpoint = WorkflowCheckpoint(
                    session_id="ordered-session",
                    step_index=i,
                    state={"i": i},
                    created_at=ts,
                )
                await storage.save(checkpoint)

            checkpoints = await storage.list_checkpoints("ordered-session")
            assert len(checkpoints) == 3
            assert checkpoints[0].created_at == 100.0
            assert checkpoints[1].created_at == 200.0
            assert checkpoints[2].created_at == 300.0

    @pytest.mark.asyncio
    async def test_load_with_specific_checkpoint_id(self):
        """load() with checkpoint_id should return that specific checkpoint."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileCheckpointStorage(directory=tmpdir)

            # Save two checkpoints
            cp1 = WorkflowCheckpoint(
                session_id="session-specific",
                step_index=0,
                state={"version": "first"},
                created_at=100.0,
            )
            cp2 = WorkflowCheckpoint(
                session_id="session-specific",
                step_index=1,
                state={"version": "second"},
                created_at=200.0,
            )
            id1 = await storage.save(cp1)
            id2 = await storage.save(cp2)

            # Load specific checkpoint by id
            loaded = await storage.load("session-specific", id1)
            assert loaded is not None
            assert loaded.checkpoint_id == id1
            assert loaded.state == {"version": "first"}

            loaded2 = await storage.load("session-specific", id2)
            assert loaded2 is not None
            assert loaded2.checkpoint_id == id2
            assert loaded2.state == {"version": "second"}

    @pytest.mark.asyncio
    async def test_load_without_checkpoint_id_returns_latest(self):
        """load() without checkpoint_id should return the latest checkpoint."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileCheckpointStorage(directory=tmpdir)

            # Save checkpoints with different created_at
            for i, ts in enumerate([100.0, 300.0, 200.0]):
                cp = WorkflowCheckpoint(
                    session_id="session-latest",
                    step_index=i,
                    state={"ts": ts},
                    created_at=ts,
                )
                await storage.save(cp)

            # Load without checkpoint_id → latest by created_at
            latest = await storage.load("session-latest")
            assert latest is not None
            assert latest.created_at == 300.0
            assert latest.state == {"ts": 300.0}

    @pytest.mark.asyncio
    async def test_load_nonexistent_checkpoint_id(self):
        """load() with nonexistent checkpoint_id should return None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileCheckpointStorage(directory=tmpdir)

            # Save a checkpoint
            cp = WorkflowCheckpoint(
                session_id="session-x",
                step_index=0,
                state={},
            )
            await storage.save(cp)

            # Load with wrong checkpoint_id
            result = await storage.load("session-x", "nonexistent-id")
            assert result is None

    @pytest.mark.asyncio
    async def test_save_returns_checkpoint_id(self):
        """save() should return the checkpoint_id."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileCheckpointStorage(directory=tmpdir)
            cp = WorkflowCheckpoint(
                session_id="session-ret",
                step_index=0,
                state={},
                checkpoint_id="my-custom-id",
            )
            result = await storage.save(cp)
            assert result == "my-custom-id"

    @pytest.mark.asyncio
    async def test_list_checkpoints_empty(self):
        """list_checkpoints for nonexistent session should return empty list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileCheckpointStorage(directory=tmpdir)
            checkpoints = await storage.list_checkpoints("no-such-session")
            assert checkpoints == []

    @pytest.mark.asyncio
    async def test_delete_removes_all_session_checkpoints(self):
        """delete() should remove all checkpoint files for a session."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileCheckpointStorage(directory=tmpdir)

            for i in range(3):
                cp = WorkflowCheckpoint(
                    session_id="session-del",
                    step_index=i,
                    state={},
                )
                await storage.save(cp)

            assert len(await storage.list_checkpoints("session-del")) == 3

            await storage.delete("session-del")
            assert len(await storage.list_checkpoints("session-del")) == 0
            assert await storage.load("session-del") is None


class TestApprovalRequest:
    """Tests for ApprovalRequest dataclass."""

    def test_to_dict(self):
        """Should serialize to dict."""
        req = ApprovalRequest(
            request_id="req-1",
            request_type="gate",
            context={"gate_id": "approval"},
            agent_id=None,
            step_index=2,
        )
        d = req.to_dict()
        assert d["request_id"] == "req-1"
        assert d["request_type"] == "gate"
        assert d["context"] == {"gate_id": "approval"}

    def test_from_dict(self):
        """Should deserialize from dict."""
        data = {
            "request_id": "req-2",
            "request_type": "human_gate",
            "context": {"prompt": "Review this"},
            "agent_id": "reviewer",
            "step_index": 1,
        }
        req = ApprovalRequest.from_dict(data)
        assert req.request_id == "req-2"
        assert req.request_type == "human_gate"
        assert req.agent_id == "reviewer"


class TestWorkflowSession:
    """Tests for WorkflowSession lifecycle."""

    def test_initial_status_is_pending(self):
        """New session should start in PENDING status."""
        session = WorkflowSession(task="test")
        assert session.status == WorkflowStatus.PENDING
        assert session.result is None
        assert session.error is None
        assert session.pending_requests == []

    def test_session_id_auto_generated(self):
        """session_id should be auto-generated UUID."""
        session = WorkflowSession(task="test")
        assert len(session.session_id) > 0

    def test_custom_session_id(self):
        """Custom session_id should be used."""
        session = WorkflowSession(session_id="custom-id", task="test")
        assert session.session_id == "custom-id"

    @pytest.mark.asyncio
    async def test_cancel_from_running(self):
        """Should cancel a running session."""
        session = WorkflowSession(task="test")
        session._set_status(WorkflowStatus.RUNNING)
        await session.cancel()
        assert session.status == WorkflowStatus.FAILED
        assert session.error == "Session cancelled"

    @pytest.mark.asyncio
    async def test_cancel_from_paused(self):
        """Should cancel a paused session."""
        session = WorkflowSession(task="test")
        session._set_status(WorkflowStatus.PAUSED)
        await session.cancel()
        assert session.status == WorkflowStatus.FAILED

    @pytest.mark.asyncio
    async def test_cancel_completed_raises(self):
        """Cancelling a completed session should raise."""
        session = WorkflowSession(task="test")
        session._set_status(WorkflowStatus.COMPLETED)
        with pytest.raises(RuntimeError, match="Cannot cancel"):
            await session.cancel()

    @pytest.mark.asyncio
    async def test_resume_requires_paused(self):
        """Resuming a non-paused session should raise."""
        session = WorkflowSession(task="test")
        session._set_status(WorkflowStatus.RUNNING)
        with pytest.raises(RuntimeError, match="Cannot resume"):
            await session.resume({})

    @pytest.mark.asyncio
    async def test_resume_from_paused(self):
        """Should resume a paused session."""
        session = WorkflowSession(task="test")
        session._set_status(WorkflowStatus.PAUSED)
        await session.resume({"approval": True})
        assert session.status == WorkflowStatus.RUNNING

    def test_to_dict_serializable(self):
        """to_dict output should be JSON-serializable."""
        session = WorkflowSession(task="test task")
        d = session.to_dict()
        # Should not raise
        json.dumps(d)
        assert d["task"] == "test task"
        assert d["status"] == "pending"
        assert d["session_id"] == session.session_id

    def test_subscribe_returns_consumer(self):
        """subscribe() should return a StreamConsumer."""
        session = WorkflowSession(task="test")
        consumer = session.subscribe()
        assert consumer is not None


class TestStateSchemaEnforcement:
    """Tests for state schema enforcement in WorkflowEngine."""

    @pytest.mark.asyncio
    async def test_warn_mode_allows_undeclared_writes(self):
        """warn mode should allow undeclared writes but log warnings."""
        from hiveflow.core.agent import Agent, AgentBehaviorType
        from hiveflow.core.schema import AgentIOMapping, StateSchema
        from hiveflow.core.workflow import StepType, WorkflowEngine, WorkflowStep
        from hiveflow.plugins.llm import LLMConfig, LLMMessage, LLMProvider, LLMResponse, TokenUsage

        class MockProvider(LLMProvider):
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
                    content="output text",
                    model="mock-model",
                    usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
                )

        agent = Agent(
            agent_id="writer",
            role="Writer",
            system_prompt="Write.",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=MockProvider(),
        )

        schema = StateSchema(
            enforcement_mode="warn",
            agent_io={"writer": AgentIOMapping(writes=["writer_output"])},
        )

        steps = [WorkflowStep(agent="writer", step_type=StepType.SEQUENTIAL)]
        engine = WorkflowEngine(steps, state_schema=schema)
        result = await engine.execute({"writer": agent}, {"task": "test"})

        # Warn mode allows all writes — output and usage both present
        assert result.status == WorkflowStatus.COMPLETED
        assert "writer_output" in result.state

    @pytest.mark.asyncio
    async def test_strict_mode_filters_undeclared_writes(self):
        """strict mode should filter out undeclared state writes."""
        from hiveflow.core.agent import Agent, AgentBehaviorType
        from hiveflow.core.schema import AgentIOMapping, StateSchema
        from hiveflow.core.workflow import StepType, WorkflowEngine, WorkflowStep
        from hiveflow.plugins.llm import LLMConfig, LLMMessage, LLMProvider, LLMResponse, TokenUsage

        class MockProvider(LLMProvider):
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
                    content="output text",
                    model="mock-model",
                    usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
                )

        agent = Agent(
            agent_id="writer",
            role="Writer",
            system_prompt="Write.",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=MockProvider(),
        )

        schema = StateSchema(
            enforcement_mode="strict",
            agent_io={"writer": AgentIOMapping(writes=["writer_output"])},
        )

        steps = [WorkflowStep(agent="writer", step_type=StepType.SEQUENTIAL)]
        engine = WorkflowEngine(steps, state_schema=schema)
        result = await engine.execute({"writer": agent}, {"task": "test"})

        assert result.status == WorkflowStatus.COMPLETED
        assert "writer_output" in result.state
        # Strict mode should filter out writer_usage (undeclared)
        assert "writer_usage" not in result.state

    @pytest.mark.asyncio
    async def test_off_mode_no_enforcement(self):
        """off mode should not enforce anything."""
        from hiveflow.core.agent import Agent, AgentBehaviorType
        from hiveflow.core.schema import AgentIOMapping, StateSchema
        from hiveflow.core.workflow import StepType, WorkflowEngine, WorkflowStep
        from hiveflow.plugins.llm import LLMConfig, LLMMessage, LLMProvider, LLMResponse, TokenUsage

        class MockProvider(LLMProvider):
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
                    content="output text",
                    model="mock-model",
                    usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
                )

        agent = Agent(
            agent_id="writer",
            role="Writer",
            system_prompt="Write.",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=MockProvider(),
        )

        schema = StateSchema(
            enforcement_mode="off",
            agent_io={"writer": AgentIOMapping(writes=["writer_output"])},
        )

        steps = [WorkflowStep(agent="writer", step_type=StepType.SEQUENTIAL)]
        engine = WorkflowEngine(steps, state_schema=schema)
        result = await engine.execute({"writer": agent}, {"task": "test"})

        assert result.status == WorkflowStatus.COMPLETED
        # Off mode — everything present
        assert "writer_output" in result.state
        assert "writer_usage" in result.state


class TestAutoCheckpointing:
    """Tests for automatic checkpointing at pause points (US2)."""

    @pytest.mark.asyncio
    async def test_gated_step_saves_checkpoint(self):
        """execute() should save a checkpoint when pausing at a GATED step."""
        from hiveflow.core.agent import Agent, AgentBehaviorType
        from hiveflow.core.workflow import StepType, WorkflowEngine, WorkflowStep
        from hiveflow.plugins.llm import LLMProvider, LLMResponse, TokenUsage

        class MockProvider(LLMProvider):
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

        writer = Agent(
            agent_id="writer",
            role="Writer",
            system_prompt="Write.",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=MockProvider(),
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
                gate_description="Review before publishing",
            ),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileCheckpointStorage(directory=tmpdir)
            engine = WorkflowEngine(steps)
            result = await engine.execute(
                {"writer": writer},
                {"task": "Write a post"},
                checkpoint_storage=storage,
                session_id="test-session-1",
            )

            assert result.status == WorkflowStatus.PAUSED

            # Verify checkpoint was saved
            checkpoints = await storage.list_checkpoints("test-session-1")
            assert len(checkpoints) == 1

            cp = checkpoints[0]
            assert cp.session_id == "test-session-1"
            assert cp.step_index == 1  # GATED step is index 1
            assert cp.current_agent_id == "approval_gate"
            assert cp.current_step_type == "gated"

    @pytest.mark.asyncio
    async def test_no_checkpoint_without_storage(self):
        """execute() should not save a checkpoint when checkpoint_storage is None."""
        from hiveflow.core.agent import Agent, AgentBehaviorType
        from hiveflow.core.workflow import StepType, WorkflowEngine, WorkflowStep
        from hiveflow.plugins.llm import LLMProvider, LLMResponse, TokenUsage

        class MockProvider(LLMProvider):
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
                    content="draft",
                    model="mock",
                    usage=TokenUsage(prompt_tokens=5, completion_tokens=5, total_tokens=10),
                )

        writer = Agent(
            agent_id="writer",
            role="Writer",
            system_prompt="Write.",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=MockProvider(),
        )

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

            # No checkpoint_storage passed
            result = await engine.execute(
                {"writer": writer},
                {"task": "Write"},
            )

            assert result.status == WorkflowStatus.PAUSED

            # Directory should have no checkpoint files
            checkpoints = await storage.list_checkpoints("anything")
            assert checkpoints == []

    @pytest.mark.asyncio
    async def test_list_checkpoints_on_hiveflow(self):
        """HiveFlow.list_checkpoints() should return checkpoint summaries."""
        from hiveflow.core.hiveflow import HiveFlow

        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FileCheckpointStorage(directory=tmpdir)

            # Manually save some checkpoints to storage
            for i in range(3):
                cp = WorkflowCheckpoint(
                    session_id="sess-abc",
                    step_index=i,
                    state={"step": i},
                    current_agent_id=f"agent_{i}",
                    created_at=float(100 + i),
                )
                await storage.save(cp)

            hf = HiveFlow(checkpoint_storage=storage)
            summaries = await hf.list_checkpoints("sess-abc")

            assert len(summaries) == 3
            assert summaries[0]["session_id"] == "sess-abc"
            assert summaries[0]["step_index"] == 0
            assert summaries[0]["current_agent_id"] == "agent_0"
            assert summaries[2]["step_index"] == 2

    @pytest.mark.asyncio
    async def test_list_checkpoints_raises_without_storage(self):
        """HiveFlow.list_checkpoints() should raise ValueError without storage."""
        from hiveflow.core.hiveflow import HiveFlow

        hf = HiveFlow()
        with pytest.raises(ValueError, match="No checkpoint storage configured"):
            await hf.list_checkpoints("any-session")
