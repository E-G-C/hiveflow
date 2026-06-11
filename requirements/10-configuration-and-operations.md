[< Back to Index](README.md)

---

> **Implementation status legend:**
> ✅ Implemented  ·  🔶 Partial  ·  ❌ Not started

## Configuration System

The framework needs a layered configuration system.

> **Status: 🔶 ~85% complete.** Core layering, three-tier LLM selection, and most
> config categories are implemented in `core/config.py`. Missing: Actions config,
> Source Mode, and MCP fields in main config.

### Three-Tier LLM Model Selection ✅

| Tier            | Purpose                 | Default              | Used For                                            |
| --------------- | ----------------------- | -------------------- | --------------------------------------------------- |
| `FAST_LLM`      | Quick, cheap operations | `openai:gpt-4o-mini` | Sub-query generation, agent selection, JSON parsing |
| `SMART_LLM`     | Primary reasoning       | `openai:gpt-4o`      | Report writing, reviewing, analysis, complex logic  |
| `STRATEGIC_LLM` | Complex planning        | `openai:o3-mini`     | Workflow planning, deep reasoning, architecture     |

Per-agent model selection can reference these tiers (`"model": "$SMART_LLM"`)
or specify a concrete model (`"model": "openai:gpt-4o"`).

> `LLMTier` enum + `resolve_model()` in `core/config.py`. Defaults match spec.

### Configuration Layering ✅

```
Defaults → Config file (JSON/YAML) → Environment variables → Team config overrides
```

Each layer overrides the previous. Environment variables use a `HIVEFLOW_`
prefix (e.g., `HIVEFLOW_SMART_LLM=openai:gpt-4o`).

> Implemented via pydantic-settings `BaseSettings` with `env_prefix="HIVEFLOW_"`.
> `from_file()` loads JSON/YAML; `apply_overrides()` handles runtime overrides.

### Key Configuration Categories

| Category          | Fields                                                                        | Status |
| ----------------- | ----------------------------------------------------------------------------- | ------ |
| **LLM**           | `FAST_LLM`, `SMART_LLM`, `STRATEGIC_LLM`, `LLM_TEMPERATURE`, `MAX_TOKENS`     | ✅     |
| **Embedding**     | `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`                                       | ✅     |
| **Retrieval**     | `RETRIEVERS` (comma-separated), `MAX_SEARCH_RESULTS_PER_QUERY`                | ✅     |
| **Scraping**      | `SCRAPER`, `MAX_SCRAPER_WORKERS`, `SCRAPER_RATE_LIMIT_DELAY`                  | ✅     |
| **Context**       | `MAX_CONTEXT_PER_TASK`, `MAX_SUMMARY_LENGTH`, `MAX_OUTLINE_LENGTH`, `ENABLE_SUMMARY_PROPAGATION`, `SIMILARITY_THRESHOLD`, `BROWSE_CHUNK_MAX_LENGTH`, `TOTAL_WORDS` | ✅     |
| **Output**        | `OUTPUT_TYPE`, `LANGUAGE`, `TONE`, `PUBLISH_FORMATS`, `OUTPUT_DIR`            | 🔶     |
| **Actions**       | `DEFAULT_ACTION_POLICY`, `ENABLE_ROLLBACK`, `ACTION_TIMEOUT`                  | ❌     |
| **Deep research** | `DEEP_RESEARCH_BREADTH`, `DEEP_RESEARCH_DEPTH`, `DEEP_RESEARCH_CONCURRENCY`   | ✅     |
| **Tone**          | `TONE` (default tone ID); extensible via tone catalog file                    | ✅     |
| **Source mode**   | `SOURCE_MODE` (web/local/hybrid/cloud/mcp/custom), `DOC_PATH`, source options | ❌     |
| **MCP**           | `MCP_SERVERS`, `MCP_STRATEGY` (fast/deep/disabled), `MCP_AUTO_TOOL_SELECTION` | 🔶     |

