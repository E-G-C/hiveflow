# Research: Document Input Pipeline

**Branch**: `001-document-input` | **Date**: 2026-02-18

## Research Summary

All technical unknowns from the plan's Technical Context have been
resolved by codebase analysis. No external research was needed — the
existing infrastructure provides clear integration points.

---

## R1: Document State Shape — Existing vs Spec

**Decision**: Extend the existing `Document` and `DocumentChunk`
classes to carry the spec-mandated metadata, then serialize to the
spec's state shape when injecting into workflow state.

**Rationale**: The existing `Document` class (`content: str`,
`source: str`, `metadata: dict`) is close but lacks explicit `format`,
`size_bytes`, `chunks`, `chunk_count`, and `total_tokens_estimate`
fields. Rather than replacing the class (which would break existing
code), we add properties/fields that compute or store these values.
The `to_state_dict()` method produces the spec-mandated shape for
`state["documents"]`.

**Alternatives considered**:
- Create an entirely new `LoadedDocument` class: rejected because it
  duplicates the existing class and forces two parallel abstractions.
- Store raw dicts in state without a class: rejected because it loses
  type safety and the loader pipeline benefits from structured objects.

---

## R2: CLI Framework

**Decision**: Use Python's built-in `argparse` for the CLI.

**Rationale**: The project has no CLI today. `argparse` is stdlib,
zero-dependency, and sufficient for the `hiveflow run` command with
`--template`, `--instructions`, `--instructions-file`, and `--doc`
flags. The constitution requires no additional dependencies when a
stdlib solution exists. A `[project.scripts]` entry point will be
added to `pyproject.toml` mapping `hiveflow` to `hiveflow.cli.main:main`.

**Alternatives considered**:
- `click`: rejected — adds a dependency for a simple command structure.
- `typer`: rejected — adds two dependencies (typer + click) and
  requires type-annotation-based APIs that conflict with the project's
  async-first pattern.

---

## R3: Document Loading Pipeline Placement

**Decision**: Create a new `hiveflow/core/documents.py` module
containing a `DocumentPipeline` class that orchestrates loading,
validation, chunking, and state injection.

**Rationale**: The loading pipeline is a multi-step process
(path validation → format detection → plugin dispatch → chunking →
token estimation → compression → state injection). This is too much
logic for `WorkflowEngine.execute()` to absorb inline. A dedicated
orchestrator keeps the engine thin and the pipeline independently
testable. The engine calls `DocumentPipeline.load()` as a
pre-execution hook.

**Alternatives considered**:
- Inline all logic in `WorkflowEngine.execute()`: rejected — violates
  single-responsibility; engine should orchestrate agents, not parse
  files.
- Put in `plugins/documents/__init__.py`: rejected — registry and
  loader base classes live there; pipeline orchestration is core logic,
  not a plugin concern.

---

## R4: Path Security Implementation

**Decision**: Create a `hiveflow/validation/path_security.py` module
with a `validate_document_path()` function that resolves paths and
checks containment within allowed directories.

**Rationale**: Path traversal validation is a cross-cutting security
concern used by the SDK, CLI, and API layers. A dedicated module makes
it testable in isolation. The function:
1. Resolves the path to an absolute path (via `Path.resolve()`)
2. Checks the resolved path starts with an allowed directory
3. Rejects symlinks pointing outside allowed directories
4. Returns the validated absolute path or raises `ValueError`

**Alternatives considered**:
- Inline validation in each entry point (SDK, CLI, API): rejected —
  duplicates security logic across three locations; a single miss
  creates a vulnerability.

---

## R5: Per-Agent Document Scoping Integration

**Decision**: Extend `AgentDefinition` (Pydantic model) with optional
`documents: list[str]`, `document_mode: str`, and
`max_document_tokens: int | None` fields. Modify `Agent._build_messages()`
to filter/format document content based on these fields.

**Rationale**: The schema is the single source of truth for agent
configuration. Adding these fields as optional with defaults (`None`,
`"none"`, `None`) ensures backward compatibility — existing team
configs without document fields continue to work unchanged.
`_build_messages()` already has the pattern of reading agent config
to shape context.

