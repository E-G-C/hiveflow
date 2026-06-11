# Feature Specification: MCP Integration & Conversational Memory

**Feature Branch**: `007-mcp-memory-integrations`
**Created**: 2026-02-25
**Status**: Draft
**Input**: Requirements document `requirements/06-integrations.md` — MCP Integration (Model Context Protocol) and Conversational Memory building blocks.

## Clarifications

### Session 2026-02-25

- Q: Should MCP tool IDs be simple (`mcp:{tool}`), always server-qualified (`mcp:{server}/{tool}`), or hybrid (qualify only on collision)? → A: Always server-qualified (`mcp:{server}/{tool}`). Prevents surprises when adding servers and avoids breaking ID renames on collision.
- Q: When are MCP server connections established — eager (at workflow start), lazy (on first tool use), or configurable? → A: Configurable. Default eager (connect at workflow start for fail-fast diagnostics), with a per-server `lazy: true` option for deferred connection.
- Q: When are stdio MCP server processes started and stopped — per-workflow, shared across runs, or per-tool-call? → A: Per-workflow. Spawned at workflow start (or first use if lazy), terminated when workflow completes or fails. Prevents orphan processes and matches the existing workflow-scoped session lifecycle.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Connect External Tools via MCP (Priority: P1)

A framework developer configures one or more MCP tool servers (local CLI tools or remote services) so that agents in their workflows can discover and use those external tools alongside built-in tools, without writing custom tool plugin code.

**Why this priority**: This is the core value proposition of MCP integration. Without it, every external tool requires a hand-coded plugin. MCP eliminates that friction and is the foundation for all other MCP features.

**Independent Test**: Can be fully tested by configuring an MCP server in a config file, running a workflow that references an MCP tool, and verifying the agent successfully calls the tool and receives results.

**Acceptance Scenarios**:

1. **Given** an MCP server is configured with the `stdio` transport, **When** the framework starts a workflow referencing an MCP tool, **Then** the framework spawns the server process, discovers its tools, and the agent can invoke them by name.
2. **Given** an MCP server is configured with the `http` transport, **When** the framework starts a workflow, **Then** it connects to the remote server, discovers tools, and agents can invoke them.
3. **Given** MCP is configured with `strategy: "disabled"`, **When** a workflow runs, **Then** no MCP servers are contacted and only built-in tools are available.
4. **Given** an MCP server is unreachable or returns an error during discovery, **When** the framework starts, **Then** workflow execution is not blocked, the failure is logged, and remaining servers and native tools remain available.

---

### User Story 2 — Use MCP Tools Transparently in Team Configs (Priority: P1)

A developer defines a team configuration that mixes built-in tools and MCP tools in the same agent. The agent discovers and uses all tools through a single, unified interface without distinguishing between sources.

**Why this priority**: Transparent coexistence is essential for MCP to be useful in practice. Developers should not have to change agent logic or team composition patterns to use MCP tools.

**Independent Test**: Can be fully tested by creating a team config that assigns both a native tool and an MCP tool to the same agent, running the workflow, and confirming both tools are called successfully.

**Acceptance Scenarios**:

1. **Given** a team config assigns `["web_search", "mcp:company_db/query"]` to an agent, **When** the agent runs, **Then** both tools appear in the agent's tool list and can be invoked.
2. **Given** an MCP tool has the same base name as a native tool (e.g., both named `search`), **When** tools are registered, **Then** the MCP tool uses the server-qualified format `mcp:{server}/search` preventing collision, and both tools are available.
3. **Given** an MCP tool is referenced in a team config but the MCP server is not configured, **When** agent construction occurs, **Then** a clear error is raised identifying the missing tool.

---

### User Story 3 — LLM-Assisted Tool Selection for Complex Tasks (Priority: P2)

When many MCP tools are available across multiple servers, a developer enables "deep" mode so the framework automatically selects the most relevant tools for each task, reducing noise and improving agent performance.

**Why this priority**: Valuable for power users with large MCP server fleets, but not required for initial MCP adoption. Most users will start with a small number of known tools.

**Independent Test**: Can be tested by configuring multiple MCP servers with many tools, enabling deep mode, running a task, and verifying that only a relevant subset of tools is injected into the agent.

**Acceptance Scenarios**:

1. **Given** deep mode is enabled and 50+ MCP tools are available, **When** a task is submitted, **Then** the framework narrows the tool set to fewer than 15 relevant tools before injecting them into the agent.
2. **Given** deep mode is enabled, **When** the task description changes between runs, **Then** different subsets of tools are selected based on task relevance.
3. **Given** deep mode selection fails (e.g., the LLM returns an invalid response), **Then** the framework falls back to fast mode (inject all tools) and logs a warning.

---

### User Story 4 — Checkpoint Persistence of team_config and task (Priority: P2)

A developer running workflows that pause at approval gates can restart the host process and resume the workflow entirely from the checkpoint file, without the original in-memory session being available.

