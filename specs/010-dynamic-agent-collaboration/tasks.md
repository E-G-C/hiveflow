# Tasks: Dynamic Agent Collaboration

**Input**: Design documents from `/specs/010-dynamic-agent-collaboration/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: Tests are included per the project constitution (§6.1: "Every public function and class MUST have unit tests").

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **Package**: `hiveflow/` at repository root
- **Tests**: `tests/` at repository root
- Follows existing hiveflow project structure

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Configuration model and runtime core that all user stories depend on

- [x] T001 <!-- bd:hiveflow-882.1 --> Add CollaborationConfig pydantic model to hiveflow/core/schema.py with fields: enabled, max_delegation_depth, max_spawned_agents, allow_recursive_orchestrators, delegation_timeout_seconds, budget_policy, fixed_budget_tokens — including validators (FR-023, FR-024, FR-026)
- [x] T002 <!-- bd:hiveflow-882.2 --> Add optional `collaboration: CollaborationConfig | None` field to TeamConfiguration in hiveflow/core/schema.py (default None, backward compatible)
- [x] T003 <!-- bd:hiveflow-882.3 --> Add global collaboration defaults (COLLABORATION_ENABLED, COLLABORATION_MAX_DEPTH, COLLABORATION_MAX_SPAWNED, COLLABORATION_TIMEOUT) to HiveFlowConfig in hiveflow/core/config.py
- [x] T004 <!-- bd:hiveflow-882.4 --> Add new StreamEventType entries (AGENT_SPAWNED, DELEGATION_STARTED, DELEGATION_COMPLETED, DELEGATION_FAILED, MESSAGE_SENT, PLAN_CREATED) to hiveflow/core/streaming.py

**Checkpoint**: Configuration schema and event types available — collaboration runtime can now be built

---

## Phase 2: Foundational (CollaborationRuntime)

**Purpose**: Core runtime that manages the agent pool, delegation tracking, and budget enforcement. MUST be complete before any user story tool plugins can be implemented.

**CRITICAL**: No user story work can begin until this phase is complete

- [x] T005 <!-- bd:hiveflow-882.5 --> Create CollaborationRuntime class in hiveflow/core/collaboration.py with __init__ accepting CollaborationConfig, initial agents dict, ArchetypeLibrary, ToolRegistry, LLMProvider, LLMConfig, and optional StreamChannel
- [x] T006 <!-- bd:hiveflow-882.6 --> Implement agent pool management in hiveflow/core/collaboration.py: get_agent(), list_agents(), register_agent() methods on CollaborationRuntime
- [x] T007 <!-- bd:hiveflow-882.7 --> Implement auto-selection logic in hiveflow/core/collaboration.py: select_best_agent(task_description) using role/tag keyword matching with fallback threshold (FR-002)
- [x] T008 <!-- bd:hiveflow-882.8 --> Implement DelegationRecord dataclass in hiveflow/core/collaboration.py with fields: delegation_id, task, delegated_by, delegate_to, depth, status, started_at, completed_at, duration_ms, tokens_used, result_summary, error
- [x] T009 <!-- bd:hiveflow-882.9 --> Implement delegation execution in hiveflow/core/collaboration.py: async delegate() method that builds filtered sub-state (FR-008), enforces depth limit (FR-009), enforces timeout via asyncio.wait_for (FR-011), detects self-delegation (FR-012), emits DELEGATION_STARTED/COMPLETED/FAILED events (FR-018), records DelegationRecord
- [x] T010 <!-- bd:hiveflow-882.10 --> Implement BudgetController in hiveflow/core/collaboration.py: budget allocation strategies (inherit_parent, fixed, unlimited), token tracking per delegation chain, BudgetExhaustedError on limit exceeded (FR-019)
- [x] T011 <!-- bd:hiveflow-882.11 --> Implement spawning infrastructure in hiveflow/core/collaboration.py: spawn_from_archetype() and spawn_from_definition() methods that create Agent instances, enforce spawn limit (FR-010), enforce tool scoping to parent tools union archetype tools (FR-027), enforce behavior_type restriction for recursive orchestrators (FR-020), assign unique IDs (FR-006), emit AGENT_SPAWNED event (FR-018)
- [x] T012 <!-- bd:hiveflow-882.12 --> Implement WorkflowEngine integration point in hiveflow/core/workflow.py: when team config has collaboration.enabled=True, create CollaborationRuntime, register pre-configured agents in pool, inject collaboration tools into orchestrator agents, store runtime in state["_collaboration_runtime"]
- [x] T013 <!-- bd:hiveflow-882.13 --> Write unit tests for CollaborationRuntime in tests/test_collaboration.py: test agent pool CRUD, auto-selection, depth checking, spawn limits, budget enforcement, tool scoping, delegation record tracking, event emission

**Checkpoint**: Foundation ready — CollaborationRuntime manages the agent pool, delegation, spawning, and budget enforcement. User story tool plugins can now be implemented.

---

## Phase 3: User Story 1 - Runtime Task Delegation (Priority: P1) MVP

**Goal**: Orchestrator agents can delegate sub-tasks to other agents at runtime and receive results, with depth limits, timeout, and cycle detection.

**Independent Test**: Run an orchestrator agent that delegates a sub-task to an existing team member via the `delegate_task` tool and receives the result incorporated into its output.

### Implementation for User Story 1

- [x] T014 <!-- bd:hiveflow-882.14 --> [US1] Create DelegateTaskTool class in hiveflow/plugins/tools/delegate_task.py implementing ToolPlugin with plugin_id="delegate_task", description, input_schema (task, delegate_to, context, expected_output), output_schema (status, result, agent_id, tokens_used)
- [x] T015 <!-- bd:hiveflow-882.15 --> [US1] Implement DelegateTaskTool.execute() in hiveflow/plugins/tools/delegate_task.py: resolve target agent from runtime agent pool (by ID or auto-select via FR-002), call runtime.delegate() with filtered state, handle depth limit exceeded, handle timeout, handle self-delegation error, handle failure, return structured result dict
- [x] T016 <!-- bd:hiveflow-882.16 --> [US1] Implement fallback agent creation in DelegateTaskTool.execute() in hiveflow/plugins/tools/delegate_task.py: when auto-select finds no match and no suitable agent exists, spawn a default llm_only agent to handle the sub-task (FR-003)
- [x] T017 <!-- bd:hiveflow-882.17 --> [US1] Write unit tests for DelegateTaskTool in tests/test_delegate_task.py: test successful delegation, auto-selection, fallback agent creation, depth limit refusal, timeout handling, self-delegation rejection, failure propagation, event emission
- [x] T018 <!-- bd:hiveflow-882.18 --> [US1] Write integration test for delegation chain in tests/test_collaboration_integration.py: end-to-end test with a real orchestrator delegating to an existing team member, verifying result returned and events emitted
- [x] T018b <!-- bd:hiveflow-882.19 --> [US1] Write test for stateless delegation on resume in tests/test_collaboration_integration.py: simulate a checkpoint during an active delegation, resume the workflow, and verify the delegation restarts from scratch rather than returning stale results (FR-025)

**Checkpoint**: User Story 1 complete — orchestrators can delegate tasks. This is the MVP.

---

## Phase 4: User Story 2 - Dynamic Agent Spawning (Priority: P1)

**Goal**: Orchestrator agents can spawn new specialist agents from archetypes or custom definitions at runtime and delegate tasks to them.

**Independent Test**: Run an orchestrator that calls spawn_agent with an archetype name, receives the new agent ID, then delegates a task to it and gets a result.

### Implementation for User Story 2

- [x] T019 <!-- bd:hiveflow-882.20 --> [US2] Create SpawnAgentTool class in hiveflow/plugins/tools/spawn_agent.py implementing ToolPlugin with plugin_id="spawn_agent", description, input_schema (archetype, custom_definition, agent_id), output_schema (status, agent_id, role, available_tools)
- [x] T020 <!-- bd:hiveflow-882.21 --> [US2] Implement SpawnAgentTool.execute() in hiveflow/plugins/tools/spawn_agent.py: validate archetype exists (list available if not), call runtime.spawn_from_archetype() or runtime.spawn_from_definition(), handle spawn limit exceeded, return spawned agent info including available tools
- [x] T021 <!-- bd:hiveflow-882.22 --> [US2] Implement to_llm_tool_spec() in hiveflow/plugins/tools/spawn_agent.py: include the list of available archetypes from the archetype library in the tool description so the LLM knows what's available
- [x] T022 <!-- bd:hiveflow-882.23 --> [US2] Write unit tests for SpawnAgentTool in tests/test_spawn_agent.py: test archetype spawn, custom definition spawn, spawn limit refusal, unknown archetype error with list, tool scoping enforcement, recursive orchestrator restriction, unique ID assignment
- [x] T023 <!-- bd:hiveflow-882.24 --> [US2] Write integration test for spawn-then-delegate in tests/test_collaboration_integration.py: end-to-end test where orchestrator spawns a researcher from archetype, delegates a task to it, verifies result and ephemeral cleanup

**Checkpoint**: User Stories 1 AND 2 complete — orchestrators can dynamically build their team and delegate. This is the core collaboration MVP.

---

## Phase 5: User Story 3 - Inter-Agent Messaging (Priority: P2)

**Goal**: Agents can send targeted messages and broadcasts to each other, enabling review cycles and richer collaboration beyond delegation.

**Independent Test**: Run two agents in a workflow where one sends a message to the other, and the recipient sees the message in its context during its next execution.

### Implementation for User Story 3

- [x] T024 <!-- bd:hiveflow-882.25 --> [P] [US3] Create SendMessageTool class in hiveflow/plugins/tools/message.py implementing ToolPlugin with plugin_id="send_message", description, input_schema (to, subject, body, requires_response), output_schema (status, message_id, to)
- [x] T025 <!-- bd:hiveflow-882.26 --> [P] [US3] Create ReadMessagesTool class in hiveflow/plugins/tools/message.py implementing ToolPlugin with plugin_id="read_messages", description, input_schema (unread_only), output_schema (messages list, count)
- [x] T026 <!-- bd:hiveflow-882.27 --> [US3] Implement SendMessageTool.execute() in hiveflow/plugins/tools/message.py: create message dict with UUID, store in state["_messages"][to_agent] (or state["_messages"]["_broadcast"]), emit MESSAGE_SENT event (FR-014, FR-015, FR-017, FR-018)
- [x] T027 <!-- bd:hiveflow-882.28 --> [US3] Implement ReadMessagesTool.execute() in hiveflow/plugins/tools/message.py: read messages from state["_messages"][caller_agent_id] and state["_messages"]["_broadcast"], filter by unread_only flag, mark read messages, return formatted list (FR-016)
- [x] T028 <!-- bd:hiveflow-882.29 --> [US3] Extend Agent._summarize_state() in hiveflow/core/agent.py to auto-inject unread messages from state["_messages"][self.agent_id] and state["_messages"]["_broadcast"] as a "Messages" section in the agent's context (FR-017)
- [x] T029 <!-- bd:hiveflow-882.30 --> [US3] Update WorkflowEngine collaboration injection in hiveflow/core/workflow.py to include SendMessageTool and ReadMessagesTool for ALL agents (not just orchestrators) when collaboration is enabled (FR-014 — messaging is not orchestrator-gated)
- [x] T030 <!-- bd:hiveflow-882.31 --> [US3] Write unit tests for messaging tools in tests/test_message.py: test send targeted, send broadcast, read unread, read all, mark-as-read, message format, event emission
- [x] T031 <!-- bd:hiveflow-882.32 --> [US3] Write integration test for message exchange in tests/test_collaboration_integration.py: two-agent workflow where agent A sends a message to agent B, agent B reads it and replies, agent A sees the reply

**Checkpoint**: User Stories 1, 2, AND 3 complete — full delegation, spawning, and messaging.

---

## Phase 6: User Story 4 - Collaborative Task Planning (Priority: P2)

**Goal**: Orchestrator agents can decompose complex tasks into dependency-ordered sub-task plans with agent assignments and execute them with concurrent independent sub-tasks.

**Independent Test**: Give an orchestrator a multi-part task, verify it produces a structured plan, executes sub-tasks respecting dependencies, runs independent tasks concurrently, and synthesizes results.

### Implementation for User Story 4

- [x] T032 <!-- bd:hiveflow-882.33 --> [US4] Implement TaskPlan and SubTask models in hiveflow/core/collaboration.py: TaskPlan with plan_id, created_by, sub_tasks list; SubTask with id, description, assigned_to, depends_on, expected_output, status, result — including DAG validation (no cycles in depends_on)
- [x] T033 <!-- bd:hiveflow-882.34 --> [US4] Implement plan execution logic in hiveflow/core/collaboration.py: async execute_plan() method on CollaborationRuntime that topologically sorts sub-tasks, groups independent tasks for concurrent execution via asyncio.gather, delegates each sub-task, tracks status, handles failures, emits PLAN_CREATED event (FR-021, FR-022)
- [x] T034 <!-- bd:hiveflow-882.35 --> [US4] Create PlanAndExecuteTool class in hiveflow/plugins/tools/delegate_task.py (or separate file) implementing ToolPlugin with plugin_id="plan_and_execute", input_schema (plan with sub_tasks array), that calls runtime.execute_plan() and returns synthesized results
- [x] T035 <!-- bd:hiveflow-882.36 --> [US4] Write unit tests for task planning in tests/test_collaboration.py: test plan creation, DAG validation (reject cycles), topological sort, concurrent grouping, sub-task status tracking, failure handling, re-delegation
- [x] T036 <!-- bd:hiveflow-882.37 --> [US4] Write integration test for plan-and-execute in tests/test_collaboration_integration.py: orchestrator receives a complex task, produces a plan with 3+ sub-tasks (some parallel, some dependent), executes it, and returns synthesized output

**Checkpoint**: All 4 user stories complete — full dynamic agent collaboration system.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Quality, observability, documentation, and backward compatibility validation

- [x] T037 <!-- bd:hiveflow-882.38 --> [P] Add collaboration configuration to the existing team config validation in hiveflow/core/schema.py: validate workflow_references accounts for dynamically spawned agents gracefully (no false errors)
- [x] T038 <!-- bd:hiveflow-882.39 --> [P] Add structured logging for all collaboration operations in hiveflow/core/collaboration.py using structlog: spawn events, delegation start/end, message delivery, budget warnings
- [x] T039 <!-- bd:hiveflow-882.40 --> [P] Write backward compatibility test in tests/test_collaboration_integration.py: run an existing workflow WITHOUT collaboration config and verify behavior is unchanged (SC-010)
- [x] T039b <!-- bd:hiveflow-882.41 --> Write budget exhaustion integration test in tests/test_collaboration_integration.py: configure a fixed token budget, run a delegation chain that exceeds it, verify BudgetExhaustedError is raised, workflow terminates gracefully, and events are recorded (SC-009, FR-019)
- [x] T040 <!-- bd:hiveflow-882.42 --> Run full test suite (uv run pytest) and fix any regressions across all existing tests
- [x] T041 <!-- bd:hiveflow-882.43 --> Run quickstart.md validation: create a sample team config with collaboration enabled per quickstart.md and verify it loads and validates correctly

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 — BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Phase 2 — delegation tools
- **User Story 2 (Phase 4)**: Depends on Phase 2 — spawning tools (can run in parallel with US1)
- **User Story 3 (Phase 5)**: Depends on Phase 2 — messaging tools (can run in parallel with US1/US2)
- **User Story 4 (Phase 6)**: Depends on Phase 3 (delegation) and Phase 4 (spawning) — composes both
- **Polish (Phase 7)**: Depends on all user story phases

### User Story Dependencies

- **User Story 1 (P1 - Delegation)**: Depends on Phase 2 only — no dependencies on other stories
- **User Story 2 (P1 - Spawning)**: Depends on Phase 2 only — no dependencies on other stories (can parallel with US1)
- **User Story 3 (P2 - Messaging)**: Depends on Phase 2 only — no dependencies on other stories (can parallel with US1/US2)
- **User Story 4 (P2 - Planning)**: Depends on US1 (delegation) + US2 (spawning) — composes both into plan-and-execute

### Within Each User Story

- Tool class creation before execute() implementation
- execute() before tests (tests validate the implementation)
- Core implementation before integration tests

### Parallel Opportunities

- Phase 1 tasks T001-T004 are sequential (same files), but scoped and fast
- Phase 2 tasks T005-T011 are mostly sequential (same file: collaboration.py)
- T012 (workflow.py) can run in parallel with T005-T011
- Phase 3 (US1), Phase 4 (US2), Phase 5 (US3) can all start in parallel after Phase 2
- Within US3: T024 and T025 are [P] — different tool classes in the same file but independent sections
- Phase 7 tasks T037, T038, T039 are [P] — different files

---

## Parallel Example: After Phase 2 Completes

```text
# These three user stories can start in parallel (different files):
Story 1: T014-T018 → hiveflow/plugins/tools/delegate_task.py + tests/test_delegate_task.py
Story 2: T019-T023 → hiveflow/plugins/tools/spawn_agent.py + tests/test_spawn_agent.py
Story 3: T024-T031 → hiveflow/plugins/tools/message.py + tests/test_message.py + agent.py mod
```

---

## Implementation Strategy

### MVP First (User Stories 1 + 2)

1. Complete Phase 1: Setup (T001-T004)
2. Complete Phase 2: Foundational (T005-T013)
3. Complete Phase 3: User Story 1 — Delegation (T014-T018)
4. Complete Phase 4: User Story 2 — Spawning (T019-T023)
5. **STOP and VALIDATE**: Test delegation + spawning independently (SC-001, SC-002, SC-003)
6. This delivers the core collaboration value proposition

### Incremental Delivery

1. Setup + Foundational → Runtime infrastructure ready
2. Add US1 (Delegation) → Test independently → Validates SC-001, SC-003, SC-005
3. Add US2 (Spawning) → Test independently → Validates SC-002, SC-006
4. Add US3 (Messaging) → Test independently → Validates SC-008
5. Add US4 (Planning) → Test independently → Validates SC-004
6. Polish → Validates SC-007, SC-009, SC-010
7. Each story adds value without breaking previous stories

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- All new code in hiveflow/core/collaboration.py uses async-first pattern (§5.4)
- No new external dependencies required — uses existing pydantic, structlog, asyncio
- Avoid: vague tasks, same file conflicts, cross-story dependencies that break independence
