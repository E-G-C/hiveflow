# Feature Specification: Agents and Teams

**Feature Branch**: `005-agents-and-teams`
**Created**: 2026-02-24
**Status**: Draft
**Input**: User description: "Implement agents and teams system with behavior types, archetypes, team composition, and workflow step types (from requirements/03-agents-and-teams.md)"

## Clarifications

### Session 2026-02-24

- Q: When parallel fan-out agents write results back to shared workflow state, what merge strategy should be used? → A: Namespaced keys — each parallel instance writes to an indexed sub-key (e.g., `research_data.item_0`, `research_data.item_1`), and results are collected as a list for the next step.
- Q: When a conditional step receives an ambiguous result (neither accept nor reject), what should happen? → A: Default to reject path — ambiguous results follow `next_on_reject` as a conservative fail-safe.
- Q: When a non-action agent (llm_only, tool_user, etc.) fails during execution, what should happen? → A: Configurable per-agent via an optional `on_failure` field with values `fail` (default), `retry`, or `skip`. When omitted, agent failure halts the workflow.
- Q: Should conditional workflow steps that form review loops have iteration limits to prevent infinite cycling? → A: Yes — configurable per-step via an optional `max_iterations` field on conditional steps (default: 3). Workflow fails with an error when exceeded.
- Q: How should transient LLM API errors (429, 5xx) be handled before triggering the agent's `on_failure` policy? → A: Automatic exponential backoff retries (e.g., up to 3 times) for transient errors (429, 5xx) before triggering `on_failure`.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Define and Run a Team from Configuration (Priority: P1)

A developer creates a team configuration file (JSON or YAML) that defines multiple agents with different behavior types and a workflow connecting them. The developer loads this configuration, the system validates it, and the team executes the defined workflow against a given task.

**Why this priority**: This is the foundational capability. Without the ability to define agents, assign behavior types, and wire them into a workflow via configuration, no other feature in this spec is useful. It delivers immediate value: a developer can define a multi-agent team and run it.

**Independent Test**: Can be fully tested by creating a team configuration file with 2-3 agents (e.g., a researcher + writer + reviewer), loading it, and verifying the workflow executes each agent in the declared order, passing state between them.

**Acceptance Scenarios**:

1. **Given** a valid team configuration with three agents (editor, researcher, writer) and sequential workflow steps, **When** the developer loads and runs the team, **Then** each agent executes in order, reads from and writes to the shared workflow state, and the final output reflects contributions from all agents.
2. **Given** a team configuration with an agent referencing a non-existent tool, **When** the developer loads the configuration, **Then** the system rejects it with a clear validation error identifying the missing tool.
3. **Given** a team configuration with a workflow step referencing an agent ID not in the agent roster, **When** the developer loads the configuration, **Then** the system rejects it with a validation error identifying the dangling reference.
4. **Given** a team configuration where an agent has `behavior_type` set to `llm_only`, **When** that agent executes, **Then** it performs a prompt-to-LLM-to-response cycle without tool access.
5. **Given** a team configuration where an agent has `behavior_type` set to `tool_user`, **When** that agent executes, **Then** it can invoke its declared tools during execution.

---

### User Story 2 - Use Archetypes to Compose Teams (Priority: P2)

A developer browses an archetype library of reusable agent definitions (researcher, planner, writer, reviewer, etc.), selects the ones they need, and composes them into a new team configuration. The selected archetypes are copied inline so the saved team is self-contained.

**Why this priority**: Archetypes reduce duplication and make team creation faster by providing pre-built agent definitions. This builds on Story 1 and enables the reuse pattern that makes the framework practical at scale.

**Independent Test**: Can be fully tested by loading the default archetype library, retrieving archetypes by name, composing them into a team configuration, and verifying the resulting team file contains full inline agent definitions with no external references.

**Acceptance Scenarios**:

1. **Given** an archetype library with built-in archetypes (researcher, planner, writer, reviewer, editor, human_reviewer), **When** the developer lists archetypes, **Then** all six are returned with their names and descriptions.
2. **Given** a developer selects the "researcher" and "writer" archetypes, **When** they compose a team, **Then** the resulting team configuration contains full inline copies of both agent definitions, not references.
3. **Given** a developer saves a team composed from archetypes, **When** an archetype in the library is later updated, **Then** the saved team file remains unchanged and continues to work as before.
4. **Given** the developer has a custom directory of archetype files, **When** they create an archetype library from that directory, **Then** all archetypes in the directory are loaded and available.

