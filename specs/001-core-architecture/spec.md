# Feature Specification: Core Architecture

**Feature Branch**: `001-core-architecture`
**Created**: 2026-02-22
**Status**: Draft
**Input**: User description: "Core architecture as defined in requirements/01-core-architecture.md — Universal Agent Class, Dynamic Team Composition, Workflow Graph Definition, and Public API"

## Clarifications

### Session 2026-02-22

- Q: Should the `action_executor` behavior type (agents that perform real-world side effects with safety policies) be included in this feature's scope? → A: Yes, include `action_executor` with Phase 1 safety policies (`auto`, `require_approval`). Phase 2 policies (`dry_run`, `confirm_on_error`) are deferred.
- Q: What is the maximum number of iterations for conditional (evaluate-iterate) loops before the workflow terminates? → A: Configurable per-step with a default of 3 iterations. The workflow fails with an error when the limit is exceeded.
- Q: Should workflow checkpointing (persist/resume across process restarts) be included in this feature? → A: Yes, Phase 1 checkpointing: save/resume at human gates and gated steps with file-based storage. Full pluggable backends and per-step checkpointing are deferred.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Define and Run a Single Agent (Priority: P1)

A developer creates a single agent by specifying its identity (system prompt), behavior type, optional tools, and model. They execute the agent against a task and receive a result. This is the most fundamental unit of the framework — everything else builds on it.

**Why this priority**: Without a working universal agent, no other feature (teams, workflows, composition) can function. This is the foundational building block.

**Independent Test**: Can be fully tested by creating an agent with a system prompt and behavior type, executing it against a string task, and verifying the result contains expected output. Delivers value as a standalone single-agent execution capability.

**Acceptance Scenarios**:

1. **Given** a developer provides a system prompt, behavior type (`llm_only`), and model name, **When** they create an agent and call execute with a task string, **Then** the agent returns a result containing the LLM's response text.
2. **Given** a developer creates an agent with behavior type `tool_user` and registers a tool, **When** the agent executes, **Then** it can invoke the tool and incorporate tool results into its response.
3. **Given** a developer creates an agent with behavior type `orchestrator`, **When** the agent executes, **Then** it can spawn and coordinate sub-tasks.
4. **Given** a developer creates an agent with behavior type `human_gate`, **When** the agent executes and requires approval, **Then** the workflow pauses and surfaces an approval request.
5. **Given** a developer creates an agent with behavior type `action_executor` and action policy `require_approval`, **When** the agent determines actions to take, **Then** the workflow pauses for approval before executing the actions and records results in the workflow state.
6. **Given** a developer creates an agent with behavior type `action_executor` and action policy `auto`, **When** the agent determines actions to take, **Then** the actions execute immediately and results are recorded in the workflow state.
7. **Given** a developer creates an agent without specifying `output_type`, **When** the agent executes, **Then** the framework infers the output type from the behavior type (e.g., `text` for `llm_only`, `structured_data` for `orchestrator`, `side_effect` for `action_executor`).

---

### User Story 2 - Compose a Team from a Template (Priority: P1)

A developer loads a pre-built team configuration from the team library and runs a multi-agent workflow against a task. The workflow executes agents in the defined order and returns a consolidated result.

**Why this priority**: Template-based teams are the primary consumption mode and the most common way developers will use the framework. This validates the entire pipeline: team loading, agent creation, workflow execution, and result assembly.

**Independent Test**: Can be fully tested by loading a bundled team template, providing a task description, and verifying that all agents in the team execute in the defined order with a final result produced.

**Acceptance Scenarios**:

1. **Given** a team template exists in the team library, **When** a developer references it by name and provides a task, **Then** the framework loads the configuration, creates the agents, and executes the workflow.
2. **Given** a team template defines a sequential workflow (A -> B -> C), **When** the workflow executes, **Then** each agent runs in order, receiving the accumulated state from prior agents.
3. **Given** a team template defines a conditional step with accept/reject branches, **When** the evaluating agent rejects, **Then** the workflow routes to the rejection branch and iterates.
4. **Given** a team template defines a parallel fan-out step, **When** the workflow reaches that step, **Then** multiple sub-tasks execute concurrently and their results are aggregated before the next step.

---

### User Story 3 - Provide a Custom Team Configuration (Priority: P2)

A developer authors a complete team configuration in JSON or YAML, including agent definitions and workflow graph, and submits it to the framework. The framework validates the configuration and executes it.

