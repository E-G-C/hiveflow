# Tasks: Task Preprocessing and Large-Input Context Management

**Input**: Design documents from `/specs/014-task-preprocessing/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: Included — the spec explicitly lists testing requirements (independent tests per user story, SC-001 through SC-007).

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **Single project**: `hiveflow/` package at repository root, `tests/` at repository root
- Refer to plan.md Project Structure for the full file-level change map

---

## Phase 1: Setup

**Purpose**: Project initialization — new module skeleton, configuration fields, provider protocol extension

- [x] T001 <!-- bd:hiveflow-38f.1 --> Create `hiveflow/core/preprocessing.py` with module docstring, imports (`structlog`, `dataclasses`, `pydantic`, `typing`), and empty class stubs for `PreprocessingConfig`, `ModelContextRegistry`, `TaskDataChunk`, `ChunkMeta`, `TaskDataManifest`, `TaskPreprocessor` per contracts/api.md
- [x] T002 <!-- bd:hiveflow-38f.2 --> [P] Add 7 new `TASK_PREPROCESS_*` fields to `HiveFlowConfig` in `hiveflow/core/config.py` per Contract 6 — `TASK_PREPROCESS_DISABLED`, `TASK_PREPROCESS_THRESHOLD_OVERRIDE`, `TASK_CONTEXT_RATIO`, `TASK_PIPELINE_FACTOR`, `TASK_CHUNK_CONTEXT_RATIO`, `TASK_CHUNK_OVERLAP_RATIO`, `TASK_TOKENS_PER_WORD`
- [x] T003 <!-- bd:hiveflow-38f.3 --> [P] Add optional `context_window` property returning `None` to `LLMProvider` protocol in `hiveflow/plugins/llm/__init__.py` per Contract 9

**Checkpoint**: Module skeleton exists, config fields available, provider protocol extended. All existing tests still pass.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core data classes and infrastructure that ALL user stories depend on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T004 <!-- bd:hiveflow-38f.4 --> Implement `PreprocessingConfig` pydantic model in `hiveflow/core/preprocessing.py` with all 7 fields, defaults, and validation per Contract 3
- [x] T005 <!-- bd:hiveflow-38f.5 --> [P] Implement `TaskDataChunk` dataclass with `chunk_id`, `content`, `words`, `topic_hint` fields and `to_dict()` method in `hiveflow/core/preprocessing.py` per Contract 4
- [x] T006 <!-- bd:hiveflow-38f.6 --> [P] Implement `ChunkMeta` dataclass with `chunk_id`, `words`, `topic_hint` fields in `hiveflow/core/preprocessing.py` per Contract 4
- [x] T007 <!-- bd:hiveflow-38f.7 --> [P] Implement `TaskDataManifest` dataclass with `total_words`, `chunk_count`, `model_context_tokens`, `effective_threshold`, `boundary_method`, `chunks` fields and `to_dict()` method in `hiveflow/core/preprocessing.py` per Contract 4
- [x] T008 <!-- bd:hiveflow-38f.8 --> Implement `ModelContextRegistry` class with `_registry` dict, `default_context=16000`, `resolve()` (exact match → longest prefix match → default), `register()`, and built-in model lookup table (~20 entries) in `hiveflow/core/preprocessing.py` per data-model.md
- [x] T009 <!-- bd:hiveflow-38f.9 --> Create `tests/test_preprocessing.py` with unit tests for `PreprocessingConfig` defaults/validation, `TaskDataChunk.to_dict()`, `TaskDataManifest.to_dict()`, `ModelContextRegistry.resolve()` (exact, prefix, default fallback, longest-prefix-wins), and `ModelContextRegistry.register()`

**Checkpoint**: All data classes and registry operational. Unit tests pass. Foundation ready for user stories.

---

## Phase 3: User Story 1 — Large input is automatically split (Priority: P1) 🎯 MVP

**Goal**: When a task exceeds the model-derived threshold, automatically separate instructions from data so that the planner agent receives only instructions plus a compact data summary, not the full blob.

**Independent Test**: Submit a task file containing 5,000+ words of instructions and 15,000+ words of data. Verify that the system separates them and no single agent receives more than 20% of the model's context window as task content.

### Implementation for User Story 1

- [x] T010 <!-- bd:hiveflow-38f.10 --> [US1] Implement `TaskPreprocessor.__init__()` accepting `llm_provider`, `model`, `config`, `context_registry` with defaults per Contract 1 in `hiveflow/core/preprocessing.py`
- [x] T011 <!-- bd:hiveflow-38f.11 --> [US1] Implement `TaskPreprocessor._compute_threshold()` — compute word-count threshold as `context_window_tokens * context_ratio / tokens_per_word / (agent_count * pipeline_factor)` with `threshold_override` support in `hiveflow/core/preprocessing.py` (FR-001, FR-010)
- [x] T012 <!-- bd:hiveflow-38f.12 --> [US1] Implement `TaskPreprocessor._detect_boundary()` — ordered heuristic cascade: (1) explicit section labels (`## Data`, `## Content`, `## Input`, `## Source`), (2) horizontal rule + heading, (3) fenced code block enclosing >60% of words, (4) size gradient (short section <30% → long section >70%), returns `(instructions, data)` tuple in `hiveflow/core/preprocessing.py` (FR-003, R8)
- [x] T013 <!-- bd:hiveflow-38f.13 --> [US1] Implement LLM fallback for boundary detection — when no structural heuristic matches, make a single LLM call with the first 2,000 words to identify the boundary. On LLM failure, fall back to 20/80 word split in `hiveflow/core/preprocessing.py` (FR-004)
- [x] T014 <!-- bd:hiveflow-38f.14 --> [US1] Implement `TaskPreprocessor.preprocess()` orchestration method — threshold check, boundary detection, state enrichment (`task_instructions`, `task_data`, `task_data_summary=""`, `task_data_manifest`), update `state["task"]` to instructions only. Skip all preprocessing when below threshold (FR-011). Handle `disabled` config flag in `hiveflow/core/preprocessing.py`
- [x] T015 <!-- bd:hiveflow-38f.15 --> [US1] Add structured logging via `structlog` for `task_preprocessing.threshold_check` and `task_preprocessing.boundary_detected` events per FR-014 in `hiveflow/core/preprocessing.py` (R9)
- [x] T016 <!-- bd:hiveflow-38f.16 --> [US1] Integrate `TaskPreprocessor` into `WorkflowEngine.__init__()` — add optional `task_preprocessor` parameter per Contract 5 in `hiveflow/core/workflow.py`
- [x] T017 <!-- bd:hiveflow-38f.17 --> [US1] Call `self._task_preprocessor.preprocess(state, agent_count)` in `WorkflowEngine.execute()` after document loading (line ~468) and before collaboration init (line ~492) in `hiveflow/core/workflow.py` (R1)
- [x] T018 <!-- bd:hiveflow-38f.18 --> [US1] Update `Agent._summarize_state()` in `hiveflow/core/agent.py` — add preprocessing-aware branch at line ~740: when `task_instructions` exists in state, use it instead of `state["task"]`; append `task_data_summary` if present (FR-008, R6)
- [x] T019 <!-- bd:hiveflow-38f.19 --> [US1] Add unit tests for threshold computation (128K model, 8K model, unknown model fallback, threshold_override, disabled flag) in `tests/test_preprocessing.py`
- [x] T020 <!-- bd:hiveflow-38f.20 --> [US1] Add unit tests for boundary detection — 4 structural patterns (explicit label, hrule+heading, code fence, size gradient) plus LLM fallback and LLM failure fallback in `tests/test_preprocessing.py`
- [x] T021 <!-- bd:hiveflow-38f.21 --> [US1] Add unit tests for `preprocess()` end-to-end — above threshold (state enriched), below threshold (state unchanged), disabled (state unchanged), entirely instructional task (empty data) in `tests/test_preprocessing.py`
- [x] T022 <!-- bd:hiveflow-38f.22 --> [US1] Add tests for preprocessing-aware `_summarize_state()` — when `task_instructions` present, when absent (fallback), when `task_data_summary` present in `tests/test_agent.py`