> **Implementation notes:**
> - **Output:** Uses `REPORT_FORMAT` (not `OUTPUT_TYPE`) in `HiveFlowConfig`. The
>   `OUTPUT_TYPE` concept is implemented separately via `core/output_types.py`
>   (registry + team generation) but not exposed as a config field.
> - **Context:** Implementation includes extra fields beyond spec:
>   `CHUNK_OVERLAP`, `SUMMARY_THRESHOLD`, `CONTEXT_RECENCY_WINDOW`.
> - **Actions:** All three fields are absent from `HiveFlowConfig`. Action schema
>   (`core/schema.py`) has `rollback_on_failure` and `rollback_action` fields but
>   no config-level defaults.
> - **Source mode:** No `SOURCE_MODE` toggle exists. Source curation
>   (`core/source_curation.py`) handles quality scoring/filtering after retrieval,
>   but not routing between web/local/hybrid sources. Implementing this requires:
>   adding `SOURCE_MODE` and `DOC_PATH` to `HiveFlowConfig`, then using them
>   to select which retrievers activate.
> - **MCP:** Strategy and server definitions exist in `plugins/mcp/config.py`
>   (`MCPConfig`), but those fields are **not surfaced in `HiveFlowConfig`**.
>   `MCP_AUTO_TOOL_SELECTION` is absent. To integrate: either embed `MCPConfig`
>   as a nested field in `HiveFlowConfig`, or add `MCP_STRATEGY` and
>   `MCP_AUTO_TOOL_SELECTION` as top-level fields that feed into `MCPConfig`.

---

## Resilience & Error Handling Patterns

> **Status: 🔶 ~35% complete.** All resilience primitives are built as
> standalone modules (`core/fallback.py`, `core/json_utils.py`, `core/errors.py`,
> `core/ratelimit.py`, `core/cost.py`) with good APIs and unit tests. However,
> **none are wired into the agent/workflow execution paths**. This is the
> largest systemic gap — the modules exist but are never called from production
> code. The integration work is the remaining effort.

Multi-agent workflows are inherently fragile — LLM calls fail, scrapes time out,
actions produce unexpected results, and JSON parsing breaks. The framework
codifies resilience patterns:

### LLM Fallback Chains 🔶

When an LLM call fails, automatically retry with fallback tiers:

```
Strategic LLM → Strategic + reduced max_tokens → Smart LLM → Fast LLM → error
```

Each tier is attempted before surfacing an error. Configurable per agent.

> **What exists:** `FallbackChain` and `RetryProvider` in `core/fallback.py`
> support generic cascades through ordered `(provider, model)` tuples. On
> transient errors (`LLMRateLimitError`, `LLMConnectionError`) it moves to the
> next provider. Auth/model-not-found errors fail immediately.
>
> **Gaps:**
> - The fixed tier cascade with a "reduced `max_tokens`" intermediate step is
>   not auto-built — callers must construct the chain manually.
> - `FallbackChain` is not imported or used by `core/agent.py` or any workflow
>   code. Integration point: wrap the LLM call in `Agent._call_llm()` (or
>   equivalent) with a `FallbackChain` built from the agent's config.

### JSON Parse Resilience 🔶

LLM-generated JSON is frequently malformed. The parsing pipeline:

```
json.loads() → json_repair.loads() → regex extraction → default fallback
```

Never crash a workflow because an LLM returned slightly invalid JSON.

> **What exists:** `parse_json_resilient()` in `core/json_utils.py` implements
> the exact 4-step pipeline above, including type validation (`expect_type`)
> and `extract_json_from_response()` convenience wrapper.
>
> **Gap:** `core/agent.py` uses raw `json.loads()` with bare `try/except`
> instead of calling `parse_json_resilient()`. Fix: replace all
> `json.loads()` calls in agent code with `parse_json_resilient()`.

### Error Isolation 🔶

- **Per-URL isolation** — Each scraped URL is wrapped in try/except; failures
  are logged and skipped
- **Per-agent isolation** — An agent failure can be caught and routed to a
  fallback path in the workflow graph
- **Per-tool isolation** — Tool execution failures return a structured error
  object rather than raising exceptions
- **Per-action isolation** — Failed actions trigger rollback procedures rather
  than crashing the workflow

