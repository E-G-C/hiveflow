[< Back to Index](README.md)

---

# 14 — Task Preprocessing and Large-Input Context Management

> **Version:** 1.0
> **Date:** 2026-03-05
> **Status:** Draft
> **Dependencies:** [09-context-management](09-context-management.md),
> [12-document-input](12-document-input.md),
> [13-dynamic-agent-collaboration](13-dynamic-agent-collaboration.md)

---

## Problem Statement

HiveFlow's context management strategy (spec 09) is built on a
**divide-and-conquer** principle: each agent receives ~3K-4K tokens of focused
context, agent outputs are summarized for downstream agents, and final assembly
is performed at the code level. This works well when the **task description**
is compact (a few sentences) and agent outputs are the primary source of
context growth.

However, when the task itself contains or references **large input data** —
a 16,000-word transcript, a lengthy codebase, a multi-page contract, a
dataset — the divide-and-conquer invariant breaks down completely:

### Observed Failure Mode

A user passes a 4,800-word processing prompt plus a 16,000-word WEBVTT
transcript as the task. The full-auto pipeline generates a 3-agent team
(editor → reviewer → writer). Execution results:

| Agent | Input tokens | Output words | Observation |
|-------|-------------|-------------|-------------|
| editor | 67,881 | 146 | Overwhelmed — produced a thin summary |
| reviewer | 68,014 | 589 | Reviewed the summary, not the transcript |
| writer | 68,836 | 589 | Rewrote the review, duplicating content |
| **Total** | **206,562** | **589** | 206K tokens for 589 words of low-quality output |

The transcript was sent to the LLM **three times** (once per agent), consuming
206K tokens while producing a superficial, repetitive 589-word output that
covered only a fraction of the source material.

### Root Causes

**1. No separation of instructions from data in `state["task"]`**

The processing prompt (instructions) and the transcript (data) are
concatenated into a single string stored in `state["task"]`.
`_summarize_state()` (agent.py:740-741) injects the entire value into
every agent's user message:

```python
if "task" in state:
    parts.append(f"Task: {state['task']}")  # Entire 21K words, every time
```

**2. The SummaryGenerator only compresses agent outputs, not inputs**

The summarizer (spec 09) compresses what agents *produce*. The task blob
— often the largest item in context — passes through untouched to every
agent regardless of that agent's role.

**3. The DocumentPipeline is disconnected from `state["task"]`**

The document input pipeline (spec 12) provides chunking, scoping, and
budget enforcement — but only for content loaded via
`HiveFlow.run(documents=[...])`. Content embedded in `state["task"]`
bypasses all of this infrastructure.

**4. `context_budget` can't help when the task consumes the budget**

The context budget mechanism (spec 09) truncates assembled context. But
since `state["task"]` is always the *first* item included, a 67K-token
task leaves no room for agent outputs — the budget is consumed before
useful context is added.

**5. Downstream agents receive content irrelevant to their role**

A reviewer checking a writer's output does not need the raw transcript.
A writer refining a draft does not need the processing instructions meant
for the orchestrator. Yet every agent receives everything.

---

## Objective

Add a **task preprocessing** layer that automatically detects large task
inputs, separates instructions from data, and routes context intelligently
so that:

1. No agent receives context irrelevant to its role
2. Large data is chunked and selectively distributed
3. The existing divide-and-conquer invariant (~3K-4K tokens per agent)
   is maintained even for large inputs
4. The system works generically for any input type (transcripts, code,
   contracts, datasets) without task-specific logic
5. Backward compatibility: small tasks (< threshold) pass through unchanged

---

## Core Concepts

### Instructions vs. Data

Every task implicitly contains two concerns:

| Concern | Example | Who needs it |
|---------|---------|-------------|
| **Instructions** | "Transform this transcript into Markdown docs following these rules..." | The planner/orchestrator (to decide what to do) |
| **Data** | The 16K-word WEBVTT transcript | The processing agents (to do the actual work) |

