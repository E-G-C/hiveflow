# Research: Core Architecture

**Feature**: 001-core-architecture
**Date**: 2026-02-22
**Status**: Complete

## Research Tasks

### R1: action_executor Behavior Type — Execution Pattern

**Decision**: The `action_executor` behavior type reuses the existing `tool_user` execution loop (LLM decides which tools to call, iterates until done) but adds a safety policy gate. When `action_policy=require_approval`, the agent pauses after the LLM proposes tool calls but before executing them — surfacing the proposed actions as approval requests. When `action_policy=auto`, behavior is identical to `tool_user` except that each tool execution is recorded as a structured `ActionRecord` in the workflow state.

**Rationale**: Reusing the tool calling loop avoids duplicating LLM interaction logic. The only difference from `tool_user` is the pause-before-execute gate and the mandatory audit trail. This is consistent with the existing `_execute_tool_user()` and `_execute_human_gate()` patterns.

**Alternatives considered**:
- Separate action execution engine (rejected: over-engineering for Phase 1; actions are just tool calls with safety policies)
- Decorator pattern on tool_user (rejected: conflates two distinct behavior semantics; configuration should be explicit per constitution 2.3)

### R2: Gated Step Type — Workflow Engine Integration

**Decision**: `GATED` is a new StepType that pauses the entire workflow (not just one agent) for external approval. Unlike `HUMAN_GATE` (which is an agent behavior that pauses when the agent reaches a decision point), `GATED` is a workflow-level pause that occurs before a step begins. The gate has a `gate_id` for identification and `gate_description` for context. The workflow emits a `gate_requested` event and transitions to `PAUSED` status until `session.resume()` is called.

