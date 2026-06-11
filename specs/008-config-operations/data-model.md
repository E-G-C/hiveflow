# Data Model: Configuration & Operations

**Feature**: 008-config-operations  
**Date**: 2026-02-27

---

## Entities

### HiveFlowConfig (extended)

The existing pydantic-settings `BaseSettings` model in `core/config.py`. New fields are additive.

| Field | Type | Default | Category | Status |
|-------|------|---------|----------|--------|
| `FAST_LLM` | `str` | `"openai:gpt-4o-mini"` | LLM | Exists |
| `SMART_LLM` | `str` | `"openai:gpt-4o"` | LLM | Exists |
| `STRATEGIC_LLM` | `str` | `"openai:o3-mini"` | LLM | Exists |
| `LLM_TEMPERATURE` | `float` | `0.7` | LLM | Exists |
| `MAX_TOKENS` | `int` | `16000` | LLM | Exists |
| `EMBEDDING_PROVIDER` | `str` | `"openai"` | Embedding | Exists |
| `EMBEDDING_MODEL` | `str` | `"text-embedding-3-small"` | Embedding | Exists |
| `RETRIEVERS` | `str` | `"tavily"` | Retrieval | Exists |
| `MAX_SEARCH_RESULTS_PER_QUERY` | `int` | `5` | Retrieval | Exists |
| `SCRAPER` | `str` | `"bs"` | Scraping | Exists |
| `MAX_SCRAPER_WORKERS` | `int` | `4` | Scraping | Exists |
| `SCRAPER_RATE_LIMIT_DELAY` | `float` | `0.5` | Scraping | Exists |
| `REPORT_FORMAT` | `str` | `"markdown"` | Output | Exists |
| `LANGUAGE` | `str` | `"english"` | Output | Exists |
| `TONE` | `str` | `"objective"` | Output | Exists |
| `PUBLISH_FORMATS` | `list[str]` | `[]` | Output | Exists |
| `OUTPUT_DIR` | `str` | `"./output"` | Output | Exists |
| `DEEP_RESEARCH_BREADTH` | `int` | `3` | Research | Exists |
| `DEEP_RESEARCH_DEPTH` | `int` | `2` | Research | Exists |
| `DEEP_RESEARCH_CONCURRENCY` | `int` | `4` | Research | Exists |
| `ENABLE_COST_TRACKING` | `bool` | `True` | Cost | Exists |
| **`SOURCE_MODE`** | `Literal["web","local","hybrid","cloud","mcp","custom"]` | `"web"` | Source | **New** |
| **`DOC_PATH`** | `str \| None` | `None` | Source | **New** |
| **`DEFAULT_ACTION_POLICY`** | `Literal["deny","allow","dry_run"]` | `"deny"` | Actions | **New** |
| **`ENABLE_ROLLBACK`** | `bool` | `False` | Actions | **New** |
| **`ACTION_TIMEOUT`** | `int` | `30` | Actions | **New** |
| **`MCP_STRATEGY`** | `Literal["disabled","fast","deep"]` | `"disabled"` | MCP | **New** |
| **`MCP_SERVERS`** | `list[dict]` | `[]` | MCP | **New** |
| **`MCP_AUTO_TOOL_SELECTION`** | `bool` | `True` | MCP | **New** |

### StreamEvent (extended)

Structured event emitted during workflow execution.

| Field | Type | Required | Status |
|-------|------|----------|--------|
| `type` | `StreamEventType` | Yes | Exists |
| `agent_id` | `str \| None` | No | Exists |
| `token` | `str \| None` | No | Exists (for TOKEN type) |
| `data` | `Any \| None` | No | Exists |
| **`step_id`** | `str \| None` | No | **New** |
| **`content`** | `str \| None` | No | **New** |
| **`metadata`** | `EventMetadata \| None` | No | **New** |
| **`timestamp`** | `datetime` | Yes | **New** (auto-set) |

### EventMetadata (new)

Structured metadata sub-object for stream events.

| Field | Type | Required |
|-------|------|----------|
| `tokens_used` | `int \| None` | No |
| `latency_ms` | `float \| None` | No |
| `model` | `str \| None` | No |
| `cost_usd` | `float \| None` | No |

### StreamEventType (extended enum)

