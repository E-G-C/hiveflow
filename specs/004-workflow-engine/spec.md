# Feature Specification: Workflow Engine

**Feature Branch**: `004-workflow-engine`
**Created**: 2026-02-23
**Status**: Draft
**Input**: User description: "Workflow engine with generalized 6-stage lifecycle, checkpointing with resume, event streaming, sub-workflows, and workflow-as-agent composition (based on requirements/02-workflows.md)"

## Clarifications

### Session 2026-02-23

- Q: Should each pause point accumulate as a separate checkpoint (enabling rewind) or overwrite the previous one? → A: Accumulate — each save creates a new checkpoint; users can rewind to any prior state.
- Q: Can failed workflows be resumed from their failure point, or only paused workflows? → A: Paused only — resume is limited to explicitly paused workflows (gates/approvals); failed workflows must restart. Failed-workflow retry may be considered for Phase 2.
- Q: What constitutes an "incompatible" workflow definition change when validating a checkpoint for resume? → A: Step-match — validate that the checkpoint's current step (agent ID + step type) still exists at the same position in the workflow; allow other changes (e.g., appending new steps).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Resume a Paused Workflow (Priority: P1)

A user starts a long-running multi-agent workflow that includes a human approval gate (e.g., an incident response workflow where remediation requires human sign-off). The workflow runs through initial stages, reaches the approval gate, and pauses. Hours later, the user provides their approval and the workflow resumes from exactly where it left off, continuing through the remaining stages without re-executing completed steps.

**Why this priority**: Workflow resume is the critical missing piece for production-grade workflows. Checkpointing infrastructure already exists but cannot actually resume execution. Without resume, any workflow with human-in-the-loop gates or long-running steps is effectively broken — it pauses but can never continue.

**Independent Test**: Can be fully tested by starting a workflow with a human gate, letting it pause, then resuming with an approval response and verifying the workflow completes from the paused step.

**Acceptance Scenarios**:

1. **Given** a running workflow reaches a human gate step, **When** the engine encounters the gate, **Then** the workflow state is checkpointed and the workflow pauses with status "awaiting_human_response" and a pending approval request.
2. **Given** a paused workflow with a saved checkpoint, **When** the user resumes the workflow providing an approval response, **Then** the engine loads the checkpoint, applies the response, and continues execution from the step immediately after the gate.
3. **Given** a paused workflow, **When** the user resumes with a rejection response, **Then** the engine loads the checkpoint, applies the rejection, and the workflow follows the rejection path defined in step transitions.
4. **Given** a checkpoint exists from a previous session, **When** the application restarts and the user requests resume, **Then** the workflow state is fully reconstructed from the persisted checkpoint file and execution continues correctly.
5. **Given** a workflow with multiple gate steps, **When** the workflow pauses at the second gate, **Then** the checkpoint includes the full state from all prior completed steps and the resume skips all previously completed steps.

---

### User Story 2 - Automatic Checkpointing at Key Points (Priority: P1)

A user runs a workflow with several sequential agent steps. After each gated step and at each approval point, the engine automatically saves a checkpoint. If the process crashes or is interrupted, the user can list available checkpoints and resume from the last saved point.

**Why this priority**: Automatic checkpointing is the foundation for reliability. Without it, any interruption (crash, timeout, network failure) means restarting the entire workflow from scratch, which is unacceptable for production use.

**Independent Test**: Can be tested by running a multi-step workflow, killing the process mid-execution, then verifying checkpoints exist and the workflow can resume from the last checkpoint.

**Acceptance Scenarios**:

1. **Given** a workflow with a gated step, **When** the workflow reaches the gated step, **Then** a checkpoint is automatically saved before pausing.
2. **Given** a workflow with an action_executor agent that requires approval, **When** the agent proposes actions, **Then** a checkpoint is saved before waiting for approval.
3. **Given** multiple checkpoints exist for a workflow, **When** the user lists checkpoints, **Then** they see all saved checkpoints with timestamps, step positions, and workflow status.
4. **Given** the workflow process is interrupted, **When** the user resumes using the latest checkpoint ID, **Then** execution continues from the exact step where the checkpoint was saved.

---

### User Story 3 - Observe Workflow Progress via Events (Priority: P2)