**Why this priority**: Custom configurations give developers full control over team composition without depending on pre-built templates. This is essential for domain-specific use cases.

**Independent Test**: Can be fully tested by providing a hand-authored JSON team configuration, having the framework validate and execute it, and verifying the workflow completes successfully.

**Acceptance Scenarios**:

1. **Given** a developer provides a valid `TeamConfiguration` as JSON, **When** they submit it for execution, **Then** the framework validates the schema, checks tool availability, and executes the workflow.
2. **Given** a developer provides a configuration with a dangling agent reference (a workflow step references an agent ID not in the roster), **When** validation runs, **Then** the framework rejects the config with a clear error identifying the missing agent.
3. **Given** a developer provides a configuration referencing a tool not registered in the tool registry, **When** validation runs, **Then** the framework reports the missing tool.
4. **Given** a developer provides a configuration with per-agent model assignments, **When** the workflow executes, **Then** each agent uses its specified model rather than the global default.

---

### User Story 4 - Generate a Team via LLM (Priority: P3)

A developer describes a problem in natural language and asks the framework to generate an appropriate team configuration using an LLM. The generated team is returned for review before execution and can be saved as a reusable template.

**Why this priority**: LLM-generated teams enable the framework to handle novel, unknown problems without requiring pre-built templates. This is a bootstrapping mechanism for edge cases.

**Independent Test**: Can be fully tested by providing a task description, triggering team generation, and verifying the returned result contains a valid team configuration with agents, workflow graph, and any capability gap reports.

**Acceptance Scenarios**:

1. **Given** a developer provides a task description, **When** they request LLM-based team generation, **Then** the framework returns a `TeamGenerationResult` containing a valid `TeamConfiguration`, any capability gaps, and any new archetypes invented by the LLM.
2. **Given** the LLM generates a team that requires a tool not available in the registry, **When** the result is returned, **Then** the capability gaps list includes the missing tool with a severity level (blocking, degraded, or functional_but_limited).
3. **Given** the developer sets `auto_approve=False` (default), **When** generation completes, **Then** the configuration is returned for inspection without automatic execution.
4. **Given** the developer sets `auto_approve=True` and no blocking gaps exist, **When** generation completes, **Then** the configuration proceeds to execution directly.

---

### User Story 5 - Use the Public API Across Consumption Contexts (Priority: P2)

A developer uses the `HiveFlow` public API to run workflows from different contexts: embedded Python, behind a REST API, from a CLI, or within a native application. The API provides a consistent interface regardless of consumption context.

**Why this priority**: The public API is the single source of truth that all consumption modes delegate to. A well-designed API enables the framework to serve web, CLI, and desktop contexts equally.

**Independent Test**: Can be fully tested by calling `HiveFlow.run()` (async) and `HiveFlow.run_sync()` with a team and task, verifying that both return a `WorkflowSession` with session ID, status, and result.

**Acceptance Scenarios**:

1. **Given** a developer creates a `HiveFlow` instance, **When** they call `await hf.run(team="template_name", task="do something")`, **Then** a `WorkflowSession` is returned with a unique session ID, status, and eventual result.
2. **Given** a developer uses the synchronous wrapper, **When** they call `hf.run_sync(team=config, task="do something")`, **Then** the call blocks until the workflow completes and returns the same `WorkflowSession`.
3. **Given** a workflow pauses at a human gate, **When** the developer inspects `session.pending_requests`, **Then** they see the approval request with enough context to make a decision. **When** they call `session.resume(responses={...})`, **Then** the workflow continues from where it paused.
4. **Given** a workflow pauses at a human gate or gated step, **When** the process restarts, **Then** the workflow can be resumed from the persisted checkpoint without re-executing completed steps.
5. **Given** a developer subscribes to workflow events, **When** the workflow executes, **Then** they receive structured events (step_start, step_complete, tool_call, output, etc.) in real time via an async iterator.

---

### User Story 6 - Discover Available Resources (Priority: P3)

A developer queries the framework to discover what teams, archetypes, tools, and models are available. This enables building UIs and tooling that adapt to the current framework configuration.

**Why this priority**: Discovery is essential for any UI or integration layer that needs to enumerate available resources, but the core execution flow works without it.

**Independent Test**: Can be fully tested by calling discovery methods on the `HiveFlow` instance and verifying that registered teams, archetypes, tools, and models are returned as serializable summaries.

