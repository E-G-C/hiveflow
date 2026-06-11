# Research: Task Preprocessing and Large-Input Context Management

**Branch**: `014-task-preprocessing` | **Date**: 2026-03-05

## R1: Where to insert preprocessing in the execution flow

**Decision**: Insert `TaskPreprocessor.preprocess(state)` in `WorkflowEngine.execute()` after document loading (line 468) and before collaboration init (line 492).

**Rationale**: At this point, `state["task"]` is fully populated (either from `initial_state` or `instructions_file`), documents are loaded, and the state is ready for agent execution. Preprocessing must run before any agent sees the state.

**Alternatives considered**:
- Before document loading: Rejected — documents might inform preprocessing decisions in future extensions.
- Outside WorkflowEngine (in caller code): Rejected — breaks encapsulation and requires all callers to remember to preprocess.
- Inside `Agent._summarize_state()`: Rejected — would run per-agent instead of once, and modifying state from within agent context assembly violates separation of concerns.

## R2: How to resolve model context windows

**Decision**: Three-tier resolution: (1) optional `context_window` property on `LLMProvider` protocol, (2) `ModelContextRegistry` with prefix-matched lookup table, (3) 16,000-token conservative default.

**Rationale**: No `context_window` property exists on `LLMProvider` today (`hiveflow/plugins/llm/__init__.py`). Adding an optional property preserves backward compatibility. The prefix-match lookup table handles the common case without requiring provider changes. The 16K default errs on the side of triggering preprocessing early (safe).

**Alternatives considered**:
- Hard-code context windows per provider class: Rejected — fragile, requires code changes for each new model.
- Query the provider API at runtime: Rejected — adds latency, not all providers expose this, and would require an additional API call per workflow.
- Use only a lookup table: Rejected — cannot account for custom/fine-tuned models deployed by users.

## R3: Chunking utility reuse and enhancement

**Decision**: Reuse `chunk_text()` from `hiveflow/plugins/documents/__init__.py` (line 217) with a wrapper that adds paragraph-boundary preference.

**Rationale**: The existing `chunk_text()` is a simple word-count splitter with overlap. The spec requires paragraph-boundary preference (FR-005). Rather than modifying the existing function (which could break document pipeline), create a thin wrapper `chunk_text_paragraph_aware()` that splits on paragraph boundaries (double newlines) first, then applies word-count limits per chunk.

**Alternatives considered**:
- Modify `chunk_text()` directly: Rejected — could change behavior for existing document pipeline users.
- Write entirely new chunking logic: Rejected — unnecessary duplication; the core word-count logic is sound.
- Use a third-party chunking library: Rejected — constitution §2.4 prefers plugins over external dependencies for non-critical functionality.

## R4: How to generate topic hints for manifest entries

**Decision**: Use LLM to generate topic hints for all chunks in a single batch call, included as part of the summarization step (FR-006 + FR-007). When summarization fails (or data is below chunk threshold), extract the first sentence of each chunk as a mechanical topic hint.