| Value | Status | Maps to spec |
|-------|--------|-------------|
| `TOKEN` | Exists | token streaming |
| `OUTPUT` | Exists | output |
| `ERROR` | Exists | error |
| `TOOL_CALL_START` | Exists | tool_call (start) |
| `TOOL_CALL_END` | Exists | tool_call (end) |
| `ACTION_PROPOSED` | Exists | action (proposed) |
| `ACTION_EXECUTED` | Exists | action (executed) |
| `APPROVAL` | Exists | approval |
| `GATE_REQUESTED` | Exists | request_info |
| `CHECKPOINT_SAVED` | Exists | checkpoint_saved |
| `AGENT_START` | Exists | — |
| `AGENT_END` | Exists | — |
| `STEP_START` | Exists | — |
| `STEP_END` | Exists | — |
| `STATE_UPDATE` | Exists | — |
| `WORKFLOW_START` | Exists | — |
| `WORKFLOW_END` | Exists | — |
| **`LOG`** | **New** | log |
| **`HUMAN_REQUEST`** | **New** | human_request |
| **`COST`** | **New** | cost |
| **`ROLLBACK`** | **New** | rollback |
| **`SUMMARY_GENERATED`** | **New** | summary_generated |
| **`OUTLINE_GENERATED`** | **New** | outline_generated |
| **`ASSEMBLY_COMPLETE`** | **New** | assembly_complete |
| **`EXECUTOR_INVOKED`** | **New** | executor_invoked |
| **`EXECUTOR_COMPLETED`** | **New** | executor_completed |

### PromptTemplate (extended)

| Field | Type | Required | Status |
|-------|------|----------|--------|
| `name` | `str` | Yes | Exists |
| `template` | `str` | Yes | Exists |
| `required_vars` | `list[str]` | No | Exists |
| **`category`** | `PromptCategory` | No | **New** |
| **`family`** | `PromptFamily` | No | **New** (default: `default`) |

### PromptFamily (new enum)

| Value | Target Models | Prompt Style |
|-------|--------------|-------------|
| `default` | GPT-4o, Claude, Gemini | Standard instruction-following |
| `granite` | IBM Granite | Structured XML-style |
| `local` | Ollama, local models | Simpler, explicit instructions |

### PromptCategory (new enum)

15 categories: `sub_task_decomposition`, `search_query_generation`, `report_writing`, `intro_conclusion`, `source_curation`, `draft_review`, `revision_feedback`, `agent_role_selection`, `summary_generation`, `outline_assembly`, `action_planning`, `action_validation`, `decision_framing`, `code_generation`, `incident_analysis`

### ActionQueue (new)

| Field | Type | Default |
|-------|------|---------|
| `max_concurrency` | `int` | From `config.ACTION_TIMEOUT` context |
| `timeout` | `float` | `30.0` |
| `enable_rollback` | `bool` | `False` |

### ResilientLLMProvider (new wrapper)

| Field | Type | Description |
|-------|------|-------------|
| `provider` | `LLMProvider` | Underlying provider to wrap |
| `fallback_chain` | `FallbackChain` | Auto-built from config tiers |
| `circuit_breaker` | `CircuitBreaker` | Per-provider circuit breaker |
| `rate_limiter` | `ProviderRateLimiter` | Global per-process limiter |
| `cost_tracker` | `CostTracker` | Per-workflow cost accumulator |

### UsageRecord (exists in cost.py)

| Field | Type |
|-------|------|
| `model` | `str` |
| `provider` | `str` |
| `prompt_tokens` | `int` |
| `completion_tokens` | `int` |
| `total_tokens` | `int` |
| `estimated_cost_usd` | `float` |
| `agent_id` | `str` |
| `timestamp` | `datetime` |

---

## Relationships

```
HiveFlowConfig ──creates──> ResilientLLMProvider
ResilientLLMProvider ──wraps──> LLMProvider (existing protocol)
ResilientLLMProvider ──uses──> FallbackChain, CircuitBreaker, ProviderRateLimiter, CostTracker
Agent ──uses──> ResilientLLMProvider (instead of raw LLMProvider)
Agent ──emits──> StreamEvent (EXECUTOR_INVOKED / EXECUTOR_COMPLETED)
StreamChannel ──fans-out──> StreamConsumer (existing), JsonLinesWriter (new)
ActionQueue ──executes──> Action (from schema.py)
OrchestratorAgent ──delegates──> DeepResearcher
OrchestratorAgent ──emits──> StreamEvent (progress)
PromptLibrary ──contains──> PromptTemplate (with category + family)
```

---

## State Transitions

### CircuitBreaker (exists — documented for reference)

```
CLOSED ──(failure_count >= threshold)──> OPEN
OPEN ──(recovery_timeout elapsed)──> HALF_OPEN
HALF_OPEN ──(success)──> CLOSED
HALF_OPEN ──(failure)──> OPEN
```

### Action Lifecycle (new)

```
PENDING ──(slot available)──> EXECUTING
EXECUTING ──(success)──> COMPLETED
EXECUTING ──(failure + rollback enabled)──> ROLLING_BACK
EXECUTING ──(failure + no rollback)──> FAILED
EXECUTING ──(timeout)──> TIMED_OUT
ROLLING_BACK ──(success)──> ROLLED_BACK
ROLLING_BACK ──(failure)──> ROLLBACK_FAILED
```