Today, both are mashed into `state["task"]`. The preprocessing layer
separates them:

```python
state = {
    "task": "Transform transcript into docs...",     # Compact (instructions only)
    "task_instructions": "Transform transcript...",  # Same as task (explicit key)
    "task_data": [                                   # Chunked source material
        {"chunk_id": "chunk_0", "content": "...", "topic": "CI/CD overview"},
        {"chunk_id": "chunk_1", "content": "...", "topic": "Security model"},
        ...
    ],
    "task_data_summary": "A 1-hour meeting covering GitHub Actions, ...",
    "task_data_manifest": {                          # Metadata for planning
        "source_type": "transcript",
        "total_words": 16017,
        "chunk_count": 8,
        "topics": ["CI/CD", "security", "agentic workflows", ...]
    },
}
```

### The Preprocessing Decision

Preprocessing activates when the task content exceeds a threshold
**derived from the model's context window**. Below the threshold,
behavior is unchanged (full backward compatibility).

```
effective_threshold = model_context_tokens * TASK_CONTEXT_RATIO / TOKENS_PER_WORD
if word_count(state["task"]) > effective_threshold:
    run preprocessing pipeline
else:
    pass through unchanged (existing behavior)
```

#### Model-Derived Threshold

Different models have vastly different context capacities. A fixed word
threshold cannot serve all cases — 3,000 words is half the context of an
8K model but irrelevant noise for a 200K model. The threshold is therefore
computed as a **fraction of the model's context window**:

```python
effective_threshold = int(model_context_tokens * task_context_ratio / tokens_per_word)
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `model_context_tokens` | Looked up from model | The model's total context window in tokens |
| `task_context_ratio` | `0.15` | Maximum fraction of context the task should consume. At 15%, the remaining 85% is reserved for system prompt, agent outputs, summaries, and LLM response. |
| `tokens_per_word` | `1.35` | Average tokens per word (English text). |

**Example thresholds by model:**

| Model | Context window | 15% budget | Threshold (words) |
|-------|---------------|------------|-------------------|
| gpt-4o-mini | 128K | 19,200 tokens | ~14,200 |
| gpt-4o | 128K | 19,200 tokens | ~14,200 |
| gpt-3.5-turbo | 16K | 2,400 tokens | ~1,800 |
| claude-3-haiku | 200K | 30,000 tokens | ~22,200 |
| Small/local (8K) | 8K | 1,200 tokens | ~890 |

This means:
- A small model (8K context) preprocesses tasks as short as ~900 words
- A large model (128K+ context) tolerates much larger tasks before
  preprocessing triggers
- The ratio is tunable per team if needed

**However**, the threshold alone doesn't determine whether preprocessing
*improves* quality. Even a 128K-context model degrades when every agent
in a 7-agent pipeline receives 67K tokens of irrelevant source material.
The real cost is `N_agents × task_tokens`, not `task_tokens` alone.
Therefore, when `agent_count > 1`, an additional **pipeline multiplier**
is applied:

```python
pipeline_adjusted = effective_threshold / max(1, agent_count * pipeline_factor)
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `pipeline_factor` | `0.3` | Reflects the cost multiplier of repeating context across agents. Higher = more aggressive preprocessing. |

With 7 agents and the default `pipeline_factor=0.3`:
- 128K model: `14,200 / (7 × 0.3)` ≈ **6,760 words** — still generous
  but prevents the 21K-word flooding seen in the observed failure mode
- 8K model: `890 / (7 × 0.3)` ≈ **424 words** — very aggressive, as
  expected for a tiny context shared across many agents

#### Model Context Window Lookup

The `TaskPreprocessor` resolves the model's context window via a
**model registry** — a lookup table mapping model family patterns to
context sizes. This avoids requiring an API call to discover model
capabilities.

