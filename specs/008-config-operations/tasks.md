# Tasks: Configuration & Operations

**Input**: Design documents from `specs/008-config-operations/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅

**Tests**: Included — the spec requires integration tests for all resilience paths and the constitution (§6.1) mandates tests for new features.

**Organization**: Tasks grouped by user story to enable independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **Package root**: `hiveflow/core/` (existing)
- **Tests**: `tests/` (existing, flat structure)
- New modules: `hiveflow/core/action_queue.py`, `hiveflow/core/orchestrator.py`, `hiveflow/core/resilient_provider.py`

---

## Phase 1: Setup

**Purpose**: Validate existing baseline before making changes

- [x] T001 <!-- bd:hiveflow-jox.1 --> Run existing test suite with `uv run pytest tests/ --ignore=tests/test_api.py --ignore=tests/test_api_documents.py --ignore=tests/test_markitdown_loader.py --ignore=tests/test_observability.py` and confirm baseline passes

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: No new foundational infrastructure needed — all shared modules (`config.py`, `agent.py`, `streaming.py`, `prompts.py`) already exist. The existing codebase IS the foundation.

**⚠️ CRITICAL**: Phase 1 must pass before proceeding. No additional blocking work required.

**Checkpoint**: Baseline confirmed — user story implementation can begin.

---

## Phase 3: User Story 1 — Configure a Multi-Agent Workflow (Priority: P1) 🎯 MVP

**Goal**: Extend `HiveFlowConfig` with 8 new fields (Source Mode, Actions, MCP) so all configuration categories from the spec are covered, with full four-layer precedence (defaults → file → env → overrides).

**Independent Test**: Create a config file and environment variables with new fields, verify precedence resolution and validation error reporting.

### Implementation for User Story 1

- [x] T002 <!-- bd:hiveflow-jox.2 --> [US1] Add Source Mode fields (`SOURCE_MODE: Literal["web","local","hybrid","cloud","mcp","custom"]` default `"web"`, `DOC_PATH: str | None` default `None`) to `HiveFlowConfig` class in hiveflow/core/config.py
- [x] T003 <!-- bd:hiveflow-jox.3 --> [US1] Add Actions config fields (`DEFAULT_ACTION_POLICY: Literal["deny","allow","dry_run"]` default `"deny"`, `ENABLE_ROLLBACK: bool` default `False`, `ACTION_TIMEOUT: int` default `30`) to `HiveFlowConfig` class in hiveflow/core/config.py
- [x] T004 <!-- bd:hiveflow-jox.4 --> [US1] Add MCP config fields (`MCP_STRATEGY: Literal["disabled","fast","deep"]` default `"disabled"`, `MCP_SERVERS: list[dict]` default `[]`, `MCP_AUTO_TOOL_SELECTION: bool` default `True`) to `HiveFlowConfig` class in hiveflow/core/config.py
- [x] T005 <!-- bd:hiveflow-jox.5 --> [P] [US1] Write integration tests for four-layer config precedence covering all new fields (defaults, file override, env override, runtime override), tier variable resolution (`$SMART_LLM`), and validation error reporting for invalid types in tests/test_config_layering.py

**Checkpoint**: All configuration categories are configurable via file/env. Existing tests still pass.

---

## Phase 4: User Story 2 — Resilient Workflow Execution (Priority: P1)

**Goal**: Wire existing resilience modules (`fallback.py`, `json_utils.py`, `errors.py`, `ratelimit.py`, `cost.py`) into agent execution paths so LLM calls automatically get fallback chains, circuit breaking, rate limiting, JSON resilience, and cost tracking.

**Independent Test**: Simulate LLM failures and verify automatic fallback cascade; inject malformed JSON and verify parsing recovery; run concurrent requests and verify rate limiting.

### Implementation for User Story 2

- [x] T006 <!-- bd:hiveflow-jox.6 --> [US2] Add `FallbackChain.from_tiers(config)` class method to auto-build fallback chain with reduced max_tokens intermediate steps (tier → tier@50% → next tier → next@50% → fast → error) in hiveflow/core/fallback.py
- [x] T007 <!-- bd:hiveflow-jox.7 --> [P] [US2] Create `ResilientLLMProvider` wrapper class implementing the resilience pipeline (rate_limit → circuit_breaker → fallback_chain → cost_track) with `from_config()` factory method in hiveflow/core/resilient_provider.py
- [x] T008 <!-- bd:hiveflow-jox.8 --> [US2] Integrate `ResilientLLMProvider` into Agent initialization — wrap `self.llm_provider` with resilience layer when config is available, affecting all 4 LLM call sites (~lines 165, 208, 312, 423) in hiveflow/core/agent.py
- [x] T009 <!-- bd:hiveflow-jox.9 --> [US2] Replace all `json.loads()` calls in agent response parsing with `parse_json_resilient()` from `core/json_utils` in hiveflow/core/agent.py
- [x] T010 <!-- bd:hiveflow-jox.10 --> [US2] Wire `CostTracker` into `ResilientLLMProvider` to record usage per LLM call, and populate `ResultPayload.cost_summary` with `WorkflowCostReport` at workflow completion in hiveflow/core/agent.py
- [x] T011 <!-- bd:hiveflow-jox.11 --> [P] [US2] Create `ActionQueue` class with `asyncio.Semaphore` concurrency control, `asyncio.wait_for` timeout, and rollback-on-failure support per contract in hiveflow/core/action_queue.py
- [x] T012 <!-- bd:hiveflow-jox.12 --> [US2] Integrate `ActionQueue` into action executor behavior type (`_execute_action_executor`) using config defaults (`ACTION_TIMEOUT`, `ENABLE_ROLLBACK`, `DEFAULT_ACTION_POLICY`) in hiveflow/core/agent.py
- [x] T013 <!-- bd:hiveflow-jox.13 --> [P] [US2] Write resilience integration tests: fallback chain cascade, circuit breaker state transitions, rate limiting throttle, JSON parse recovery, cost tracking accumulation in tests/test_resilience_integration.py
- [x] T014 <!-- bd:hiveflow-jox.14 --> [P] [US2] Write ActionQueue unit tests: concurrent execution, timeout behavior, rollback on failure, drain semantics in tests/test_action_queue.py

**Checkpoint**: Agents automatically recover from transient LLM failures. Cost data appears in results. Action queue controls side effects.

---

## Phase 5: User Story 3 — Prompt Template Library Usage (Priority: P2)

**Goal**: Extend `PromptTemplate` with dotted-path variable resolution, prompt families (Default/Granite/Local), and add 13 new categorized prompt templates to the library.

**Independent Test**: Load a template, substitute dotted-path variables from mock state, verify output. Switch model family and verify prompt variant selection.

### Implementation for User Story 3

- [x] T015 <!-- bd:hiveflow-jox.15 --> [US3] Add `PromptFamily` enum
- [x] T016 <!-- bd:hiveflow-jox.16 --> [US3] Add `PromptCategory` enum
- [x] T017 <!-- bd:hiveflow-jox.17 --> [US3] Implement `resolve_dotted_path(obj, path)`
- [x] T018 <!-- bd:hiveflow-jox.18 --> [US3] Update `PromptTemplate` to add
- [x] T019 <!-- bd:hiveflow-jox.19 --> [US3] Add 13 new categorized prompt templates
- [x] T020 <!-- bd:hiveflow-jox.20 --> [P] [US3] Write prompt template tests: dotted-path resolution (nested dict, object attrs, missing path warning), family auto-detection, category filtering, all 15 categories present in tests/test_prompt_templates.py

**Checkpoint**: All 15 prompt categories available. Dotted-path variables resolve correctly. Family auto-selection works.

---

## Phase 6: User Story 4 — Real-Time Workflow Monitoring (Priority: P2)

**Goal**: Extend streaming protocol with missing event types, structured metadata, paired executor events, and a JSON-lines audit log writer.

**Independent Test**: Run a workflow with a stream subscriber, verify EXECUTOR_INVOKED/EXECUTOR_COMPLETED events with correct metadata. Check JSON-lines file is written.

### Implementation for User Story 4

- [x] T021 <!-- bd:hiveflow-jox.21 --> [US4] Add 9 new `StreamEventType` enum values (`LOG`, `HUMAN_REQUEST`, `COST`, `ROLLBACK`, `SUMMARY_GENERATED`, `OUTLINE_GENERATED`, `ASSEMBLY_COMPLETE`, `EXECUTOR_INVOKED`, `EXECUTOR_COMPLETED`) in hiveflow/core/streaming.py
- [x] T022 <!-- bd:hiveflow-jox.22 --> [US4] Create `EventMetadata` pydantic model (`tokens_used`, `latency_ms`, `model`, `cost_usd`) and add `step_id`, `content`, `metadata`, `timestamp` fields to `StreamEvent` in hiveflow/core/streaming.py
- [x] T023 <!-- bd:hiveflow-jox.23 --> [US4] Create `JsonLinesWriter` async subscriber class that writes `StreamEvent` as JSON lines to `{OUTPUT_DIR}/events-{YYYY-MM-DD}.jsonl` using `aiofiles` in hiveflow/core/streaming.py
- [x] T024 <!-- bd:hiveflow-jox.24 --> [US4] Emit paired `EXECUTOR_INVOKED` (with input state) and `EXECUTOR_COMPLETED` (with output and metadata) events in `Agent.execute()` before and after core logic in hiveflow/core/agent.py
- [x] T025 <!-- bd:hiveflow-jox.25 --> [US4] Wire `JsonLinesWriter` into `StreamChannel` subscriber list during workflow startup when `OUTPUT_DIR` is configured in hiveflow/core/workflow.py
- [x] T026 <!-- bd:hiveflow-jox.26 --> [P] [US4] Write streaming protocol tests: all 26 event types instantiable, EventMetadata fields, JsonLinesWriter file creation and content, paired executor events in tests/test_streaming_protocol.py

**Checkpoint**: Every agent step emits paired observability events. Audit log file is written automatically.

---

## Phase 7: User Story 5 — Recursive Multi-Level Exploration (Priority: P3)

**Goal**: Wrap `DeepResearcher` as an `OrchestratorAgent` that participates in the agent registry/workflow graph and reports progress via stream events.

**Independent Test**: Configure orchestrator with breadth=2, depth=2, run against mock research function, verify sub-task spawning, depth limits, result merging, and progress reporting.

### Implementation for User Story 5

- [x] T027 <!-- bd:hiveflow-jox.27 --> [US5] Create `OrchestratorAgent` class that delegates to `DeepResearcher`, implements `execute(state) -> AgentResult`, maps callbacks to stream events, and includes `get_progress() -> float` in hiveflow/core/orchestrator.py
- [x] T028 <!-- bd:hiveflow-jox.28 --> [US5] Register `OrchestratorAgent` as an agent type in the agent registry so it can be referenced from team configurations in hiveflow/core/registry.py
- [x] T029 <!-- bd:hiveflow-jox.29 --> [P] [US5] Write orchestrator agent tests: recursive depth limits, breadth sub-task count, concurrent branch execution, progress percentage reporting, result merging in tests/test_orchestrator_agent.py

**Checkpoint**: Recursive exploration available as a workflow agent. Progress reported via stream events.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Finalize exports, documentation, and validate end-to-end.

- [x] T030 <!-- bd:hiveflow-jox.30 --> [P] Update `hiveflow/core/__init__.py` exports to include new public classes (`ResilientLLMProvider`, `ActionQueue`, `OrchestratorAgent`, `JsonLinesWriter`, `EventMetadata`, `PromptFamily`, `PromptCategory`)
- [x] T031 <!-- bd:hiveflow-jox.31 --> [P] Update CHANGELOG.md with all feature additions (config fields, resilience integration, prompt library expansion, streaming protocol, orchestrator agent)
- [x] T032 <!-- bd:hiveflow-jox.32 --> Run full test suite (`uv run pytest tests/ --ignore=tests/test_api.py --ignore=tests/test_api_documents.py --ignore=tests/test_markitdown_loader.py --ignore=tests/test_observability.py`) and fix any regressions
- [x] T033 <!-- bd:hiveflow-jox.33 --> Validate quickstart.md examples compile and execute correctly against the implemented code

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 — BLOCKS all user stories
- **US1 — Configuration (Phase 3)**: Depends on Phase 2. No other story dependencies.
- **US2 — Resilience (Phase 4)**: Depends on Phase 3 (needs ACTION_TIMEOUT, ENABLE_ROLLBACK config fields)
- **US3 — Prompts (Phase 5)**: Depends on Phase 2 only. Can run in parallel with US1/US2.
- **US4 — Streaming (Phase 6)**: Depends on Phase 2 only. Can run in parallel with US1/US2/US3. Note: T024 modifies `agent.py` (also modified by US2), so if running in parallel, merge carefully.
- **US5 — Recursive (Phase 7)**: Depends on Phase 2 only. Can run in parallel with other stories.
- **Polish (Phase 8)**: Depends on all desired user stories being complete.

### User Story Dependencies

```
Phase 1 (Setup)
    │
