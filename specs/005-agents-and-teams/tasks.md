# Tasks: Agents and Teams

**Input**: Design documents from `/specs/005-agents-and-teams/`
**Prerequisites**: plan.md ✓, spec.md ✓, research.md ✓, data-model.md ✓, contracts/ ✓, quickstart.md ✓

**Tests**: Included per constitution §6.1 — each gap requires corresponding unit tests.

**Organization**: Tasks grouped by user story. ~75% of functionality already exists (research.md). Tasks focus on 12 identified gaps (G1–G12). User Stories 6 (Model Selection) and 7 (State Schema) are already fully implemented and require no tasks.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2)

## Path Conventions

- Source: `hiveflow/` (single Python package)
- Templates: `hiveflow/templates/`
- Tests: `tests/`

---

## Phase 1: Foundational Schema & Infrastructure

**Purpose**: Schema additions and core model changes that BLOCK all user story implementation

**⚠️ CRITICAL**: No user story work can begin until these schema changes land

- [x] T001 <!-- bd:hiveflow-xi5.1 --> Add `on_failure` (str|None, default=None), `max_retries` (int, default=1, ge=1), `rollback_on_failure` (bool, default=False), and `rollback_action` (str|None, default=None) fields to AgentDefinition with a field_validator ensuring on_failure is one of 'fail', 'retry', 'skip' in hiveflow/core/schema.py
- [x] T002 <!-- bd:hiveflow-xi5.2 --> Extend the existing `action_policy` field_validator to accept 'dry_run' and 'confirm_on_error' in addition to 'auto' and 'require_approval' in hiveflow/core/schema.py
- [x] T003 <!-- bd:hiveflow-xi5.3 --> Add `SUB_WORKFLOW = "sub_workflow"` member to the WorkflowStepType StrEnum in hiveflow/core/schema.py
- [x] T004 <!-- bd:hiveflow-xi5.4 --> Add `team` (str|None), `input_mapping` (dict[str,str]|None), and `output_mapping` (dict[str,str]|None) fields to WorkflowStepDefinition with a model_validator ensuring `team` is required when `type` is `sub_workflow` in hiveflow/core/schema.py
- [x] T005 <!-- bd:hiveflow-xi5.5 --> [P] Enhance the ActionRecord dataclass with `policy` (str|None=None), `approved_by` (str|None=None), `reversible` (bool=False), `rollback_action` (str|None=None), and `workflow_run_id` (str|None=None) fields — all with backward-compatible defaults in hiveflow/core/result_payload.py
- [ ] T006 <!-- bd:hiveflow-xi5.6 --> [P] Add tests for new AgentDefinition fields (on_failure validation accepts fail/retry/skip, rejects invalid; max_retries ge=1; rollback fields present) in tests/test_schema_additions.py
- [x] T007 <!-- bd:hiveflow-xi5.7 --> [P] Add tests for expanded action_policy validator (accepts dry_run, confirm_on_error; rejects unknown values), SUB_WORKFLOW enum member, and sub_workflow step validation (team required) in tests/test_schema_additions.py

**Checkpoint**: All schema additions landed and validated by tests. User story work can begin.

---

## Phase 2: User Story 1 — Define and Run a Team from Configuration (Priority: P1) 🎯 MVP

**Goal**: Complete the team execution path with per-agent failure policies (`on_failure`: fail/retry/skip) and automatic transient LLM error backoff, enabling robust team execution against real-world LLM APIs.

**Independent Test**: Run a team with an agent configured with `on_failure="retry"` and verify retry behavior. Mock LLM 429 errors and verify automatic exponential backoff retry before on_failure is triggered.

### Implementation for User Story 1

