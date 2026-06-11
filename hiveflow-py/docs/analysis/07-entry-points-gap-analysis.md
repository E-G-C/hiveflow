# Gap Analysis: 07-entry-points.md vs Current Implementation

**Date:** 2026-02-24 
**Baseline:** Current codebase (v0.1.0) 
**Constraint:** Requirements must be enhancements only — no reduction of existing functionality.

---

## Summary

The current implementation already covers a significant portion of `07-entry-points.md`. Most gaps are **additive** (new CLI commands, new REST endpoints, new methods). However, there are **naming/signature contradictions** and **behavioral differences** that would require breaking changes to align 1:1 with the spec. These are flagged below.

| Category | OK (aligned) | Enhancement (additive) | Contradiction / Red Flag |
|---|---|---|---|
| Python API | 8 | 4 | 4 |
| CLI | 2 | 8 | 2 |
| REST API | 5 | 10 | 3 |
| Misc (Docker, Sources) | 0 | 4 | 0 |

---

## RED FLAGS & CONTRADICTIONS

### RF-01: CLI uses `--template` but spec requires `--team`

| Spec | Current |
|---|---|
| `hiveflow run --team research_report --task "..."` | `hiveflow run --template research_report --instructions "..."` |

The CLI argument is `--template` in the codebase (`cli/main.py` L33) but the spec mandates `--team`. Also, the spec uses `--task` while the implementation uses `--instructions` / `--instructions-file`.

**Risk:** Renaming `--template` → `--team` and `--instructions` → `--task` is a **breaking change** for any existing users or scripts. The current names are more descriptive (`--template` is what you load, `--instructions` is what you provide).

**Recommendation:** Add `--team` and `--task` as aliases, keep existing flags as deprecated but functional. This is an enhancement, not a reduction.

---

### RF-02: `TeamTemplateLibrary.list_templates()` vs spec's `list_teams()`

| Spec | Current |
|---|---|
| `hf.team_library().list_teams()` | `hf.team_library().list_templates()` → returns `list[str]` |

The spec calls the method `list_teams()` but the implementation has `list_templates()` (defined in `teams.py` L52).

**Risk:** Renaming removes an existing public API method.

**Recommendation:** Add `list_teams()` as an alias for `list_templates()`. Keep both.

---

### RF-03: `ToolRegistry.describe()` does not exist

| Spec | Current |
|---|---|
| `hf.tool_registry().describe()` | No `describe()` method. Only `list_ids()`, `get()`, `get_or_raise()`. |

The `PluginRegistry` base class (and `ToolRegistry` subclass) has no `describe()` method that returns metadata about registered tools.

**Risk:** None — purely additive. But the name `describe()` without arguments returning tool metadata would clash with any future per-tool describe pattern.

**Recommendation:** Implement `describe()` that returns `list[dict]` with tool IDs and descriptions. Pure enhancement.

---

### RF-04: `LLMProviderRegistry.list_models()` does not exist

| Spec | Current |
|---|---|
| `hf.model_registry().list_models()` | No `list_models()` method. Has `list_ids()` (provider IDs) and per-provider `get_available_models()`. |

The spec expects a unified `list_models()` method on the registry. Currently, `list_ids()` only lists provider names (e.g., `["openai", "anthropic"]`), and `get_available_models()` is a per-provider method that returns `[]` by default.

**Risk:** None — purely additive. Needs aggregation logic across providers.

**Recommendation:** Add `list_models()` that iterates providers and collects their `get_available_models()` results.

---

### RF-05: `HiveFlow.run_sync_resume()` does not exist

| Spec | Current |
|---|---|
| `hf.run_sync_resume(session, responses=user_response)` | No `run_sync_resume()` method. `resume()` is async only. |

The spec's "Native Application Integration" section requires a sync wrapper for resume operations, mirroring `run_sync()` for initial execution. This does not exist.

**Risk:** None — purely additive. But this has design implications: `resume()` currently takes `session_id` (str) as first arg, while the spec passes a `session` object.

**Recommendation:** Add `run_sync_resume()` accepting either a session object or session_id, wrapping the async `resume()`. Enhancement only.

---

### RF-06: Python API `session.events()` — property vs async generator

| Spec | Current |
|---|---|
| `async for event in session.events():` (async generator) | `session.events` is a `StreamChannel` property. To iterate, you call `session.subscribe()` → `StreamConsumer` → `async for event in consumer`. |

The spec shows `session.events()` as a callable that returns an async iterable. The current implementation exposes `events` as a property returning the raw `StreamChannel`, and a separate `subscribe()` method for consuming events.

