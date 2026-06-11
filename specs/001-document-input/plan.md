# Implementation Plan: Document Input Pipeline

**Branch**: `001-document-input` | **Date**: 2026-02-18 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/001-document-input/spec.md`

## Summary

Add a first-class document input pipeline to HiveFlow so users can
feed local files (or inline content) into workflows via the SDK, CLI,
and API. Documents are loaded, parsed by format-specific plugins,
chunked, and injected into workflow state before the first agent
executes. Advanced features include per-agent document scoping (which
documents and how much each agent sees), an on-demand document
retrieval tool for `tool_user` agents, extended format loaders (PDF,
DOCX, PPTX, XLSX, Markdown, HTML, JSON, XML), and multipart document
upload endpoints for server mode.

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: pydantic >=2.9.2, openai, anthropic, httpx,
aiofiles, structlog, rich (all existing); pymupdf (PDF), python-docx
(DOCX), python-pptx (PPTX), openpyxl (XLSX), beautifulsoup4 (HTML)
(all already in optional dependency groups)
**Storage**: N/A — documents are held in-memory in workflow state;
file-based source only
**Testing**: pytest + pytest-asyncio (existing); `uv run pytest`
**Target Platform**: Cross-platform Python framework (Linux, macOS,
Windows)
**Project Type**: Single — `hiveflow/` package at repository root
**Performance Goals**: Load and chunk 20 documents totaling 50 MB
within a single workflow invocation
**Constraints**: 50 MB configurable total document size limit;
async-first public APIs; file paths restricted to working directory
or configurable allowed-paths list
**Scale/Scope**: Up to 20 documents per invocation; 11 supported
file formats; 3 interface layers (SDK, CLI, API)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1
design.*

| # | Principle | Status | Evidence |
|---|-----------|--------|----------|
| 2.1 | Configuration Over Code | PASS | Per-agent document scoping configured in YAML team templates. Users pass file paths, not orchestration code. |
| 2.2 | Progressive Disclosure | PASS | Simplest case: `hiveflow run --template X --doc file.txt`. Advanced scoping, modes, retrieval tool are opt-in. |
| 2.3 | Explicit State, No Magic | PASS | Documents stored in `state["documents"]` and `state["document_summary"]`. No hidden channels. |
| 2.4 | Plugin Architecture | PASS | Document loaders are `DocumentLoaderPlugin` plugins discovered via `hiveflow.document_loaders` entry points. Retrieval tool is a `ToolPlugin`. |
| 2.5 | Backward Compatibility | PASS | All new parameters (`documents`, `instructions_file`, `document_mode`) have defaults. Existing workflows are unaffected. |
| 2.6 | Observability | PASS | Structured logging for document loading, chunking, compression, and scoping decisions. Trace spans for loading pipeline. |
| 2.7 | Fail Loudly | PASS | Clear errors for: missing files, unsupported formats, path traversal, size limit exceeded, mutually exclusive options, unresolved scoping references. |

**Result**: All gates pass. No violations requiring justification.

## Project Structure

### Documentation (this feature)

```text
specs/001-document-input/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── sdk-api.md
│   ├── cli-api.md
│   └── rest-api.md
├── checklists/
│   └── requirements.md  # Spec quality checklist
└── tasks.md             # Phase 2 output (/speckit.tasks)
```

### Source Code (repository root)

```text
hiveflow/
├── __init__.py                         # Add: documents param to public API
├── core/
│   ├── schema.py                       # Extend: AgentDefinition with document fields
│   ├── workflow.py                     # Extend: document loading pre-execution hook
│   ├── agent.py                        # Extend: _build_messages() for document context
│   ├── state.py                        # (no changes — state is dict-based)
│   └── documents.py                    # NEW: DocumentPipeline orchestrator
├── plugins/
│   └── documents/
│       ├── __init__.py                 # Extend: Document/DocumentChunk with spec fields
│       ├── plain_text.py               # EXTRACT: PlainTextLoader to own file
│       ├── markdown_loader.py          # NEW: MarkdownLoader
│       ├── pdf_loader.py              # NEW: PDFLoader (pymupdf)
│       ├── docx_loader.py            # NEW: DocxLoader (python-docx)
│       ├── pptx_loader.py            # NEW: PptxLoader (python-pptx)
│       ├── excel_loader.py           # NEW: ExcelLoader (openpyxl)
│       ├── html_loader.py            # NEW: HTMLLoader (beautifulsoup4)
│       ├── json_loader.py            # NEW: JSONLoader (built-in)
│       └── xml_loader.py             # NEW: XMLLoader (built-in)
│   └── tools/
│       └── document_retriever.py      # NEW: DocumentRetrieverTool
├── cli/
│   ├── __init__.py                    # NEW: CLI module
│   └── main.py                        # NEW: hiveflow CLI entry point
├── api/
│   └── __init__.py                    # Extend: document upload endpoints
├── validation/
│   └── path_security.py               # NEW: path traversal validation

tests/
├── test_document_pipeline.py          # NEW: pipeline integration tests
├── test_document_loaders.py           # NEW: per-loader unit tests
├── test_document_scoping.py           # NEW: per-agent scoping tests
├── test_document_retriever.py         # NEW: retriever tool tests
├── test_cli.py                        # NEW: CLI tests
├── test_path_security.py              # NEW: path validation tests
└── test_api_documents.py              # NEW: API upload endpoint tests
```

**Structure Decision**: Single-project layout. All source under
`hiveflow/`, all tests under `tests/`. New modules added within
existing package structure — no new top-level packages.

## Complexity Tracking

> No violations detected. Table intentionally empty.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| *(none)*  |            |                                     |