```python
MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-4": 8_192,
    "gpt-3.5-turbo": 16_385,
    "o3-mini": 200_000,
    "o3": 200_000,
    "o1": 200_000,
    "o1-mini": 128_000,
    "claude-3-opus": 200_000,
    "claude-3-sonnet": 200_000,
    "claude-3-haiku": 200_000,
    "claude-3.5-sonnet": 200_000,
    "claude-opus-4": 200_000,
    "claude-sonnet-4": 200_000,
}
DEFAULT_CONTEXT_WINDOW: int = 16_000  # Conservative fallback for unknown models
```

Lookup uses prefix matching (`"gpt-4o-mini-2024-07-18"` matches
`"gpt-4o-mini"`). When no match is found, `DEFAULT_CONTEXT_WINDOW`
provides a conservative fallback that triggers preprocessing early.

The registry can be extended at runtime via `HiveFlowConfig` or by
the `LLMProvider` interface — providers that know their model's context
size can expose it via an optional `context_window` property.

#### Manual Override

The model-derived threshold can always be overridden explicitly:

```python
TaskPreprocessor(
    llm_provider=provider,
    model="gpt-4o-mini",
    threshold_override=5000,  # Fixed word count, ignores model lookup
)
```

Or via config: `TASK_PREPROCESS_THRESHOLD=5000` (0 = disabled).

---

## Architecture

### Component: `TaskPreprocessor`

A new class in `hiveflow/core/task_preprocessor.py` that runs before
workflow execution begins. It is invoked automatically by the
`WorkflowEngine` (or `HiveFlow.run()`) when the task exceeds the size
threshold.

```
                        ┌─────────────────────────────┐
              task      │     TaskPreprocessor         │
   state["task"] ──────►│                              │
                        │  1. Detect: is this large?   │
                        │  2. Separate instructions     │
                        │     from data                │
                        │  3. Chunk the data            │
                        │  4. Summarize for routing     │
                        │  5. Build chunk manifest      │
                        │                              │
                        └──────────┬──────────────────┘
                                   │
      ┌────────────────────────────┼────────────────────────┐
      │                            │                        │
      ▼                            ▼                        ▼
 state["task"]              state["task_data"]     state["task_data_summary"]
 (instructions only)        (chunked content)      (compact summary for routing)
```

#### Step 1: Size Detection

```python
word_count = len(state["task"].split())
if word_count <= self.threshold:
    return state  # Pass through unchanged
```

#### Step 2: Instruction/Data Separation

The task content is split into an **instructions** section (what the user
wants done) and a **data** section (the content to process). This is
format-agnostic — the same logic works for transcripts, code, contracts,
meeting notes, or any other content type.

**Strategy: structural heuristics first, LLM fallback second.**

The separator identifies the boundary by scanning for generic structural
markers that indicate "instructions end, bulk content begins." These are
content-agnostic patterns common across many input formats:

| Marker type | Pattern | Example |
|-------------|---------|---------|
| Fenced code block | ` ``` ` followed by large content | Code, transcripts, data dumps wrapped in fences |
| Horizontal rule + heading | `---` followed by `## Target File:` or `## Content:` or similar | Multi-section task files with explicit data sections |
| Sharp size gradient | Paragraph N has < 200 words, paragraph N+1 has > 1,000 words | Instructions are short; data is long |
| Explicit labels | `## Input`, `## Source`, `## Data`, `## Document`, `## Transcript`, `## Content` | User-labeled sections |

The heuristic does **not** inspect the content format (WEBVTT timestamps,
Python syntax, JSON structure, etc.). It only looks for structural
boundaries between a short "instruction" section and a long "content"
section. This keeps it generic across all input types.

**Size gradient heuristic** (most reliable and fully generic): When no
explicit markers are found, the separator divides the text into
paragraphs (split on double newlines) and finds the point where short
instructional paragraphs transition to long content paragraphs. The
boundary is the last paragraph whose cumulative word count stays below
a fraction of the total (e.g., first 20% of words = instructions,
remaining 80% = data).

**LLM fallback**: When no structural boundary is detectable (e.g., the
entire task is a single continuous block of text with no markers or size
gradient), use a fast LLM call:

```
Given this task input, identify where the INSTRUCTIONS
(what the user wants done) end and the DATA (content to process) begins.
Return JSON: {"split_index": <char_index>}
If the content is entirely instructions (no data to process),
return {"split_index": -1}
```

**No-data case**: Some tasks are purely instructional with no embedded
data (e.g., "Write a marketing plan for product X"). When neither
heuristics nor the LLM find a data section, preprocessing still
activates — it stores the full text as `task_instructions` and sets
`task_data` to an empty list. This enables the downstream context
benefit (agents receive `task_instructions` instead of the full blob)
even when there's nothing to chunk.

#### Step 3: Chunking

Reuse the existing `chunk_text()` utility from `DocumentPipeline` to split
the data section into LLM-sized chunks. The default chunking strategy is
**word-count-based with paragraph-boundary preference** — the existing
`chunk_text()` already implements this. No format-specific logic is
required in the core path.

```python
chunks = chunk_text(
    data_section,
    chunk_size=chunk_target_words,
    chunk_overlap=chunk_overlap_words,
)
```

Chunk boundaries prefer natural breakpoints in this priority order:
1. Double-newline paragraph breaks
2. Single-newline line breaks
3. Sentence boundaries (period + space)
4. Word boundaries (fallback)

This ordering produces coherent chunks for any prose, code, structured
data, or mixed content — without inspecting the format.

**Chunk target size** is also model-derived, using the same context
window lookup:

```python
chunk_target_tokens = int(model_context_tokens * CHUNK_CONTEXT_RATIO)
chunk_target_words = int(chunk_target_tokens / tokens_per_word)
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `CHUNK_CONTEXT_RATIO` | `0.10` | Target chunk size as fraction of model context. At 10%, each chunk fills ~10% of the model's window, leaving room for instructions, prior summaries, and output. |
| `chunk_overlap_ratio` | `0.10` | Overlap as fraction of chunk size (10% of chunk). |

**Example chunk sizes by model:**

| Model | Context | 10% chunk budget | Chunk size (words) |
|-------|---------|-----------------|-------------------|
| gpt-4o-mini | 128K | 12,800 tokens | ~9,500 |
| gpt-3.5-turbo | 16K | 1,600 tokens | ~1,200 |
| Small/local (8K) | 8K | 800 tokens | ~600 |

This ensures chunks are appropriately sized for the model that will
process them — small models get small chunks, large models get larger
ones.

**Pluggable chunking** (Phase 3): Format-aware chunking strategies
(e.g., splitting code at function boundaries, splitting transcripts at
speaker changes) can be registered as optional plugins. These are not
required for correctness — the generic word-count chunker works for all
formats — but can improve chunk coherence for specific content types.

#### Step 4: Summarization

Generate a compact summary of the data content (~200 words) using the
fast LLM tier. This summary is used by planning/routing agents that need
awareness of the content without seeing it in full.

#### Step 5: Manifest Generation

Build a structured manifest describing the chunks:

```python
{
    "total_words": 16017,
    "chunk_count": 8,
    "model_context_tokens": 128000,
    "effective_threshold": 6760,
    "chunks": [
        {"chunk_id": "chunk_0", "words": 2100, "topic_hint": "..."},
        {"chunk_id": "chunk_1", "words": 1850, "topic_hint": "..."},
        ...
    ]
}
```

The `topic_hint` field is generated by the summarization step (Step 4)
as a one-line description of each chunk's content. It is used by
planning agents to assign chunks to workers without reading the full
chunk content.

---

### Modified: `_summarize_state()` Context Assembly

The agent's `_summarize_state()` method (agent.py) is updated to be
preprocessing-aware:

```python
# Current behavior (unchanged for small tasks):
if "task" in state:
    parts.append(f"Task: {state['task']}")

# New behavior (when preprocessing has run):
if "task_instructions" in state:
    parts.append(f"Task: {state['task_instructions']}")
    if "task_data_summary" in state:
        parts.append(f"\nSource material ({state['task_data_manifest']['total_words']} words, "
                     f"{state['task_data_manifest']['chunk_count']} sections): "
                     f"{state['task_data_summary']}")