---

### User Story 3 - Execute Action-Oriented Agents with Safety Policies (Priority: P2)

A developer configures an agent with `behavior_type: action_executor` and assigns an action safety policy (auto, require_approval, dry_run, or confirm_on_error). When the workflow reaches this agent, the system enforces the configured policy before executing any real-world side effects.

**Why this priority**: Action-oriented agents are what differentiate HiveFlow from text-only agent frameworks. They enable agents to perform real-world actions (deploy, create files, send messages) with appropriate safety controls. This is a core differentiator and essential for production use.

**Independent Test**: Can be fully tested by configuring an action_executor agent with `require_approval` policy, running the workflow, verifying it pauses for approval, and then checking the audit trail records the action.

**Acceptance Scenarios**:

1. **Given** an action_executor agent with `action_policy: auto`, **When** the agent determines an action to take, **Then** the action executes immediately without pausing.
2. **Given** an action_executor agent with `action_policy: require_approval`, **When** the agent determines an action to take, **Then** the workflow pauses and waits for approval before executing.
3. **Given** an action_executor agent with `action_policy: dry_run`, **When** the agent determines an action to take, **Then** the system reports what would be executed without performing the action.
4. **Given** any action executed by an action_executor agent, **When** the action completes, **Then** the system records a structured audit trail entry containing agent ID, action, tool used, input, output, policy, timestamp, and reversibility.
5. **Given** an action_executor agent with `rollback_on_failure: true` that executes a reversible action, **When** a downstream step determines the action was incorrect, **Then** the system can trigger the declared rollback action.

---

### User Story 4 - Workflow Step Types Including Gated and Conditional (Priority: P2)

A developer defines a workflow with various step types — sequential, parallel fan-out, conditional branching, and gated steps — to create sophisticated multi-agent coordination patterns.

**Why this priority**: Different problems require different coordination patterns. Sequential-only workflows are limiting. Parallel fan-out, conditional branching, and gated steps enable real-world workflow patterns like review loops, approval gates, and parallel research tasks.

**Independent Test**: Can be fully tested by defining a workflow that includes one of each step type and verifying each behaves correctly: sequential proceeds to next, parallel fans out, conditional branches on accept/reject, and gated pauses for approval.

**Acceptance Scenarios**:

1. **Given** a workflow step with `type: sequential`, **When** the agent completes, **Then** execution proceeds to the `next` agent.
2. **Given** a workflow step with `type: parallel_fan_out`, **When** the agent runs, **Then** it executes once per parallel item from the previous step's output, writing results to namespaced sub-keys (e.g., `research_data.item_0`, `research_data.item_1`) that are collected as a list for the next step.
3. **Given** a workflow step with `type: conditional`, **When** the agent produces an accept result, **Then** execution proceeds to `next_on_accept`; **When** the agent produces a reject result, **Then** execution proceeds to `next_on_reject`.
4. **Given** a workflow step with `type: conditional`, **When** the agent produces an ambiguous result that is neither accept nor reject, **Then** execution defaults to `next_on_reject` and logs a warning.
5. **Given** a workflow step with `type: gated` and `gate: human_approval`, **When** the workflow reaches this step, **Then** execution pauses before the agent runs and waits for human approval.
6. **Given** a gated step combined with workflow checkpointing, **When** the workflow pauses at the gate, **Then** the state is automatically checkpointed so the process can stop and resume later when approval arrives.
7. **Given** a conditional step with `max_iterations: 3` forming a reviewer-reviser loop, **When** the reviewer rejects 3 times consecutively, **Then** the workflow halts with an iteration-limit error rather than looping indefinitely.

---

### User Story 5 - LLM-Generated Team Composition (Priority: P3)

When no pre-built team template fits the developer's task, they can ask the system to generate a team configuration using an LLM. The LLM receives the task description, available tools, models, and archetypes, and produces a validated team configuration along with capability gap reports.

