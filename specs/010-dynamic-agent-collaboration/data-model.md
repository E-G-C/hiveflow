# Data Model: Dynamic Agent Collaboration

**Feature**: 010-dynamic-agent-collaboration
**Date**: 2026-03-04

## Entities

### CollaborationConfig

Configuration model for dynamic collaboration settings, nested within `TeamConfiguration`.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | `bool` | `False` | Whether dynamic collaboration tools are injected into orchestrator agents |
| `max_delegation_depth` | `int` | `3` | Maximum nesting depth for delegation chains |
| `max_spawned_agents` | `int` | `10` | Maximum agents that can be spawned per workflow execution |
| `allow_recursive_orchestrators` | `bool` | `False` | Whether spawned agents can themselves be orchestrators |
| `delegation_timeout_seconds` | `int` | `300` | Maximum time (seconds) for a single delegation to complete |
| `budget_policy` | `str` | `"inherit_parent"` | Budget propagation: `"inherit_parent"`, `"fixed"`, `"unlimited"` |
| `fixed_budget_tokens` | `int \| None` | `None` | Token budget per child when `budget_policy` is `"fixed"` |

**Validation rules**:
- `max_delegation_depth` must be >= 1
- `max_spawned_agents` must be >= 1
- `delegation_timeout_seconds` must be >= 1
- `budget_policy` must be one of: `"inherit_parent"`, `"fixed"`, `"unlimited"`
- `fixed_budget_tokens` required when `budget_policy` is `"fixed"`

**Relationships**:
- Belongs to `TeamConfiguration` (optional field, `collaboration: CollaborationConfig | None`)
- Global defaults mirrored in `HiveFlowConfig`

---

### CollaborationRuntime

Runtime manager created per workflow execution when collaboration is enabled. Not persisted — exists only during execution.

| Field | Type | Description |
|-------|------|-------------|
| `config` | `CollaborationConfig` | Merged config (team overrides global defaults) |
| `agent_pool` | `dict[str, Agent]` | Registry of all agents (pre-configured + dynamically spawned) |
| `archetype_library` | `ArchetypeLibrary` | Source of agent archetypes for spawning |
| `tool_registry` | `ToolRegistry` | Global tool registry for resolving tool references |
| `spawned_count` | `int` | Number of agents spawned in this execution (for limit enforcement) |
| `spawned_agent_ids` | `set[str]` | IDs of all spawned agents (for cleanup tracking) |
| `delegation_history` | `list[DelegationRecord]` | Audit trail of all delegations |

**Identity & uniqueness**: One instance per workflow execution. Not shared across executions.

**Lifecycle**: Created by `WorkflowEngine` at execution start → used by tool plugins during execution → discarded at execution end.

---

### DelegationRecord

Audit record for a single delegation event.

| Field | Type | Description |
|-------|------|-------------|
| `delegation_id` | `str` | Unique ID (auto-generated UUID) |
| `task` | `str` | Description of the delegated sub-task |
| `delegated_by` | `str` | Agent ID of the delegating orchestrator |
| `delegate_to` | `str` | Agent ID of the target agent |
| `depth` | `int` | Delegation depth level (1 = direct from orchestrator) |
| `status` | `str` | `"started"`, `"completed"`, `"failed"`, `"timeout"` |
| `started_at` | `datetime` | When delegation began |
| `completed_at` | `datetime \| None` | When delegation ended (None if in-flight) |
| `duration_ms` | `int \| None` | Execution duration in milliseconds |
| `tokens_used` | `int \| None` | Tokens consumed by the delegated execution |
| `result_summary` | `str \| None` | Brief summary of the result (for audit) |
| `error` | `str \| None` | Error message if failed |

**Lifecycle**: Created at delegation start (`status="started"`) → updated at completion/failure → stored in `CollaborationRuntime.delegation_history`.

---

### Message

Inter-agent message stored in shared workflow state.

| Field | Type | Description |
|-------|------|-------------|
| `message_id` | `str` | Unique ID (auto-generated UUID) |
| `from_agent` | `str` | Sender agent ID |
| `to_agent` | `str` | Recipient agent ID, or `"broadcast"` for all agents |
| `subject` | `str \| None` | Optional subject line |
| `body` | `str` | Message content |
| `requires_response` | `bool` | Whether the sender expects a reply |
| `timestamp` | `str` | ISO 8601 timestamp |
| `read` | `bool` | Whether the recipient has processed this message |

**Storage convention**: State key `_messages` is a `dict[str, list[Message]]` where keys are recipient agent IDs (or `"_broadcast"` for broadcasts).

**Lifecycle**: Created by `SendMessageTool` → stored in state → read/marked by `ReadMessagesTool` or auto-injected via `_summarize_state()` → persists in state for the duration of the workflow execution.

---

### TaskPlan

Structured decomposition produced by a collaborative planner orchestrator.

| Field | Type | Description |
|-------|------|-------------|
| `plan_id` | `str` | Unique ID (auto-generated UUID) |
| `created_by` | `str` | Agent ID of the planner orchestrator |
| `sub_tasks` | `list[SubTask]` | Ordered list of sub-tasks |

### SubTask

Individual unit within a task plan.

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Unique ID within the plan (e.g., `"st_1"`) |
| `description` | `str` | What needs to be done |
| `assigned_to` | `str` | Agent ID, `"auto"`, or `"spawn:{archetype}"` |
| `depends_on` | `list[str]` | IDs of prerequisite sub-tasks |
| `expected_output` | `str` | Output type: `"text"`, `"structured_data"`, `"decision"` |
| `status` | `str` | `"pending"`, `"in_progress"`, `"completed"`, `"failed"` |
| `result` | `Any \| None` | Output from the assigned agent |

**Relationships**: SubTask.depends_on references other SubTask.id values within the same plan. Forms a DAG (directed acyclic graph).

---

## State Contract Additions

New reserved keys added to the workflow state dict:

| Key | Type | Set by | Description |
|-----|------|--------|-------------|
| `_collaboration_runtime` | `CollaborationRuntime` | WorkflowEngine (init) | Runtime manager reference |
| `_messages` | `dict[str, list[dict]]` | SendMessageTool | Inter-agent message store |
| `_delegation_depth` | `int` | DelegateTaskTool | Current delegation nesting depth |

All keys are `_`-prefixed (internal) — agents cannot overwrite them through normal state mutations.

## Event Types Added

| Event Type | StreamEventType Value | Data Fields |
|------------|----------------------|-------------|
| Agent spawned | `AGENT_SPAWNED` | `agent_id`, `archetype`, `spawned_by`, `spawned_count` |
| Delegation started | `DELEGATION_STARTED` | `delegation_id`, `task`, `delegate_to`, `delegated_by`, `depth` |
| Delegation completed | `DELEGATION_COMPLETED` | `delegation_id`, `task`, `delegate_to`, `delegated_by`, `result_summary`, `duration_ms`, `tokens_used` |
| Delegation failed | `DELEGATION_FAILED` | `delegation_id`, `task`, `delegate_to`, `error`, `duration_ms` |
| Message sent | `MESSAGE_SENT` | `message_id`, `from_agent`, `to_agent`, `subject` |
| Plan created | `PLAN_CREATED` | `plan_id`, `created_by`, `sub_task_count` |
