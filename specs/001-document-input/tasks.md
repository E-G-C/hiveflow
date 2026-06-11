# Tasks: Document Input Pipeline

**Input**: Design documents from `/specs/001-document-input/`
**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, contracts/

**Tests**: Included — test files are listed in plan.md project structure and are part of the implementation.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **Single project**: `hiveflow/` package at repository root, `tests/` at repository root
- Paths are relative to the repository root

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization — register entry points and create package scaffolding

- [ ] T001 <!-- bd:hiveflow-9ms --> Add `[project.entry-points."hiveflow.document_loaders"]` section with `plain_text` entry and `[project.scripts]` entry `hiveflow = "hiveflow.cli.main:main"` in pyproject.toml
- [ ] T002 <!-- bd:hiveflow-v91 --> [P] Create `hiveflow/validation/__init__.py` package init file
- [ ] T003 <!-- bd:hiveflow-2ik --> [P] Create `hiveflow/cli/__init__.py` package init file

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core model extensions and utilities that MUST be complete before ANY user story can be implemented

**CRITICAL**: No user story work can begin until this phase is complete

- [ ] T004 <!-- bd:hiveflow-dg8 --> Extend `Document` class with `name`, `format`, `size_bytes`, `total_tokens_estimate` fields and add `to_state_dict()` method; extend `DocumentChunk` with `token_estimate` field and add `to_state_dict()` method in hiveflow/plugins/documents/__init__.py
- [ ] T005 <!-- bd:hiveflow-00g --> [P] Implement `validate_document_path(path, working_dir, allowed_paths)` that resolves paths, rejects traversal sequences and out-of-scope symlinks, and returns validated absolute path in hiveflow/validation/path_security.py
- [ ] T006 <!-- bd:hiveflow-wyh --> [P] Extract `PlainTextLoader` class to hiveflow/plugins/documents/plain_text.py and update imports in hiveflow/plugins/documents/__init__.py to re-export from new location
- [ ] T007 <!-- bd:hiveflow-1us --> [P] Add `DocumentMode` string enum (`full`, `relevant_chunks`, `summary`, `metadata_only`, `none`) and extend `AgentDefinition` with optional `documents: list[str] | None`, `document_mode: str = "none"`, `max_document_tokens: int | None` fields in hiveflow/core/schema.py

**Checkpoint**: Foundation ready — user story implementation can now begin

---

## Phase 3: User Story 1 — Load Documents by File Path (Priority: P1) MVP

**Goal**: Users pass file paths (or inline content dicts) when invoking a workflow via SDK, and the framework loads, parses, chunks, and injects documents into state before the first agent executes.

**Independent Test**: A user can invoke a single-agent workflow with a text file, and the agent receives the file content in its context without additional setup.

### Implementation for User Story 1

- [ ] T008 <!-- bd:hiveflow-v8y.1 --> [US1] Create `DocumentPipeline` class with `__init__` (registry, working_dir, allowed_paths, max_total_bytes, chunk_size, chunk_overlap) and async `load()` method that validates paths, detects formats, dispatches to loaders, chunks content, estimates tokens, enforces size limit, and returns `(list[dict], str)` tuple of document state dicts and summary string in hiveflow/core/documents.py
- [ ] T009 <!-- bd:hiveflow-v8y.2 --> [US1] Extend `WorkflowEngine.execute()` signature with `documents: list[str | dict[str, str]] | None = None` and `instructions_file: str | None = None` keyword-only params; wire `DocumentPipeline.load()` as pre-execution hook to populate `state["documents"]` and `state["document_summary"]` before first agent runs in hiveflow/core/workflow.py
- [ ] T010 <!-- bd:hiveflow-v8y.3 --> [US1] Update `Agent._build_messages()` to include document content from `state["documents"]` in agent context messages in hiveflow/core/agent.py
- [ ] T011 <!-- bd:hiveflow-v8y.4 --> [P] [US1] Write integration tests covering: single file loading, multiple files, inline content dicts, mixed inputs, missing file error, unsupported format error, path traversal rejection, size limit enforcement, duplicate name rejection, empty file handling in tests/test_document_pipeline.py
- [ ] T012 <!-- bd:hiveflow-v8y.5 --> [P] [US1] Write unit tests covering: valid paths within working_dir, traversal sequences rejected, symlinks outside allowed dirs rejected, allowed-paths list configuration in tests/test_path_security.py

**Checkpoint**: At this point, document loading via SDK works end-to-end with plain text files

---

## Phase 4: User Story 2 — Load Instructions from File (Priority: P1)

**Goal**: Users author complex prompts in a file and reference it by path; the framework reads the file and uses its content as the instructions string.

