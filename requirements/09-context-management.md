[< Back to Index](README.md)

---

## Context Management Strategy

The framework's ability to produce outputs far larger than any single LLM
context window is one of its most important capabilities. This is achieved
through a **divide-and-conquer pattern**.

### The Divide-and-Conquer Pattern

No individual LLM call exceeds a small token budget, yet the combined output
can span tens of thousands of words (or coordinate dozens of actions):

1. **Decompose** — The orchestrator breaks the problem into N independent
   sub-tasks
2. **Fan-out** — Each sub-task is handled independently, in parallel, by
   separate agent instances
3. **Isolated context** — Each worker receives only its own context (~3K–4K
   tokens), not the full picture
4. **Code-level assembly** — The final output is stitched together by Python
   code (not LLM generation) — programmatic assembly of sections, results,
   action logs, etc.

### Why This Works

| Property               | Explanation                                                    |
| ---------------------- | -------------------------------------------------------------- |
| **No single-call bottleneck** | Each LLM call handles ≤ 4K tokens of context               |
| **Linear scalability**       | More sub-tasks = more parallel calls, same per-call budget  |
| **Quality preservation**     | Each sub-task gets focused, relevant context                |
| **Token efficiency**         | Total tokens ≈ N × task_budget, not N²                      |

### Summary Propagation

When downstream agents need awareness of what earlier agents produced, the
framework uses **summary propagation** rather than passing raw content:

1. Each sub-task output is summarized to ~100–200 tokens
2. Summaries are concatenated into an **outline** (~500–1000 tokens)
3. The outline is passed to cross-cutting agents (reviewer, conclusion writer)
4. This maintains global coherence without blowing the context budget

#### SummaryGenerator Class

The `SummaryGenerator` is the core component that powers summary propagation.
It is created by the workflow engine (or by `TeamGenerator.build()`) and runs
after each agent step.

```python
summarizer = SummaryGenerator(
    llm_provider=provider,
    model="",                  # defaults to provider's default model
    max_summary_tokens=200,    # per-summary output token budget
    max_outline_tokens=1000,   # outline assembly budget
    summary_threshold=None,    # min words before summarization activates
)
```

**Adaptive summarization:** `summary_threshold` controls when summarization
activates. When set (e.g. `summary_threshold=4000`), only agent outputs
longer than that word count are summarized — shorter outputs pass through
unchanged. This prevents over-compression of moderate outputs while still
protecting against context overflow for very long ones. When `None` (default),
`max_summary_tokens` is used as the threshold, preserving legacy behavior.

**Methods:**

| Method            | Input                              | Output    | Behavior                                                                       |
| ----------------- | ---------------------------------- | --------- | ------------------------------------------------------------------------------ |
| `summarize(text)` | Raw agent output text              | `str`     | Generates ~200-token summary via LLM; short-circuits if text below threshold   |
| `build_outline(summaries)` | `dict[agent_id, summary]` | `str`     | Assembles coherent outline from multiple summaries                             |

The summarizer uses low temperature (0.3) for faithful, non-creative
summaries. If the input text is already within the token budget (estimated by
word count), `summarize()` returns it unchanged — avoiding unnecessary LLM
calls.

#### State Key Conventions

Summary propagation relies on consistent state key naming:

| State Key Pattern         | Written By         | Contains                                     |
| ------------------------- | ------------------ | -------------------------------------------- |
| `{agent_id}_output`       | Agent              | Full raw output from the agent               |
| `{agent_id}_summary`      | WorkflowEngine     | ~200-token summary of the agent's output     |
| `{agent_id}_outline`      | WorkflowEngine     | Outline assembled from parallel item summaries|
| `{agent_id}_outputs`      | WorkflowEngine     | List of full outputs from parallel fan-out   |
| `{agent_id}_summaries`    | WorkflowEngine     | Dict of per-item summaries from parallel fan-out |
| `parallel_items`          | Orchestrator       | List of sub-task descriptions                |

#### Downstream Agent Context Assembly

When an agent's state is assembled for an LLM call (`_summarize_state()`), the
following priority logic applies:

1. Include `task` and `input_data` from state
2. Include any `_outline` entries (from parallel fan-out results)
3. **Prefer `{agent_id}_summary`** over `{agent_id}_output` for prior agents
4. Fall back to full `_output` only when no `_summary` exists (backward compat)
5. If the agent has a `context_budget`, truncate assembled context to fit

This ensures downstream agents get focused, compressed context rather than
the full output of every prior step — which is critical for maintaining quality
as pipeline depth increases.

#### Positional Context for Fan-Out Workers

When an agent runs inside a `parallel_fan_out` step, its state includes
positional awareness:

- `current_item` — The specific sub-task assigned to this worker
- `item_index` — Zero-based index within the parallel items list
- `parallel_items` — The complete list of all sub-tasks (for awareness, not
  for execution)

This enables each parallel worker to produce contextually appropriate output
(e.g., correctly numbering its section, not overlapping with other sections).

### Advanced Context Management

The framework implements several advanced context management strategies
inspired by research in dynamic context management for multi-step agents
(DeepMiner, AgentDiet).

#### Sliding Window State Propagation

In deep sequential pipelines (5+ agents), all prior summaries accumulate
in context, but the earliest become increasingly irrelevant. When
`CONTEXT_RECENCY_WINDOW` is set to a positive integer N, only the N most
recent agent summaries/outputs are included fully in downstream context.
Older entries are collapsed into a single line:

> Earlier agents (planner, researcher) have completed their work. Their
> outputs informed the recent agents below.

This prevents distant, low-value context from diluting the focus for
downstream agents while still acknowledging prior work.

#### Context Expiry (TTL)

Each workflow step can declare a `context_ttl` (time-to-live) indicating
how many downstream steps its summary should remain visible:

```yaml
workflow:
  steps:
    - agent: planner
      type: sequential
      context_ttl: 2  # Summary visible for next 2 steps only
      next: researcher
```

After the TTL expires, the agent's summary is silently dropped from
downstream context assembly. Agents without `context_ttl` (default: `None`)
never expire.

#### Differential Compression

The `SummaryGenerator.summarize()` method applies different compression
ratios based on agent output type:

| Output Type       | Budget Multiplier | Rationale                                |
| ------------------|-------------------|------------------------------------------|
| `reasoning`       | 2.0×              | Reasoning traces have long-term strategic value |
| `structured_data` | 2.0×              | Planning decisions inform downstream work |
| `data`            | 0.5×              | Data outputs are locally relevant, aggressively compressed |
| `side_effect`     | 0.5×              | Action confirmations need minimal detail  |
| (default)         | 1.0×              | Standard budget when type is unspecified  |

This is based on the insight that reasoning traces and planning decisions
have far more downstream value than raw data or tool outputs.

#### Intelligent Context Reduction (ContextReducer)

When assembled context exceeds the agent's `context_budget` by a significant
margin (default: 1.5×), the framework invokes a cheap LLM (FAST_LLM tier)
as a "reflection module" to intelligently compress the context before
falling back to mechanical word-level truncation:

```python
from hiveflow.core.context_reducer import ContextReducer

reducer = ContextReducer(
    llm_provider=provider,
    model="gpt-4o-mini",
    overflow_threshold=1.5,  # Only invoke when >150% of budget
)
```

The reducer classifies and removes three types of waste:
- **Useless**: Irrelevant metadata, verbose boilerplate, debug traces
- **Redundant**: Same information repeated across multiple sections
- **Expired**: Context from agents whose work has been superseded

This two-pass approach (LLM reduction → mechanical fallback) achieves
significantly better context quality than blind truncation alone, at a
cost far lower than expanding the main agent's context budget.

#### Redundancy Detection

Before applying the sliding window, `_summarize_state()` performs
lightweight trigram-based redundancy detection across consecutive agent
entries. If two entries share >60% of their trigrams (Jaccard overlap),
the older entry is replaced with a short back-reference:

> (superseded by reviewer's output below)

This prevents duplicate information from consuming valuable context budget
without requiring an LLM call.

### Code-Level Assembly

After all agent steps complete, the `WorkflowEngine` can perform **code-level
assembly** — stitching together outputs from specified agents into a single
`final_output` in state. This is done by Python code, not by an LLM call.

```python
engine = WorkflowEngine(
    steps,
    summarizer=summarizer,
    assembly_agents=["writer"],  # agents whose outputs to assemble
)
```

**Assembly behavior:**

- For **sequential workflows**: concatenates the `{agent_id}_output` values
  from the specified agents in workflow order
- For **parallel fan-out**: concatenates all items from `{agent_id}_outputs`
  (the list of per-item outputs)
- The result is stored as `state["final_output"]`

Assembly is performed at the code level to avoid consuming LLM context on
mechanical concatenation, and to preserve the full length of each section
without truncation.

### Token Budget Invariants

| Parameter                    | Default       | Description                                        |
| ---------------------------- | ------------- | -------------------------------------------------- |
| `MAX_CONTEXT_PER_TASK`       | 4000 tokens   | Maximum context passed to a sub-task worker         |
| `MAX_SUMMARY_LENGTH`         | 200 tokens    | Maximum length of a sub-task summary                |
| `MAX_OUTLINE_LENGTH`         | 1000 tokens   | Maximum total outline for cross-cutting agents      |
| `MAX_TOKENS`                 | 16000 tokens  | Default maximum LLM output tokens per agent         |
| `ENABLE_SUMMARY_PROPAGATION` | `true`        | Enable automatic summary generation after each step |
| `SUMMARY_THRESHOLD`          | `None`        | Min words before summarization activates (`None` = legacy) |
| `CONTEXT_RECENCY_WINDOW`     | `0`           | Sliding window: only include N most recent agent summaries (0 = all) |
| `CHUNK_SIZE` / `BROWSE_CHUNK_MAX_LENGTH` | 1000 tokens | Text splitter chunk size                 |
| `CHUNK_OVERLAP`              | 200 tokens    | Text splitter overlap                               |
| `SIMILARITY_THRESHOLD`       | 0.35          | Minimum cosine similarity for context inclusion     |

### Implementation Pattern

```
Orchestrator
├── Decompose problem → [task_1, task_2, ..., task_N]
├── For each task (parallel):
│   ├── Generate sub-queries (FAST_LLM, ~100 tokens out)
│   ├── Gather data (tool plugins)
│   ├── Process + chunk + embed + filter (data pipeline)
│   ├── Assemble context (~3K tokens)
│   └── Execute task (SMART_LLM or action_executor)
├── Collect all outputs
├── Generate summaries (FAST_LLM, ~100 tokens each)
├── Assemble outline from summaries
├── Write introduction / executive summary (SMART_LLM)
├── Write conclusion / next steps (SMART_LLM)
└── Code-level assembly: final deliverable
```

---

---

[Next: Configuration & Operations >](10-configuration-and-operations.md)
