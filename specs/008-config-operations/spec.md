# Feature Specification: Configuration & Operations

**Feature Branch**: `008-config-operations`  
**Created**: 2026-02-27  
**Status**: Draft  
**Input**: User description: "Configuration and operations system with layered config, resilience patterns, prompt templates, streaming protocol, and recursive exploration" (derived from `requirements/10-configuration-and-operations.md`)

## Clarifications

### Session 2026-02-27

- Q: Should provider API keys/secrets (e.g., OPENAI_API_KEY) be managed through HiveFlow config? → A: External only — providers read their own standard env vars (e.g., OPENAI_API_KEY); HiveFlow config never stores or proxies secrets.
- Q: Should the LLM fallback chain include a reduced-max_tokens intermediate step before tier demotion? → A: Yes — the chain is: current tier → same tier with 50% max_tokens → next lower tier, matching the requirements document.
- Q: What are the default values for Actions configuration (DEFAULT_ACTION_POLICY, ENABLE_ROLLBACK, ACTION_TIMEOUT)? → A: deny-by-default policy, rollback disabled, 30-second timeout.
- Q: Is rate limiting scoped per-workflow-instance or global per-process? → A: Global per-process — rate limiters are shared across all concurrent workflows to prevent overwhelming external APIs.
- Q: Where are JSON-lines audit log files stored and is rotation handled? → A: Under the configured OUTPUT_DIR with date-based filenames (e.g., `events-2026-02-27.jsonl`); no automatic rotation (external tooling responsibility).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Configure a Multi-Agent Workflow (Priority: P1)

A framework user sets up a new multi-agent workflow project. They need to configure LLM model assignments, context limits, output preferences, and operational parameters across multiple layers — hardcoded defaults, a project configuration file, environment variables, and per-team overrides — so the framework behaves correctly in their environment without modifying source code.

**Why this priority**: Configuration is the foundation that every other capability depends on. Without a working layered configuration system, no agents, workflows, or resilience patterns can function correctly.

**Independent Test**: Can be fully tested by creating a configuration file and environment variables, then verifying the framework resolves settings in the correct precedence order (defaults → file → env → overrides).

**Acceptance Scenarios**:

1. **Given** no configuration file or environment variables, **When** the framework starts, **Then** all settings resolve to documented defaults (e.g., SMART_LLM defaults to its documented value, MAX_TOKENS defaults to 16000).
2. **Given** a project configuration file with custom LLM assignments, **When** the framework starts, **Then** the file values override the defaults.
3. **Given** environment variables set with a `HIVEFLOW_` prefix, **When** the framework starts, **Then** environment values override both defaults and file values.
4. **Given** a team configuration with per-agent model overrides, **When** the workflow runs, **Then** team overrides take highest precedence for the agents they apply to.
5. **Given** an agent configuration referencing a tier variable (e.g., `$SMART_LLM`), **When** the model is resolved, **Then** the tier variable expands to the concrete model configured for that tier.

---

### User Story 2 - Resilient Workflow Execution (Priority: P1)

A framework user runs a complex multi-agent workflow in production. External LLM calls occasionally fail, scraped URLs time out, and LLM responses sometimes contain malformed JSON. The user expects the framework to handle these transient failures gracefully — retrying with fallback models, parsing broken JSON, isolating failures per-agent, and applying rate limiting — without manual intervention or workflow crashes.

**Why this priority**: Production reliability is essential. Workflows that crash on transient failures are unusable in real deployments. Resilience patterns are a co-equal priority with configuration.

**Independent Test**: Can be fully tested by simulating LLM failures and verifying automatic fallback, injecting malformed JSON and verifying successful parsing, and triggering concurrent requests to verify rate limiting.

**Acceptance Scenarios**:

1. **Given** an LLM call fails with a transient error (rate limit, connection timeout), **When** the framework processes the failure, **Then** it automatically retries with the next model in the fallback chain (Strategic → Smart → Fast) before surfacing an error.
2. **Given** an LLM returns malformed JSON, **When** the framework parses the response, **Then** it recovers through a multi-step parse pipeline (strict parse → repair → regex extraction → default fallback) without crashing.
3. **Given** one agent in a workflow fails, **When** the error is caught, **Then** the failure is isolated to that agent and the workflow can continue or route to a fallback path.
4. **Given** multiple agents make concurrent external API calls, **When** the calls exceed configured rate limits, **Then** the framework throttles requests to stay within limits.
5. **Given** a workflow completes, **When** the result is returned, **Then** it includes accumulated cost data (token usage and estimated dollar amounts) for every LLM call made during execution.