**Independent Test**: A user can invoke a workflow with `instructions_file="./prompt.md"` (SDK) or `--instructions-file ./prompt.md` (CLI) and the agent receives the file's content as the task instructions.

### Implementation for User Story 2

- [ ] T013 <!-- bd:hiveflow-v8y.6 --> [US2] Implement `load_instructions_file(path)` in `DocumentPipeline` that reads the file as UTF-8 and returns content string, with path security validation, in hiveflow/core/documents.py
- [ ] T014 <!-- bd:hiveflow-v8y.7 --> [US2] Add mutual-exclusivity validation: raise `ValueError` when both `initial_state["task"]` and `instructions_file` are provided in `WorkflowEngine.execute()` in hiveflow/core/workflow.py
- [ ] T015 <!-- bd:hiveflow-v8y.8 --> [US2] Create CLI entry point with `hiveflow run` command using argparse: `--template` (required), `--instructions`, `--instructions-file`, `--doc` (repeatable), `--config`; support `--instructions -` and `--doc -` for stdin with mutual-exclusivity check; exit codes 0/1/2/3; JSON output to stdout, errors to stderr in hiveflow/cli/main.py
- [ ] T016 <!-- bd:hiveflow-v8y.9 --> [US2] Write CLI tests covering: basic invocation, --instructions-file loading, --doc flag, multiple --doc flags, stdin for instructions, stdin for doc, dual-stdin rejection, instructions mutual-exclusivity error in tests/test_cli.py

**Checkpoint**: At this point, both SDK and CLI document workflows work with plain text and instructions-from-file

---

## Phase 5: User Story 3 — Per-Agent Document Scoping (Priority: P2)

**Goal**: Workflow designers control which documents each agent sees and how (full, relevant_chunks, summary, metadata_only, none) via declarative team template configuration.

**Independent Test**: A three-agent workflow can be configured where Agent A sees document X in full, Agent B sees only metadata, and Agent C sees no documents — and each agent's context confirms the expected scoping.

### Implementation for User Story 3

- [ ] T017 <!-- bd:hiveflow-v8y.10 --> [US3] Implement `scope_for_agent()` in `DocumentPipeline` supporting `full`, `metadata_only`, `none` modes, plus `max_document_tokens` truncation in hiveflow/core/documents.py
- [ ] T018 <!-- bd:hiveflow-v8y.11 --> [US3] Implement `relevant_chunks` mode (embedding-based with fallback to `full` when no provider configured, with warning log) and `summary` mode (via FAST_LLM) in `scope_for_agent()` in hiveflow/core/documents.py
- [ ] T019 <!-- bd:hiveflow-v8y.12 --> [US3] Modify `Agent._build_messages()` to call `DocumentPipeline.scope_for_agent()` using the agent's `AgentDefinition` scoping config instead of injecting all documents in hiveflow/core/agent.py
- [ ] T020 <!-- bd:hiveflow-v8y.13 --> [US3] Add validation at workflow start: check that all document names referenced in agent `documents` fields match loaded document names; raise `ValueError` for unresolved references in hiveflow/core/workflow.py
- [ ] T021 <!-- bd:hiveflow-v8y.14 --> [US3] Write scoping tests covering: full mode, metadata_only mode, none mode, relevant_chunks with fallback, summary mode, max_document_tokens truncation, unresolved reference error, documents=None (all docs), documents=[] (no docs) in tests/test_document_scoping.py

**Checkpoint**: At this point, multi-agent workflows with document scoping work end-to-end

---

## Phase 6: User Story 5 — Extended Document Format Support (Priority: P2)

**Goal**: Users process documents beyond plain text — 8 additional format loaders as DocumentLoaderPlugin implementations.

**Independent Test**: A user can pass a `.pdf` file (or any supported format) as a document to a workflow and the agent receives the parsed content.

**Note**: This phase can be worked on in parallel with Phase 5 (US3) — all loaders touch independent files.

### Implementation for User Story 5