- [x] T008 <!-- bd:hiveflow-xi5.8 --> [US1] Implement `_retry_transient` async helper method in WorkflowEngine with exponential backoff (base_delay=1.0s, backoff_factor=2.0, max_retries=3) that catches transient LLM errors (httpx.HTTPStatusError 429/5xx, openai.RateLimitError, openai.APIStatusError 5xx, anthropic.RateLimitError, anthropic.APIStatusError 5xx, ConnectionError, TimeoutError, asyncio.TimeoutError) and logs each retry attempt via structlog in hiveflow/core/workflow.py
- [x] T009 <!-- bd:hiveflow-xi5.9 --> [US1] Implement `_execute_agent_with_failure_policy` async wrapper that first calls `_retry_transient(agent.execute, state)`, then on failure applies the agent's `on_failure` policy: 'fail' re-raises (workflow halts), 'retry' retries up to `max_retries` then re-raises, 'skip' logs warning via structlog and returns state unmodified in hiveflow/core/workflow.py
- [x] T010 <!-- bd:hiveflow-xi5.10 --> [US1] Wire `_execute_agent_with_failure_policy` into the main agent execution path in `WorkflowEngine._execute_step()` so all agent executions go through transient backoff → on_failure policy in hiveflow/core/workflow.py
- [x] T011 <!-- bd:hiveflow-xi5.11 --> [P] [US1] Add tests for `_retry_transient`: mock 429 twice then succeed (verify success), mock persistent 5xx (verify raises after 3 retries), mock ConnectionError (verify retried), verify exponential delay timing in tests/test_transient_retry.py
- [x] T012 <!-- bd:hiveflow-xi5.12 --> [P] [US1] Add tests for `_execute_agent_with_failure_policy`: on_failure='fail' halts workflow on error, on_failure='retry' retries up to max_retries, on_failure='skip' proceeds with state unmodified, on_failure=None defaults to 'fail' behavior in tests/test_core.py

**Checkpoint**: Teams run with per-agent failure handling and transparent transient error recovery. US1 is the MVP — validate independently.

---

## Phase 3: User Story 2 — Use Archetypes to Compose Teams (Priority: P2)

**Goal**: Provide archetype JSON files on disk and additional team templates so developers can browse, load, and compose teams from reusable pre-built definitions.

**Independent Test**: Verify `ArchetypeLibrary.default()` loads all 6 archetypes from JSON files in `hiveflow/templates/archetypes/`. Verify `code_review.json` and `content_creation.json` load as valid TeamConfiguration objects.

### Implementation for User Story 2

- [x] T013 <!-- bd:hiveflow-xi5.13 --> [P] [US2] Create researcher.json archetype file matching the existing 'researcher' entry in ARCHETYPES dict in hiveflow/templates/archetypes/researcher.json
- [x] T014 <!-- bd:hiveflow-xi5.14 --> [P] [US2] Create planner.json archetype file matching the existing 'planner' entry in ARCHETYPES dict in hiveflow/templates/archetypes/planner.json
- [x] T015 <!-- bd:hiveflow-xi5.15 --> [P] [US2] Create writer.json archetype file matching the existing 'writer' entry in ARCHETYPES dict in hiveflow/templates/archetypes/writer.json
- [x] T016 <!-- bd:hiveflow-xi5.16 --> [P] [US2] Create reviewer.json archetype file matching the existing 'reviewer' entry in ARCHETYPES dict in hiveflow/templates/archetypes/reviewer.json
- [x] T017 <!-- bd:hiveflow-xi5.17 --> [P] [US2] Create editor.json archetype file matching the existing 'editor' entry in ARCHETYPES dict in hiveflow/templates/archetypes/editor.json
- [x] T018 <!-- bd:hiveflow-xi5.18 --> [P] [US2] Create human_reviewer.json archetype file matching the existing 'human_reviewer' entry in ARCHETYPES dict in hiveflow/templates/archetypes/human_reviewer.json
- [x] T019 <!-- bd:hiveflow-xi5.19 --> [P] [US2] Create code_review.json team template with reviewer + code_writer + human_reviewer agents and a conditional review loop workflow in hiveflow/templates/code_review.json
- [x] T020 <!-- bd:hiveflow-xi5.20 --> [P] [US2] Create content_creation.json team template with planner + researcher + writer + editor agents and a sequential workflow in hiveflow/templates/content_creation.json
- [x] T021 <!-- bd:hiveflow-xi5.21 --> [US2] Add tests for archetype JSON file loading (all 6 load from disk, match in-memory ARCHETYPES) and new team template loading (code_review.json, content_creation.json validate as TeamConfiguration) in tests/test_teams.py

**Checkpoint**: Archetype library discoverable on disk. Three team templates available (research_report, code_review, content_creation).

---

## Phase 4: User Story 3 — Execute Action-Oriented Agents with Safety Policies (Priority: P2)

**Goal**: Complete the `action_executor` behavior type with `dry_run` and `confirm_on_error` policies, rollback support, and enhanced audit trail fields on all action records.

**Independent Test**: Configure an action_executor with `action_policy="dry_run"`, run workflow, verify `{agent}_dry_run_plan` recorded without execution. Configure `rollback_on_failure=True` and verify rollback triggers on downstream failure.

