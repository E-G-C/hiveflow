# Tasks: Output Pipeline Architecture

**Input**: Design documents from `/specs/003-output-pipeline/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/sdk-api.md

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Phase 1: Setup

**Purpose**: Project initialization, dependency updates, and shared infrastructure

- [x] T001 <!-- bd:hiveflow-xi6.1 --> Update `pyproject.toml` publishers extra to use `pypandoc>=1.14`, `pypandoc_binary>=1.14`, `jinja2>=3.1.4` — remove `mistune`, `md2pdf`, `htmldocx`
- [x] T002 <!-- bd:hiveflow-xi6.2 --> Run `uv sync` and verify publishers extra installs correctly
- [x] T003 <!-- bd:hiveflow-xi6.3 --> [P] Create default layout template at `hiveflow/templates/layouts/default.yaml` per data-model.md LayoutTemplate schema

---

## Phase 2: Foundational — ResultPayload + Layout System

**Purpose**: Core data model and layout infrastructure that ALL publishers depend on

**⚠️ CRITICAL**: No publisher work can begin until this phase is complete

- [x] T004 <!-- bd:hiveflow-xi6.4 --> Create `ResultPayload`, `PayloadSection`, and `ActionRecord` dataclasses in `hiveflow/core/result_payload.py` per data-model.md fields; include `to_dict()` serialization and `from_workflow_result()` class method
- [x] T005 <!-- bd:hiveflow-xi6.5 --> Write unit tests for `ResultPayload` construction, `to_dict()`, and `from_workflow_result()` in `tests/test_result_payload.py`
- [x] T006 <!-- bd:hiveflow-xi6.6 --> Create `LayoutTemplate`, `LayoutSection` dataclasses and `load_layout()`, `list_layouts()` functions in `hiveflow/core/layout.py`; load YAML from `hiveflow/templates/layouts/`
- [x] T007 <!-- bd:hiveflow-xi6.7 --> Write unit tests for layout loading, resolution by name, missing layout error, and section ordering in `tests/test_layout.py`
- [x] T008 <!-- bd:hiveflow-xi6.8 --> Add `publish_payload()` method to `PublisherPlugin` base class in `hiveflow/plugins/publishers/__init__.py` with default fallback to existing `publish(content, output_path, metadata)`
- [x] T009 <!-- bd:hiveflow-xi6.9 --> Update `PublisherRegistry.publish_all()` in `hiveflow/plugins/publishers/__init__.py` to accept `ResultPayload`, resolve layout, de-duplicate formats, and dispatch to `publish_payload()` with per-publisher error isolation and structured logging
- [x] T010 <!-- bd:hiveflow-xi6.10 --> Add `PublishConfig` Pydantic model to `hiveflow/core/schema.py` with fields: `formats`, `layout`, `style`, `output_dir`, `filename`; wire into `TeamConfiguration`
- [x] T011 <!-- bd:hiveflow-xi6.11 --> Write unit tests for `PublishConfig` validation and `TeamConfiguration` integration in `tests/test_core.py`
- [x] T012 <!-- bd:hiveflow-xi6.12 --> Export `ResultPayload`, `PayloadSection`, `ActionRecord` from `hiveflow/__init__.py`

**Checkpoint**: ResultPayload, layout system, and updated registry are ready — publisher implementation can begin

---

## Phase 3: User Story 3 — Structured ResultPayload (Priority: P1) 🎯 MVP

**Goal**: Workflow engine assembles a `ResultPayload` from completed workflow state

**Independent Test**: Run a workflow, access the `ResultPayload`, verify it has correct fields (title, content, sections, references, actions, cost_summary)

- [x] T013 <!-- bd:hiveflow-xi6.13 --> [US3] Integrate `ResultPayload.from_workflow_result()` into `WorkflowEngine.execute()` in `hiveflow/core/workflow.py` — assemble payload after successful completion and attach to `WorkflowResult`
- [x] T014 <!-- bd:hiveflow-xi6.14 --> [US3] Write integration test in `tests/test_result_payload.py` verifying payload assembly from a mock multi-agent workflow result with citations, cost data, and step results

**Checkpoint**: WorkflowEngine returns a ResultPayload on completion — all downstream publishers can consume it

---

## Phase 4: User Story 1 — Publish as Markdown (Priority: P1)

**Goal**: Export workflow results as a well-structured `.md` file with layout, frontmatter, TOC, references, and cost appendix

**Independent Test**: Publish a ResultPayload as Markdown, verify the file contains expected sections in order with correct metadata

- [x] T015 <!-- bd:hiveflow-xi6.15 --> [US1] Refactor existing `MarkdownPublisher` in `hiveflow/plugins/publishers/__init__.py` to implement `publish_payload()` using layout template for section ordering, YAML frontmatter, auto-generated TOC, references section, and cost appendix
- [x] T016 <!-- bd:hiveflow-xi6.16 --> [US1] Write unit tests for Markdown publisher in `tests/test_publishers.py` covering: basic publish, TOC generation, references rendering, empty content validation error, directory auto-creation, metadata frontmatter

**Checkpoint**: `hiveflow run --publish markdown` produces a structured .md file

---

## Phase 5: User Story 1b — JSON Publisher (Priority: P1)

**Goal**: Serialize the full ResultPayload to a `.json` file preserving all fields

**Independent Test**: Publish a ResultPayload as JSON, verify the file is valid JSON matching `to_dict()` output

- [x] T017 <!-- bd:hiveflow-xi6.17 --> [P] [US1] Create `JSONPublisher` in `hiveflow/plugins/publishers/json_publisher.py` implementing `publish_payload()` — serialize payload via `to_dict()` with `json.dumps(indent=2)`
- [x] T018 <!-- bd:hiveflow-xi6.18 --> [P] [US1] Write unit tests for JSON publisher in `tests/test_publishers.py` covering: valid JSON output, round-trip fidelity, empty fields handling
- [x] T019 <!-- bd:hiveflow-xi6.19 --> [US1] Register JSON publisher via entry point in `pyproject.toml` under `[project.entry-points."hiveflow.publishers"]`

**Checkpoint**: Markdown + JSON publishers both work — zero-dependency output pipeline is complete

---

## Phase 6: User Story 4 — Custom Layout Templates (Priority: P2)

**Goal**: Users can define custom layout templates in YAML and reference them by name in team config

**Independent Test**: Create a custom layout that reorders sections and omits TOC, publish, verify output matches custom structure

- [x] T020 <!-- bd:hiveflow-xi6.20 --> [US4] Implement custom layout directory scanning in `hiveflow/core/layout.py` — support user-specified layout directories alongside built-in layouts
- [x] T021 <!-- bd:hiveflow-xi6.21 --> [US4] Implement layout `apply()` method that takes a `ResultPayload` and returns ordered rendered sections, omitting optional sections with no content and warning on required sections with no content
- [x] T022 <!-- bd:hiveflow-xi6.22 --> [US4] Write unit tests for custom layout loading, section ordering, optional/required behavior, and invalid layout name error in `tests/test_layout.py`
- [x] T023 <!-- bd:hiveflow-xi6.23 --> [US4] Update Markdown publisher to use `layout.apply()` for section ordering instead of hardcoded structure

**Checkpoint**: Custom layouts work with Markdown publisher — `publish.layout: "executive-brief"` in team config produces custom document structure

---

## Phase 7: User Story 2 — Multi-Format Publish (Priority: P1)

**Goal**: Publish to multiple formats in a single call, isolating per-publisher failures

**Independent Test**: Configure 3 formats, verify all 3 files created; mock one publisher to fail, verify other 2 still succeed

- [x] T024 <!-- bd:hiveflow-xi6.24 --> [US2] Write integration tests in `tests/test_publishers.py` for multi-format publish: 3 formats produce 3 files, duplicate de-duplication, missing publisher warning, one failure doesn't block others
- [x] T025 <!-- bd:hiveflow-xi6.25 --> [US2] Wire `PublishConfig` from team config into `WorkflowEngine` — auto-publish after execution when `publish.formats` is non-empty in `hiveflow/core/workflow.py`
- [x] T026 <!-- bd:hiveflow-xi6.26 --> [US2] Add `--publish` CLI flag to `hiveflow/cli/main.py` accepting comma-separated format list (e.g., `--publish markdown,pdf`) and `--output-dir` flag

**Checkpoint**: `hiveflow run --template X --query Y --publish markdown,json` produces both files automatically

---

## Phase 8: User Story 5 — PDF Publisher (Priority: P2)

**Goal**: Publish styled PDF output via pypandoc (pandoc + LaTeX)

**Independent Test**: Publish a ResultPayload as PDF, verify the output is a valid PDF file

- [x] T027 <!-- bd:hiveflow-xi6.27 --> [P] [US5] Create `PDFPublisher` in `hiveflow/plugins/publishers/pdf_publisher.py` implementing `publish_payload()` — assemble Markdown from layout, convert via `pypandoc.convert_text()` wrapped in `asyncio.to_thread()`, support optional LaTeX template/CSS via config
- [x] T028 <!-- bd:hiveflow-xi6.28 --> [P] [US5] Write unit tests for PDF publisher in `tests/test_publishers.py` — mock `pypandoc.convert_text` to verify correct arguments, test graceful error when pandoc/LaTeX unavailable
- [x] T029 <!-- bd:hiveflow-xi6.29 --> [US5] Register PDF publisher via entry point in `pyproject.toml`

**Checkpoint**: PDF output works for users with LaTeX installed

---

## Phase 9: User Story 6 — DOCX Publisher (Priority: P2)

**Goal**: Publish DOCX output with proper headings, lists, and formatting via pypandoc

**Independent Test**: Publish a ResultPayload as DOCX, verify the output is a valid .docx file

- [x] T030 <!-- bd:hiveflow-xi6.30 --> [P] [US6] Create `DOCXPublisher` in `hiveflow/plugins/publishers/docx_publisher.py` implementing `publish_payload()` — assemble Markdown from layout, convert via `pypandoc.convert_text()` wrapped in `asyncio.to_thread()`
- [x] T031 <!-- bd:hiveflow-xi6.31 --> [P] [US6] Write unit tests for DOCX publisher in `tests/test_publishers.py` — mock pypandoc, verify correct format argument (`docx`), test graceful error when pandoc unavailable
- [x] T032 <!-- bd:hiveflow-xi6.32 --> [US6] Register DOCX publisher via entry point in `pyproject.toml`

**Checkpoint**: DOCX output works — enterprise users can export to Word

---

## Phase 10: User Story 5b — HTML Publisher (Priority: P2)

**Goal**: Publish styled HTML output via pypandoc + Jinja2 template

**Independent Test**: Publish a ResultPayload as HTML, verify the output is valid HTML with styled layout

- [x] T033 <!-- bd:hiveflow-xi6.33 --> [P] [US5] Create default HTML Jinja2 template at `hiveflow/templates/html/default.html` with responsive styling, title, body, and metadata sections
- [x] T034 <!-- bd:hiveflow-xi6.34 --> [P] [US5] Create `HTMLPublisher` in `hiveflow/plugins/publishers/html_publisher.py` implementing `publish_payload()` — convert MD→HTML via pypandoc, render into Jinja2 template with metadata
- [x] T035 <!-- bd:hiveflow-xi6.35 --> [P] [US5] Write unit tests for HTML publisher in `tests/test_publishers.py` — mock pypandoc, verify Jinja2 template rendering, test custom template path
- [x] T036 <!-- bd:hiveflow-xi6.36 --> [US5] Register HTML publisher via entry point in `pyproject.toml`

**Checkpoint**: All 5 built-in publishers (Markdown, JSON, HTML, PDF, DOCX) are complete

---

## Phase 11: User Story 8 — Completion Callbacks (Priority: P3)

**Goal**: Register sync/async callbacks invoked with ResultPayload on workflow completion

**Independent Test**: Register a callback, run a workflow, verify callback received the payload

- [x] T037 <!-- bd:hiveflow-xi6.37 --> [US8] Add `on_complete()` callback registration and `_invoke_callbacks()` dispatch to `WorkflowEngine` in `hiveflow/core/workflow.py` — support both sync and async callables with per-callback error isolation
- [x] T038 <!-- bd:hiveflow-xi6.38 --> [US8] Write unit tests for callback registration, invocation order, async callbacks, error isolation, and sync-in-async wrapping in `tests/test_publish_callbacks.py`

**Checkpoint**: Callbacks fire reliably after workflow completion

---

## Phase 12: User Story 7 — Third-Party Publisher Extensibility (Priority: P3)

**Goal**: Third-party publishers can be installed via entry points without modifying core code

**Independent Test**: Create a minimal mock publisher plugin, register via entry point, verify it appears in registry and can be invoked

- [x] T039 <!-- bd:hiveflow-xi6.39 --> [US7] Write integration test in `tests/test_publishers.py` verifying entry-point-based plugin discovery: register a mock publisher via entry point, confirm it appears in `registry.list()`, invoke it via `publish_all()`, verify error in custom publisher doesn't affect built-in publishers
- [x] T040 <!-- bd:hiveflow-xi6.40 --> [US7] Verify and document the third-party publisher authoring contract in `docs/plugins.md` — protocol requirements, entry point registration, testing guidance

**Checkpoint**: Plugin extensibility validated end-to-end

---

## Phase 13: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, observability, cleanup, and validation

- [x] T041 <!-- bd:hiveflow-xi6.41 --> [P] Add structured log events (`output.publish.start`, `output.publish.complete`, `output.publish.error`) with publisher ID, format, output path, and duration to all publishers in `hiveflow/plugins/publishers/__init__.py`
- [x] T042 <!-- bd:hiveflow-xi6.42 --> [P] Update `README.md` with output pipeline feature description, available formats, and publisher config example
- [x] T043 <!-- bd:hiveflow-xi6.43 --> [P] Update `CHANGELOG.md` with all output pipeline additions
- [x] T044 <!-- bd:hiveflow-xi6.44 --> [P] Update `docs/plugins.md` with publisher plugin type in the plugin types table
- [x] T045 <!-- bd:hiveflow-xi6.45 --> Run all tests (`uv run pytest`) and fix any failures
- [x] T046 <!-- bd:hiveflow-xi6.46 --> Run linter (`uv run ruff check hiveflow/ tests/`) and fix any violations
- [x] T047 <!-- bd:hiveflow-xi6.47 --> Validate quickstart.md scenarios manually — confirm Markdown + JSON publish works end-to-end

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately
- **Phase 2 (Foundational)**: Depends on Phase 1 — BLOCKS all publishers
- **Phase 3 (US3: ResultPayload)**: Depends on Phase 2 — BLOCKS all publishers
- **Phase 4 (US1: Markdown)**: Depends on Phase 3
- **Phase 5 (US1b: JSON)**: Depends on Phase 3 — can run in parallel with Phase 4
- **Phase 6 (US4: Layouts)**: Depends on Phase 4 (refines Markdown publisher)
- **Phase 7 (US2: Multi-format)**: Depends on Phases 4 + 5 (needs ≥2 publishers)
- **Phase 8 (US5: PDF)**: Depends on Phase 3 — can run in parallel with Phases 4–7
- **Phase 9 (US6: DOCX)**: Depends on Phase 3 — can run in parallel with Phases 4–8
- **Phase 10 (US5b: HTML)**: Depends on Phase 3 — can run in parallel with Phases 4–9
- **Phase 11 (US8: Callbacks)**: Depends on Phase 3 — can run in parallel with publishers
- **Phase 12 (US7: Extensibility)**: Depends on Phase 2 (registry exists)
- **Phase 13 (Polish)**: Depends on all desired phases being complete

### User Story Dependencies

```
Phase 2 (Foundational) ──┬──▶ Phase 3 (US3: ResultPayload) ──┬──▶ Phase 4 (US1: Markdown) ──▶ Phase 6 (US4: Layouts)
                         │                                    │                                      │
                         │                                    ├──▶ Phase 5 (US1b: JSON) ─────────────┼──▶ Phase 7 (US2: Multi-format)
                         │                                    │                                      │
                         │                                    ├──▶ Phase 8 (US5: PDF) ───────────────┘
                         │                                    ├──▶ Phase 9 (US6: DOCX)
                         │                                    ├──▶ Phase 10 (US5b: HTML)
                         │                                    └──▶ Phase 11 (US8: Callbacks)
                         │
                         └──▶ Phase 12 (US7: Extensibility)
