# Implementation Plan: Task Preprocessing and Large-Input Context Management

**Branch**: `014-task-preprocessing` | **Date**: 2026-03-05 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/014-task-preprocessing/spec.md`

## Summary

Implement automatic detection and decomposition of large task inputs so that agents receive focused, right-sized context instead of the full input blob. When `state["task"]` exceeds a model-derived threshold, the system separates instructions from data, chunks the data into model-appropriate segments, generates a compact summary and manifest for routing agents, and updates context assembly to inject only relevant pieces into each agent's prompt. Tasks below the threshold are passed through unchanged with zero overhead.

The approach integrates into the existing execution flow: `TaskPreprocessor.preprocess()` runs in `WorkflowEngine.execute()` after document loading and before agent execution. It reuses the existing `chunk_text()` utility (enhanced with paragraph-boundary awareness), `SummaryGenerator` LLM call pattern, and `structlog` logging. Agent context assembly in `Agent._summarize_state()` gains a preprocessing-aware branch. Delegation, fan-out, and retrieval mechanisms are extended to support chunk routing.

## Technical Context

**Language/Version**: Python 3.11+ (no `from __future__ import annotations`)
**Primary Dependencies**: pydantic >=2.9.2, pydantic-settings, structlog >=24.4.0, openai >=1.52.0, anthropic >=0.39.0, httpx
**Storage**: In-memory state dict (no persistent storage for preprocessing artifacts)
**Testing**: pytest with `uv run pytest`
**Target Platform**: Cross-platform Python library (Linux, macOS, Windows)
**Project Type**: Single Python package (`hiveflow/`)
**Performance Goals**: ≤2 LLM calls overhead per preprocessing run (SC-005); ≥60% token reduction for 21K-word inputs (SC-001)
**Constraints**: No agent receives task content >20% of model context window (SC-003); full backward compatibility for small tasks (SC-004, FR-011)
**Scale/Scope**: Inputs up to ~100K words; model context windows from 8K to 1M tokens

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| §2.1 Configuration Over Code | PASS | Preprocessing is fully configurable via `HiveFlowConfig` env vars and team YAML — no user code required |
| §2.2 Progressive Disclosure | PASS | Zero-config default (auto-threshold). Advanced users can tune ratios and overrides |
| §2.3 Explicit State, No Magic | PASS | All preprocessing state stored in well-documented keys (`task_instructions`, `task_data`, etc.). No hidden side channels |
| §2.4 Plugin Architecture | PASS | `ModelContextRegistry` extensible at runtime. `LLMProvider.context_window` is an optional property on the existing protocol |
| §2.5 Backward Compatibility | PASS | Tasks below threshold produce zero state changes (FR-011). `state["task"]` always exists (FR-013) |
| §2.6 Observability Built In | PASS | FR-014 requires structured log events for all preprocessing decisions |
| §2.7 Fail Loudly, Recover Gracefully | PASS | Boundary detection fallback (20/80 split), summarization retry+backoff+mechanical fallback. All failures logged |
| §3.1 Core Module Boundaries | PASS | New `core/preprocessing.py` module. Depends only on `core/*` and `plugins/llm` (existing pattern) |
| §3.2 Plugin Rules | PASS | No new plugins required. `ModelContextRegistry` is core, not a plugin |
| §4.1 State Contract | PASS | 4 new state keys documented. `state["task"]` contract preserved (FR-013) |
| §5.1 Python 3.11+ | PASS | No `from __future__` imports |
| §5.2 uv Package Manager | PASS | No new external dependencies required |
| §5.4 Async First | PASS | `preprocess()` is `async` (LLM calls are async) |
| §6.1 Testing | PASS | Unit tests for all components; integration test for full preprocessing pipeline |
| §6.3 Documentation | PASS | README, CHANGELOG, and guides will be updated |
| §7 Extension Guidelines | PASS | All 6 checklist items satisfied (see below) |

**Extension Guidelines Checklist**:
1. Core or plugin? → **Core** (`core/preprocessing.py`) — preprocessing is not provider-specific or optional
2. Progressive disclosure? → **Yes** — zero-config default, existing simple workflows unaffected
3. State contract? → **Yes** — 4 new keys documented in data-model.md and this plan
4. Observable? → **Yes** — structured logging per FR-014
5. Tested? → **Yes** — unit + integration tests planned
6. Documented? → **Yes** — quickstart.md, updated guides planned

### Post-Phase 1 Re-Check

| Principle | Status | Notes |
|-----------|--------|-------|
| All above | PASS | Design phase introduced no violations. Data model uses dataclasses (simple data as per AGENTS.md). No new external dependencies. Async-first preserved. State keys are stable contracts. |

## Project Structure

### Documentation (this feature)

```text
specs/014-task-preprocessing/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   └── api.md           # Phase 1 output (Python API contracts)
├── checklists/
│   └── requirements.md  # Spec quality checklist
└── tasks.md             # Phase 2 output (/speckit.tasks command)
```

### Source Code (repository root)

```text
hiveflow/
├── core/
│   ├── preprocessing.py    # NEW — TaskPreprocessor, ModelContextRegistry, data classes
│   ├── agent.py            # MODIFIED — _summarize_state() preprocessing-aware branch
│   ├── workflow.py         # MODIFIED — TaskPreprocessor integration in execute()
│   ├── config.py           # MODIFIED — new TASK_PREPROCESS_* config fields
│   ├── collaboration.py    # MODIFIED — _build_sub_state() propagates preprocessing keys
│   ├── teams.py            # MODIFIED — build() creates TaskPreprocessor, team config parsing
│   └── summarizer.py       # UNCHANGED — reused for pattern reference
├── plugins/
│   ├── llm/
│   │   └── __init__.py     # MODIFIED — optional context_window on LLMProvider protocol
│   └── documents/
│       └── __init__.py     # UNCHANGED — chunk_text() reused
tests/
├── test_preprocessing.py   # NEW — unit tests for TaskPreprocessor and components
├── test_preprocessing_integration.py  # NEW — integration tests for full pipeline
├── test_infrastructure.py  # MODIFIED — may need minor updates
└── test_agent.py           # MODIFIED — tests for preprocessing-aware _summarize_state()
```

**Structure Decision**: Single Python package. New code in `hiveflow/core/preprocessing.py` (1 new file). Modifications to 6 existing files. 2 new test files. No new directories except `contracts/` under specs.

## Complexity Tracking

> No constitution violations. No complexity justifications needed.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| (none) | — | — |

## Design Decisions Summary

Key decisions from [research.md](research.md):

1. **Integration point**: `WorkflowEngine.execute()` after document loading, before collaboration init (R1)
2. **Context registry**: Three-tier model resolution — provider property → prefix lookup → 16K default (R2)
3. **Chunking**: Reuse `chunk_text()` with paragraph-boundary-aware wrapper (R3)
4. **Topic hints**: Single batched LLM call for summary + hints; first-sentence fallback (R4)
5. **Delegation**: Extend `_build_sub_state()` to propagate preprocessing keys + `chunk_ids` filter (R5)
6. **Context assembly**: Preprocessing-aware branch at line 740 of `agent.py` (R6)
7. **Configuration**: `HiveFlowConfig` global fields + team-level `preprocessing:` section (R7)
8. **Boundary heuristics**: Ordered cascade — explicit labels → hrule+heading → code fence → size gradient → LLM (R8)
9. **Logging**: `structlog` events for all preprocessing decisions (R9)
10. **Fan-out**: Extend existing `parallel_fan_out` with `source: "task_data"` (R10)

## File-Level Change Map

| File | Change Type | Scope | Key Changes |
|------|------------|-------|-------------|
| `hiveflow/core/preprocessing.py` | NEW | ~400 lines | `TaskPreprocessor`, `PreprocessingConfig`, `ModelContextRegistry`, `TaskDataChunk`, `ChunkMeta`, `TaskDataManifest`, boundary detection heuristics, paragraph-aware chunking wrapper |
| `hiveflow/core/config.py` | MODIFY | ~15 lines | 7 new `TASK_PREPROCESS_*` fields on `HiveFlowConfig` |
| `hiveflow/core/workflow.py` | MODIFY | ~20 lines | Import `TaskPreprocessor`, add `task_preprocessor` param to `__init__`, call `preprocess()` in `execute()`, extend fan-out to support `source: "task_data"` |
| `hiveflow/core/agent.py` | MODIFY | ~25 lines | Preprocessing-aware branch in `_summarize_state()` at line 740 |
| `hiveflow/core/teams.py` | MODIFY | ~30 lines | Parse `preprocessing:` from team config, create `TaskPreprocessor` in `build()`, pass to `WorkflowEngine` |
| `hiveflow/core/collaboration.py` | MODIFY | ~20 lines | `_build_sub_state()` propagates preprocessing keys, `DelegateTaskTool` accepts `chunk_ids` param |
| `hiveflow/plugins/llm/__init__.py` | MODIFY | ~5 lines | Optional `context_window` property on `LLMProvider` protocol |
| `tests/test_preprocessing.py` | NEW | ~350 lines | Unit tests: threshold computation, boundary detection (4 patterns + LLM fallback), chunking, summary, manifest, config |
| `tests/test_preprocessing_integration.py` | NEW | ~200 lines | Integration: full pipeline end-to-end, backward compat, fan-out, delegation routing |
| `tests/test_agent.py` | MODIFY | ~30 lines | Tests for preprocessing-aware `_summarize_state()` |