### Implementation for User Story 3

- [x] T022 <!-- bd:hiveflow-xi5.22 --> [US3] Implement `dry_run` action policy branch in `_execute_action_executor`: have LLM propose tool calls, create ActionRecord entries with `status="dry_run"` without executing tools, store planned actions list in `{agent_id}_dry_run_plan` state key in hiveflow/core/agent.py
- [x] T023 <!-- bd:hiveflow-xi5.23 --> [US3] Implement `confirm_on_error` action policy branch in `_execute_action_executor`: execute tools like `auto` mode, on tool execution error create checkpoint with `awaiting_error_resolution` containing error details and pause workflow for human decision (retry/skip/abort) in hiveflow/core/agent.py
- [x] T024 <!-- bd:hiveflow-xi5.24 --> [US3] Update all action policy paths in `_execute_action_executor` to populate enhanced ActionRecord fields (`policy`, `approved_by`, `reversible`, `rollback_action`, `workflow_run_id`) when creating action records in hiveflow/core/agent.py
- [x] T025 <!-- bd:hiveflow-xi5.25 --> [US3] Implement `_trigger_rollback` async method in WorkflowEngine that invokes the declared `rollback_action` tool with original action context, logs errors via structlog if rollback itself fails (does not re-raise) in hiveflow/core/workflow.py
- [x] T026 <!-- bd:hiveflow-xi5.26 --> [US3] Wire rollback triggering into workflow step failure handling: when a step fails and the previous action_executor agent had `rollback_on_failure=True`, call `_trigger_rollback` with that agent's rollback_action and original action context in hiveflow/core/workflow.py
- [x] T027 <!-- bd:hiveflow-xi5.27 --> [P] [US3] Add tests for dry_run policy: actions recorded with status="dry_run" but tools NOT executed, `{agent}_dry_run_plan` populated in state in tests/test_action_executor.py
- [x] T028 <!-- bd:hiveflow-xi5.28 --> [P] [US3] Add tests for confirm_on_error policy: tools execute on success, workflow pauses with checkpoint on tool error in tests/test_action_executor.py
- [x] T029 <!-- bd:hiveflow-xi5.29 --> [P] [US3] Add tests for rollback: rollback triggers on downstream failure when rollback_on_failure=True, rollback failure is logged not raised, rollback skipped when rollback_on_failure=False in tests/test_action_executor.py

**Checkpoint**: All four action policies functional (auto, require_approval, dry_run, confirm_on_error). Rollback declarative and tested. Enhanced audit trail populating on all action records.

---

## Phase 5: User Story 4 — Workflow Step Types Including Gated and Conditional (Priority: P2)

**Goal**: Add `sub_workflow` step type for nested workflow execution, namespaced parallel fan-out merge for granular result access, and conditional ambiguity defaulting to reject path.

**Independent Test**: Run a workflow with a conditional step where agent output is ambiguous (tied scores), verify reject path taken. Run parallel fan-out and verify `{agent}_parallel_results` dict contains indexed sub-keys. Run a sub_workflow step and verify inner workflow executes with mapped state.

### Implementation for User Story 4

- [x] T030 <!-- bd:hiveflow-xi5.30 --> [US4] Change conditional tie-breaking in `_evaluate_condition` from `accept_score >= reject_score` to `accept_score > reject_score` so ties default to reject, and add a structlog warning when scores are tied (ambiguous result) in hiveflow/core/workflow.py
- [x] T031 <!-- bd:hiveflow-xi5.31 --> [US4] Add `{agent}_parallel_results` dict with `item_{i}` → full result dict mapping to `_execute_parallel` output, preserving existing `{agent}_outputs` (list) and `{agent}_output` (concatenated string) keys for backward compatibility in hiveflow/core/workflow.py
- [x] T032 <!-- bd:hiveflow-xi5.32 --> [US4] Implement `_execute_sub_workflow` async method in WorkflowEngine: load inner TeamConfiguration from TeamLibrary by `step.team` name, build inner agents and WorkflowEngine, apply `input_mapping` (or pass full state), execute inner workflow, apply `output_mapping` (or merge full result), enforce max recursion depth of 5 in hiveflow/core/workflow.py
- [x] T033 <!-- bd:hiveflow-xi5.33 --> [US4] Wire `_execute_sub_workflow` into WorkflowEngine step type dispatch so `WorkflowStepType.SUB_WORKFLOW` steps call the new method in hiveflow/core/workflow.py
- [x] T034 <!-- bd:hiveflow-xi5.34 --> [US4] Pass TeamLibrary reference to WorkflowEngine from HiveFlow facade so sub_workflow steps can resolve team names in hiveflow/core/hiveflow.py
- [x] T035 <!-- bd:hiveflow-xi5.35 --> [P] [US4] Add tests for conditional ambiguity → reject default: tied accept/reject scores follow reject path, structlog warning emitted on ambiguous result in tests/test_advanced.py
- [x] T036 <!-- bd:hiveflow-xi5.36 --> [P] [US4] Add tests for namespaced parallel merge: `{agent}_parallel_results` dict structure correct with `item_0`, `item_1` keys, backward compat with `_outputs` list and `_output` concatenated string in tests/test_advanced.py
- [x] T037 <!-- bd:hiveflow-xi5.37 --> [P] [US4] Add tests for sub_workflow execution: inner workflow runs with input_mapping applied, output_mapping merges result, recursion depth > 5 raises RuntimeError in tests/test_core.py

