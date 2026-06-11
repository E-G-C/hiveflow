# Data Model: Workflow Engine

**Feature**: 004-workflow-engine
**Date**: 2026-02-23

## Entity Overview

```
WorkflowCheckpoint ──1:N── CheckpointStorage
       │
       ├── session_id (groups checkpoints for a workflow run)
       ├── checkpoint_id (unique identifier per save)
       └── step_index → WorkflowStep (position in workflow graph)

WorkflowSession ──1:1── WorkflowEngine
       │
       ├── session_id
       ├── checkpoint_storage (optional)
       └── pending_requests: list[ApprovalRequest]

StreamEvent ──emitted by── WorkflowEngine
       │
       └── event_type: StreamEventType (including new OUTPUT, APPROVAL)
```

## Entities

### WorkflowCheckpoint (Modified)

Existing frozen dataclass with new fields for accumulation and validation.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `checkpoint_id` | `str` | `uuid4()` | **NEW** — Unique identifier for this checkpoint |
| `session_id` | `str` | required | Groups checkpoints belonging to the same workflow run |
| `step_index` | `int` | required | Position in the workflow step list where execution paused |
| `current_agent_id` | `str` | `""` | **NEW** — Agent ID at the paused step (for validation) |
| `current_step_type` | `str` | `""` | **NEW** — Step type at the paused step (for validation) |
| `state` | `dict[str, Any]` | required | Full workflow state dictionary at pause time |
| `pending_requests` | `list[dict]` | `[]` | Serialized ApprovalRequest objects awaiting response |
| `iteration_counts` | `dict[str, int]` | `{}` | Per-agent iteration counters (for conditional loops) |
| `team_config` | `dict[str, Any]` | `{}` | Serialized TeamConfiguration for agent reconstruction |
| `task` | `str` | `""` | Original task description |
| `created_at` | `float` | `time.time()` | Timestamp of checkpoint creation |
| `version` | `str` | `"1"` | Checkpoint format version |

**Identity**: `checkpoint_id` is globally unique. `session_id` groups related checkpoints.
**Ordering**: Checkpoints for the same session are ordered by `created_at`.
**Validation**: `version` field enables format evolution detection.

### CheckpointStorage Protocol (Modified)

| Method | Signature | Change |
|--------|-----------|--------|
| `save` | `async def save(checkpoint: WorkflowCheckpoint) -> str` | **CHANGED** — Returns `checkpoint_id` (was `None`) |
| `load` | `async def load(session_id: str, checkpoint_id: str | None = None) -> WorkflowCheckpoint | None` | **CHANGED** — Optional `checkpoint_id`; without it, returns latest |
| `delete` | `async def delete(session_id: str) -> None` | Unchanged — deletes all checkpoints for session |
| `list_sessions` | `async def list_sessions() -> list[str]` | Unchanged |
| `list_checkpoints` | `async def list_checkpoints(session_id: str) -> list[WorkflowCheckpoint]` | **NEW** — Returns all checkpoints for a session, ordered by created_at |

### FileCheckpointStorage (Modified)

**File naming**: `{session_id}_{checkpoint_id}.json`
- Example: `abc-123_550e8400-e29b-41d4-a716-446655440000.json`
- All checkpoints for a session can be found by globbing `{session_id}_*.json`

### StreamEventType Enum (Modified)

| Value | Status | Description |
|-------|--------|-------------|
| `OUTPUT` | **NEW** | Terminal workflow output produced |
| `APPROVAL` | **NEW** | Human approval response processed |
| `CHECKPOINT_SAVED` | Existing (unwired) | Checkpoint persisted — now emitted by engine |

### WorkflowEngine (Modified)

**New method**: `resume(agents, checkpoint) -> WorkflowResult`

**Modified method**: `execute()` gains optional parameters:
- `checkpoint_storage: CheckpointStorage | None = None`
- `session_id: str | None = None`

**New internal behavior**: When `checkpoint_storage` is provided and the engine pauses, it saves a checkpoint before returning.

### WorkflowResult (Unchanged)

No changes to the result dataclass. The `status` field already supports `PAUSED`.

### ApprovalRequest (Unchanged)

No changes. Already supports `human_gate`, `action_approval`, and `gate` request types.

## State Transitions

### Checkpoint Lifecycle

```
[created] --save()--> [persisted]
[persisted] --load()--> [loaded for validation]
[loaded] --validate()--> [valid] or [invalid/error]
[valid] --resume()--> [consumed by engine]
```

### Workflow Status with Checkpointing

```
PENDING → RUNNING → PAUSED (checkpoint saved) → RUNNING (resumed) → COMPLETED
PENDING → RUNNING → PAUSED (checkpoint saved) → RUNNING (resumed) → PAUSED (new checkpoint)
PENDING → RUNNING → FAILED (no resume possible)
```

## Validation Rules

- `checkpoint_id` must be non-empty and unique
- `session_id` must be non-empty
- `step_index` must be >= 0 and < number of workflow steps
- `current_agent_id` must match `workflow.steps[step_index].agent` at resume time
- `current_step_type` must match `workflow.steps[step_index].step_type` at resume time
- `version` must be compatible with current checkpoint format version
- `state` must be JSON-serializable
- `pending_requests` entries must be deserializable to `ApprovalRequest`
