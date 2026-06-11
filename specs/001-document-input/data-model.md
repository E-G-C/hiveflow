# Data Model: Document Input Pipeline

**Branch**: `001-document-input` | **Date**: 2026-02-18

## Entities

### Document (extended)

Extends the existing `Document` class in
`hiveflow/plugins/documents/__init__.py`.

| Field | Type | Source | Description |
|-------|------|--------|-------------|
| `content` | `str` | Existing | Raw text content |
| `source` | `str` | Existing | Original file path or identifier |
| `metadata` | `dict[str, Any]` | Existing | Arbitrary key-value metadata |
| `name` | `str` | **New** | Canonical identifier — full relative path for files, user-provided name for inline content |
| `format` | `str` | **New** | File extension without dot (e.g., `txt`, `pdf`, `docx`) |
| `size_bytes` | `int` | **New** | Raw file size in bytes |
| `total_tokens_estimate` | `int` | **New** | Approximate token count (word_count / 0.75) |

**Identity rule**: `name` is the unique identifier within a workflow
invocation. For file-based documents, this is the relative path from
the working directory. For inline content, this is the user-provided
`name` key. Duplicate names within a single invocation are rejected.

**State serialization** (`to_state_dict()`):

```python
{
    "name": "reports/summary.txt",
    "format": "txt",
    "size_bytes": 24500,
    "chunks": [
        {"index": 0, "content": "First chunk..."},
        {"index": 1, "content": "Second chunk..."}
    ],
    "chunk_count": 2,
    "total_tokens_estimate": 6100
}
```

### DocumentChunk (extended)

Extends the existing `DocumentChunk` class.

| Field | Type | Source | Description |
|-------|------|--------|-------------|
| `content` | `str` | Existing | Chunk text content |
| `source` | `str` | Existing | Parent document source path |
| `chunk_index` | `int` | Existing | Zero-based index within parent |
| `total_chunks` | `int` | Existing | Total chunks in parent document |
| `metadata` | `dict[str, Any]` | Existing | Arbitrary metadata |
| `token_estimate` | `int` | **New** | Approximate token count for this chunk |

**Serialization** (`to_state_dict()`):

```python
{"index": 0, "content": "First chunk..."}
```

### DocumentMode (new enum)

Per-agent configuration controlling document delivery.

| Value | Behavior |
|-------|----------|
| `full` | All chunks injected into agent context |
| `relevant_chunks` | Semantically similar chunks only (requires embedding provider) |
| `summary` | Pre-generated summary via FAST_LLM |
| `metadata_only` | Name, format, size, chunk count — no content |
| `none` | No document content (default when `documents` omitted) |

**Fallback**: If `relevant_chunks` is specified but no embedding
provider is configured, falls back to `full` with a warning logged.

### AgentDefinition (extended)

Extends the existing Pydantic model in `hiveflow/core/schema.py`.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `documents` | `list[str] \| None` | `None` | Document names this agent receives. `None` = all, `[]` = none |
| `document_mode` | `str` | `"none"` | How document content is delivered (see DocumentMode) |
| `max_document_tokens` | `int \| None` | `None` | Per-agent document token budget. `None` = use global default |

**Validation rules**:
- `document_mode` must be one of the DocumentMode values
- `max_document_tokens` must be positive if set
- Documents listed in `documents` must match loaded document names
  (validated at workflow start, not at schema parse time)

### DocumentPipeline (new)

Orchestrator class in `hiveflow/core/documents.py`.

| Method | Signature | Description |
|--------|-----------|-------------|
| `load` | `async (inputs: list[str \| dict], working_dir: Path, allowed_paths: list[Path] \| None, max_total_bytes: int) -> list[dict]` | Full pipeline: validate → detect → load → chunk → estimate tokens → return state dicts |
| `load_instructions_file` | `async (path: str, working_dir: Path) -> str` | Read instructions file as UTF-8 string |
| `scope_for_agent` | `(documents: list[dict], agent_def: AgentDefinition, state: dict) -> list[dict]` | Filter/transform documents per agent's scoping config |

### DocumentRetrieverTool (new)

Tool plugin in `hiveflow/plugins/tools/document_retriever.py`.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `document_name` | `str` | No | Filter by document name |
| `query` | `str` | No | Semantic search within chunks |
| `chunk_indices` | `list[int]` | No | Specific chunk indices |
| `max_tokens` | `int` | No | Limit returned content |

**Returns**: `list[dict]` — matching chunks in the standard chunk
shape.

## Relationships

```text
Document 1───* DocumentChunk
    │
    └── stored in state["documents"] as list[dict]

AgentDefinition ──references──> Document (by name)
    │
    └── document_mode controls delivery

DocumentRetrieverTool ──reads──> state["documents"]
    │
    └── returns matching DocumentChunks

DocumentPipeline ──uses──> DocumentLoaderRegistry
    │                          │
    │                          └── dispatches to DocumentLoaderPlugin
    │
    └── uses chunk_text() for chunking
```

## State Keys Contract

| Key | Type | Set by | When |
|-----|------|--------|------|
| `task` | `str` | Engine (init) | Always (existing) |
| `documents` | `list[dict]` | DocumentPipeline | Pre-execution, if documents provided |
| `document_summary` | `str` | DocumentPipeline | Pre-execution, if documents provided |
| `input_data` | `Any` | Engine (init) | Legacy compatibility (existing) |
| `current_agent` | `str` | Engine (step) | Each agent step (existing) |
| `history` | `list[dict]` | Engine (step) | Each agent step (existing) |