elif "task" in state:
    parts.append(f"Task: {state['task']}")
```

This means:
- **Planning/routing agents** see: instructions + data summary (~200 words)
- **Processing agents** see: instructions + their assigned chunk(s)
- **Reviewers** see: instructions + the output they're reviewing
- **No agent** sees the full 16K-word data blob unless explicitly requested

---

### Modified: WorkflowEngine Integration

The preprocessing step is called automatically at the start of
`WorkflowEngine.execute()`:

```python
async def execute(self, agents, initial_state, ...):
    state = dict(initial_state)

    # Task preprocessing for large inputs
    if self._task_preprocessor is not None:
        state = await self._task_preprocessor.preprocess(state)

    # ... existing execution logic
```

The preprocessor is created by `TeamGenerator.build()` or can be
configured manually:

```python
engine = WorkflowEngine(
    steps,
    task_preprocessor=TaskPreprocessor(
        llm_provider=provider,
        model="gpt-4o-mini",       # Used for context window lookup + summary calls
        # All other params derived from model. Override if needed:
        # threshold_override=5000,  # Fixed word count
        # task_context_ratio=0.20,  # More generous task budget
    ),
)
```

---

### Chunk Routing: How Agents Get Their Data

Three strategies for delivering chunk content to processing agents:

#### Strategy 1: Planner-Assigned Chunks (collaboration mode)

When collaboration is enabled, the planner/orchestrator sees the manifest
and assigns chunks to workers via delegation:

```python
# The orchestrator's plan:
delegate_task(
    task="Process the CI/CD section of the transcript",
    delegate_to="auto",
    context={"task_data_chunk": "chunk_0"}  # Only this chunk
)
```

The delegated agent receives only `chunk_0` in its context — not the
full transcript.

#### Strategy 2: Fan-Out Over Chunks (static workflow)

For non-collaboration workflows, the engine can automatically fan-out
over chunks when a step is configured for it:

```yaml
workflow:
  steps:
    - agent: processor
      type: parallel_fan_out
      fan_out_source: task_data  # Fan-out over preprocessed chunks
      next: assembler