**Checkpoint**: All workflow step types functional (sequential, parallel_fan_out, conditional, human_gate, gated, sub_workflow). Conditional is conservative on ambiguity. Parallel results granularly accessible. Sub-workflows composable with depth guard.

---

## Phase 6: User Story 5 — LLM-Generated Team Composition (Priority: P3)

**Goal**: Enable LLM-based team generation that receives a task description and available registries, and produces a validated TeamConfiguration with capability gap reports.

**Independent Test**: Call `generate_team_from_llm` with a task description and mock LLM provider, verify the returned `TeamGenerationResult` contains a valid `TeamConfiguration`, capability gap list, and new archetypes.

### Implementation for User Story 5

- [x] T038 <!-- bd:hiveflow-xi5.38 --> [US5] Implement `generate_team_from_llm` async method on TeamGenerator: build structured prompt with task description, tool registry specs, and archetype library examples; call LLM via llm_provider; parse JSON response with json-repair; validate against TeamConfiguration schema; detect capability gaps by comparing requested tools/models against registries; return TeamGenerationResult with config, capability_gaps, and new_archetypes in hiveflow/core/teams.py
- [x] T039 <!-- bd:hiveflow-xi5.39 --> [US5] Add blocking gap rejection logic in `generate_team_from_llm`: if `auto_approve=True` and any CapabilityGap has severity='blocking', raise ValueError with gap details; if `auto_approve=False`, return result for developer inspection regardless of gap severity in hiveflow/core/teams.py
- [x] T040 <!-- bd:hiveflow-xi5.40 --> [P] [US5] Add tests for LLM team generation: valid output parses to TeamConfiguration, blocking gaps with auto_approve=True raises ValueError, degraded gaps produce warnings, auto_approve=False returns result for inspection, new_archetypes included in result in tests/test_teams.py

**Checkpoint**: LLM-generated teams work end-to-end. Capability gaps accurately reported and blocking gaps enforced.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, end-to-end validation, and cleanup across all stories

- [x] T041 <!-- bd:hiveflow-xi5.41 --> [P] Update docstrings for all modified public methods in hiveflow/core/schema.py, hiveflow/core/agent.py, hiveflow/core/workflow.py, hiveflow/core/teams.py, and hiveflow/core/result_payload.py
- [x] T042 <!-- bd:hiveflow-xi5.42 --> [P] Run quickstart.md scenarios (Scenarios 1–7) to validate end-to-end functionality across all implemented gaps
- [x] T043 <!-- bd:hiveflow-xi5.43 --> Run full test suite (`uv run pytest`) and fix any regressions introduced by the changes

---

## Dependencies & Execution Order

### Phase Dependencies

- **Foundational (Phase 1)**: No dependencies — can start immediately. BLOCKS all user stories.
- **US1 (Phase 2)**: Depends on Phase 1 (needs on_failure schema fields)
- **US2 (Phase 3)**: Depends on Phase 1 (needs SUB_WORKFLOW enum for template completeness) — can run in parallel with US1
- **US3 (Phase 4)**: Depends on Phase 1 (needs action_policy expansion + ActionRecord enhancement)
- **US4 (Phase 5)**: Depends on Phase 1 (needs sub_workflow schema) + Phase 2 (transient retry helper reused)
- **US5 (Phase 6)**: Depends on Phase 1 (schema) + Phase 3 (archetype JSON files used as examples in LLM prompt)
- **Polish (Phase 7)**: Depends on all user stories being complete