**Why this priority**: Addresses a known gap in the current checkpoint system where `team_config` and `task` are not written to the checkpoint file. This makes cold-resume (process crash recovery) reliable.

**Independent Test**: Can be tested by running a workflow that pauses at a human gate, terminating the process, restarting, and successfully resuming the workflow from the checkpoint file alone.

**Acceptance Scenarios**:

1. **Given** a workflow pauses at a gated step and a checkpoint is saved, **When** the process is restarted and resume is called with only the session ID, **Then** the workflow resumes with the correct team configuration and task, even if the in-memory session is gone.
2. **Given** a checkpoint is loaded that contains `team_config` and `task`, **When** both the session object and checkpoint contain team configs, **Then** the session's config takes precedence (backward-compatible behavior).

---

### User Story 5 — Expose Workflows as MCP Tools (Priority: P3)

An organization runs HiveFlow as a service and wants other MCP-capable applications (IDE assistants, chat interfaces, automation platforms) to trigger HiveFlow workflows as if they were standard MCP tools.

**Why this priority**: This reverses the integration direction — HiveFlow becomes a tool provider. Valuable for platform teams but requires MCP client functionality to be stable first.

**Independent Test**: Can be tested by starting the HiveFlow MCP server, connecting an external MCP client, and invoking a registered workflow.

**Acceptance Scenarios**:

1. **Given** HiveFlow is running as an MCP server with a team registered, **When** an external MCP client requests the tool list, **Then** the team appears as an invocable tool with the correct input/output schema.
2. **Given** an external client invokes a HiveFlow workflow via MCP, **When** the workflow completes, **Then** the result is returned to the client in MCP-compliant format.
3. **Given** an external client invokes a workflow that requires human approval, **When** the workflow pauses, **Then** the MCP server returns a pending status and the client can poll for completion.

---

### Edge Cases

- What happens when an MCP server disconnects mid-tool-call? The framework returns a tool execution error to the agent, allowing it to retry or proceed without that tool's output.
- What happens when an MCP server exposes zero tools? The server is logged as connected but empty; no tools are registered and no error is raised.
- What happens when the `mcp.json` config file is missing or malformed? If `strategy` is not `"disabled"`, a clear configuration error is raised at startup. If the file is simply absent and no `HIVEFLOW_MCP_CONFIG` env var is set, MCP is treated as disabled.
- What happens when two MCP servers expose a tool with the same name? Both are registered with server-qualified IDs (e.g., `mcp:serverA/search` and `mcp:serverB/search`). Since all MCP tool IDs always include the server name, this is handled by default with no special collision logic.
- What happens when a checkpoint file is corrupted? The existing behavior is preserved: `CheckpointError` is raised with a descriptive message, and the resume attempt fails gracefully.
- What happens when a workflow fails or is interrupted while stdio MCP server processes are running? The framework terminates all spawned stdio processes as part of workflow cleanup, preventing orphan processes.

## Requirements *(mandatory)*

### Functional Requirements

**MCP Client — Core (Phase 1):**

- **FR-001**: The framework MUST support connecting to MCP servers via two transport modes: `stdio` (spawn a local process) and `http` (connect to a remote URL via HTTP with Server-Sent Events).
- **FR-002**: The framework MUST discover all tools exposed by connected MCP servers and register each as an individual tool instance in the existing tool registry.
- **FR-003**: Each MCP tool MUST be wrapped so that it conforms to the existing tool plugin contract: unique identifier, description, input schema, output schema, execute method, and LLM tool spec generation.
- **FR-004**: MCP tool identifiers MUST use the format `mcp:{server}/{tool}` (e.g., `mcp:jira/search`), where `{server}` is the configured server name and `{tool}` is the tool name from that server. This always-qualified format prevents name collisions with native tools and between servers, and avoids breaking ID renames if a second server later exposes the same tool name.
- **FR-005**: The framework MUST support three MCP strategy modes: `disabled` (no MCP), `fast` (connect and register all tools), and `deep` (LLM-assisted tool selection).
- **FR-006**: MCP server configuration MUST be stored in a dedicated configuration file, separate from the main framework configuration, because it involves nested structures that do not fit the flat environment variable pattern.
- **FR-007**: The MCP configuration file location MUST be customizable via an environment variable.
- **FR-008**: MCP server configuration MUST support per-server authentication, including bearer token authentication with credentials referenced via environment variables.
- **FR-009**: MCP servers MUST be connected eagerly by default (at workflow start, before agent execution begins). If a server is unreachable during eager connection, the framework MUST log an error and continue — it MUST NOT block workflow execution for the remaining servers and native tools. Servers configured with `lazy: true` MUST defer connection until an agent first references one of their tools.
- **FR-010**: The MCP strategy MUST be overridable at the team configuration level, allowing different workflows to use different strategies.
- **FR-010a**: For `stdio` transport servers, the spawned process lifetime MUST be scoped to the workflow run. The process is started at workflow start (or on first tool reference if `lazy: true`) and terminated when the workflow completes or fails. The framework MUST ensure cleanup even on unexpected workflow failures.

