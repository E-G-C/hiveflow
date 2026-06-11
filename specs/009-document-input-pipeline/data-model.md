# Data Model: Document Input Pipeline Enhancements

**Feature**: 009-document-input-pipeline  
**Date**: 2026-02-27

---

## Entities

### HiveFlow.run() (extended signature)

| Parameter | Type | Default | Status |
|-----------|------|---------|--------|
| `team` | `str \| dict \| TeamConfiguration` | required | Exists |
| `task` | `str` | required | Exists |
| `documents` | `list[str \| dict] \| None` | `None` | Exists |
| `initial_state` | `dict[str, Any] \| None` | `None` | Exists |
| `checkpoint` | `bool` | `False` | Exists |
| **`instructions_file`** | `str \| None` | `None` | **New** |

**Validation rule**: `task` (non-empty) and `instructions_file` are mutually exclusive.

### DocumentLoaderPlugin (extended)

| Method | Type | Status |
|--------|------|--------|
| `plugin_id` | `property -> str` | Exists (abstract) |
| `description` | `property -> str` | Exists (abstract) |
| `supported_extensions` | `property -> list[str]` | Exists (abstract) |
| `load(file_path)` | `async -> Document` | Exists (abstract) |
| **`load_from_bytes(data, filename)`** | `async -> Document` | **New** (non-abstract, default impl) |

### Document Summary Cache (state key)

| State Key | Type | Description |
|-----------|------|-------------|
| `_document_summaries` | `dict[str, str]` | Maps document name → LLM-generated summary. Populated on first summary request, reused for subsequent agents. |

### Document Template Variables

| Variable | Type | Source | Default (no docs) |
|----------|------|--------|-------------------|
| `$document_count` | `int` | `len(state["documents"])` | `0` |
| `$document_names` | `str` | comma-join of doc names | `""` |
| `$document_summary` | `str` | `state["document_summary"]` | `""` |

---

## Relationships

```
HiveFlow.run(instructions_file) → DocumentPipeline.load_instructions_file() → task string
DocumentLoaderPlugin.load_from_bytes() → temp file → load() → Document
DocumentPipeline.generate_summary() → FAST_LLM → state["_document_summaries"]
scope_for_agent(mode="summary") → reads state["_document_summaries"] → single summary chunk
Agent._build_messages() → injects document_count/names/summary into template variables
```
