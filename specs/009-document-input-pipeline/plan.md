# Implementation Plan: Document Input Pipeline Enhancements

**Branch**: `009-document-input-pipeline` | **Date**: 2026-02-27 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/009-document-input-pipeline/spec.md`

## Summary

Four additive enhancements to the existing document input pipeline: (1) surface `instructions_file` on `HiveFlow.run()`, (2) add `load_from_bytes()` to `DocumentLoaderPlugin`, (3) implement the `summary` document mode with LLM-based summarization, and (4) register document metadata variables for prompt templates. All changes are backward-compatible — no existing APIs, schemas, or behavior change.

## Technical Context

**Language/Version**: Python 3.11+ (no `from __future__ import annotations`)  
**Primary Dependencies**: pydantic ≥2.9.2, pydantic-settings, aiofiles, structlog ≥24.4.0  
**Storage**: File-based (documents loaded from filesystem or in-memory bytes)  
**Testing**: `uv run pytest tests/` (asyncio_mode=auto)  
**Target Platform**: Python library + CLI (cross-platform)  
**Project Type**: Single Python package  
**Performance Goals**: `load_from_bytes()` temp-file overhead <50ms; summary LLM calls use FAST_LLM tier  
**Constraints**: Zero breaking changes to existing public APIs; all enhancements additive  
**Scale/Scope**: 4 enhancements touching 4 modules (hiveflow.py, documents.py, plugins/documents/__init__.py, agent.py)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| §2.1 Configuration Over Code | ✅ PASS | instructions_file adds config, doesn't require code |
| §2.2 Progressive Disclosure | ✅ PASS | All new parameters are optional with sensible defaults |
| §2.3 Explicit State, No Magic | ✅ PASS | Summary cache lives in state dict; doc variables from state |
| §2.4 Plugin Architecture | ✅ PASS | load_from_bytes() extends the plugin base class non-abstractly |
| §2.5 Backward Compatibility | ✅ PASS | All 4 changes are additive; no existing signature changes |
| §2.6 Observability Built In | ✅ PASS | Summary fallback logs warnings; no new opaque paths |
| §2.7 Fail Loudly, Recover Gracefully | ✅ PASS | Empty file returns empty task (loud); LLM failure falls back with warning (graceful) |
| §3.1 Core Module Rules | ✅ PASS | No new provider SDK imports at core import time |
| §5.1 Python 3.11+ | ✅ PASS | No `from __future__ import annotations` |
| §5.2 uv Package Manager | ✅ PASS | No new dependencies |
| §6.1 Testing | ✅ PASS | Tests planned for all 4 enhancements |

No violations. No complexity tracking needed.

## Project Structure

### Documentation (this feature)

```text
specs/009-document-input-pipeline/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
└── tasks.md             # Phase 2 output (/speckit.tasks)
```

### Source Code (repository root)

```text
hiveflow/
├── core/
│   ├── hiveflow.py          # MODIFY: Add instructions_file param to run()
│   ├── documents.py         # MODIFY: Add summary mode impl to scope_for_agent()
│   └── agent.py             # MODIFY: Inject document template variables into state
├── plugins/
│   └── documents/
│       └── __init__.py      # MODIFY: Add load_from_bytes() to DocumentLoaderPlugin
└── __init__.py

tests/
├── test_instructions_file.py       # NEW: instructions_file on HiveFlow.run()
├── test_load_from_bytes.py         # NEW: load_from_bytes() on loaders
├── test_summary_document_mode.py   # NEW: LLM-based summary document mode
└── test_document_template_vars.py  # NEW: Prompt template variables for documents
```

**Structure Decision**: Existing package structure preserved. No new modules — all changes modify existing files. Four new test files.
