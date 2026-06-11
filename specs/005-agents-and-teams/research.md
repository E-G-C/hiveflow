# Research: Agents and Teams

**Feature**: 005-agents-and-teams
**Date**: 2026-02-24

## Existing Implementation Inventory

The codebase already implements ~75% of the spec. This research documents what exists, what's missing, and decisions for each gap.

### Already Implemented

| Component | Location | Coverage |
|-----------|----------|----------|
| 5 behavior types (llm_only, tool_user, orchestrator, human_gate, action_executor) | `core/agent.py` AgentBehaviorType enum + execution dispatch | Complete |
| AgentDefinition schema | `core/schema.py` lines 91-202 | Complete (except `on_failure`) |
| WorkflowStepDefinition schema with max_iterations | `core/schema.py` lines 204-230 | Complete (except `sub_workflow` type) |
| TeamConfiguration schema | `core/schema.py` | Complete |
| WorkflowEngine with sequential, parallel_fan_out, conditional, human_gate, gated | `core/workflow.py` | Complete (behavioral tweaks needed) |
| Conditional iteration counting | `core/workflow.py` lines 811-824 | Complete |
| ArchetypeLibrary with 6 built-ins + file loading | `core/teams.py` lines 111-202 | Complete |
| TeamTemplateLibrary | `core/teams.py` | Complete |
| TeamGenerator (template-based, no LLM) | `core/teams.py` lines 325-413 | Partial |
| CapabilityGap + TeamGenerationResult | `core/teams.py` | Complete |
| ModelRequirements, OutputType, StateSchema | `core/schema.py` | Complete |
| ActionRecord dataclass | `core/result_payload.py` lines 19-51 | Basic (needs enhancement) |
| Checkpoint/resume | `core/checkpoint.py` | Complete |
| Plugin system / tool registry | `core/registry.py`, `plugins/` | Complete |
| Action executor with auto/require_approval | `core/agent.py` lines 373-493 | Partial (needs dry_run, confirm_on_error) |
| research_report.json team template | `templates/research_report.json` | Complete |
| RetryProvider (no backoff delay) | `core/fallback.py` lines 133-203 | Partial — retries without delay |
| FallbackChain (provider cascading) | `core/fallback.py` lines 15-118 | Complete |
| TokenBucketRateLimiter | `core/ratelimit.py` | Complete |

### Gaps Requiring Implementation