**Why this priority**: This is an advanced bootstrapping capability. It requires Stories 1 and 2 to be functional first (you need the schema, validation, and archetype system in place). It's powerful but optional — developers can always hand-author configurations.

**Independent Test**: Can be fully tested by providing a task description and tool/model registries, calling the generation function, and verifying the returned result contains a valid team configuration, any capability gaps, and any new archetypes the LLM invented.

**Acceptance Scenarios**:

1. **Given** a task description and available tool/model registries, **When** the developer calls the team generation function, **Then** the system returns a `TeamGenerationResult` containing a valid `TeamConfiguration`, a list of `CapabilityGap` entries, and any `new_archetypes` invented by the LLM.
2. **Given** the LLM generates a team that needs a tool not in the registry, **When** the gap severity is `blocking`, **Then** the system rejects the configuration and reports what tool is needed.
3. **Given** the LLM generates a team with a `degraded` gap, **When** the result is returned, **Then** the system warns about the limitation and suggests a fallback behavior type.
4. **Given** `auto_approve=False` (default), **When** the team is generated, **Then** the result is returned for developer inspection before execution begins.
5. **Given** `auto_approve=True` and no blocking gaps, **When** the team is generated, **Then** the team proceeds directly to execution.

---

### User Story 6 - Per-Agent Model Selection and Capability Requirements (Priority: P3)

A developer assigns specific models to agents or declares capability requirements (strengths, tool calling support, context window needs) so the system selects the best available model at build time.

**Why this priority**: Model selection is important for production quality but the system works with defaults initially. This is an optimization and portability feature that becomes critical as teams grow and agents have diverse needs.

**Independent Test**: Can be fully tested by configuring agents with `model_requirements` instead of explicit model names, running the build step, and verifying the system resolves each agent to an appropriate model from the registry.

**Acceptance Scenarios**:

1. **Given** an agent with an explicit `model` field set, **When** the team is built, **Then** that exact model is used regardless of any `model_requirements`.
2. **Given** an agent with `model_requirements` specifying `strengths: ["coding"]` and `supports_tool_calling: true`, **When** the team is built, **Then** the system selects a model from the registry that matches those requirements.
3. **Given** an agent with neither `model` nor `model_requirements`, **When** the team is built, **Then** the team-level or global default model is used.
4. **Given** an agent using tier variables like `$SMART_LLM`, **When** the team is built, **Then** the variable resolves to the configured model for that tier.

---

### User Story 7 - State Schema Enforcement (Priority: P3)

A developer defines a state schema on the team configuration that declares which state keys each agent reads and writes. The system enforces these boundaries at runtime to prevent agents from accessing or modifying state they shouldn't.

**Why this priority**: State enforcement is a safety and debugging feature. The system works without it (enforcement defaults to off/warn). It becomes important for production workflows, especially those with action_executor agents where uncontrolled state access is a security concern.

**Independent Test**: Can be fully tested by defining a team with `state_schema.agent_io` mappings, setting enforcement to `warn` mode, running the workflow where an agent writes an undeclared key, and verifying a warning is logged.

**Acceptance Scenarios**:

1. **Given** a team with `state_schema` defined and enforcement set to `warn`, **When** an agent writes a state key not in its declared `writes` list, **Then** the system logs a warning but allows the write.
2. **Given** a team with no `state_schema` defined, **When** enforcement is set to any mode, **Then** enforcement is automatically `off` and agents have unrestricted state access.
3. **Given** enforcement set to `off`, **When** agents read and write any state keys, **Then** no checks or warnings are produced.

---

### Edge Cases

