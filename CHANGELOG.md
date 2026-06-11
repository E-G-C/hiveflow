# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed

- **Repository restructured into a polyglot monorepo** — moved the Python implementation (the `hiveflow` package, `tests/`, `docs/`, `examples/`, `pyproject.toml`, and `uv.lock`) into a dedicated `hiveflow-py/` directory alongside the existing `hiveflow-js/` TypeScript implementation. Cross-language specs (`requirements/`, `specs/`) remain at the repository root, and a new top-level `README.md` describes the monorepo layout. Run all Python tooling from `hiveflow-py/`.

### Added

- **`hiveflow-js` demo smoke runner** — added `npm run demo:smoke` to rebuild the TypeScript workspace and execute every live demo in one pass, plus a manual GitHub Actions smoke workflow for operator-supplied live endpoints

- **LLM-generated team composition for `hiveflow-js`** — added `TeamGenerator.generateTeamFromLLM()` plus `HiveFlow.composeTeamFromLLM()` with validated JSON parsing, blocking tool-gap reporting, new-archetype surfacing, regression coverage, and a live LLM team-generation demo (`hiveflow-llmteam`)

- **TypeScript parity matrix requirements document** — added `requirements/15-typescript-parity-matrix.md` plus requirements index coverage to track Python-vs-TypeScript feature parity, example-family parity, and the rewrite to-do list

- **Dynamic collaboration runtime for `hiveflow-js` orchestrators** — added opt-in collaboration config on `TeamConfiguration`, runtime `spawn_agent` and `delegate_task` tools for orchestrator agents, collaboration event emission, regression coverage, and a live dynamic-collaboration demo (`hiveflow-yec`)

- **Archetype library and deterministic team generation for `hiveflow-js`** — added `ArchetypeLibrary` with built-in and directory-loaded archetypes, deterministic `TeamGenerator` composition into self-contained `TeamConfiguration` objects, `HiveFlow` discovery/composition helpers, regression coverage, bundled archetype templates, and a live team-generator demo (`hiveflow-z22`)

- **Team configuration and team library support for `hiveflow-js`** — added persisted `TeamConfiguration` JSON/YAML load-save support, `TeamLibrary` directory/default template loading, team-to-runtime compilation with optional model reference resolution and nested team lookup, `HiveFlow` helpers for running from team configs or team names, regression coverage, a built-in template, and a live team-config demo (`hiveflow-354`)

- **Nested `sub_workflow` pause propagation for `hiveflow-js`** — parent workflows now pause and checkpoint when nested workflows hit `human_gate` or other resumable pause points, forward nested workflow events, support parent-level resume through nested checkpoints, and include regression coverage plus a dedicated live subworkflow-pause demo (`hiveflow-774`)

- **`rollback_on_failure` for `hiveflow-js` action executors** — added reversible action metadata, rollback tool invocation on failed side effects, rollback-aware action-error payloads, regression coverage, and a live action-rollback demo (`hiveflow-3dx`)

- **`confirm_on_error` for `hiveflow-js` action executors** — added pause-on-failure execution semantics, action-error session requests and resume handling, regression coverage, and a live action-error demo (`hiveflow-dna`)

- **Definition-backed cold resume for `hiveflow-js`** — added serializable `WorkflowDefinition` and `WorkflowRuntimeCatalog` support, stored workflow definitions inside paused checkpoints, enabled `HiveFlow.loadSession()` and `resumeSession()` reconstruction without caller-supplied runtime objects, and updated the checkpoint demo plus regression coverage (`hiveflow-504`)

- **`sub_workflow` composition for `hiveflow-js`** — added inline named nested workflow execution with input/output mapping, recursive depth limits, public subworkflow registry types, and a live subworkflow demo (`hiveflow-6vf`)

- **`action_executor` behavior for `hiveflow-js`** — added audited side-effect execution with `auto`, `dry_run`, and `require_approval` policies, action-approval pause/resume handling, manual AI SDK tool planning, and a live action-executor demo (`hiveflow-qm4`)

- **Checkpoint persistence for `hiveflow-js`** — added file-backed and in-memory checkpoint storage, automatic checkpoint saves at `gated` and `human_gate` pause points, and durable `WorkflowSession`/`HiveFlow` resume support backed by persisted paused results (`hiveflow-966`)

