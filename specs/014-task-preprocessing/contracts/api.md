# API Contracts: Task Preprocessing

**Branch**: `014-task-preprocessing` | **Date**: 2026-03-05

This feature is an internal library component (no HTTP/REST API). Contracts are defined as Python API surfaces.

## Contract 1: TaskPreprocessor public API

```python
class TaskPreprocessor:
    """Pre-execution pipeline for separating, chunking, and summarizing large task inputs."""

    def __init__(
        self,
        llm_provider: LLMProvider,
        model: str = "",
        config: PreprocessingConfig | None = None,
        context_registry: ModelContextRegistry | None = None,
    ) -> None: ...

    async def preprocess(
        self,
        state: dict[str, Any],
        agent_count: int = 1,
    ) -> dict[str, Any]:
        """
        Analyze state["task"] and, if above threshold, separate instructions
        from data, chunk data, generate summary and manifest.

        Returns:
            Enriched state dict with preprocessing keys, or unmodified state
            if below threshold or disabled.

        State keys added on activation:
            - task_instructions: str
            - task_data: list[dict] (serialized TaskDataChunk list)
            - task_data_summary: str
            - task_data_manifest: dict (serialized TaskDataManifest)

        State keys modified on activation:
            - task: set to instructions only (compact)

        Guarantees:
            - state["task"] is never empty or removed
            - No keys added when below threshold (FR-011)
            - Max 2 LLM calls overhead (FR-004 fallback + FR-006 summary)
        """
        ...
```

## Contract 2: ModelContextRegistry public API

```python
class ModelContextRegistry:
    """Maps model name prefixes to context window sizes in tokens."""

    DEFAULT_CONTEXT: int = 16_000

    def __init__(self, overrides: dict[str, int] | None = None) -> None:
        """Initialize with built-in models + optional overrides."""
        ...

    def resolve(self, model: str) -> int:
        """
        Resolve a model name to its context window in tokens.

        Resolution order:
        1. Exact match
        2. Longest prefix match
        3. DEFAULT_CONTEXT fallback (16,000)
        """
        ...

    def register(self, prefix: str, context_tokens: int) -> None:
        """Add or update a model prefix entry at runtime."""
        ...
```

## Contract 3: PreprocessingConfig schema

```python
class PreprocessingConfig(BaseModel):
    """Configuration for task preprocessing parameters."""

    disabled: bool = False
    threshold_override: int = 0  # 0 = auto-compute
    context_ratio: float = 0.15
    pipeline_factor: float = 0.3
    chunk_context_ratio: float = 0.10
    chunk_overlap_ratio: float = 0.10
    tokens_per_word: float = 1.35
```

## Contract 4: Data structure schemas

```python
@dataclass
class TaskDataChunk:
    """A segment of the data section."""
    chunk_id: str       # e.g., "chunk_001"
    content: str        # The chunk text
    words: int          # Word count
    topic_hint: str     # One-sentence topic description

    def to_dict(self) -> dict[str, Any]: ...

@dataclass
class ChunkMeta:
    """Per-chunk entry in the manifest."""
    chunk_id: str
    words: int
    topic_hint: str

@dataclass
class TaskDataManifest:
    """Metadata describing all chunks."""
    total_words: int
    chunk_count: int
    model_context_tokens: int
    effective_threshold: int
    boundary_method: str
    chunks: list[ChunkMeta]

    def to_dict(self) -> dict[str, Any]: ...
```

## Contract 5: WorkflowEngine constructor extension

```python
class WorkflowEngine:
    def __init__(
        self,
        workflow_steps: list[WorkflowStep],
        *,
        # ... existing parameters ...
        task_preprocessor: TaskPreprocessor | None = None,  # NEW
    ) -> None: ...
```

## Contract 6: HiveFlowConfig new fields

```python
class HiveFlowConfig(BaseSettings):
    # ... existing fields ...

    # Task preprocessing
    TASK_PREPROCESS_DISABLED: bool = False
    TASK_PREPROCESS_THRESHOLD_OVERRIDE: int = 0
    TASK_CONTEXT_RATIO: float = 0.15
    TASK_PIPELINE_FACTOR: float = 0.3
    TASK_CHUNK_CONTEXT_RATIO: float = 0.10
    TASK_CHUNK_OVERLAP_RATIO: float = 0.10
    TASK_TOKENS_PER_WORD: float = 1.35
```

## Contract 7: Team config preprocessing section

```yaml
# In team configuration YAML/JSON
preprocessing:
  disabled: false           # default: false
  threshold_override: 0     # default: 0 (auto-compute)
  context_ratio: 0.15       # default: 0.15
  pipeline_factor: 0.3      # default: 0.3
  chunk_context_ratio: 0.10 # default: 0.10
  chunk_overlap_ratio: 0.10 # default: 0.10
  tokens_per_word: 1.35     # default: 1.35
```

## Contract 8: DelegateTaskTool schema extension

```python
# Extended tool input schema for delegation with chunk routing
{
    "name": "delegate_task",
    "parameters": {
        "task": {"type": "string", "description": "Task description for the delegate"},
        "agent_id": {"type": "string", "description": "Agent to delegate to"},
        "chunk_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Optional chunk IDs to include in delegate context",
            "default": []
        }
    }
}
```

## Contract 9: LLMProvider optional context_window property

```python
class LLMProvider(Protocol):
    # ... existing methods ...

    @property
    def context_window(self) -> int | None:
        """
        Optional: return the model's context window in tokens.
        Return None if unknown (registry fallback will be used).
        """
        return None
```

## Contract 10: Fan-out source extension

```yaml
# Existing fan-out step:
- agent: worker
  step_type: parallel_fan_out
  items: ["item1", "item2"]

# New: fan-out over preprocessed chunks:
- agent: worker
  step_type: parallel_fan_out
  source: "task_data"  # NEW — iterates state["task_data"]
```