**Checkpoint**: Core preprocessing works — large inputs are separated into instructions and data. Agents receive compact context. Small tasks pass through unchanged. All unit tests pass.

---

## Phase 4: User Story 2 — Threshold adapts to model context window (Priority: P1)

**Goal**: The preprocessing threshold is computed as a function of the model's context window, not a fixed value. Different models trigger preprocessing at different input sizes.

**Independent Test**: Configure the same task with an 8K-context model and a 128K-context model. Verify the threshold differs by at least 10x (SC-006).

### Implementation for User Story 2

- [x] T023 <!-- bd:hiveflow-38f.23 --> [US2] Add provider-level context window resolution — in `TaskPreprocessor._compute_threshold()`, check `llm_provider.context_window` first before registry fallback in `hiveflow/core/preprocessing.py` (FR-002)
- [x] T024 <!-- bd:hiveflow-38f.24 --> [US2] Add unit tests for three-tier resolution: provider property → registry prefix match → 16K default. Test 8K vs 128K threshold difference ≥10x (SC-006). Test `threshold_override` bypasses model resolution in `tests/test_preprocessing.py`

**Checkpoint**: Threshold is fully model-adaptive. Tests verify 10x difference between 8K and 128K models. Provider-exposed context windows are respected.

---

## Phase 5: User Story 3 — Instructions and data separated generically (Priority: P1)

