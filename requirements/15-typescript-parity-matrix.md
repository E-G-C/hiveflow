[< Back to Index](README.md)

---

# 15 - Python / TypeScript Parity Matrix

> **Version:** 1.0 **Date:** 2026-03-23 **Status:** Working backlog
> **Dependencies:** [01-core-architecture](01-core-architecture.md),
> [03-agents-and-teams](03-agents-and-teams.md),
> [05-data-processing](05-data-processing.md),
> [06-integrations](06-integrations.md),
> [08-output-pipeline](08-output-pipeline.md),
> [09-context-management](09-context-management.md),
> [10-configuration-and-operations](10-configuration-and-operations.md),
> [12-document-input](12-document-input.md),
> [13-dynamic-agent-collaboration](13-dynamic-agent-collaboration.md),
> [14-task-preprocessing](14-task-preprocessing.md)

---

## Objective

Track parity between the Python reference implementation and the TypeScript
rewrite as a **working migration backlog**.

This document is intentionally operational rather than aspirational. Each row
should answer three questions clearly:

1. What exists today in Python?
2. What already exists in TypeScript?
3. What is the next concrete slice of work?

This is **not** an API-compatibility plan. The TypeScript rewrite remains
greenfield. The purpose of this matrix is to track **capability parity**,
**example parity**, and the **remaining to-do list** for the rewrite.

---

## Status Legend

| Status       | Meaning                                                                                                                                   |
| ------------ | ----------------------------------------------------------------------------------------------------------------------------------------- |
| **Done**     | TypeScript has working runtime support for the slice, regression coverage, docs, and at least one runnable demo or clear usage path       |
| **Partial**  | TypeScript has meaningful support, but Python remains broader or the TypeScript surface still lacks demos, docs, or adjacent capabilities |
| **Todo**     | No meaningful TypeScript implementation yet                                                                                               |
| **Deferred** | Known gap, but not a one-to-one parity target or not worth porting yet                                                                    |

---

## Tracking Rules

| Rule                          | Description                                                                                                        |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| Python is the reference       | The implementation under `hiveflow-py/hiveflow/` and the Python examples under `hiveflow-py/examples/` define the current feature baseline |
| Done means shippable          | A row only moves to **Done** when implementation, tests, docs, and a runnable TypeScript demo all exist            |
| Example parity matters        | A runtime feature is not truly landed if there is no demo showing how it is supposed to be used                    |
| Slice work narrowly           | Prefer landing one matrix row or one tightly related cluster of rows per issue                                     |
| Update this file continuously | When TypeScript work lands, update both the status and the next-slice text in this matrix                          |

---

## Current Baseline

| Surface              | Python                                                                                                     | TypeScript                                                                                         |
| -------------------- | ---------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| Role in repo         | Full implementation reference                                                                              | Experimental greenfield rewrite                                                                    |
| Example breadth      | Broad example catalog across workflow, providers, documents, data, publishing, MCP, skills, and operations | Focused runtime demos for the current orchestration slice                                          |
| Integration depth    | Provider plugins, MCP, document loaders, embeddings, output publishers, resilience, observability, skills  | AI SDK adapter, OpenAI-compatible helper, runtime catalog, team config, checkpoints, collaboration |
| Current parity state | Source of truth                                                                                            | Strong on workflow runtime semantics, early on ecosystem features                                  |

---

## Feature Parity Matrix

