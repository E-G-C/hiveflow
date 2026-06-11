# Implementation Plan: Workflow Engine

**Branch**: `004-workflow-engine` | **Date**: 2026-02-23 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/004-workflow-engine/spec.md`

## Summary

Implement checkpoint-based workflow resume, automatic checkpointing at gates/approval points, and new event types to complete the production-grade workflow execution lifecycle. Phase 1 focuses on making paused workflows resumable from persisted checkpoints with full state restoration. Phase 2 (deferred) adds sub-workflows, workflow-as-agent, and async event iterators.

The implementation builds on existing infrastructure: `WorkflowCheckpoint` dataclass, `FileCheckpointStorage`, `WorkflowSession`, and the `WorkflowEngine` execution loop. The primary work is wiring these components together for end-to-end resume and adding checkpoint accumulation.

## Technical Context

**Language/Version**: Python 3.11+ (no `from __future__ import annotations`)
**Primary Dependencies**: pydantic >=2.9.2, pydantic-settings, openai >=1.52.0, anthropic >=0.39.0, structlog >=24.4.0, httpx, aiofiles, pyyaml, json-repair
**Storage**: File-based JSON for workflow checkpoints (`FileCheckpointStorage` in `.hiveflow/checkpoints/`)
**Testing**: pytest + pytest-asyncio (auto mode) + pytest-cov + pytest-mock
**Target Platform**: Python library (cross-platform)
**Project Type**: Single Python package (`hiveflow/`)
**Performance Goals**: Resume from checkpoint within 5 seconds (SC-002)
**Constraints**: Async-first; core modules must remain usable as library without CLI/API
**Scale/Scope**: Single-user/process per workflow; file-based storage sufficient for Phase 1

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| 2.1 Configuration Over Code | PASS | Checkpointing is engine infrastructure, not user code. Workflows defined via YAML/JSON team configs. |
| 2.2 Progressive Disclosure | PASS | Checkpointing is opt-in via `checkpoint=True` parameter. Existing workflows unaffected. |
| 2.3 Explicit State, No Magic | PASS | Checkpoints capture the full state dict. Resume restores from that explicit state. No hidden channels. |
| 2.4 Plugin Architecture | PASS | `CheckpointStorage` is already a protocol. File-based and in-memory backends exist. New backends plug in. |
| 2.5 Backward Compatibility | PASS | All changes are additive. `execute()` signature gains optional params. Existing call sites unchanged. |
| 2.6 Observability | PASS | New event types (`output`, `checkpoint_saved`, `approval`) enhance observability. |
| 2.7 Fail Loudly | PASS | Checkpoint validation rejects corrupted/incompatible checkpoints with clear errors before state modification. |
| 3.1 Core Modules | PASS | All changes are in `core/`. No new external dependencies. No imports from `cli/`, `api/`, or `server/`. |
| 3.2 Plugin System | PASS | `CheckpointStorage` protocol unchanged. Accumulation support is additive. |
| 4.1 Workflow State | PASS | No new reserved state keys. Checkpoint state captures existing keys. |
| 6.1 Testing | PASS | Every new method will have unit tests. Integration tests cover full resume flow. |
| 6.3 Documentation | PASS | CHANGELOG and README updated. Public APIs have docstrings. |

**Result: All gates pass. No violations. Proceed to Phase 0.**

## Project Structure

### Documentation (this feature)

```text
specs/004-workflow-engine/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── checkpoint-api.md
└── tasks.md             # Phase 2 output (/speckit.tasks command)
```

### Source Code (repository root)

```text
hiveflow/
├── core/
│   ├── checkpoint.py    # MODIFY: Accumulation model, checkpoint_id, list by workflow
│   ├── workflow.py      # MODIFY: Add resume(), step index tracking, auto-checkpoint
│   ├── session.py       # MODIFY: Wire resume to engine re-execution
│   ├── hiveflow.py      # MODIFY: Update resume() to fully re-execute via engine
│   ├── streaming.py     # MODIFY: Add OUTPUT and APPROVAL event types
│   ├── schema.py        # MODIFY: Add sub_workflow step type (Phase 2 prep)
│   └── agent.py         # NO CHANGE for Phase 1
├── plugins/             # NO CHANGE
├── cli/                 # NO CHANGE for Phase 1
└── api/                 # NO CHANGE for Phase 1

tests/
├── test_checkpoint_session.py  # MODIFY: Add accumulation, resume, validation tests
├── test_workflow_resume.py     # NEW: Integration tests for full resume flow
└── test_workflow_events.py     # NEW: Event emission tests for new event types
```

**Structure Decision**: Existing single-package structure (`hiveflow/core/`) is used. All workflow engine changes are in `core/`. No new modules needed — changes modify 5 existing files and add 2 new test files.

## Complexity Tracking

> No constitution violations. This table is intentionally empty.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| (none)    | —          | —                                   |

## Post-Design Constitution Check

*Re-evaluation after Phase 1 design completion.*

| Principle | Status | Notes |
|-----------|--------|-------|
| 2.1 Configuration Over Code | PASS | No change from pre-design. Checkpointing enabled via parameter, not user code. |
| 2.2 Progressive Disclosure | PASS | `execute()` gains optional params with `None` defaults. Existing call sites untouched. |
| 2.3 Explicit State, No Magic | PASS | Resume passes `responses` dict explicitly. Checkpoint state is the sole truth. |
| 2.4 Plugin Architecture | PASS | `CheckpointStorage` protocol extended additively. Existing pattern preserved. |
| 2.5 Backward Compatibility | PASS* | `CheckpointStorage.save()` return type changes (`None` → `str`) and `list_checkpoints()` is added. This is acceptable pre-1.0; only built-in implementations exist. No external consumers affected. |
| 2.6 Observability | PASS | Three event types now emitted: `output`, `checkpoint_saved`, `approval`. Full lifecycle coverage. |
| 2.7 Fail Loudly | PASS | `CheckpointError` with descriptive messages for corruption, version mismatch, step mismatch. `ValueError` for wrong workflow status. `KeyError` for missing sessions. |
| 3.1 Core Modules | PASS | All changes in `core/`. Zero new external dependencies. No imports from cli/api/server. |
| 3.2 Plugin System | PASS | Protocol evolution is additive. New methods don't break existing protocol usage patterns. |
| 4.1 Workflow State | PASS | No new reserved keys. Existing `awaiting_*` flags reused. |
| 6.1 Testing | PASS | 2 new test files + modifications to existing checkpoint tests. Full coverage of resume flow. |
| 6.3 Documentation | PASS | quickstart.md, data-model.md, contracts/ all produced. CHANGELOG/README updates planned. |

**Result: All gates pass post-design. The CheckpointStorage protocol evolution (2.5) is a minor pre-1.0 change affecting only built-in implementations. No violations requiring complexity justification.**

