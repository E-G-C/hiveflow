# Implementation Plan: Dynamic Agent Collaboration

**Branch**: `010-dynamic-agent-collaboration` | **Date**: 2026-03-04 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/010-dynamic-agent-collaboration/spec.md`

## Summary

Enable orchestrator agents to dynamically collaborate at runtime by delegating tasks, spawning specialist agents from archetypes, exchanging inter-agent messages, and composing collaborative task plans — all without requiring the workflow graph to be defined ahead of time. Implemented as additive tool plugins (`DelegateTaskTool`, `SpawnAgentTool`, `MessageTool`) backed by a `CollaborationRuntime` that manages the runtime agent pool, depth tracking, budget enforcement, and tool access scoping. The collaboration tools are auto-injected into orchestrator agents when `collaboration.enabled` is true in the team configuration.

## Technical Context

**Language/Version**: Python 3.11+ (no `from __future__ import annotations`)
**Primary Dependencies**: pydantic >=2.9.2, openai >=1.52.0, anthropic >=0.39.0, structlog >=24.4.0, asyncio (stdlib)
**Storage**: In-memory (runtime agent pool, message bus); file-based JSON checkpoints (existing)
**Testing**: pytest + pytest-asyncio (existing test infrastructure)
**Target Platform**: Cross-platform Python library (CLI-first, API-first)
**Project Type**: Single package — `hiveflow/` with `tests/`
**Performance Goals**: Delegation overhead < 50ms above the delegate agent's own execution time; concurrent sub-tasks execute via `asyncio.gather`
**Constraints**: Max delegation depth default 3; max spawned agents default 10; delegation timeout default 300s — all configurable at global and team levels
**Scale/Scope**: Operates within a single workflow execution; agent pool bounded by `max_spawned_agents`; no persistence of spawned agents across runs

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| §2.1 Configuration Over Code | PASS | Collaboration enabled/configured via team config YAML/JSON; no user code required |
| §2.2 Progressive Disclosure | PASS | `collaboration.enabled` defaults to `false`; existing workflows unaffected; simple teams remain simple |
| §2.3 Explicit State, No Magic | PASS | Messages stored in state `_messages`; delegation context is explicit filtered state; all flows traceable |
| §2.4 Plugin Architecture | PASS | Delegation, spawning, messaging implemented as `ToolPlugin` subclasses; registered via existing `ToolRegistry` |
| §2.5 Backward Compatibility | PASS | Additive feature; no changes to existing `Agent`, `WorkflowEngine`, or `TeamConfiguration` behavior; new optional field on schema |
| §2.6 Observability Built In | PASS | All collaboration events (spawn, delegate, message, plan) emitted via `StreamChannel` and logged to audit trail |
| §2.7 Fail Loudly, Recover Gracefully | PASS | Depth limit exceeded → clear error; spawn limit → clear error; timeout → delegation terminated with error info; budget exhausted → graceful termination |
| §3.1 Core Module Rules | PASS | New code in `hiveflow/core/collaboration.py` (runtime) and `hiveflow/plugins/tools/` (tool plugins); core has zero new external dependencies |
| §3.2 Plugin Rules | PASS | Collaboration tools are `ToolPlugin` implementations; no global state at import time; declared dependencies only |
| §4.1 State Contract | PASS | New reserved keys: `_messages`, `_delegation_depth`, `_spawned_agents` (all `_`-prefixed internal); agent output keys follow existing `{agent_id}_output` convention |
| §5.1 Language | PASS | Python 3.11+, no `from __future__ import annotations` |
| §5.2 Package Management | PASS | No new external dependencies required |
| §5.4 Async First | PASS | All collaboration operations are async; delegation uses `await agent.execute()`; parallel sub-tasks use `asyncio.gather()` |
| §6.1 Testing | PASS | Unit tests for each tool plugin + CollaborationRuntime; integration tests for delegation chains |
| §7 Extension Guidelines | PASS | New state keys documented; observable via events; configurable with defaults; tested |
| §8 Scope Boundaries | REVIEW | Dynamic agent spawning approaches "free-form agent systems" territory — mitigated by orchestrator-gating, depth limits, and spawn caps |

**Gate result**: PASS (§8 review noted but mitigated by design constraints)

## Project Structure

### Documentation (this feature)

```text
specs/010-dynamic-agent-collaboration/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
└── tasks.md             # Phase 2 output (/speckit.tasks command)
```

### Source Code (repository root)

```text
hiveflow/
├── core/
│   ├── collaboration.py          # NEW — CollaborationRuntime, CollaborationConfig model
│   ├── schema.py                 # MODIFIED — add CollaborationConfig to TeamConfiguration
│   ├── config.py                 # MODIFIED — add global collaboration defaults to HiveFlowConfig
│   ├── workflow.py               # MODIFIED — inject collaboration tools into orchestrator agents
│   ├── streaming.py              # MODIFIED — add new StreamEventType entries
│   ├── agent.py                  # MODIFIED — extend _summarize_state() with message injection
│   └── teams.py                  # UNCHANGED — ArchetypeLibrary used as-is
├── plugins/
│   └── tools/
│       ├── __init__.py           # UNCHANGED — ToolPlugin + ToolRegistry used as-is
│       ├── delegate_task.py      # NEW — DelegateTaskTool
│       ├── spawn_agent.py        # NEW — SpawnAgentTool
│       └── message.py            # NEW — SendMessageTool + ReadMessagesTool

tests/
├── test_collaboration.py         # NEW — unit tests for CollaborationRuntime
├── test_delegate_task.py         # NEW — unit tests for DelegateTaskTool
├── test_spawn_agent.py           # NEW — unit tests for SpawnAgentTool
├── test_message.py               # NEW — unit tests for messaging tools
└── test_collaboration_integration.py  # NEW — integration tests for delegation chains
```

**Structure Decision**: Single-package structure following existing `hiveflow/` layout. New core runtime goes in `hiveflow/core/collaboration.py`. New tool plugins go in `hiveflow/plugins/tools/`. This matches the existing pattern where core logic is in `core/` and tool implementations are in `plugins/tools/`.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| §8 Scope — dynamic spawning approaches free-form agents | Orchestrators need to adapt team composition at runtime to handle emergent sub-problems; this is the core value proposition of the feature | Static-only teams were the simpler alternative but cannot handle tasks whose decomposition is only known after initial analysis. Mitigated by: orchestrator-only gating (FR-013), depth limits (FR-009), spawn caps (FR-010), ephemeral agents (FR-007), tool scoping (FR-027). |
