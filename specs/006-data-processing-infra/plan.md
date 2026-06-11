# Implementation Plan: Data Processing Infrastructure

**Branch**: `006-data-processing-infra` | **Date**: 2026-02-25 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/006-data-processing-infra/spec.md`

## Summary

Implement the data processing layer beneath hiveflow's agent system: pluggable retrievers for web search, scrapers for content extraction, embedding providers for semantic similarity, vector stores for persistent search, an ingestion-time semantic filtering pipeline, a source curation/credibility scoring pipeline, citation configuration in team configs, and Azure Blob/URL document loaders. All new capabilities are plugin-based, off by default, and additive over the existing codebase. The existing `SimpleVectorStore`, `SearchResult`, `ScrapedContent`, `EmbeddingProvider`, `RetrieverPlugin`, `ScraperPlugin`, and `CitationTracker` base classes/interfaces already exist and will be extended, not replaced.

## Technical Context

**Language/Version**: Python 3.11+ (no `from __future__ import annotations`)
**Primary Dependencies**: httpx, aiofiles, structlog, pydantic>=2.9.2, pydantic-settings, openai>=1.52.0; new optional: beautifulsoup4, playwright, duckduckgo-search, tavily-python, numpy
**Storage**: In-memory vector store (default); pluggable backends (ChromaDB, FAISS, etc.) via entry points; file-based JSON for checkpoints (existing)
**Testing**: pytest + pytest-asyncio; `uv run pytest`
**Target Platform**: Python library (cross-platform); no server/CLI changes required
**Project Type**: Single Python package with plugin extras
**Performance Goals**: scrape_batch of 20 URLs in under 60s with 15 concurrency; embedding batch of 100 chunks under 10s; vector search of 10K documents under 500ms
**Constraints**: Per-URL scrape timeout 15s (configurable); scrape concurrency 15 (configurable); similarity threshold 0.35 (configurable); chunk size 1000 chars / overlap 200 chars (existing)
**Scale/Scope**: Plugin interfaces + 2 retrievers + 2 scrapers + 1 embedding provider + 1 vector store (in-memory refactored) + semantic pipeline + source curation + citation config + 2 document loaders

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| **S2.1** Configuration Over Code | PASS | All new features configured via team config blocks (`retrievers`, `source_curation`, `citations`, `vector_store`). No user code required. |
| **S2.2** Progressive Disclosure | PASS | Everything off by default. Existing workflows unchanged (SC-008). Simple usage path unaffected. |
| **S2.3** Explicit State, No Magic | PASS | New state keys (`visited_urls`) are documented. All data flows through state dict. |
| **S2.4** Plugin Architecture | PASS | Core feature: 4 new plugin types with entry point discovery. |
| **S2.5** Backward Compatibility | PASS | All changes additive. Existing `SearchResult`, `ScrapedContent`, `EmbeddingProvider` interfaces preserved. `SimpleVectorStore` refactored to superset interface. |
| **S2.6** Observability | PASS | FR-034: all new plugins use structlog. StreamChannel reserved for workflow events. |
| **S2.7** Fail Loudly, Recover Gracefully | PASS | Error isolation in scrape_batch (return_exceptions). Clear messages for missing plugins. Graceful fallback to full content when no embedding provider configured. |
| **S3.1** Core Module Boundaries | PASS | Retriever/scraper/embedding/vector store implementations live in `plugins/`. Core modules (`documents.py`, `schema.py`, `workflow.py`) gain minimal integration points only. |
| **S3.2** Plugin Rules | PASS | No global state at import. Missing optional deps log warning and skip registration. |
| **S3.3** Boundary Layers | PASS | No CLI/API/server changes required. |
| **S4.1** Workflow State | PASS | `visited_urls` added as optional key (only when citations enabled). Existing reserved keys unchanged. |
| **S4.3** Document Shape | PASS | No changes to existing document contract. |
| **S5.1** Language | PASS | Python 3.11+. No `__future__` imports. |
| **S5.2** Package Management | PASS | uv only. New deps added as optional extras in `pyproject.toml`. |
| **S5.3** Library Preferences | PASS | No Microsoft equivalent exists for search retrieval, web scraping, or embedding. OpenAI, BeautifulSoup, Playwright justified. |
| **S5.4** Async First | PASS | All new plugin interfaces are async. |
| **S6.1** Testing | Required | Each new module gets unit tests. Integration tests for full pipeline. |
| **S6.3** Documentation | Required | README, CHANGELOG updates. |
| **S7** Extension Guidelines | PASS | All 6 checklist items addressed: plugins not core, progressive disclosure, state keys documented, observable via structlog, testing and docs required. |
| **S8** Scope Boundaries | PASS | Source curation pipeline feeds context to agents (not ETL). Aligns with "document loading exists to feed context to agents." |

**Gate result: PASS. No violations. Complexity Tracking table not needed.**

**Post-Phase 1 re-check**: PASS. Design artifacts (data-model.md, contracts/, quickstart.md) are consistent with all principles. No new violations introduced. VectorStorePlugin is a plugin (S3.2), source curation lives in core/ but only orchestrates plugin calls (S3.1), all contracts are async-first (S5.4).

## Project Structure

### Documentation (this feature)

```text
specs/006-data-processing-infra/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── retriever.py     # RetrieverPlugin interface contract
│   ├── scraper.py       # ScraperPlugin interface contract
│   ├── embedding.py     # EmbeddingProvider interface contract
│   ├── vector_store.py  # VectorStorePlugin interface contract
│   └── source_curation.py # SourceCurationPipeline contract
└── tasks.md             # Phase 2 output (/speckit.tasks)
```

### Source Code (repository root)

```text
hiveflow/
├── core/
│   ├── schema.py               # Extended: CitationConfig, SourceCurationConfig, VectorStoreConfig models
│   ├── documents.py            # Extended: relevant_chunks mode with embedding pipeline
│   ├── workflow.py             # Extended: visited_urls tracking, citation auto-integration
│   ├── citations.py            # Extended: MLA + Chicago formats, config-driven activation
│   └── source_curation.py      # NEW: multi-signal scoring pipeline
│
├── plugins/
│   ├── retrievers/
│   │   ├── __init__.py         # EXISTING: RetrieverPlugin, SearchResult, RetrieverRegistry
│   │   ├── tavily_retriever.py # NEW: Tavily search backend
│   │   └── duckduckgo_retriever.py # NEW: DuckDuckGo search backend
│   │
│   ├── scrapers/
│   │   ├── __init__.py         # EXISTING: ScraperPlugin, ScrapedContent, ScraperRegistry
│   │   ├── bs4_scraper.py      # NEW: BeautifulSoup scraper
│   │   └── playwright_scraper.py # NEW: Playwright JS-capable scraper
│   │
│   ├── embeddings/
│   │   ├── __init__.py         # EXISTING: EmbeddingProvider, SimpleVectorStore, EmbeddingProviderRegistry
│   │   └── openai_embeddings.py # NEW: OpenAI embedding provider
│   │
│   ├── vector_stores/
│   │   ├── __init__.py         # NEW: VectorStorePlugin, VectorStoreRegistry
│   │   └── memory_store.py     # NEW: Refactored SimpleVectorStore as VectorStorePlugin
│   │
│   └── documents/
│       ├── azure_blob_loader.py # NEW: Azure Blob Storage loader
│       └── url_loader.py       # NEW: URL loader via scraper pipeline
│
├── validation/
│   └── path_security.py        # EXISTING: no changes
│
└── __init__.py                 # Extended: export new public classes

tests/
├── test_retriever_plugins.py        # NEW: retriever plugin unit tests
├── test_scraper_plugins.py          # NEW: scraper plugin unit tests
├── test_embedding_plugins.py        # NEW: embedding provider unit tests
├── test_vector_store_plugins.py     # NEW: vector store plugin unit tests
├── test_semantic_filtering.py       # NEW: end-to-end semantic pipeline
├── test_source_curation.py          # NEW: source curation scoring/filtering
├── test_citation_config.py          # NEW: citation config integration
├── test_azure_blob_loader.py        # NEW: Azure Blob loader
├── test_url_loader.py               # NEW: URL document loader
└── test_scraper_timeout.py          # NEW: per-URL timeout behavior
```

**Structure Decision**: Single Python package. All new backend implementations live in `hiveflow/plugins/`. The only core module additions are `source_curation.py` (new) and config extensions to `schema.py`, `citations.py`, `documents.py`, and `workflow.py`. This follows the established pattern where plugin interfaces live in `plugins/` and orchestration logic lives in `core/`.
