# Implementation Plan: Agents and Teams

**Branch**: `005-agents-and-teams` | **Date**: 2026-02-24 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/005-agents-and-teams/spec.md`

## Summary

Complete the agents and teams system by filling gaps in the existing implementation. The codebase already provides ~75% of the required functionality: all 5 behavior types, workflow step types (except sub_workflow), archetype/team libraries, schema validation, checkpoint/resume, and basic action audit trails. This plan focuses on the remaining gaps: adding `on_failure` per-agent policy with transient-error backoff, `dry_run`/`confirm_on_error` action policies with rollback support, `sub_workflow` step type, LLM-based team generation, namespaced parallel merge, conditional ambiguity defaulting to reject, archetype JSON files on disk, and additional team templates.

## Technical Context

**Language/Version**: Python 3.11+ (no `from __future__ import annotations` per constitution §5.1)
**Primary Dependencies**: pydantic >=2.9.2, openai >=1.52.0, anthropic >=0.39.0, structlog >=24.4.0, httpx, aiofiles, pyyaml, json-repair, ratelimit
**Storage**: File-based JSON for checkpoints (`.hiveflow/checkpoints/`), JSON/YAML for team configs and archetypes
**Testing**: pytest via `uv run pytest` (constitution §6.1)
**Target Platform**: Python library + CLI (cross-platform)
**Project Type**: Single Python package
**Performance Goals**: Agent execution overhead negligible compared to LLM latency; parallel fan-out uses asyncio.gather
**Constraints**: Async-first (§5.4); core modules zero import-time dependency on LLM SDKs (§3.1); plugins loaded lazily (§3.2)
**Scale/Scope**: Teams of 2-20 agents; workflows of 2-50 steps; archetype/team libraries of 10-100 entries

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| # | Principle | Status | Notes |
|---|-----------|--------|-------|
| 2.1 | Configuration Over Code | PASS | All new capabilities are config-driven (on_failure, action_policy, max_iterations are schema fields) |
| 2.2 | Progressive Disclosure | PASS | All new fields are optional with sensible defaults (on_failure=fail, max_iterations=3, action_policy=auto) |
| 2.3 | Explicit State, No Magic | PASS | Parallel namespaced keys make state flow explicit; audit trail entries written to state dict |
| 2.4 | Plugin Architecture | PASS | Rollback uses existing tool plugin interface; no core changes to plugin system needed |
| 2.5 | Backward Compatibility | PASS | All changes are additive; existing team configs continue to work unchanged; new fields have defaults |
| 2.6 | Observability Built In | PASS | Enhanced audit trail; conditional loop warnings logged; transient retry attempts logged with structlog |
| 2.7 | Fail Loudly, Recover Gracefully | PASS | on_failure=fail is default; iteration limits prevent infinite loops; transient errors retried with backoff before surfacing (directly aligns with §2.7) |
| 3.1 | Core Module Boundaries | PASS | Changes confined to existing core modules (schema.py, agent.py, workflow.py, teams.py); no new core modules |
| 3.2 | Plugin System | PASS | No changes to plugin protocols; tool plugins unaffected |
| 5.1 | Language & Runtime | PASS | Python 3.11+, no `from __future__ import annotations` |
| 5.2 | Package Management | PASS | uv only; no new top-level deps needed (ratelimit already available) |
| 5.4 | Async First | PASS | All new methods (generate_team_from_llm, _execute_sub_workflow, rollback) are async |
| 6.1 | Testing | PASS | Each gap requires corresponding unit and integration tests |

**Pre-Phase 0 Gate: PASSED — no violations.**

## Project Structure

### Documentation (this feature)

```text
specs/005-agents-and-teams/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (Python API contracts)
│   └── python-api.md
└── tasks.md             # Phase 2 output (/speckit.tasks command)
```

### Source Code (repository root)

```text
hiveflow/
├── core/
│   ├── schema.py          # MODIFY: on_failure, sub_workflow, dry_run/confirm_on_error policies
│   ├── agent.py           # MODIFY: dry_run, confirm_on_error, rollback, transient backoff
│   ├── workflow.py         # MODIFY: namespaced parallel merge, conditional→reject, sub_workflow, on_failure wrapper
│   ├── teams.py           # MODIFY: LLM-based team generation
│   ├── checkpoint.py      # NO CHANGE
│   ├── config.py          # NO CHANGE
│   ├── session.py         # NO CHANGE
│   ├── registry.py        # NO CHANGE
│   ├── hiveflow.py        # MINOR: wire sub_workflow team resolution
│   └── result_payload.py  # MODIFY: enhanced ActionRecord fields
├── templates/
│   ├── archetypes/        # NEW: JSON archetype files on disk
│   │   ├── researcher.json
│   │   ├── planner.json
│   │   ├── writer.json
│   │   ├── reviewer.json
│   │   ├── editor.json
│   │   └── human_reviewer.json
│   ├── research_report.json  # EXISTS
│   ├── code_review.json      # NEW
│   └── content_creation.json # NEW
└── plugins/               # NO CHANGE

tests/
├── test_schema.py               # MODIFY: new schema field tests
├── test_schema_additions.py     # MODIFY: on_failure, sub_workflow, policy tests
├── test_action_executor.py      # MODIFY: dry_run, confirm_on_error, rollback tests
├── test_core.py                 # MODIFY: enhanced workflow behavior tests
├── test_advanced.py             # MODIFY: conditional→reject, namespaced parallel tests
├── test_teams.py                # NEW: LLM team generation, archetype file loading tests
└── test_transient_retry.py      # NEW: exponential backoff for transient LLM errors
```

**Structure Decision**: Single Python package layout. All changes within `hiveflow/`. New archetype files under `hiveflow/templates/archetypes/`. Two new test files for team generation and transient retry coverage.

## Complexity Tracking

> No constitution violations detected. No entries needed.
