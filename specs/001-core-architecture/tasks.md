# Implementation Tasks: Core Architecture

**Feature**: 001-core-architecture
**Date**: 2026-02-23
**Generated from**: [spec.md](spec.md), [plan.md](plan.md), [data-model.md](data-model.md)

## Task Dependency Graph

```
Layer 0 (Schema)     T001 ─┬─ T002 ─┬─ T003 ─── T004
                            │        │
Layer 1 (Core)       T005 ─┤  T006 ─┤  T007 ─── T008
                            │        │
Layer 2 (Session)    T009 ──┴─ T010 ─┘
                            │
Layer 3 (Facade)     T011 ──── T012
                            │
Layer 4 (Tests)      T013 ─ T014 ─ T015 ─ T016
```

## Layer 0 — Schema & Enums (no dependencies)

### T001 <!-- bd:hiveflow-2a0.1 -->: Schema — Add action_executor behavior type + agent fields

**Files**: `hiveflow/core/schema.py`
**FR**: FR-001, FR-002, FR-003, FR-013, FR-018

Add to `AgentBehaviorTypeSchema` enum:
- `ACTION_EXECUTOR = "action_executor"`

Add to `AgentDefinition` model:
- `action_policy: str | None = None` — "auto"|"require_approval"; required when behavior_type=action_executor
- `model_requirements: ModelRequirements | None = None` — declarative model requirements
- `output_type: str | None = None` — text|structured_data|side_effect|composite

Create `ModelRequirements` pydantic model:
- `cost_tier: str | None = None` — fast|smart|strategic
- `supports_tools: bool | None = None`
- `supports_vision: bool | None = None`
- `strengths: list[str] = []`

Add validators:
- `action_policy` MUST be set when behavior_type=action_executor; MUST be None otherwise
- `model` takes precedence over `model_requirements`
- When `output_type` is None, default inferred from behavior_type

**Acceptance**: All existing tests pass; new validation rules enforced.

---

### T002 <!-- bd:hiveflow-2a0.2 -->: Schema — Add gated step type + step fields

**Files**: `hiveflow/core/schema.py`
**FR**: FR-007
**Depends on**: None

Add to `WorkflowStepType` enum:
- `GATED = "gated"`

Add to `WorkflowStepDefinition` model:
- `max_iterations: int | None = None` — per-step iteration limit (default: 3 when conditional)
- `gate_id: str | None = None` — required when type=gated
- `gate_description: str | None = None` — human-readable gate context

Update validators:
- `gate_id` required when type=gated
- `agent` may be empty string when type=gated
- `max_iterations` only meaningful for conditional steps

Update `TeamConfiguration.validate_workflow_references` to allow empty agent for gated steps.

**Acceptance**: Gated step configs validate; empty agent allowed for gated type only.

---

### T003 <!-- bd:hiveflow-2a0.3 -->: Schema — Add state enforcement mode

**Files**: `hiveflow/core/schema.py`
**FR**: FR-017
**Depends on**: None

Add to `StateSchema`:
- `enforcement_mode: str = "warn"` — "warn"|"strict"|"off"

Add validator for enforcement_mode values.

**Acceptance**: StateSchema accepts warn/strict/off; rejects invalid values.

---

### T004 <!-- bd:hiveflow-2a0.4 -->: Streaming — Add new event types

**Files**: `hiveflow/core/streaming.py`
**FR**: FR-011
**Depends on**: None

Add to `StreamEventType` enum:
- `CHECKPOINT_SAVED = "checkpoint_saved"`
- `ACTION_PROPOSED = "action_proposed"`
- `ACTION_EXECUTED = "action_executed"`
- `GATE_REQUESTED = "gate_requested"`

**Acceptance**: New event types available; existing events unchanged.

---

## Layer 1 — Core Modules (depend on Layer 0)

### T005 <!-- bd:hiveflow-2a0.5 -->: Agent — Add action_executor behavior type

**Files**: `hiveflow/core/agent.py`
**FR**: FR-002, FR-003, FR-018
**Depends on**: T001

Add to `AgentBehaviorType` runtime enum:
- `ACTION_EXECUTOR = "action_executor"`

Add to `Agent.__init__`:
- `action_policy: str | None = None`
- `output_type: str | None = None`

Add `_execute_action_executor()` method:
- Reuses tool_user loop (LLM decides which tools to call)
- When `action_policy=require_approval`: pauses after LLM proposes tool calls, returns state with `awaiting_action_approval=True` and proposed actions
- When `action_policy=auto`: executes tools immediately, records each as ActionRecord in state
- Always records executed actions as structured audit entries

Add to `execute()` dispatch: `ACTION_EXECUTOR` → `_execute_action_executor()`

