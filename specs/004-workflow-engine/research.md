# Research: Workflow Engine

**Feature**: 004-workflow-engine
**Date**: 2026-02-23

## Research Summary

This document captures design decisions and technical investigation for the workflow engine checkpoint resume, accumulation, and event streaming features.

---

## R1: Checkpoint Accumulation Model

### Decision

Use unique `checkpoint_id` (UUID) for each checkpoint, with `session_id` as a grouping key. File naming becomes `{session_id}_{checkpoint_id}.json`.

### Rationale

The current implementation uses `session_id` as the sole file key, overwriting on each save. To support accumulation (multiple checkpoints per workflow session), each checkpoint needs its own unique identifier while remaining grouped by session for listing.

UUID-based checkpoint IDs are preferred over sequential numbering because:
- No concurrency risk from counter increment
- No need to read existing files to determine next number
- Aligns with how `ApprovalRequest.request_id` already uses UUIDs
- Checkpoint ordering is determined by `created_at` timestamp, not file name

### Alternatives Considered

| Alternative | Why Rejected |
|-------------|-------------|
| Sequential index (`_0.json`, `_1.json`) | Requires reading directory to find max, race-prone |
| Timestamp-only (`_1708695600.json`) | Sub-second resolution risk; less unique than UUID |
| Separate directory per session | Over-complicated for typical 1-5 checkpoints per session |

### Impact on Existing Code

- `CheckpointStorage` protocol: `save()` return type changes from `None` to `str` (returns checkpoint_id)
- `load()` signature changes: add optional `checkpoint_id` parameter; without it, loads latest
- New method: `list_checkpoints(session_id: str) -> list[WorkflowCheckpoint]`
- `WorkflowCheckpoint`: add `checkpoint_id: str` field (auto-generated UUID)
- `FileCheckpointStorage._session_path()`: renamed to `_checkpoint_path(session_id, checkpoint_id)`

**Backward compatibility**: Old single-file checkpoints (`{session_id}.json`) can still be loaded by treating them as the sole checkpoint for that session. A migration path is not required since this is pre-1.0 storage.

---

## R2: Resume Execution Flow

### Decision

Add a `resume()` method to `WorkflowEngine` that accepts a `WorkflowCheckpoint` and `agents` dict, then enters the execute loop at the checkpointed step index.

### Rationale

The current `HiveFlow.resume()` loads a checkpoint and calls `session.resume(responses)`, but this only changes the session status to RUNNING — it never re-invokes the workflow engine's execution loop. The engine needs an explicit entry point for resumption.

The resume flow:

1. `HiveFlow.resume(session_id, responses)` is called
2. Load checkpoint from `CheckpointStorage`
3. Validate checkpoint compatibility (step-match: agent ID + step type at same position)
4. Reconstruct agents via `TeamGenerator.build()` from checkpoint's `team_config`
5. Apply approval responses to checkpoint state (clear `awaiting_*` flags, set response data)
6. Call `WorkflowEngine.resume(agents, checkpoint)` which enters execute loop at `step_index`
7. Continue execution from the step after the paused step through to completion

### Key Design Details

**Step-match validation** (FR-006): Compare `checkpoint.step_index` against `self.steps`. Verify `self.steps[step_index].agent == expected_agent_id` and `self.steps[step_index].step_type == expected_step_type`.

**State modification on resume**: Before entering the loop, clear the pause flags (`awaiting_human_input`, `awaiting_action_approval`, `awaiting_gate_approval`) and inject the approval responses.

**Resume entry point**: The execute loop currently starts at `self.steps[0]`. Resume starts at `self.steps[checkpoint.step_index]` and advances to the next step (since the paused step already executed — it paused waiting for input, which is now provided).

### Alternatives Considered

| Alternative | Why Rejected |
|-------------|-------------|
| Replay all steps from start, skipping completed | Wasteful, may have side effects with tool_user/action_executor agents |
| Store full step_results in checkpoint | Bloats checkpoint with LLM responses; step_results are informational only |
| Add resume to execute() via parameter | Pollutes execute() with resume logic; cleaner as separate method |

---

## R3: Automatic Checkpointing Integration

### Decision

The `WorkflowEngine.execute()` loop saves a checkpoint to the provided `CheckpointStorage` whenever the workflow pauses, before returning the PAUSED result. The engine receives `checkpoint_storage` and `session_id` as optional parameters.

### Rationale

Currently, `HiveFlow._save_checkpoint()` is called after `execute()` returns PAUSED. Moving checkpoint saves into the engine itself ensures:
- The step_index is captured accurately (currently hardcoded to 0)
- The checkpoint is saved atomically with the pause decision
- The same pattern works for both `execute()` and `resume()`

### Design

```
execute(..., checkpoint_storage=storage, session_id=sid)
  → on GATED/HUMAN_GATE/ACTION_APPROVAL pause:
    → save checkpoint with current step_index, state, pending_requests
    → emit checkpoint_saved event
    → return WorkflowResult(status=PAUSED)
```

`HiveFlow.run()` passes `checkpoint_storage` and `session.session_id` to `execute()` when `checkpoint=True`. The engine handles saves internally.

---

## R4: New Event Types

### Decision

Add three new event types to `StreamEventType`: `OUTPUT`, `APPROVAL`, and ensure `CHECKPOINT_SAVED` is emitted when checkpoints are saved.

### Rationale

- `OUTPUT` (FR-008): Emitted when the workflow produces its final result. Maps to the terminal output of the workflow. Emitted in `execute()` just before returning a COMPLETED result.
- `CHECKPOINT_SAVED` already exists in the enum but is never emitted. Wire it to checkpoint save operations in the engine.
- `APPROVAL` (FR-010): Emitted when a human approval response is processed during resume. Emitted at the start of `resume()` after applying responses.

### Event Data Shapes

```python
# OUTPUT event
{"event_type": "output", "data": {"result": <workflow_output>}}

# CHECKPOINT_SAVED event
{"event_type": "checkpoint_saved", "data": {"checkpoint_id": "...", "step_index": N, "session_id": "..."}}

# APPROVAL event (new)
{"event_type": "approval", "data": {"request_id": "...", "decision": "approved|rejected", "gate_id": "..."}}
```

---

## R5: Checkpoint Compatibility Validation

### Decision

Step-match validation: confirm the checkpoint's current step (agent ID + step type) still exists at the same position in the current workflow definition. Allow other changes.

### Rationale

Per clarification Q3, the validation strategy is:
1. Load checkpoint, extract `step_index`
2. Look up `self.steps[step_index]` in the current workflow
3. Verify: `step.agent == checkpoint.state["current_agent"]` (or stored agent_id)
4. Verify: `step.step_type` matches what was checkpointed
5. If mismatch: raise `CheckpointError` with descriptive message
6. If step_index out of range: raise `CheckpointError`
7. If match: proceed with resume

This allows safe workflow evolution (appending steps, modifying steps after the resume point) while catching the dangerous cases (reordered or removed steps).

### Implementation

Store `current_agent_id` and `current_step_type` in the `WorkflowCheckpoint` for validation purposes. This avoids needing to inspect `state["current_agent"]` which is a reserved state key that serves a different purpose.

New fields on `WorkflowCheckpoint`:
- `current_agent_id: str` — agent ID at checkpoint time
- `current_step_type: str` — step type at checkpoint time