- **Session event streaming for `hiveflow-js`** — added async `session.events()` consumers backed by workflow event hooks so TypeScript sessions can stream step, pause, and approval events across pause/resume boundaries (`hiveflow-965`)

- **`WorkflowSession` primitive for `hiveflow-js`** — added a minimal session handle with status transitions, pending-request extraction, and `run()`/`resume()` lifecycle on top of the TypeScript workflow engine (`hiveflow-964`)

- **In-memory resume for paused `hiveflow-js` workflows** — added `WorkflowEngine.resume()` and `HiveFlow.resume()` so paused `gated` and `human_gate` results can continue in memory with injected responses; checkpoint persistence is still deferred (`hiveflow-963`)

- **Paused `human_gate` handling for `hiveflow-js`** — implemented the `human_gate` agent behavior and workflow-step pause semantics so the TypeScript runtime can stop after requesting human input and surface pending-human metadata (`hiveflow-962`)

- **Paused `gated` step handling for `hiveflow-js`** — added paused workflow results with pending-gate metadata so the TypeScript runtime can stop cleanly before protected steps execute; full checkpoint/resume remains a later slice (`hiveflow-961`)

- **Parallel and conditional workflow execution for `hiveflow-js`** — expanded the TypeScript core runtime with `parallel_fan_out` aggregation, conditional revision loops with bounded iterations, and a live branching demo package for the new orchestration slice (`hiveflow-960`)

- **Live OpenAI-compatible validation for `hiveflow-js`** — added an `@ai-sdk/openai`-backed helper for OpenAI-compatible base URLs, a live smoke demo package defaulting to `claude-opus-4-6`, and unit coverage for the new adapter factory (`hiveflow-958`)

- **Experimental `hiveflow-js` workspace** — added a greenfield TypeScript workspace with `@hiveflow/core`, `@hiveflow/provider-ai-sdk`, Vitest coverage for the initial runtime slice, and a live sequential demo package for the rewrite bootstrap (`hiveflow-957`)

- **Perplexity Sonar LLM provider** — added first-class `perplexity:` model resolution, `PERPLEXITY_API_KEY` authentication, provider discovery tests, and Perplexity usage docs/example updates

- **Comprehensive SDK documentation** — 12 SDK reference docs under `docs/sdk/` covering HiveFlow, Agent, WorkflowEngine, TeamConfiguration, TeamGenerator, WorkflowSession, Streaming, Cost Tracking, Result Payload, Prompts, Output Types, and Document Pipeline
- **User guide documentation** — 10 user guides under `docs/guides/` covering Quickstart, Agents & Teams, Workflow Patterns, Document Processing, Data Processing, Output Publishing, MCP Integration, Context Management, Deep Research, Resilience, and CLI Reference
- **Documentation index** — `docs/index.md` as the landing page with links to all guides and SDK reference
- **Resilience example** — `examples/resilience/01_fallback_and_cost.py` demonstrating FallbackChain, RetryProvider, and CostTracker (no API key required)
- **Streaming example** — `examples/streaming/01_event_streaming.py` demonstrating event callbacks, StreamChannel, and JsonLinesWriter (no API key required)

- **`reasoning` and `data` output types** — `OutputType` enum now includes `REASONING` (2× summary budget) and `DATA` (0.5× budget) for differential compression
- **Declarative context management fields** — `AgentDefinition` schema accepts `context_recency_window` and `context_budget` for YAML/JSON team configs
- **`context_reducer` wiring in `TeamGenerator.build()`** — new `enable_context_reducer` and `context_reducer_overflow` parameters auto-create `ContextReducer` instances for agents with `context_budget`
- **`context_reducer` parameter in `Agent.from_definition()`** — declarative agent creation now accepts an optional `ContextReducer` instance
- **`context_ttl` wiring in `TeamGenerator.build()`** — step-level `context_ttl` from config is now passed through to `WorkflowStep` construction

### Changed

- **`hiveflow-js` examples now use live models** — replaced mock-backed example model adapters with a shared OpenAI-compatible live helper so examples exercise real model behavior while mocks remain in tests only
- **Spec 09 State Key Conventions** — replaced hardcoded `writer_outputs` with generic `{agent_id}_outputs` and `{agent_id}_summaries` patterns
- **Spec 09 Token Budget Invariants** — clarified `CHUNK_SIZE` / `BROWSE_CHUNK_MAX_LENGTH` dual naming

