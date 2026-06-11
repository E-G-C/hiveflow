# Tasks: MCP Integration & Conversational Memory

**Input**: Design documents from `/specs/007-mcp-memory-integrations/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: Tests ARE included as the constitution (S6.1) requires tests for all public functions/classes, and the spec/plan explicitly call for unit and integration tests.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **Single project**: `hiveflow/` (package), `tests/` at repository root
- New MCP module: `hiveflow/plugins/mcp/`
- Core modifications: `hiveflow/core/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization — add `mcp` optional dependency, create plugin package skeleton

- [x] T001 <!-- bd:hiveflow-7lk.1 --> Add `mcp>=1.26.0` as optional dependency in `pyproject.toml` under a new `mcp` extras group, run `uv lock`
- [x] T002 <!-- bd:hiveflow-7lk.2 --> Create `hiveflow/plugins/mcp/` package with `__init__.py` that conditionally imports MCP components (guards against missing `mcp` package with structlog warning)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story — MCP config models and the tool wiring fix

**CRITICAL**: No user story work can begin until this phase is complete

- [x] T003 <!-- bd:hiveflow-7lk.3 --> Implement MCPAuthConfig, MCPServerDefinition, and MCPConfig pydantic models in `hiveflow/plugins/mcp/config.py` per contracts/mcp_config.py (validators, from_file class method, HIVEFLOW_MCP_CONFIG env var support, default `.hiveflow/mcp.json` path)
- [x] T004 <!-- bd:hiveflow-7lk.4 --> [P] Write unit tests for MCPConfig models in `tests/test_mcp_config.py` — valid configs, transport-specific validation (stdio requires command, http requires url), auth validation, from_file with missing file returns disabled, malformed JSON raises ValueError, duplicate server names rejected
- [x] T005 <!-- bd:hiveflow-7lk.5 --> Add `mcp_strategy: str | None` field to TeamConfiguration in `hiveflow/core/schema.py` with validator restricting values to `None`, `"disabled"`, `"fast"`, `"deep"`
- [x] T006 <!-- bd:hiveflow-7lk.6 --> Fix tool wiring gap in `TeamGenerator.build()` in `hiveflow/core/teams.py` — add `tool_registry: ToolRegistry | None = None` parameter, resolve `agent_def["tools"]` via `tool_registry.get_tools_for_agent()` when registry is provided, pass resolved tools to `Agent()` constructor
- [x] T007 <!-- bd:hiveflow-7lk.7 --> Update `HiveFlow.run()` in `hiveflow/core/hiveflow.py` to pass `self._tool_registry` to `generator.build()` as the new `tool_registry` keyword argument
- [x] T008 <!-- bd:hiveflow-7lk.8 --> [P] Write unit tests for tool wiring in `tests/test_tool_wiring.py` — build() with tool_registry resolves tools, build() without tool_registry still works (backward compat), missing tool ID raises KeyError

**Checkpoint**: Foundation ready — MCPConfig parses, TeamGenerator wires tools, mcp_strategy field available

---

## Phase 3: User Story 1 — Connect External Tools via MCP (Priority: P1) MVP

**Goal**: A developer configures MCP tool servers and agents discover and use their tools alongside native tools, without writing custom plugin code.

**Independent Test**: Configure an MCP server in mcp.json, run a workflow referencing an MCP tool, verify the agent successfully calls the tool.

### Tests for User Story 1

- [x] T009 <!-- bd:hiveflow-7lk.9 --> [P] [US1] Write unit tests for MCPToolBridge in `tests/test_mcp_bridge.py` — plugin_id format, description/input_schema passthrough, execute() with mock call_fn returning TextContent, execute() with isError=True returns error dict, to_llm_tool_spec() returns sanitized name, llm_name property, normalize_call_result for all content types
- [x] T010 <!-- bd:hiveflow-7lk.10 --> [P] [US1] Write unit tests for MCPManager in `tests/test_mcp_manager.py` — startup/shutdown lifecycle with mock MCP sessions, eager server failure logs and continues, disabled strategy is no-op, tool registration in ToolRegistry after startup, is_available returns False when mcp package missing

### Implementation for User Story 1

