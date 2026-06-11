# Data Model: Task Preprocessing and Large-Input Context Management

**Branch**: `014-task-preprocessing` | **Date**: 2026-03-05

## Entities

### TaskPreprocessor

The orchestrating component that runs the full preprocessing pipeline.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `llm_provider` | `LLMProvider` | (required) | LLM provider for boundary detection fallback and summarization |
| `model` | `str` | (from config) | Model identifier for LLM calls |
| `config` | `PreprocessingConfig` | `PreprocessingConfig()` | Tuning parameters |
| `context_registry` | `ModelContextRegistry` | `ModelContextRegistry()` | Model-to-context-window lookup |
| `logger` | `structlog.BoundLogger` | auto | Structured logger |

**Methods**:
- `async preprocess(state: dict[str, Any], agent_count: int) -> dict[str, Any]` — Main entry point. Returns enriched state or unmodified state if below threshold.
- `_compute_threshold(model: str, agent_count: int) -> int` — Computes word-count threshold from model context window.
- `_detect_boundary(text: str) -> tuple[str, str]` — Splits text into (instructions, data) using heuristics or LLM fallback.
- `_chunk_data(data: str, target_words: int, overlap_words: int) -> list[TaskDataChunk]` — Chunks data section with paragraph-boundary preference.
- `async _summarize_and_manifest(chunks: list[TaskDataChunk]) -> tuple[str, TaskDataManifest]` — Generates summary and manifest in a single LLM call.
- `_mechanical_summary(chunks: list[TaskDataChunk]) -> str` — Fallback summary from chunk metadata.

### PreprocessingConfig

Pydantic model for preprocessing parameters. Mirrors global `HiveFlowConfig` fields and team-level overrides.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `disabled` | `bool` | `False` | Disable preprocessing entirely |
| `threshold_override` | `int` | `0` | Fixed word-count threshold (0 = auto-compute) |
| `context_ratio` | `float` | `0.15` | Fraction of context window used for threshold |
| `pipeline_factor` | `float` | `0.3` | Per-agent context multiplier |
| `chunk_context_ratio` | `float` | `0.10` | Fraction of context window per chunk target |
| `chunk_overlap_ratio` | `float` | `0.10` | Overlap as fraction of chunk size |
| `tokens_per_word` | `float` | `1.35` | Token-to-word conversion ratio |

### ModelContextRegistry

Lookup table mapping model name prefixes to context window sizes.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `_registry` | `dict[str, int]` | BUILT_IN_MODELS | Prefix → context tokens mapping |
| `default_context` | `int` | `16000` | Fallback for unknown models |

**Methods**:
- `resolve(model: str) -> int` — Returns context window in tokens. Tries exact match, then prefix match (longest prefix wins), then default.
- `register(prefix: str, context_tokens: int)` — Adds/updates a prefix entry at runtime.

**Built-in registry** (initial entries):
```
gpt-4o           → 128,000
gpt-4o-mini      → 128,000
gpt-4-turbo      → 128,000
gpt-4            → 8,192
gpt-3.5          → 16,385
o3-mini          → 128,000
o3               → 200,000
o1               → 200,000
claude-3-opus    → 200,000
claude-3-sonnet  → 200,000
claude-3-haiku   → 200,000
claude-3.5       → 200,000
claude-           → 200,000
gemini-1.5-pro   → 1,000,000
gemini-1.5-flash → 1,000,000
gemini-2         → 1,000,000
mistral-large    → 128,000
mistral-medium   → 32,000
mistral-small    → 32,000
command-r-plus   → 128,000
command-r        → 128,000
```

### TaskDataChunk

A segment of the data section.

| Field | Type | Description |
|-------|------|-------------|
| `chunk_id` | `str` | Unique identifier (e.g., `"chunk_001"`) |
| `content` | `str` | The chunk text |
| `words` | `int` | Word count |
| `topic_hint` | `str` | One-sentence topic description |

### TaskDataManifest

Metadata describing all chunks.

| Field | Type | Description |
|-------|------|-------------|
| `total_words` | `int` | Total words across all chunks |
| `chunk_count` | `int` | Number of chunks |
| `model_context_tokens` | `int` | Context window used for sizing |
| `effective_threshold` | `int` | Threshold value that triggered preprocessing |
| `boundary_method` | `str` | Heuristic that detected the boundary |
| `chunks` | `list[ChunkMeta]` | Per-chunk metadata |

### ChunkMeta

Per-chunk entry in the manifest.

| Field | Type | Description |
|-------|------|-------------|
| `chunk_id` | `str` | Matches `TaskDataChunk.chunk_id` |
| `words` | `int` | Word count |
| `topic_hint` | `str` | One-sentence topic description |

## State Keys Added

When preprocessing activates, these keys are added to workflow state:

| Key | Type | Description |
|-----|------|-------------|
| `task_instructions` | `str` | Extracted instructions (also written to `state["task"]`) |
| `task_data` | `list[dict]` | Serialized `TaskDataChunk` list (`chunk_id`, `content`, `words`, `topic_hint`) |
| `task_data_summary` | `str` | Compact summary (≤300 words) or empty string |
| `task_data_manifest` | `dict` | Serialized `TaskDataManifest` |

When preprocessing does NOT activate (below threshold or disabled):
- None of these keys are added
- `state["task"]` remains unchanged
- Zero additional LLM calls

## Relationships

```
TaskPreprocessor
├── uses PreprocessingConfig (composition)
├── uses ModelContextRegistry (composition)
├── produces list[TaskDataChunk]
├── produces TaskDataManifest
│   └── contains list[ChunkMeta]
└── enriches state dict with PreprocessedState keys

WorkflowEngine
├── owns TaskPreprocessor (optional, nullable)
└── calls preprocess() in execute()

Agent._summarize_state()
├── reads task_instructions (if present)
├── reads task_data_summary (if present)
├── reads task_data (for fan-out workers via current_item)
└── falls back to state["task"] when preprocessing keys absent

CollaborationRuntime._build_sub_state()
├── propagates task_instructions
├── propagates task_data_summary
├── propagates task_data_manifest
└── filters task_data to specific chunk_id when delegating
```

## State Transitions

```
[Initial State]
    │
    ▼
state["task"] = full original text
    │
    ▼ TaskPreprocessor.preprocess()
    │
    ├─ Below threshold? → return state unchanged (no new keys)
    │
    ├─ Above threshold, data < 1 chunk target?
    │   → state["task"] = instructions only
    │   → state["task_instructions"] = instructions
    │   → state["task_data"] = [single entry with all data]
    │   → state["task_data_summary"] = ""
    │   → state["task_data_manifest"] = {chunk_count: 1, ...}
    │
    └─ Above threshold, data ≥ 1 chunk target?
        → state["task"] = instructions only
        → state["task_instructions"] = instructions
        → state["task_data"] = [chunk_1, chunk_2, ..., chunk_n]
        → state["task_data_summary"] = LLM summary (≤300 words)
        → state["task_data_manifest"] = {chunk_count: n, chunks: [...]}
```