Update `from_definition()`: handle `action_executor` behavior type + `action_policy` field.

**Acceptance**: action_executor agents can execute with both auto and require_approval policies.

---

### T006 <!-- bd:hiveflow-2a0.6 -->: Workflow — Add gated step + conditional loop failure + iteration limits

**Files**: `hiveflow/core/workflow.py`
**FR**: FR-007, FR-009
**Depends on**: T002, T004

Add to `StepType` runtime enum:
- `GATED = "gated"`

Add to `WorkflowStep` dataclass:
- `max_iterations: int = 3`
- `gate_id: str | None = None`
- `gate_description: str | None = None`

Update `WorkflowEngine.execute()`:
- Handle `GATED` step type: emit GATE_REQUESTED event, transition to PAUSED status, return result with pending gate info
- Handle `ACTION_EXECUTOR` pause: when agent returns `awaiting_action_approval=True`, emit ACTION_PROPOSED, transition to PAUSED

Update `_resolve_next_step()`:
- Use per-step `max_iterations` (from WorkflowStep) when available, fall back to `self.max_conditional_loops`
- Change exceeded behavior: raise WorkflowError instead of forcing accept path
- Keep `max_conditional_loops` constructor param for backward compat

Update `WorkflowEngine.from_schema()`: pass through new fields.

**Acceptance**: Gated steps pause workflow; conditional loops fail on exceed; per-step iteration limits work.

---

### T007 <!-- bd:hiveflow-2a0.7 -->: Checkpoint — Create checkpoint module

**Files**: `hiveflow/core/checkpoint.py` (NEW)
**FR**: FR-019
**Depends on**: T004

Create:
- `WorkflowCheckpoint` frozen dataclass: session_id, step_index, state, pending_requests, iteration_counts, team_config, task, created_at, version
  - `to_dict()` and `from_dict()` methods
- `CheckpointStorage` Protocol: save, load, delete, list_sessions (all async)
- `FileCheckpointStorage` class: JSON file per session in configurable directory (default: `.hiveflow/checkpoints`)
- `CheckpointError` exception class

**Acceptance**: Checkpoint can be saved to file, loaded, deleted; corrupt file raises CheckpointError.

---

### T008 <!-- bd:hiveflow-2a0.8 -->: Workflow — Add state schema enforcement

**Files**: `hiveflow/core/workflow.py`
**FR**: FR-017
**Depends on**: T003

Add enforcement logic to `WorkflowEngine`:
- Accept optional `state_schema` parameter in constructor
- After each agent execution (in execute loop), check state writes against schema
- `warn` mode: log structlog warnings for undeclared writes
- `strict` mode: filter agent output to only declared write keys
- `off` mode: no enforcement
- Enforcement runs post-agent, pre-state-merge

**Acceptance**: Undeclared writes produce warnings in warn mode; filtered in strict mode; ignored in off mode.

---

## Layer 2 — Session & Library (depend on Layer 1)

### T009 <!-- bd:hiveflow-2a0.9 -->: Session — Create WorkflowSession + ApprovalRequest

**Files**: `hiveflow/core/session.py` (NEW)
**FR**: FR-009, FR-012, FR-014
**Depends on**: T005, T006, T007

Create:
- `ApprovalRequest` frozen dataclass: request_id (UUID4), request_type, context, agent_id, step_index, created_at
- `WorkflowSession` class:
  - Properties: session_id, status, result, error, pending_requests, created_at
  - Methods: `async resume(responses)`, `async cancel()`, `subscribe()` → StreamConsumer, `to_dict()`
  - State transitions: PENDING → RUNNING → COMPLETED/FAILED/PAUSED → RUNNING/CANCELLED
  - Integrates with CheckpointStorage for save on pause, load on resume

**Acceptance**: Session tracks lifecycle; resume/cancel work; to_dict is JSON-serializable.

---

### T010 <!-- bd:hiveflow-2a0.10 -->: Teams — Extract ArchetypeLibrary + CapabilityGap + TeamGenerationResult

**Files**: `hiveflow/core/teams.py`
**FR**: FR-005, FR-015, FR-016
**Depends on**: T001

Create `ArchetypeLibrary` class:
- `register(name, archetype)`, `get(name)`, `list_archetypes()`
- `from_directory(path)`, `default()` (loads from TeamGenerator.ARCHETYPES initially)

Create `CapabilityGap` pydantic model:
- resource_type, resource_id, severity, description, fallback_strategy

Create `TeamGenerationResult` pydantic model:
- config (TeamConfiguration), capability_gaps, new_archetypes, has_blocking_gaps (computed)

