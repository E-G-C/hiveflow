# Data Model: Core Architecture

**Feature**: 001-core-architecture
**Date**: 2026-02-22

## Entity Definitions

### Agent (Updated)

**Module**: `hiveflow/core/agent.py`
**Type**: Class (runtime execution unit)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| agent_id | str | (required) | Unique identifier within workflow |
| role | str | (required) | Human-readable role description |
| system_prompt | str | (required) | LLM system prompt defining behavior |
| behavior_type | AgentBehaviorType | (required) | Execution strategy |
| tools | list[ToolPlugin] \| None | None | Available tools |
| model | str | "$SMART_LLM" | Model reference (tier var or provider:model) |
| llm_provider | LLMProvider \| None | None | Resolved provider instance |
| llm_config | LLMConfig \| None | None | LLM call configuration |
| max_tool_iterations | int | 10 | Tool calling loop limit |
| context_budget | int \| None | None | Input context token cap |
| action_policy | str \| None | None | **NEW**: Safety policy for action_executor ("auto"\|"require_approval") |
| output_type | str \| None | None | **NEW**: Expected output type (inferred from behavior_type if None) |
| agent_definition | Any \| None | None | Original AgentDefinition schema reference |

**Relationships**:
- Belongs to a workflow (referenced by WorkflowStep.agent)
- Uses ToolPlugin instances (many-to-many)
- Produces AgentResult on execution
- Created from AgentDefinition via `Agent.from_definition()`

### AgentBehaviorType (Updated)

**Module**: `hiveflow/core/agent.py`
**Type**: StrEnum

| Value | Description | Default Output Type |
|-------|-------------|-------------------|
| llm_only | Pure LLM response | text |
| tool_user | LLM + tool access | text |
| orchestrator | Decomposes tasks, spawns sub-work | structured_data |
| human_gate | Pauses for human input | text |
| action_executor | **NEW**: Performs side effects via tools with safety policies | side_effect |

### AgentResult (Unchanged)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| agent_id | str | (required) | Source agent |
| output | dict[str, Any] | (required) | Output state updates |
| response | LLMResponse \| None | None | Raw LLM response |
| tool_results | list[dict] \| None | None | Tool execution results |
| latency_ms | float | 0.0 | Execution time |

---

### AgentDefinition (Updated)

**Module**: `hiveflow/core/schema.py`
**Type**: Pydantic BaseModel

| Field | Type | Default | Validation | Description |
|-------|------|---------|------------|-------------|
| id | str | (required) | Non-empty | Unique identifier |
| role | str | (required) | Non-empty | Human-readable role |
| system_prompt | str | (required) | Non-empty | Behavior definition |
| behavior_type | str | (required) | Enum: llm_only\|tool_user\|orchestrator\|human_gate\|action_executor | Execution strategy |
| tools | list[str] | [] | Tool IDs | Available tools |
| model | str | "$SMART_LLM" | | Model reference |
| max_tokens | int \| None | None | >0 if set | Output token cap |
| documents | list[str] \| None | None | | Document names |
| document_mode | str | "none" | Enum | Document loading mode |
| max_document_tokens | int \| None | None | >0 if set | Per-agent doc token budget |
| action_policy | str \| None | None | **NEW**: "auto"\|"require_approval"; required when behavior_type=action_executor | Safety policy |
| model_requirements | dict[str, Any] \| None | None | **NEW**: See ModelRequirements shape | Declarative model requirements |
| output_type | str \| None | None | **NEW**: text\|structured_data\|side_effect\|composite | Output type (inferred if None) |

**Validation rules**:
- `action_policy` MUST be set when `behavior_type=action_executor`; MUST be None otherwise
- `model` takes precedence over `model_requirements` (explicit wins)
- When `output_type` is None, default inferred from `behavior_type`

### ModelRequirements (New)

**Module**: `hiveflow/core/schema.py`
**Type**: Pydantic BaseModel (embedded in AgentDefinition)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| cost_tier | str \| None | None | fast\|smart\|strategic (maps to LLMTier) |
| supports_tools | bool \| None | None | Requires tool/function calling |
| supports_vision | bool \| None | None | Requires vision/multimodal |
| strengths | list[str] | [] | Desired capabilities (e.g., "reasoning", "coding") |

---

### TeamConfiguration (Unchanged schema, updated agents)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| team_name | str | (required) | Unique name |
| description | str | (required) | Team purpose |
| agents | list[AgentDefinition] | (required) | Agent roster |
| workflow | WorkflowGraph | (required) | Execution graph |
| state_schema | StateSchema \| None | None | State enforcement rules |
| publish | PublishConfig \| None | None | Output publishing config |