**Rationale**: A single LLM call generating both summary and per-chunk topic hints is efficient (stays within SC-005's 2-call budget). First-sentence extraction is a reasonable fallback that requires no LLM call.

**Alternatives considered**:
- One LLM call per chunk for topic hints: Rejected — violates SC-005 (max 2 overhead calls).
- Keyword extraction (TF-IDF/TextRank): Rejected — adds dependency on NLP libraries; mechanical first-sentence is simpler and sufficient.
- No topic hints on fallback: Rejected — manifest without topic hints degrades planner ability to route chunks.

## R5: How to pass chunk references during delegation

**Decision**: Extend `CollaborationRuntime._build_sub_state()` (line 843 of `collaboration.py`) to propagate `task_instructions`, `task_data`, `task_data_summary`, and `task_data_manifest` from parent state. Add a `chunk_id` parameter to `DelegateTaskTool` that, when provided, filters `task_data` to only the specified chunk(s).

**Rationale**: The collaboration system already builds a sub-state for delegated agents. Extending it to include preprocessing keys follows the existing pattern. Adding `chunk_id` to the tool schema allows planners to explicitly assign chunks to delegates, fulfilling FR-009 (delegation with chunk context).

**Alternatives considered**:
- Pass full `task_data` to every delegate: Rejected — defeats the purpose of preprocessing (each worker gets all chunks).
- Create a separate chunk routing system: Rejected — over-engineering; delegation already has the mechanics.
- Store chunks in external storage and pass references: Rejected — adds I/O complexity; in-memory state is sufficient for typical document sizes.

## R6: How to integrate with existing `_summarize_state()` context assembly

**Decision**: Add a preprocessing-aware branch at `agent.py` line 740. When `task_instructions` key exists in state, use it instead of `state["task"]`. Append `task_data_summary` after instructions. For agents with `current_item` containing a chunk reference (fan-out workers), include the chunk content. The existing `state["task"]` is still set (to instructions only) so downstream code that reads `state["task"]` directly still works.

**Rationale**: This is the minimal change to the most critical integration point. The fallback to `state["task"]` when preprocessing keys are absent (FR-011) ensures zero behavior change for non-preprocessed workflows.

**Alternatives considered**:
- Create a separate `_summarize_preprocessed_state()` method: Rejected — code duplication; the existing method already handles multiple state shapes.
- Override `_build_messages()` in a subclass: Rejected — Agent is not designed for subclassing; configuration-over-code is the HiveFlow pattern.

## R7: Configuration integration pattern

**Decision**: Add new fields to `HiveFlowConfig` (pydantic-settings) with `HIVEFLOW_` env prefix. Team-level overrides via a `preprocessing` key in team config dict. Follow existing naming conventions.

**Rationale**: Existing config uses `HiveFlowConfig` for global settings and team config dicts for per-team overrides. The spec requires both (FR-010, FR-012).

**New global config fields**:
- `TASK_PREPROCESS_DISABLED: bool = False`
- `TASK_PREPROCESS_THRESHOLD_OVERRIDE: int = 0` (0 = auto-compute)
- `TASK_CONTEXT_RATIO: float = 0.15`
- `TASK_PIPELINE_FACTOR: float = 0.3`
- `TASK_CHUNK_CONTEXT_RATIO: float = 0.10`
- `TASK_CHUNK_OVERLAP_RATIO: float = 0.10`
- `TASK_TOKENS_PER_WORD: float = 1.35`

**Team-level config**:
```yaml
preprocessing:
  disabled: false
  threshold_override: 0
  context_ratio: 0.15
  pipeline_factor: 0.3
  chunk_context_ratio: 0.10
  chunk_overlap_ratio: 0.10
  tokens_per_word: 1.35
```

## R8: Boundary detection heuristic ordering

**Decision**: Apply heuristics in this order (first match wins):
1. Explicit section labels: `## Data`, `## Content`, `## Input`, `## Source` (case-insensitive heading search)
2. Horizontal rule + heading: `---` or `***` followed by a heading within 2 lines
3. Fenced code block: Opening ` ``` ` that encloses >60% of total word count
4. Size gradient: Sliding-window analysis — if any boundary between paragraphs separates a "short" section (<30% of total words) from a "long" section (>70%), use that boundary
5. LLM fallback: Single LLM call with the first 2,000 words asking "where do the instructions end and the data begin?"

**Rationale**: Ordered from most specific (explicit labels are unambiguous) to most general (LLM fallback handles anything). The size gradient is placed before LLM because it requires no external call and handles the common case where instructions are short and data is long.

**Alternatives considered**:
- LLM-first approach: Rejected — wasted LLM call when structural markers are present; violates SC-005.
- Regex-based content detection: Rejected — would be format-specific (e.g., matching WEBVTT headers, JSON structures); the spec requires generic heuristics.

## R9: Structured logging pattern

**Decision**: Use `structlog` (already a project dependency) to emit structured events. Follow the existing logging patterns in `workflow.py` and `agent.py`. Events:
- `task_preprocessing.threshold_check`: `{activated: bool, task_words: int, threshold: int, model: str, context_window: int}`
- `task_preprocessing.boundary_detected`: `{method: str, instructions_words: int, data_words: int}`
- `task_preprocessing.chunking_complete`: `{chunk_count: int, chunk_sizes: list[int], overlap: int}`
- `task_preprocessing.summarization_complete`: `{summary_words: int, method: str, elapsed_ms: float}`
- `task_preprocessing.complete`: `{total_elapsed_ms: float, chunks: int, llm_calls: int}`

**Rationale**: Constitution §2.6 requires observability to be built in. The existing codebase uses `structlog.get_logger()` throughout. Preprocessing decisions are critical for debugging workflow quality issues.

## R10: Fan-out integration for chunk processing

**Decision**: Extend the existing `parallel_fan_out` step type to accept `source: "task_data"` as an alternative to inline items. When `source: "task_data"`, the engine iterates over `state["task_data"]` and sets `current_item` to each chunk dict for the parallel workers.

**Rationale**: The workflow engine already supports parallel fan-out (lines 620-680 of workflow.py). The `current_item` / `item_index` / `parallel_items` keys are already handled in `_summarize_state()`. Reusing this mechanism minimizes new code and follows existing patterns.

**Alternatives considered**:
- New step type `chunk_fan_out`: Rejected — duplicates existing fan-out logic.
- Dynamic workflow modification: Rejected — out of scope per spec.