```

### Parallel Opportunities

- **Phase 4 + Phase 5**: Markdown and JSON publishers can be built simultaneously (different files)
- **Phases 8 + 9 + 10**: PDF, DOCX, HTML publishers can all be built simultaneously (different files)
- **Phase 11**: Callbacks can be built in parallel with any publisher phase
- **Phase 12**: Extensibility testing can run in parallel with Phase 11
- **Within phases**: All tasks marked [P] can run in parallel

---

## Implementation Strategy

### MVP First (Phases 1–5)

1. Complete Phase 1: Setup (deps updated)
2. Complete Phase 2: Foundational (ResultPayload + layout + registry)
3. Complete Phase 3: US3 (engine assembles payload)
4. Complete Phase 4: US1 (Markdown publisher)
5. Complete Phase 5: US1b (JSON publisher)
6. **STOP and VALIDATE**: Markdown + JSON output works end-to-end
7. Deploy/demo — zero-dependency output pipeline is usable

### Full Delivery

8. Complete Phase 6: US4 (custom layouts)
9. Complete Phase 7: US2 (multi-format + CLI)
10. Complete Phases 8–10: US5/US6 (PDF, DOCX, HTML — in parallel)
11. Complete Phase 11: US8 (callbacks)
12. Complete Phase 12: US7 (extensibility validation)
13. Complete Phase 13: Polish (docs, logging, cleanup)

---

## Notes

- [P] tasks = different files, no dependencies on incomplete tasks
- [Story] label maps task to specific user story for traceability
- Markdown + JSON publishers are zero-dependency; HTML/PDF/DOCX need pypandoc
- pypandoc calls wrapped in `asyncio.to_thread()` for async compatibility
- PDF output requires LaTeX engine (document in quickstart, not a code dependency)
- Existing `PublisherPlugin.publish(content, output_path, metadata)` signature preserved
- Commit after each task or logical group
