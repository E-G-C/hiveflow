# Python API Contracts: Agents and Teams

**Feature**: 005-agents-and-teams
**Date**: 2026-02-24

This document defines the public Python API contracts for changes and additions in the agents and teams feature. All async-first per constitution §5.4.

---

## Schema Additions (pydantic models)

### AgentDefinition — New Fields

```python
# In hiveflow/core/schema.py — additions to existing AgentDefinition

class AgentDefinition(BaseModel):
    # ... existing fields ...

    on_failure: str | None = Field(
        default=None,
        description="Failure policy: 'fail' (default), 'retry', 'skip'",
    )
    max_retries: int = Field(
        default=1,
        ge=1,
        description="Max retry attempts when on_failure='retry'",
    )
    rollback_on_failure: bool = Field(
        default=False,
        description="Trigger rollback tool on downstream failure",
    )
    rollback_action: str | None = Field(
        default=None,
        description="Tool ID to invoke for rollback",
    )

    @field_validator("on_failure")
    @classmethod
    def validate_on_failure(cls, v: str | None) -> str | None:
        if v is not None and v not in ("fail", "retry", "skip"):
            raise ValueError("on_failure must be 'fail', 'retry', or 'skip'")
        return v

    # Updated action_policy validator (replaces existing)
    @field_validator("action_policy")
    @classmethod
    def validate_action_policy(cls, v: str | None) -> str | None:
        if v is not None and v not in ("auto", "require_approval", "dry_run", "confirm_on_error"):
            raise ValueError(
                "action_policy must be 'auto', 'require_approval', 'dry_run', or 'confirm_on_error'"
            )
        return v
```

### WorkflowStepType — New Member

```python
class WorkflowStepType(StrEnum):
    SEQUENTIAL = "sequential"
    PARALLEL_FAN_OUT = "parallel_fan_out"
    CONDITIONAL = "conditional"
    HUMAN_GATE = "human_gate"
    GATED = "gated"
    SUB_WORKFLOW = "sub_workflow"  # NEW
```

### WorkflowStepDefinition — New Fields

```python
class WorkflowStepDefinition(BaseModel):
    # ... existing fields ...

    team: str | None = Field(
        default=None,
        description="Team name for sub_workflow steps",
    )
    input_mapping: dict[str, str] | None = Field(
        default=None,
        description="Outer→inner state key mapping for sub_workflow",
    )
    output_mapping: dict[str, str] | None = Field(
        default=None,
        description="Inner→outer state key mapping for sub_workflow",
    )
```

### ActionRecord — Enhanced Fields

```python
@dataclass(frozen=True)
class ActionRecord:
    action_id: str
    action_type: str
    description: str
    status: str  # "completed", "failed", "pending", "approved", "rejected", "dry_run"
    agent_id: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)
    # NEW fields
    policy: str | None = None
    approved_by: str | None = None
    reversible: bool = False
    rollback_action: str | None = None
    workflow_run_id: str | None = None
```

---

## Agent Execution Contracts

### Action Executor — dry_run Path

```python
async def _execute_action_executor(self, state: dict[str, Any]) -> dict[str, Any]:
    """
    Enhanced with 4 policies:
    - auto: execute immediately
    - require_approval: pause for human approval
    - dry_run: plan actions without executing (NEW)
    - confirm_on_error: execute, escalate on failure (NEW)
    """
```

**dry_run contract**:
- Input: state dict
- Behavior: LLM proposes tool calls; recorded with `status="dry_run"` without execution
- Output state key: `{agent_id}_dry_run_plan` (list of planned action dicts)
- No side effects

**confirm_on_error contract**:
- Input: state dict
- Behavior: execute tools like `auto`; on tool error, checkpoint and pause
- On error: checkpoint with `awaiting_error_resolution` containing error details
- Resume accepts: `retry`, `skip`, or `abort`

### Transient Error Backoff (FR-021)

```python
# In hiveflow/core/workflow.py

async def _retry_transient(
    self,
    func: Callable[..., Awaitable[T]],
    *args: Any,
    max_retries: int = 3,
    base_delay: float = 1.0,
    backoff_factor: float = 2.0,
    transient_exceptions: tuple[type[Exception], ...] = (),
    **kwargs: Any,
) -> T:
    """
    Retry an async function with exponential backoff for transient errors.

    Applied automatically to every agent execution before the on_failure
    policy is evaluated. Catches transient LLM errors (429 rate limit,
    5xx server errors, connection/timeout errors) and retries with
    delays of base_delay * backoff_factor^attempt (1s, 2s, 4s).

    Args:
        func: Async function to execute
        max_retries: Max retry attempts (default: 3)
        base_delay: Initial delay in seconds (default: 1.0)
        backoff_factor: Delay multiplier per attempt (default: 2.0)
        transient_exceptions: Additional exception types to treat as transient

    Returns:
        Result of the function

    Raises:
        The last exception if all retries exhausted (propagates to on_failure)
    """
```

