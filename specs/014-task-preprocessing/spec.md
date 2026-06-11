# Feature Specification: Task Preprocessing and Large-Input Context Management

**Feature Branch**: `014-task-preprocessing`
**Created**: 2026-03-05
**Status**: Draft
**Input**: Requirement 14 — automatic detection and decomposition of large task inputs so that agents receive focused, right-sized context instead of the full input blob.

## Clarifications

### Session 2026-03-05

- Q: What level of observability should task preprocessing provide? → A: Structured events — log entries for threshold decision, boundary method used, chunk count, summary size, and total preprocessing time.
- Q: What should happen when the summarization LLM call fails? → A: Retry with backoff; if the retry also fails, fall back to a manifest-based mechanical summary (chunk count, total words, first-sentence excerpts from each chunk).
- Q: Should there be a minimum data size below which chunking is skipped? → A: Yes — if the data section fits within one chunk target size, store it as a single entry in `task_data` without invoking the summarizer or generating topic hints.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Large input is automatically split so agents produce comprehensive output (Priority: P1)

A user submits a task containing a 4,800-word processing prompt plus a 16,000-word document (e.g., a meeting transcript, a codebase, a contract). Today, every agent in the workflow receives all 21,000 words verbatim (~67K tokens), drowning in context and producing thin, repetitive output. With task preprocessing, the system automatically separates instructions from data, chunks the data, and routes only the relevant pieces to each agent. The result is comprehensive coverage of the entire source document, not just a cursory summary.

**Why this priority**: This is the core value proposition. Without it, any task with large embedded content produces poor results and wastes tokens. This story alone delivers measurable improvement.

**Independent Test**: Submit a task file containing 5,000+ words of instructions and 15,000+ words of data. Verify that the system separates them, no single agent receives more than 20% of the model's context window as task content, and the final output covers the full source material — not just the first few pages.

**Acceptance Scenarios**:

1. **Given** a task with 21,000 words (instructions + data), **When** the workflow executes with preprocessing enabled, **Then** the planner agent receives only instructions (~5,000 words) plus a compact data summary (~200 words), not the full 21,000-word blob.
2. **Given** the same task, **When** worker agents execute, **Then** each worker receives only its assigned data chunk plus the instructions — not the full data section.
3. **Given** a task below the preprocessing threshold (e.g., 500 words with a 128K-context model), **When** the workflow executes, **Then** behavior is identical to today — `state["task"]` is passed through unchanged with no additional state keys.

---

### User Story 2 - Threshold adapts to the model's context window (Priority: P1)

The preprocessing decision must not use a fixed word count. A user running a small 8K-context model needs preprocessing to activate much earlier than a user running a 128K-context model. The threshold is computed as a fraction of the model's context window, adjusted by the number of agents in the pipeline, so preprocessing is appropriately aggressive or permissive for the model in use.

**Why this priority**: Without model-aware thresholds, the feature either preprocesses unnecessarily on large models (wasted LLM calls) or fails to activate on small models (context overflow). This is essential for the feature to work across all deployment scenarios.

**Independent Test**: Configure the same task with two different models (one 8K context, one 128K context). Verify that the computed threshold differs and preprocessing activates/deactivates accordingly.

**Acceptance Scenarios**:

1. **Given** a model with 128K context window and a 3-agent pipeline, **When** the system computes the preprocessing threshold, **Then** the threshold is approximately `128,000 * 0.15 / 1.35 / (3 * 0.3)` words.
2. **Given** a model with 8K context window and the same pipeline, **When** the system computes the threshold, **Then** it is significantly lower.
3. **Given** an unknown model not in the lookup table, **When** the system computes the threshold, **Then** it uses a conservative 16K-token fallback to trigger preprocessing early.
4. **Given** a user sets `threshold_override=5000`, **When** the system computes the threshold, **Then** the fixed override is used regardless of model context window.

---

### User Story 3 - Instructions and data are separated generically (Priority: P1)