**MCP Deep Mode (Phase 2):**

- **FR-011**: In deep mode, the framework MUST fetch the full tool catalog from all connected MCP servers, pass it to a fast-tier LLM along with the task description, and inject only the LLM-selected subset of tools into the agent.
- **FR-012**: If LLM-based tool selection fails, the framework MUST fall back to fast mode behavior and log a warning.

**MCP Gateway — HiveFlow as MCP Server (Phase 2):**

- **FR-013**: The framework MUST provide an optional, separately installable package that exposes registered workflows as MCP-compliant tools for external MCP clients.
- **FR-014**: Each team registered in the team template library MUST appear as an invocable MCP tool with an auto-generated input/output schema.

**Checkpoint Enhancement:**

- **FR-015**: The checkpoint save operation MUST persist `team_config` and `task` into the checkpoint file, so that workflows can be resumed from a cold start (no in-memory session) using only the checkpoint data.
- **FR-016**: On resume, the in-memory session's `team_config` MUST take precedence over the checkpoint's `team_config` to maintain backward compatibility.

### Key Entities

- **MCP Server Definition**: A configured external tool server with a name, transport type (stdio or http), connection details (URL or command), optional authentication, and an optional `lazy` flag (default false) that defers connection until first tool use.
- **MCP Tool Bridge**: A wrapper that adapts a single MCP server tool into the framework's native tool plugin contract, enabling transparent use by agents.
- **MCP Manager**: A component that reads MCP configuration, establishes connections to configured servers, discovers their tools, and registers them in the tool registry.
- **MCP Configuration**: A dedicated configuration file describing the MCP strategy and list of server definitions.
- **Workflow Checkpoint** (existing, enhanced): A persistent snapshot of workflow state at a pause point, now including team configuration and task data for cold-resume support.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A developer can connect an MCP tool server and have its tools available to agents within the same workflow run, with zero changes to agent logic or team composition patterns.
- **SC-002**: 100% of existing workflows that do not use MCP continue to function identically when MCP is set to `disabled` (default) — zero regressions.
- **SC-003**: MCP tool calls complete within the same timeout bounds as native tool calls, plus reasonable network overhead for remote servers (under 2 seconds additional latency for tool discovery).
- **SC-004**: A workflow that pauses at a gated step can be resumed from only the checkpoint file after a process restart, with team configuration and task correctly restored.
- **SC-005**: In deep mode with 50+ available MCP tools, the LLM-based selection narrows the tool set to fewer than 15 tools relevant to the task, reducing prompt token usage by at least 60% compared to injecting all tools.
- **SC-006**: An external MCP client can discover and invoke HiveFlow workflows as tools and receive structured results (Phase 2).

## Scope & Boundaries

### In Scope

- MCP client supporting stdio and HTTP/SSE transports
- MCP tool wrapping via the existing tool plugin contract
- MCP configuration file format and loading
- Three strategy modes (disabled, fast, deep)
- MCP tool + native tool coexistence in the unified tool registry
- Checkpoint enhancement for team_config and task persistence
- HiveFlow as MCP server (Phase 2, optional package)

### Out of Scope

- Changes to the core tool plugin interface (no new abstract properties like `category`, `reversible`, `requires_approval` — those are tracked in `04-plugins.md`)
- Changes to agent execution logic (agents use tools the same way regardless of source)
- Persistent memory management (application-layer concern, not framework)
- Multi-turn conversation protocol (application-layer concern)
- New embedding providers or vector store backends
- Middleware support on WorkflowEngine (tracked in `04-plugins.md`)
- `ToolRegistry.describe()` method (tracked in `04-plugins.md`; a prerequisite for deep mode, but owned by that spec)

### Assumptions

- The existing tool plugin interface (`plugin_id`, `description`, `input_schema`, `output_schema`, `execute()`, `to_llm_tool_spec()`) is sufficient for wrapping MCP tools without modification.
- The existing tool registry's `register()` method can accept MCP-bridged tools without changes.
- MCP servers conform to the Model Context Protocol specification and expose tools with JSON Schema-compatible input/output schemas.
- The `FAST_LLM` tier defined in the framework configuration is suitable for deep mode tool selection.
- The MCP configuration file uses JSON format, consistent with the existing team configuration and checkpoint file formats.
- Bearer token is the primary authentication method for remote MCP servers; other mechanisms (mTLS, OAuth) may be added later as enhancements.

### Dependencies

- **04-plugins.md — ToolRegistry.describe()**: Required for deep mode (Phase 2) to serialize the combined tool catalog for LLM selection. Deep mode cannot ship until this prerequisite is met.
- **Existing ToolPlugin contract**: MCP tools wrap this interface; any changes to the base contract affect MCP tool bridges.
- **Existing CheckpointStorage protocol**: The checkpoint enhancement must preserve backward compatibility with existing checkpoint files.
