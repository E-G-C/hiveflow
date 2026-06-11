# Implementation Plan: Output Pipeline Architecture

**Branch**: `003-output-pipeline` | **Date**: 2026-02-20 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/003-output-pipeline/spec.md`

## Summary

Implement a decoupled output pipeline that assembles completed workflow results
into a structured `ResultPayload` data model and dispatches rendering to
publisher plugins. The pipeline supports five built-in formats (Markdown, JSON,
HTML, PDF, DOCX) using pypandoc as the consolidated conversion engine for HTML,
PDF, and DOCX. The Markdown and JSON publishers are zero-dependency.
Layout templates control document structure. Completion callbacks allow
programmatic result delivery.

## Technical Context

**Language/Version**: Python 3.11+ (no `from __future__ import annotations`)
**Primary Dependencies**: pypandoc >=1.14, pypandoc_binary >=1.14, jinja2 >=3.1.4 (all optional under `publishers` extra)
**Storage**: Filesystem (output files) — no database
**Testing**: pytest + pytest-asyncio (existing test infrastructure)
**Target Platform**: Cross-platform (Windows, Linux, macOS)
**Project Type**: Single project — library/framework
**Performance Goals**: Publish all 5 formats in <10 seconds for <50 pages
**Constraints**: Backward compatible with existing `PublisherPlugin.publish(content, output_path, metadata)` signature
**Scale/Scope**: Typical workflow results 1–100 pages of Markdown content

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| 2.1 Configuration Over Code | **PASS** | Publishing configured via `publish` block in team config YAML |
| 2.2 Progressive Disclosure | **PASS** | Publishing is entirely optional; workflows work without it; simple `formats: ["markdown"]` config for basic use |
| 2.3 Explicit State, No Magic | **PASS** | `ResultPayload` is an explicit, inspectable data model assembled from workflow state |
| 2.4 Plugin Architecture | **PASS** | Publishers are plugins discovered via `hiveflow.publishers` entry points; new formats added without core changes |
| 2.5 Backward Compatibility | **PASS** | Existing `PublisherPlugin.publish(content, output_path, metadata)` preserved; new `publish(payload, config)` added alongside |
| 2.6 Observability Built In | **PASS** | Structured log events for publish start/complete/error; latency and format in every event |
| 2.7 Fail Loudly, Recover Gracefully | **PASS** | Per-publisher error isolation; explicit errors for missing deps, invalid layouts, empty content |
| 3.1 Core Modules | **PASS** | `ResultPayload` and assembly logic live in `core/`; publishers are plugins |
| 3.2 Plugin System | **PASS** | Publishers discovered via entry points; missing deps logged + skipped |
| 3.3 Boundary Layers | **PASS** | API exposes payload as JSON (GET /api/workflows/{id}); CLI gets `--publish` flag; logic in core |
| 4.1 Workflow State | **PASS** | No new reserved state keys — `ResultPayload` is assembled from existing state after workflow completes |
| 5.1 Language & Runtime | **PASS** | Python 3.11+, no `__future__` annotations |
| 5.2 Package Management | **PASS** | All deps in `pyproject.toml` under `publishers` optional extra |
| 5.4 Async First | **PASS** | `publish()` is async; callbacks support async callables |
| 6.1 Testing | **PASS** | Unit tests for payload assembly, each publisher, registry, layout resolution, callbacks |
| 6.3 Documentation | **PASS** | README, CHANGELOG, quickstart, API contract docs |
| 8 Scope Boundaries | **PASS** | "Not a UI framework" — output pipeline exports files, does not render UI |

**Gate result: ALL PASS — no violations.**

## Project Structure

### Documentation (this feature)

```text
specs/003-output-pipeline/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   └── sdk-api.md       # Publisher SDK contract
└── tasks.md             # Phase 2 output (from /speckit.tasks)
```

### Source Code (repository root)

```text
hiveflow/
├── core/
│   ├── result_payload.py       # NEW: ResultPayload data model + assembly
│   └── workflow.py             # MODIFIED: assemble ResultPayload after execution
├── plugins/
│   └── publishers/
│       ├── __init__.py         # MODIFIED: extend PublisherPlugin protocol, update registry
│       ├── json_publisher.py   # NEW: JSON publisher (zero-dep)
│       ├── html_publisher.py   # NEW: HTML publisher (pypandoc + jinja2)
│       ├── pdf_publisher.py    # NEW: PDF publisher (pypandoc + LaTeX)
│       └── docx_publisher.py   # NEW: DOCX publisher (pypandoc)
├── core/
│   └── layout.py               # NEW: LayoutTemplate model + default/custom resolution
└── templates/
    └── layouts/
        └── default.yaml        # NEW: Default layout template definition

tests/
├── test_result_payload.py      # NEW: ResultPayload model + assembly tests
├── test_publishers.py          # MODIFIED: add tests for new publishers
├── test_layout.py              # NEW: Layout template tests
└── test_publish_callbacks.py   # NEW: Callback registration + invocation tests
```

**Structure Decision**: Extends existing `hiveflow/plugins/publishers/` with new
publisher modules. New `core/result_payload.py` for the payload data model
(follows the existing pattern of one-class-per-core-module: `cost.py`,
`citations.py`, `streaming.py`). Layout system in `core/layout.py`.
HTML publisher templates go under `hiveflow/templates/layouts/`.