| # | Gap | FR | Files Affected | Complexity |
|---|-----|-----|---------------|------------|
| G1 | `on_failure` field on AgentDefinition | FR-020 | schema.py, workflow.py | Low |
| G2 | `dry_run` action policy | FR-003 | schema.py, agent.py | Medium |
| G3 | `confirm_on_error` action policy | FR-003 | schema.py, agent.py | Medium |
| G4 | Rollback support for action_executor | FR-005 | agent.py, workflow.py, result_payload.py | Medium |
| G5 | `sub_workflow` step type | FR-019 | schema.py, workflow.py, hiveflow.py | High |
| G6 | Namespaced parallel fan-out merge | Clarif. Q1 | workflow.py | Medium |
| G7 | Conditional ambiguity → reject default | Clarif. Q2 | workflow.py | Low |
| G8 | LLM-based team generation | FR-013 | teams.py | High |
| G9 | Archetype JSON files on disk | FR-009 | templates/archetypes/*.json | Low |
| G10 | Additional team templates | Assumption | templates/*.json | Low |
| G11 | Enhanced ActionRecord fields | FR-004 | result_payload.py | Low |
| G12 | Transient LLM error backoff at agent level | FR-021 | workflow.py (or agent.py) | Medium |

---

## Gap Research & Decisions

### G1: `on_failure` Field on AgentDefinition

**Decision**: Add optional `on_failure` field to `AgentDefinition` with values `fail` (default), `retry`, `skip`. Add optional `max_retries: int = 1` for retry mode.

**Rationale**: Clarification Q3 established per-agent failure policy. Follows existing pattern of `action_policy` — a string enum field with sensible default.

**Implementation**:
- Add `on_failure: str | None = Field(default=None)` to AgentDefinition in `schema.py`
- Add validator: values must be `fail`, `retry`, or `skip`; `None` treated as `fail`
- Add `max_retries: int = Field(default=1, ge=1)` for `on_failure="retry"`
- In `workflow.py`, wrap `_execute_agent()` call with failure policy logic

**Alternatives considered**:
- Workflow-level global policy — rejected; agents have different reliability characteristics
- No policy (always fail) — rejected; inflexible for production

---

### G2: `dry_run` Action Policy

**Decision**: Extend action_policy validator to accept `dry_run`. LLM proposes tool calls, framework records them as "planned" actions without executing.

**Rationale**: Essential for testing and validation of action_executor agents.

**Implementation**:
- Extend validator in `schema.py` line 166 to accept `dry_run`
- In `agent.py` `_execute_action_executor()`, add third branch: collect proposed tool calls, create ActionRecord with `status="dry_run"`, skip execution, store in `{agent}_dry_run_plan`

**Alternatives considered**:
- Separate behavior type — rejected; dry_run is a policy on the same behavior
- Tool-level dry_run — rejected; safety gate belongs at agent level

---

### G3: `confirm_on_error` Action Policy

**Decision**: Extend action_policy to accept `confirm_on_error`. Actions execute immediately (like `auto`), but on tool failure the workflow pauses for human decision.

**Rationale**: Middle ground between `auto` (fully automated) and `require_approval` (always stop).

**Implementation**:
- Extend validator to accept `confirm_on_error`
- In `agent.py`, execute tools like `auto` mode; on error, create checkpoint with `awaiting_error_resolution`, surface error for human decision (retry, skip, abort)

**Alternatives considered**:
- Auto-retry then escalate — deferred; initial implementation pauses on first error
- Separate `on_tool_error` field — rejected; action_policy is the right abstraction

---

### G4: Rollback Support

**Decision**: Add `rollback_on_failure: bool = False` and `rollback_action: str | None = None` to AgentDefinition. Framework invokes the declared rollback tool when triggered.

**Rationale**: Spec and requirements explicitly require declarative rollback. Framework calls the rollback tool; does not infer rollback logic.

**Implementation**:
- Add fields to AgentDefinition in `schema.py`
- In `workflow.py`, when a step fails and previous action_executor had `rollback_on_failure=True`, invoke `rollback_action` tool with original action context
- Enhanced ActionRecord (G11) tracks `reversible: bool` and `rollback_action: str`
- If rollback itself fails, log and surface error (per spec edge case)

**Alternatives considered**:
- Automatic rollback inference — rejected; spec says declarative
- Compensation events — too complex for initial delivery

---

### G5: `sub_workflow` Step Type

**Decision**: Add `SUB_WORKFLOW` to WorkflowStepType and implement nested execution. Sub-workflow loads another TeamConfiguration, executes it with mapped state.

**Rationale**: Enables workflow composability. Phase 2 scope per assumptions, but schema and basic execution should be in place.

**Implementation**:
- Add `SUB_WORKFLOW = "sub_workflow"` to enum
- Add `team`, `input_mapping`, `output_mapping` fields to WorkflowStepDefinition
- In `workflow.py`, add `_execute_sub_workflow()`: load team, build inner engine, map state in, execute, map state out
- Recursion guard: max 5 nesting levels

**Alternatives considered**:
- Inline sub-workflow definition — rejected; TeamConfiguration reuse is cleaner
- Coroutine delegation — unnecessary complexity

---

### G6: Namespaced Parallel Fan-Out Merge

**Decision**: Parallel instances write to indexed sub-keys; results collected into structured dict for downstream access.

**Rationale**: Clarification Q1. Current simple dict merge loses individual item identity.

**Implementation**:
- In `workflow.py` `_execute_parallel()`, after asyncio.gather:
  - Add `{agent}_parallel_results` as structured dict mapping `item_{i}` → result
  - Preserve existing `{agent}_outputs` (list) and `{agent}_output` (concatenated) for backward compat

**Alternatives considered**:
- Break existing merge — rejected; backward compatibility (§2.5) is non-negotiable
- Only list aggregation — rejected; namespaced keys give granular access

---

### G7: Conditional Ambiguity → Reject Default

**Decision**: Change tie-breaking from `accept_score >= reject_score` (tie → accept) to `accept_score > reject_score` (tie → reject).

**Rationale**: Clarification Q2. Conservative fail-safe. Log warning on ambiguity.

**Implementation**:
- In `workflow.py` `_evaluate_condition()` line 866: change `>=` to `>`
- Add structlog warning on tied scores

**Alternatives considered**:
- Configurable per-step — rejected; single behavior is simpler and spec decision was definitive

---

### G8: LLM-Based Team Generation

**Decision**: Add `async generate_team_from_llm()` to `TeamGenerator`. Sends structured prompt to LLM with task, tools, models, archetypes. Parses response into TeamGenerationResult.

**Rationale**: Existing `generate_team()` is template-based/deterministic. FR-013 requires LLM-based generation.

**Implementation**:
- Add async method accepting `llm_provider`, `tool_registry`, `archetype_library`, `auto_approve`
- Build structured prompt with: task description, tool specs, archetype examples
- Request JSON output matching TeamConfiguration schema
- Parse with json-repair for resilience
- Validate against schema, detect capability gaps
- Return TeamGenerationResult

**Alternatives considered**:
- Function calling for structured output — viable but json-repair + schema validation is more portable across providers
- Intermediate format — unnecessary; TeamConfiguration JSON is the target

---

### G9: Archetype JSON Files on Disk

**Decision**: Create `hiveflow/templates/archetypes/` directory with 6 JSON files matching existing ARCHETYPES dict.

**Rationale**: Makes archetypes discoverable, editable, consistent with `from_directory()` pattern.

**Implementation**: Create researcher.json, planner.json, writer.json, reviewer.json, editor.json, human_reviewer.json. Keep in-memory ARCHETYPES as fallback.

**Alternatives considered**:
- YAML — rejected; JSON is primary format per requirements
- Remove in-memory dict — rejected; both provides resilient defaults

---

### G10: Additional Team Templates

**Decision**: Create `code_review.json` and `content_creation.json`.

**Rationale**: Spec assumes 3+ templates. Only `research_report.json` exists.

**Implementation**:
- `code_review.json`: reviewer + code_writer + human_reviewer, conditional loop
- `content_creation.json`: planner + researcher + writer + editor, sequential

---

### G11: Enhanced ActionRecord Fields

**Decision**: Add `policy`, `approved_by`, `reversible`, `rollback_action`, `workflow_run_id` to ActionRecord.

**Rationale**: Spec requires richer audit trail. Current ActionRecord is basic.

**Implementation**: All new fields optional with defaults for backward compat. Update `_execute_action_executor()` to populate.

---

### G12: Transient LLM Error Backoff at Agent Level

**Decision**: Add exponential backoff retry logic at the agent execution level in the workflow engine, specifically for transient LLM errors (429, 5xx), before the `on_failure` policy is evaluated.

**Rationale**: FR-021 and Clarification Q5. Constitution §2.7 explicitly mandates: "Transient errors (API rate limits, network timeouts) are retried with exponential backoff before surfacing."

**Existing infrastructure**:
- `RetryProvider` in `core/fallback.py` — wraps a single provider with retry but **no delay between attempts**
- `FallbackChain` — cascades across providers on failure
- `TokenBucketRateLimiter` — proactive rate limiting, not reactive retry

**Implementation approach**:
- Add a `_retry_transient` async helper in `workflow.py` (or reuse/enhance `RetryProvider`)
- Detect transient errors: HTTP 429 (rate limit), 5xx (server errors), `ConnectionError`, `TimeoutError`
- Apply exponential backoff: delays of 1s, 2s, 4s (base=1, factor=2, max_retries=3)
- Log each retry attempt with structlog (aligned with §2.6)
- If all retries exhausted, the error propagates to the `on_failure` policy
- This layer sits **between** the raw agent execution and the `on_failure` policy:
  ```
  Agent.execute() → [transient backoff retry] → [on_failure policy] → workflow
  ```

**Why not just enhance RetryProvider?**
- `RetryProvider` operates at the provider level and applies to all uses of a provider globally
- FR-021 requires retry at the **agent execution level**, so the retry count and backoff apply per-agent-invocation within a workflow, not per-provider globally
- Developers may use `RetryProvider` independently for provider-level resilience; the agent-level retry is additive

**Alternatives considered**:
- Enhance `RetryProvider` with delay — useful independently, but wrong abstraction level for FR-021
- Use `ratelimit` library — it's for proactive rate limiting, not reactive retry
- No backoff (just retry) — rejected; constitution §2.7 explicitly says "exponential backoff"
