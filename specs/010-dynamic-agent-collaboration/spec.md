# Feature Specification: Dynamic Agent Collaboration

**Feature Branch**: `010-dynamic-agent-collaboration`
**Created**: 2026-03-04
**Status**: Draft
**Input**: User description: "Enable agents within a running workflow to dynamically collaborate at runtime — decomposing tasks, delegating work, recruiting specialist agents, and communicating directly — without requiring the full workflow graph to be defined ahead of time."

## Clarifications

### Session 2026-03-04

- Q: When a workflow is checkpointed while delegations are in-flight, what should happen on resume? → A: In-flight delegations restart from scratch on workflow resume (stateless delegation). The timeout mechanism bounds the cost of re-execution.
- Q: What tool access boundaries apply to spawned agents? → A: Spawned agents can use their parent orchestrator's tools plus any tools defined by their archetype. They cannot access arbitrary tools from the global registry beyond this combined set.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Runtime Task Delegation (Priority: P1)

A workflow operator sets up an orchestrator agent to handle a complex, open-ended task. During execution, the orchestrator encounters a sub-problem that requires specialist expertise. Without stopping the workflow or reconfiguring the team, the orchestrator delegates that sub-task to another agent, waits for the result, and incorporates it into its own output.

**Why this priority**: This is the foundational capability that all other collaboration features build upon. Without runtime delegation, agents are locked into the static execution graph defined before the workflow starts. This single capability unlocks the core value proposition — agents that adapt to the problem as it unfolds.

**Independent Test**: Can be fully tested by running an orchestrator agent that delegates a sub-task to an existing team member and receives the result. Delivers immediate value by allowing agents to break work into pieces dynamically.

**Acceptance Scenarios**:

1. **Given** a running workflow with an orchestrator agent and at least one other agent in the team, **When** the orchestrator decides a sub-task should be handled by the other agent, **Then** the orchestrator can delegate that sub-task, receive the result, and use it in its final output.
2. **Given** a delegation request with no specific target agent, **When** the orchestrator delegates with automatic agent selection, **Then** the system matches the sub-task to the most appropriate available agent based on the agent's role and capabilities.
3. **Given** a delegated sub-task, **When** the delegate agent completes the work, **Then** the result is returned to the orchestrator and a completion event is recorded in the workflow's event stream.
4. **Given** a delegation request, **When** the maximum delegation depth has been reached, **Then** the system refuses the delegation and informs the orchestrator that the depth limit has been exceeded.

---

### User Story 2 - Dynamic Agent Spawning (Priority: P1)

A workflow operator configures an orchestrator agent with access to a library of agent archetypes. During execution, the orchestrator determines that additional specialist agents are needed — either more instances of an existing role or entirely new roles. The orchestrator creates these agents on-the-fly from the archetype library or from custom definitions, and dispatches work to them.

**Why this priority**: Spawning and delegation are tightly coupled — spawning provides the agents that delegation targets. Together they form the minimum viable dynamic collaboration system. Without spawning, delegation is limited to pre-configured agents, which significantly reduces the adaptability benefit.

**Independent Test**: Can be fully tested by running an orchestrator that spawns a specialist agent from an archetype, delegates a task to it, and receives the result. Delivers value by allowing team composition to adapt to the problem.

**Acceptance Scenarios**:

1. **Given** an orchestrator agent with access to an archetype library, **When** the orchestrator requests a new specialist agent by archetype name, **Then** a new agent is created from that archetype and registered in the running workflow's agent pool.
2. **Given** an orchestrator agent, **When** the orchestrator provides a custom agent definition (role and instructions), **Then** a new agent is created with those specifications and made available for delegation.
3. **Given** a workflow with a configured maximum spawned agent limit, **When** the orchestrator attempts to spawn an agent that would exceed this limit, **Then** the system refuses the spawn and informs the orchestrator that the limit has been reached.
4. **Given** a spawned agent, **When** the workflow execution completes, **Then** the spawned agent is not persisted to the team configuration (spawned agents are ephemeral).

---

### User Story 3 - Inter-Agent Messaging (Priority: P2)

Agents within a running workflow can send targeted messages to each other — asking clarifying questions, sharing findings, or requesting feedback — beyond the linear state pipeline. This enables richer collaboration patterns such as review cycles, negotiation, and information broadcasting.

**Why this priority**: Messaging enables collaboration patterns that go beyond simple task delegation. It allows agents to negotiate, clarify, and iterate — making the overall collaboration more intelligent. However, useful collaboration is possible with delegation and spawning alone, making messaging an enhancement rather than a prerequisite.

**Independent Test**: Can be fully tested by running two agents where one sends a message to the other, and the recipient reads and acts on it in its next execution. Delivers value by enabling richer agent-to-agent communication.

**Acceptance Scenarios**:

1. **Given** two agents in a running workflow, **When** one agent sends a targeted message to the other, **Then** the message is available to the recipient agent in its next execution context.
2. **Given** an agent with a message requiring a response, **When** the recipient agent processes the message, **Then** the recipient can send a reply back to the original sender.
3. **Given** an agent that sends a broadcast message, **When** any other agent in the workflow next executes, **Then** each agent sees the broadcast message in its context.
4. **Given** multiple messages sent to an agent, **When** the agent requests only unread messages, **Then** only messages not previously processed are returned.

---

### User Story 4 - Collaborative Task Planning (Priority: P2)

An orchestrator agent receives a complex, multi-faceted task. It analyzes the task, decomposes it into sub-tasks with dependency relationships, identifies which specialist agents are needed, spawns or assigns them, and coordinates their parallel or sequential execution. The orchestrator then synthesizes all results into a coherent final output.

**Why this priority**: This represents the highest-level collaboration pattern — a full plan-and-execute loop. It composes the delegation and spawning capabilities into a powerful automated workflow within a workflow. It is prioritized after messaging because it builds on all prior capabilities and represents an advanced use case.

**Independent Test**: Can be fully tested by giving an orchestrator a complex task (e.g., "Build a marketing campaign analysis") and verifying that it decomposes the task, assigns sub-tasks to appropriate agents, runs independent sub-tasks concurrently, and synthesizes results.

**Acceptance Scenarios**:

1. **Given** an orchestrator with planning capabilities and a complex task, **When** the orchestrator analyzes the task, **Then** it produces a structured plan with identified sub-tasks, dependency relationships, and agent assignments.
2. **Given** a plan with independent sub-tasks (no dependencies between them), **When** the orchestrator executes the plan, **Then** the independent sub-tasks are executed concurrently.
3. **Given** a plan with dependent sub-tasks, **When** the orchestrator executes the plan, **Then** dependent sub-tasks wait for their prerequisites to complete before starting.
4. **Given** a sub-task that returns insufficient results, **When** the orchestrator evaluates the quality, **Then** the orchestrator can re-delegate the sub-task with additional feedback or guidance.

---

### Edge Cases

- What happens when a delegated agent exceeds the configured timeout? The delegation is terminated and the orchestrator is informed of the timeout, allowing it to retry or take alternative action.
- What happens when an agent delegates to itself (cycle)? The system detects self-delegation and rejects it with an error.
- What happens when the maximum delegation depth is reached mid-chain? The deepest agent receives a clear refusal and must complete its work without further delegation.
- What happens when the spawned agent limit is reached? The orchestrator receives a clear refusal and must work with the agents already available.
- What happens when a delegated agent fails (exception or error)? A failure event is recorded and the orchestrator receives the error information, allowing it to retry, delegate to a different agent, or handle the failure gracefully.
- What happens when budget is exhausted during a delegation chain? The delegation is terminated, remaining budget information is surfaced, and the orchestrator can decide how to proceed.
- What happens when an orchestrator tries to spawn an agent with an archetype that does not exist? The system returns an error indicating the archetype was not found, listing available archetypes.
- What happens when messages are sent to an agent that has already finished executing? The message is stored and available if the agent is invoked again; otherwise, it remains undelivered in the message store.
- What happens when a workflow is checkpointed while a delegation chain is in progress? All in-flight delegations are discarded. On resume, the orchestrator re-executes from its last checkpointed state, reissuing delegations as needed.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST allow orchestrator-type agents to delegate sub-tasks to other agents during workflow execution and receive the results.
- **FR-002**: The system MUST support automatic agent selection for delegation, matching sub-task descriptions to the best available agent based on role and capability metadata.
- **FR-003**: When no suitable agent exists for a delegation, the system MUST create a default general-purpose agent to handle the sub-task.
- **FR-004**: The system MUST allow orchestrator agents to create new agents at runtime from the archetype library.
- **FR-005**: The system MUST allow orchestrator agents to create new agents at runtime from custom inline definitions specifying a role and instructions.
- **FR-006**: The system MUST assign each spawned agent a unique identifier and register it in the running workflow's agent pool.
- **FR-007**: Spawned agents MUST be ephemeral — they exist only for the duration of the current workflow execution and are not persisted to the team configuration.
- **FR-008**: The delegated agent MUST receive a filtered copy of the parent's state (not the full state), including the delegated task and any explicitly provided context.
- **FR-009**: The system MUST enforce a configurable maximum delegation depth to prevent infinite delegation chains (default: 3 levels).
- **FR-010**: The system MUST enforce a configurable maximum number of spawned agents per workflow execution (default: 10 agents).
- **FR-011**: The system MUST enforce a configurable timeout for delegated tasks (default: 300 seconds).
- **FR-012**: The system MUST prevent agents from delegating tasks to themselves (cycle detection).
- **FR-013**: Only agents with the orchestrator behavior type MUST be permitted to spawn agents, delegate tasks, or compose sub-teams.
- **FR-014**: The system MUST allow agents to send targeted messages to specific other agents.
- **FR-015**: The system MUST allow agents to send broadcast messages to all agents in the workflow.
- **FR-016**: The system MUST allow agents to read their unread messages, with the option to also read previously read messages.
- **FR-017**: Messages MUST be delivered asynchronously — written to shared state and read by the target agent on its next execution.
- **FR-018**: The system MUST record all collaboration events (spawning, delegation start/complete/fail, messages sent, plans created) in the workflow's event stream and audit trail.
- **FR-019**: The system MUST support configurable budget policies for spawned agents and delegated tasks, controlling how cost and token budgets propagate from parent to child.
- **FR-020**: Spawned agents MUST NOT be permitted to act as orchestrators by default, preventing recursive spawning. This restriction MUST be overridable via configuration with a mandatory maximum delegation depth.
- **FR-021**: The system MUST support collaborative task planning where an orchestrator decomposes a complex task into sub-tasks with dependency relationships, assigns agents, and coordinates execution.
- **FR-022**: Independent sub-tasks within a plan (no dependencies) MUST be eligible for concurrent execution.
- **FR-023**: The system MUST allow dynamic collaboration to be enabled or disabled at the team configuration level.
- **FR-024**: Team-level collaboration settings MUST override global default settings.
- **FR-025**: When a workflow is checkpointed during an active delegation, in-flight delegations MUST be treated as incomplete. On resume, they MUST restart from scratch (stateless delegation).
- **FR-026**: The maximum delegation depth, delegation timeout, and maximum spawned agent count MUST each be independently configurable at both the global and team levels, with team-level values overriding global defaults.
- **FR-027**: Spawned agents MUST only have access to tools from the union of their parent orchestrator's tool set and their archetype-defined tool set. They MUST NOT access arbitrary tools from the global registry beyond this combined set.