**Goal**: Boundary detection works for any content type using only structural markers — no format-specific logic.

**Independent Test**: Submit task files with 4 different boundary patterns (code fence, horizontal rule + heading, explicit `## Data` label, no markers at all). Verify correct separation in each case (SC-007).

### Implementation for User Story 3

- [x] T025 <!-- bd:hiveflow-38f.25 --> [US3] Create integration test fixtures — 4 synthetic task files (label boundary, hrule boundary, code fence boundary, size gradient boundary) plus an LLM-fallback-needed file in `tests/test_preprocessing.py`
- [x] T026 <!-- bd:hiveflow-38f.26 --> [US3] Add integration test verifying all 4 structural patterns produce correct instruction/data separation (SC-007) plus LLM fallback test in `tests/test_preprocessing.py`
- [x] T027 <!-- bd:hiveflow-38f.27 --> [US3] Add edge case test — entirely instructional task (no data section) results in `task_data=[]` and `task_instructions` containing full text in `tests/test_preprocessing.py`

**Checkpoint**: Boundary detection handles all 4 structural patterns plus LLM fallback. SC-007 verified via tests.

---

## Phase 6: User Story 4 — Data chunked and summarized for routing (Priority: P2)

**Goal**: After separation, the data section is chunked into model-appropriate segments with a compact summary and manifest for routing agents.

**Independent Test**: Submit a 16,000-word data section with a 128K model. Verify chunks are ~10% of context window. Verify summary ≤300 words and manifest lists all chunks with topic hints.

### Implementation for User Story 4

- [x] T028 <!-- bd:hiveflow-38f.28 --> [US4] Implement `TaskPreprocessor._chunk_data()` — paragraph-boundary-aware wrapper over existing `chunk_text()` from `hiveflow/plugins/documents/__init__.py`. Split on double newlines first, then apply word-count limits per chunk. Target chunk size = `context_window * chunk_context_ratio / tokens_per_word`. Overlap = `chunk_size * chunk_overlap_ratio`. Cap each chunk at 1.5x target. Assign `chunk_id` = `"chunk_001"`, `"chunk_002"`, etc. in `hiveflow/core/preprocessing.py` (FR-005, R3)
- [x] T029 <!-- bd:hiveflow-38f.29 --> [US4] Implement minimum data size skip — if data section word count ≤ chunk target, store as single `TaskDataChunk` entry without summarization or topic hints per clarification Q3 in `hiveflow/core/preprocessing.py` (FR-005)
- [x] T030 <!-- bd:hiveflow-38f.30 --> [US4] Implement `TaskPreprocessor._summarize_and_manifest()` — single LLM call generating both summary (≤300 words) and per-chunk topic hints. Build `TaskDataManifest` with all metadata. On failure: retry once with backoff, then fall back to `_mechanical_summary()` per clarification Q2 in `hiveflow/core/preprocessing.py` (FR-006, FR-007)
- [x] T031 <!-- bd:hiveflow-38f.31 --> [US4] Implement `TaskPreprocessor._mechanical_summary()` — generate fallback summary from manifest metadata: chunk count, total words, first-sentence excerpt from each chunk in `hiveflow/core/preprocessing.py`
- [x] T032 <!-- bd:hiveflow-38f.32 --> [US4] Wire chunking and summarization into `preprocess()` — after boundary detection, chunk data (if ≥ 1 chunk target), summarize, generate manifest, populate `task_data`, `task_data_summary`, `task_data_manifest` state keys in `hiveflow/core/preprocessing.py`
- [x] T033 <!-- bd:hiveflow-38f.33 --> [US4] Add structured logging for `task_preprocessing.chunking_complete` and `task_preprocessing.summarization_complete` and `task_preprocessing.complete` events per FR-014 in `hiveflow/core/preprocessing.py` (R9)
- [x] T034 <!-- bd:hiveflow-38f.34 --> [US4] Add unit tests for `_chunk_data()` — paragraph-boundary splitting, chunk size within 1.5x target, overlap between chunks, chunk_id sequencing in `tests/test_preprocessing.py`
- [x] T035 <!-- bd:hiveflow-38f.35 --> [US4] Add unit tests for minimum data size skip — data below chunk target stored as single entry with no summary call in `tests/test_preprocessing.py`
- [x] T036 <!-- bd:hiveflow-38f.36 --> [US4] Add unit tests for `_summarize_and_manifest()` — summary ≤300 words, manifest fields correct, topic hints present. Test retry+backoff on LLM failure. Test mechanical summary fallback in `tests/test_preprocessing.py`