> **What exists:** `CircuitBreaker` (closed/open/half-open states),
> `with_timeout()`, and `BulkheadSemaphore` in `core/errors.py`. Tool calls in
> `agent.py` have try/except blocks. Action schema has `rollback_on_failure`
> and `rollback_action` fields.
>
> **Gaps:**
> - `CircuitBreaker` and `BulkheadSemaphore` are not applied to any execution
>   path — only tested in unit tests.
> - Tool errors are caught and logged but not returned as structured error
>   objects to the calling agent.
> - Rollback fields are schema-only — **no code actually invokes a rollback
>   action** when an action fails. Needs: an action executor that checks
>   `rollback_on_failure` and calls the rollback action on failure.

### Rate Limiting & Concurrency Control 🔶

- **Global rate limiter** — Prevents overwhelming external APIs
- **Per-tool concurrency** — Configurable max workers per tool (e.g., max 15
  concurrent scrapers)
- **Semaphore-based throttling** — For parallel fan-out steps
- **Action queue** — Side-effect actions are executed through a controlled queue
  with configurable parallelism

> **What exists:** `TokenBucketRateLimiter` (burst support, async `acquire()`),
> `ConcurrencyLimiter` (semaphore-based), and `ProviderRateLimiter`
> (per-provider dual limiter for requests/min + tokens/min) in
> `core/ratelimit.py`.
>
> **Gaps:**
> - None of these are instantiated or called from production code.
> - **Action queue** does not exist — needs a new `ActionQueue` class.
> - Integration points: wrap LLM provider calls with `ProviderRateLimiter`,
>   wrap tool dispatch with `ConcurrencyLimiter`, create a global
>   `TokenBucketRateLimiter` managed by the workflow engine.

### Cost Tracking & Accumulation 🔶

- Every LLM call reports token usage via a **cost callback**
- Costs accumulate per-agent and per-workflow-run
- Per-model pricing tables enable dollar-amount cost estimation
- Embedding costs are estimated separately
- Cost data is included in the workflow result payload and available via the
  observability/logging system

> **What exists:** `CostTracker` in `core/cost.py` with `UsageRecord`,
> `AgentCostSummary`, `WorkflowCostReport` data models. Per-model pricing table
> (`MODEL_PRICING`) covering OpenAI, Anthropic, and local models with prefix-match
> fallback. `ResultPayload.cost_summary` field (in `core/result_payload.py`)
> typed as `WorkflowCostReport`.
>
> **Gaps:**
> - `CostTracker.record()` is **never called** from LLM provider or agent code.
> - `ResultPayload.cost_summary` is never populated with real data.
> - Embedding cost: `openai_embeddings.py` has `estimate_cost()` but it's
>   independent of `CostTracker`.
> - Integration plan: instantiate a `CostTracker` per workflow run, pass it to
>   LLM providers as a callback, populate `ResultPayload.cost_summary` at
>   workflow completion.

---

## Prompt Template Library

> **Status: 🔶 ~25% complete.** Tone system is excellent (17 built-in tones,
> YAML extension, injection helpers). Output length guidance is done. Only 2 of
> 15 prompt categories are implemented. Prompt families and dotted-path template
> variables are not started.

System prompts are the primary mechanism for agent specialization. The framework
provides a **prompt template library**.

### Prompt Families ❌

Different LLM providers/models respond best to different prompt structures:

| Family  | Models               | Differences                            |
| ------- | -------------------- | -------------------------------------- |
| Default | GPT-4o, Claude, etc. | Standard instruction-following prompts |
| Granite | IBM Granite models   | Structured XML-style prompts           |
| Local   | Ollama, local models | Simpler, more explicit instructions    |

> Not implemented. `PromptTemplate` and `PromptLibrary` in `core/prompts.py`
> have a single format. Needs: a `PromptFamily` enum/registry, per-family
> template variants, and family auto-selection based on model name or config.

### Template Variables 🔶

Prompts support variable interpolation from the workflow state:

```
"You are working on: {task.description}. Focus on: {task.subtopic}.
Language: {config.language}. Tone: {config.tone}. Output format: {config.output_format}."
```

> **What exists:** `PromptTemplate` uses `string.Template` with `$variable`
> syntax and `safe_substitute`. Supports `required_vars` validation and variable
> discovery.
>
> **Gap:** Only flat `$variable` names work — no dotted-path resolution like
> `{task.description}` or `{config.language}`. Needs: a resolver that can
> traverse workflow state objects by dot-separated paths.

### Prompt Categories

The library includes templates for:

- Sub-task decomposition ❌
- Search query generation ❌
- Report writing (by section type) ❌
- Introduction / conclusion generation ❌
- Source curation and ranking ❌
- Draft review against guidelines 🔶 (`SYSTEM_REVIEWER` exists, generic)
- Revision with feedback ❌
- Agent role selection ❌
- **Summary generation** (`SYSTEM_SUMMARIZER`) ✅ — concise, faithful summaries
  within a token budget
- **Outline assembly** (`SYSTEM_OUTLINE_BUILDER`) ✅ — coherent outline from
  multiple section summaries
- **Action planning** (determining which actions to take) ❌
- **Action validation** (verifying action prerequisites) ❌
- **Decision framing** (structuring evaluation criteria) ❌
- **Code generation** (language-specific coding instructions) ❌
- **Incident analysis** (root cause analysis patterns) ❌

> 2 of 15 categories fully implemented, 1 partial, 12 missing. Existing
> templates also include `SYSTEM_RESEARCHER` and `SYSTEM_WRITER` (with output
> length guidance) which cover basic agent roles but not the specialized
> categories above.

### Output Length Guidance ✅

Built-in prompts include explicit length guidance to ensure agents produce
substantive output rather than terse summaries:

- **Researcher prompts:** "Aim for at least 1000 words of detailed analysis"
- **Writer prompts:** "Aim for at least 1500 words"
- **Summarizer prompts:** "at most $max_tokens tokens"
- **Outline prompts:** "Keep it under $max_tokens tokens"

These defaults work in conjunction with the `MAX_TOKENS` configuration
(default: 16000) to ensure agents have sufficient output budget.

---

## Streaming & Message Protocol

> **Status: 🔶 ~40% complete.** Core streaming channel and token-level streaming
> work. `StreamEvent` model is missing several required fields. 9 of 16 message
> types are absent. Executor I/O observation and the JSON-lines file writer for
> the dual-output pattern are not implemented.

Real-time visibility into multi-agent workflows requires a structured message
protocol.

### Message Format 🔶

```json
{
  "type": "log | output | tool_call | action | human_request | cost | error",
  "agent_id": "reviewer",
  "step_id": "step_003",
  "content": "...",
  "metadata": {
    "tokens_used": 450,
    "latency_ms": 1200,
    "model": "gpt-4o"
  },
  "timestamp": "2026-02-12T14:30:00Z"
}
```

> `StreamEvent` in `core/streaming.py` has `type` and `agent_id`. Missing:
> `step_id`, `content` (uses `token`/`data` instead), structured `metadata`
> sub-fields (`tokens_used`, `latency_ms`, `model`), and `timestamp`.

### Message Types (Extended in v2)

| Type                  | Description                                            | Status |
| --------------------- | ------------------------------------------------------ | ------ |
| `log`                 | Informational log from an agent step                   | ❌     |
| `output`              | Content produced by an agent (text, data)              | ✅     |
| `tool_call`           | A tool was invoked (with input/output)                 | ✅     |
| `action`              | A real-world action was executed or proposed            | ✅     |
| `human_request`       | The workflow is paused waiting for human input          | ❌     |
| `approval`            | A human has approved or rejected an action              | ✅     |
| `cost`                | Token/cost accounting update                           | ❌     |
| `error`               | An error occurred (with severity and recovery action)  | ✅     |
| `rollback`            | An action was rolled back                              | ❌     |
| `summary_generated`   | A summary was produced for an agent's output           | ❌     |
| `outline_generated`   | An outline was assembled from parallel item summaries  | ❌     |
| `assembly_complete`   | Code-level assembly finished                           | ❌     |
| `checkpoint_saved`    | Workflow state was checkpointed (includes checkpoint_id) | ✅   |
| `executor_invoked`    | An agent/executor step began (input data available)    | ❌     |
| `executor_completed`  | An agent/executor step finished (output data available)| ❌     |
| `request_info`        | Workflow paused for approval/feedback (tool or gate)   | ❌     |

> `StreamEventType` enum has: `OUTPUT`, `ERROR`, `CHECKPOINT_SAVED`, `APPROVAL`,
> `TOOL_CALL_START/END`, `ACTION_PROPOSED/EXECUTED`, `GATE_REQUESTED`, `TOKEN`.
> Close match exists for `human_request` as `GATE_REQUESTED` but under a
> different name.

