# HiveFlow Examples

End-to-end examples demonstrating every major feature of the HiveFlow
multi-agent framework — from basic workflows to advanced context management,
document processing, LLM provider plugins, and output publishing.

## Quick Start

```bash
# Install HiveFlow (from the hiveflow-py/ directory)
uv sync

# Run any example
uv run python examples/getting_started/basic_workflow.py
```

Most **core_architecture** and **llm_providers** examples include mock providers
and run without API keys. Examples that call a live LLM are marked in each
directory's README.

## Directory Layout

```
examples/
├── README.md                     ← you are here
│
├── getting_started/              ← First examples to try
│   ├── 01_basic_workflow.py      — Two-agent sequential workflow
│   ├── 02_team_config.py         — Load and validate team configuration
│   └── 03_generated_team.py      — Dynamic team generation from description
│
├── core_architecture/            ← Framework internals (mock LLM, no API key)
│   ├── 01_hiveflow_facade.py     — HiveFlow entry point and run_sync()
│   ├── 02_action_executor.py     — Action executor with safety policies
│   ├── 03_gated_workflow.py      — Gated steps for human-in-the-loop
│   ├── 04_checkpointing.py       — Durable checkpoint save/load/rewind
│   ├── 05_session_lifecycle.py   — WorkflowSession status and serialization
│   ├── 06_model_requirements.py  — Declarative model selection and tiers
│   ├── 07_discovery_apis.py      — Enumerate teams, archetypes, tools, models
│   ├── 08_state_schema.py        — State schema enforcement modes
│   ├── 09_checkpoint_resume.py   — End-to-end checkpoint/resume cycle
│   └── 10_workflow_events.py     — Event stream and lifecycle callbacks
│
├── agents_and_teams/             ← Agent composition and team workflows (Azure OpenAI)
│   ├── 01_team_from_config.py    — Inline team config with 3 agents
│   ├── 02_failure_policies.py    — Per-agent on_failure: fail, retry, skip
│   ├── 03_archetypes.py          — Browse and compose from archetype library
│   ├── 04_action_policies.py     — dry_run, require_approval action policies
│   ├── 05_conditional_workflow.py — Conditional review loop with max iterations
│   ├── 06_parallel_fanout.py     — Parallel fan-out with namespaced results
│   ├── 07_llm_team_generation.py — LLM-generated team composition
│   ├── 08_e2e_llm_team.py        — Full pipeline: generate → build → execute → publish
│   ├── 09_context_management.py  — All 10 context management strategies
│   ├── 10_task_driven_pipeline.py — Task-driven multi-agent pipeline
│   ├── 11_delegation.py          — Dynamic delegation to team members
│   ├── 12_spawn_and_delegate.py  — Spawn specialists from archetypes on-demand
│   ├── 13_collaborative_planning.py — Structured task planning with concurrency
│   ├── 14_full_auto_pipeline.py — Full-auto: file → LLM team → collaboration → publish
│   └── tasks/                   — Sample .md task files for file-driven examples
│
├── llm_providers/                ← LLM provider plugin system
│   ├── 01_discovery.py           — Provider discovery and capabilities
│   ├── 02_chat.py                — Basic chat completions
│   ├── 03_streaming.py           — Real-time token streaming
│   ├── 04_azure_rbac.py          — Azure RBAC vs API key authentication
│   ├── 05_secret_backend.py      — Custom secret backends (dict, vault)
│   ├── 06_tier_variables.py      — $SMART_LLM, $FAST_LLM resolution
│   ├── 07_fallback_chain.py      — FallbackChain and RetryProvider
│   ├── 08_observability.py       — structlog + OpenTelemetry integration
│   ├── 09_multi_turn.py          — Multi-turn conversation with history
│   ├── 10_function_calling.py    — Tool specs and tool_calls round-trip
│   └── 11_json_mode.py           — Structured JSON output mode
│
├── document_workflows/           ← Document processing pipelines
│   ├── 01_document_pipeline.py   — Loading, chunking, scoping (no LLM)
│   ├── 02_document_summarizer.py — Document analysis + executive summary
│   ├── 03_document_qa.py         — Q&A with DocumentRetrieverTool
│   ├── 04_multi_doc_report.py    — Multi-document report with per-agent scoping
│   └── 05_document_workflow.py   — Full document-driven workflow patterns
│
├── data_processing/              ← Retrievers, scrapers, embeddings, vector stores
│   ├── 01_retriever_search.py    — Multi-retriever search with dedup (no LLM)
│   ├── 02_scraper_pipeline.py    — Scraping, routing, validation, batch (no LLM)
│   ├── 03_embeddings_similarity.py — Embeddings + vector store + search (Azure)
│   ├── 04_semantic_filtering.py  — Semantic chunk filtering (Azure)
│   ├── 05_source_curation.py     — Credibility scoring pipeline (no LLM)
│   ├── 06_citations.py           — APA/MLA/Chicago citation styles (no LLM)
│   └── 07_research_workflow.py   — Full pipeline: retrieve, curate, embed, cite
│
├── advanced_workflows/           ← Complex multi-agent patterns
│   ├── 01_fan_out_report.py      — Planner → parallel writers → assembly
│   ├── 02_fan_out_generated.py   — Fan-out with dynamic team generation
│   ├── 03_deep_research.py       — Recursive branching research
│   └── 04_team_builder.py        — Generate team blueprint + publish
│
├── output_pipeline/              ← Publishing workflow results
│   ├── 01_basic_publish.py       — Workflow → Markdown + JSON
│   ├── 02_sdk_publish.py         — Rich ResultPayload programmatically
│   ├── 03_custom_layout.py       — Custom YAML layout templates
│   ├── 04_completion_callbacks.py — Sync/async completion callbacks
│   ├── 05_auto_publish_config.py — Auto-publish via team config
│   ├── 06_publish_pdf_docx.py    — PDF, DOCX, HTML multi-format
│   ├── 07_fan_out_publish.py     — Fan-out + multi-format publish
│   └── 08_generated_team_publish.py — Team generation + publish
│
├── console_app/                  ← End-to-end console application
│   └── main.py                   — Interactive multi-agent console app
│
├── resilience/                   ← Production resilience patterns
│   └── 01_fallback_and_cost.py   — Fallback chains, retries, cost tracking
│
├── streaming/                    ← Real-time event streaming
│   └── 01_event_streaming.py     — Event callbacks, StreamChannel, JSONL writer
│
└── sample_output/                ← Pre-generated output for reference
    ├── basic_workflow.txt
    ├── core_architecture/
    ├── agents_and_teams/
    └── ...
```