- [x] T011 <!-- bd:hiveflow-7lk.11 --> [US1] Implement MCPToolBridge(ToolPlugin) in `hiveflow/plugins/mcp/bridge.py` per contracts/mcp_tool_bridge.py — plugin_id as `mcp:{server}/{tool}`, execute() calls call_fn and normalizes result, to_llm_tool_spec() with sanitized name (`mcp_{server}__{tool}`), llm_name property, structlog logging for execute
- [x] T012 <!-- bd:hiveflow-7lk.12 --> [US1] Implement `normalize_call_result()` function in `hiveflow/plugins/mcp/bridge.py` — TextContent, ImageContent, EmbeddedResource, isError handling, empty content
- [x] T013 <!-- bd:hiveflow-7lk.13 --> [US1] Implement MCPManager in `hiveflow/plugins/mcp/manager.py` per contracts/mcp_manager.py — __init__ with AsyncExitStack, startup() connecting eager servers (stdio via `stdio_client`, http via `streamable_http_client`), session.initialize() + list_tools(), MCPToolBridge creation per tool, registration in tool_registry, shutdown() via exit_stack.aclose(), bearer token auth resolution from env var for http transport
- [x] T014 <!-- bd:hiveflow-7lk.14 --> [US1] Implement `_connect_stdio()` in MCPManager (`hiveflow/plugins/mcp/manager.py`) — use `StdioServerParameters(command, args, env)` and `stdio_client()` context manager, push to AsyncExitStack
- [x] T015 <!-- bd:hiveflow-7lk.15 --> [US1] Implement `_connect_http()` in MCPManager (`hiveflow/plugins/mcp/manager.py`) — use `streamable_http_client(url)` context manager, create `httpx.AsyncClient` with bearer token header when auth configured, push to AsyncExitStack
- [x] T016 <!-- bd:hiveflow-7lk.16 --> [US1] Implement `ensure_server()` for lazy server connections in MCPManager (`hiveflow/plugins/mcp/manager.py`) — connect on first tool use, raise MCPConnectionError on failure (unlike startup which skips)
- [x] T017 <!-- bd:hiveflow-7lk.17 --> [US1] Implement MCPConnectionError and MCPToolExecutionError exception classes in `hiveflow/plugins/mcp/manager.py` per contracts/mcp_manager.py
- [x] T018 <!-- bd:hiveflow-7lk.18 --> [US1] Integrate MCPManager into `HiveFlow.run()` in `hiveflow/core/hiveflow.py` — load MCPConfig.from_file(), resolve effective strategy (team_config.mcp_strategy or mcp_config.strategy), create MCPManager when not disabled, call startup(task) before build(), shutdown() in finally block
- [x] T019 <!-- bd:hiveflow-7lk.19 --> [US1] Update Agent `_tool_map` construction in `hiveflow/core/agent.py` to map both `plugin_id` and `llm_name` (if tool has `llm_name` attribute) to the same tool instance, so LLM tool calls using sanitized names dispatch correctly
- [x] T020 <!-- bd:hiveflow-7lk.20 --> [US1] Update `hiveflow/plugins/mcp/__init__.py` exports — expose MCPToolBridge, MCPManager, MCPConfig, MCPConnectionError, MCPToolExecutionError; guard imports with try/except for missing `mcp` package
- [x] T021 <!-- bd:hiveflow-7lk.21 --> [US1] Write integration test in `tests/test_mcp_manager.py` — test full MCPManager lifecycle with a mock stdio MCP server (mock subprocess), verify tools are discovered, registered, callable, and cleaned up on shutdown

**Checkpoint**: At this point, User Story 1 should be fully functional — MCP servers connect, tools are discovered and registered, agents can call them

---

## Phase 4: User Story 2 — Use MCP Tools Transparently in Team Configs (Priority: P1)

**Goal**: A developer mixes native and MCP tools in the same agent via team configuration, and both work through a unified interface.

**Independent Test**: Create a team config assigning both native and MCP tools to one agent, run the workflow, confirm both tools are callable.

### Tests for User Story 2

- [x] T022 <!-- bd:hiveflow-7lk.22 --> [P] [US2] Write integration test in `tests/test_tool_wiring.py` — build a team config with `["web_search", "mcp:local_tools/file_read"]`, register a mock native tool and MCPToolBridge in ToolRegistry, call build(), verify agent has both tools in _tool_map (including sanitized LLM name mapping)

### Implementation for User Story 2

- [x] T023 <!-- bd:hiveflow-7lk.23 --> [US2] Verify and test that name collision between native tool `search` and MCP tool `mcp:serverA/search` are handled — both should coexist in ToolRegistry and agent _tool_map since they have different plugin_ids. Add explicit test case in `tests/test_tool_wiring.py`
- [x] T024 <!-- bd:hiveflow-7lk.24 --> [US2] Verify that referencing an MCP tool from an unconfigured server (e.g., `mcp:missing/tool` not in registry) produces a clear KeyError from `get_tools_for_agent()` with available tool IDs listed. Add test case in `tests/test_tool_wiring.py`

**Checkpoint**: At this point, User Stories 1 AND 2 should both work — MCP tools and native tools coexist transparently

---

## Phase 5: User Story 3 — LLM-Assisted Tool Selection (Priority: P2)