### Executor I/O Observation (Inspired by Microsoft Agent Framework) ❌

Every agent step emits paired `executor_invoked` and `executor_completed`
events with the full input and output data. This enables observability
without modifying agent code:

```python
engine.on_event(lambda event_type, agent_id, data:
    print(f"[{event_type}] {agent_id}: {data}")
)
```

Observers see what each agent received and produced, enabling:
- **Debugging** — Inspect what state an agent saw
- **Auditing** — Record all data flowing through the workflow
- **Replay** — Reconstruct execution from the event stream
- **Testing** — Assert on agent inputs/outputs in integration tests

> Not implemented. No paired events emitted. `StreamChannel` supports fan-out
> but there is no hook in the agent execution path to emit input/output
> snapshots. Implementation: add `executor_invoked`/`executor_completed` event
> types to `StreamEventType`, then emit them in `Agent.execute()` before and
> after the core logic.

### Dual-Output Pattern 🔶

Every agent step emits to **two sinks simultaneously**:

1. **WebSocket stream** — real-time delivery to the frontend
2. **Structured log file** — persistent audit trail (JSON lines format)

> `StreamChannel` supports async fan-out to multiple subscribers (WebSocket
> side). No JSON-lines file writer exists. `core/observability.py` configures
> structlog with JSON rendering for general logging, but that is not the
> per-event audit trail the spec requires. Needs: a `JsonLinesWriter`
> subscriber that `StreamChannel` forwards events to.

### Token-Level LLM Streaming ✅

For LLM-based agents, the framework supports `stream=True` on LLM calls,
forwarding tokens through the WebSocket as they arrive.

> `StreamingAgent.stream_tokens()` in `core/streaming.py` calls
> `provider.chat_stream()` and forwards individual tokens as `TOKEN` events.

---

## Recursive Exploration Capability

> **Status: 🔶 ~70% complete.** `DeepResearcher` in `core/research.py` handles
> plan/branch/dive/merge with correct defaults. However, it is a standalone
> utility (not an orchestrator agent) and uses callbacks instead of nested
> workflow instances.

For complex problems, the framework supports **recursive multi-level
exploration** as a workflow pattern. This generalizes the "deep research"
concept from v1 to any domain.

### How It Works

1. **Plan** — Generate a breadth-first query/task tree from the main problem
2. **Branch** — For each sub-task, spawn a nested workflow
3. **Dive** — Each branch can recursively generate further sub-tasks up to a
   configurable depth
4. **Merge** — Aggregate findings and results from all branches

### Domain Examples

- **Research:** Recursively explore subtopics of a broad question
- **Code analysis:** Recursively trace dependencies and call chains
- **Incident investigation:** Recursively follow causal chains
- **Decision analysis:** Recursively evaluate sub-decisions and dependencies

### Configuration ✅

| Parameter           | Default | Description                               |
| ------------------- | ------- | ----------------------------------------- |
| `breadth`           | 3       | Number of sub-tasks per level             |
| `depth`             | 2       | Maximum recursion depth                   |
| `concurrency`       | 4       | Max parallel branches                     |
| `max_context_words` | 25000   | Context window budget across all branches |

> Implemented via `DeepResearchConfig` in `core/research.py` — all defaults match.

### Implementation 🔶

Recursive exploration is modeled as an `orchestrator` agent that creates nested
workflow instances. Each branch spawns a fresh agent team and merges results
back into the parent state. Progress tracking reports completion percentage
across all branches.

> **What exists:** `DeepResearcher` class with `_generate_sub_queries()`,
> `_research_branch()` (concurrent via `asyncio.gather()`), recursive depth
> control, and `merge_findings()` using `ContextCompressor`.
>
> **Gaps:**
> - `DeepResearcher` is a standalone utility, not an agent subclass — it
>   doesn't participate in the agent registry or workflow graph.
> - Branches call a pluggable `research_fn` callback, not nested `Workflow`
>   instances. To match spec: create an `OrchestratorAgent` subclass that
>   wraps `DeepResearcher` and spawns per-branch workflows.
> - No progress percentage tracking across branches.

---

[Next: Document Input Pipeline >](12-document-input.md)