### Added

- **Document Input Pipeline Examples** — five comprehensive examples covering spec 009 enhancements:
  - `01_instructions_file.py` — `instructions_file` parameter on `HiveFlow.run()`, mutual exclusivity, and empty file edge case
  - `02_load_from_bytes.py` — `load_from_bytes()` on loaders, pipeline bytes loading, mixed sources, MarkItDown HTML conversion
  - `03_summary_mode.py` — LLM summary generation, caching, `scope_for_agent()` comparison, workflow with summary agents
  - `04_template_variables.py` — `$document_count`, `$document_names`, `$document_summary` resolution in agent prompts
  - `05_full_pipeline.py` — end-to-end combining all 4 enhancements with 3-agent workflow (analyst → planner → writer)

### Fixed

- **`hiveflow-js` LLM team composition now retries invalid live JSON** — `TeamGenerator.generateTeamFromLLM()` now feeds validation failures back into the model for up to three correction attempts, and the live `llm-team-generator` demo now reports a note instead of aborting the smoke suite when the endpoint still returns invalid team structure

- **`hiveflow-js` OpenAI-compatible adapter now defaults to chat mode** — `createOpenAICompatibleModelAdapter()` now chooses the AI SDK chat model by default instead of the Responses API default, adds an explicit `apiMode` override, and updates the live demo/docs so OpenAI-compatible proxies can run models like `claude-opus-4-6` without Responses API support

- **`HiveFlow.__init__` now installs global config** — `set_config()` is called so that downstream code using `get_config()` (e.g. `ResilientLLMProvider`, fallback chains, summary generation) picks up caller-supplied overrides for LLM tiers
- **`FallbackChain.from_tiers` strips provider prefix** — tier strings like `azure:gpt-4o-mini` are now reduced to `gpt-4o-mini` before being used as deployment names, fixing `DeploymentNotFound` errors on Azure
- **`TeamGenerator.build` resolves `$TIER_LLM` variables** — agent model strings like `$STRATEGIC_LLM` are now resolved via `get_config().resolve_model()` instead of being passed through verbatim
- **`DocumentPipeline.generate_summaries` resolves model from config** — when no model is specified, the method now falls back to `get_config().FAST_LLM` stripped of its provider prefix, fixing empty model errors in Azure
- **`HiveFlow.run` instructions_file path validation** — the `DocumentPipeline` for loading instruction files now sets `working_dir` to the file's parent directory, allowing instructions outside the CWD

### Added

- **Document Input Pipeline Enhancements** — four additive improvements:
  - `instructions_file` parameter on `HiveFlow.run()` — load complex workflow instructions from a text file, mutually exclusive with non-empty `task`
  - `load_from_bytes(data, filename)` on `DocumentLoaderPlugin` — load documents from in-memory byte streams with default temp-file delegation; backward compatible for all existing loaders
  - `summary` document mode (LLM-based) — agents with `document_mode="summary"` receive condensed LLM summaries instead of raw chunks; cached per-document per-run via `state["_document_summaries"]`
  - Document prompt template variables — `$document_count`, `$document_names`, `$document_summary` auto-populated from workflow state in agent system prompts

- **Configuration System Extensions** — new config fields for all categories:
  - Source Mode: `SOURCE_MODE` (web/local/hybrid/cloud/mcp/custom), `DOC_PATH`
  - Actions: `DEFAULT_ACTION_POLICY` (deny/allow/dry_run), `ENABLE_ROLLBACK`, `ACTION_TIMEOUT`
  - MCP: `MCP_STRATEGY` (disabled/fast/deep), `MCP_SERVERS`, `MCP_AUTO_TOOL_SELECTION`
  - All fields have backward-compatible defaults; env vars with `HIVEFLOW_` prefix

- **Resilience Integration** — existing resilience modules wired into production paths:
  - `ResilientLLMProvider` wraps any LLM provider with rate limiting → circuit breaker → fallback chain → cost tracking
  - `FallbackChain.from_tiers(config)` auto-builds 6-step cascade with reduced max_tokens intermediate steps
  - `parse_json_resilient()` replaces all `json.loads` calls in agent response parsing
  - `ActionQueue` for side-effect operations with semaphore-based concurrency, timeout, and rollback support
  - `CostTracker` wired into agent execution with `get_cost_tracker()` accessor

