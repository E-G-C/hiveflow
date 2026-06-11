# hiveflow-js

Experimental TypeScript rewrite of HiveFlow.

This workspace is intentionally greenfield. It is not API-compatible with the Python package and does not try to preserve Python configuration formats or migration paths.

## Current Scope

- `@hiveflow/core`
  - initial agent runtime
  - immutable workflow state container
  - sequential workflow execution
  - parallel fan-out execution over `parallelItems` or `taskData`
  - conditional branching with bounded revision loops
  - opt-in orchestrator collaboration with runtime `spawn_agent` and `delegate_task` tools
  - inline `sub_workflow` composition via named nested workflow registration plus input/output mapping
  - nested `sub_workflow` pause propagation with parent-level checkpoint/session resume
  - `action_executor` agents with `auto`, `dry_run`, `require_approval`, and `confirm_on_error` policies
  - per-agent `rollback_on_failure` hooks with declarative rollback tool execution
  - paused action-approval requests with same-step resume after approval
  - paused action-error escalation with resume-to-next-step after acknowledgement
  - `human_gate` steps that pause after agent execution until input is provided
  - `gated` step pausing with pending-gate metadata
  - in-memory resume for paused `human_gate`, `gated`, and `action_executor` workflows
  - `WorkflowSession` primitive for session status, pending requests, and run/resume lifecycle
  - async session event streaming via `session.events()`
  - file-backed and in-memory checkpoint persistence for paused sessions
  - serializable `WorkflowDefinition` plus `WorkflowRuntimeCatalog` reconstruction for cold resume without caller-supplied runtime objects
  - `TeamConfiguration` file persistence plus `TeamLibrary` loading for template/custom team configs compiled into the runtime catalog
  - `ArchetypeLibrary` plus deterministic `TeamGenerator` composition for self-contained team configs assembled from reusable archetypes
  - `TeamGenerator.generateTeamFromLLM()` and `HiveFlow.composeTeamFromLLM()` for validated LLM-guided team composition with capability-gap reporting
  - lightweight `HiveFlow` facade
- `@hiveflow/provider-ai-sdk`
  - Vercel AI SDK Core-backed model adapter
  - request and response normalization for text generation, tool calls, and streaming
  - manual tool-planning mode for approval-gated action execution
- shared OpenAI-compatible live example helper built on `@ai-sdk/openai`, defaulting to chat-completions mode with an explicit Responses API override
- `@hiveflow/example-sequential-demo`
  - live demo using the shared OpenAI-compatible example helper
- `@hiveflow/example-branching-demo`
  - live demo covering `parallel_fan_out` plus `conditional` revision routing
- `@hiveflow/example-action-executor-demo`
  - live demo covering `action_executor` approval, resume, and audited side effects
- `@hiveflow/example-action-error-demo`
  - live demo covering `confirm_on_error` failure escalation and acknowledgement-driven resume
- `@hiveflow/example-action-rollback-demo`
  - live demo covering `rollback_on_failure` recovery for automatic side effects
- `@hiveflow/example-subworkflow-demo`
  - live demo covering named nested workflows with input/output mapping
- `@hiveflow/example-subworkflow-pause-demo`
  - live demo covering nested `human_gate` pause propagation through a parent `sub_workflow`
- `@hiveflow/example-team-config-demo`
  - live demo covering persisted team configs loaded through `TeamLibrary` and executed through `HiveFlow.runFromTeam()`
- `@hiveflow/example-team-generator-demo`
  - live demo covering archetype discovery, deterministic team composition, and execution through `HiveFlow.composeTeam()`
- `@hiveflow/example-llm-team-generator-demo`
  - live demo covering LLM-guided team generation, JSON validation, capability-gap reporting, and new-archetype surfacing
- `@hiveflow/example-dynamic-collaboration-demo`
  - live demo covering orchestrator-driven agent spawning, targeted delegation, and collaboration event emission
- `@hiveflow/example-checkpoint-demo`
  - live demo covering definition-backed checkpoint save, reload, and cold resume in a fresh `HiveFlow` instance
- `@hiveflow/example-session-events-demo`
  - live demo covering `WorkflowSession.events()` across a paused `human_gate` and resume
- `@hiveflow/example-live-openai-compatible-demo`
  - minimal provider-focused live demo for an OpenAI-compatible endpoint using `claude-opus-4-6` by default in chat mode, with an env override for Responses API

## Commands

```bash
cd hiveflow-js
npm install
npm run build
npm run test
npm run demo:sequential
npm run demo:branching
npm run demo:action-executor
npm run demo:action-error
npm run demo:action-rollback
npm run demo:subworkflow
npm run demo:subworkflow-pause
npm run demo:team-config
npm run demo:team-generator
npm run demo:llm-team-generator
npm run demo:dynamic-collaboration
npm run demo:checkpoint
npm run demo:session-events
npm run demo:smoke
npm run demo:live-openai
```