- [ ] T022 <!-- bd:hiveflow-dsh --> [P] [US5] Create `MarkdownLoader` that splits on heading boundaries (`^#{1,6}\s`) and preserves document structure in hiveflow/plugins/documents/markdown_loader.py
- [ ] T023 <!-- bd:hiveflow-ick --> [P] [US5] Create `PDFLoader` using pymupdf with page-number metadata, graceful import error if pymupdf not installed in hiveflow/plugins/documents/pdf_loader.py
- [ ] T024 <!-- bd:hiveflow-dm0 --> [P] [US5] Create `DocxLoader` using python-docx that extracts paragraphs and headings, graceful import error if python-docx not installed in hiveflow/plugins/documents/docx_loader.py
- [ ] T025 <!-- bd:hiveflow-956 --> [P] [US5] Create `PptxLoader` using python-pptx that extracts slide-by-slide including speaker notes, graceful import error if python-pptx not installed in hiveflow/plugins/documents/pptx_loader.py
- [ ] T026 <!-- bd:hiveflow-0my --> [P] [US5] Create `ExcelLoader` using openpyxl that extracts sheet-by-sheet as text representation, graceful import error if openpyxl not installed in hiveflow/plugins/documents/excel_loader.py
- [ ] T027 <!-- bd:hiveflow-ysb --> [P] [US5] Create `HTMLLoader` using beautifulsoup4 that extracts main content and strips navigation/ads, graceful import error if bs4 not installed in hiveflow/plugins/documents/html_loader.py
- [ ] T028 <!-- bd:hiveflow-7rd --> [P] [US5] Create `JSONLoader` using stdlib json that pretty-prints content in hiveflow/plugins/documents/json_loader.py
- [ ] T029 <!-- bd:hiveflow-a0e --> [P] [US5] Create `XMLLoader` using stdlib xml.etree that extracts text content in hiveflow/plugins/documents/xml_loader.py
- [ ] T030 <!-- bd:hiveflow-jlz --> [US5] Register all new loaders in `[project.entry-points."hiveflow.document_loaders"]` in pyproject.toml and write per-loader unit tests in tests/test_document_loaders.py

**Checkpoint**: All 11 file formats are loadable through the same user-facing interface

---

## Phase 7: User Story 4 — On-Demand Document Retrieval Tool (Priority: P3)

**Goal**: Tool-using agents can call a document retrieval tool mid-execution to fetch specific content from loaded documents by name, semantic query, or chunk index.

**Independent Test**: A `tool_user` agent can call the document retrieval tool to fetch specific chunks from a loaded document and use them in its response.

### Implementation for User Story 4

- [ ] T031 <!-- bd:hiveflow-e4j --> [US4] Create `DocumentRetrieverTool` as ToolPlugin subclass with params `document_name`, `query`, `chunk_indices`, `max_tokens`; reads from `state["documents"]`; semantic search via embedding provider with keyword fallback in hiveflow/plugins/tools/document_retriever.py
- [ ] T032 <!-- bd:hiveflow-b1a --> [US4] Register `document_retriever` in `[project.entry-points."hiveflow.tools"]` in pyproject.toml
- [ ] T033 <!-- bd:hiveflow-h82 --> [US4] Write retriever tests covering: fetch by name, fetch by chunk indices, max_tokens truncation, no documents loaded, semantic query, keyword fallback in tests/test_document_retriever.py

**Checkpoint**: Tool-using agents can dynamically query documents during execution

---

## Phase 8: User Story 6 — Document Upload via API (Priority: P3)

**Goal**: Integrators using server mode upload documents via multipart form data alongside workflow execution requests.

**Independent Test**: An HTTP client can POST a multipart request with file attachments to the workflow endpoint and receive results that reference the uploaded documents.

### Implementation for User Story 6

- [ ] T034 <!-- bd:hiveflow-v8y.15 --> [US6] Extend `POST /workflows/start` to accept multipart form data with `template`, `instructions`, `instructions_file`, `documents` UploadFile fields alongside existing JSON body in hiveflow/api/__init__.py
- [ ] T035 <!-- bd:hiveflow-v8y.16 --> [US6] Add `POST /workflows/{workflow_id}/documents` endpoint for uploading documents to a running workflow in hiveflow/api/__init__.py
- [ ] T036 <!-- bd:hiveflow-v8y.17 --> [US6] Add `GET /workflows/{workflow_id}/documents` (list all) and `GET /workflows/{workflow_id}/documents/{name}` (get specific) endpoints in hiveflow/api/__init__.py
- [ ] T037 <!-- bd:hiveflow-v8y.18 --> [US6] Write API document endpoint tests covering: multipart upload, inline JSON documents, document listing, specific document retrieval, size limit rejection, unsupported format rejection in tests/test_api_documents.py

**Checkpoint**: All three interfaces (SDK, CLI, API) support document input

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories

- [ ] T038 <!-- bd:hiveflow-v8y.19 --> Add structured logging (structlog) for document loading, chunking, compression, scoping decisions, and error conditions across DocumentPipeline in hiveflow/core/documents.py
- [ ] T039 <!-- bd:hiveflow-v8y.20 --> Validate quickstart.md scenarios end-to-end by running SDK and CLI examples
- [ ] T040 <!-- bd:hiveflow-v8y.21 --> Run full test suite (`uv run pytest`) and `ruff check .`; fix any failures or lint errors

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Foundational — MVP target
- **US2 (Phase 4)**: Depends on US1 (extends same pipeline and workflow integration)
- **US3 (Phase 5)**: Depends on US1 (scoping acts on loaded documents)
- **US5 (Phase 6)**: Depends on Foundational only (loaders are independent files) — CAN run in parallel with US1/US2/US3
- **US4 (Phase 7)**: Depends on US1 (reads documents from state)
- **US6 (Phase 8)**: Depends on US1 (uses DocumentPipeline)
- **Polish (Phase 9)**: Depends on all desired user stories being complete