**Risk:** Making `events` callable (method) would break code accessing `session.events` as a property. The spec event types also differ — spec uses `event.type == "step_complete"` and `event.type == "output"` while current code uses `StreamEventType` enum values like `STEP_END`, `OUTPUT`.

**Recommendation:** Add an `events()` method that returns an async iterable (calling `subscribe()` internally). Keep the property for backward compatibility by renaming it to `_events_channel` (internal). The event type naming differences (`step_complete` vs `STEP_END`, etc.) need alignment.

---

### RF-07: `generate_team()` return type — spec expects `.config` with `save_json()`, `.new_archetypes` with `save_json()`

| Spec | Current |
|---|---|
| `result.config.save_json(...)` — implies TeamConfiguration | `result.config` returns a raw `dict[str, Any]` |
| `result.new_archetypes` — list of archetype objects with `.save_json()` | `TeamGenerationResult.new_archetypes` does not exist |

Currently `TeamGenerationResult.config` is `dict[str, Any]` (teams.py). The spec expects it to be a `TeamConfiguration` Pydantic model (which does have `save_json()`). Also, the spec expects `result.new_archetypes` with archetype objects that have `save_json()` — this attribute doesn't exist.

**Risk:** Changing `config` from `dict` to `TeamConfiguration` could break code that treats it as a dict. However, Pydantic models support dict-like access in many cases.

**Recommendation:** Wrap the dict in a `TeamConfiguration` on return. Add `new_archetypes` field. Ensure backward compatibility by keeping dict-like access patterns working.

---

### RF-08: REST API endpoint paths diverge significantly

| Spec Endpoint | Current Endpoint | Issue |
|---|---|---|
| `POST /api/workflows` | `POST /workflows/start` | Different path **and** prefix |
| `GET /api/workflows/{id}` | `GET /workflows/{workflow_id}` | Path prefix, param name |
| `POST /api/workflows/{id}/resume` | `POST /workflows/{workflow_id}/resume` | Path prefix |
| `DELETE /api/workflows/{id}` | **Not implemented** | Missing |
| `GET /api/teams` | `GET /templates` | Different name AND prefix |
| `GET /api/teams/{name}` | `GET /templates/{name}` | Different name AND prefix |
| `POST /api/teams/generate` | `POST /templates/generate` | Different name AND prefix |
| `GET /api/archetypes` | **Not implemented** | Missing |
| `GET /api/tools` | `GET /tools` | Prefix only |
| `GET /api/models` | **Not implemented** | Missing |
| `GET /api/checkpoints` | **Not implemented** | Missing |
| `GET /api/checkpoints/{id}` | **Not implemented** | Missing |
| `GET /api/workflows/{id}/actions` | **Not implemented** | Missing |
| `POST /api/actions/{id}/rollback` | **Not implemented** | Missing |
| `WS /api/workflows/{id}/events` | `WS /ws/workflows/{workflow_id}` | Different path |
| `GET /api/workflows/{id}/events` (SSE) | **Not implemented** | Missing |

**Key contradictions:**
1. The spec uses `/api/` prefix; the current implementation has no prefix.
2. Spec uses `/teams` for team listing; current uses `/templates`.
3. Spec uses `POST /api/workflows` to create; current uses `POST /workflows/start`.
4. WebSocket paths differ.

**Risk:** Changing existing endpoint paths would break any frontend code, API clients, or integrations already using the current paths. The `/templates` vs `/teams` naming is conceptually meaningful — the current code distinguishes between templates (pre-built configs) and teams (runtime instances), while the spec conflates them.

**Recommendation:** Add the `/api/` prefixed endpoints alongside existing ones (router aliasing). Do NOT remove existing endpoints. Deprecate old paths over time.

---

### RF-09: REST API uses `HiveFlow` facade inconsistently

The spec states: "A reference FastAPI server wraps the `HiveFlow` public API". However, the current REST API in `api/__init__.py` does **not** use the `HiveFlow` class at all. It directly instantiates `WorkflowEngine`, `Agent`, `TeamTemplateLibrary`, and `LLMProviderRegistry` independently.

**Risk:** This is an architectural gap but not a contradiction per se — the REST API works. Switching to use `HiveFlow` internally would be a refactor that could introduce regressions if not carefully done.

**Recommendation:** Refactor the REST API to delegate to a `HiveFlow` instance. This is an enhancement to align with the spec's architecture and reduces code duplication.

---

### RF-10: CLI missing most subcommands