### Key Entities

- **Delegation**: Represents a sub-task assigned by one agent to another during execution. Contains the task description, source agent, target agent, context, expected output type, depth level, and result.
- **Spawned Agent**: An ephemeral agent created at runtime from an archetype or custom definition. Has a unique ID, role, instructions, and is scoped to the current workflow execution.
- **Message**: A communication from one agent to another (or broadcast). Contains sender, recipient, subject, body, response-required flag, timestamp, and read status.
- **Task Plan**: A structured decomposition of a complex task into sub-tasks with dependency relationships, agent assignments, and expected output types.
- **Collaboration Configuration**: The settings governing dynamic collaboration behavior — enablement, depth limits, spawn limits, timeouts, budget policies, and recursive orchestrator permissions.
- **Agent Pool**: The runtime registry of all agents available in a workflow execution, including both pre-configured and dynamically spawned agents.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An orchestrator agent can delegate a sub-task to another agent and receive the result within a single workflow execution, end-to-end, without manual intervention.
- **SC-002**: An orchestrator agent can spawn at least 5 specialist agents from archetypes during a single workflow execution and delegate different tasks to each one.
- **SC-003**: A 3-level delegation chain (orchestrator delegates to agent A, which delegates to agent B) completes successfully and returns results back through the chain.
- **SC-004**: Independent sub-tasks within a plan execute concurrently, completing faster than sequential execution of the same tasks.
- **SC-005**: When the delegation depth limit is reached, the system prevents further delegation and the workflow completes without error or hang.
- **SC-006**: When the spawned agent limit is reached, the system prevents further spawning and the orchestrator can still complete its task with available agents.
- **SC-007**: All collaboration events (spawn, delegate, message, plan) appear in the workflow audit trail with sufficient detail to reconstruct the collaboration history.
- **SC-008**: Two agents can exchange messages (send and reply) within a workflow execution, enabling a review-and-revise cycle.
- **SC-009**: Budget enforcement prevents a delegation chain from consuming more resources than allocated, and the workflow terminates gracefully when budget is exhausted.
- **SC-010**: Enabling dynamic collaboration on an existing team does not change the behavior of workflows that do not use delegation, spawning, or messaging features (backward compatibility).

## Assumptions

- The existing archetype library contains sufficient agent definitions for common specialist roles (e.g., researcher, writer, reviewer). If the library is sparse, the custom inline definition path provides a fallback.
- Agent execution is already async-capable, allowing concurrent execution of independent delegated tasks.
- The shared state dictionary is the standard mechanism for inter-agent data flow, and extending it with a messages namespace is consistent with the existing architecture.
- Budget tracking and cost monitoring infrastructure already exists and can be extended to track per-delegation costs.
- The event stream and audit trail infrastructure already exists and can accept new event types without modification.
- Reasonable defaults (depth limit of 3, spawn limit of 10, timeout of 300 seconds) are appropriate for most use cases and can be overridden per team.

## Dependencies

- Core architecture (agents, workflows, shared state)
- Workflow engine (execution, event streaming, checkpoints)
- Agents and teams (behavior types, archetypes, team configuration)
- Plugin system (tool plugins, tool registry)