**Transient error detection heuristic**:
- `httpx.HTTPStatusError` with status 429 or 5xx
- `openai.RateLimitError`, `openai.APIStatusError` with 5xx
- `anthropic.RateLimitError`, `anthropic.APIStatusError` with 5xx
- `ConnectionError`, `TimeoutError`, `asyncio.TimeoutError`

### Agent Failure Handling (FR-020)

```python
async def _execute_agent_with_failure_policy(
    self,
    agent: Agent,
    state: dict[str, Any],
    on_failure: str = "fail",
    max_retries: int = 1,
) -> dict[str, Any]:
    """
    Wraps agent execution with transient backoff (FR-021) then failure policy (FR-020):

    1. Call _retry_transient(agent.execute, state) — handles 429/5xx with backoff
    2. If transient retry succeeds → return result
    3. If transient retry exhausted → apply on_failure policy:
       - fail: re-raise exception (workflow halts)
       - retry: retry up to max_retries times (these are non-transient retries), then re-raise
       - skip: log warning, return state unmodified
    """
```

---

## Workflow Engine Contracts

### Sub-Workflow Execution

```python
async def _execute_sub_workflow(
    self,
    step: WorkflowStep,
    state: dict[str, Any],
) -> dict[str, Any]:
    """
    Execute a nested workflow:
    1. Load inner team config from TeamLibrary by step.team name
    2. Build inner agents and WorkflowEngine
    3. Map state via input_mapping (or pass full state)
    4. Execute inner workflow
    5. Map result via output_mapping (or merge full result)
    6. Return updated outer state

    Raises RuntimeError if sub_workflow depth exceeds 5.
    """
```

### Parallel Fan-Out — Namespaced Merge

```python
async def _execute_parallel(
    self,
    step: WorkflowStep,
    state: dict[str, Any],
) -> dict[str, Any]:
    """
    Enhanced parallel execution:
    - Each instance writes to {agent}_output (individual)
    - All collected into {agent}_outputs (list) — existing behavior preserved
    - Concatenated into {agent}_output (string) — existing behavior preserved
    - NEW: {agent}_parallel_results (dict) with item_{i} → result for granular access
    """
```

### Conditional Evaluation — Reject Default

```python
def _evaluate_condition(self, state: dict[str, Any], agent_id: str) -> bool:
    """
    Returns True for accept, False for reject.
    CHANGED: When accept_score == reject_score (tie/ambiguous): returns False (reject).
    Logs structlog warning on ambiguous result.
    """
```

---

## Team Composition Contracts

### LLM-Based Team Generation (FR-013)

```python
class TeamGenerator:
    async def generate_team_from_llm(
        self,
        task_description: str,
        llm_provider: LLMProvider,
        tool_registry: ToolRegistry | None = None,
        archetype_library: ArchetypeLibrary | None = None,
        auto_approve: bool = False,
    ) -> TeamGenerationResult:
        """
        Generate a team configuration using an LLM.

        Args:
            task_description: What the team should accomplish
            llm_provider: LLM to use for generation
            tool_registry: Available tools (for agent assignment)
            archetype_library: Existing archetypes (fed as examples)
            auto_approve: Skip confirmation when no blocking gaps

        Returns:
            TeamGenerationResult with config, capability_gaps, new_archetypes

        Raises:
            ValueError: If generated config has blocking gaps and auto_approve=True
        """
```

### Rollback Invocation (FR-005)

```python
async def _trigger_rollback(
    self,
    agent_id: str,
    rollback_action: str,
    original_action_context: dict[str, Any],
) -> dict[str, Any]:
    """
    Invoke rollback tool for a previously executed action.
    Logs error if rollback itself fails (does not raise).
    """
```

---

## Library Contracts (no changes)

`ArchetypeLibrary` and `TeamTemplateLibrary` APIs unchanged. Default loading will discover new archetype JSON files from `templates/archetypes/`.
