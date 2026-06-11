# Research: Dynamic Agent Collaboration

**Feature**: 010-dynamic-agent-collaboration
**Date**: 2026-03-04

## Research Topics

### R1: How to integrate collaboration tools into the existing Agent execution flow

**Decision**: Collaboration tools (`DelegateTaskTool`, `SpawnAgentTool`, `SendMessageTool`, `ReadMessagesTool`) are standard `ToolPlugin` implementations injected into orchestrator agents' tool lists at workflow build time. No changes to `Agent.execute()` or the tool-calling loop are needed.

**Rationale**: The existing `_execute_tool_user()` method already supports iterative tool calling — the agent calls tools, gets results, and decides what to do next. Delegation and spawning fit naturally into this loop: the orchestrator calls `delegate_task`, gets the result, and incorporates it. The `Agent` class doesn't need to know about collaboration; it just sees tools.

**Alternatives considered**:
- **New behavior type (e.g., `AgentBehaviorType.COLLABORATOR`)**: Rejected because it duplicates the `tool_user` loop and creates unnecessary branching in `Agent.execute()`. The orchestrator behavior type already exists and can host collaboration tools.
- **Direct method injection on Agent**: Rejected because it violates the plugin architecture principle (§2.4) and would require modifying the Agent class.

### R2: How to pass CollaborationRuntime context to tool plugins

**Decision**: The `CollaborationRuntime` instance is stored in the workflow state under the reserved key `_collaboration_runtime`. Each collaboration tool retrieves it from the `tool_input` context or from a state reference passed during tool construction. The runtime is created by `WorkflowEngine` when `collaboration.enabled` is true and injected into state before execution begins.

**Rationale**: This follows the existing pattern where `_stream_channel` is injected into state for event publishing. Tools already receive execution context through their `execute()` method's input dict. The runtime reference in state allows tools to access the agent pool, check depth limits, and enforce budgets without any special wiring.

**Alternatives considered**:
- **Global singleton runtime**: Rejected per §2.3 (Explicit State, No Magic) — no ambient context.
- **Constructor injection**: Each tool created with a runtime reference. This is also viable and avoids state pollution, but is less consistent with how `_stream_channel` is handled. We'll use a hybrid: the runtime is created per-workflow and tools receive it via a factory method during injection, while also having it available via state for spawned-agent tools.

### R3: How DelegateTaskTool constructs and executes a sub-agent

**Decision**: `DelegateTaskTool.execute()` resolves the target agent from the `CollaborationRuntime.agent_pool` (by ID or via auto-selection), constructs a filtered sub-state from the parent state, calls `await target_agent.execute(sub_state)`, and returns the result. The delegation depth is tracked via `_delegation_depth` in state, incremented before the sub-call.

**Rationale**: Using the existing `Agent.execute()` method means delegated agents behave identically to regular agents — same LLM calling, same tool access, same state conventions. The filtered sub-state (task + explicit context + shared documents) follows the existing `AgentIOMapping` pattern from `StateSchema`.

**Alternatives considered**:
- **Nested WorkflowEngine execution**: Only needed for sub-team delegation (Phase 2). For single-agent delegation, direct `agent.execute()` is simpler and has less overhead.
- **New execution pathway**: Rejected — reuses battle-tested Agent execution flow.

### R4: How SpawnAgentTool creates agents at runtime

**Decision**: `SpawnAgentTool.execute()` takes either an `archetype` name (resolved via `ArchetypeLibrary`) or a `custom_definition` dict, converts it into an `Agent` instance using the same `LLMProvider` and `LLMConfig` inherited from the parent orchestrator, resolves tool references against the `ToolRegistry` (scoped to parent tools + archetype tools per FR-027), assigns a unique ID, and registers the agent in `CollaborationRuntime.agent_pool`.

**Rationale**: The `ArchetypeLibrary.get()` method already returns archetype dicts with `role`, `system_prompt`, `behavior_type`, and `tools` — exactly what's needed to construct an `Agent`. Tool scoping is enforced at spawn time by filtering the tool list against the allowed set (parent + archetype).

**Alternatives considered**:
- **AgentDefinition schema validation**: Convert archetype/custom to `AgentDefinition` pydantic model first for validation. This adds safety but also coupling. Decision: validate key fields inline (role required, system_prompt required) without full schema — keeps it lightweight.
- **Deferred tool resolution**: Resolve tools at delegation time, not spawn time. Rejected — resolving at spawn time catches errors early (missing tool → immediate error to orchestrator).

### R5: How auto-selection matches tasks to agents

**Decision**: Auto-selection in `DelegateTaskTool` uses a simple keyword/metadata matching approach: each agent in the pool has `role` and optionally `tags` metadata. The task description is compared against agent roles and tags using basic string containment and overlap scoring. If no match exceeds a threshold, the system falls back to spawning a default `llm_only` agent (per FR-003).

**Rationale**: Full semantic matching (embeddings, LLM-based selection) adds latency and complexity. For the initial implementation, simple heuristic matching is sufficient — orchestrators that know exactly which agent they want will use `delegate_to` with an explicit ID. Auto-selection is a convenience fallback.