---

### User Story 3 - Prompt Template Library Usage (Priority: P2)

A framework user creates specialized agents that need carefully structured system prompts. They want to use the built-in prompt template library — selecting from categorized prompt templates, interpolating workflow state variables, and having prompts automatically adapted for the target LLM model family — instead of writing raw prompt strings.

**Why this priority**: Prompt quality directly impacts agent effectiveness. A template library reduces errors and provides consistent, tested prompt patterns across all agents.

**Independent Test**: Can be fully tested by loading a template, substituting variables from a mock workflow state, and verifying the rendered prompt contains expected content with correct formatting for the target model family.

**Acceptance Scenarios**:

1. **Given** a prompt template with variable placeholders, **When** the template is rendered with workflow state data, **Then** all variables are correctly substituted, including nested/dotted-path references (e.g., `task.description`, `config.language`).
2. **Given** a template designed for a specific prompt category (e.g., sub-task decomposition, report writing), **When** the user selects it, **Then** the template provides structured instructions optimized for that task type.
3. **Given** a model from a different family (e.g., a local model vs. a cloud model), **When** a prompt is rendered, **Then** the framework selects the appropriate prompt variant for that model family.
4. **Given** a template with required variables that are not provided, **When** rendering is attempted, **Then** the system reports which variables are missing.

---

### User Story 4 - Real-Time Workflow Monitoring (Priority: P2)

A framework user runs a long multi-agent workflow and needs real-time visibility into progress. They want to observe what each agent is doing, what data flows between agents, and track costs — through both live streaming and persistent audit logs — without modifying any agent code.

**Why this priority**: Observability is critical for debugging, auditing, and building user trust. Without streaming events, long-running workflows are opaque black boxes.

**Independent Test**: Can be fully tested by running a workflow with a stream subscriber attached and verifying that structured events are emitted for each agent step with correct metadata.

**Acceptance Scenarios**:

1. **Given** a workflow is running, **When** an agent begins or completes a step, **Then** paired events (`executor_invoked` / `executor_completed`) are emitted with the agent's input and output data.
2. **Given** a stream subscriber is connected, **When** events are emitted, **Then** each event includes the agent ID, step ID, content, timestamp, and metadata (tokens used, latency, model).
3. **Given** a workflow is running, **When** events are emitted, **Then** they are simultaneously written to both a live stream (for real-time subscribers) and a persistent structured log file (JSON lines format) for audit.
4. **Given** an LLM-based agent is producing output, **When** streaming mode is enabled, **Then** individual tokens are forwarded in real time as they arrive from the LLM provider.

---

### User Story 5 - Recursive Multi-Level Exploration (Priority: P3)

A framework user needs to deeply investigate a complex topic (research question, codebase analysis, incident investigation). They configure a recursive exploration workflow that automatically plans sub-tasks, branches into parallel investigations at each level, dives recursively to a configurable depth, and merges findings from all branches into a coherent result.

**Why this priority**: Recursive exploration is a powerful advanced capability, but it builds on top of the workflow engine and agent system. It delivers high value for complex domains but is not required for basic workflow operation.

**Independent Test**: Can be fully tested by configuring a recursive exploration with breadth=2, depth=2, running it against a mock research function, and verifying the correct number of sub-tasks are spawned, recursion depth is respected, and results are merged.

**Acceptance Scenarios**:

1. **Given** a main problem and configuration (breadth=3, depth=2, concurrency=4), **When** recursive exploration starts, **Then** the system generates a breadth-first sub-task tree and spawns nested workflows for each branch.
2. **Given** a branch at the maximum configured depth, **When** the branch evaluates whether to recurse further, **Then** it stops and returns its findings instead of generating more sub-tasks.
3. **Given** multiple branches running in parallel, **When** all branches complete, **Then** their findings are aggregated and merged into a coherent combined result.
4. **Given** a recursive exploration in progress, **When** the user queries progress, **Then** the system reports completion percentage across all active branches.

---

### Edge Cases

