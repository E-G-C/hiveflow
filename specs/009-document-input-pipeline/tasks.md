# Tasks: Document Input Pipeline Enhancements

**Input**: Design documents from `specs/009-document-input-pipeline/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅

**Tests**: Included — the constitution (§6.1) mandates tests for new features.

**Organization**: Tasks grouped by user story (one enhancement per story) to enable independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3, US4)
- Include exact file paths in descriptions

## Path Conventions

- **Package root**: `hiveflow/` (existing)
- **Tests**: `tests/` (existing, flat structure)

---

## Phase 1: Setup

**Purpose**: Validate existing baseline before making changes

- [x] T001 <!-- bd:hiveflow-32t.1 --> Run existing test suite with `uv run pytest tests/ --ignore=tests/test_api.py --ignore=tests/test_api_documents.py --ignore=tests/test_markitdown_loader.py --ignore=tests/test_observability.py` and confirm baseline passes

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: No new foundational infrastructure needed — all target modules already exist. The existing document pipeline IS the foundation.

**⚠️ CRITICAL**: Phase 1 must pass before proceeding.

**Checkpoint**: Baseline confirmed — user story implementation can begin.

---

## Phase 3: User Story 1 — Load Instructions from a File via Python API (Priority: P1) 🎯 MVP

**Goal**: Add `instructions_file` parameter to `HiveFlow.run()` so Python API users can load complex workflow instructions from a file without manually reading it.

**Independent Test**: Create an instructions file, call `HiveFlow.run(instructions_file=path)`, verify file contents are used as the task string.

### Implementation for User Story 1

- [x] T002 <!-- bd:hiveflow-32t.2 --> [US1] Add `instructions_file: str | None = None` parameter to `HiveFlow.run()` method signature, add mutual exclusivity validation with non-empty `task`, and read file via `DocumentPipeline.load_instructions_file()` to set the task string in hiveflow/core/hiveflow.py
- [x] T003 <!-- bd:hiveflow-32t.3 --> [P] [US1] Write tests for instructions_file: file loaded as task, mutual exclusivity error, missing file error, empty file produces empty task, various text formats (.txt, .md) in tests/test_instructions_file.py

**Checkpoint**: Python API users can pass `instructions_file` to `HiveFlow.run()`. Existing tests still pass.

---

## Phase 4: User Story 2 — Load Documents from In-Memory Bytes (Priority: P2)

**Goal**: Add `load_from_bytes(data, filename)` to `DocumentLoaderPlugin` base class with a default temp-file delegation implementation that works for all existing loaders.

**Independent Test**: Pass raw bytes and a filename to `load_from_bytes()`, verify the returned Document matches what `load()` produces for the same content on disk.

### Implementation for User Story 2

- [x] T004 <!-- bd:hiveflow-32t.4 --> [US2] Add `load_from_bytes(data: bytes, filename: str) -> Document` non-abstract method to `DocumentLoaderPlugin` base class with default temp-file delegation (NamedTemporaryFile(delete=False) + try/finally cleanup) and empty-bytes validation in hiveflow/plugins/documents/__init__.py
- [x] T005 <!-- bd:hiveflow-32t.5 --> [US2] Add `load_from_bytes()` support to `DocumentPipeline` for processing in-memory content dicts that include raw `bytes` data in hiveflow/core/documents.py
- [x] T006 <!-- bd:hiveflow-32t.6 --> [P] [US2] Write tests for load_from_bytes: default temp-file delegation produces correct Document, empty bytes raises ValueError, temp file cleaned up on success and on failure, PlainTextLoader and MarkdownLoader produce expected output in tests/test_load_from_bytes.py

**Checkpoint**: Any document loader can accept byte streams. Existing loaders work unchanged via default delegation.

---

## Phase 5: User Story 3 — Receive Condensed Document Summaries as an Agent (Priority: P2)

**Goal**: Implement the `summary` document mode with LLM-based summarization using the FAST_LLM tier, with caching in workflow state to avoid re-summarizing the same document.

**Independent Test**: Load a document, request `document_mode="summary"` for an agent, verify the agent receives a single summary chunk (not raw chunks) and that a second agent reuses the cached summary.

### Implementation for User Story 3

- [x] T007 <!-- bd:hiveflow-32t.7 --> [US3] Add `async generate_summaries(documents, state, llm_provider, max_tokens)` method to `DocumentPipeline` that generates LLM-based summaries using `SYSTEM_SUMMARIZER` prompt template, caches results in `state["_document_summaries"]`, and skips already-cached documents in hiveflow/core/documents.py
- [x] T008 <!-- bd:hiveflow-32t.8 --> [US3] Update `scope_for_agent()` in `DocumentPipeline` to use cached summaries from `state["_document_summaries"]` when `document_mode="summary"`, replacing the current metadata_only fallback. Keep fallback to metadata_only with warning when no summary is cached in hiveflow/core/documents.py
- [x] T009 <!-- bd:hiveflow-32t.9 --> [US3] Add summary pre-generation call in the workflow engine — before executing an agent step, check if the agent's `document_mode` is `"summary"` and call `DocumentPipeline.generate_summaries()` if summaries aren't yet cached in hiveflow/core/workflow.py
- [x] T010 <!-- bd:hiveflow-32t.10 --> [P] [US3] Write tests for summary document mode: LLM summary generation, caching (second call skips LLM), fallback to metadata_only when no LLM available, summary respects MAX_SUMMARY_LENGTH, scope_for_agent returns single summary chunk in tests/test_summary_document_mode.py

**Checkpoint**: Agents with `document_mode="summary"` receive condensed LLM summaries. Caching prevents duplicate LLM calls.

---

## Phase 6: User Story 4 — Reference Document Metadata in Prompt Templates (Priority: P3)

**Goal**: Register `$document_count`, `$document_names`, and `$document_summary` as template variables that are auto-populated from workflow state when documents are loaded.

**Independent Test**: Load documents into state, render a prompt template using document variables, verify correct substitution.

### Implementation for User Story 4

- [x] T011 <!-- bd:hiveflow-32t.11 --> [US4] Inject document template variables (`document_count`, `document_names`, `document_summary`) into the prompt variables when building agent messages — extract from state's `documents` and `document_summary` keys with defaults (0, "", "") when no documents loaded in hiveflow/core/agent.py
- [x] T012 <!-- bd:hiveflow-32t.12 --> [P] [US4] Write tests for document template variables: variables populated from state, defaults when no documents, document_count is integer, document_names is comma-separated, document_summary from state in tests/test_document_template_vars.py

**Checkpoint**: Prompt templates can reference `$document_count`, `$document_names`, `$document_summary`.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Finalize exports, documentation, and validate end-to-end.

- [x] T013 <!-- bd:hiveflow-32t.13 --> [P] Update CHANGELOG.md with all 4 enhancements (instructions_file, load_from_bytes, summary mode, template variables)
- [x] T014 <!-- bd:hiveflow-32t.14 --> Run full test suite (`uv run pytest tests/ --ignore=tests/test_api.py --ignore=tests/test_api_documents.py --ignore=tests/test_markitdown_loader.py --ignore=tests/test_observability.py`) and fix any regressions
- [x] T015 <!-- bd:hiveflow-32t.15 --> Validate quickstart.md examples compile and execute correctly against the implemented code

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 — BLOCKS all user stories
- **US1 — Instructions File (Phase 3)**: Depends on Phase 2 only
- **US2 — Load from Bytes (Phase 4)**: Depends on Phase 2 only
- **US3 — Summary Mode (Phase 5)**: Depends on Phase 2 only
- **US4 — Template Variables (Phase 6)**: Depends on Phase 2 only
- **Polish (Phase 7)**: Depends on all user stories being complete

### User Story Dependencies

```
Phase 1 (Setup)
    │