```

Each parallel instance of `processor` receives one chunk in
`state["current_item"]` — the same mechanism used today for
parallel fan-out, now applied to task data.

#### Strategy 3: Document Retriever (on-demand)

Agents with the `document_retriever` tool can pull specific chunks
by topic or by ID:

```json
{
    "name": "retrieve_task_data",
    "parameters": {
        "query": "security model",
        "max_chunks": 2
    }
}
```

This leverages the existing `DocumentRetrieverTool` infrastructure.

---

### Automatic Workflow Adaptation

When preprocessing detects large input and the team includes an
orchestrator with collaboration enabled, the system can suggest or inject
a planning-first workflow:

1. **Planner phase**: Orchestrator receives instructions + data summary +
   manifest. Creates a plan with chunk-to-agent assignments.
2. **Processing phase**: Workers receive their assigned chunks via
   delegation. Run in parallel where no dependencies exist.
3. **Assembly phase**: Writer/assembler merges worker outputs.
4. **Review phase**: Reviewer checks the assembled output (not the raw
   data).

This is a recommendation, not a requirement — the system should work
without it, just less efficiently.

---

## Configuration

### `HiveFlowConfig` Additions

```python
# Task preprocessing
TASK_PREPROCESS_THRESHOLD: int = 0         # Fixed word override. 0 = use model-derived threshold (default)
TASK_CONTEXT_RATIO: float = 0.15           # Max fraction of model context for task content
TASK_PIPELINE_FACTOR: float = 0.3          # Pipeline multiplier for multi-agent repeats
TASK_CHUNK_CONTEXT_RATIO: float = 0.10     # Chunk size as fraction of model context
TASK_CHUNK_OVERLAP_RATIO: float = 0.10     # Overlap as fraction of chunk size
TASK_PREPROCESS_DISABLED: bool = False      # Set True to fully disable preprocessing
```

### Model Context Window Resolution Order

1. `LLMProvider.context_window` property (if implemented by the provider)
2. `MODEL_CONTEXT_WINDOWS` lookup table (built-in, prefix-matched)
3. `DEFAULT_CONTEXT_WINDOW` fallback (16,000 tokens — conservative)

Providers that wrap a known service (Azure OpenAI, Anthropic) can
implement the `context_window` property to return the exact value from
the deployment metadata. This is optional — the lookup table covers
all common models.

### Team-Level Override

```json
{
    "team_name": "document_processor",
    "task_preprocessing": {
        "enabled": true,
        "threshold_override": null,
        "task_context_ratio": 0.15,
        "chunk_context_ratio": 0.10
    }
}
```

A team can override any parameter. `threshold_override` (integer word
count) bypasses the model-derived calculation entirely when set. Setting
`enabled: false` disables preprocessing for that team regardless of task
size.

---

## Backward Compatibility

| Scenario | Behavior |
|----------|----------|
| Task < threshold words | Zero change. `state["task"]` used as-is. |
| Task >= threshold, preprocessing disabled | Zero change. Existing behavior. |
| Task >= threshold, preprocessing enabled | `state["task"]` replaced with instructions. Data available via `task_data`, `task_data_summary`, `task_data_manifest`. |
| Code reading `state["task"]` | Still works — `task` is always present (contains instructions when preprocessing runs, full content when it doesn't). |
| Agents without `task_data` awareness | They receive instructions + data summary. Degraded but functional. |

The key invariant: **`state["task"]` always exists and is always small
enough to be useful context.** It is never empty. When preprocessing runs,
it contains the instructions. When it doesn't, it contains the original
content (unchanged).

---

## Token Budget Analysis

### Before (Current Behavior)

```
Task content:  21,000 words → ~67K tokens
Agents:        3 (sequential)
Per-agent:     67K tokens input
Total:         201K tokens
Useful output: 589 words
Efficiency:    0.3%
```

### After (With Preprocessing)

```
Task instructions:  500 words → ~700 tokens
Data summary:       200 words → ~300 tokens
Chunks:             8 × 2,000 words → 8 × ~2,700 tokens each
Preprocessing:      1 LLM call for separation + 1 for summary → ~5K tokens

Planner:       700 (instructions) + 300 (summary) = ~1K tokens
8 Workers:     700 (instructions) + 2,700 (chunk) = ~3.4K tokens each
Assembler:     700 + 8 × 300 (summaries) = ~3.1K tokens
Reviewer:      700 + assembled output = ~4K tokens