- **Prompt Template Library** — expanded with families, categories, dotted-path variables:
  - `PromptFamily` enum (default, granite, local) with `detect_family()` auto-selection
  - `PromptCategory` enum with 15 categories covering all specified prompt types
  - `resolve_dotted_path()` for nested variable resolution (e.g., `${task.description}`)
  - 16 total templates (5 existing + 11 new), all 15 categories covered

- **Streaming Protocol** — extended with metadata, new event types, audit logging:
  - 9 new `StreamEventType` values (26 total): LOG, HUMAN_REQUEST, COST, ROLLBACK, SUMMARY_GENERATED, OUTLINE_GENERATED, ASSEMBLY_COMPLETE, EXECUTOR_INVOKED, EXECUTOR_COMPLETED
  - `EventMetadata` dataclass (tokens_used, latency_ms, model, cost_usd)
  - `StreamEvent` extended with step_id, content, metadata, timestamp
  - `JsonLinesWriter` for persistent JSON-lines audit logs under OUTPUT_DIR
  - Paired EXECUTOR_INVOKED/EXECUTOR_COMPLETED events emitted in `Agent.execute()`
  - StreamChannel + JsonLinesWriter wired into WorkflowEngine

- **Recursive Exploration** — OrchestratorAgent wrapping DeepResearcher:
  - `OrchestratorAgent` with `execute(state)` and `get_progress()` for workflow integration
  - Emits stream events for progress tracking during recursive exploration

- **Output Type Routing** — map deliverable types to pipeline shapes and prompt templates:
  - `OutputTypeDefinition`, `OutputTypeId`, `OutputTypeRegistry` for 10 built-in output types (detailed_report, quick_report, outline, resource_list, deep_research, decision_record, action_plan, code_artifact, incident_report, custom)
  - `OutputOptions` for per-type parameters (max_sections, words_per_section, include_introduction, etc.)
  - `CitationsConfig` for citation behavior control (enabled, style, inline, generate_reference_section)
  - `PromptTemplateSet` for per-stage prompt templates (query generation, writing, review, action, intro/conclusion)
  - `TeamGenerator.generate_team_for_output_type()` maps pipeline shapes to agent archetypes
  - `pipeline_output_type`, `output_options`, `tone` fields on `TeamConfiguration`

- **Tone & Style System** — structured tone catalog with prompt modifier injection:
  - `ToneDefinition` model (tone_id, label, description, prompt_modifier)
  - `ToneCatalog` with 17 built-in tones (objective, formal, analytical, persuasive, informative, explanatory, descriptive, critical, comparative, speculative, reflective, narrative, humorous, optimistic, pessimistic, concise, executive)
  - `resolve_from_config()` handles string (lookup), dict (inline definition), None
  - Custom tones override built-in on ID collision
  - Warning log for unknown tone IDs

- **MCP Integration** — connect agents to external tool servers via Model Context Protocol:
  - `MCPConfig`, `MCPServerDefinition`, `MCPAuthConfig` models for `.hiveflow/mcp.json` configuration (T001-T004)
  - `MCPToolBridge` adapts MCP server tools as native `ToolPlugin` instances with dual-mapping dispatch (T011-T012, T019)
  - `MCPManager` lifecycle manager for server connections with eager/lazy modes and per-workflow scoping (T013-T018)
  - Three-tier strategy: `disabled`, `fast` (all tools), `deep` (LLM-assisted selection) (T026-T027)
  - `mcp_strategy` field on `TeamConfiguration` for per-team strategy override (T005)
  - Tool wiring in `TeamGenerator.build()` — agents receive resolved tools from the registry (T006-T007)
  - `MCPGateway` exposes HiveFlow workflows as MCP tools for external clients via FastMCP (T032-T035)
  - Enhanced checkpoint persistence — `team_config` and `task` now saved for cold-resume support (T028-T031)

