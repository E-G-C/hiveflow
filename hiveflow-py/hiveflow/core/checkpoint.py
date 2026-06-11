"""Workflow Checkpointing - Persist and resume workflow state across process restarts.

Provides durable persistence of workflow state at human gates and gated steps,
enabling workflows to be resumed after process restarts without re-executing
completed steps.
"""

import contextlib
import json
import os
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import structlog

logger = structlog.get_logger()


class CheckpointError(Exception):
    """Raised when checkpoint operations fail (save, load, corruption)."""


@dataclass(frozen=True)
class WorkflowCheckpoint:
    """Serialized snapshot of a paused workflow's state.

    Contains everything needed to resume a workflow from where it left off,
    including the current step, accumulated state, pending approval requests,
    and iteration counters.
    """

    session_id: str
    step_index: int
    state: dict[str, Any]
    checkpoint_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    current_agent_id: str = ""
    current_step_type: str = ""
    pending_requests: list[dict[str, Any]] = field(default_factory=list)
    iteration_counts: dict[str, int] = field(default_factory=dict)
    team_config: dict[str, Any] = field(default_factory=dict)
    task: str = ""
    created_at: float = field(default_factory=time.time)
    version: str = "1"

    def to_dict(self) -> dict[str, Any]:
        """Serialize checkpoint to a JSON-compatible dictionary."""
        return {
            "session_id": self.session_id,
            "step_index": self.step_index,
            "state": self.state,
            "checkpoint_id": self.checkpoint_id,
            "current_agent_id": self.current_agent_id,
            "current_step_type": self.current_step_type,
            "pending_requests": self.pending_requests,
            "iteration_counts": self.iteration_counts,
            "team_config": self.team_config,
            "task": self.task,
            "created_at": self.created_at,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkflowCheckpoint":
        """Deserialize checkpoint from a dictionary.

        Args:
            data: Dictionary representation of a checkpoint

        Returns:
            WorkflowCheckpoint instance

        Raises:
            CheckpointError: If data is missing required fields or malformed
        """
        try:
            return cls(
                session_id=data["session_id"],
                step_index=data["step_index"],
                state=data.get("state", {}),
                checkpoint_id=data.get("checkpoint_id", str(uuid.uuid4())),
                current_agent_id=data.get("current_agent_id", ""),
                current_step_type=data.get("current_step_type", ""),
                pending_requests=data.get("pending_requests", []),
                iteration_counts=data.get("iteration_counts", {}),
                team_config=data.get("team_config", {}),
                task=data.get("task", ""),
                created_at=data.get("created_at", time.time()),
                version=data.get("version", "1"),
            )
        except (KeyError, TypeError) as e:
            raise CheckpointError(f"Invalid checkpoint data: {e}") from e


@runtime_checkable
class CheckpointStorage(Protocol):
    """Protocol for checkpoint storage backends.

    Implementations must provide async save, load, delete, list_sessions,
    and list_checkpoints methods. Phase 1 provides FileCheckpointStorage;
    custom backends can be implemented by conforming to this protocol.
    """

    async def save(self, checkpoint: WorkflowCheckpoint) -> str:
        """Persist a checkpoint. Returns checkpoint_id."""
        ...

    async def load(
        self, session_id: str, checkpoint_id: str | None = None
    ) -> WorkflowCheckpoint | None:
        """Load a checkpoint.

        If checkpoint_id is None, returns the latest checkpoint for the session.
        If checkpoint_id is provided, returns that specific checkpoint.
        Returns None if not found.
        """
        ...

    async def delete(self, session_id: str) -> None:
        """Remove all checkpoints for a session."""
        ...

    async def list_sessions(self) -> list[str]:
        """List all session IDs that have checkpoints."""
        ...

    async def list_checkpoints(self, session_id: str) -> list[WorkflowCheckpoint]:
        """List all checkpoints for a session, ordered by created_at ascending."""
        ...


class FileCheckpointStorage:
    """File-based checkpoint storage using JSON files.

    Stores one JSON file per checkpoint in the configured directory,
    using {session_id}_{checkpoint_id}.json naming for accumulation.
    Default directory: .hiveflow/checkpoints
    """

    def __init__(self, directory: str | Path = ".hiveflow/checkpoints") -> None:
        """Initialize file checkpoint storage.

        Args:
            directory: Directory to store checkpoint files
        """
        self.directory = Path(directory)

    def _sanitize_id(self, id_str: str) -> str:
        """Sanitize an ID string to prevent path traversal."""
        return id_str.replace("/", "_").replace("\\", "_").replace("..", "_")

    def _checkpoint_path(self, session_id: str, checkpoint_id: str) -> Path:
        """Get the file path for a specific checkpoint."""
        safe_session = self._sanitize_id(session_id)
        safe_checkpoint = self._sanitize_id(checkpoint_id)
        return self.directory / f"{safe_session}_{safe_checkpoint}.json"

    def _session_glob(self, session_id: str) -> list[Path]:
        """Get all checkpoint files for a session."""
        safe_session = self._sanitize_id(session_id)
        if not self.directory.exists():
            return []
        return list(self.directory.glob(f"{safe_session}_*.json"))

    async def save(self, checkpoint: WorkflowCheckpoint) -> str:
        """Persist a checkpoint to a JSON file. Returns checkpoint_id.

        Args:
            checkpoint: The checkpoint to save

        Returns:
            The checkpoint_id of the saved checkpoint

        Raises:
            CheckpointError: If save fails
        """
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self._checkpoint_path(checkpoint.session_id, checkpoint.checkpoint_id)
            data = json.dumps(checkpoint.to_dict(), indent=2, default=str)
            # Atomic write: write to temp file in same dir, then rename
            fd, tmp_path = tempfile.mkstemp(dir=str(self.directory), suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(data)
                os.replace(tmp_path, str(path))
            except BaseException:
                with contextlib.suppress(OSError):
                    os.unlink(tmp_path)
                raise
            logger.debug(
                "Checkpoint saved for session %s (checkpoint %s) at step %d",
                checkpoint.session_id,
                checkpoint.checkpoint_id,
                checkpoint.step_index,
            )
            return checkpoint.checkpoint_id
        except (OSError, TypeError, ValueError) as e:
            raise CheckpointError(
                f"Failed to save checkpoint for session {checkpoint.session_id}: {e}"
            ) from e

    async def load(
        self, session_id: str, checkpoint_id: str | None = None
    ) -> WorkflowCheckpoint | None:
        """Load a checkpoint from a JSON file.

        Args:
            session_id: Session to load
            checkpoint_id: Specific checkpoint to load. If None, loads latest.

        Returns:
            WorkflowCheckpoint or None if not found

        Raises:
            CheckpointError: If file exists but is corrupted
        """
        if checkpoint_id is not None:
            path = self._checkpoint_path(session_id, checkpoint_id)
            if not path.exists():
                return None
            return self._read_checkpoint(path, session_id)

        # Load latest checkpoint by created_at
        checkpoints = await self.list_checkpoints(session_id)
        if not checkpoints:
            return None
        return checkpoints[-1]

    def _read_checkpoint(self, path: Path, session_id: str) -> WorkflowCheckpoint:
        """Read and deserialize a checkpoint file."""
        try:
            raw = path.read_text(encoding="utf-8")
            data = json.loads(raw)
            return WorkflowCheckpoint.from_dict(data)
        except json.JSONDecodeError as e:
            raise CheckpointError(f"Corrupted checkpoint file for session {session_id}: {e}") from e
        except OSError as e:
            raise CheckpointError(f"Failed to read checkpoint for session {session_id}: {e}") from e

    async def delete(self, session_id: str) -> None:
        """Remove all checkpoint files for a session.

        Args:
            session_id: Session to delete
        """
        for path in self._session_glob(session_id):
            try:
                path.unlink()
            except OSError as e:
                logger.warning(
                    "Failed to delete checkpoint file %s: %s",
                    path,
                    e,
                )
        logger.debug("Checkpoints deleted for session %s", session_id)

    async def list_sessions(self) -> list[str]:
        """List all session IDs that have checkpoints.

        Returns:
            Sorted list of unique session IDs with stored checkpoints
        """
        if not self.directory.exists():
            return []

        session_ids: set[str] = set()
        for path in self.directory.glob("*.json"):
            stem = path.stem
            # Filename format: {session_id}_{checkpoint_id}.json
            # checkpoint_id is a UUID (36 chars), so session_id is stem[:-37]
            if len(stem) > 37 and stem[-37] == "_":
                session_ids.add(stem[:-37])
        return sorted(session_ids)

    async def list_checkpoints(self, session_id: str) -> list[WorkflowCheckpoint]:
        """List all checkpoints for a session, ordered by created_at ascending.

        Args:
            session_id: Session to list checkpoints for

        Returns:
            List of WorkflowCheckpoint ordered by created_at
        """
        paths = self._session_glob(session_id)
        checkpoints = []
        for path in paths:
            try:
                checkpoint = self._read_checkpoint(path, session_id)
                checkpoints.append(checkpoint)
            except CheckpointError:
                logger.warning("Skipping corrupted checkpoint file: %s", path)
        checkpoints.sort(key=lambda c: c.created_at)
        return checkpoints
