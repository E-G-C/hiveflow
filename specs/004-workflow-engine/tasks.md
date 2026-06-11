# Tasks: Workflow Engine

**Input**: Design documents from `/specs/004-workflow-engine/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: Tests are included as this is core framework infrastructure requiring high reliability.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story. Phase 2 spec features (US4 Sub-Workflows, US5 Workflow-as-Agent, US6 Async Iterator) are deferred and not included.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Setup

**Purpose**: No new project setup needed — this feature modifies an existing Python package. This phase is empty.

*(No tasks — existing project structure is used as-is)*

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Update core data models and protocols that ALL user stories depend on. These changes are additive and backward-compatible.

**CRITICAL**: No user story work can begin until this phase is complete.

- [x] T001 Add `checkpoint_id` field (UUID default), `current_agent_id` field, and `current_step_type` field to `WorkflowCheckpoint` dataclass in `hiveflow/core/checkpoint.py`. Update `to_dict()` and `from_dict()` to serialize/deserialize the new fields with backward-compatible defaults for old checkpoint files missing these fields. <!-- bd:hiveflow-blp.1 -->

- [x] T002 Update `CheckpointStorage` protocol in `hiveflow/core/checkpoint.py`: change `save()` return type from `None` to `str` (returns `checkpoint_id`), add optional `checkpoint_id` parameter to `load()` signature, and add new `list_checkpoints(session_id: str) -> list[WorkflowCheckpoint]` method to the protocol. <!-- bd:hiveflow-blp.2 -->

- [x] T003 Update `FileCheckpointStorage` in `hiveflow/core/checkpoint.py` for accumulation model: rename `_session_path()` to `_checkpoint_path(session_id, checkpoint_id)` with `{session_id}_{checkpoint_id}.json` naming, update `save()` to write per-checkpoint files and return `checkpoint_id`, update `load()` to accept optional `checkpoint_id` (loads latest by `created_at` when None), update `list_sessions()` to extract unique session IDs from filenames, implement `list_checkpoints()` that globs `{session_id}_*.json` and returns all checkpoints ordered by `created_at`, and update `delete()` to remove all checkpoint files for a session. <!-- bd:hiveflow-blp.3 -->

- [x] T004 [P] Add `OUTPUT = "output"` and `APPROVAL = "approval"` to `StreamEventType` enum in `hiveflow/core/streaming.py`. <!-- bd:hiveflow-blp.4 -->

- [x] T005 Update existing checkpoint tests in `tests/test_checkpoint_session.py`: add tests for new `WorkflowCheckpoint` fields (`checkpoint_id`, `current_agent_id`, `current_step_type`), test `to_dict()`/`from_dict()` round-trip with new fields, test backward compatibility loading old checkpoint format missing new fields, test `FileCheckpointStorage` accumulation (multiple saves for same session), test `list_checkpoints()` returns ordered results, and test `load()` with and without `checkpoint_id` parameter. <!-- bd:hiveflow-blp.5 -->

**Checkpoint**: Foundation ready — data models and protocols support accumulation, validation fields, and new event types. User story implementation can now begin.

---

## Phase 3: User Story 2 - Automatic Checkpointing at Key Points (Priority: P1)

**Goal**: The workflow engine automatically saves checkpoints when pausing at gates/approvals. Users can list all checkpoints for a session.

**Independent Test**: Run a multi-step workflow with gates, verify checkpoint files are created at each pause point, and verify listing returns all checkpoints with correct metadata.

**Why US2 before US1**: Auto-checkpointing modifies `WorkflowEngine.execute()` to accept `checkpoint_storage` and save checkpoints internally. Resume (US1) builds on this modified execute loop.

### Implementation for User Story 2

- [x] T006 [US2] Add `checkpoint_storage: CheckpointStorage | None = None` and `session_id: str | None = None` keyword parameters to `WorkflowEngine.execute()` in `hiveflow/core/workflow.py`. These are optional and default to `None` — existing call sites are unaffected. <!-- bd:hiveflow-blp.6 -->

- [x] T007 [US2] Wire automatic checkpoint saves into the three pause paths in `WorkflowEngine.execute()` in `hiveflow/core/workflow.py`: at GATED step pause (around line 275), HUMAN_GATE pause (around line 315), and action_executor approval pause (around line 333). Before each `return WorkflowResult(status=PAUSED, ...)`, if `checkpoint_storage` and `session_id` are provided, create a `WorkflowCheckpoint` with the current `step_index` (from `self.steps.index(current_step)`), `current_agent_id`, `current_step_type`, full `state`, serialized `pending_requests`, `iteration_counts`, and `team_config`, then `await checkpoint_storage.save(checkpoint)`. Add an internal `_save_checkpoint()` helper to avoid code duplication across the three pause paths. <!-- bd:hiveflow-blp.7 -->

- [x] T008 [US2] Update `HiveFlow.run()` in `hiveflow/core/hiveflow.py` to pass `checkpoint_storage=self._checkpoint_storage` and `session_id=session.session_id` to `engine.execute()` when `checkpoint=True`. Remove the existing `_save_checkpoint()` method and its call after `execute()` returns — checkpoint saving is now handled inside the engine. Also extract and store the `team_config` dict (from `TeamConfiguration.model_dump()` or equivalent) so it's available for the checkpoint's `team_config` field. <!-- bd:hiveflow-blp.8 -->

- [x] T009 [US2] Add `list_checkpoints(session_id: str) -> list[dict[str, Any]]` method to `HiveFlow` class in `hiveflow/core/hiveflow.py`. This method delegates to `self._checkpoint_storage.list_checkpoints(session_id)` and returns a list of checkpoint summary dicts (checkpoint_id, session_id, step_index, current_agent_id, created_at). Raise `ValueError` if no checkpoint storage is configured. <!-- bd:hiveflow-blp.9 -->

- [x] T010 [US2] Add auto-checkpointing tests in `tests/test_checkpoint_session.py`: test that `WorkflowEngine.execute()` saves a checkpoint when it pauses at a GATED step with `checkpoint_storage` provided, test that the saved checkpoint has correct `step_index` and `current_agent_id`, test that no checkpoint is saved when `checkpoint_storage` is `None`, test that `HiveFlow.list_checkpoints()` returns all accumulated checkpoints for a session, and test that `HiveFlow.list_checkpoints()` raises `ValueError` when no storage is configured. <!-- bd:hiveflow-blp.10 -->

**Checkpoint**: Workflows automatically save checkpoints at every pause point. Users can list all checkpoints. The engine correctly captures step position and agent metadata.

---

## Phase 4: User Story 1 - Resume a Paused Workflow (Priority: P1) MVP

**Goal**: Users can resume a paused workflow from any saved checkpoint, with full state restoration and no re-execution of completed steps.

**Independent Test**: Start a workflow with a human gate, let it pause, verify checkpoint exists, resume with approval response, verify workflow completes from the paused step without re-executing prior steps.

### Implementation for User Story 1

- [x] T011 [US1] Implement `_validate_checkpoint()` private method in `WorkflowEngine` in `hiveflow/core/workflow.py`. This method accepts a `WorkflowCheckpoint` and verifies: (1) `checkpoint.step_index` is within range of `self.steps`, (2) `self.steps[checkpoint.step_index].agent` matches `checkpoint.current_agent_id`, (3) `str(self.steps[checkpoint.step_index].step_type)` matches `checkpoint.current_step_type`. Raises `CheckpointError` with descriptive messages on mismatch. Import `CheckpointError` from `hiveflow.core.checkpoint`. <!-- bd:hiveflow-blp.11 -->

- [x] T012 [US1] Implement `resume()` method in `WorkflowEngine` in `hiveflow/core/workflow.py` per the contract in `contracts/checkpoint-api.md`. Signature: `async def resume(self, agents: dict[str, Agent], checkpoint: WorkflowCheckpoint, *, responses: dict[str, Any] | None = None, checkpoint_storage: CheckpointStorage | None = None, session_id: str | None = None) -> WorkflowResult`. Implementation: (1) call `_validate_checkpoint()`, (2) restore `state = dict(checkpoint.state)`, (3) apply responses by clearing `awaiting_human_input`/`awaiting_action_approval`/`awaiting_gate_approval` flags and storing responses in state, (4) restore `iteration_counts` from checkpoint, (5) resolve `current_step` to `self.steps[checkpoint.step_index]`, (6) advance to the next step via `_resolve_next_step()`, (7) enter the existing execute while-loop from that step forward (extract loop body to `_execute_loop()` shared between `execute()` and `resume()`). <!-- bd:hiveflow-blp.12 -->

- [x] T013 [US1] Update `HiveFlow.resume()` in `hiveflow/core/hiveflow.py` for full engine re-execution flow. Implementation: (1) load checkpoint via `self._checkpoint_storage.load(session_id, checkpoint_id)`, (2) validate checkpoint exists (raise `KeyError` if not), (3) reconstruct team config from `checkpoint.team_config` using `TeamConfiguration.model_validate(checkpoint.team_config)`, (4) rebuild agents and engine via `TeamGenerator.build()` (or equivalent), (5) call `engine.resume(agents, checkpoint, responses=responses, checkpoint_storage=self._checkpoint_storage, session_id=session_id)`, (6) update session with result, (7) return session. Add optional `checkpoint_id` keyword parameter to the method signature. <!-- bd:hiveflow-blp.13 -->

- [x] T014 [US1] Update `WorkflowSession.resume()` in `hiveflow/core/session.py` to accept and store the engine result. Currently it only changes status to RUNNING. After calling the engine's resume flow (triggered by HiveFlow), the session should receive the `WorkflowResult` and update its status, result, and pending_requests accordingly so the caller gets the final state. <!-- bd:hiveflow-blp.14 -->

- [x] T015 [US1] Create `tests/test_workflow_resume.py` with integration tests: test resume from a human_gate checkpoint (approve → completes), test resume from a human_gate checkpoint (reject → follows rejection path), test resume from a gated step checkpoint, test resume from an action_executor approval checkpoint, test resume skips completed steps (verify agent execute is NOT called for prior steps), test resume from a specific checkpoint_id (not latest), test `_validate_checkpoint()` rejects mismatched agent_id, test `_validate_checkpoint()` rejects mismatched step_type, test `_validate_checkpoint()` rejects out-of-range step_index, test resume of a FAILED workflow raises ValueError, test resume with invalid session_id raises KeyError, and test resume with corrupted checkpoint raises CheckpointError. <!-- bd:hiveflow-blp.15 -->

**Checkpoint**: Users can pause and resume workflows with full state preservation. The MVP is complete — checkpoint resume is the core value proposition of this feature.

---

## Phase 5: User Story 3 - Observe Workflow Progress via Events (Priority: P2)

**Goal**: Fill gaps in event coverage so the event stream gives a complete picture of workflow execution — including output, checkpoint saved, and approval events.

**Independent Test**: Register event callbacks on a workflow engine, run a workflow that pauses and resumes, verify the complete sequence of events is received including the three new event types.

### Implementation for User Story 3

- [x] T016 [P] [US3] Emit `OUTPUT` event in `WorkflowEngine.execute()` and `resume()` in `hiveflow/core/workflow.py`. Just before returning a `WorkflowResult` with `status=COMPLETED`, call `self._emit("output", "", {"result": state.get("final_output", "")})` (or extract result_payload if present). This gives consumers the terminal output of the workflow. <!-- bd:hiveflow-blp.16 -->

- [x] T017 [P] [US3] Emit `CHECKPOINT_SAVED` event in the `_save_checkpoint()` helper (created in T007) in `hiveflow/core/workflow.py`. After `await checkpoint_storage.save(checkpoint)`, call `self._emit("checkpoint_saved", agent_id, {"checkpoint_id": checkpoint.checkpoint_id, "session_id": session_id, "step_index": checkpoint.step_index})`. <!-- bd:hiveflow-blp.17 -->

- [x] T018 [US3] Emit `APPROVAL` event in `WorkflowEngine.resume()` in `hiveflow/core/workflow.py`. After applying responses (step 3 of the resume flow), emit `self._emit("approval", checkpoint.current_agent_id, {"request_id": request_id, "decision": decision, "gate_id": gate_id})` for each processed response. <!-- bd:hiveflow-blp.18 -->

- [x] T019 [US3] Create `tests/test_workflow_events.py` with event emission tests: test that `output` event is emitted on workflow completion with correct data, test that `checkpoint_saved` event is emitted when a checkpoint is saved with correct checkpoint_id and step_index, test that `approval` event is emitted during resume with correct request_id and decision, test that all events are received in order (step_start → step_complete → ... → checkpoint_saved → ... → approval → ... → output), and test that existing events (step_start, step_complete, gate_requested) continue to work correctly after changes. <!-- bd:hiveflow-blp.19 -->

**Checkpoint**: The event stream provides complete lifecycle coverage. All workflow actions — steps, checkpoints, approvals, and output — are observable via events.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Documentation and validation across all user stories.

- [x] T020 [P] Update `CHANGELOG.md` with workflow engine checkpoint resume and auto-checkpointing features (Phase 1 of 004-workflow-engine). <!-- bd:hiveflow-blp.20 -->

- [x] T021 [P] Update `README.md` or relevant documentation with checkpoint/resume usage examples including `checkpoint=True`, `HiveFlow.resume()`, and `HiveFlow.list_checkpoints()`. <!-- bd:hiveflow-blp.21 -->

- [x] T022 Run all tests with `uv run pytest` and fix any failures or regressions introduced by the workflow engine changes. <!-- bd:hiveflow-blp.22 -->

- [x] T023 Validate `specs/004-workflow-engine/quickstart.md` scenarios work end-to-end by running the example code patterns against the implementation. <!-- bd:hiveflow-blp.23 -->

---

## Dependencies & Execution Order

### Phase Dependencies

- **Foundational (Phase 2)**: No dependencies — can start immediately. BLOCKS all user stories.
- **US2 Auto-Checkpointing (Phase 3)**: Depends on Foundational completion. SHOULD complete before US1 because it modifies `execute()` in ways that `resume()` builds on.
- **US1 Resume (Phase 4)**: Depends on Foundational + US2. This is the MVP.
- **US3 Events (Phase 5)**: Depends on Foundational. Can start after US2 (needs `_save_checkpoint()` helper). Independent of US1 for OUTPUT/CHECKPOINT_SAVED events; depends on US1 for APPROVAL event.
- **Polish (Phase 6)**: Depends on all user stories being complete.

### User Story Dependencies

- **US2 (P1)**: Depends only on Foundational. Modifies `execute()` loop.
- **US1 (P1)**: Depends on Foundational + US2. Adds `resume()` that builds on the modified `execute()` loop.
- **US3 (P2)**: Depends on Foundational + US2. Partially depends on US1 (APPROVAL event only).
- **US4, US5, US6 (P3)**: Phase 2 of the spec — deferred, not included in this task list.

### Within Each User Story

- Data model changes (Foundational) before engine changes
- Engine changes before facade/session changes
- Implementation before tests (tests validate the implementation)
- Story complete before moving to next priority

### Parallel Opportunities

- T001, T002, T003 are sequential (same file: checkpoint.py)
- T004 can run in parallel with T001-T003 (different file: streaming.py)
- T005 can run after T001-T003 (tests for checkpoint changes)
- Within US3: T016 and T017 can run in parallel (different locations in workflow.py, but both modifications — take care with merge)
- T020 and T021 can run in parallel (different files)

---

## Parallel Example: Foundational Phase

```bash
# These can run in parallel (different files):
Task T001-T003: "Update WorkflowCheckpoint and FileCheckpointStorage in hiveflow/core/checkpoint.py"
Task T004: "Add OUTPUT and APPROVAL to StreamEventType in hiveflow/core/streaming.py"

