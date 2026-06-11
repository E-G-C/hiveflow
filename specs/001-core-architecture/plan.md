# Implementation Plan: Core Architecture

**Branch**: `001-core-architecture` | **Date**: 2026-02-22 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/001-core-architecture/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/plan-template.md` for the execution workflow.

## Summary

Implement the HiveFlow core architecture as defined in requirements/01-core-architecture.md: a universal agent class with 5 behavior types (including `action_executor`), dynamic team composition via 3 modes (template, custom, LLM-generated), a workflow graph engine with 6 step types (including `gated`), a public API (`HiveFlow` entry point + `WorkflowSession`), and Phase 1 workflow checkpointing at gates with file-based storage. The existing codebase provides ~70% of the foundation; this plan addresses the remaining gaps identified through code-level analysis.

## Technical Context

**Language/Version**: Python 3.11+ (no `from __future__ import annotations`)
**Primary Dependencies**: pydantic >=2.9.2, pydantic-settings, openai >=1.52.0, anthropic >=0.39.0, structlog >=24.4.0, httpx, aiofiles, pyyaml, json-repair, ratelimit
**Storage**: File-based JSON for workflow checkpoints; JSON/YAML files for team configs and archetypes
**Testing**: pytest via `uv run pytest` (471 existing tests, 78% coverage)
**Target Platform**: Cross-platform Python library (pip-installable package)
**Project Type**: Single Python package (`hiveflow/`)
**Performance Goals**: <100ms event delivery latency (SC-009); agent execution bounded by LLM provider latency
**Constraints**: Async-first with sync wrappers; core modules must not import cli/api; zero import-time LLM SDK dependencies in core; all public inputs/outputs JSON-serializable
**Scale/Scope**: Framework library consumed by CLI, REST API, and embedded Python applications

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| 2.1 Configuration Over Code | PASS | Teams, agents, archetypes all defined as config. New features (action_executor, gated steps) are config-driven. |
| 2.2 Progressive Disclosure | PASS | Simplest usage (`hf.run(team="name", task="query")`) unchanged. New fields (action_policy, model_requirements, gate) are optional with defaults. |
| 2.3 Explicit State, No Magic | PASS | All data flows through dict-based state. Checkpoint persists state explicitly. Action audit trail stored in state. |
| 2.4 Plugin Architecture | PASS | LLM providers, tools, document loaders remain plugins. CheckpointStorage uses protocol pattern for future pluggability. |
| 2.5 Backward Compatibility | PASS | All schema additions are optional fields with defaults. Enum additions (ACTION_EXECUTOR, GATED) are additive. Existing workflows unaffected. |
| 2.6 Observability | PASS | Event streaming already covers step lifecycle. New events (checkpoint_saved, action_executed) follow existing StreamEventType pattern. |
| 2.7 Fail Loudly, Recover Gracefully | PASS | Conditional loop limit raises error on exceed. Checkpoint corruption reports clear error. Validation catches invalid configs before execution. |

**Gate result: PASS** — No violations. Proceeding to Phase 0.

## Project Structure

### Documentation (this feature)

```text
specs/001-core-architecture/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── public-api.md    # HiveFlow + WorkflowSession API contract
└── tasks.md             # Phase 2 output (/speckit.tasks command)
```

### Source Code (repository root)

```text
hiveflow/
├── __init__.py                     # Package exports (update: add new public symbols)
├── core/
│   ├── agent.py                    # UPDATE: add ACTION_EXECUTOR behavior type + execution path
│   ├── workflow.py                 # UPDATE: add GATED step type, iteration limit behavior, checkpoint hooks
│   ├── schema.py                   # UPDATE: add action_policy, model_requirements, gate, output_type fields
│   ├── teams.py                    # UPDATE: extract ArchetypeLibrary class, add LLM generation
│   ├── config.py                   # (minor: no changes expected)
│   ├── state.py                    # (no changes expected)
│   ├── streaming.py                # UPDATE: add new event types (checkpoint_saved, action_executed)
│   ├── checkpoint.py               # NEW: WorkflowCheckpoint, FileCheckpointStorage
│   ├── session.py                  # NEW: WorkflowSession class
│   ├── hiveflow.py                 # NEW: HiveFlow top-level entry point
│   ├── result_payload.py           # (uses existing ActionRecord)
│   ├── compression.py              # (no changes)
│   ├── summarizer.py               # (no changes)
│   ├── fallback.py                 # (no changes)
│   ├── cost.py                     # (no changes)
│   ├── citations.py                # (no changes)
│   └── ...
├── plugins/
│   ├── llm/                        # (no changes)
│   ├── tools/                      # (no changes)
│   └── ...
├── api/
│   └── __init__.py                 # UPDATE: wire new HiveFlow/WorkflowSession API
├── cli/
│   └── ...                         # (no changes in scope)
└── templates/
    ├── teams/                      # (existing team templates)
    └── archetypes/                 # NEW: individual archetype JSON files