**Alternatives considered**:
- Separate document scoping config outside AgentDefinition: rejected —
  fragments the agent configuration model.

---

## R6: DocumentRetrieverTool Design

**Decision**: Implement as a `ToolPlugin` subclass registered under
`hiveflow.tools`. The tool reads documents from `state["documents"]`
and returns matching chunks.

**Rationale**: The existing tool system (`ToolPlugin` base class,
`ToolRegistry`, `to_llm_tool_spec()`) provides everything needed.
The retriever tool follows the same pattern as other tool plugins.
It exposes parameters `document_name`, `query`, `chunk_indices`, and
`max_tokens` per the spec. Semantic search (when `query` is provided)
delegates to the embedding provider if configured, otherwise falls
back to keyword matching.

**Alternatives considered**:
- Bespoke document access API instead of a tool: rejected — agents
  already have a tool-calling mechanism; adding a parallel access
  channel violates "Explicit State, No Magic".

---

## R7: Extended Format Loaders — Library Choices

**Decision**: Use the libraries already declared in `pyproject.toml`
optional dependencies.

| Format | Library | Optional Group | Notes |
|--------|---------|---------------|-------|
| `.md`  | Built-in (regex/split) | (none) | Split on headings `^#{1,6}\s` |
| `.pdf` | `pymupdf` | `scraping` | Already in optional deps |
| `.docx`| `python-docx` | `documents` | Already in optional deps |
| `.pptx`| `python-pptx` | `documents` | Already in optional deps |
| `.xlsx`| `openpyxl` | `documents` | Already in optional deps |
| `.html`| `beautifulsoup4` | `scraping` | Already in optional deps |
| `.json`| Built-in `json` | (none) | stdlib |
| `.xml` | Built-in `xml.etree` | (none) | stdlib |

**Rationale**: No new third-party dependencies needed. Three loaders
(Markdown, JSON, XML) use only stdlib. The remaining five use
libraries already declared in the project's optional dependency groups.

**Alternatives considered**:
- `pdfplumber` for PDF: rejected — `pymupdf` is already a dependency and
  is faster for text extraction.
- `pandas` for CSV/Excel: rejected for CSV (overkill; existing
  `PlainTextLoader` handles it), considered acceptable for Excel but
  `openpyxl` is more targeted and already declared.

---

## R8: API Document Upload

**Decision**: Extend the existing `/workflows/start` endpoint to
accept multipart form data with file fields. Add three new endpoints:
`POST /workflows/{id}/documents`, `GET /workflows/{id}/documents`,
`GET /workflows/{id}/documents/{name}`.

**Rationale**: FastAPI natively supports `UploadFile` for multipart.
The existing endpoint structure (`/workflows/start`) is the natural
place to add document attachments. Separate document endpoints support
the "add documents to a running workflow" scenario and metadata
queries.

**Alternatives considered**:
- Separate `/upload` endpoint with URL linking: rejected — adds
  indirection; multipart upload on the existing endpoint is simpler.

---

## R9: Entry Point Registration

**Decision**: Add `[project.entry-points."hiveflow.document_loaders"]`
section to `pyproject.toml` and register all built-in loaders.

**Rationale**: The existing entry point groups (`hiveflow.tools`,
`hiveflow.llm`, etc.) follow this pattern. Document loaders must
be discoverable the same way. The `DocumentLoaderRegistry` already
looks for `hiveflow.document_loaders` entry points — the entry point
group just isn't populated yet.

---

## R10: Token Estimation

**Decision**: Use word count / 0.75 as the token estimate (common
approximation for English text). Store as `total_tokens_estimate` in
the document state shape.

**Rationale**: An exact tokenizer (tiktoken, etc.) would add a
dependency and be model-specific. The word-based approximation is
sufficient for context budget decisions. The existing `chunk_text()`
already uses word count as its unit.

**Alternatives considered**:
- `tiktoken`: rejected — model-specific, adds dependency, slower.
- Character count / 4: equivalent accuracy but word-based is more
  human-interpretable in logs.