- **Data Processing Infrastructure** — comprehensive plugin-based data processing layer:
  - **Retriever plugins**: TavilyRetriever and DuckDuckGoRetriever for web search, with parallel multi-retriever dispatch and URL deduplication via RetrieverRegistry.search_all()
  - **Scraper plugins**: BS4Scraper (BeautifulSoup4) and PlaywrightScraper (headless Chromium) for web content extraction, with ScraperRouter for URL-pattern-based routing and configurable per-URL timeout (default 15s, HIVEFLOW_SCRAPER_TIMEOUT)
  - **Embedding provider**: OpenAIEmbeddingProvider (text-embedding-3-small), with auto-batch splitting and cost estimation
  - **Vector store plugins**: VectorStorePlugin interface with MemoryVectorStore (numpy-accelerated cosine similarity with pure-Python fallback), CollectionManager for namespace isolation
  - **Semantic filtering pipeline**: Enhanced `relevant_chunks` document mode — chunks are embedded, filtered by cosine similarity threshold, and ranked by relevance instead of falling back to full content
  - **Source curation pipeline**: Multi-signal credibility scoring (domain authority, content relevance, freshness, LLM judgment) with configurable weights, min_score threshold, and max_sources cap
  - **Citation enhancements**: MLA and Chicago citation formats, CitationConfig model for team-level declarative configuration
  - **Document loaders**: AzureBlobLoader (azure-storage-blob async) and URLLoader (httpx-based) for cloud and web document sources
  - **Config models**: CitationConfig, SourceCurationConfig, ScoringWeights, VectorStoreConfig added to TeamConfiguration
  - **New pyproject.toml extras**: `documents-azure` (azure-storage-blob, aiohttp); `tavily-python` added to `retrieval`
  - **Entry points**: hiveflow.retrievers, hiveflow.scrapers, hiveflow.embeddings (OpenAI), hiveflow.vector_stores (memory)
  - **Public exports**: 10 new classes exported from hiveflow package

- **Examples — SDK-quality reorganization** — restructured all examples into a coherent SDK reference with six organized directories: `getting_started/` (3 mock examples), `core_architecture/` (10 mock examples), `agents_and_teams/` (9 Azure examples), `llm_providers/` (11 provider examples), `document_workflows/` (4 new examples with mock fallback), `advanced_workflows/` (4 new examples with mock fallback), and `output_pipeline/` (8 renumbered examples). Added top-level `examples/README.md` with directory layout, prerequisites, and environment variable reference.
- **Examples — sample output files** — pre-generated `sample_output/` directory with captured output from every mock-provider example, enabling reference without API keys.
- **Examples — getting_started directory** — three new introductory examples: `01_basic_workflow.py` (two-agent workflow with mock LLM), `02_team_config.py` (team config loading/validation), `03_generated_team.py` (TeamGenerator without LLM).
- **Examples — document_workflows directory** — four new document pipeline examples with mock providers: document pipeline inspection, document summarization, document Q&A with retriever tool, and multi-document report with per-agent scoping.
- **Examples — advanced_workflows directory** — four new examples: fan-out report, fan-out with generated teams, deep research, and team builder — all with mock LLM fallback.

### Fixed

- **Examples — hardcoded IP addresses** — replaced hardcoded `192.168.50.145` LAN addresses with `os.environ.get("OPENAI_BASE_URL", "http://localhost:8080/v1")` across `fan_out_report.py`, `fan_out_generated.py`, `generated_team.py`, `document_summarizer/main.py`, `document_qa/main.py`, and `console_app/main.py`.
- **Examples — Unicode encoding** — replaced all non-ASCII characters (arrows, em dashes, check marks, etc.) with ASCII-safe equivalents for Windows cp1252 terminal compatibility.
- **Examples — core_architecture/01 mock provider** — fixed `01_hiveflow_facade.py` to register MockProvider with LLMProviderRegistry so the example runs without API keys.
- **Output pipeline — numbered examples** — renumbered all `output_pipeline/` scripts with `01_`-`08_` prefixes for consistent ordering.

### Added