When a task exceeds the threshold, the system splits it into instructions (what the user wants done) and data (the content to process). This separation works for any content type — transcripts, code, contracts, datasets — without format-specific logic. The system uses structural markers (headings, code fences, horizontal rules, size gradients) to find the boundary, falling back to an LLM call only when no structural pattern is detected.

**Why this priority**: Separation is the foundation for all downstream routing. If instructions and data can't be reliably split, the rest of the feature doesn't work.

**Independent Test**: Submit task files with different boundary patterns (code fence, horizontal rule + heading, explicit `## Data` label, no markers at all). Verify correct separation in each case.

**Acceptance Scenarios**:

1. **Given** a task where instructions are followed by a horizontal rule + heading + code fence containing data, **When** preprocessing runs, **Then** everything before the structural marker is classified as instructions and everything after as data.
2. **Given** a task with no explicit markers but a sharp size gradient (first 500 words are short paragraphs, next 15,000 words are dense content), **When** preprocessing runs, **Then** the size gradient heuristic correctly identifies the boundary.
3. **Given** a task that is entirely instructional (no embedded data), **When** preprocessing runs, **Then** `task_instructions` contains the full text and `task_data` is an empty list.
4. **Given** a task with no structural markers and no size gradient, **When** preprocessing runs, **Then** the system uses an LLM call to identify the boundary.

---

### User Story 4 - Data is chunked and summarized for routing (Priority: P2)

After separation, the data section is chunked into model-appropriate segments and a compact summary is generated. The summary allows planning agents to understand the content without reading it. The manifest lists all chunks with word counts and topic hints so orchestrators can assign chunks to workers intelligently.

**Why this priority**: Chunking and summarization enable the multi-worker parallel processing pattern. Without them, workers must still receive the full data section.

**Independent Test**: Submit a 16,000-word data section with a 128K-context model. Verify chunks are appropriately sized (~10% of context window). Submit the same data with an 8K model. Verify chunks are smaller. Verify the summary is under 300 words and the manifest lists all chunks with topic hints.

**Acceptance Scenarios**:

1. **Given** a 16,000-word data section and a 128K-context model, **When** preprocessing chunks the data, **Then** each chunk is approximately 10% of the model's context window in tokens.
2. **Given** the same data section and an 8K-context model, **When** preprocessing chunks, **Then** chunks are proportionally smaller (10% of 8K).
3. **Given** chunked data, **When** the summarizer runs, **Then** `task_data_summary` contains a coherent summary of 300 words or fewer.
4. **Given** chunked data, **When** the manifest is generated, **Then** each chunk entry includes `chunk_id`, `words`, and a `topic_hint` of one sentence or fewer.

---

### User Story 5 - Agents receive only the context relevant to their role (Priority: P2)

After preprocessing, the context assembly method injects `task_instructions` (compact) instead of the full `state["task"]`. Planning agents also see the data summary and manifest. Processing agents see their assigned chunk. Reviewers see the assembled output. No agent receives the full data blob unless explicitly requested.

**Why this priority**: This is where the token savings and quality improvement are realized. Without role-based routing, preprocessing produces the right data structures but agents still drown in irrelevant context.

**Independent Test**: Run a preprocessing-enabled workflow. Inspect the context assembled for each agent type. Verify planners see summary + manifest, workers see their chunk, reviewers see only the assembled document.

**Acceptance Scenarios**:

1. **Given** preprocessing has run, **When** agent context is assembled for any agent, **Then** it includes `task_instructions` (not the full original task) and `task_data_summary`.
2. **Given** a worker agent with an assigned chunk reference in its state, **When** context is assembled, **Then** the worker's chunk content is included but other chunks are not.
3. **Given** preprocessing keys are absent (small task or disabled), **When** context is assembled, **Then** it falls back to the existing behavior unchanged.

---

### User Story 6 - Chunks are routed to workers via delegation, fan-out, or retrieval (Priority: P3)