| ID  | Area                                                                | Python baseline                                                                                       | TypeScript today                                                                                             | Status      | Priority | Next slice                                                                                                 |
| --- | ------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ | ----------- | -------- | ---------------------------------------------------------------------------------------------------------- |
| F01 | Core agent runtime and workflow state                               | Universal `Agent`, shared state, `WorkflowEngine`, `HiveFlow` facade                                  | `Agent`, `WorkflowState`, `WorkflowEngine`, `HiveFlow` are implemented and tested                            | **Done**    | P0       | Maintain parity as new Python runtime behaviors land                                                       |
| F02 | Sequential, parallel fan-out, conditional loops                     | Core workflow patterns from specs 01-03 and `hiveflow-py/examples/core_architecture`, `hiveflow-py/examples/agents_and_teams` | Sequential and branching demos exist; runtime covers parallel fan-out and bounded conditional revision loops | **Done**    | P0       | Keep semantics aligned with Python loop behavior                                                           |
| F03 | Human-in-the-loop pauses (`human_gate`, `gated`)                    | Pause points, approvals, resumable workflows                                                          | `human_gate` and `gated` pauses are implemented with resume support and checkpoint integration               | **Done**    | P0       | Add a dedicated `gated` demo if that becomes a user-facing slice                                           |
| F04 | Action executor core (`auto`, `dry_run`, `require_approval`)        | Action-oriented agents plus queueing and policy support                                               | `action_executor` supports `auto`, `dry_run`, and `require_approval`; approval and auto paths are demoed     | **Partial** | P1       | Add explicit `dry_run` demo coverage and decide whether TypeScript needs Python-style `ActionQueue` parity |
| F05 | Action error acknowledgement (`confirm_on_error`)                   | Error-aware action flows in core architecture and operations                                          | Implemented, tested, documented, and demoed                                                                  | **Done**    | P1       | Maintain only                                                                                              |
| F06 | Rollback on failure                                                 | Automatic rollback support for failed side effects                                                    | Implemented, tested, documented, and demoed                                                                  | **Done**    | P1       | Maintain only                                                                                              |
| F07 | `WorkflowSession` lifecycle and pending requests                    | Session status, pause/resume/cancel, request inspection                                               | Implemented with session lifecycle, pending requests, and session-backed demos                               | **Done**    | P0       | Maintain only                                                                                              |
| F08 | Workflow and session event streaming                                | Rich event surface, callbacks, `StreamChannel`, JSONL writer, audit events                            | `session.events()` exists and spans pause/resume, but event taxonomy is narrower than Python                 | **Partial** | P1       | Expand event types, callback helpers, and audit/logging story                                              |
| F09 | Checkpoint persistence and cold resume                              | Durable checkpointing, list/history, restore, rewind                                                  | File and memory checkpoint storage, cold session load, and fresh-process resume are implemented              | **Done**    | P0       | Add checkpoint history and rewind only if needed                                                           |
| F10 | `sub_workflow` composition                                          | Nested workflows, reusable teams, mapped I/O                                                          | Implemented with named nested workflows and input/output mapping                                             | **Done**    | P0       | Maintain only                                                                                              |
| F11 | Nested sub-workflow pause propagation                               | Parent pause/resume through nested workflow checkpoints                                               | Implemented, tested, and demoed                                                                              | **Done**    | P0       | Maintain only                                                                                              |
| F12 | `TeamConfiguration` and `TeamLibrary`                               | Persisted team configs, load/save, reusable team definitions                                          | JSON/YAML persistence and team-library loading are implemented and demoed                                    | **Done**    | P0       | Maintain only                                                                                              |
| F13 | `ArchetypeLibrary` and deterministic `TeamGenerator`                | Archetype reuse and deterministic team composition                                                    | Implemented with templates, library loading, and team-generator demo                                         | **Done**    | P0       | Maintain only                                                                                              |
| F14 | Runtime collaboration: delegation and spawning                      | Dynamic delegation and agent spawning from spec 13                                                    | Runtime `spawn_agent` and `delegate_task` are implemented with collaboration events and demo coverage        | **Partial** | P1       | Add the remaining spec-13 collaboration features instead of expanding only spawn/delegate                  |
| F15 | Inter-agent messaging                                               | Targeted messages and request-response between agents                                                 | No TypeScript support yet                                                                                    | **Todo**    | P1       | Add a message bus or equivalent state convention plus a focused demo                                       |
| F16 | Collaborative task planning                                         | Runtime decomposition into planned sub-tasks with dependency awareness                                | No TypeScript support yet                                                                                    | **Todo**    | P1       | Add planning artifact schema and orchestrator-driven planning demo                                         |
| F17 | LLM-generated teams and capability-gap reporting                    | Python can generate teams from prompts and report capability gaps                                     | `TeamGenerator.generateTeamFromLLM()` and `HiveFlow.composeTeamFromLLM()` validate model output, report blocking tool gaps, and surface new archetypes | **Done**    | P1       | Maintain only                                                                                              |
| F18 | Context management and context reducer                              | Summary propagation, budgets, TTL, reducer, redundancy controls                                       | No TypeScript support yet                                                                                    | **Todo**    | P1       | Port summary propagation and budget enforcement before advanced reducers                                   |
| F19 | Task preprocessing and large-input handling                         | Spec 14 preprocessing for large tasks and task/data separation                                        | No TypeScript support yet                                                                                    | **Todo**    | P1       | Port preprocessing thresholds, task splitting, and manifest generation                                     |
| F20 | Provider abstraction, discovery, tier variables, model requirements | Provider registry, secret backends, tier variables, discovery, model metadata                         | Runtime model factories and AI SDK adapter exist, but no provider-registry parity                            | **Partial** | P1       | Add provider registry, tier resolution, discovery APIs, and model metadata                                 |
| F21 | OpenAI-compatible live validation                                   | Python examples can target OpenAI-compatible endpoints                                                | A shared live OpenAI-compatible helper now powers every TypeScript demo, and the dedicated connectivity demo has been validated | **Done**    | P0       | Add model preflight against `/v1/models` to improve operator feedback                                      |
| F22 | MCP integration and gateway                                         | Config, bridge, manager, deep mode, gateway, cold resume, live agent                                  | No TypeScript support yet                                                                                    | **Todo**    | P1       | Port MCP config and tool bridge first, then manager and gateway                                            |
| F23 | Document input pipeline and document workflows                      | Document loaders, scoping, summary mode, document workflows                                           | No TypeScript support yet                                                                                    | **Todo**    | P1       | Port document loaders and scoping before document workflows                                                |
| F24 | Data processing, embeddings, vector stores, citations               | Retrievers, scrapers, embeddings, semantic filtering, citations, research pipeline                    | No TypeScript support yet                                                                                    | **Todo**    | P2       | Port retrieval primitives after the document pipeline exists                                               |
| F25 | Output pipeline and publishers                                      | `ResultPayload`, layout templates, Markdown/JSON/HTML/PDF/DOCX publishing                             | No TypeScript support yet                                                                                    | **Todo**    | P2       | Port payload model and Markdown/JSON publishers first                                                      |
| F26 | Resilience, cost tracking, observability                            | Fallback chains, retries, cost accounting, structlog, OpenTelemetry                                   | No TypeScript support yet                                                                                    | **Todo**    | P2       | Port fallback/cost first, observability second                                                             |
| F27 | Skills registry and skill-activated workflows                       | Skills, prompt injection, activation tools, skill-driven examples                                     | No TypeScript support yet                                                                                    | **Todo**    | P2       | Port skill registry plus one skill-activation demo                                                         |
| F28 | Entry points: CLI, API, console app                                 | Python package entry points, FastAPI surface, interactive console app                                 | No TypeScript equivalent yet                                                                                 | **Todo**    | P3       | Decide whether parity requires full CLI/API/app coverage or a narrower TS surface                          |
| F29 | Demo smoke harness and example CI coverage                          | Python has a broad example catalog and reference outputs                                              | TypeScript has 14 live demos, a live-endpoint `demo:smoke` runner, and a manual GitHub Actions smoke workflow for operator-supplied endpoints | **Done**    | P2       | Maintain runner docs and endpoint prerequisites                                                             |

