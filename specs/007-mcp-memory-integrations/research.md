# Research: MCP Integration & Conversational Memory

**Feature**: 007-mcp-memory-integrations
**Date**: 2026-02-25

---

## R1. MCP Python SDK (`mcp` package)

**Decision**: Use the official `mcp` package (PyPI: `mcp>=1.26.0`).

**Rationale**: Tier 1 official SDK maintained by the Model Context Protocol team. MIT licensed. Requires Python >= 3.10 (compatible with hiveflow's 3.11+). Active development (50+ releases since Nov 2024). Provides async context manager patterns that align with hiveflow's async-first architecture.

**Key details**:
- Package: `mcp>=1.26.0`
- Transports: `stdio`, `sse` (legacy), `streamable_http` (production)
- Client API: `ClientSession` with `initialize()`, `list_tools()`, `call_tool()`
- Stdio: `StdioServerParameters(command, args, env)` + `stdio_client()` context manager
- HTTP: `streamable_http_client(url)` context manager (supersedes legacy `sse_client`)
- Tool spec: `Tool(name, description, inputSchema)` — `inputSchema` is JSON Schema dict
- Tool result: `CallToolResult` with `.content` list of `TextContent | ImageContent | EmbeddedResource`
- Lifecycle: async context managers for connection and session; `AsyncExitStack` for cleanup
- Auth: OAuth support via `OAuthClientProvider`; bearer token via custom `httpx.AsyncClient`

**Alternatives**: No other production-quality MCP Python SDK exists. `modelcontextprotocol` on PyPI is just a CLI scaffolding tool, not a runtime library.

**Note on transport naming**: The spec uses "http" for the transport name. The SDK's `streamable_http_client` is the recommended approach for HTTP-based connections. The older `sse_client` is being superseded. For hiveflow's config, users will write `"transport": "http"` and the framework will use `streamable_http_client` internally.

---

## R2. ToolPlugin Interface Compatibility

**Decision**: MCPToolBridge can implement ToolPlugin without any changes to the base interface.

**Rationale**: The existing `ToolPlugin` abstract base class defines exactly the properties and methods needed to wrap MCP tools:

| ToolPlugin Property/Method | MCP SDK Mapping |
|---|---|
| `plugin_id: str` | `f"mcp:{server_name}/{tool.name}"` |
| `description: str` | `tool.description` |
| `input_schema: dict` | `tool.inputSchema` (already JSON Schema) |
| `output_schema: dict` | `{"type": "object"}` (MCP tools return flexible content) |
| `execute(tool_input) -> dict` | `session.call_tool(tool.name, arguments=tool_input)` |
| `to_llm_tool_spec() -> dict` | Default implementation works (uses plugin_id and input_schema) |

**Key details**:
- `ToolPlugin` lives at `hiveflow/plugins/tools/__init__.py:16-78`
- `ToolRegistry` inherits `PluginRegistry[ToolPlugin]` at `hiveflow/plugins/tools/__init__.py:81-127`
- `ToolRegistry.register()` accepts any `ToolPlugin` instance — no type guards to bypass
- Agent `_tool_map` construction at `agent.py:115-117` indexes by `plugin_id` — MCP tools with `mcp:` prefix integrate transparently
- `to_llm_tool_spec()` default impl at `tools/__init__.py:63-78` uses `self.plugin_id` as `function.name` — the `mcp:server/tool` format is valid as an LLM function name

**Concern**: Some LLM providers may not accept `/` in function names. The MCPToolBridge's `to_llm_tool_spec()` should sanitize the function name for LLM compatibility (e.g., replace `/` with `__`) while keeping `plugin_id` unchanged for registry lookups.

---

## R3. Tool Wiring Gap in TeamGenerator.build()

**Decision**: MCP tool resolution must be addressed alongside the existing tool wiring gap.

**Rationale**: The current `TeamGenerator.build()` at `teams.py:535-680` does NOT resolve `agent_def["tools"]` to `ToolPlugin` instances. Agent definitions in team configs specify tool IDs (e.g., `["web_search", "mcp:jira/search"]`) but `build()` does not pass a `tool_registry` or resolved tools to the `Agent()` constructor.

**Key details**:
- `Agent.__init__` accepts `tools: list[ToolPlugin] | None = None` (agent.py:60)
- `HiveFlow.__init__` accepts `tool_registry: ToolRegistry | None = None` (hiveflow.py:47)
- `HiveFlow.run()` calls `generator.build()` without passing tool_registry (hiveflow.py:131-134)
- The gap exists for ALL tools (native and MCP) — not just MCP tools

**Impact on MCP**: The MCPManager must register MCP tools into the ToolRegistry. Then `build()` must be enhanced to resolve tool IDs from the registry and pass them to agents. This is a prerequisite for MCP tools to function, but it also fixes native tool wiring.

**Approach**: Add `tool_registry: ToolRegistry | None = None` parameter to `TeamGenerator.build()`. When present, resolve `agent_def["tools"]` via `tool_registry.get_tools_for_agent()` and pass to `Agent()`.

---

## R4. MCP Configuration File Design

**Decision**: Use dedicated `mcp.json` at `.hiveflow/mcp.json`, loadable via `HIVEFLOW_MCP_CONFIG` env var.

**Rationale**: MCP config involves nested server definitions with per-server auth, transport details, and optional flags. This does not fit HiveFlowConfig's flat `HIVEFLOW_`-prefixed environment variable pattern. A dedicated JSON file is consistent with how team configs and checkpoint files already use JSON.

**Key details**:
- Default path: `.hiveflow/mcp.json`
- Override: `HIVEFLOW_MCP_CONFIG` environment variable
- Format: `{"strategy": "fast"|"deep"|"disabled", "servers": [...]}`
- Each server: `{name, transport, url|command, args?, env?, auth?, lazy?}`
- Auth: `{"type": "bearer", "env": "TOKEN_VAR_NAME"}` — resolves token from environment variable
- Lazy flag: `lazy: true` defers connection until first tool use (default: `false`)

**Validation**: Use pydantic models for config parsing: `MCPConfig`, `MCPServerDefinition`, `MCPAuthConfig`. This ensures clear error messages on malformed config.

---

## R5. MCP Connection Lifecycle Management

**Decision**: Use `AsyncExitStack` for MCP connection lifecycle, scoped to workflow execution.

**Rationale**: The MCP SDK uses async context managers (`async with stdio_client(...) as (read, write)`, `async with ClientSession(read, write) as session`). These need to stay open for the duration of the workflow so tools can be called at any step. Python's `AsyncExitStack` allows pushing multiple context managers and cleaning them all up in a single `aclose()`.

**Key details**:
- MCPManager creates an `AsyncExitStack` at workflow start
- For each configured server (eager or first-use for lazy):
  1. Enter transport context manager → push to stack
  2. Enter `ClientSession` context manager → push to stack
  3. `session.initialize()` → capability negotiation
  4. `session.list_tools()` → discover tools
  5. Create `MCPToolBridge` per tool → register in ToolRegistry
- At workflow end (or failure): `await exit_stack.aclose()` tears down all connections
- For stdio servers: process is killed when the stdio context manager exits
- For unreachable servers (eager): log error, skip server, continue with remaining
- Cleanup is guaranteed via try/finally in the workflow execution path

**Integration point**: The MCPManager's `startup()` and `shutdown()` methods are called by HiveFlow.run() around the workflow execution.

---

## R6. Checkpoint Enhancement Scope

**Decision**: Minimal change to `_save_checkpoint()` — add `team_config` and `task` fields.

**Rationale**: The `WorkflowCheckpoint` dataclass already has `team_config: dict[str, Any]` and `task: str` fields (checkpoint.py:40-41). The `_save_checkpoint()` method (workflow.py:228-235) simply doesn't populate them. The fix is to pass these values through.

**Key details**:
- `WorkflowCheckpoint` already has the fields (checkpoint.py:40-41)
- `_save_checkpoint()` needs two new parameters: `team_config` and `task`
- Callers of `_save_checkpoint()` (workflow.py: lines 500-508, 543-551, 575-583) need to pass the values
- `WorkflowEngine` needs access to `team_config` and `task` — currently it has `self._task` (set via `run()`) but not `team_config`
- On resume (hiveflow.py:303-318): fallback chain already exists — session._team_config first, then checkpoint.team_config. The fix makes the checkpoint fallback actually contain data.

**Backward compatibility**: Old checkpoint files without team_config/task will deserialize with empty defaults (dict/str), triggering the existing fallback chain. No migration needed.

---

## R7. MCPToolBridge Output Normalization

**Decision**: Normalize MCP `CallToolResult` content to a `dict[str, Any]` for `execute()` return.

**Rationale**: MCP tools return `CallToolResult` with a `.content` list containing mixed content types (`TextContent`, `ImageContent`, `EmbeddedResource`). The `ToolPlugin.execute()` contract returns `dict[str, Any]`. A normalization step is needed.

**Key details**:
- Single TextContent: `{"result": content.text}`
- Multiple TextContent: `{"result": "\n".join(c.text for c in text_contents)}`
- ImageContent present: `{"result": text, "images": [{"mime_type": ..., "data": ...}]}`
- EmbeddedResource present: included in a `"resources"` list
- `isError` flag on result: raise a `ToolExecutionError` or return `{"error": error_text}`
- This normalization lives in MCPToolBridge.execute(), not in a separate layer

---

## R8. LLM Function Name Sanitization

**Decision**: Override `to_llm_tool_spec()` in MCPToolBridge to sanitize the function name.

**Rationale**: LLM providers (OpenAI, Anthropic) may restrict function names to `[a-zA-Z0-9_-]`. The MCP tool plugin_id format `mcp:server/tool` contains `:` and `/` which may be rejected. The LLM-facing name needs sanitization while the registry-facing `plugin_id` keeps the canonical format.

**Key details**:
- `plugin_id`: remains `mcp:{server}/{tool}` (used for registry lookup, config references)
- `to_llm_tool_spec()`: returns name as `mcp_{server}__{tool}` (colons → underscore, slashes → double underscore)
- Agent `_tool_map` must map BOTH the plugin_id AND the sanitized LLM name to the same tool instance, so tool calls from the LLM (using sanitized name) can be dispatched
- Alternative considered: using only sanitized names everywhere. Rejected because the `mcp:server/tool` format is more readable in configs and logs.

---

## R9. MCP Strategy Override in Team Config

**Decision**: Add optional `mcp_strategy` field to TeamConfiguration schema.

**Rationale**: FR-010 requires the MCP strategy to be overridable per-team. The strategy from `mcp.json` is the default, but a team config can override it. This allows a simple workflow to use `disabled` while a complex workflow uses `deep`.

**Key details**:
- `TeamConfiguration` in schema.py gets `mcp_strategy: str | None = None`
- Valid values: `"disabled"`, `"fast"`, `"deep"`, or `None` (use mcp.json default)
- Resolved at workflow start: `effective_strategy = team_config.mcp_strategy or mcp_config.strategy`
- No changes to mcp.json format — the override lives only in team configs

---

## R10. Bearer Token Authentication for HTTP Transport

**Decision**: Create custom `httpx.AsyncClient` with Authorization header, pass to `streamable_http_client()`.

**Rationale**: The MCP SDK's `streamable_http_client()` accepts an optional `http_client` parameter. For bearer token auth, we create an httpx client with the token pre-set in headers. The token value is resolved from an environment variable specified in the MCP config.

**Key details**:
- Config: `"auth": {"type": "bearer", "env": "MCP_JIRA_TOKEN"}`
- Resolution: `token = os.environ[auth_config.env]` at connection time
- Client: `httpx.AsyncClient(headers={"Authorization": f"Bearer {token}"})`
- Error: Clear message if env var is not set (e.g., "MCP server 'jira' requires bearer token in env var 'MCP_JIRA_TOKEN' but it is not set")
- Future: OAuth support can be added later using the SDK's `OAuthClientProvider`