**Checkpoint**: Full chunking and summarization pipeline operational. SC-001 (60% token reduction) and SC-003 (20% context cap) can be validated. Manifest generation correct.

---

## Phase 7: User Story 5 — Agents receive role-appropriate context (Priority: P2)

**Goal**: After preprocessing, planners receive summary + manifest, workers receive their assigned chunk, reviewers see assembled output. No agent gets the full data blob.

**Independent Test**: Run a preprocessing-enabled workflow. Inspect context assembled for each agent type. Verify planners see summary + manifest, workers see their chunk only, and fallback works when preprocessing keys are absent.

### Implementation for User Story 5

- [x] T037 <!-- bd:hiveflow-38f.37 --> [US5] Extend `Agent._summarize_state()` in `hiveflow/core/agent.py` — when `task_data_summary` is present, include data summary and manifest chunk list in context. When `current_item` contains a chunk dict (fan-out worker), include chunk content
- [x] T038 <!-- bd:hiveflow-38f.38 --> [US5] Parse `preprocessing:` section from team config dict in `TeamGenerator.build()`, create `PreprocessingConfig`, instantiate `TaskPreprocessor`, pass to `WorkflowEngine` in `hiveflow/core/teams.py` (FR-012, Contract 7, R7)
- [x] T039 <!-- bd:hiveflow-38f.39 --> [US5] Add tests for role-based context — planner gets instructions + summary + manifest, worker with `current_item` chunk gets instruction + chunk content, agent without preprocessing keys gets full `state["task"]` unchanged in `tests/test_agent.py`

**Checkpoint**: Context routing works end-to-end. SC-003 (20% cap) fully enforced. Team-level config overrides operational.

---

## Phase 8: User Story 6 — Chunks routed via delegation, fan-out, or retrieval (Priority: P3)

**Goal**: Chunks reach workers through three mechanisms: delegation with chunk context, parallel fan-out over `task_data`, and on-demand retrieval.

**Independent Test**: For each routing strategy, run a workflow with preprocessed chunks. Verify workers receive individual chunks, not the full data blob.

### Implementation for User Story 6

- [x] T040 <!-- bd:hiveflow-38f.40 --> [US6] Extend `CollaborationRuntime._build_sub_state()` in `hiveflow/core/collaboration.py` — propagate `task_instructions`, `task_data_summary`, `task_data_manifest` from parent state. When `chunk_ids` is provided, filter `task_data` to only matching chunks (R5)
- [x] T041 <!-- bd:hiveflow-38f.41 --> [US6] Extend `DelegateTaskTool` input schema in `hiveflow/core/collaboration.py` — add optional `chunk_ids` array parameter per Contract 8
- [x] T042 <!-- bd:hiveflow-38f.42 --> [US6] Extend `parallel_fan_out` step handling in `WorkflowEngine` to support `source: "task_data"` — iterate over `state["task_data"]` and set `current_item` to each chunk dict in `hiveflow/core/workflow.py` (R10, Contract 10)
- [x] T043 <!-- bd:hiveflow-38f.43 --> [US6] Create `tests/test_preprocessing_integration.py` with integration tests: (1) delegation with `chunk_ids` filtering, (2) fan-out over `task_data` setting `current_item` per chunk, (3) backward compatibility — no preprocessing keys means unchanged fan-out behavior (FR-009)

**Checkpoint**: All three chunk routing strategies operational. Full feature complete.

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, final validation, and cross-story integration testing