---

## Example Parity Matrix

| ID  | Python example family                | Python scope                                                                                                                                                              | Current TypeScript demos                                                                                                                                                      | Status       | Priority | Next slice                                                                                            |
| --- | ------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------ | -------- | ----------------------------------------------------------------------------------------------------- |
| E01 | `getting_started/`                   | Basic workflow, team config, generated team                                                                                                                               | `sequential-demo`, `team-config-demo`, `team-generator-demo`                                                                                                                  | **Done**     | P0       | Keep docs aligned with the current demo entry points                                                  |
| E02 | `core_architecture/`                 | Facade, action executor, gated workflow, checkpoints, sessions, model requirements, discovery APIs, state schema, workflow events                                         | `action-executor-demo`, `action-error-demo`, `action-rollback-demo`, `checkpoint-demo`, `session-events-demo`, `subworkflow-demo`, `subworkflow-pause-demo`, `branching-demo` | **Partial**  | P0       | Add dedicated demos for gated steps, model requirements, discovery APIs, and state-schema enforcement |
| E03 | `agents_and_teams/`                  | Team config, failure policies, archetypes, action policies, conditional workflows, fan-out, LLM team generation, delegation, spawn, collaborative planning, preprocessing | `team-config-demo`, `team-generator-demo`, `llm-team-generator-demo`, `dynamic-collaboration-demo`, `branching-demo`                                                          | **Partial**  | P1       | Add failure-policy and collaborative-planning demos                                                      |
| E04 | `llm_providers/`                     | Discovery, chat, streaming, Azure RBAC, secret backends, tiers, fallback, observability, multi-turn, function calling, JSON mode                                          | All current demos now run through the shared OpenAI-compatible live helper, with `live-openai-compatible-demo` as the provider-focused entry point                          | **Partial**  | P1       | Add discovery, streaming, multi-turn, function-calling, and structured-output demos                   |
| E05 | `document_workflows/`                | Document pipeline, summarizer, Q&A, multi-doc report, full workflow                                                                                                       | No TypeScript equivalent                                                                                                                                                      | **Todo**     | P1       | Port after document primitives land                                                                   |
| E06 | `data_processing/`                   | Retrievers, scraping, embeddings, semantic filtering, source curation, citations, research workflow                                                                       | No TypeScript equivalent                                                                                                                                                      | **Todo**     | P2       | Port after providers and documents                                                                    |
| E07 | `advanced_workflows/`                | Fan-out report, generated fan-out, deep research, team builder                                                                                                            | `branching-demo`, `team-generator-demo`, `dynamic-collaboration-demo` partially overlap                                                                                       | **Partial**  | P1       | Add deep-research and builder-style demos                                                             |
| E08 | `output_pipeline/`                   | Result publishing, layouts, auto-publish, callbacks, PDF/DOCX/HTML                                                                                                        | No TypeScript equivalent                                                                                                                                                      | **Todo**     | P2       | Add Markdown/JSON publish demo first                                                                  |
| E09 | `console_app/`                       | Interactive end-to-end console app                                                                                                                                        | No TypeScript equivalent                                                                                                                                                      | **Todo**     | P3       | Decide whether to port as console app, CLI, or web entry point                                        |
| E10 | `resilience/`                        | Fallback and cost example                                                                                                                                                 | No TypeScript equivalent                                                                                                                                                      | **Todo**     | P2       | Add one resilience smoke demo after fallback support exists                                           |
| E11 | `streaming/`                         | Event callbacks, stream channels, JSONL writer                                                                                                                            | `session-events-demo`                                                                                                                                                         | **Partial**  | P2       | Add richer callback and persistent-event demos                                                        |
| E12 | `config_operations/`                 | Resilient provider, config layering, prompt templates, streaming events, action queue, instructions-file examples                                                         | No TypeScript equivalent                                                                                                                                                      | **Todo**     | P2       | Port only after provider, prompt, and action-ops layers exist                                         |
| E13 | `document_input_pipeline/`           | Instructions files, load from bytes, summary mode, template variables, full pipeline                                                                                      | No TypeScript equivalent                                                                                                                                                      | **Todo**     | P1       | Add once document pipeline exists                                                                     |
| E14 | `embeddings/`                        | Local embeddings, HuggingFace, provider comparison                                                                                                                        | No TypeScript equivalent                                                                                                                                                      | **Todo**     | P2       | Add after vector-store layer exists                                                                   |
| E15 | `mcp_integration/`                   | MCP configuration, tool bridge, manager lifecycle, gateway, cold resume, live MCP agent                                                                                   | No TypeScript equivalent                                                                                                                                                      | **Todo**     | P1       | Port config and bridge first, then lifecycle and gateway demos                                        |
| E16 | `skills/`                            | Skill registry, skill activation, live code review, live research pipeline, extraction                                                                                    | No TypeScript equivalent                                                                                                                                                      | **Todo**     | P2       | Add after skills registry exists                                                                      |
| E17 | Top-level standalone Python examples | Thin entry points like `basic_workflow.py`, `fan_out_report.py`, `generated_team.py`, `document_workflow.py`                                                              | No direct TypeScript equivalents                                                                                                                                              | **Deferred** | P3       | Prefer category-owned demos over duplicating all top-level wrappers                                   |