- **Example 09 -- context management showcase** -- end-to-end example (`09_context_management.py`) exercising all 10 context management strategies: summary propagation, differential compression, orchestrator decomposition, parallel fan-out, context budget enforcement, sliding window, context TTL expiry, redundancy detection, intelligent context reduction (ContextReducer), and code-level assembly. Includes full instrumentation metrics, an efficiency report, and publishes output as Markdown + Word (.docx).
- **Context Management — sliding window state propagation** — new `CONTEXT_RECENCY_WINDOW` config parameter (default: `0` = disabled). When set to N, only the N most recent agent summaries are included fully in downstream context; older entries are collapsed into a single-line placeholder. Prevents distant, low-value context from diluting focus in deep sequential pipelines (inspired by DeepMiner).
- **Context Management — context expiry (TTL)** — workflow steps can now declare `context_ttl` to control how many downstream steps their summary remains visible. After the TTL expires, the summary is silently dropped from context assembly. The workflow engine tracks execution order and TTL metadata in state.
- **Context Management — differential compression** — `SummaryGenerator.summarize()` now accepts an `output_type` parameter. Reasoning/structured_data outputs receive 2× the summary token budget; data/side_effect outputs receive 0.5×. The workflow engine passes each agent's `output_type` to the summarizer automatically.
- **Context Management — intelligent context reduction (ContextReducer)** — new `ContextReducer` class in `hiveflow/core/context_reducer.py` uses a cheap LLM as a reflection module to intelligently compress context by removing useless, redundant, and expired information. Invoked when context exceeds budget × overflow_threshold (default: 1.5×), with mechanical truncation as fallback.
- **Context Management — redundancy detection** — `_summarize_state()` now performs lightweight trigram-based deduplication across consecutive agent entries. Entries sharing >60% trigram overlap have the older one replaced with a back-reference, preventing duplicate information from consuming context budget.
- **Schema — `context_ttl` on WorkflowStepDefinition** — new optional field allowing workflow step TTL to be defined in team configuration JSON/YAML files.
- **Docs — context management** — added Context Management section to `docs/architecture.md` (task decomposition, summary propagation, six reduction strategies, code-level assembly), context management example to `docs/getting-started.md`, and expanded `docs/configuration.md` with agent-level and step-level context parameters.

### Added

- **Context Management — adaptive summarization threshold** — `SummaryGenerator` now accepts a `summary_threshold` parameter that sets the minimum word count before summarization activates, decoupled from `max_summary_tokens` (which controls the output budget). This prevents over-compression of short-to-medium outputs while still compressing very long ones. `TeamGenerator.build()` exposes `summary_threshold` as a keyword argument, and `HiveFlowConfig.SUMMARY_THRESHOLD` makes it configurable via environment variable (`HIVEFLOW_SUMMARY_THRESHOLD`).
- **Example 08 — output pipeline publishing** — the end-to-end LLM team example now publishes final output as Markdown and Word (.docx) with a unique UTC timestamp via the framework's `PublisherRegistry`.

### Fixed

- **SummaryGenerator — Azure provider prefix** — `SummaryGenerator` now strips the `azure:` provider prefix from model names (e.g. `azure:gpt-4o-mini` → `gpt-4o-mini`), consistent with `Agent._build_config()`. Previously, summary generation failed with `DeploymentNotFound` when using Azure OpenAI because the prefix was passed as the deployment name.

### Added