**Goal**: When many MCP tools are available, deep mode uses a fast-tier LLM to select only the most relevant subset for the task.

**Independent Test**: Configure multiple MCP servers with many tools, enable deep mode, run a task, verify only a relevant subset is injected.

**Dependency**: Requires `ToolRegistry.describe()` from 04-plugins.md. This phase implements the framework plumbing and LLM selection logic, but may need a temporary `describe()` implementation or stub until that prerequisite ships.

### Tests for User Story 3

- [x] T025 <!-- bd:hiveflow-7lk.25 --> [P] [US3] Write unit tests for deep mode selection in `tests/test_mcp_manager.py` — mock LLM response selecting subset of tools, verify unselected tools are not in registry, fallback to fast mode on LLM failure, verify warning logged on fallback

### Implementation for User Story 3

- [x] T026 <!-- bd:hiveflow-7lk.26 --> [US3] Implement `_run_deep_selection()` in MCPManager (`hiveflow/plugins/mcp/manager.py`) — serialize tool catalog, call FAST_LLM with task description and catalog, parse selected tool IDs, unregister non-selected tools from registry, fallback to fast mode on any failure
- [x] T027 <!-- bd:hiveflow-7lk.27 --> [US3] Wire deep mode trigger in MCPManager.startup() (`hiveflow/plugins/mcp/manager.py`) — after all servers connected, if strategy is "deep", call _run_deep_selection(task)

**Checkpoint**: Deep mode functional — LLM selects relevant tools from large catalogs

---

## Phase 6: User Story 4 — Checkpoint Persistence of team_config and task (Priority: P2)

**Goal**: Workflows that pause at gates persist enough data in the checkpoint file for cold-resume without the original in-memory session.

**Independent Test**: Run a workflow that pauses at a gate, terminate the process, restart, resume from checkpoint file alone.

### Tests for User Story 4

- [x] T028 <!-- bd:hiveflow-7lk.28 --> [P] [US4] Write unit tests for enhanced checkpoint in `tests/test_checkpoint_enhanced.py` — _save_checkpoint() persists team_config and task, resume loads them from checkpoint, session team_config takes precedence over checkpoint, backward compat with old checkpoint files (missing team_config/task)

### Implementation for User Story 4

- [x] T029 <!-- bd:hiveflow-7lk.29 --> [US4] Update `_save_checkpoint()` in `hiveflow/core/workflow.py` to accept and persist `team_config: dict[str, Any]` and `task: str` parameters into the WorkflowCheckpoint
- [x] T030 <!-- bd:hiveflow-7lk.30 --> [US4] Update all callers of `_save_checkpoint()` in `hiveflow/core/workflow.py` to pass `team_config` and `task` values — WorkflowEngine needs access to these (store in __init__ or pass via run())
- [x] T031 <!-- bd:hiveflow-7lk.31 --> [US4] Verify the existing resume fallback chain in `hiveflow/core/hiveflow.py` works correctly with the now-populated checkpoint fields — session team_config takes precedence, checkpoint data used as fallback

**Checkpoint**: Cold-resume works — checkpoint files contain all data needed for full workflow restore

---

## Phase 7: User Story 5 — Expose Workflows as MCP Tools (Priority: P3)

**Goal**: HiveFlow acts as an MCP server, exposing registered workflows as tools for external MCP clients.

**Independent Test**: Start HiveFlow MCP server, connect an external client, discover and invoke a registered workflow.

**Note**: This is a Phase 2 feature implemented as an optional, separately installable package. The scope here is the gateway scaffolding — full implementation may span a follow-up iteration.

### Implementation for User Story 5

- [x] T032 <!-- bd:hiveflow-7lk.32 --> [US5] Design the MCP gateway package structure — determine whether it lives in `hiveflow/plugins/mcp/gateway.py` or as a separate top-level package (e.g., `hiveflow-mcp-server`). Document decision in a comment/docstring.
- [x] T033 <!-- bd:hiveflow-7lk.33 --> [US5] Implement MCP server scaffolding
- [x] T034 <!-- bd:hiveflow-7lk.34 --> [US5] Implement workflow invocation handler
- [x] T035 <!-- bd:hiveflow-7lk.35 --> [P] [US5] Write integration test for MCP gateway

**Checkpoint**: MCP Gateway functional — external MCP clients can discover and invoke HiveFlow workflows

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, cleanup, and validation across all user stories