- What happens when a configuration file contains invalid YAML/JSON syntax? The system reports a clear parsing error with the file path and line number, then falls back to defaults.
- What happens when an environment variable conflicts with an invalid value type (e.g., a string where an integer is expected)? The system reports a validation error identifying the variable and expected type.
- What happens when all models in a fallback chain fail? The system surfaces a structured error indicating all fallback options were exhausted, including which models were tried and their failure reasons.
- What happens when the JSON parse resilience pipeline exhausts all strategies? The system returns the configured default fallback value rather than crashing.
- What happens when rate limiting delays exceed the configured action timeout? The system raises a timeout error rather than blocking indefinitely.
- What happens when a recursive exploration branch encounters an error at depth > 1? The error is isolated to that branch; sibling and parent branches continue, and the merged result notes the failed branch.
- What happens when a prompt template references a variable path that does not exist in the workflow state? The system uses safe substitution, leaving the placeholder intact and logging a warning.
- What happens when a stream subscriber disconnects mid-workflow? The workflow continues running; the disconnected subscriber is removed, and remaining subscribers continue receiving events. The persistent log file is unaffected.

## Requirements *(mandatory)*

### Functional Requirements

**Configuration System**

- **FR-001**: System MUST support a four-layer configuration precedence: hardcoded defaults → configuration file (JSON or YAML) → environment variables (with `HIVEFLOW_` prefix) → runtime/team overrides.
- **FR-002**: System MUST provide a three-tier LLM model selection mechanism (Fast, Smart, Strategic) with documented defaults, where each tier can be overridden at any configuration layer.
- **FR-003**: System MUST resolve per-agent model references that use tier variables (e.g., `$SMART_LLM`) to their concrete configured model values.
- **FR-004**: System MUST support all key configuration categories: LLM, Embedding, Retrieval, Scraping, Context, Output, Actions, Deep Research, Tone, Source Mode, and MCP.
- **FR-005**: System MUST validate configuration values at load time and report clear errors for invalid types or out-of-range values. Provider API keys (e.g., OPENAI_API_KEY, ANTHROPIC_API_KEY) are explicitly out of scope — they are read by provider SDKs from their own standard environment variables and MUST NOT be stored in HiveFlow configuration files.
- **FR-006**: System MUST support a Source Mode toggle (`web`, `local`, `hybrid`, `cloud`, `mcp`, `custom`) that controls which retrieval sources are activated, along with a `DOC_PATH` setting for local document sources.
- **FR-007**: System MUST surface MCP configuration (server definitions, strategy, auto-tool-selection) in the main configuration alongside other settings.

**Resilience & Error Handling**

- **FR-008**: System MUST implement LLM fallback chains that automatically cascade through configured model tiers on transient failures (rate limit, connection errors), stopping immediately on non-transient errors (authentication, model-not-found). The fallback sequence includes an intermediate reduced-max_tokens step before tier demotion: current tier → same tier with 50% max_tokens → next lower tier (e.g., Strategic → Strategic@50% tokens → Smart → Smart@50% tokens → Fast → error).
- **FR-009**: System MUST implement a multi-step JSON parse resilience pipeline: strict parse → repair parse → regex extraction → default fallback, used for all LLM response parsing.
- **FR-010**: System MUST isolate failures at the agent, tool, URL, and action levels so that a single failure does not crash the entire workflow.
- **FR-011**: System MUST support circuit breaker patterns (closed/open/half-open states) to prevent repeated calls to failing services.
- **FR-012**: System MUST provide rate limiting (token bucket with burst support) and concurrency control (semaphore-based) that are applied to LLM provider calls and tool dispatch. Rate limiters are global per-process, shared across all concurrent workflow instances, to prevent overwhelming external APIs regardless of how many workflows run concurrently.
- **FR-013**: System MUST provide an action queue for side-effect operations with configurable parallelism and timeout. Default action policy is `deny` (actions require explicit approval unless overridden), default rollback is disabled, and default action timeout is 30 seconds.
- **FR-014**: System MUST support rollback procedures for failed actions when rollback is configured.
- **FR-015**: System MUST track and accumulate costs (token usage and dollar estimates) per-agent and per-workflow-run, using per-model pricing data, and include cost summaries in workflow result payloads.

**Prompt Template Library**

- **FR-016**: System MUST provide a prompt template library with categorized templates covering: sub-task decomposition, search query generation, report writing, introduction/conclusion generation, source curation, draft review, revision with feedback, agent role selection, summary generation, outline assembly, action planning, action validation, decision framing, code generation, and incident analysis.
- **FR-017**: System MUST support prompt variable interpolation with dotted-path resolution (e.g., `task.description`, `config.language`) that can traverse workflow state objects.
- **FR-018**: System MUST support prompt families (Default, Granite, Local) with per-family template variants that are automatically selected based on the target model.
- **FR-019**: System MUST provide output length guidance in agent prompts that work in conjunction with the MAX_TOKENS configuration.