**Alternatives considered**:
- **LLM-based agent selection**: Have the orchestrator's LLM choose which agent to delegate to. This is actually what already happens naturally — the orchestrator sees available agents in its context and decides who to delegate to. Auto-selection is just a simpler code-level fallback.
- **Embedding similarity**: Higher quality matching but adds dependency on embedding infrastructure. Can be added later as an enhancement.

### R6: How inter-agent messaging integrates with shared state

**Decision**: Messages are stored in state under `_messages` — a dict keyed by recipient agent ID, with a special `_broadcast` key for broadcast messages. Each message is a dict with `from`, `to`, `subject`, `body`, `requires_response`, `timestamp`, `read`. The `_summarize_state()` method is extended to inject unread messages into the agent's context. A `ReadMessagesTool` allows explicit inbox checking.

**Rationale**: Storing messages in state follows §2.3 (Explicit State, No Magic) and is consistent with how all other inter-agent data flows. Making messages available via `_summarize_state()` means agents automatically see incoming messages without needing to explicitly call a tool — reducing the chance of missed messages.

**Alternatives considered**:
- **Separate message transport (Redis, queue)**: Rejected per §2.3 — adds a side channel outside the state dict.
- **Tool-only access (no _summarize_state injection)**: Agents would only see messages if they actively call `read_messages`. This is less reliable since agents might not think to check. Hybrid approach: auto-inject in context + explicit tool for manual checking.

### R7: How to modify _summarize_state() for message injection

**Decision**: Add a new section in `Agent._summarize_state()` that checks for `_messages[self.agent_id]` and `_messages["_broadcast"]` in state. Unread messages are formatted as a "Messages" section in the agent's context, similar to how document summaries are included. After the agent processes, messages should be marked as `read` in a post-execution step.

**Rationale**: This is a minimal, targeted change to `_summarize_state()`. The method already assembles context from multiple sources (task, previous outputs, documents); adding messages is consistent and straightforward.

**Alternatives considered**:
- **Separate context builder**: Create a new method/class for message context. Rejected — over-engineering for what amounts to ~15 lines of formatting logic in an existing method.

### R8: Budget enforcement for delegated tasks

**Decision**: The existing `CostTracker` records costs per agent but does not enforce budgets. For collaboration, `CollaborationRuntime` maintains a `BudgetController` that tracks token consumption per delegation chain. Budget policies (`inherit_parent`, `fixed`, `unlimited`) are implemented as allocation strategies: `inherit_parent` passes remaining budget to the child and deducts usage; `fixed` allocates a set amount; `unlimited` disables checking. Budget exhaustion raises a `BudgetExhaustedError` that the delegation tool catches and returns as a tool result.

**Rationale**: Building on top of `CostTracker` (which already integrates with `ResilientLLMProvider`) minimizes new infrastructure. The budget controller wraps cost tracker data with enforcement logic.

**Alternatives considered**:
- **Modify CostTracker to enforce limits**: Would change existing behavior for all workflows, violating backward compatibility (§2.5).
- **Token-count-only budgets (no cost)**: Simpler but less useful — different models have vastly different costs per token. Supporting both token and cost budgets is better.

### R9: Checkpoint/resume behavior for delegations

**Decision**: In-flight delegations are stateless — they are not checkpointed. If a workflow is checkpointed during a delegation, the delegation result is lost. On resume, the orchestrator re-executes from its last checkpoint, which means it will re-invoke the delegation. This is acceptable because: (a) delegation results are typically incorporated into the orchestrator's output, which IS checkpointed after the orchestrator completes; (b) the timeout mechanism (FR-011) bounds re-execution cost.

**Rationale**: Checkpointing mid-delegation would require serializing in-flight agent state, LLM conversation history, and tool call state — significant complexity with limited benefit. Stateless delegation is simpler and consistent with the existing checkpoint model (checkpoints happen between workflow steps, not mid-step).

**Alternatives considered**:
- **Full delegation checkpointing**: Serialize delegation state. Rejected — excessive complexity for v1; can be added later if needed.
- **Delegation-aware checkpoint barriers**: Prevent checkpointing during delegation. Rejected — checkpoints are already step-boundary events; delegations happen within a step.

### R10: Collaboration configuration schema design

**Decision**: Add a `CollaborationConfig` pydantic model to `schema.py` with fields: `enabled` (bool, default False), `max_delegation_depth` (int, default 3), `max_spawned_agents` (int, default 10), `delegation_timeout_seconds` (int, default 300), `allow_recursive_orchestrators` (bool, default False), `budget_policy` (str, default "inherit_parent"). Add `collaboration: CollaborationConfig | None` as an optional field on `TeamConfiguration`. Add corresponding global defaults to `HiveFlowConfig`.

**Rationale**: Optional field on `TeamConfiguration` ensures backward compatibility — existing configs without `collaboration` work unchanged. The `CollaborationConfig` model provides pydantic validation for all settings. Team-level values override global defaults per FR-024/FR-026.

**Alternatives considered**:
- **Flat fields on TeamConfiguration**: Simpler but clutters the schema with 6+ new top-level fields. A nested config object is cleaner.
- **Separate collaboration config file**: Over-engineering — a nested object in the existing team config is sufficient.
