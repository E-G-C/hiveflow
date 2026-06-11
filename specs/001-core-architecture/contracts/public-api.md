# Public API Contract: Core Architecture

**Feature**: 001-core-architecture
**Date**: 2026-02-22

## HiveFlow Entry Point

### Constructor

```python
class HiveFlow:
    def __init__(
        self,
        *,
        config: HiveFlowConfig | None = None,
        team_library: TeamTemplateLibrary | None = None,
        archetype_library: ArchetypeLibrary | None = None,
        tool_registry: ToolRegistry | None = None,
        llm_registry: LLMProviderRegistry | None = None,
        checkpoint_storage: CheckpointStorage | None = None,
    ) -> None:
        """
        Create a HiveFlow instance.

        All parameters are optional — sensible defaults are used when not provided.
        This is the primary entry point for the framework.
        """
```

### run() — Execute a workflow

```python
async def run(
    self,
    team: str | TeamConfiguration | dict[str, Any],
    task: str,
    *,
    documents: list[str | dict[str, str]] | None = None,
    initial_state: dict[str, Any] | None = None,
    checkpoint: bool = False,
) -> WorkflowSession:
    """
    Execute a multi-agent workflow.

    Args:
        team: Team template name (str), TeamConfiguration object,
              or raw dict (validated against schema).
        task: The user's task or query.
        documents: Optional document paths or metadata.
        initial_state: Optional initial state overrides.
        checkpoint: Enable checkpoint persistence at gates.

    Returns:
        WorkflowSession with session_id, status, result, and event stream.

    Raises:
        ValidationError: If team configuration is invalid.
        WorkflowError: If execution fails.
    """
```

### run_sync() — Synchronous wrapper

```python
def run_sync(
    self,
    team: str | TeamConfiguration | dict[str, Any],
    task: str,
    **kwargs,
) -> WorkflowSession:
    """
    Synchronous wrapper around run().
    Blocks until workflow completes or pauses.
    """
```

### generate_team() — LLM-based team generation

```python
async def generate_team(
    self,
    task: str,
    *,
    model: str | None = None,
    auto_approve: bool = False,
) -> TeamGenerationResult:
    """
    Generate a team configuration using an LLM.

    Args:
        task: Description of the problem to solve.
        model: LLM to use for generation (defaults to $STRATEGIC_LLM).
        auto_approve: If True and no blocking gaps, execute immediately.

    Returns:
        TeamGenerationResult with config, capability_gaps, and new_archetypes.
    """
```

### resume() — Resume a paused workflow

```python
async def resume(
    self,
    session_id: str,
    responses: dict[str, Any],
) -> WorkflowSession:
    """
    Resume a paused workflow session.

    Args:
        session_id: Session to resume.
        responses: Approval responses keyed by request_id.

    Returns:
        Updated WorkflowSession.

    Raises:
        KeyError: If session_id not found (in-memory or checkpoint storage).
        WorkflowError: If session is not in PAUSED state.
    """
```

### Discovery Methods

```python
def team_library(self) -> TeamTemplateLibrary:
    """Access the team template library."""

def archetype_library(self) -> ArchetypeLibrary:
    """Access the archetype library."""

def tool_registry(self) -> ToolRegistry:
    """Access the tool registry."""

def model_registry(self) -> LLMProviderRegistry:
    """Access the LLM provider/model registry."""
```

---

## WorkflowSession

### Properties

```python
class WorkflowSession:
    @property
    def session_id(self) -> str: ...

    @property
    def status(self) -> WorkflowStatus: ...

    @property
    def result(self) -> WorkflowResult | None: ...

    @property
    def error(self) -> str | None: ...

    @property
    def pending_requests(self) -> list[ApprovalRequest]: ...

    @property
    def created_at(self) -> float: ...
```

### Methods

```python
async def resume(self, responses: dict[str, Any]) -> None:
    """Resume from paused state with approval responses."""

async def cancel(self) -> None:
    """Cancel the session. Status transitions to FAILED."""

def subscribe(self) -> StreamConsumer:
    """Subscribe to real-time workflow events."""

def to_dict(self) -> dict[str, Any]:
    """JSON-serializable session representation."""
```

---

## TeamGenerationResult

```python
class TeamGenerationResult(BaseModel):
    config: TeamConfiguration
    capability_gaps: list[CapabilityGap] = []
    new_archetypes: list[dict[str, Any]] = []

    @property
    def has_blocking_gaps(self) -> bool:
        return any(g.severity == "blocking" for g in self.capability_gaps)
```

---

## ArchetypeLibrary

```python
class ArchetypeLibrary:
    def register(self, name: str, archetype: dict[str, Any]) -> None: ...
    def get(self, name: str) -> dict[str, Any] | None: ...
    def list_archetypes(self) -> list[str]: ...

    @classmethod
    def from_directory(cls, directory: str | Path) -> ArchetypeLibrary: ...

    @classmethod
    def default(cls) -> ArchetypeLibrary: ...
```

---

## CheckpointStorage Protocol

```python
class CheckpointStorage(Protocol):
    async def save(self, checkpoint: WorkflowCheckpoint) -> None: ...
    async def load(self, session_id: str) -> WorkflowCheckpoint | None: ...
    async def delete(self, session_id: str) -> None: ...
    async def list_sessions(self) -> list[str]: ...
```

---

## Event Types (additions)

| Event Type | Payload | Emitted When |
|-----------|---------|--------------|
| CHECKPOINT_SAVED | `{session_id, step_index, path}` | Checkpoint persisted to storage |
| ACTION_PROPOSED | `{agent_id, actions: list[dict]}` | action_executor proposes actions (require_approval) |
| ACTION_EXECUTED | `{agent_id, action_id, status, result}` | action_executor completes an action |
| GATE_REQUESTED | `{gate_id, gate_description, step_index}` | Gated step pauses workflow |

---

## Error Types

| Error | Raised When | HTTP Status (API) |
|-------|------------|-------------------|
| ValidationError (pydantic) | Invalid TeamConfiguration | 422 |
| WorkflowError | Execution failure (conditional loop exceeded, agent error) | 500 |
| CheckpointError | Checkpoint load/save failure, corrupted data | 500 |
| KeyError | Session not found | 404 |

---

## Backward Compatibility Notes

- All new `AgentDefinition` fields are optional with sensible defaults — existing configs work unchanged
- New enum values (`action_executor`, `gated`) are additive — existing configs never encounter them
- `WorkflowEngine.max_conditional_loops` parameter retained for backward compat; per-step `max_iterations` takes precedence when set
- `TeamGenerator.ARCHETYPES` dict preserved but deprecated in favor of `ArchetypeLibrary`
- All existing `__init__.py` exports preserved; new symbols added
