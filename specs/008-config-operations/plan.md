# Implementation Plan: Configuration & Operations

**Branch**: `008-config-operations` | **Date**: 2026-02-27 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `specs/008-config-operations/spec.md`

## Summary

Integrate existing but disconnected resilience, cost, and streaming modules into production execution paths, extend the configuration system with missing fields (Source Mode, Actions, MCP), expand the prompt template library, enhance the streaming protocol, and wrap `DeepResearcher` as an orchestrator agent. All core resilience modules (`fallback.py`, `errors.py`, `ratelimit.py`, `json_utils.py`, `cost.py`) are fully implemented but not called from `agent.py` or the workflow engine — the primary work is wiring integration, not new algorithm design.

## Technical Context

**Language/Version**: Python 3.11+ (no `from __future__ import annotations`)  
**Primary Dependencies**: pydantic ≥2.9.2, pydantic-settings, openai ≥1.52.0, anthropic ≥0.39.0, structlog ≥24.4.0, httpx, aiofiles, json-repair, ratelimit  
**Storage**: File-based JSON for checkpoints (`.hiveflow/checkpoints/`); JSON/YAML for team configs  
**Testing**: `uv run pytest tests/` (asyncio_mode=auto, 47 test files)  
**Target Platform**: Python library + CLI (cross-platform)  
**Project Type**: Single Python package  
**Performance Goals**: Config resolution <10ms; fallback chain attempt <100ms overhead per step; streaming event emission <1ms  
**Constraints**: Zero breaking changes to existing public APIs; backward-compatible config schema  
**Scale/Scope**: ~32 core modules, ~990-line agent.py, 4 LLM call sites to wrap with resilience

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| §2.1 Configuration Over Code | ✅ PASS | All new features configurable via YAML/JSON/env vars |
| §2.2 Progressive Disclosure | ✅ PASS | All new config fields have sensible defaults; existing workflows unaffected |
| §2.3 Explicit State, No Magic | ✅ PASS | Rate limiters and cost trackers are explicit objects, not ambient globals (except global per-process rate limiter, which is an intentional shared resource) |
| §2.4 Plugin Architecture | ✅ PASS | No new concrete provider dependencies in core; resilience wraps the existing provider protocol |
| §2.5 Backward Compatibility | ✅ PASS | All changes additive; no existing field/API removal |
| §2.6 Observability Built In | ✅ PASS | Streaming protocol expansion directly serves observability |
| §2.7 Fail Loudly, Recover Gracefully | ✅ PASS | This feature's primary purpose is implementing this principle |
| §3.1 Core Module Rules | ✅ PASS | No new provider SDK imports at core import time |
| §5.1 Python 3.11+ | ✅ PASS | No `from __future__ import annotations` |
| §5.2 uv Package Manager | ✅ PASS | No new dependencies outside uv management |
| §6.1 Testing | ✅ PASS | Integration tests planned for all resilience paths |

No violations. Complexity Tracking table not needed.

## Project Structure

### Documentation (this feature)

```text
specs/008-config-operations/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
└── tasks.md             # Phase 2 output (/speckit.tasks)
```

### Source Code (repository root)

```text
hiveflow/
├── core/
│   ├── config.py            # MODIFY: Add SOURCE_MODE, DOC_PATH, Actions, MCP fields
│   ├── agent.py             # MODIFY: Wrap 4 LLM call sites with resilience layer
│   ├── fallback.py          # MODIFY: Add auto-build with reduced max_tokens step
│   ├── json_utils.py        # (no changes — already complete)
│   ├── errors.py            # (no changes — already complete)
│   ├── ratelimit.py         # (no changes — already complete)
│   ├── cost.py              # (no changes — already complete)
│   ├── prompts.py           # MODIFY: Add dotted-path resolver, prompt families, 13 new categories
│   ├── streaming.py         # MODIFY: Add missing event types, step_id, metadata, JsonLinesWriter
│   ├── research.py          # (no changes — already complete)
│   ├── result_payload.py    # (no changes — cost_summary field exists)
│   ├── schema.py            # (no changes — rollback fields exist)
│   ├── action_queue.py      # NEW: ActionQueue with configurable parallelism/timeout
│   └── orchestrator.py      # NEW: OrchestratorAgent wrapping DeepResearcher
├── plugins/
│   └── mcp/
│       └── config.py        # (reference — MCP fields surfaced in core/config.py)
└── __init__.py

tests/
├── test_config_layering.py      # NEW: Four-layer config precedence tests
├── test_resilience_integration.py # NEW: Fallback + circuit breaker + rate limiting integration
├── test_prompt_templates.py     # NEW: Dotted-path, families, categories
├── test_streaming_protocol.py   # NEW: Event types, dual output, JsonLinesWriter
├── test_action_queue.py         # NEW: Action queue with parallelism/timeout/rollback
└── test_orchestrator_agent.py   # NEW: OrchestratorAgent with DeepResearcher
```

**Structure Decision**: Existing single-package structure (`hiveflow/core/`) is preserved. Two new modules are added (`action_queue.py`, `orchestrator.py`). Six existing modules are modified. Six new test files cover integration paths.