### User Story Dependencies

- **US1 (P1)**: Can start after Phase 1. No dependency on other stories. **This is the MVP.**
- **US2 (P2)**: Can start after Phase 1. Independent of US1.
- **US3 (P2)**: Can start after Phase 1. Independent of US1 and US2.
- **US4 (P2)**: Can start after Phase 1 + US1 (reuses _retry_transient pattern). Independent of US2/US3.
- **US5 (P3)**: Can start after Phase 1 + US2 (uses archetype files). Independent of US3/US4.
- **US6 (P3)**: Already implemented — no tasks needed.
- **US7 (P3)**: Already implemented — no tasks needed.

### Within Each User Story

- Schema/infrastructure changes before behavior implementation
- Core implementation before integration/wiring
- Tests can run in parallel with each other (marked [P])
- Story complete before moving to next priority

### Parallel Opportunities

- Phase 1: T005, T006, T007 <!-- bd:hiveflow-xi5.7 --> can run in parallel (different files)
- US1: T011, T012 <!-- bd:hiveflow-xi5.12 --> can run in parallel (different test files)
- US2: T013–T020 <!-- bd:hiveflow-xi5.20 --> can ALL run in parallel (each creates a separate file)
- US3: T027, T028, T029 <!-- bd:hiveflow-xi5.29 --> can run in parallel (different test sections)
- US4: T035, T036, T037 <!-- bd:hiveflow-xi5.37 --> can run in parallel (different test files)
- **Cross-story**: US1, US2, US3 can run in parallel after Phase 1

---

## Parallel Example: User Story 2

```text
# All archetype files are independent — launch simultaneously:
T013: Create researcher.json in hiveflow/templates/archetypes/
T014: Create planner.json in hiveflow/templates/archetypes/
T015: Create writer.json in hiveflow/templates/archetypes/
T016: Create reviewer.json in hiveflow/templates/archetypes/
T017: Create editor.json in hiveflow/templates/archetypes/
T018: Create human_reviewer.json in hiveflow/templates/archetypes/

# Team templates are also independent:
T019: Create code_review.json in hiveflow/templates/
T020: Create content_creation.json in hiveflow/templates/
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Foundational schema additions
2. Complete Phase 2: User Story 1 (on_failure + transient backoff)
3. **STOP and VALIDATE**: Run test suite, verify teams execute with failure handling
4. Deploy/demo — teams now run robustly against real LLM APIs

### Incremental Delivery

1. Phase 1 → Schema foundation ready
2. Add US1 → Test independently → **MVP: robust team execution**
3. Add US2 → Test independently → Archetypes on disk, 3 team templates
4. Add US3 → Test independently → Full action safety policies + rollback
5. Add US4 → Test independently → All workflow step types including sub_workflow
6. Add US5 → Test independently → LLM-generated team composition
7. Phase 7 → Polish, docs, final regression pass
8. Each story adds value without breaking previous stories

### Parallel Team Strategy

With multiple developers after Phase 1 completes:

- **Developer A**: US1 (P1 — MVP, priority)
- **Developer B**: US2 (P2 — archetypes, independent)
- **Developer C**: US3 (P2 — action policies, independent)
- After US1 done: Developer A picks up US4, then US5

---

## Summary

| Metric | Value |
|--------|-------|
| Total tasks | 43 |
| Phase 1 (Foundational) | 7 tasks |
| US1 (Define & Run Team) | 5 tasks |
| US2 (Archetypes) | 9 tasks |
| US3 (Action Safety) | 8 tasks |
| US4 (Workflow Steps) | 8 tasks |
| US5 (LLM Generation) | 3 tasks |
| Phase 7 (Polish) | 3 tasks |
| Parallel opportunities | 28 tasks marked [P] |
| Gaps covered | All 12 (G1–G12) |
| User stories skipped | US6 (Model Selection), US7 (State Schema) — already implemented |
| Suggested MVP scope | Phase 1 + US1 (12 tasks) |

---

## Notes

- [P] tasks = different files, no dependencies — safe for parallel execution
- [Story] label maps each task to its user story for traceability
- Each user story is independently completable and testable
- Commit after each task or logical group
- Stop at any checkpoint to validate the story independently
- All paths are relative to repository root (`hiveflow/`, `tests/`)
- Constitution §5.1: No `from __future__ import annotations`
- Constitution §5.4: All new methods must be async-first
- Constitution §6.1: Tests via `uv run pytest`