A user runs a workflow and wants to monitor its progress in real time. They register event callbacks and receive structured notifications as each step starts, completes, errors, or emits intermediate results. This enables building dashboards, logging pipelines, or interactive UIs on top of the workflow engine.

**Why this priority**: Event observability is essential for understanding what a multi-agent workflow is doing, but the callback mechanism already works. This story focuses on filling gaps in event coverage (output events, checkpoint events, approval events) so the event stream gives a complete picture of workflow execution.

**Independent Test**: Can be tested by registering event callbacks on a workflow engine instance, running a workflow, and verifying that the expected sequence of events is received with correct data.

**Acceptance Scenarios**:

1. **Given** a workflow with registered event callbacks, **When** a step starts and completes, **Then** `step_start` and `step_complete` events are emitted with the agent ID and relevant data.
2. **Given** a workflow that produces final output, **When** the output is generated, **Then** an `output` event is emitted containing the terminal output.
3. **Given** a workflow that saves a checkpoint, **When** the checkpoint is persisted, **Then** a `checkpoint_saved` event is emitted with the checkpoint ID and step position.
4. **Given** a paused workflow that receives an approval response, **When** the approval is processed, **Then** an `approval` event is emitted indicating the decision and affected gate.

---

### User Story 4 - Compose Workflows from Sub-Workflows (Priority: P3)

A user defines a complex workflow (e.g., "product launch") that contains reusable sub-workflows (e.g., "market research" and "content creation") as individual steps. Each sub-workflow executes independently with its own agents, receives input mapped from the parent workflow state, and returns results that are merged back into the parent state.

**Why this priority**: Sub-workflows enable modularity and reuse, but they are a Phase 2 feature. The core workflow engine must work reliably with checkpointing and resume (P1) before adding compositional complexity.

**Independent Test**: Can be tested by defining a parent workflow with a `sub_workflow` step type that references a child team configuration, running the parent, and verifying the child executes and its results appear in the parent state.

**Acceptance Scenarios**:

1. **Given** a parent workflow with a `sub_workflow` step referencing a child team configuration, **When** the parent reaches the sub-workflow step, **Then** the child workflow is instantiated and executed with the mapped input state.
2. **Given** a sub-workflow that has completed, **When** its result is returned, **Then** the parent workflow merges the output into its own state using the defined output mapping.
3. **Given** a sub-workflow step with input_mapping and output_mapping, **When** the sub-workflow executes, **Then** only the mapped state keys are passed to/from the sub-workflow (not the full parent state).
4. **Given** a sub-workflow that fails, **When** the error is propagated, **Then** the parent workflow receives a step_error and follows its error handling path.

---

### User Story 5 - Wrap a Workflow as a Single Agent (Priority: P3)

A user has a tested multi-agent workflow (e.g., a research pipeline) and wants to use it as a single "agent" within a larger orchestration. They wrap the workflow so it presents the same interface as any other agent — it receives state, produces output — enabling hierarchical composition and progressive refinement.

**Why this priority**: This is a Phase 2 convenience pattern that builds on sub-workflows. It provides a cleaner API for hierarchical composition but requires sub-workflows to work first.

**Independent Test**: Can be tested by wrapping a workflow using an `as_agent()` method, inserting it into a parent workflow as a regular agent, and verifying it executes the full inner workflow and produces the expected output.

**Acceptance Scenarios**:

1. **Given** a complete workflow definition, **When** the user wraps it using `as_agent()` with an agent ID and role, **Then** the result behaves like a standard agent that can be used in other workflow steps.
2. **Given** a wrapped workflow-agent placed in a larger workflow, **When** the parent workflow executes the wrapped agent's step, **Then** the inner workflow runs to completion and its final state is returned as the agent's output.
3. **Given** a wrapped workflow-agent, **When** it is inspected or listed alongside other agents, **Then** it presents the same interface (agent_id, role, execute method) as any regular agent.

---

### User Story 6 - Stream Workflow Events via Async Iterator (Priority: P3)

A user building a web application wants to stream real-time workflow events to a frontend via WebSocket or Server-Sent Events. Instead of registering callbacks, they consume events as an async iterator, making it natural to pipe events through a streaming protocol.