**Rationale**: The requirements distinguish between agent-level human gates (intrinsic to the agent's behavior) and workflow-level gates (structural pauses in the graph). This separation keeps agent behavior pure and moves orchestration concerns to the workflow engine.

**Alternatives considered**:
- Reusing HUMAN_GATE for both (rejected: conflates agent behavior with workflow structure; a gate step doesn't need an agent at all)
- Gate as a modifier on any step type (rejected: increases combinatorial complexity; a dedicated step type is simpler)

### R3: Conditional Loop Failure Behavior

**Decision**: Change the existing behavior from "force accept path on exceed" to "raise WorkflowError on exceed". The `max_iterations` field moves from a global `max_conditional_loops` on WorkflowEngine to a per-step `max_iterations` field on `WorkflowStepDefinition` (when type=conditional). Default: 3. The WorkflowEngine still maintains a global fallback via constructor parameter for backward compatibility.

**Rationale**: Per the clarification session, exceeding the iteration limit is an error condition, not a soft fallback. Developers should know when their workflow is stuck rather than silently accepting a potentially bad result. Per-step configuration allows different thresholds for different evaluators.

**Alternatives considered**:
- Keep existing force-accept behavior (rejected: per clarification, user chose explicit failure)
- Remove global parameter entirely (rejected: breaks backward compatibility per constitution 2.5)

### R4: Workflow Checkpointing — Storage Pattern

**Decision**: Implement `WorkflowCheckpoint` as a frozen dataclass containing the serialized workflow state, plus `FileCheckpointStorage` using JSON files. Checkpoints are saved automatically when the workflow transitions to `PAUSED` status (human gates and gated steps). The checkpoint includes: session_id, workflow_step_index, accumulated state dict, pending approval requests, iteration counters, and timestamp. Resume loads the checkpoint and restarts the workflow engine from the saved step.

**Rationale**: File-based JSON storage is the simplest durable option that works cross-platform without additional dependencies. It aligns with the constitution's progressive disclosure principle — advanced users can implement custom storage in a future phase via a `CheckpointStorage` protocol.

**Alternatives considered**:
- SQLite storage (rejected: adds dependency for Phase 1; file-based is sufficient)
- In-memory only (rejected: defeats the purpose of cross-process resume)
- Full pluggable storage from day one (rejected: YAGNI for Phase 1; protocol defined but only file backend implemented)

### R5: HiveFlow + WorkflowSession — API Design Pattern

**Decision**: `HiveFlow` is a facade class in `hiveflow/core/hiveflow.py` that composes `TeamTemplateLibrary`, `ArchetypeLibrary`, `ToolRegistry`, `LLMProviderRegistry`, and `HiveFlowConfig`. It provides `run()` (async), `run_sync()` (sync wrapper), `generate_team()`, and discovery methods. `WorkflowSession` is a handle class in `hiveflow/core/session.py` that wraps a running workflow with session_id (UUID), status, result, pending_requests, events (StreamChannel), resume(), and cancel().

**Rationale**: The facade pattern keeps the public API surface small while delegating to existing subsystems. `WorkflowSession` is a thin wrapper over `WorkflowEngine` execution, adding session identity, event streaming, and checkpoint integration. Sync wrappers use `asyncio.run()` or `asyncio.get_event_loop().run_until_complete()` per the constitution's async-first principle (2.6).

**Alternatives considered**:
- Making WorkflowEngine the public API directly (rejected: engine is an execution primitive, not a consumer-facing API; session adds identity, events, and lifecycle)
- Separate sync and async classes (rejected: sync wraps async per constitution 5.4)

### R6: ArchetypeLibrary — Extraction from TeamGenerator

**Decision**: Extract the static `ARCHETYPES` dict from `TeamGenerator` into a new `ArchetypeLibrary` class with the same patterns as `TeamTemplateLibrary`: `register()`, `get()`, `list_archetypes()`, `from_directory()`, `default()`. Individual archetype definitions stored as JSON files in `hiveflow/templates/archetypes/`. `TeamGenerator` takes an `ArchetypeLibrary` as a constructor dependency instead of using its static dict.

**Rationale**: Follows the same pattern as `TeamTemplateLibrary` for consistency. Moving archetypes to files makes them discoverable and user-extensible (users can add custom archetypes by file). This aligns with the constitution's plugin architecture principle (2.4).

**Alternatives considered**:
- Keep archetypes as a dict in TeamGenerator (rejected: not user-extensible, not consistent with team template patterns)
- Merge into TeamTemplateLibrary (rejected: archetypes and teams are different concepts; archetypes are building blocks, teams are complete configs)

### R7: LLM Team Generation — Capability Gap Reporting

**Decision**: `TeamGenerator.generate_team_from_llm()` sends the task description plus available archetypes and tools to the LLM, which returns a JSON team configuration. The generator then validates the config against the schema and checks tool availability. Missing tools are reported as `CapabilityGap` objects with severity: `blocking` (team cannot function), `degraded` (quality reduced), `functional_but_limited` (minor capability loss). The result is wrapped in `TeamGenerationResult(config, gaps, new_archetypes)`.

**Rationale**: The LLM generates the config; the framework validates it. This keeps the LLM out of the validation loop and makes gap reporting deterministic. Severity levels let the caller decide whether to proceed.

**Alternatives considered**:
- LLM validates its own output (rejected: non-deterministic validation is unreliable)
- No gap reporting (rejected: per FR-016, capability gaps must be reported with severity)

### R8: State Schema Enforcement — Runtime Behavior

**Decision**: `WorkflowEngine` accepts an optional `StateSchema` from the `TeamConfiguration`. Enforcement mode is a field on `StateSchema` with values: `warn` (default), `strict`, `off`. In `warn` mode, undeclared state writes produce structlog warnings. In `strict` mode, agent state output is filtered to only declared write keys. In `off` mode, no enforcement. Enforcement runs after each agent execution, before state merge.

**Rationale**: State enforcement is a validation concern that belongs in the workflow engine execution loop, not in individual agents. The three modes give developers progressive control. `warn` is the safe default that catches issues without breaking execution.

**Alternatives considered**:
- Enforcement in Agent.execute() (rejected: agents shouldn't know about schema; that's orchestration logic)
- Only strict mode (rejected: too disruptive for existing workflows without schema)

### R9: Model Requirements Resolution

**Decision**: `AgentDefinition.model_requirements` is an optional dict with keys like `strengths` (list[str]), `cost_tier` (str: fast/smart/strategic), `supports_tools` (bool), `supports_vision` (bool). Resolution occurs at team build time in `TeamGenerator.build()` or `HiveFlow.run()`: if `model` is not set but `model_requirements` are, the framework resolves to a concrete model using `HiveFlowConfig` tier mapping and `LLMProviderRegistry` capabilities. If both `model` and `model_requirements` are set, `model` wins.

**Rationale**: Declarative requirements decouple agent definitions from specific model names, improving portability (SC-003). Resolution at build time means the resolved model is known before execution starts, avoiding runtime surprises.

**Alternatives considered**:
- Runtime resolution per call (rejected: non-deterministic model switching mid-workflow is confusing)
- Remove model_requirements entirely (rejected: per FR-013, declarative requirements are explicitly required)
