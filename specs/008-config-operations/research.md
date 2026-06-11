# Research: Configuration & Operations

**Feature**: 008-config-operations  
**Date**: 2026-02-27  
**Purpose**: Resolve all technical unknowns and document design decisions for implementation.

---

## R-001: Resilience Layer Integration Pattern

**Decision**: Wrapper/decorator approach — inject a `ResilientLLMProvider` that wraps the existing `llm_provider` protocol, adding fallback chains, circuit breaking, rate limiting, and cost tracking transparently.

**Rationale**: The 4 LLM call sites in `agent.py` (lines ~165, ~208, ~312, ~423) all call `self.llm_provider.chat(messages, config)`. Rather than modifying each call site with resilience logic, a wrapper provider intercepts the call, applies the resilience pipeline, and delegates to the underlying provider. This keeps `agent.py` clean and makes resilience testable in isolation.

**Alternatives considered**:
- **Modify each call site directly**: Rejected — 4 separate integration points create duplication and divergence risk.
- **Middleware chain**: Rejected — over-engineered for a single `.chat()` method; a simple wrapper is sufficient.
- **Agent base class refactor**: Rejected — too invasive; violates backward compatibility (§2.5).

**Implementation approach**:
```
ResilientLLMProvider wraps llm_provider:
  1. ProviderRateLimiter.acquire()          # global per-process
  2. CircuitBreaker.call() →
     3. FallbackChain.execute() →
        4. llm_provider.chat()              # actual call
  5. CostTracker.record()                   # on success
  6. parse_json_resilient()                  # for structured output
```

---

## R-002: Fallback Chain Auto-Construction with Reduced max_tokens

**Decision**: `FallbackChain.from_tiers(config)` class method that auto-builds the chain from the configured tiers, inserting a 50% max_tokens intermediate step before each tier demotion.

**Rationale**: The requirements document specifies: "Strategic → Strategic + reduced max_tokens → Smart → Fast → error". The current `FallbackChain` requires manual construction. A factory method reads the config tiers and generates the full chain automatically.

**Alternatives considered**:
- **Manual chain construction per agent**: Rejected — error-prone, violates DRY.
- **Config-file-specified chains**: Rejected — too complex for most users; violates progressive disclosure (§2.2).

**Chain structure**:
```
[
  (strategic_provider, strategic_model, max_tokens),
  (strategic_provider, strategic_model, max_tokens * 0.5),
  (smart_provider, smart_model, max_tokens),
  (smart_provider, smart_model, max_tokens * 0.5),
  (fast_provider, fast_model, max_tokens),
  → error: LLMFallbackExhaustedError
]
```

---

## R-003: Configuration Extension Strategy for Missing Fields

**Decision**: Add new fields directly to `HiveFlowConfig` with defaults that preserve existing behavior. Source Mode and MCP fields are added as top-level fields; Actions fields are added as a group.

**Rationale**: The existing `HiveFlowConfig` uses pydantic-settings `BaseSettings` with `env_prefix="HIVEFLOW_"`. Adding fields is additive and backward-compatible — all new fields have defaults matching the current implicit behavior (e.g., `SOURCE_MODE="web"` matches current behavior where only web retrievers are used).

**New fields**:
| Field | Type | Default | Env Var |
|-------|------|---------|---------|
| `SOURCE_MODE` | `Literal["web","local","hybrid","cloud","mcp","custom"]` | `"web"` | `HIVEFLOW_SOURCE_MODE` |
| `DOC_PATH` | `str \| None` | `None` | `HIVEFLOW_DOC_PATH` |
| `DEFAULT_ACTION_POLICY` | `Literal["deny","allow","dry_run"]` | `"deny"` | `HIVEFLOW_DEFAULT_ACTION_POLICY` |
| `ENABLE_ROLLBACK` | `bool` | `False` | `HIVEFLOW_ENABLE_ROLLBACK` |
| `ACTION_TIMEOUT` | `int` | `30` | `HIVEFLOW_ACTION_TIMEOUT` |
| `MCP_STRATEGY` | `Literal["disabled","fast","deep"]` | `"disabled"` | `HIVEFLOW_MCP_STRATEGY` |
| `MCP_SERVERS` | `list[dict]` | `[]` | `HIVEFLOW_MCP_SERVERS` |
| `MCP_AUTO_TOOL_SELECTION` | `bool` | `True` | `HIVEFLOW_MCP_AUTO_TOOL_SELECTION` |

**Alternatives considered**:
- **Nest MCPConfig as a sub-model**: Rejected — env var resolution with nested pydantic-settings models is complex and the flat approach is simpler for users.
- **Separate config file for MCP**: Rejected — violates single-config-file principle.

---

## R-004: Prompt Family Auto-Selection

**Decision**: A `PromptFamily` enum (`default`, `granite`, `local`) with a `detect_family(model_name: str) -> PromptFamily` function that uses prefix matching on model names.

