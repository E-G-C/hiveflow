# Data Model: MCP Integration & Conversational Memory

**Feature**: 007-mcp-memory-integrations
**Date**: 2026-02-25

---

## Entities

### MCPServerDefinition (new pydantic model)

To be created in `hiveflow/plugins/mcp/config.py`.

| Field       | Type                        | Required | Default | Description                                            |
| ----------- | --------------------------- | -------- | ------- | ------------------------------------------------------ |
| `name`      | `str`                       | Yes      | —       | Unique server name (used in tool IDs and logging)      |
| `transport` | `Literal["stdio", "http"]`  | Yes      | —       | Transport mode                                         |
| `url`       | `str \| None`               | No       | `None`  | Server URL (required when transport is `http`)         |
| `command`   | `str \| None`               | No       | `None`  | Executable to spawn (required when transport is `stdio`) |
| `args`      | `list[str]`                 | No       | `[]`    | Arguments for spawned process (`stdio` only)           |
| `env`       | `dict[str, str] \| None`    | No       | `None`  | Additional env vars for spawned process (`stdio` only) |
| `auth`      | `MCPAuthConfig \| None`     | No       | `None`  | Authentication config (`http` only)                    |
| `lazy`      | `bool`                      | No       | `False` | Defer connection until first tool use                  |

**Identity**: Deduplicated by `name`. Two servers with the same name is a config validation error.

**Validators**:
- `url` MUST be set when `transport == "http"`
- `command` MUST be set when `transport == "stdio"`
- `auth` only valid when `transport == "http"`
- `env` and `args` only valid when `transport == "stdio"`

---

### MCPAuthConfig (new pydantic model)

To be created in `hiveflow/plugins/mcp/config.py`.

| Field  | Type                    | Required | Default | Description                                      |
| ------ | ----------------------- | -------- | ------- | ------------------------------------------------ |
| `type` | `Literal["bearer"]`     | Yes      | —       | Authentication type (extensible to `"oauth"` later) |
| `env`  | `str`                   | Yes      | —       | Environment variable name holding the token value |

**Resolution**: At connection time, `os.environ[auth.env]` is resolved. A `KeyError` produces a clear error message identifying the server name and missing env var.

---

### MCPConfig (new pydantic model)

To be created in `hiveflow/plugins/mcp/config.py`.

| Field      | Type                                          | Required | Default      | Description                            |
| ---------- | --------------------------------------------- | -------- | ------------ | -------------------------------------- |
| `strategy` | `Literal["disabled", "fast", "deep"]`         | No       | `"disabled"` | Global MCP strategy mode               |
| `servers`  | `list[MCPServerDefinition]`                   | No       | `[]`         | List of configured MCP servers         |

**Validators**:
- Server names MUST be unique within the `servers` list
- If `strategy` is `"fast"` or `"deep"` and `servers` is empty, log a warning (configured but no servers)

**File location**: `.hiveflow/mcp.json` (default), overridable via `HIVEFLOW_MCP_CONFIG` env var.

**Loading**: `MCPConfig.from_file(path)` class method. If file doesn't exist and env var not set, returns `MCPConfig(strategy="disabled")` (MCP silently off).

---

### MCPToolBridge (new class, extends ToolPlugin)

To be created in `hiveflow/plugins/mcp/bridge.py`.

| Property/Method            | Type/Signature                                              | Status |
| -------------------------- | ----------------------------------------------------------- | ------ |
| `plugin_id`                | `str` — format: `mcp:{server_name}/{tool_name}`            | NEW    |
| `description`              | `str` — from MCP server tool spec                          | NEW    |
| `input_schema`             | `dict[str, Any]` — from MCP tool `inputSchema`             | NEW    |
| `output_schema`            | `dict[str, Any]` — `{"type": "object"}`                    | NEW    |
| `server_name`              | `str` — the MCP server this tool belongs to                 | NEW    |
| `tool_name`                | `str` — the tool name within the MCP server                 | NEW    |
| `execute(tool_input)`      | `async (dict[str, Any]) -> dict[str, Any]`                 | NEW    |
| `to_llm_tool_spec()`       | `-> dict[str, Any]` — sanitized name for LLM compatibility | NEW    |

**Construction**: Receives `server_name: str`, `tool_spec: mcp.types.Tool`, and a callable `call_fn` for executing tool calls. The `call_fn` is a closure over the `ClientSession.call_tool` method, avoiding direct session reference.

**execute() behavior**:
1. Call `self._call_fn(self.tool_name, arguments=tool_input)`
2. Normalize `CallToolResult.content` to dict:
   - Single/multiple `TextContent` → `{"result": combined_text}`
   - `ImageContent` present → add `"images"` list
   - `isError=True` → `{"error": error_text}`
3. Log execution via structlog (`mcp.tool.execute`, server_name, tool_name, success/error)

