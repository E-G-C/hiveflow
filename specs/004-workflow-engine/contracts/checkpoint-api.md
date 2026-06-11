# API Contracts: Checkpoint & Resume

**Feature**: 004-workflow-engine
**Date**: 2026-02-23

This document defines the Python API contracts for checkpoint resume, event streaming, and workflow session management. HiveFlow is a library — these are Python method signatures, not REST endpoints.

---

## 1. HiveFlow Facade API

### 1.1 run() — Start a Workflow

```python
async def run(
    self,
    team: str | dict[str, Any] | TeamConfiguration,
    task: str,
    *,
    documents: list[str | dict[str, str]] | None = None,
    initial_state: dict[str, Any] | None = None,
    checkpoint: bool = False,  # existing parameter
) -> WorkflowSession:
    """Execute a workflow.

    When checkpoint=True and the workflow pauses (gates/approvals),
    the engine automatically saves a checkpoint to the configured
    CheckpointStorage.

    Returns:
        WorkflowSession with status COMPLETED, FAILED, or PAUSED.
    """
```

**No signature change.** Behavior change: when `checkpoint=True`, the engine (not HiveFlow) saves checkpoints internally.

### 1.2 resume() — Resume a Paused Workflow

```python
async def resume(
    self,
    session_id: str,
    responses: dict[str, Any],
    *,
    checkpoint_id: str | None = None,  # NEW: optional specific checkpoint
) -> WorkflowSession:
    """Resume a paused workflow session.

    Args:
        session_id: Session to resume.
        responses: Approval responses keyed by request_id.
            Values: "approved", "rejected", or custom response string.
        checkpoint_id: Specific checkpoint to resume from.
            If None, resumes from the latest checkpoint for this session.

    Returns:
        Updated WorkflowSession (may be COMPLETED, FAILED, or PAUSED again).

    Raises:
        KeyError: If session_id not found in active sessions or storage.
        CheckpointError: If checkpoint is corrupted or incompatible.
        ValueError: If workflow status is not PAUSED/awaiting_human_response.
    """
```

**Changed:** Added optional `checkpoint_id` parameter. Full re-execution flow via engine.

### 1.3 list_checkpoints() — List Saved Checkpoints

```python
async def list_checkpoints(
    self,
    session_id: str,
) -> list[dict[str, Any]]:
    """List all saved checkpoints for a workflow session.

    Returns:
        List of checkpoint summaries ordered by created_at, each containing:
        - checkpoint_id: str
        - session_id: str
        - step_index: int
        - current_agent_id: str
        - status: str (from state analysis)
        - created_at: float (timestamp)

    Raises:
        ValueError: If no checkpoint storage is configured.
    """
```

**New method.**

---

## 2. WorkflowEngine API

### 2.1 execute() — Execute Workflow (Modified)

```python
async def execute(
    self,
    agents: dict[str, Agent],
    initial_state: dict[str, Any],
    *,
    documents: list[str | dict[str, str]] | None = None,
    instructions_file: str | None = None,
    checkpoint_storage: CheckpointStorage | None = None,  # NEW
    session_id: str | None = None,  # NEW
) -> WorkflowResult:
    """Execute the workflow graph.

    When checkpoint_storage and session_id are provided, the engine
    automatically saves a checkpoint when the workflow pauses at
    gates, human gates, or action approval points.
    """
```

**Changed:** Two new optional keyword parameters. Existing call sites unaffected.

### 2.2 resume() — Resume from Checkpoint (New)

```python
async def resume(
    self,
    agents: dict[str, Agent],
    checkpoint: WorkflowCheckpoint,
    *,
    responses: dict[str, Any] | None = None,
    checkpoint_storage: CheckpointStorage | None = None,
    session_id: str | None = None,
) -> WorkflowResult:
    """Resume workflow execution from a checkpoint.

    Args:
        agents: Agent dictionary (reconstructed from team config).
        checkpoint: The checkpoint to resume from.
        responses: Approval responses to apply before resuming.
        checkpoint_storage: Storage for saving further checkpoints.
        session_id: Session ID for new checkpoints.

    Returns:
        WorkflowResult from resumed execution.

    Raises:
        CheckpointError: If checkpoint is incompatible with current workflow.
        ValueError: If checkpoint step_index is out of range.
    """
```

**New method.** Core of the resume implementation.

---

## 3. CheckpointStorage Protocol (Modified)

```python
@runtime_checkable
class CheckpointStorage(Protocol):

    async def save(self, checkpoint: WorkflowCheckpoint) -> str:
        """Persist a checkpoint. Returns checkpoint_id."""
        ...

    async def load(
        self,
        session_id: str,
        checkpoint_id: str | None = None,
    ) -> WorkflowCheckpoint | None:
        """Load a checkpoint.

        If checkpoint_id is None, returns the latest checkpoint for the session.
        If checkpoint_id is provided, returns that specific checkpoint.
        Returns None if not found.
        """
        ...

    async def delete(self, session_id: str) -> None:
        """Delete all checkpoints for a session."""
        ...

    async def list_sessions(self) -> list[str]:
        """List all session IDs that have checkpoints."""
        ...

    async def list_checkpoints(self, session_id: str) -> list[WorkflowCheckpoint]:
        """List all checkpoints for a session, ordered by created_at ascending."""
        ...
```

**Changes:**
- `save()` returns `str` (checkpoint_id) instead of `None`
- `load()` gains optional `checkpoint_id` parameter
- `list_checkpoints()` is a new method

---

## 4. WorkflowCheckpoint (Modified)

```python
@dataclass(frozen=True)
class WorkflowCheckpoint:
    session_id: str
    step_index: int
    state: dict[str, Any]
    checkpoint_id: str = field(default_factory=lambda: str(uuid.uuid4()))  # NEW
    current_agent_id: str = ""  # NEW
    current_step_type: str = ""  # NEW
    pending_requests: list[dict[str, Any]] = field(default_factory=list)
    iteration_counts: dict[str, int] = field(default_factory=dict)
    team_config: dict[str, Any] = field(default_factory=dict)
    task: str = ""
    created_at: float = field(default_factory=time.time)
    version: str = "1"
```

**New fields:** `checkpoint_id`, `current_agent_id`, `current_step_type`.

---

## 5. StreamEventType (Modified)

```python
class StreamEventType(StrEnum):
    # ... existing values ...
    OUTPUT = "output"              # NEW
    APPROVAL = "approval"          # NEW
    CHECKPOINT_SAVED = "checkpoint_saved"  # existing, now emitted
```

---

## 6. Event Data Contracts

### OUTPUT Event
```json
{
    "event_type": "output",
    "agent_id": "",
    "data": {
        "result": "<final workflow output or result_payload>"
    }
}
```

### CHECKPOINT_SAVED Event
```json
{
    "event_type": "checkpoint_saved",
    "agent_id": "<agent_id at paused step>",
    "data": {
        "checkpoint_id": "550e8400-...",
        "session_id": "abc-123",
        "step_index": 2
    }
}
```

### APPROVAL Event
```json
{
    "event_type": "approval",
    "agent_id": "<agent_id of gate/approval step>",
    "data": {
        "request_id": "req-456",
        "decision": "approved",
        "gate_id": "deploy_gate"
    }
}
```