Total:         5K + 1K + (8 × 3.4K) + 3.1K + 4K = ~40K tokens
Useful output: 8 × ~500 words per chunk = ~4,000 words
Efficiency:    10% (33× improvement)
```

---

## Relationship to Existing Specs

### vs. Context Management (Spec 09)

Spec 09 defines the divide-and-conquer pattern and summary propagation
for **agent outputs**. This spec extends the same principles to **task
inputs**. The preprocessing layer ensures that the task content obeys the
same ~3K-4K token budget that spec 09 mandates for agent context.

### vs. Document Input Pipeline (Spec 12)

Spec 12 provides the infrastructure (chunking, scoping, budget
enforcement) but only for documents loaded via the `documents` parameter.
This spec bridges the gap: large content in `state["task"]` is
automatically routed through the same chunking infrastructure.

Implementation note: `TaskPreprocessor` should reuse
`DocumentPipeline._chunk_document()` and `chunk_text()` rather than
duplicating chunking logic.

### vs. Dynamic Collaboration (Spec 13)

Spec 13 enables runtime delegation and planning. This spec provides the
**data substrate** that makes collaboration effective for large inputs:
instead of delegating the entire 67K-token context, the orchestrator
delegates focused subtasks with compact chunk references.

### vs. Fan-Out (Spec 02)

Parallel fan-out already supports data-parallel execution over items.
This spec extends that to support fan-out over preprocessed task data
chunks, using the same `current_item` / `parallel_items` state
conventions.

---

## Implementation Phases

### Phase 1 — Core Preprocessing

**Deliverables:**
1. `TaskPreprocessor` class with model-derived threshold computation,
   generic structural boundary detection, word-count chunking, and
   summarization
2. `MODEL_CONTEXT_WINDOWS` lookup table with prefix matching
3. Optional `context_window` property on `LLMProvider` interface
4. State key conventions: `task_instructions`, `task_data`,
   `task_data_summary`, `task_data_manifest`
5. Updated `_summarize_state()` to prefer `task_instructions` over `task`
   when available
6. Integration point in `WorkflowEngine.execute()`
7. Configuration: ratios, override threshold, disable flag
8. Unit tests: threshold computation per model, boundary detection
   (structural markers, size gradient, LLM fallback), chunking,
   summary generation, backward compatibility (small tasks unchanged)

### Phase 2 — Intelligent Routing

**Deliverables:**
1. Fan-out over `task_data` chunks (parallel_fan_out source)
2. Chunk reference injection in `DelegateTaskTool` context
3. Integration with `DocumentRetrieverTool` for on-demand chunk access
4. Integration tests: large document processing, large codebase review,
   mixed-content task handling

### Phase 3 — Adaptive Workflow Generation and Pluggable Chunking

**Deliverables:**
1. `TeamGenerator.generate_team_from_llm()` awareness of preprocessed
   data (manifest informs team composition — e.g., "8 chunks → create
   8 workers + 1 assembler")
2. Automatic workflow adaptation: when large input is detected and
   collaboration is enabled, inject a planner-first workflow
3. Pluggable chunking backend interface (`ChunkingStrategy`) for
   format-aware splitting (e.g., code at function boundaries, structured
   documents at heading boundaries). The generic word-count chunker remains
   the default; format-specific strategies are optional plugins.
4. End-to-end example demonstrating the full pipeline with a large input

---

## Testing Strategy

### Unit Tests

- `TaskPreprocessor`: threshold detection (below/above), instruction/data
  separation (heuristic markers), chunking (word count, overlap), summary
  generation, manifest structure
- `_summarize_state()`: prefers `task_instructions` when present, falls
  back to `task` when absent, includes `task_data_summary` for non-processing
  agents
- Backward compatibility: small tasks unchanged, no preprocessing keys
  in state when below threshold

### Integration Tests

- Large transcript: preprocessing → planning → chunk delegation → assembly
- Large codebase: preprocessing → parallel fan-out → review
- Mixed content: task with both instructions and inline data
- Threshold boundary: task at exactly threshold word count

### Performance Tests

- Token consumption: verify total tokens < threshold (vs. baseline)
- Output quality: verify output covers all chunks (vs. baseline covering
  only a fraction)

---

## Open Questions

1. **Should preprocessing be opt-in or opt-out?** Current proposal:
   opt-out (runs automatically when threshold exceeded, can be disabled
   via `TASK_PREPROCESS_DISABLED=true`). Alternative: opt-in via team
   config.

2. **Should chunks be stored in `state["task_data"]` (list in state)
   or in the existing `state["documents"]` infrastructure?** Using
   `documents` reuses existing scoping and retrieval infrastructure but
   may conflate user-supplied documents with preprocessed task data.

3. **Should `LLMProvider` expose `context_window` as a required or
   optional property?** Making it required forces all provider
   implementations to update. Making it optional means the lookup table
   is always the primary path and providers are a bonus source. Current
   proposal: optional property with `None` default.

4. **Pipeline factor calibration**: The `pipeline_factor=0.3` is a
   reasonable starting point but may need empirical tuning. Should this
   be exposed as a user-facing config or kept as an internal constant?

---

[< Back to Index](README.md)