**to_llm_tool_spec() behavior**:
- Returns OpenAI-compatible function spec with sanitized name
- Name: `mcp_{server_name}__{tool_name}` (`:` → `_`, `/` → `__`)
- Description and parameters from MCP tool spec

**Agent dispatch**: Agent `_tool_map` maps both `plugin_id` (`mcp:server/tool`) AND sanitized LLM name (`mcp_server__tool`) to the same `MCPToolBridge` instance. This is handled by MCPManager during registration — it registers the tool once in ToolRegistry (by plugin_id), and the Agent's tool wiring maps both names.

---

### MCPManager (new class)

To be created in `hiveflow/plugins/mcp/manager.py`.

| Property/Method                  | Type/Signature                                                     | Status |
| -------------------------------- | ------------------------------------------------------------------ | ------ |
| `config`                         | `MCPConfig`                                                        | NEW    |
| `tool_registry`                  | `ToolRegistry`                                                     | NEW    |
| `async startup(task: str)`       | `async () -> None` — connect eager servers, discover tools         | NEW    |
| `async ensure_server(name: str)` | `async (str) -> None` — connect lazy server on first use           | NEW    |
| `async shutdown()`               | `async () -> None` — close all connections, terminate processes    | NEW    |
| `get_tools()`                    | `-> list[MCPToolBridge]` — all discovered MCP tools                | NEW    |
| `is_available`                   | `bool` — True if mcp package is importable                        | NEW    |

**Lifecycle**:
1. `__init__(config, tool_registry)`: Stores config and registry. Creates `AsyncExitStack`.
2. `startup(task)`: For each non-lazy server, calls `_connect_server()`. On failure, logs warning and continues. For `deep` strategy, runs LLM-based selection after all connections.
3. `_connect_server(server_def)`: Enters transport context manager and `ClientSession()` into `AsyncExitStack`. Calls `session.initialize()` and `session.list_tools()`. Creates `MCPToolBridge` per tool and registers in `tool_registry`.
4. `ensure_server(name)`: For lazy servers, connects on demand.
5. `shutdown()`: Calls `await self._exit_stack.aclose()`. This closes all sessions and terminates all stdio processes.

**Error handling**:
- Connection failure during `startup()`: log error, skip server, continue
- Connection failure during `ensure_server()`: raise `MCPConnectionError` (lazy servers are needed when referenced)
- Tool execution failure (mid-call disconnect): caught in MCPToolBridge.execute(), returned as `{"error": ...}`

---

### TeamConfiguration (existing — modified)

Located in `hiveflow/core/schema.py`.

| Field          | Type              | Status   | Description                              |
| -------------- | ----------------- | -------- | ---------------------------------------- |
| `mcp_strategy` | `str \| None`     | **NEW**  | Override MCP strategy for this team       |

**Validator**: Value must be `None`, `"disabled"`, `"fast"`, or `"deep"`.

**Resolution order**: `team_config.mcp_strategy` → `mcp_config.strategy` → `"disabled"`.

---

### WorkflowCheckpoint (existing — enhanced)

Located in `hiveflow/core/checkpoint.py`.

| Field         | Type              | Status       | Description                              |
| ------------- | ----------------- | ------------ | ---------------------------------------- |
| `team_config` | `dict[str, Any]`  | **EXISTING** | Now populated by `_save_checkpoint()`    |
| `task`        | `str`             | **EXISTING** | Now populated by `_save_checkpoint()`    |

No schema changes needed — the fields already exist on the dataclass. The change is behavioral: `_save_checkpoint()` will populate them where it currently leaves them as empty defaults.

---

## Relationships

```text
MCPConfig
  └── servers: list[MCPServerDefinition]
        └── auth?: MCPAuthConfig

MCPManager
  ├── config: MCPConfig
  ├── tool_registry: ToolRegistry
  └── _connections: dict[str, ClientSession]
        └── tools: list[MCPToolBridge]
              └── extends ToolPlugin
                    └── registered in ToolRegistry

TeamConfiguration
  ├── agents[].tools: list[str]  ← includes "mcp:{server}/{tool}" IDs
  └── mcp_strategy?: str         ← overrides MCPConfig.strategy

HiveFlow.run()
  ├── loads MCPConfig from mcp.json
  ├── creates MCPManager(config, tool_registry)
  ├── await mcp_manager.startup(task)
  ├── generator.build(config, llm_provider, tool_registry=tool_registry)
  │     └── resolves agent tools from registry (native + MCP)
  ├── engine.run(agents, ...)
  │     └── _save_checkpoint(..., team_config=config, task=task)
  └── await mcp_manager.shutdown()
```

---

## State Changes

No new reserved workflow state keys. MCP tools write to existing agent-scoped keys:

- `{agent_id}_tool_results` — MCP tool call results (same format as native tool results)
- `{agent_id}_output` — agent output incorporating MCP tool results

Checkpoint changes:
- `team_config` field: populated with the full team configuration dict
- `task` field: populated with the task string