tests/
├── test_agent.py                   # UPDATE: add action_executor tests
├── test_workflow.py                # UPDATE: add gated step, iteration limit tests
├── test_schema.py                  # UPDATE: add new field validation tests
├── test_checkpoint.py              # NEW: checkpoint save/load/resume tests
├── test_session.py                 # NEW: WorkflowSession lifecycle tests
├── test_hiveflow.py                # NEW: HiveFlow entry point tests
├── test_archetypes.py              # NEW: ArchetypeLibrary tests
└── ...
```

**Structure Decision**: Single Python package following existing `hiveflow/core/` module structure. Three new core modules (`checkpoint.py`, `session.py`, `hiveflow.py`) added alongside existing modules. No new top-level packages needed.

## Complexity Tracking

No constitution violations to justify. All additions are additive optional fields, new modules following existing patterns, and new enum values — consistent with progressive disclosure and backward compatibility principles.

## Implementation Gap Analysis

| Component | Current State | Required State | Change Type |
|-----------|--------------|----------------|-------------|
| AgentBehaviorType | 4 values (llm_only, tool_user, orchestrator, human_gate) | 5 values (+action_executor) | Enum addition |
| Agent.execute() | 4 behavior paths | 5 behavior paths (+_execute_action_executor) | New method |
| AgentDefinition | No action_policy, model_requirements, output_type | All three fields added (optional) | Schema addition |
| StepType | 4 values (sequential, parallel_fan_out, conditional, human_gate) | 5 values (+gated) | Enum addition |
| WorkflowStepDefinition | No gate field | gate field added (optional, required when type=gated) | Schema addition |
| WorkflowEngine | max_conditional_loops=5, forces accept on exceed | Configurable per-step, fails on exceed (default 3) | Behavior change |
| Checkpoint support | None | FileCheckpointStorage + WorkflowCheckpoint + save/resume | New module |
| HiveFlow class | Does not exist | Top-level entry point with run/run_sync/generate_team | New module |
| WorkflowSession | Does not exist | Session handle with status/result/events/resume/cancel | New module |
| ArchetypeLibrary | Static dict in TeamGenerator | Separate class with file loading, default() | Refactor + new class |
| LLM team generation | Deterministic from archetypes only | LLM-based generation with capability gaps | New capability |
| TeamGenerationResult | Does not exist | Wraps config + gaps + new archetypes | New model |
| CapabilityGap | Does not exist | Severity-categorized gap reporting | New model |
| State schema enforcement | Schema exists but not enforced | warn/strict/off modes | New enforcement logic |
| OutputType inference | Not implemented | Default output_type from behavior_type | New logic |

## Constitution Check — Post-Design Re-evaluation

*GATE: Re-check after Phase 1 design is complete.*

| Principle | Status | Post-Design Notes |
|-----------|--------|-------------------|
| 2.1 Configuration Over Code | PASS | All new features (action_executor, gated steps, checkpointing) are config-driven. `HiveFlow` accepts config objects, not code. |
| 2.2 Progressive Disclosure | PASS | Quickstart examples confirm: 2 lines for template usage (~SC-002), <10 lines for custom (~SC-001). All new fields optional with defaults. |
| 2.3 Explicit State, No Magic | PASS | Data model shows all state flows through dict. WorkflowCheckpoint serializes full state explicitly. No hidden channels. |
| 2.4 Plugin Architecture | PASS | CheckpointStorage defined as Protocol for future pluggability. Only FileCheckpointStorage implemented (Phase 1). LLM/tool/document plugins unchanged. |
| 2.5 Backward Compatibility | PASS | Contracts document confirms: all schema additions optional, existing exports preserved, `max_conditional_loops` kept for compat, `TeamGenerator.ARCHETYPES` preserved but deprecated. |
| 2.6 Observability | PASS | 4 new StreamEventType values (CHECKPOINT_SAVED, ACTION_PROPOSED, ACTION_EXECUTED, GATE_REQUESTED) follow existing pattern. Events are structured and JSON-serializable. |
| 2.7 Fail Loudly, Recover Gracefully | PASS | Conditional loop exceed raises WorkflowError. Checkpoint corruption raises CheckpointError. ValidationError for invalid configs. All with actionable messages. |

**Post-design gate result: PASS** — No violations introduced by design artifacts.

## Generated Artifacts

| Artifact | Path | Description |
|----------|------|-------------|
| research.md | `specs/001-core-architecture/research.md` | 9 research decisions resolving all technical unknowns |
| data-model.md | `specs/001-core-architecture/data-model.md` | Entity definitions, field types, validation rules, state transitions |
| public-api.md | `specs/001-core-architecture/contracts/public-api.md` | HiveFlow + WorkflowSession API contracts with signatures |
| quickstart.md | `specs/001-core-architecture/quickstart.md` | 8 usage examples demonstrating target developer experience |

## Next Step

Run `/speckit.tasks` to generate the dependency-ordered implementation task list from this plan.