### User Story Dependencies

```text
Setup (Phase 1)
  └── Foundational (Phase 2)
        ├── US1: Load Documents (Phase 3) ──── MVP
        │     ├── US2: Instructions from File (Phase 4)
        │     ├── US3: Per-Agent Scoping (Phase 5)
        │     ├── US4: Retrieval Tool (Phase 7)
        │     └── US6: API Upload (Phase 8)
        └── US5: Extended Formats (Phase 6) ── parallel with US1+
              └── (test with pipeline after US1 complete)
```

### Within Each User Story

- Models/entities before services
- Services before integration points
- Core implementation before tests
- Story complete before moving to next priority

### Parallel Opportunities

- **Phase 1**: T002
 and T003 can run in parallel
- **Phase 2**: T005, T006, T007 can run in parallel (after T004 if they depend on Document class; T005 is fully independent)
- **Phase 3**: T011 and T012 (test files) can run in parallel
- **Phase 5 + Phase 6**: US3 and US5 can be worked on in parallel (different files entirely)
- **Phase 6**: T022–T029 (all 8 format loaders) can ALL run in parallel — each is an independent file
- **Phase 7**: US4 can start as soon as US1 is done, even if US3/US5 are in progress
- **Phase 8**: US6 can start as soon as US1 is done, even if other stories are in progress

---

## Parallel Example: User Story 5 (Extended Formats)

```bash
# All 8 loaders can be implemented simultaneously:
Task T022: "Create MarkdownLoader in hiveflow/plugins/documents/markdown_loader.py"
Task T023: "Create PDFLoader in hiveflow/plugins/documents/pdf_loader.py"
Task T024: "Create DocxLoader in hiveflow/plugins/documents/docx_loader.py"
Task T025: "Create PptxLoader in hiveflow/plugins/documents/pptx_loader.py"
Task T026: "Create ExcelLoader in hiveflow/plugins/documents/excel_loader.py"
Task T027: "Create HTMLLoader in hiveflow/plugins/documents/html_loader.py"
Task T028: "Create JSONLoader in hiveflow/plugins/documents/json_loader.py"
Task T029: "Create XMLLoader in hiveflow/plugins/documents/xml_loader.py"
```

## Parallel Example: Foundational Phase

```bash
# After T004 (Document class extension), these three are independent:
Task T005: "Path security module in hiveflow/validation/path_security.py"
Task T006: "Extract PlainTextLoader to hiveflow/plugins/documents/plain_text.py"
Task T007: "DocumentMode enum and AgentDefinition extension in hiveflow/core/schema.py"
```

---

## Implementation Strategy

### MVP First (User Stories 1 + 2 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL — blocks all stories)
3. Complete Phase 3: User Story 1 — Load Documents by File Path
4. **STOP and VALIDATE**: Test US1 independently via SDK
5. Complete Phase 4: User Story 2 — Instructions from File + CLI
6. **STOP and VALIDATE**: Test US2 independently via SDK and CLI
7. Deploy/demo if ready — users can load plain text documents and use file-based instructions

### Incremental Delivery

1. Setup + Foundational → Foundation ready
2. Add US1 → Test independently → Deploy/Demo (**MVP!**)
3. Add US2 → Test independently → Deploy/Demo (CLI available)
4. Add US5 → Test independently → Deploy/Demo (all formats supported)
5. Add US3 → Test independently → Deploy/Demo (multi-agent scoping)
6. Add US4 → Test independently → Deploy/Demo (retrieval tool)
7. Add US6 → Test independently → Deploy/Demo (API uploads)
8. Polish → Final validation → Release

### Parallel Team Strategy

With multiple developers:

1. Team completes Setup + Foundational together
2. Once Foundational is done:
   - Developer A: US1 → US2 (sequential, same files)
   - Developer B: US5 (all format loaders — independent files)
3. After US1 completes:
   - Developer A: US3 (scoping)
   - Developer C: US4 (retrieval tool)
   - Developer D: US6 (API endpoints)
4. Stories complete and integrate independently

---

## Notes

- [P] tasks = different files, no dependencies on in-progress tasks
- [Story] label maps task to specific user story for traceability
- Each user story is independently completable and testable
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- All loaders follow the existing `DocumentLoaderPlugin` protocol (R7)
- Token estimation uses word_count / 0.75 approximation (R10)
- CLI uses argparse (R2), no additional dependencies
- Path security is centralized in one module, used by SDK, CLI, and API (R4)