## Prerequisites

| Example Category       | Requirements                                |
| ---------------------- | ------------------------------------------- |
| **getting_started**    | `uv sync`                                   |
| **core_architecture**  | `uv sync` (mock providers, no API key)      |
| **agents_and_teams**   | `uv sync --extra llm-azure` + `az login`    |
| **llm_providers**      | Varies — see per-example docs               |
| **document_workflows** | `uv sync` (mock or live LLM)                |
| **advanced_workflows** | `uv sync` + OpenAI-compatible endpoint      |
| **output_pipeline**    | `uv sync --extra publishers` (for DOCX/PDF) |
| **resilience**         | `uv sync` (mock providers, no API key)      |
| **streaming**          | `uv sync` (mock providers, no API key)      |
| **console_app**        | `uv sync` + OpenAI-compatible endpoint      |

## Environment Variables

| Variable                  | Purpose                     | Default       |
| ------------------------- | --------------------------- | ------------- |
| `AZURE_OPENAI_ENDPOINT`   | Azure OpenAI resource URL   | (per-example) |
| `AZURE_OPENAI_DEPLOYMENT` | Azure model deployment name | `gpt-4o-mini` |
| `OPENAI_API_KEY`          | OpenAI API key              | —             |
| `ANTHROPIC_API_KEY`       | Anthropic API key           | —             |

## Conventions

- Each example is a self-contained script with a `main()` or `async main()`
  entry point
- Docstrings at the top explain what the example demonstrates and how to run it
- Examples that need an LLM default to Azure OpenAI with RBAC (`az login`)
- Mock providers are used where live LLM access isn't needed
- Output files are written to `./output/` (gitignored)
- Sample output is captured in `sample_output/` for reference without running