`npm run demo:smoke` rebuilds the workspace packages and runs every TypeScript demo against the configured live endpoint, including `demo:live-openai`.

## Workspace Layout

```text
hiveflow-js/
  packages/
    core/
    provider-ai-sdk/
  examples/
    action-error-demo/
    action-rollback-demo/
    action-executor-demo/
    branching-demo/
    checkpoint-demo/
    sequential-demo/
    subworkflow-demo/
    subworkflow-pause-demo/
    team-config-demo/
    team-generator-demo/
    llm-team-generator-demo/
    dynamic-collaboration-demo/
    session-events-demo/
    live-openai-compatible-demo/
```

## Live Example Configuration

All TypeScript examples read these environment variables:

- `HIVEFLOW_LIVE_OPENAI_BASE_URL`
  - default: `http://192.168.50.187:4000/v1`
- `HIVEFLOW_LIVE_OPENAI_MODEL`
  - optional; default: `claude-opus-4-6`
- `HIVEFLOW_LIVE_OPENAI_API_KEY`
  - optional; defaults to `not-needed`
- `HIVEFLOW_LIVE_OPENAI_API_MODE`
  - optional; defaults to `chat`; set to `responses` only when the endpoint and model pair support OpenAI Responses API

Example:

```bash
cd hiveflow-js
HIVEFLOW_LIVE_OPENAI_BASE_URL=http://192.168.50.187:4000/v1 npm run demo:live-openai
```

Many OpenAI-compatible proxies expose `/chat/completions` but do not implement `/responses` for non-OpenAI models. The compatibility helper now defaults to `chat` for that reason.

If the endpoint cannot be reached from the current environment, the demos exit with a clear connectivity error that includes the configured model id.

The GitHub Actions smoke workflow is now a manual `workflow_dispatch` job. Supply a live endpoint that is reachable from the runner before starting it.

## Design Notes

- `WorkflowDefinition` is a serializable runtime description for steps, agents, and nested sub-workflows.
- `WorkflowRuntimeCatalog` maps serializable model definitions and tool ids back to live adapters and tool implementations.
- `TeamConfiguration` is the user-facing persisted team format; it validates agent/workflow structure, supports JSON/YAML save/load, and compiles into `WorkflowDefinition` objects with optional `TeamLibrary` and string-model resolution.
- `ArchetypeLibrary` stores reusable agent definitions, and `TeamGenerator` deterministically expands those archetypes into self-contained `TeamConfiguration` objects.
- `TeamGenerator.generateTeamFromLLM()` and `HiveFlow.composeTeamFromLLM()` accept model output as JSON or structured objects, retry invalid team JSON with validation feedback, report blocking tool gaps, and surface proposed new archetypes for manual review before execution.
- `TeamConfiguration.collaboration` enables execution-scoped orchestration controls such as delegation depth, spawn limits, timeouts, and recursive-orchestrator policy.
- `HiveFlow.runSessionFromDefinition()` stores the definition inside paused checkpoints so `loadSession({ sessionId })` and `resumeSession({ sessionId, responses })` can rebuild runtime in a fresh process.
- `HiveFlow.createSessionFromTeam()`, `runSessionFromTeam()`, and `runFromTeam()` reuse the same runtime-catalog execution path as definition-backed sessions.
- `HiveFlow.teamLibrary()`, `archetypeLibrary()`, and `composeTeam()` expose the discovery and deterministic-composition layer above the runtime catalog.
- When collaboration is enabled for an `orchestrator`, `WorkflowRuntimeCatalog` injects `spawn_agent` and `delegate_task` tools and the workflow emits `agent_spawned`, `delegation_started`, `delegation_completed`, and `delegation_failed` events.
- The current Python implementation under `hiveflow/` is the implementation reference.
- The documents under `requirements/` are the functional reference.
- Example programs are demonstrations only and do not drive architecture decisions.
- `sub_workflow` steps now resolve named nested workflows registered on the parent `WorkflowEngine`, apply optional input/output mappings, forward nested workflow events, and pause the parent workflow when the nested workflow pauses so checkpoint/session resume can continue through the parent runtime.
- `action_executor` agents now plan tools in manual mode, pause with `action_proposed` metadata under `require_approval`, pause with `action_error` metadata under `confirm_on_error`, and resume either by re-entering the same step after approval or continuing after explicit error acknowledgement.
- When `rollbackOnFailure` and `rollbackAction` are configured on an `action_executor`, failed tool executions now invoke the declared rollback tool immediately and record the rollback outcome in workflow state.
- `human_gate` steps now return a paused workflow result with pending human-input metadata when the agent requests input.
- `gated` steps now return a paused workflow result before agent execution.
- Paused `gated`, `human_gate`, and `action_executor` workflows can now be resumed from checkpoint storage either with manually reconstructed runtime objects or from stored `WorkflowDefinition` metadata via `WorkflowRuntimeCatalog`.