- What happens when a team configuration references an agent ID in a workflow step that does not exist in the agents roster? The system must reject the configuration with a descriptive validation error.
- What happens when an action_executor agent's configured tool is unavailable at runtime? The system must report the missing tool and either skip the action or fail gracefully depending on the action policy.
- What happens when a conditional workflow step receives an ambiguous result that is neither accept nor reject? The system defaults to the reject path (`next_on_reject`) as a conservative fail-safe, and logs a warning that the result was ambiguous.
- What happens when a gated step's approval never arrives? The checkpointed state must persist indefinitely and the workflow must be resumable at any later time.
- What happens when an LLM-generated team configuration fails schema validation? The system must report specific validation failures and not attempt to execute the invalid configuration.
- What happens when parallel fan-out produces zero items? The system must handle empty fan-out gracefully and proceed to the next step with an empty result set.
- What happens when parallel fan-out agents target the same declared write key? Each parallel instance writes to a namespaced indexed sub-key; the framework collects them into a list for the downstream step.
- What happens when an archetype file is malformed JSON? The archetype library must skip it with a warning rather than failing to load entirely.
- What happens when rollback is triggered but the rollback action itself fails? The system must log the rollback failure and surface it to the developer rather than silently continuing.
- What happens when a non-action agent fails during execution? The system applies the agent's `on_failure` policy: `fail` (default) halts the workflow, `retry` re-executes up to the configured retry count then halts, `skip` logs the failure and proceeds to the next workflow step. For transient LLM API errors (429, 5xx), the system automatically applies exponential backoff retries (up to 3 times) before considering it a failure and triggering the `on_failure` policy.
- What happens when a conditional step's reject path creates a review loop that never converges? The step's `max_iterations` limit (default: 3) caps the number of reject-path cycles; when exceeded, the workflow halts with an iteration-limit error.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST support defining agents with five behavior types: `llm_only`, `tool_user`, `orchestrator`, `human_gate`, and `action_executor`
- **FR-002**: System MUST validate team configurations against the schema before execution, checking structural conformance, dangling agent references, and tool availability
- **FR-003**: System MUST support the `action_executor` behavior type with four safety policies: `auto`, `require_approval`, `dry_run`, and `confirm_on_error`
- **FR-004**: System MUST record a structured audit trail for every action executed by an `action_executor` agent, including agent ID, action, tool, input, output, policy, timestamp, and reversibility
- **FR-005**: System MUST support rollback for reversible actions when `rollback_on_failure` is enabled on an action_executor agent
- **FR-006**: System MUST support four agent output types: `text`, `structured_data`, `side_effect`, and `composite`, with default inference from behavior type when not specified
- **FR-007**: System MUST support six workflow step types: `sequential`, `parallel_fan_out`, `conditional`, `human_gate`, `gated`, and `sub_workflow`
- **FR-008**: System MUST support the `gated` step type with a `human_approval` gate that pauses execution before the agent runs and integrates with workflow checkpointing
- **FR-009**: System MUST provide an `ArchetypeLibrary` that loads reusable agent definitions from directories, with built-in archetypes for researcher, planner, writer, reviewer, editor, and human_reviewer
- **FR-010**: System MUST copy archetypes inline when composing teams so that saved team configurations are self-contained with no external references
- **FR-011**: System MUST provide a `TeamLibrary` that loads team configurations from directories and provides access by name
- **FR-012**: System MUST support three team composition modes: template (from library), custom (developer-provided), and LLM-generated
- **FR-013**: System MUST support LLM-generated team composition that receives task description, tool registry, model registry, and archetype library, and returns a `TeamGenerationResult` with the configuration, capability gaps, and new archetypes
- **FR-014**: System MUST classify capability gaps by severity (`blocking`, `degraded`, `functional_but_limited`) and reject configurations with blocking gaps
- **FR-015**: System MUST support per-agent model selection via explicit `model` field or declarative `model_requirements` with build-time resolution, where explicit model takes precedence
- **FR-016**: System MUST support state schema enforcement with three modes: `warn` (default), `strict`, and `off`
- **FR-017**: System MUST support tier variables (`$SMART_LLM`, `$FAST_LLM`) as a simpler alternative to `model_requirements`
- **FR-018**: System MUST persist teams and archetypes as JSON or YAML files using serialization methods on the configuration objects
- **FR-019**: System MUST support the `sub_workflow` step type that executes another team configuration as a nested workflow with input/output mappings
- **FR-020**: System MUST support an optional `on_failure` field on agent definitions with values `fail` (default), `retry`, and `skip`. When `fail`, agent failure halts the workflow. When `retry`, the agent re-executes up to a configurable retry count. When `skip`, the agent's failure is logged and the workflow proceeds to the next step.
- **FR-021**: System MUST automatically apply exponential backoff retries (up to 3 times) for transient LLM API errors (429, 5xx) before considering an agent execution failed and triggering its `on_failure` policy.
- **FR-022**: System MUST support an optional `max_iterations` field on conditional workflow steps (default: 3) that limits how many times the step's reject-path cycle can repeat. When exceeded, the workflow halts with an iteration-limit error.