- [x] T044 <!-- bd:hiveflow-38f.44 --> [P] Update `docs/guides/context-management.md` with task preprocessing documentation — auto-threshold, boundary detection, chunking, configuration options
- [x] T045 <!-- bd:hiveflow-38f.45 --> [P] Update `docs/configuration.md` with new `TASK_PREPROCESS_*` configuration fields and team-level `preprocessing:` section
- [x] T046 <!-- bd:hiveflow-38f.46 --> Add full end-to-end integration test in `tests/test_preprocessing_integration.py` — submit 21K-word task, verify SC-001 (≥60% token reduction), SC-002 (≥80% topic coverage), SC-003 (no agent >20% context), SC-004 (small task unchanged), SC-005 (≤2 LLM calls overhead)
- [x] T047 <!-- bd:hiveflow-38f.47 --> Update CHANGELOG.md with task preprocessing feature entry
- [x] T048 <!-- bd:hiveflow-38f.48 --> Run `uv run pytest` — verify all existing tests still pass plus all new tests pass

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Phase 2 — core preprocessing pipeline
- **US2 (Phase 4)**: Depends on Phase 3 (T011 threshold computation) — refines threshold logic
- **US3 (Phase 5)**: Depends on Phase 3 (T012-T013 boundary detection) — validates boundary coverage
- **US4 (Phase 6)**: Depends on Phase 3 — adds chunking and summarization on top of boundary detection
- **US5 (Phase 7)**: Depends on Phase 3 + Phase 6 — context routing requires preprocessed state
- **US6 (Phase 8)**: Depends on Phase 7 — chunk routing requires role-based context to be working
- **Polish (Phase 9)**: Depends on all user stories being complete

### User Story Dependencies

- **US1 (P1)**: After Foundational → implements core `preprocess()`, boundary detection, engine integration
- **US2 (P1)**: After US1 → refines threshold computation with provider resolution
- **US3 (P1)**: After US1 → validates boundary detection across 4+ patterns
- **US4 (P2)**: After US1 → adds chunking, summarization, manifest on top of boundary detection
- **US5 (P2)**: After US1 + US4 → adds role-based context assembly and team config
- **US6 (P3)**: After US5 → adds delegation, fan-out, and retrieval routing

### Within Each User Story

- Data classes before logic
- Core logic before integration points
- Integration before tests
- Tests validate the story checkpoint

### Parallel Opportunities

- **Phase 1**: T002 and T003 can run in parallel (different files)
- **Phase 2**: T005, T006, T007 can run in parallel (different dataclasses, same file but independent sections)
- **Phase 3**: T019, T020, T021, T022 tests can be written in parallel after T014 completes
- **Phase 6**: T034, T035, T036 tests can be written in parallel after T032 completes
- **Phase 9**: T044 and T045 documentation tasks can run in parallel

---

## Parallel Example: Phase 2 (Foundational)

```
# Launch independent dataclass implementations in parallel:
Task T005: "Implement TaskDataChunk dataclass in hiveflow/core/preprocessing.py"
Task T006: "Implement ChunkMeta dataclass in hiveflow/core/preprocessing.py"
Task T007: "Implement TaskDataManifest dataclass in hiveflow/core/preprocessing.py"
```

## Parallel Example: Phase 3 (US1 tests)

```
# After T014 (preprocess() complete), launch test tasks in parallel:
Task T019: "Unit tests for threshold computation in tests/test_preprocessing.py"
Task T020: "Unit tests for boundary detection in tests/test_preprocessing.py"
Task T021: "Unit tests for preprocess() end-to-end in tests/test_preprocessing.py"
Task T022: "Tests for preprocessing-aware _summarize_state() in tests/test_agent.py"
```

---

## Implementation Strategy

### MVP First (User Stories 1-3 Only)

1. Complete Phase 1: Setup (T001-T003)
2. Complete Phase 2: Foundational (T004-T009)
3. Complete Phase 3: US1 — core preprocessing (T010-T022)
4. **STOP and VALIDATE**: Large inputs are separated, agents receive compact context, small tasks unchanged
5. Complete Phase 4: US2 — model-adaptive threshold (T023-T024)
6. Complete Phase 5: US3 — generic boundary patterns (T025-T027)
7. **MVP COMPLETE**: Preprocessing activates automatically with model-aware thresholds and generic boundary detection

### Incremental Delivery

1. Setup + Foundational → data classes and registry ready
2. Add US1 → core preprocessing works → validate with 21K-word task
3. Add US2 → threshold adapts to model → verify 8K vs 128K difference
4. Add US3 → all boundary patterns covered → verify SC-007
5. Add US4 → chunking + summarization → verify SC-001 token reduction
6. Add US5 → role-based context routing → verify SC-003 cap
7. Add US6 → delegation + fan-out + retrieval → full feature
8. Polish → documentation + final validation

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable at its checkpoint
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- The spec explicitly requires tests (independent test per user story, 7 success criteria)
- All new code goes in `hiveflow/core/preprocessing.py` (single new file) — modifications to 6 existing files