Phase 2 (Foundational)
    │
    ├─── Phase 3: US1 Configuration (P1) ──── Phase 4: US2 Resilience (P1)
    │                                                   │
    ├─── Phase 5: US3 Prompts (P2) ────────────────────┤
    │                                                   │
    ├─── Phase 6: US4 Streaming (P2) ──────────────────┤
    │                                                   │
    └─── Phase 7: US5 Recursive (P3) ──────────────────┘
                                                        │
                                                  Phase 8 (Polish)
```

### Within Each User Story

- Models/enums before logic that uses them
- Core implementation before integration with agent.py
- Tests can be written in parallel with implementation (separate files)
- Story complete = checkpoint passes

### Parallel Opportunities

**Across stories** (with separate developers):
- US3 (Prompts) can run fully in parallel with US1+US2 — touches only `prompts.py`
- US4 (Streaming) can run mostly in parallel — touches `streaming.py` and `workflow.py` independently, but shares `agent.py` with US2
- US5 (Recursive) can run fully in parallel — touches only new `orchestrator.py` and `registry.py`

**Within stories** (tasks marked [P]):
- US1: T005 (tests) in parallel with T002–T004 (implementation)
- US2: T007 (resilient_provider.py) + T011 (action_queue.py) + T013/T014 (tests) all in parallel
- US3: T020 (tests) in parallel with T015–T019 (implementation)
- US4: T026 (tests) in parallel with T021–T025 (implementation)
- US5: T029 (tests) in parallel with T027–T028 (implementation)

---

## Parallel Example: User Story 2 (Resilience)

```text
# These can run simultaneously (different files):
T007: Create ResilientLLMProvider in hiveflow/core/resilient_provider.py
T011: Create ActionQueue in hiveflow/core/action_queue.py
T013: Write resilience integration tests in tests/test_resilience_integration.py
T014: Write action queue tests in tests/test_action_queue.py