### Key Entities

- **AgentDefinition**: Represents a single agent within a team. Key attributes: unique ID, role description, system prompt, behavior type, list of tools, model assignment, output type, optional model requirements, action policy (for action executors), and optional failure handling policy (`on_failure`).
- **TeamConfiguration**: A complete team definition containing a list of agent definitions, a workflow graph of steps, an optional state schema, team name, version, and description. Self-contained and portable.
- **WorkflowStepDefinition**: A single step in the workflow graph. Key attributes: agent ID, step type (sequential, parallel_fan_out, conditional, gated, sub_workflow), next step(s), optional gate type, and optional `max_iterations` for conditional steps (default: 3).
- **Archetype**: A reusable, standalone agent definition that exists outside any specific team. Stored as a file and copied inline during team composition. Includes optional metadata like tags and description.
- **ArchetypeLibrary**: A collection of archetypes loaded from one or more directories. Provides lookup by name and registration of new archetypes.
- **TeamLibrary**: A collection of team configurations loaded from directories. Provides lookup by name and registration of new teams.
- **ActionRecord**: A structured audit entry for actions performed by action_executor agents. Contains action ID, agent ID, workflow run ID, action details, policy applied, approval info, timestamp, and rollback information.
- **CapabilityGap**: Describes a missing capability identified during LLM team generation. Contains the affected agent, needed capability, severity level, and suggested fallback.
- **TeamGenerationResult**: The output of LLM-generated team composition. Wraps the runnable TeamConfiguration with generation metadata including capability gaps and new archetypes.
- **ModelRequirements**: Declarative specification of what an agent needs from its model. Includes desired strengths, tool calling support, structured output support, minimum context window, and cost tier.

## Assumptions

- The `self_configure` behavior type described in the requirements document is explicitly deferred to a future release and is not in scope for this feature.
- The `sub_workflow` step type is Phase 2 scope. The schema and validation should support it, but full nested execution may be delivered incrementally.
- The `strict` state enforcement mode is documented as future scope. The `warn` and `off` modes are the primary deliverables.
- `automated_check` and `webhook` gate types are future scope. Only `human_approval` is in scope for the `gated` step type.
- The `version` field on TeamConfiguration is developer-managed. The system does not enforce or track versioning.
- Team and archetype files use standard JSON or YAML formats. No custom serialization format is needed.
- The framework ships with 6 built-in archetypes (researcher, planner, writer, reviewer, editor, human_reviewer) and at least 3 example team configurations (research_report, code_review, content_creation).
- Action rollback is declarative (the agent declares a rollback action in configuration). The framework invokes the rollback tool; it does not automatically infer how to reverse arbitrary actions.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Developers can define a multi-agent team with 2+ agents and run it against a task, with all agents executing in the configured workflow order, within a single session.
- **SC-002**: All five behavior types (llm_only, tool_user, orchestrator, human_gate, action_executor) are functional and produce the expected execution patterns when used in a team configuration.
- **SC-003**: Team configurations with schema violations (dangling references, missing tools, invalid structure) are rejected with clear, actionable error messages identifying each problem.
- **SC-004**: The archetype library loads built-in archetypes and custom directory archetypes, and composed teams are fully self-contained (no external archetype references after composition).
- **SC-005**: Action executor agents with `require_approval` policy correctly pause execution and resume only after approval, with all actions recorded in the audit trail.
- **SC-006**: Workflow step types (sequential, parallel_fan_out, conditional, gated) each exhibit correct control flow behavior as defined in their specifications.
- **SC-007**: LLM-generated team composition produces valid, runnable configurations with accurate capability gap reports that correctly classify gap severity.
- **SC-008**: Per-agent model selection resolves correctly: explicit model wins over model_requirements, model_requirements resolves to an appropriate registered model, and absent settings fall back to team/global defaults.
- **SC-009**: State schema enforcement in `warn` mode logs warnings for undeclared writes, and `off` mode produces no enforcement overhead.
- **SC-010**: Developers can compose a new team from library archetypes and have it running against a task without writing any agent definitions from scratch.