Update `TeamGenerator`:
- Accept `ArchetypeLibrary` as constructor dependency
- Keep `ARCHETYPES` dict for backward compat (deprecated)
- Add `action_executor` to behavior_map in `build()`

**Acceptance**: ArchetypeLibrary works like TeamTemplateLibrary; TeamGenerator accepts library; backward compat maintained.

---

## Layer 3 — Facade (depends on Layer 2)

### T011 <!-- bd:hiveflow-2a0.11 -->: HiveFlow — Create top-level entry point

**Files**: `hiveflow/core/hiveflow.py` (NEW)
**FR**: FR-008, FR-010, FR-014
**Depends on**: T009, T010

Create `HiveFlow` facade class:
- Constructor: config, team_library, archetype_library, tool_registry, llm_registry, checkpoint_storage (all optional with defaults)
- `async run(team, task, *, documents, initial_state, checkpoint)` → WorkflowSession
- `run_sync(team, task, **kwargs)` → WorkflowSession (sync wrapper)
- `async generate_team(task, *, model, auto_approve)` → TeamGenerationResult
- `async resume(session_id, responses)` → WorkflowSession
- Discovery: `team_library()`, `archetype_library()`, `tool_registry()`, `model_registry()`

Team resolution: str → template lookup, dict → validate as TeamConfiguration, TeamConfiguration → use directly.

**Acceptance**: HiveFlow.run/run_sync execute workflows; generate_team returns valid result; discovery methods work.

---

### T012 <!-- bd:hiveflow-2a0.12 -->: Exports — Update __init__.py + Agent.from_definition

**Files**: `hiveflow/__init__.py`, `hiveflow/core/agent.py`
**FR**: FR-014
**Depends on**: T011

Update `hiveflow/__init__.py`:
- Add imports: HiveFlow, WorkflowSession, ApprovalRequest, WorkflowCheckpoint, FileCheckpointStorage, CheckpointStorage, ArchetypeLibrary, CapabilityGap, TeamGenerationResult, ModelRequirements
- Add to `__all__`

Update `Agent.from_definition()`:
- Add `action_executor` to behavior_map
- Pass through `action_policy` and `output_type`

**Acceptance**: All new public symbols importable from `hiveflow`; from_definition handles action_executor.

---

## Layer 4 — Tests (depend on implementation layers)

### T013 <!-- bd:hiveflow-2a0.13 -->: Tests — Schema additions

**Files**: `tests/test_schema_additions.py` (NEW)
**Depends on**: T001, T002, T003

Test:
- AgentDefinition with action_executor requires action_policy
- AgentDefinition rejects action_policy when not action_executor
- ModelRequirements validation
- output_type validation
- WorkflowStepDefinition with gated type requires gate_id
- WorkflowStepDefinition allows empty agent for gated
- max_iterations on conditional steps
- StateSchema enforcement_mode validation
- TeamConfiguration allows gated steps with empty agent

**Acceptance**: All schema validation rules covered by tests.

---

### T014 <!-- bd:hiveflow-2a0.14 -->: Tests — Action executor + gated steps + conditional loops

**Files**: `tests/test_action_executor.py` (NEW), `tests/test_gated_steps.py` (NEW)
**Depends on**: T005, T006

Test:
- action_executor with auto policy executes tools immediately
- action_executor with require_approval pauses workflow
- action_executor records audit trail
- Gated step pauses workflow with GATE_REQUESTED event
- Conditional loop fails on exceeding max_iterations
- Per-step max_iterations overrides global

**Acceptance**: All behavior paths covered.

---

### T015 <!-- bd:hiveflow-2a0.15 -->: Tests — Checkpoint + session + state enforcement

**Files**: `tests/test_checkpoint.py` (NEW), `tests/test_session.py` (NEW)
**Depends on**: T007, T008, T009

Test:
- FileCheckpointStorage save/load/delete/list
- Corrupt checkpoint raises CheckpointError
- WorkflowSession lifecycle transitions
- Session resume/cancel
- Session to_dict serialization
- State enforcement warn/strict/off modes

**Acceptance**: All checkpoint and session behaviors covered.

---

### T016 <!-- bd:hiveflow-2a0.16 -->: Tests — HiveFlow facade + ArchetypeLibrary

**Files**: `tests/test_hiveflow_facade.py` (NEW), `tests/test_archetype_library.py` (NEW)
**Depends on**: T010, T011, T012

Test:
- HiveFlow.run with template name
- HiveFlow.run with dict config
- HiveFlow.run_sync wrapper
- HiveFlow discovery methods
- ArchetypeLibrary register/get/list
- ArchetypeLibrary.default() loads built-in archetypes
- TeamGenerationResult.has_blocking_gaps property
- CapabilityGap model validation

**Acceptance**: All facade and library behaviors covered.