**Acceptance Scenarios**:

1. **Given** a `HiveFlow` instance with registered teams, **When** the developer calls `hf.team_library().list_teams()`, **Then** they receive a list of available team names.
2. **Given** a `HiveFlow` instance with registered archetypes, **When** the developer calls `hf.archetype_library().list_archetypes()`, **Then** they receive a list of available archetype names.
3. **Given** a `HiveFlow` instance with registered tools, **When** the developer calls `hf.tool_registry()`, **Then** they can enumerate available tools with their descriptions and schemas.
4. **Given** a `HiveFlow` instance, **When** the developer calls `hf.model_registry()`, **Then** they can list available LLM providers and models.

---

### Edge Cases

- What happens when an agent's specified model is unavailable at runtime? The framework should report the error clearly and, if a fallback chain is configured, attempt the next provider.
- What happens when a workflow reaches a conditional step and the evaluating agent produces ambiguous output (neither clear accept nor reject)? The framework should have a defined default branch or error behavior.
- What happens when a conditional loop exceeds its maximum iteration count? The workflow fails with an error indicating the step, iteration count, and last evaluation result. The default limit is 3 iterations, configurable per step.
- What happens when a parallel fan-out step has zero sub-tasks? The workflow should skip to the next step without error.
- What happens when a human gate approval never arrives? The workflow remains in a paused state indefinitely; the session is inspectable and can be cancelled. If checkpointed, the paused state persists across process restarts.
- What happens when a checkpoint file is corrupted or missing on resume? The framework should report a clear error and not partially execute from an inconsistent state.
- What happens when an LLM-generated team configuration is structurally valid but semantically nonsensical (e.g., a single agent with no workflow)? Validation should enforce minimum structural requirements (at least one agent, at least one workflow step).
- What happens when two agents in a workflow write to the same state key? The later agent's output overwrites the earlier one (immutable merge semantics).
- What happens when a developer provides both `model` and `model_requirements` on an agent? `model` takes precedence (explicit always wins).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST provide a single universal agent class that is specialized at creation time through configuration (system prompt, behavior type, tools, model, output type, max tokens, context budget).
- **FR-002**: System MUST support five agent behavior types: `llm_only` (pure LLM response), `tool_user` (external tool access), `orchestrator` (spawns sub-workflows), `human_gate` (pauses for human input), and `action_executor` (performs real-world side effects via tools).
- **FR-003**: System MUST support four agent output types: `text`, `structured_data`, `side_effect`, and `composite`, with inference of default output type from behavior type when not specified.
- **FR-004**: System MUST support optional per-agent `max_tokens` to cap LLM output length, and optional per-agent `context_budget` to cap input context size.
- **FR-005**: System MUST provide three team composition modes: template (load from library), custom (developer-provided configuration), and LLM-generated (delegate team design to an LLM).
- **FR-006**: System MUST validate all team configurations against a defined schema before execution, checking for structural conformance, dangling agent references, and tool availability.
- **FR-007**: System MUST support workflow graphs with sequential steps, parallel fan-out, conditional branching (accept/reject) with a configurable per-step maximum iteration count (default: 3), human-in-the-loop gates, and gated steps (workflow-level pauses).
- **FR-008**: System MUST provide a top-level `HiveFlow` entry point with async `run()` and synchronous `run_sync()` methods for workflow execution.
- **FR-009**: System MUST represent running workflows as `WorkflowSession` objects that are inspectable (status, result), pausable, resumable, and cancellable.
- **FR-010**: System MUST provide discovery APIs for teams, archetypes, tools, and models that return serializable summaries.
- **FR-011**: System MUST emit structured workflow events (step_start, step_complete, step_error, output, tool_call, request_info, approval) consumable as an async iterator.
- **FR-012**: System MUST expose human-in-the-loop as explicit pause/request/resume operations on a session, not as callbacks.
- **FR-013**: System MUST support per-agent model selection via explicit model name or declarative model requirements (strengths, capabilities, cost tier) resolved at build time.
- **FR-014**: System MUST ensure all public API inputs and outputs are JSON-serializable (no opaque Python objects required as inputs).
- **FR-015**: System MUST provide an archetype library for storing and loading reusable agent definitions as configuration files, with archetypes copied inline into team configurations at composition time.
- **FR-016**: System MUST report capability gaps when generating teams via LLM, categorized by severity (blocking, degraded, functional_but_limited) with suggested fallback strategies.
- **FR-017**: System MUST support state schema enforcement at the workflow engine level with configurable modes: `warn` (log warnings for undeclared writes, default), `strict` (filter state to declared reads/writes), and `off` (no enforcement).
- **FR-018**: System MUST support per-agent action safety policies for `action_executor` agents: `auto` (execute immediately) and `require_approval` (pause for human approval before executing). Each executed action MUST be recorded in the workflow state as a structured audit entry.
- **FR-019**: System MUST support workflow checkpointing at human gates and gated steps, persisting full workflow state (current step, accumulated state, pending approval requests) to file-based storage so that workflows can be resumed across process restarts.