---

## Suggested Implementation Order

| Slice | Matrix rows                  | Why this order                                                                             | Exit criteria                                                                    |
| ----- | ---------------------------- | ------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------- |
| S1    | F20, E04                     | The provider layer is the foundation for most higher-level parity work                     | Provider registry, tier variables, discovery APIs, and at least 3 provider demos |
| S2    | F18, F19, E12, E13           | Context and preprocessing affect nearly every multi-agent and document workflow            | Summary propagation, budget rules, preprocessing thresholds, and 2 focused demos |
| S3    | F23, E05                     | Documents are a prerequisite for the Python document workflow families                     | Loaders, document scoping, summary mode, and 2 document demos                    |
| S4    | F24, E06, E14                | Retrieval and embeddings depend on providers and documents                                 | Retriever/embedding/vector primitives plus at least 2 data-processing demos      |
| S5    | F25, E08                     | Publishing is a self-contained capability with clear user value                            | `ResultPayload`, Markdown/JSON publishing, and 1 publish demo                    |
| S6    | F22, E15                     | MCP is a major integration surface but easier once core runtime and providers are stable   | MCP config, bridge, manager, and at least 1 live or simulated demo               |
| S7    | F15, F16, F17, E03, E07      | Advanced collaboration becomes more useful after providers and context controls exist      | Messaging, planning, LLM-generated teams, and 2 collaboration demos              |
| S8    | F26, F27, F28, E09, E10, E16 | Remaining ecosystem and operator features can land after the core platform is broad enough | Fallback/cost, skills, and at least one entry-point decision with demo coverage  |

---

## Definition Of Done For Each Row

| Requirement    | Definition                                                                |
| -------------- | ------------------------------------------------------------------------- |
| Implementation | Runtime support exists in `hiveflow-js/packages/` and is not demo-only    |
| Tests          | Regression coverage exists for the new slice                              |
| Demo           | At least one runnable example demonstrates the capability end to end      |
| Docs           | `hiveflow-js/README.md`, root docs, and this parity matrix are updated    |
| Tracking       | Status and next-slice text in this file are updated as part of the change |

---

## Notes

| Topic               | Guidance                                                                                           |
| ------------------- | -------------------------------------------------------------------------------------------------- |
| API compatibility   | Do not force one-to-one API compatibility with Python; track capability parity instead             |
| Example duplication | Prefer one clear TypeScript demo per capability family over recreating every Python wrapper script |
| Prioritization      | Land platform foundations before high-surface integration families                                 |
| Maintenance         | When Python gains a new family or materially expands an existing one, add or revise rows here      |