**Streaming & Message Protocol**

- **FR-020**: System MUST emit structured stream events with required fields: type, agent_id, step_id, content, metadata (tokens_used, latency_ms, model), and timestamp.
- **FR-021**: System MUST support all specified message types: log, output, tool_call, action, human_request, approval, cost, error, rollback, summary_generated, outline_generated, assembly_complete, checkpoint_saved, executor_invoked, executor_completed, and request_info.
- **FR-022**: System MUST emit paired `executor_invoked` / `executor_completed` events for every agent step, capturing full input and output data for observability.
- **FR-023**: System MUST support a dual-output pattern where events are simultaneously delivered to live stream subscribers and written to a persistent structured log file (JSON lines format). Audit log files are stored under the configured `OUTPUT_DIR` with date-based filenames (e.g., `events-2026-02-27.jsonl`). Automatic log rotation is not provided; external tooling is responsible for retention management.
- **FR-024**: System MUST support token-level LLM streaming, forwarding individual tokens through the streaming channel as they arrive.

**Recursive Exploration**

- **FR-025**: System MUST support recursive multi-level exploration with configurable breadth (sub-tasks per level), depth (max recursion), concurrency (parallel branches), and context budget (max words across branches).
- **FR-026**: Recursive exploration MUST be modeled as an orchestrator agent that creates nested workflow instances for each branch, participating in the agent registry and workflow graph.
- **FR-027**: System MUST provide progress tracking that reports completion percentage across all active exploration branches.

### Key Entities

- **Configuration**: The resolved set of all framework settings, produced by merging four layers (defaults, file, environment, overrides). Contains LLM tier assignments, context limits, output preferences, and operational parameters.
- **Fallback Chain**: An ordered sequence of LLM provider/model pairs that are attempted in order when calls fail. Supports transient vs. non-transient error classification.
- **Prompt Template**: A reusable prompt definition belonging to a category and family, with variable placeholders that are resolved against workflow state at render time.
- **Stream Event**: A structured message emitted during workflow execution, carrying type, agent identity, step identity, content, metadata, and timestamp. Delivered to live subscribers and persistent logs.
- **Cost Record**: An accumulation of token usage and estimated dollar amounts for LLM calls, tracked per-agent and aggregated per-workflow-run.
- **Recursive Explorer**: An orchestrator agent that manages a tree of sub-tasks across configurable breadth and depth, spawning nested workflow instances and merging their results.

## Assumptions

- The existing `HiveFlowConfig` (pydantic-settings `BaseSettings`) will be extended rather than replaced.
- Existing resilience modules (`core/fallback.py`, `core/json_utils.py`, `core/errors.py`, `core/ratelimit.py`, `core/cost.py`) provide correct implementations; the primary work is integrating them into production execution paths.
- The `StreamChannel` fan-out mechanism works correctly for multiple subscribers; only the JSON-lines file writer and additional event types need to be added.
- `DeepResearcher` in `core/research.py` provides correct plan/branch/dive/merge logic; the work is wrapping it as an orchestrator agent within the workflow system.
- Per-model pricing tables in `core/cost.py` are kept up to date as new models are added.
- Default configuration values documented in the requirements file are authoritative.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Developers can configure the framework entirely through configuration files and environment variables, with zero source-code changes required for standard deployments.
- **SC-002**: 100% of configuration settings resolve correctly through the four-layer precedence chain, verified by integration tests covering each layer.
- **SC-003**: Workflows survive transient LLM failures without manual intervention, automatically falling back through at least 3 model tiers before reporting an error.
- **SC-004**: Malformed LLM JSON responses are successfully parsed in 95%+ of cases through the resilience pipeline, compared to 0% with strict parsing.
- **SC-005**: A single agent failure does not cause any other agent in the workflow to fail or the workflow to crash.
- **SC-006**: All 15 prompt template categories are available and usable, with variable interpolation supporting nested state references.
- **SC-007**: Every agent execution step produces paired observability events (invoked/completed) viewable by stream subscribers without modifying agent code.
- **SC-008**: Workflow event streams are simultaneously available in real time and persisted to a structured audit log.
- **SC-009**: Recursive exploration respects configured depth and breadth limits, and reports accurate progress percentages during execution.
- **SC-010**: Workflow result payloads include complete cost breakdowns with per-agent token counts and estimated dollar amounts.
