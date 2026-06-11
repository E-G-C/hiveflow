# Data Model: Agents and Teams

**Feature**: 005-agents-and-teams
**Date**: 2026-02-24

## Entity Overview

This data model documents **changes and additions** to existing schemas. Entities marked "EXISTS" already have implementations; only the delta is documented.

## Entities

### AgentDefinition (EXISTS — schema.py)

**Changes**: Add 4 new optional fields.

| Field | Type | Default | Status | Description |
|-------|------|---------|--------|-------------|
| id | str | required | EXISTS | Unique agent identifier within the team |
| role | str | required | EXISTS | Human-readable role description |
| system_prompt | str | required | EXISTS | System prompt for the LLM |
| behavior_type | AgentBehaviorTypeSchema | required | EXISTS | One of: llm_only, tool_user, orchestrator, human_gate, action_executor |
| tools | list[str] | [] | EXISTS | Tool plugin IDs available to the agent |
| model | str \| None | None | EXISTS | Explicit model name (provider:model format) |
| max_tokens | int \| None | None | EXISTS | Maximum tokens for LLM response |
| documents | list[str] \| None | None | EXISTS | Document scoping patterns |
| document_mode | DocumentMode \| None | None | EXISTS | How documents are delivered to agent |
| max_document_tokens | int \| None | None | EXISTS | Token budget for document context |
| action_policy | str \| None | None | **MODIFIED** | Safety policy: auto, require_approval, **dry_run**, **confirm_on_error** |
| model_requirements | ModelRequirements \| None | None | EXISTS | Declarative model capability requirements |
| output_type | OutputType \| None | None | EXISTS | Output type: text, structured_data, side_effect, composite |
| **on_failure** | **str \| None** | **None** | **NEW** | **Failure policy: fail (default when None), retry, skip** |
| **max_retries** | **int** | **1** | **NEW** | **Max retry attempts when on_failure="retry"** |
| **rollback_on_failure** | **bool** | **False** | **NEW** | **Whether to trigger rollback on downstream failure** |
| **rollback_action** | **str \| None** | **None** | **NEW** | **Tool ID to invoke for rollback** |

**Validation rules**:
- `on_failure` must be one of `fail`, `retry`, `skip` when set
- `max_retries` must be >= 1
- `rollback_action` should reference a valid tool ID (validated at team level)
- `action_policy` validator extended to accept `dry_run` and `confirm_on_error`
- `rollback_on_failure` and `rollback_action` are only meaningful when `behavior_type` is `action_executor`

---

### WorkflowStepDefinition (EXISTS — schema.py)

**Changes**: Add `sub_workflow` to step type enum, add 3 new optional fields.

| Field | Type | Default | Status | Description |
|-------|------|---------|--------|-------------|
| agent | str | required | EXISTS | Agent ID to execute |
| type | WorkflowStepType | required | EXISTS | Step type (add **sub_workflow**) |
| next | str \| None | None | EXISTS | Next agent for sequential steps |
| next_on_accept | str \| None | None | EXISTS | Next agent on accept (conditional) |
| next_on_reject | str \| None | None | EXISTS | Next agent on reject (conditional) |
| gate | str \| None | None | EXISTS | Gate type for gated steps |
| max_iterations | int \| None | None | EXISTS | Per-step iteration limit for conditional loops (default: 3) |
| **team** | **str \| None** | **None** | **NEW** | **Team name for sub_workflow steps** |
| **input_mapping** | **dict[str, str] \| None** | **None** | **NEW** | **Outer→inner state key mapping for sub_workflow** |
| **output_mapping** | **dict[str, str] \| None** | **None** | **NEW** | **Inner→outer state key mapping for sub_workflow** |

**Validation rules**:
- `team` is required when `type` is `sub_workflow`
- `input_mapping`/`output_mapping` optional; when absent, inner workflow receives/returns full state
- `team` validated against TeamLibrary at build time

---

### WorkflowStepType (EXISTS — schema.py)

