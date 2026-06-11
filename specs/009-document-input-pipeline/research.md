# Research: Document Input Pipeline Enhancements

**Feature**: 009-document-input-pipeline  
**Date**: 2026-02-27  
**Purpose**: Resolve technical unknowns for implementation.

---

## R-001: instructions_file Integration Point in HiveFlow.run()

**Decision**: Add `instructions_file: str | None = None` parameter to `HiveFlow.run()`. Read via `DocumentPipeline.load_instructions_file()` which already handles validation and UTF-8 reading. Set `task` from file content before calling the engine.

**Rationale**: `load_instructions_file()` exists at line ~281 of `documents.py` and handles path validation + UTF-8 reading. Reusing it avoids duplicating file-reading logic. Mutual exclusivity check is a simple guard at the top of `run()`.

**Alternatives considered**:
- **Add a separate `run_from_file()` method**: Rejected — adds API surface without benefit; a parameter is simpler.
- **Read file in the engine layer**: Rejected — engine already accepts instructions_file; this just surfaces it to the facade.

---

## R-002: load_from_bytes() Default Implementation Strategy

**Decision**: Add `load_from_bytes(data: bytes, filename: str) -> Document` as a non-abstract method on `DocumentLoaderPlugin` with a default that writes to a temp file and delegates to `load()`.

**Rationale**: The temp-file approach provides zero-effort backward compatibility for all 10+ existing loaders. On Windows, the temp file must be closed before `load()` reads it (Windows file locking). Using `tempfile.NamedTemporaryFile(delete=False)` + manual `Path.unlink()` in a try/finally handles this correctly.

**Alternatives considered**:
- **Abstract method requiring all loaders to implement**: Rejected — breaks all existing loaders (§2.5).
- **io.BytesIO wrapper**: Rejected — many loaders use file-path-based libraries (pymupdf, python-docx) that need actual files.

---

## R-003: Summary Mode LLM Integration

**Decision**: In `scope_for_agent()`, when `document_mode="summary"`, generate summaries using the existing `SYSTEM_SUMMARIZER` prompt template and `FAST_LLM` tier. Cache summaries in state under a `_document_summaries` key (dict mapping document name → summary string).

**Rationale**: The `SYSTEM_SUMMARIZER` template already exists with `$text` and `$max_tokens` variables. Using it provides consistent summary formatting. Caching in state (keyed by document name) ensures reuse across agents and is visible/traceable per §2.3. The summary replaces the document's chunks list with a single chunk containing the summary text.

**Implementation detail**: `scope_for_agent()` is synchronous, but LLM calls are async. The summary generation needs to happen earlier — either in `DocumentPipeline.load()` or as a pre-processing step in the workflow engine. Best approach: add an `async generate_summary()` method to `DocumentPipeline` that's called from the workflow engine before agent execution when any agent uses summary mode.

**Alternatives considered**:
- **Generate summaries lazily in scope_for_agent()**: Rejected — scope_for_agent() is sync; can't call async LLM.
- **Pre-generate for all documents**: Rejected — wasteful if no agent uses summary mode.

---

## R-004: Document Template Variable Injection Point

**Decision**: Inject document variables (`document_count`, `document_names`, `document_summary`) into the variables dict when rendering prompts in `Agent._build_messages()`. Extract from state's `documents` and `document_summary` keys.

**Rationale**: The prompt template system (from feature 008) supports flat `$variable` substitution. Injecting these 3 variables from state before prompt rendering requires no changes to the template system itself — just passing extra variables.

**Alternatives considered**:
- **Auto-register in PromptLibrary**: Rejected — library is stateless; variables come from runtime state.
- **Middleware/hook in prompt render**: Rejected — over-engineered for 3 variables.