### Key Entities

- **Agent**: The universal execution unit, specialized through configuration. Attributes: identity (id, role, system prompt), behavior type, tools, model, output type, max tokens, context budget, action policy (for `action_executor` agents). Produces an `AgentResult` upon execution.
- **TeamConfiguration**: A complete definition of a multi-agent team, including a roster of agent definitions and a workflow graph. Self-contained and serializable as JSON/YAML.
- **AgentDefinition**: The specification for a single agent within a team, including its system prompt, behavior type, tools, model assignment or model requirements, output type, and action policy (when behavior type is `action_executor`).
- **WorkflowGraph**: An ordered set of workflow step definitions that express agent execution topology (sequential, parallel, conditional, gated).
- **WorkflowSession**: A handle to a running or completed workflow. Provides session ID, status, result, pending approval requests, resume/cancel operations, and event streaming.
- **Archetype**: A reusable, standalone agent definition stored as configuration. Building blocks that compose into teams. Loaded by an ArchetypeLibrary.
- **TeamLibrary**: A named collection of pre-built team configurations, loadable from directories or bundled defaults.
- **ArchetypeLibrary**: A named collection of reusable agent definitions, loadable from directories or bundled defaults.
- **WorkflowEvent**: A structured event emitted during workflow execution for observability (step lifecycle, tool calls, outputs, approvals).
- **CapabilityGap**: A report of a tool or capability that an LLM-generated team needs but is not available, with severity and fallback strategy.
- **StateSchema**: Declares required state keys and per-agent read/write mappings for state enforcement.
- **WorkflowCheckpoint**: A serialized snapshot of a paused workflow's state, including current step, accumulated state, pending approval requests, and iteration counts. Used for durable persistence and cross-process resume.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A developer can define and execute a single-agent workflow with fewer than 10 lines of code, receiving a result within the expected LLM response time.
- **SC-002**: A developer can load a pre-built team template and execute a multi-agent workflow with fewer than 5 lines of code.
- **SC-003**: Team configurations are fully portable — a saved configuration file can be used on any machine with the framework installed, without requiring the original archetype library.
- **SC-004**: All invalid team configurations (dangling references, missing tools, schema violations) are caught at validation time before any LLM calls are made.
- **SC-005**: Workflows with human-in-the-loop gates can be paused, checkpointed to durable storage, and resumed — even across process restarts — without losing any intermediate state.
- **SC-006**: The framework supports at least 4 distinct workflow topologies (sequential, parallel fan-out, conditional branching, gated steps) composable within a single workflow.
- **SC-007**: LLM-generated teams produce valid, executable configurations with clear capability gap reports at least 90% of the time for common task domains.
- **SC-008**: All public API operations are usable from both async and synchronous contexts without requiring consumers to manage event loops.
- **SC-009**: Workflow events are delivered in real time with less than 100ms latency from the underlying operation, enabling responsive UIs and monitoring dashboards.
- **SC-010**: The discovery APIs enumerate all registered resources (teams, archetypes, tools, models) with sufficient metadata for a UI to present meaningful choices to the user.

## Assumptions

- Developers have access to at least one LLM provider (OpenAI, Anthropic, or Azure OpenAI) with valid API credentials.
- The framework runs in Python 3.11+ environments.
- Tool plugins are registered before workflow execution and are available for the duration of the workflow.
- Human-in-the-loop approvals happen through the consuming application's UI (REST endpoint, CLI prompt, desktop dialog) — the framework provides the pause/resume mechanism, not the presentation layer.
- LLM-generated team configurations target common task domains (research, content creation, code review, decision-making). Highly specialized domains may require manual team authoring.
- Per-agent model selection assumes the referenced models are available in the provider registry at execution time.