**Changes**: Add one new member.

| Value | Status |
|-------|--------|
| sequential | EXISTS |
| parallel_fan_out | EXISTS |
| conditional | EXISTS |
| human_gate | EXISTS |
| gated | EXISTS |
| **sub_workflow** | **NEW** |

---

### ActionRecord (EXISTS — result_payload.py)

**Changes**: Add 5 new optional fields, extend status values.

| Field | Type | Default | Status | Description |
|-------|------|---------|--------|-------------|
| action_id | str | required | EXISTS | Unique action identifier |
| action_type | str | required | EXISTS | Type of action taken |
| description | str | required | EXISTS | Human-readable description |
| status | str | required | **MODIFIED** | completed, failed, pending, approved, rejected, **dry_run** |
| agent_id | str | required | EXISTS | Agent that performed the action |
| timestamp | float | time.time() | EXISTS | When action occurred |
| metadata | dict | {} | EXISTS | Arbitrary metadata |
| **policy** | **str \| None** | **None** | **NEW** | **Action policy applied** |
| **approved_by** | **str \| None** | **None** | **NEW** | **Approver identity** |
| **reversible** | **bool** | **False** | **NEW** | **Can be rolled back** |
| **rollback_action** | **str \| None** | **None** | **NEW** | **Rollback tool ID** |
| **workflow_run_id** | **str \| None** | **None** | **NEW** | **Workflow run ID for correlation** |

---

### TeamConfiguration, StateSchema, ModelRequirements, CapabilityGap, TeamGenerationResult

**No schema changes needed.** All already contain the required fields.

---

## State Shape Changes

### Parallel Fan-Out State (MODIFIED)

After parallel execution, in addition to existing keys:

| Key | Type | Status | Description |
|-----|------|--------|-------------|
| `{agent}_outputs` | list[str] | EXISTS | Ordered list of parallel outputs |
| `{agent}_output` | str | EXISTS | Concatenated output (backward compat) |
| `{agent}_parallel_results` | dict[str, dict] | **NEW** | `item_{i}` → full result dict for granular access |

### Action Executor State (ENHANCED)

| Key | Type | Status | Description |
|-----|------|--------|-------------|
| `{agent}_action_records` | list[dict] | **MODIFIED** | Enhanced with policy, reversibility fields |
| `{agent}_dry_run_plan` | list[dict] | **NEW** | Planned actions when policy is dry_run |

### Transient Retry State (NEW — internal, not persisted to user state)

The transient retry layer does not write to workflow state. Retry attempts are logged via structlog. Only the final outcome (success or failure) reaches the `on_failure` policy.

## Relationship Diagram

```
TeamConfiguration
├── agents: list[AgentDefinition]
│   ├── behavior_type → AgentBehaviorType
│   ├── model_requirements → ModelRequirements (optional)
│   ├── output_type → OutputType (optional)
│   ├── action_policy: auto | require_approval | dry_run | confirm_on_error
│   ├── on_failure: fail | retry | skip
│   └── rollback_on_failure, rollback_action (action_executor only)
├── workflow: WorkflowGraph
│   └── steps: list[WorkflowStepDefinition]
│       ├── type → WorkflowStepType (incl. sub_workflow)
│       ├── max_iterations (conditional only)
│       └── team, input_mapping, output_mapping (sub_workflow only)
└── state_schema: StateSchema (optional)
    ├── required_keys
    ├── agent_io (per-agent reads/writes)
    └── enforcement_mode: warn | strict | off

ArchetypeLibrary → loads → AgentDefinition (partial, no workflow context)
TeamLibrary → loads → TeamConfiguration
TeamGenerator → generates → TeamGenerationResult
                              ├── config: TeamConfiguration
                              ├── capability_gaps: list[CapabilityGap]
                              └── new_archetypes: list[AgentDefinition]

Execution flow per agent:
  Agent.execute(state) → [transient backoff retry (FR-021)] → [on_failure policy (FR-020)] → workflow engine
```