- [ ] T036 <!-- bd:hiveflow-7lk.36 --> [P] Update CHANGELOG.md with MCP integration feature summary
- [ ] T037 <!-- bd:hiveflow-7lk.37 --> [P] Update README.md with MCP configuration section (reference quickstart.md examples)
- [ ] T038 <!-- bd:hiveflow-7lk.38 --> [P] Remove any `from __future__ import annotations` if introduced in new files (constitution S5.1 compliance)
- [ ] T039 <!-- bd:hiveflow-7lk.39 --> Run full test suite (`uv run pytest`) and fix any failures
- [ ] T040 <!-- bd:hiveflow-7lk.40 --> Run quickstart.md validation — verify all code examples are consistent with the implementation

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion — BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Foundational — this is the MVP
- **User Story 2 (Phase 4)**: Depends on User Story 1 (uses MCPToolBridge and tool wiring)
- **User Story 3 (Phase 5)**: Depends on User Story 1 (uses MCPManager); independent of User Story 2
- **User Story 4 (Phase 6)**: Depends on Foundational only — INDEPENDENT of MCP stories (can run in parallel with US1)
- **User Story 5 (Phase 7)**: Depends on User Story 1 (uses MCPToolBridge, MCPManager)
- **Polish (Phase 8)**: Depends on all desired user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational — no dependencies on other stories
- **User Story 2 (P1)**: Requires US1 complete (needs MCPToolBridge and registry integration)
- **User Story 3 (P2)**: Requires US1 complete (needs MCPManager and connected servers)
- **User Story 4 (P2)**: Can start after Foundational — INDEPENDENT of MCP stories
- **User Story 5 (P3)**: Requires US1 complete (needs working MCP infrastructure)

### Within Each User Story

- Tests written first (where included)
- Models/entities before services
- Services before integration
- Core implementation before cross-component wiring

### Parallel Opportunities

- **Phase 2**: T004 and T008 (tests) can run in parallel with each other and after their respective implementation tasks
- **Phase 3**: T009 and T010 (tests) can run in parallel
- **Phase 3 + Phase 6**: User Story 1 and User Story 4 can run in parallel after Foundational
- **Phase 4**: T022 can be written while US1 implementation is in progress
- **Phase 5**: T025 can be written while US1/US2 work is in progress
- **Phase 8**: T036, T037, T038 can all run in parallel

---

## Parallel Example: User Story 1

```bash
# Launch both test suites in parallel:
Task: "Write unit tests for MCPToolBridge in tests/test_mcp_bridge.py" (T009)
Task: "Write unit tests for MCPManager in tests/test_mcp_manager.py" (T010)

# After tests, implementation can proceed — T011 and T012 in parallel (both in bridge.py but different functions):
Task: "Implement MCPToolBridge(ToolPlugin) in hiveflow/plugins/mcp/bridge.py" (T011)
# T012 depends on T011 (same file)

# T014 and T015 can run in parallel (independent transport methods):
Task: "Implement _connect_stdio() in MCPManager" (T014)
Task: "Implement _connect_http() in MCPManager" (T015)
```

## Parallel Example: US1 + US4 (Independent Tracks)

```bash
# These two tracks can run fully in parallel after Phase 2:

# Track A: MCP Integration (US1)
Task: T009-T021 (MCPToolBridge, MCPManager, HiveFlow integration)

# Track B: Checkpoint Enhancement (US4)
Task: T028-T031 (checkpoint persistence, resume verification)
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001-T002)
2. Complete Phase 2: Foundational (T003-T008)
3. Complete Phase 3: User Story 1 (T009-T021)
4. **STOP and VALIDATE**: Test MCP connection, tool discovery, and agent tool invocation
5. Deploy/demo if ready — agents can use external tools via MCP

### Incremental Delivery

1. Complete Setup + Foundational -> Foundation ready
2. Add User Story 1 -> Test independently -> MCP works (MVP!)
3. Add User Story 2 -> Test independently -> Mixed tools in team configs
4. Add User Story 4 -> Test independently -> Cold-resume works (can parallel with US2)
5. Add User Story 3 -> Test independently -> Deep mode for large tool catalogs
6. Add User Story 5 -> Test independently -> HiveFlow as MCP server
7. Each story adds value without breaking previous stories

### Parallel Team Strategy

With multiple developers:

1. Team completes Setup + Foundational together
2. Once Foundational is done:
   - Developer A: User Story 1 (MCP core)
   - Developer B: User Story 4 (Checkpoint — independent track)
3. After US1 completes:
   - Developer A: User Story 2 (Transparent coexistence)
   - Developer C: User Story 3 (Deep mode)
4. After US1 stable:
   - Developer D: User Story 5 (MCP Gateway)
5. Stories complete and integrate independently

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Verify tests fail before implementing
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- US4 (Checkpoint) is notably independent — can run on a separate track from all MCP stories
- US5 (Gateway) is P3 and may be deferred to a follow-up iteration
- Deep mode (US3) depends on ToolRegistry.describe() from 04-plugins.md — may need a stub
