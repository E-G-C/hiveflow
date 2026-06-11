# Implementation Plan: MCP Integration & Conversational Memory

**Branch**: `007-mcp-memory-integrations` | **Date**: 2026-02-25 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/007-mcp-memory-integrations/spec.md`

## Summary

Implement MCP (Model Context Protocol) client support so agents can discover and use external tool servers (stdio and HTTP transports) alongside native tools, with zero changes to agent logic. MCP tools are wrapped as `MCPToolBridge(ToolPlugin)` instances and registered in the existing `ToolRegistry`. An `MCPManager` reads a dedicated `mcp.json` config, establishes connections using the official `mcp` Python SDK, discovers server tools, and registers them. Three strategy modes are supported: `disabled`, `fast`, and `deep` (LLM-assisted selection, Phase 2). Additionally, the checkpoint system is enhanced to persist `team_config` and `task` for cold-resume support. The MCP Gateway (HiveFlow as MCP server) is deferred to Phase 2 as a separately installable package.

## Technical Context

**Language/Version**: Python 3.11+ (no `from __future__ import annotations`)
**Primary Dependencies**: mcp>=1.26.0 (new optional), httpx, pydantic>=2.9.2, pydantic-settings, structlog>=24.4.0; existing: openai>=1.52.0, anthropic>=0.39.0
**Storage**: File-based JSON for MCP configuration (`.hiveflow/mcp.json`); file-based JSON for checkpoints (existing, enhanced)
**Testing**: pytest + pytest-asyncio; `uv run pytest`
**Target Platform**: Python library (cross-platform); no server/CLI changes required
**Project Type**: Single Python package with new optional `mcp` extras group
**Performance Goals**: MCP tool discovery under 2 seconds per server (SC-003); tool call latency bounded by server response time plus reasonable overhead
**Constraints**: Eager connection failures must not block workflow execution; stdio processes must be cleaned up on workflow end/failure
**Scale/Scope**: MCPToolBridge + MCPManager + MCPConfig models + mcp.json loader + checkpoint enhancement + tool wiring fix in TeamGenerator.build()

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| **S2.1** Configuration Over Code | PASS | MCP servers configured via `mcp.json` file. Strategy configurable per-team via `mcp_strategy` field. No user code required to use MCP tools. |
| **S2.2** Progressive Disclosure | PASS | MCP is off by default (`disabled` strategy when no mcp.json exists). Existing workflows unchanged. Simple path: just add `mcp.json` with a server definition. |
| **S2.3** Explicit State, No Magic | PASS | MCP tools flow through the same state dict as native tools. No hidden side channels. Tool results written to `{agent_id}_tool_results`. |
| **S2.4** Plugin Architecture | PASS | Core feature: MCPToolBridge extends `ToolPlugin`. Registered via existing `ToolRegistry.register()`. No new plugin interface types required. |
| **S2.5** Backward Compatibility | PASS | All changes additive. Existing ToolPlugin, ToolRegistry, Agent interfaces unchanged. Old checkpoint files deserialize with empty defaults for new fields. |
| **S2.6** Observability | PASS | MCPManager logs connection attempts, tool discovery counts, and failures via structlog. Tool execution failures logged with server/tool context. |
| **S2.7** Fail Loudly, Recover Gracefully | PASS | Unreachable servers logged and skipped (FR-009). Mid-call disconnects return tool execution error to agent. Clear error for missing env vars in auth config. |
| **S3.1** Core Module Boundaries | PASS | MCP implementation lives in `hiveflow/plugins/mcp/` (plugin layer). Core modules gain minimal integration: `workflow.py` adds team_config/task to checkpoint, `teams.py` gains tool_registry parameter. |
| **S3.2** Plugin Rules | PASS | MCPToolBridge does not modify global state at import. Missing `mcp` package logs warning and skips MCP initialization. |
| **S3.3** Boundary Layers | PASS | No CLI/API/server changes required. |
| **S4.1** Workflow State | PASS | No new reserved state keys. MCP tools write to existing agent state keys. |
| **S5.1** Language | PASS | Python 3.11+. No `__future__` imports. |
| **S5.2** Package Management | PASS | uv only. `mcp` added as optional extra in `pyproject.toml`. |
| **S5.3** Library Preferences | PASS | No Microsoft MCP SDK exists. The official `mcp` package is the only production-quality option. |
| **S5.4** Async First | PASS | MCPManager, MCPToolBridge.execute(), connection lifecycle — all async. |
| **S6.1** Testing | Required | Unit tests for MCPToolBridge, MCPManager, MCPConfig. Integration tests with mock MCP server. |
| **S6.3** Documentation | Required | README, CHANGELOG updates. |
| **S7** Extension Guidelines | PASS | All 6 checklist items addressed: plugin not core, progressive disclosure, no new state keys, observable via structlog, testing and docs required. |
| **S8** Scope Boundaries | PASS | MCP enables agents to call external tools — consistent with workflow orchestration, not general-purpose agent framework. |

**Gate result: PASS. No violations. Complexity Tracking table not needed.**

**Post-Phase 1 re-check**: PASS. Design artifacts (data-model.md, contracts/, quickstart.md) are consistent with all principles. No new violations introduced. MCPToolBridge is a plugin (S3.2), MCPManager lives in plugins/ not core/ (S3.1), all contracts are async-first (S5.4), LLM function name sanitization handles provider compatibility without changing registry contracts (S2.5), checkpoint enhancement is backward-compatible with existing files (S2.5).

## Project Structure

### Documentation (this feature)

```text
specs/007-mcp-memory-integrations/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── mcp_tool_bridge.py  # MCPToolBridge(ToolPlugin) contract
│   ├── mcp_manager.py      # MCPManager lifecycle contract
│   └── mcp_config.py       # MCPConfig pydantic models contract
└── tasks.md             # Phase 2 output (/speckit.tasks)
```

### Source Code (repository root)

```text
hiveflow/
├── core/
│   ├── workflow.py            # MODIFIED: _save_checkpoint() persists team_config + task
│   ├── teams.py               # MODIFIED: build() accepts tool_registry, resolves tool IDs
│   ├── hiveflow.py            # MODIFIED: passes tool_registry to build(), calls MCPManager startup/shutdown
│   └── schema.py              # MODIFIED: TeamConfiguration gains mcp_strategy field
│
├── plugins/
│   └── mcp/
│       ├── __init__.py        # NEW: MCPToolBridge, public API exports
│       ├── manager.py         # NEW: MCPManager (connection lifecycle, tool discovery)
│       ├── config.py          # NEW: MCPConfig, MCPServerDefinition pydantic models
│       └── bridge.py          # NEW: MCPToolBridge(ToolPlugin) implementation
│
└── __init__.py                # MODIFIED: export MCPManager if mcp package available

tests/
├── test_mcp_bridge.py         # NEW: MCPToolBridge unit tests
├── test_mcp_manager.py        # NEW: MCPManager unit tests (mock MCP server)
├── test_mcp_config.py         # NEW: MCPConfig parsing and validation tests
├── test_checkpoint_enhanced.py # NEW: checkpoint team_config/task persistence
└── test_tool_wiring.py        # NEW: TeamGenerator.build() tool resolution
```

**Structure Decision**: Single Python package. All new MCP code lives in `hiveflow/plugins/mcp/` as a plugin module. Core modifications are minimal: checkpoint persistence fix in `workflow.py`, tool wiring fix in `teams.py`, MCPManager orchestration in `hiveflow.py`, and `mcp_strategy` field addition in `schema.py`. This follows the established pattern where plugin implementations live in `plugins/` and core modules gain only minimal integration points.