# Then sequentially (same file - agent.py):
T008: Integrate ResilientLLMProvider into Agent
T009: Replace json.loads with parse_json_resilient
T010: Wire CostTracker
T012: Integrate ActionQueue into action executor
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup — verify baseline
2. Complete Phase 3: US1 — extend config with 8 new fields
3. **STOP and VALIDATE**: Test config precedence independently
4. This alone delivers value: all config categories are configurable

### Incremental Delivery

1. Setup → US1 (Configuration) → **MVP: All settings configurable**
2. Add US2 (Resilience) → **Production-ready: Workflows survive failures**
3. Add US3 (Prompts) → **Better agents: Structured prompt library**
4. Add US4 (Streaming) → **Observable: Full audit trail**
5. Add US5 (Recursive) → **Advanced: Deep exploration capability**
6. Each increment is independently valuable and testable

### Parallel Team Strategy

With multiple developers after Setup completes:
- **Developer A**: US1 → US2 (sequential — US2 needs US1 config fields)
- **Developer B**: US3 (Prompts — fully independent)
- **Developer C**: US4 (Streaming — mostly independent, merge agent.py carefully)
- **Developer D**: US5 (Recursive — fully independent)

---

## Notes

- [P] tasks = different files, no dependencies on incomplete tasks in same phase
- [Story] labels map tasks to user stories for traceability
- All new config fields have defaults preserving existing behavior (§2.5 backward compatibility)
- Existing resilience modules are COMPLETE — tasks focus on integration, not reimplementation
- `agent.py` is modified by US2 (resilience wrapper, JSON parsing, cost) and US4 (executor events) — if running in parallel, coordinate merges
- Total: 33 tasks across 8 phases