**Validation rules**:
- All workflow steps must reference agents in the agents list (no dangling references)
- Agent IDs must be unique within the team
- At least one agent required
- At least one workflow step required

---

### WorkflowStepDefinition (Updated)

**Module**: `hiveflow/core/schema.py`
**Type**: Pydantic BaseModel

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| agent | str | (required) | Agent ID (may be empty for gated steps) |
| type | str | (required) | sequential\|parallel_fan_out\|conditional\|human_gate\|gated |
| next | str \| None | None | Next step (sequential) |
| next_on_accept | str \| None | None | Accept branch (conditional) |
| next_on_reject | str \| None | None | Reject branch (conditional) |
| max_iterations | int \| None | None | **NEW**: Per-step iteration limit for conditional (default: 3) |
| gate_id | str \| None | None | **NEW**: Unique gate identifier (required when type=gated) |
| gate_description | str \| None | None | **NEW**: Human-readable gate context (for gated steps) |

**Validation rules**:
- `gate_id` required when type=gated
- `agent` may be empty string when type=gated (no agent executes; it's a workflow pause)
- `next_on_accept`/`next_on_reject` required when type=conditional
- `max_iterations` only meaningful when type=conditional; ignored otherwise

---

### WorkflowStep (Updated)

**Module**: `hiveflow/core/workflow.py`
**Type**: Dataclass (runtime)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| agent | str | (required) | Agent ID |
| step_type | StepType \| str | (required) | Step execution strategy |
| next_step | str \| None | None | Next step (sequential) |
| next_on_accept | str \| None | None | Accept branch |
| next_on_reject | str \| None | None | Reject branch |
| max_iterations | int | 3 | **NEW**: Conditional loop limit |
| gate_id | str \| None | None | **NEW**: Gate identifier |
| gate_description | str \| None | None | **NEW**: Gate context |

### StepType (Updated)

| Value | Description |
|-------|-------------|
| sequential | Execute agent, proceed to next |
| parallel_fan_out | Execute agent N times (one per parallel_item) |
| conditional | Evaluate output, branch to accept/reject |
| human_gate | Agent-level pause for human input |
| gated | **NEW**: Workflow-level pause (no agent execution) |

---

### WorkflowSession (New)

**Module**: `hiveflow/core/session.py`
**Type**: Class

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| session_id | str | UUID4 | Unique session identifier |
| status | WorkflowStatus | PENDING | Current session status |
| team_config | TeamConfiguration | (required) | Team configuration being executed |
| task | str | (required) | User's task/query |
| result | WorkflowResult \| None | None | Execution result (set on completion) |
| error | str \| None | None | Error message (set on failure) |
| pending_requests | list[ApprovalRequest] | [] | Active approval/gate requests |
| events | StreamChannel | (auto) | Event streaming channel |
| checkpoint_storage | CheckpointStorage \| None | None | Checkpoint backend |
| created_at | float | time.time() | Session creation timestamp |

**State transitions**:
```
PENDING → RUNNING → COMPLETED
PENDING → RUNNING → FAILED
PENDING → RUNNING → PAUSED → RUNNING → COMPLETED
PENDING → RUNNING → PAUSED → CANCELLED (via cancel())
```

**Methods**:
- `async resume(responses: dict[str, Any]) -> None`
- `async cancel() -> None`
- `subscribe() -> StreamConsumer`
- `to_dict() -> dict[str, Any]` (JSON-serializable)

### ApprovalRequest (New)

**Module**: `hiveflow/core/session.py`
**Type**: Dataclass (frozen)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| request_id | str | UUID4 | Unique request identifier |
| request_type | str | (required) | "human_gate"\|"action_approval"\|"gate" |
| context | dict[str, Any] | {} | Decision context (agent output, proposed actions, gate description) |
| agent_id | str \| None | None | Source agent (None for workflow gates) |
| step_index | int | (required) | Workflow step that triggered the pause |
| created_at | float | time.time() | Request creation timestamp |

---

### WorkflowCheckpoint (New)

**Module**: `hiveflow/core/checkpoint.py`
**Type**: Dataclass (frozen)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| session_id | str | (required) | Session this checkpoint belongs to |
| step_index | int | (required) | Workflow step index at pause |
| state | dict[str, Any] | (required) | Accumulated workflow state |
| pending_requests | list[dict[str, Any]] | [] | Serialized ApprovalRequests |
| iteration_counts | dict[str, int] | {} | Per-step iteration counters |
| team_config | dict[str, Any] | (required) | Serialized TeamConfiguration |
| task | str | (required) | Original task |
| created_at | float | time.time() | Checkpoint creation timestamp |
| version | str | "1" | Checkpoint format version |

**Methods**:
- `to_dict() -> dict[str, Any]`
- `@classmethod from_dict(data: dict) -> WorkflowCheckpoint`

### CheckpointStorage (New)

**Module**: `hiveflow/core/checkpoint.py`
**Type**: Protocol

| Method | Signature | Description |
|--------|-----------|-------------|
| save | `async save(checkpoint: WorkflowCheckpoint) -> None` | Persist checkpoint |
| load | `async load(session_id: str) -> WorkflowCheckpoint \| None` | Load checkpoint by session ID |
| delete | `async delete(session_id: str) -> None` | Remove checkpoint |
| list_sessions | `async list_sessions() -> list[str]` | List checkpointed session IDs |

### FileCheckpointStorage (New)

**Module**: `hiveflow/core/checkpoint.py`
**Type**: Class (implements CheckpointStorage)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| directory | Path | ".hiveflow/checkpoints" | Storage directory |

---

### CapabilityGap (New)

**Module**: `hiveflow/core/teams.py`
**Type**: Pydantic BaseModel

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| resource_type | str | (required) | "tool"\|"model"\|"capability" |
| resource_id | str | (required) | Tool ID, model name, or capability name |
| severity | str | (required) | "blocking"\|"degraded"\|"functional_but_limited" |
| description | str | (required) | What's missing and why it matters |
| fallback_strategy | str \| None | None | Suggested workaround |

### TeamGenerationResult (New)

**Module**: `hiveflow/core/teams.py`
**Type**: Pydantic BaseModel

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| config | TeamConfiguration | (required) | Generated team configuration |
| capability_gaps | list[CapabilityGap] | [] | Missing capabilities |
| new_archetypes | list[dict[str, Any]] | [] | Novel archetypes invented by LLM |
| has_blocking_gaps | bool | (computed) | True if any gap is blocking |

---

### ArchetypeLibrary (New)

**Module**: `hiveflow/core/teams.py`
**Type**: Class

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| _archetypes | dict[str, dict[str, Any]] | {} | Registered archetypes |

**Methods**:
- `register(name: str, archetype: dict[str, Any]) -> None`
- `get(name: str) -> dict[str, Any] | None`
- `list_archetypes() -> list[str]`
- `@classmethod from_directory(cls, directory: str | Path) -> ArchetypeLibrary`
- `@classmethod default(cls) -> ArchetypeLibrary` (loads bundled archetypes)

---

### StateSchema (Updated)

**Module**: `hiveflow/core/schema.py`
**Type**: Pydantic BaseModel

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| required_keys | list[str] | [] | Keys that must exist in initial state |
| agent_io | dict[str, AgentIOMapping] | {} | Per-agent read/write declarations |
| enforcement_mode | str | "warn" | **NEW**: "warn"\|"strict"\|"off" |

### HiveFlow (New)

**Module**: `hiveflow/core/hiveflow.py`
**Type**: Class (facade)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| config | HiveFlowConfig | get_config() | Framework configuration |
| _team_library | TeamTemplateLibrary | TeamTemplateLibrary.default() | Team templates |
| _archetype_library | ArchetypeLibrary | ArchetypeLibrary.default() | Agent archetypes |
| _tool_registry | ToolRegistry | ToolRegistry() | Available tools |
| _llm_registry | LLMProviderRegistry | LLMProviderRegistry() | LLM providers |
| _checkpoint_storage | CheckpointStorage \| None | None | Checkpoint backend |
| _active_sessions | dict[str, WorkflowSession] | {} | In-memory session tracking |

**Methods**:
- `async run(team: str | TeamConfiguration | dict, task: str, **kwargs) -> WorkflowSession`
- `run_sync(team: str | TeamConfiguration | dict, task: str, **kwargs) -> WorkflowSession`
- `async generate_team(task: str, **kwargs) -> TeamGenerationResult`
- `async resume(session_id: str, responses: dict[str, Any]) -> WorkflowSession`
- `team_library() -> TeamTemplateLibrary`
- `archetype_library() -> ArchetypeLibrary`
- `tool_registry() -> ToolRegistry`
- `model_registry() -> LLMProviderRegistry`

### StreamEventType (Updated)

| Value | Description |
|-------|-------------|
| (existing values) | ... |
| CHECKPOINT_SAVED | **NEW**: Checkpoint persisted to storage |
| ACTION_PROPOSED | **NEW**: action_executor proposes actions (before approval) |
| ACTION_EXECUTED | **NEW**: action_executor completed an action |
| GATE_REQUESTED | **NEW**: Gated step requests external approval |