- **Workflow Engine — checkpoint accumulation** — checkpoint storage now supports multiple checkpoints per session with UUID-based `checkpoint_id`, `list_checkpoints()` for session history, and backward-compatible deserialization of old checkpoint formats (T001-T005)
- **Workflow Engine — automatic checkpointing** — `WorkflowEngine.execute()` auto-saves checkpoints at all three pause points (GATED steps, HUMAN_GATE, action_executor approval) when `checkpoint_storage` and `session_id` are provided; `HiveFlow.list_checkpoints()` exposes checkpoint history (T006-T010)
- **Workflow Engine — resume from checkpoint** — `WorkflowEngine.resume()` restores workflow state from any saved checkpoint, validates step/agent/type consistency, applies approval responses, and continues execution from the next step without re-executing completed steps (T011-T015)
- **Workflow Engine — event stream completeness** — new `OUTPUT`, `CHECKPOINT_SAVED`, and `APPROVAL` events provide full lifecycle observability; events follow guaranteed ordering (step_start → step_complete → checkpoint_saved → approval → output) (T016-T019)
- **Workflow Engine — examples** — updated `04_checkpointing.py` with accumulation/list/rewind; new `09_checkpoint_resume.py` (end-to-end pause/resume); new `10_workflow_events.py` (full event lifecycle)
- **Core Architecture — action_executor behavior type** — new agent behavior type for real-world side effects (email, deploy, publish) with safety policies: `auto` (execute immediately with audit trail) and `require_approval` (pause for human approval before executing) (hiveflow-u2n, hiveflow-rx0)
- **Core Architecture — gated workflow steps** — new `gated` step type for workflow-level pauses without agent execution, supporting external approval gates with `gate_id` and `gate_description` (hiveflow-omp, hiveflow-9y2)
- **Core Architecture — workflow checkpointing** — `WorkflowCheckpoint`, `CheckpointStorage` protocol, and `FileCheckpointStorage` for persisting/resuming paused workflows across process restarts (hiveflow-5yn)
- **Core Architecture — state schema enforcement** — configurable modes (`warn`, `strict`, `off`) for validating agent state writes against declared schemas (hiveflow-q5g, hiveflow-8rb)
- **Core Architecture — WorkflowSession** — session handle with lifecycle tracking (PENDING→RUNNING→COMPLETED/FAILED/PAUSED), pause/resume/cancel operations, event streaming, and JSON serialization (hiveflow-xzi)
- **Core Architecture — ArchetypeLibrary** — reusable agent definition library with `register/get/list/from_directory/default`, extracted from TeamGenerator for extensibility (hiveflow-e48)
- **Core Architecture — CapabilityGap + TeamGenerationResult** — structured capability gap reporting (blocking/degraded/functional_but_limited) for LLM-generated teams (hiveflow-e48)
- **Core Architecture — HiveFlow facade** — top-level entry point with `run()`/`run_sync()`/`generate_team()`/`resume()` and discovery APIs for teams, archetypes, tools, models (hiveflow-q61)
- **Core Architecture — ModelRequirements** — declarative model requirements (cost_tier, supports_tools, supports_vision, strengths) for portable agent definitions (hiveflow-u2n)
- **Core Architecture — new streaming events** — `CHECKPOINT_SAVED`, `ACTION_PROPOSED`, `ACTION_EXECUTED`, `GATE_REQUESTED` event types (hiveflow-atf)
- **Core Architecture — per-step iteration limits** — configurable `max_iterations` on conditional steps with default of 3 (hiveflow-9y2)
- **10 new public exports** — `HiveFlow`, `WorkflowSession`, `ApprovalRequest`, `WorkflowCheckpoint`, `FileCheckpointStorage`, `CheckpointStorage`, `ArchetypeLibrary`, `CapabilityGap`, `TeamGenerationResult`, `ModelRequirements` (hiveflow-j65)

### Changed

- **Conditional loop failure behavior** — exceeding `max_iterations` now raises a `WorkflowError` (FAILED status) instead of silently forcing the accept path; `max_conditional_loops` constructor parameter retained for backward compatibility (hiveflow-9y2)

### Removed

- **Chainlit frontend** — removed `hiveflow/frontend/` module, `.chainlit/` config, `chainlit.md`, `frontend/` React app, and `test_frontend.py`; frontends belong in applications built on top of HiveFlow, not in the core framework
- **Chainlit dependency** — removed `chainlit` from core `dependencies` and the `frontend` optional-dependency group in `pyproject.toml`
- **Frontend references** — stripped Chainlit/frontend mentions from requirements, README, architecture docs, and getting-started guide

### Added

- **Output Pipeline Architecture** — decoupled export system assembling workflow results into structured `ResultPayload` and dispatching to publisher plugins (T001-T047)
- **ResultPayload data model** — `ResultPayload`, `PayloadSection`, `ActionRecord` dataclasses with `to_dict()` serialization and `from_workflow_result()` assembly (T004-T005)
- **Layout template system** — YAML-based layout templates controlling document section ordering with `apply()` method, optional/required sections, and custom layout directories (T003, T006-T007, T020-T023)
- **PublishConfig** — Pydantic model for `publish` block in team config: `formats`, `layout`, `style`, `output_dir`, `filename` (T010-T011)
- **Markdown publisher** — structured Markdown output with YAML frontmatter, TOC, references, cost appendix, and layout support (T015-T016)
- **JSON publisher** — zero-dependency serialization of full `ResultPayload` to `.json` (T017-T019)
- **PDF publisher** — Markdown-to-PDF conversion via pypandoc with optional LaTeX template support (T027-T029)
- **DOCX publisher** — Markdown-to-DOCX conversion via pypandoc with optional reference document (T030-T032)
- **HTML publisher** — Markdown-to-HTML via pypandoc + Jinja2 template with responsive default styling (T033-T036)
- **Multi-format publish** — `PublisherRegistry.publish_all()` with format de-duplication, per-publisher error isolation, and structured logging (T024)
- **Auto-publish** — automatic publishing after workflow execution when `publish.formats` is configured (T025)
- **CLI publish flags** — `--publish` and `--output-dir` CLI flags for on-demand publishing (T026)
- **Completion callbacks** — `WorkflowEngine.on_complete()` for registering sync/async callbacks with per-callback error isolation (T037-T038)
- **Third-party publisher extensibility** — validated plugin discovery, invocation, and error isolation for custom publishers (T039-T040)
- **Structured log events** — `output.publish.start`, `output.publish.complete`, `output.publish.error` with publisher_id, format, output_path, duration_s (T041)
- **Publisher authoring docs** — protocol requirements, entry point registration, and testing guidance in `docs/plugins.md` (T040)