# Then after both complete:
Task T005: "Update existing checkpoint tests in tests/test_checkpoint_session.py"
```

## Parallel Example: User Story 3

```bash
# These touch different code locations (but same file — coordinate):
Task T016: "Emit OUTPUT event on workflow completion in hiveflow/core/workflow.py"
Task T017: "Emit CHECKPOINT_SAVED event on checkpoint save in hiveflow/core/workflow.py"

# Then after both:
Task T018: "Emit APPROVAL event during resume in hiveflow/core/workflow.py"
Task T019: "Event emission tests in tests/test_workflow_events.py"
```

---

## Implementation Strategy

### MVP First (US2 + US1)

1. Complete Phase 2: Foundational (data model changes)
2. Complete Phase 3: US2 Auto-Checkpointing (engine saves checkpoints)
3. Complete Phase 4: US1 Resume (engine resumes from checkpoints)
4. **STOP and VALIDATE**: Test resume flow end-to-end
5. Deploy/demo if ready — this delivers the core value

### Incremental Delivery

1. Foundational → Data models support accumulation and validation fields
2. + US2 → Workflows automatically checkpoint at pause points
3. + US1 → Users can resume from checkpoints (MVP complete!)
4. + US3 → Full event observability for monitoring and dashboards
5. + Polish → Documentation and validation
6. Each increment adds value without breaking previous functionality

### Deferred (Phase 2 of Spec)

- US4: Sub-Workflows (FR-011 to FR-015)
- US5: Workflow-as-Agent (FR-016 to FR-018)
- US6: Async Event Iterator (FR-019 to FR-021)

These will be generated as separate tasks after Phase 1 is validated.

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- All file paths are relative to repository root (`c:/Work/AI/hiveflow/`)
- US2 is ordered before US1 because execute() modifications are a prerequisite for resume()