**Why this priority**: This is a Phase 2 API improvement. The callback mechanism (P2) provides the same functionality but requires a different consumption pattern. The async iterator is a convenience for streaming-first applications.

**Independent Test**: Can be tested by calling `execute_stream()` on the workflow engine and consuming events via `async for`, verifying all expected events are yielded in order.

**Acceptance Scenarios**:

1. **Given** a workflow engine with `execute_stream()` method, **When** a workflow is executed via streaming, **Then** events are yielded as an async iterator in the order they occur.
2. **Given** a streaming workflow execution, **When** a gate step is reached, **Then** a `gate_requested` event is yielded and the iterator pauses until a response is provided.
3. **Given** a streaming consumer connected via WebSocket, **When** events are yielded, **Then** each event is serializable and suitable for transmission over the wire.

---

### Edge Cases

- What happens when a checkpoint file is corrupted or incomplete? The system reports a clear error and allows the user to list other available checkpoints or restart the workflow.
- What happens when the workflow definition has changed since a checkpoint was saved? The system validates that the checkpoint's current step (agent ID + step type) still exists at the same position. If the resume step has been moved, removed, or its type changed, the system refuses to resume with a clear error. Other changes (e.g., appending new steps) are permitted.
- What happens when a sub-workflow enters an infinite loop? Sub-workflows inherit the parent's max_iterations limit by default (configurable per sub-workflow step). The engine enforces a hard ceiling to prevent runaway execution.
- What happens when resume is attempted with an invalid checkpoint ID? The system returns a clear "checkpoint not found" error.
- What happens when a workflow has no gated or approval steps? Checkpoints are not automatically saved during Phase 1 (automatic per-step checkpointing is Phase 2). The workflow runs to completion without pausing.
- What happens when multiple users attempt to resume the same checkpoint concurrently? The system uses the checkpoint status field to detect concurrent access and rejects the second resume attempt.
- What happens when a user attempts to resume a failed workflow? The system rejects the resume with a clear error indicating that only paused workflows (status "awaiting_human_response") can be resumed; failed workflows must be restarted from scratch.

## Requirements *(mandatory)*

### Functional Requirements

#### Checkpoint Resume (Phase 1)

- **FR-001**: System MUST be able to resume a workflow from a saved checkpoint when the workflow status is "awaiting_human_response" (paused at a gate or approval point), restoring the full workflow state including current step position, workflow state dictionary, and pending approval requests. Workflows in "failed" status are NOT resumable and must be restarted.
- **FR-002**: System MUST skip all previously completed steps when resuming from a checkpoint, executing only from the checkpointed step forward.
- **FR-003**: System MUST accept human approval responses (approve/reject) when resuming a paused workflow and apply them to the pending gate or action request.
- **FR-004**: System MUST automatically save a checkpoint when a workflow pauses at a human gate, gated step, or action_executor approval point.
- **FR-005**: System MUST accumulate checkpoints — each save creates a new checkpoint with a unique ID rather than overwriting the previous one. Users MUST be able to list all saved checkpoints for a given workflow, showing checkpoint ID, timestamp, current step, and status, and resume from any of them.
- **FR-006**: System MUST validate checkpoint integrity on load by confirming the checkpoint's current step (agent ID + step type) still exists at the same position in the current workflow definition. Other workflow changes (e.g., appending new steps after the resume point) are permitted. The system MUST report clear errors if the checkpoint is corrupted or the resume step has been moved, removed, or changed.
- **FR-007**: System MUST reconstruct the agent execution context (agent instances with their configurations) from the checkpoint data and team configuration when resuming.

#### Event Streaming Enhancements (Phase 1)

- **FR-008**: System MUST emit an `output` event when a workflow produces terminal output.
- **FR-009**: System MUST emit a `checkpoint_saved` event when a checkpoint is persisted, including the checkpoint ID and step position.
- **FR-010**: System MUST emit an `approval` event when a human approval response is processed, including the decision and affected gate identifier.

#### Sub-Workflows (Phase 2)

- **FR-011**: System MUST support a `sub_workflow` step type that references another team configuration by name.
- **FR-012**: System MUST pass a configurable subset of parent state to the sub-workflow via an `input_mapping` definition.
- **FR-013**: System MUST merge sub-workflow results back into the parent state via an `output_mapping` definition.
- **FR-014**: System MUST propagate sub-workflow errors to the parent workflow as step errors.
- **FR-015**: System MUST enforce iteration limits on sub-workflows to prevent runaway execution.