- **LLM Provider Plugin Architecture** — entry-point-based auto-discovery of LLM providers via `hiveflow.llm` group; `provider:model` resolution through `LLMProviderRegistry` (T001-T016)
- **Azure OpenAI provider** — `AzureOpenAIProvider` with dual auth: Microsoft Entra ID RBAC via `DefaultAzureCredential` (preferred) and API key fallback; requires `hiveflow[llm-azure]` extras (T011-T012)
- **SecretBackend protocol** — pluggable credential resolution via structural typing; default `EnvVarBackend` reads from env vars, swap to custom backends (Vault, SSM) with `set_secret_backend()` (T003, T009)
- **Observability module** — `configure_logging()` with structlog (ConsoleRenderer for dev, JSONRenderer for prod); optional OpenTelemetry spans and metrics (`gen_ai.client.operation.duration`, `gen_ai.client.token.usage`) gated by `HIVEFLOW_OTEL_ENABLED` (T004, T010)
- **Provider instrumentation** — OpenAI, Anthropic, and Azure providers emit structured log events (`llm.chat.complete`, `llm.chat.error`) with `provider_id`, `model`, `latency_ms`, and token counts (T006-T007, T011)
- **Enhanced model resolution errors** — `resolve_model()` suggests install commands for known extras (e.g. `uv add hiveflow[llm-azure]`) when a provider is missing (T005)
- **Azure endpoint normalization** — provider auto-strips `/openai/deployments/<name>` from endpoints when users paste the full deployment URL from the Azure portal
- **LLM provider examples** — 8 end-to-end examples under `examples/llm_providers/` covering discovery, chat, streaming, Azure RBAC, secret backends, tier variables, fallback chains, and observability
- **Document Input Pipeline** — full document loading, chunking, and token-budget management (`hiveflow.core.documents.DocumentPipeline`) (T001-T003)
- **Path security validation** — prevent path-traversal attacks on document paths (`hiveflow.validation.path_security`) (T004-T007)
- **Document model extensions** — `document_mode`, `documents` filter, `max_document_tokens` on Agent schema (T008-T012)
- **Per-agent document scoping** — agents receive only the documents they need based on their configuration (T013-T016)
- **Tokenization and chunking** — configurable chunk sizes with token estimation for LLM context management (T017-T018)
- **Document scoping validation** — schema-level validation of document scoping configuration (T019-T021)
- **Format-specific loaders** — dedicated loaders for PDF, DOCX, PPTX, XLSX, HTML, JSON, XML, Markdown, and plain text (T022-T030)
- **DocumentRetrieverTool** — ToolPlugin for on-demand document retrieval during agent execution (T031-T033)
- **Document management API** — REST endpoints for document upload, listing, and deletion (T034-T037)
- **CLI document support** — `hiveflow run --documents` flag for loading documents from the command line
- **Structured logging** — `structlog`-based logging throughout the document pipeline (T038)
- **Quickstart validation** — runtime checks that document configuration is correct before execution (T039)
- **MarkItDown universal loader** — Microsoft MarkItDown integration for PDF, DOCX, PPTX, XLSX, HTML, CSV, JSON, XML, EPUB, ZIP conversion
- **Loader fallback mechanism** — when one document loader fails, the pipeline tries the next matching loader instead of crashing
- **End-to-end examples** — `document_summarizer`, `document_qa`, `multi_doc_report` with local llama.cpp LLM
- **Standalone examples** — `document_pipeline.py` and `document_workflow.py` (no LLM required)
- **Azure RBAC requirement** — high-priority requirement for Microsoft Entra ID role-based access control in `requirements/04-plugins.md`

### Fixed

- Ruff lint violations across all new modules (T040)
- Existing `test_xml_loader_discoverable` test adapted for multi-loader discovery ordering