Phase 2 (Foundational)
    │
    ├─── Phase 3: US1 Instructions File (P1) ─────────┐
    │                                                   │
    ├─── Phase 4: US2 Load from Bytes (P2) ────────────┤
    │                                                   │
    ├─── Phase 5: US3 Summary Mode (P2) ───────────────┤
    │                                                   │
    └─── Phase 6: US4 Template Variables (P3) ─────────┘
                                                        │
                                                  Phase 7 (Polish)
```

**All 4 user stories are fully independent** — they touch different modules/methods and can be implemented in any order or in parallel.

### Within Each User Story

- Implementation before tests (tests marked [P] can run in parallel with impl)
- Story complete = checkpoint passes

### Parallel Opportunities

**Across stories**: All 4 stories can run in parallel (no shared modified files except US3+US4 both touch agent.py — but different methods).

**Within stories** (tasks marked [P]):
- US1: T003 (tests) in parallel with T002 (implementation)
- US2: T006 (tests) in parallel with T004-T005 (implementation)
- US3: T010 (tests) in parallel with T007-T009 (implementation)
- US4: T012 (tests) in parallel with T011 (implementation)

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup — verify baseline
2. Complete Phase 3: US1 — add instructions_file to HiveFlow.run()
3. **STOP and VALIDATE**: Test instructions_file independently
4. This alone delivers value: Python API parity with CLI

### Incremental Delivery

1. Setup → US1 (Instructions File) → **MVP: Python API parity**
2. Add US2 (Load from Bytes) → **API-ready: Byte stream support**
3. Add US3 (Summary Mode) → **Efficient: Token-saving summaries**
4. Add US4 (Template Variables) → **Dynamic: Self-describing prompts**
5. Each increment is independently valuable and testable

### Parallel Team Strategy

With multiple developers after Setup completes:
- **Developer A**: US1 (hiveflow.py) — fully independent
- **Developer B**: US2 (plugins/documents/__init__.py + documents.py) — fully independent
- **Developer C**: US3 (documents.py + workflow.py) — fully independent
- **Developer D**: US4 (agent.py) — fully independent

---

## Notes

- [P] tasks = different files, no dependencies on incomplete tasks
- [Story] labels map tasks to user stories for traceability
- All 4 enhancements are backward compatible (§2.5) — no existing API changes
- US3 (Summary Mode) is the most complex: requires async LLM call, state caching, and workflow engine integration
- US1 and US4 are the simplest: single-method changes with straightforward tests
- Total: 15 tasks across 7 phases