#### Workflow-as-Agent (Phase 2)

- **FR-016**: System MUST allow a complete workflow to be wrapped as a single agent via an `as_agent()` method.
- **FR-017**: The wrapped workflow-agent MUST present the same interface as a regular agent (agent_id, role, execute method).
- **FR-018**: The wrapped workflow-agent MUST execute its inner workflow to completion and return the final state as its output.

#### Async Event Iterator (Phase 2)

- **FR-019**: System MUST provide an `execute_stream()` method that yields workflow events as an async iterator.
- **FR-020**: The async iterator MUST yield all event types that would be emitted via the callback mechanism.
- **FR-021**: Each yielded event MUST be serializable for transmission over streaming protocols.

### Key Entities

- **WorkflowCheckpoint**: A snapshot of workflow execution state at a specific point. Each save creates a new checkpoint with a unique ID (checkpoints accumulate rather than overwrite). Includes session ID, step index, full state dictionary, pending approval requests, iteration counts, team configuration reference, and creation timestamp. Users can resume from any accumulated checkpoint.
- **CheckpointStorage**: A pluggable backend interface for persisting and retrieving checkpoints. Built-in implementations include file-based (JSON files) and in-memory (for testing).
- **WorkflowStep**: A single step in the workflow graph, defining which agent executes, the step type (sequential, parallel_fan_out, conditional, human_gate, gated, sub_workflow), and transition rules.
- **StreamEvent**: A structured event emitted during workflow execution, containing event type, agent ID, timestamp, and event-specific data. Serializable for wire transmission.
- **TeamConfiguration**: The complete definition of a multi-agent team, including agent definitions, workflow graph, state schema, and optional publish configuration.
- **ApprovalRequest**: A pending request for human approval at a gate or action_executor step, containing the request ID, agent ID, description, and proposed actions.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Users can pause a workflow at any approval point and resume it later with full state preservation — no completed steps are re-executed upon resume.
- **SC-002**: Workflows with human-in-the-loop gates can survive process restarts and be resumed from persisted checkpoints within 5 seconds of requesting resume.
- **SC-003**: 100% of workflow lifecycle events (step start, step complete, step error, checkpoint saved, approval processed) are captured by registered event consumers with no dropped events.
- **SC-004**: Users can list all checkpoints for a workflow and identify the most recent one within a single operation.
- **SC-005**: Sub-workflows (Phase 2) execute as self-contained units — a failing sub-workflow does not corrupt the parent workflow state.
- **SC-006**: A workflow wrapped as an agent (Phase 2) is indistinguishable from a regular agent to the consuming workflow — no special handling is required by the parent.
- **SC-007**: Corrupted or incompatible checkpoints are detected and reported with actionable error messages before any workflow state is modified.

## Assumptions

- **File-based checkpoint storage** is sufficient for Phase 1. Database and Redis backends are deferred to future phases as plugin extensions.
- **Checkpoint versioning** uses a simple version field to detect incompatible changes. Full migration support between checkpoint versions is out of scope for Phase 1.
- **Sub-workflow team configurations** are loaded from the same sources as parent configurations (YAML/JSON files). Dynamic team generation for sub-workflows is out of scope.
- **Concurrent access** to checkpoints is not expected in typical usage (single user/process per workflow). Basic concurrent-access detection via status field is sufficient.
- **Event ordering** guarantees are limited to single-workflow execution. Cross-workflow event ordering is not guaranteed.
- **The existing WorkflowCheckpoint dataclass, CheckpointStorage protocol, and FileCheckpointStorage implementation** are the foundation for resume functionality — the spec builds on these rather than replacing them.

## Phasing

This feature spans two implementation phases as described in the requirements:

- **Phase 1**: Checkpoint resume at gates/approval points, automatic checkpointing at gates, new event types (`output`, `checkpoint_saved`, `approval`), checkpoint listing and validation.
- **Phase 2**: Sub-workflows, workflow-as-agent, async event iterator (`execute_stream()`), automatic checkpointing after every step, parallel sub-workflows, recursive nesting limits.