| Spec CLI Command | Implemented? |
|---|---|
| `hiveflow run --team ... --task ...` | Partial (`--template`, `--instructions`) |
| `hiveflow teams list` | No |
| `hiveflow teams generate --task ...` | No |
| `hiveflow teams validate ./file.json` | No |
| `hiveflow archetypes list` | No |
| `hiveflow tools list` | No |
| `hiveflow providers list` | No |
| `hiveflow resume --checkpoint ...` | No |
| `hiveflow run ... --dry-run` | No |
| `hiveflow run ... --doc ./file` | Yes (`--doc`) |
| `hiveflow serve` (Docker section) | No |

**Risk:** None — all purely additive. The existing `run` command keeps working.

**Recommendation:** Implement CLI subcommands incrementally.

---

## ENHANCEMENTS (no contradictions — safe to implement)

| ID | Feature | Notes |
|---|---|---|
| E-01 | `ToolRegistry.describe()` | New method |
| E-02 | `LLMProviderRegistry.list_models()` | New aggregation method |
| E-03 | `HiveFlow.run_sync_resume()` | Sync wrapper for resume |
| E-04 | CLI subcommands: `teams list`, `teams generate`, `teams validate` | New argparse subparsers |
| E-05 | CLI subcommands: `archetypes list`, `tools list`, `providers list` | New argparse subparsers |
| E-06 | CLI: `hiveflow resume --checkpoint <id>` | New subcommand |
| E-07 | CLI: `--dry-run` flag | New flag |
| E-08 | REST: `DELETE /api/workflows/{id}` (cancel) | New endpoint |
| E-09 | REST: `GET /api/archetypes` | New endpoint |
| E-10 | REST: `GET /api/models` | New endpoint |
| E-11 | REST: `GET /api/checkpoints`, `GET /api/checkpoints/{id}` | New endpoints |
| E-12 | REST: `GET /api/workflows/{id}/actions`, `POST /api/actions/{id}/rollback` | New endpoints |
| E-13 | REST: SSE endpoint for event streaming | New endpoint |
| E-14 | `TeamGenerationResult.new_archetypes` field | New field |
| E-15 | Source Plugin Interface & cloud source plugins | Entirely new subsystem |
| E-16 | Docker support (`hiveflow serve` command) | New CLI + Dockerfile |

---

## WHAT'S WELL ALIGNED (no changes needed)

| Feature | Spec | Implementation |
|---|---|---|
| `HiveFlow` facade class | | `hiveflow.core.hiveflow.HiveFlow` |
| `hf.run(team=..., task=..., documents=...)` | | Async, returns `WorkflowSession` |
| `hf.run_sync(...)` | | Sync wrapper with thread pool |
| `hf.generate_team(task, auto_approve=False)` | | Returns `TeamGenerationResult` |
| `hf.resume(session_id, responses)` | | Async resume from checkpoint |
| `hf.team_library()` / `hf.archetype_library()` | | Discovery methods |
| `hf.tool_registry()` / `hf.model_registry()` | | Discovery methods |
| `TeamConfiguration.from_json_file()` / `.save_json()` | | Pydantic model with I/O |
| `session.status`, `session.pending_requests` | | `WorkflowSession` properties |
| `session.result` | | `WorkflowResult` on completion |
| CLI entry point `hiveflow = "hiveflow.cli.main:main"` | | In `pyproject.toml` |
| REST workflow start, status, resume | | In `api/__init__.py` |
| WebSocket streaming | | Implemented |
| `ApprovalRequest` for human-in-the-loop | | Fully functional |

---

## PRIORITY RECOMMENDATIONS

### Must Fix Before Implementing (high risk of breaking changes)

1. **RF-01, RF-02:** Alias `--team`/`--task` and `list_teams()` alongside existing names. Do not remove existing names.
2. **RF-08:** Add `/api/` prefixed routes as aliases. Do not remove existing routes.
3. **RF-06:** Add `events()` method without breaking the `events` property.

### Should Implement (medium priority, clean enhancements)

4. **RF-09:** Refactor REST API to delegate to `HiveFlow`.
5. **RF-03, RF-04:** Add `describe()` and `list_models()` methods.
6. **RF-05:** Add `run_sync_resume()`.
7. **RF-07:** Wrap `generate_team()` result config in `TeamConfiguration`.

### Can Defer (low priority, new subsystems)

8. **E-04 through E-07:** CLI subcommands.
9. **E-08 through E-13:** REST API new endpoints.
10. **E-15:** Source Plugin system (entirely new).
11. **E-16:** Docker/serve command.
