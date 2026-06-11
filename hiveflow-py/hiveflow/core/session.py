"""Workflow Session - Handle to a running or completed workflow.

Provides session identity, status tracking, pause/resume operations,
event streaming, and checkpoint integration for workflow executions.
"""

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog

from hiveflow.core.streaming import StreamChannel, StreamConsumer
from hiveflow.core.workflow import WorkflowResult, WorkflowStatus

logger = structlog.get_logger()


@dataclass(frozen=True)
class ApprovalRequest:
    """A pending approval or gate request surfaced during workflow execution.

    Created when a workflow pauses at a human gate, gated step, or
    action_executor with require_approval policy.
    """

    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    request_type: str = ""  # "human_gate", "action_approval", "gate"
    context: dict[str, Any] = field(default_factory=dict)
    agent_id: str | None = None
    step_index: int = 0
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-compatible dictionary."""
        return {
            "request_id": self.request_id,
            "request_type": self.request_type,
            "context": self.context,
            "agent_id": self.agent_id,
            "step_index": self.step_index,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ApprovalRequest":
        """Deserialize from a dictionary."""
        return cls(
            request_id=data.get("request_id", str(uuid.uuid4())),
            request_type=data.get("request_type", ""),
            context=data.get("context", {}),
            agent_id=data.get("agent_id"),
            step_index=data.get("step_index", 0),
            created_at=data.get("created_at", time.time()),
        )


class WorkflowSession:
    """Handle to a running or completed workflow execution.

    Provides a stable identity (session_id), status tracking,
    result access, pending approval requests, resume/cancel
    operations, and real-time event streaming.

    State transitions::

        PENDING → RUNNING → COMPLETED
        PENDING → RUNNING → FAILED
        PENDING → RUNNING → PAUSED → RUNNING → COMPLETED
        PENDING → RUNNING → PAUSED → CANCELLED (via cancel())
    """

    def __init__(
        self,
        *,
        session_id: str | None = None,
        team_config: Any = None,
        task: str = "",
        checkpoint_storage: Any | None = None,
    ) -> None:
        """Initialize a workflow session.

        Args:
            session_id: Unique session identifier (auto-generated if None)
            team_config: The TeamConfiguration being executed
            task: The user's task/query
            checkpoint_storage: Optional CheckpointStorage for durable persistence
        """
        self._session_id = session_id or str(uuid.uuid4())
        self._status = WorkflowStatus.PENDING
        self._team_config = team_config
        self._task = task
        self._result: WorkflowResult | None = None
        self._error: str | None = None
        self._pending_requests: list[ApprovalRequest] = []
        self._events = StreamChannel()
        self._checkpoint_storage = checkpoint_storage
        self._created_at = time.time()

    @property
    def session_id(self) -> str:
        """Unique session identifier."""
        return self._session_id

    @property
    def status(self) -> WorkflowStatus:
        """Current session status."""
        return self._status

    @property
    def result(self) -> WorkflowResult | None:
        """Execution result (set on completion)."""
        return self._result

    @property
    def error(self) -> str | None:
        """Error message (set on failure)."""
        return self._error

    @property
    def pending_requests(self) -> list[ApprovalRequest]:
        """Active approval/gate requests."""
        return list(self._pending_requests)

    @property
    def created_at(self) -> float:
        """Session creation timestamp."""
        return self._created_at

    @property
    def events(self) -> StreamChannel:
        """Event streaming channel."""
        return self._events

    def _set_status(self, status: WorkflowStatus) -> None:
        """Update session status with validation."""
        self._status = status

    def _set_result(self, result: WorkflowResult) -> None:
        """Set the workflow result and update status."""
        self._result = result
        self._status = result.status
        if result.error:
            self._error = result.error
        # Extract pending requests from paused state
        if result.status == WorkflowStatus.PAUSED:
            self._extract_pending_requests(result.state)

    def _extract_pending_requests(self, state: dict[str, Any]) -> None:
        """Extract approval requests from workflow state."""
        self._pending_requests.clear()

        if state.get("awaiting_human_input"):
            self._pending_requests.append(
                ApprovalRequest(
                    request_type="human_gate",
                    context={
                        "prompt": state.get("human_prompt", ""),
                    },
                    agent_id=state.get("_current_agent_id"),
                )
            )
        elif state.get("awaiting_action_approval"):
            # Find the agent that proposed actions
            for key in state:
                if key.endswith("_proposed_actions"):
                    agent_id = key.replace("_proposed_actions", "")
                    self._pending_requests.append(
                        ApprovalRequest(
                            request_type="action_approval",
                            context={
                                "proposed_actions": state[key],
                            },
                            agent_id=agent_id,
                        )
                    )
                    break
        elif state.get("awaiting_gate_approval"):
            self._pending_requests.append(
                ApprovalRequest(
                    request_type="gate",
                    context={
                        "gate_id": state.get("pending_gate_id", ""),
                        "gate_description": state.get("pending_gate_description", ""),
                    },
                )
            )

    async def resume(
        self,
        _responses: dict[str, Any],
        result: WorkflowResult | None = None,
    ) -> None:
        """Resume from paused state with approval responses.

        Args:
            responses: Approval responses keyed by request_id
            result: Optional workflow result from engine re-execution.
                If provided, the session status, result, and pending_requests
                are updated to reflect the engine's output.

        Raises:
            RuntimeError: If session is not in PAUSED state
        """
        if self._status != WorkflowStatus.PAUSED:
            raise RuntimeError(f"Cannot resume session in '{self._status}' state; must be 'paused'")
        self._pending_requests.clear()

        if result is not None:
            self._set_result(result)
        else:
            self._status = WorkflowStatus.RUNNING

        logger.info("Session %s resumed", self._session_id)

    async def cancel(self) -> None:
        """Cancel the session. Status transitions to FAILED.

        Raises:
            RuntimeError: If session is already completed or failed
        """
        if self._status in (WorkflowStatus.COMPLETED, WorkflowStatus.FAILED):
            raise RuntimeError(f"Cannot cancel session in '{self._status}' state")
        self._status = WorkflowStatus.FAILED
        self._error = "Session cancelled"
        self._pending_requests.clear()
        logger.info("Session %s cancelled", self._session_id)

    def subscribe(self) -> StreamConsumer:
        """Subscribe to real-time workflow events.

        Returns:
            StreamConsumer for async iteration over events
        """
        return self._events.subscribe()

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable session representation.

        Returns:
            Dictionary representation of the session
        """
        result_dict = None
        if self._result:
            result_dict = {
                "status": self._result.status.value,
                "state": self._result.state,
                "error": self._result.error,
            }

        return {
            "session_id": self._session_id,
            "status": self._status.value,
            "task": self._task,
            "result": result_dict,
            "error": self._error,
            "pending_requests": [r.to_dict() for r in self._pending_requests],
            "created_at": self._created_at,
        }