**Rationale**: Different model families respond best to different prompt structures. Auto-detection from the model name avoids requiring users to manually specify the family. Prefix matching (`granite:` → Granite, `ollama:` → Local, everything else → Default) is simple and extensible.

**Alternatives considered**:
- **User-specified family in config**: Rejected as primary mechanism — too much friction. Kept as optional override.
- **Per-provider family mapping**: Rejected — providers can serve multiple model families.

**Family characteristics**:
- **Default**: Standard instruction-following prompts (GPT-4o, Claude, etc.)
- **Granite**: Structured XML-style prompts with explicit sections
- **Local**: Simpler, more explicit instructions with fewer implicit expectations

---

## R-005: Dotted-Path Variable Resolution in Prompts

**Decision**: Replace `string.Template` with a custom resolver that supports `$variable` (flat) and `${object.path.field}` (dotted) syntax, traversing dict and object attributes.

**Rationale**: The current `PromptTemplate` uses `string.Template` with `safe_substitute`, which only supports flat `$variable` names. The spec requires `task.description`, `config.language`, etc. A custom resolver walks the dot-separated path, checking `dict.__getitem__` then `getattr` at each level.

**Alternatives considered**:
- **Jinja2 templates**: Rejected — heavy dependency for simple variable resolution; jinja2 is optional (publishers extras only).
- **Format string with `**kwargs` flattening**: Rejected — loses the nested structure information.

---

## R-006: Streaming Protocol Extension

**Decision**: Extend `StreamEventType` enum with missing types, add `step_id`, `content`, `metadata`, and `timestamp` fields to `StreamEvent`, and create a `JsonLinesWriter` subscriber.

**Rationale**: The existing `StreamEvent` has `type` and `agent_id` but lacks required fields per FR-020. The existing `StreamChannel` fan-out supports multiple subscribers, so adding a `JsonLinesWriter` as another subscriber is architecturally clean.

**New StreamEventType values** (9 additions):
`LOG`, `HUMAN_REQUEST`, `COST`, `ROLLBACK`, `SUMMARY_GENERATED`, `OUTLINE_GENERATED`, `ASSEMBLY_COMPLETE`, `EXECUTOR_INVOKED`, `EXECUTOR_COMPLETED`

**Existing types that map to spec** (renaming not needed — keep both names):
- `GATE_REQUESTED` ≈ `request_info` (keep existing name, add alias)
- `ACTION_PROPOSED` + `ACTION_EXECUTED` ≈ `action`

**JsonLinesWriter**: Async subscriber that appends each `StreamEvent` as a JSON line to `{OUTPUT_DIR}/events-{date}.jsonl`. Uses `aiofiles` for non-blocking writes. Opened on workflow start, closed on workflow end.

---

## R-007: ActionQueue Design

**Decision**: New `core/action_queue.py` module with an `ActionQueue` class using `asyncio.Semaphore` for concurrency control and `asyncio.wait_for` for timeouts.

**Rationale**: The spec requires a controlled queue for side-effect actions (FR-013). No action queue exists today. The design mirrors the existing `ConcurrencyLimiter` in `ratelimit.py` but adds queue semantics: enqueue action → wait for slot → execute with timeout → handle rollback on failure.

**Interface**:
```python
class ActionQueue:
    def __init__(self, max_concurrency: int, timeout: float, enable_rollback: bool)
    async def submit(self, action: Action) -> ActionResult
    async def drain(self) -> list[ActionResult]
```

---

## R-008: OrchestratorAgent Wrapping DeepResearcher

**Decision**: New `core/orchestrator.py` module with `OrchestratorAgent` that extends `Agent` (or is registered as an agent subclass), delegates to `DeepResearcher`, and reports progress via `StreamChannel`.

**Rationale**: `DeepResearcher` is a standalone utility that uses callbacks, not nested `Workflow` instances. Rather than refactoring `DeepResearcher` (which works correctly), the `OrchestratorAgent` wraps it as an agent that participates in the registry and workflow graph. It maps `DeepResearcher`'s callbacks to workflow events and progress updates.

**Alternatives considered**:
- **Refactor DeepResearcher to use Workflow instances**: Rejected — too invasive; the callback pattern works, and wrapping preserves the tested implementation.
- **Make DeepResearcher an Agent subclass directly**: Rejected — DeepResearcher has a different interface from Agent; adapting is cleaner than inheriting.

---

## R-009: JSON-Lines Audit Log Location

**Decision**: Audit logs are written to `{OUTPUT_DIR}/events-{YYYY-MM-DD}.jsonl` using `aiofiles`. No automatic rotation; files accumulate daily.

**Rationale**: Aligns with the clarification decision. The `OUTPUT_DIR` config field already exists. Date-based filenames prevent single-file growth. External log rotation tools (logrotate, Azure Monitor, etc.) handle retention per the operator's policy.

**Alternatives considered**:
- **Single file with rotation**: Rejected — adds complexity without clear benefit for a framework library.
- **Per-workflow-run files**: Rejected — would create many small files; date-based is a better default.
