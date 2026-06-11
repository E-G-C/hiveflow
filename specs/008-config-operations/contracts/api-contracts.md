# API Contracts: Configuration & Operations

**Feature**: 008-config-operations  
**Date**: 2026-02-27

> This feature extends internal Python APIs (not HTTP endpoints). Contracts are
> defined as Python protocol/interface signatures that consuming code depends on.

---

## Contract 1: ResilientLLMProvider

```python
class ResilientLLMProvider:
    """Wraps an LLMProvider with resilience patterns (fallback, circuit breaking,
    rate limiting, cost tracking). Drop-in replacement for any LLMProvider."""

    async def chat(
        self,
        messages: list[dict[str, str]],
        config: dict[str, Any] | None = None,
    ) -> ChatResponse:
        """Execute LLM call with full resilience pipeline.

        Pipeline: rate_limit → circuit_breaker → fallback_chain → cost_track
        Raises LLMFallbackExhaustedError if all fallbacks fail.
        """
        ...

    @classmethod
    def from_config(
        cls,
        provider: LLMProvider,
        config: HiveFlowConfig,
        cost_tracker: CostTracker | None = None,
    ) -> "ResilientLLMProvider":
        """Factory: auto-build resilience stack from config."""
        ...
```

## Contract 2: ActionQueue

```python
class ActionQueue:
    """Queue for side-effect actions with concurrency control and timeout."""

    def __init__(
        self,
        max_concurrency: int = 5,
        timeout: float = 30.0,
        enable_rollback: bool = False,
    ) -> None: ...

    async def submit(self, action: Action) -> ActionResult:
        """Submit an action for execution. Blocks until a slot is available.
        Applies timeout. Triggers rollback on failure if enabled."""
        ...

    async def drain(self) -> list[ActionResult]:
        """Wait for all submitted actions to complete. Returns all results."""
        ...
```

## Contract 3: PromptTemplate (extended)

```python
class PromptTemplate:
    """Prompt template with dotted-path variable resolution and family support."""

    def render(
        self,
        variables: dict[str, Any],
        family: PromptFamily | None = None,
    ) -> str:
        """Render template with dotted-path variable resolution.
        Falls back to safe_substitute for unresolved paths (logs warning).
        If family is provided and a family-specific variant exists, uses that."""
        ...

    @staticmethod
    def resolve_dotted_path(obj: Any, path: str) -> Any:
        """Traverse obj by dot-separated path. Supports dicts and objects."""
        ...
```

## Contract 4: JsonLinesWriter (StreamChannel subscriber)

```python
class JsonLinesWriter:
    """Async subscriber that writes StreamEvents as JSON lines to a file."""

    def __init__(self, output_dir: str) -> None: ...

    async def on_event(self, event: StreamEvent) -> None:
        """Append event as JSON line to date-based file."""
        ...

    async def close(self) -> None:
        """Flush and close the current file."""
        ...
```

## Contract 5: OrchestratorAgent

```python
class OrchestratorAgent:
    """Agent that wraps DeepResearcher for recursive exploration within workflows."""

    async def execute(self, state: dict[str, Any]) -> AgentResult:
        """Run recursive exploration using DeepResearcher.
        Emits EXECUTOR_INVOKED/EXECUTOR_COMPLETED events.
        Reports progress via StreamChannel."""
        ...

    def get_progress(self) -> float:
        """Return completion percentage (0.0 to 1.0) across all branches."""
        ...
```

## Contract 6: StreamEvent (extended)

```python
class StreamEvent(BaseModel):
    """Structured event emitted during workflow execution."""

    type: StreamEventType
    agent_id: str | None = None
    step_id: str | None = None        # NEW
    content: str | None = None         # NEW
    token: str | None = None
    data: Any | None = None
    metadata: EventMetadata | None = None  # NEW
    timestamp: datetime = Field(default_factory=datetime.utcnow)  # NEW

class EventMetadata(BaseModel):
    tokens_used: int | None = None
    latency_ms: float | None = None
    model: str | None = None
    cost_usd: float | None = None
```