Chunks reach processing agents through three mechanisms: (a) planner-assigned delegation (collaboration mode), where the orchestrator passes a chunk reference in the delegation context; (b) parallel fan-out over chunks (static workflow), using the existing fan-out step type with `task_data` as the source; (c) on-demand retrieval via the document retriever tool, where any agent can pull specific chunks by topic or ID.

**Why this priority**: Multiple routing strategies ensure the feature works across all workflow patterns (collaboration, static, hybrid). However, the core value (Stories 1-5) already works with a single routing mechanism.

**Independent Test**: For each routing strategy, run a workflow with preprocessed chunks. Verify workers receive individual chunks, not the full data blob.

**Acceptance Scenarios**:

1. **Given** collaboration is enabled and a planner delegates with a chunk reference, **When** the delegate agent executes, **Then** it receives only that chunk's content in its context.
2. **Given** a static workflow with fan-out over task data, **When** the engine executes, **Then** each parallel instance receives one chunk.
3. **Given** an agent with document retriever tool access, **When** it queries by topic, **Then** the most relevant chunk(s) are returned.

---

### Edge Cases

- What happens when the task is exactly at the threshold boundary? The system does not preprocess (threshold is exclusive: `>`, not `>=`).
- What happens when the data section is empty after separation (all instructions, no data)? `task_data` is an empty list; `task_data_summary` is empty; agents receive only `task_instructions`.
- What happens when the LLM boundary-detection call fails (timeout, error)? Fall back to a conservative split: treat the first 20% of words as instructions, remaining 80% as data.
- What happens when a model is not in the context window lookup table? Use the conservative default of 16,000 tokens, which will trigger preprocessing earlier.
- What happens when `threshold_override` is set to 0? Preprocessing is fully disabled for that configuration.
- What happens when chunk overlap causes a chunk to exceed the target size? The chunker caps each chunk at 1.5x the target and splits further if needed.
- What happens when the summarization LLM call fails? Retry once with backoff. If the retry also fails, generate a mechanical summary from the manifest: chunk count, total word count, and first-sentence excerpts from each chunk. The workflow continues without blocking.
- What happens when the data section after separation is smaller than one chunk target? Skip chunking, summarization, and manifest generation. Store the data as a single entry in `task_data` and pass it directly to agents alongside `task_instructions`.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST compute the preprocessing threshold as a function of the model's context window, the task-context ratio, and the pipeline agent count with a pipeline factor.
- **FR-002**: System MUST resolve model context windows via: (1) an optional provider-exposed property, (2) a built-in lookup table with prefix matching, (3) a conservative 16,000-token default fallback.
- **FR-003**: System MUST detect the instruction/data boundary using generic structural heuristics (fenced code blocks, horizontal rules + headings, explicit section labels, size gradient) without format-specific content inspection.
- **FR-004**: System MUST fall back to an LLM call for boundary detection when no structural pattern is found.
- **FR-005**: System MUST chunk the data section using word-count-based splitting with paragraph-boundary preference, where chunk target size is derived from the model's context window. If the data section is smaller than one chunk target, the system MUST skip chunking, summarization, and manifest generation, storing the data as a single entry in `task_data`.
- **FR-006**: System MUST generate a compact summary of the data content (300 words or fewer) for use by planning and routing agents. If the summarization LLM call fails, the system MUST retry once with backoff; if the retry also fails, generate a mechanical summary from the manifest (chunk count, total words, first-sentence excerpts per chunk).
- **FR-007**: System MUST generate a manifest listing all chunks with `chunk_id`, `words`, and `topic_hint` for each.
- **FR-008**: System MUST update agent context assembly to inject `task_instructions` instead of the full `state["task"]` when preprocessing keys are present, with fallback to existing behavior when they are absent.
- **FR-009**: System MUST support three chunk routing strategies: delegation with chunk context, parallel fan-out over `task_data`, and on-demand retrieval.
- **FR-010**: System MUST allow the model-derived threshold to be overridden via a fixed word count or disabled entirely via configuration.
- **FR-011**: System MUST maintain full backward compatibility: tasks below the threshold produce zero changes to state or behavior.
- **FR-012**: System MUST provide team-level configuration overrides for all preprocessing parameters.
- **FR-013**: `state["task"]` MUST always exist and contain compact content (instructions only when preprocessing runs, full original when it doesn't). It is never empty or removed.
- **FR-014**: System MUST emit structured log events for key preprocessing decisions: threshold check result (activated or skipped, with computed threshold value), boundary detection method used (which heuristic matched or LLM fallback), chunk count and sizes produced, summary word count, and total preprocessing wall-clock time.

### Key Entities

- **TaskPreprocessor**: The component that runs before workflow execution, performing threshold detection, boundary separation, chunking, summarization, and manifest generation.
- **ModelContextRegistry**: A lookup table mapping model name prefixes to context window sizes in tokens. Extensible at runtime.
- **TaskDataChunk**: A segment of the data section, identified by `chunk_id`, with content, word count, and topic hint fields.
- **TaskDataManifest**: Metadata describing all chunks — total words, chunk count, model context used, effective threshold, and per-chunk metadata.
- **PreprocessedState**: The enriched state containing `task_instructions`, `task_data`, `task_data_summary`, and `task_data_manifest` keys alongside the original `task` (now containing instructions only).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For a 21,000-word input processed by a 3-agent pipeline, total token consumption is reduced by at least 60% compared to baseline (no preprocessing).
- **SC-002**: For the same input, final output covers at least 80% of the source material's topics, compared to less than 30% without preprocessing.
- **SC-003**: No agent in a preprocessed workflow receives task content exceeding 20% of the model's context window.
- **SC-004**: Tasks below the model-derived threshold produce zero additional state keys and zero additional LLM calls — identical behavior to today.
- **SC-005**: Preprocessing adds no more than 2 LLM calls overhead (one for boundary detection fallback, one for summarization) regardless of input size.
- **SC-006**: The preprocessing threshold differs by at least 10x between an 8K-context model and a 128K-context model for the same task and agent count.
- **SC-007**: Boundary detection correctly separates instructions from data for at least 4 distinct structural patterns (code fence, horizontal rule, explicit label, size gradient) without format-specific logic.

## Assumptions

- The tokens-per-word ratio of 1.35 is a reasonable approximation for English text. Non-English or highly technical content may differ; the system allows ratio overrides.
- The existing document pipeline chunking utility supports word-count-based splitting with paragraph-boundary preference and will be reused.
- The existing summary generator (or a similar fast-LLM call pattern) will be used for data summarization and topic hint generation.
- Overlap between chunks (default 10% of chunk size) is sufficient to prevent information loss at boundaries.
- The pipeline factor of 0.3 is a reasonable starting point; empirical tuning may adjust this value.

## Scope Boundaries

**In scope:**
- Automatic threshold computation from model context window
- Generic structural boundary detection (heuristics + LLM fallback)
- Word-count-based chunking with model-derived chunk sizes
- Data summarization and manifest generation
- Updated context assembly for preprocessing-aware state injection
- Integration with workflow execution entry point and team builder
- Configuration at global and team levels
- Full backward compatibility for small tasks

**Out of scope:**
- Format-specific chunking plugins (future work)
- Automatic workflow restructuring when large input is detected (future work)
- LLM team generator awareness of chunk manifests (future work)
- Semantic (embedding-based) chunk relevance filtering
- Real-time streaming of preprocessed chunks during execution

## Dependencies

- Context management (spec 09): The divide-and-conquer pattern and context assembly method this feature extends.
- Document input pipeline (spec 12): The chunking utilities this feature reuses.
- Dynamic agent collaboration (spec 13): The delegation and planning tools that enable chunk-to-agent routing.
