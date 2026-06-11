# Tasks: Data Processing Infrastructure

**Input**: Design documents from `/specs/006-data-processing-infra/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅, quickstart.md ✅

**Tests**: Included — per constitution §S6.1, each new module requires unit tests and integration tests for the full pipeline.

**Organization**: Tasks grouped by user story (8 stories, P1–P8) for independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project configuration, dependency groups, entry points, and directory structure

- [x] T001 <!-- bd:hiveflow-hgv.1 --> Update pyproject.toml — add optional dependency extras groups (`retrieval`, `scraping`, `embeddings`, `documents-azure`) and entry points for all new plugin types (`hiveflow.retrievers`, `hiveflow.scrapers`, `hiveflow.embeddings`, `hiveflow.vector_stores`) per quickstart.md
- [x] T002 <!-- bd:hiveflow-hgv.2 --> Create new plugin directories with `__init__.py` files: `hiveflow/plugins/vector_stores/__init__.py` and `hiveflow/plugins/documents/__init__.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Config models, base classes, and shared utilities that ALL user stories depend on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T003 <!-- bd:hiveflow-hgv.3 --> [P] Add `CitationConfig`, `SourceCurationConfig`, `ScoringWeights`, and `VectorStoreConfig` pydantic models to `hiveflow/core/schema.py` per data-model.md — CitationConfig (enabled, style, inline, generate_reference_section), SourceCurationConfig (enabled, min_score, max_sources, freshness_max_age_days, domain_allow_list, domain_block_list, scoring_weights), VectorStoreConfig (backend, collection_prefix, persist, similarity_metric); wire into TeamConfiguration as optional fields
- [x] T004 <!-- bd:hiveflow-hgv.4 --> [P] Create `VectorStorePlugin` abstract base class with `add()`, `search()`, `delete()`, `clear()`, `count()` methods, `CollectionManager` class, and `VectorStoreRegistry` in `hiveflow/plugins/vector_stores/__init__.py` per contracts/vector_store.py
- [x] T005 <!-- bd:hiveflow-hgv.5 --> [P] Add `ScraperRouter` class (URL-pattern-based scraper selection with fallback to default) and `validate_scraped_content()` function (MIN_CONTENT_LENGTH=100 chars) to `hiveflow/plugins/scrapers/__init__.py` per contracts/scraper.py; update `scrape_batch()` default concurrency to 15
- [x] T006 <!-- bd:hiveflow-hgv.6 --> [P] Add `estimate_cost(num_tokens: int) -> float` method to `EmbeddingProvider` base class in `hiveflow/plugins/embeddings/__init__.py` per contracts/embedding.py

**Checkpoint**: Foundation ready — user story implementation can now begin

---

## Phase 3: User Story 1 — Search External Sources via Retrievers (Priority: P1) 🎯 MVP

**Goal**: Workflow authors configure search backends (Tavily, DuckDuckGo) in team config; agents invoke retrievers to get merged, deduplicated search results

**Independent Test**: Configure a single retriever, run a search query, verify results returned in normalized SearchResult format with url, title, content, score, and metadata fields

### Tests for User Story 1

- [x] T007 <!-- bd:hiveflow-hgv.7 --> [P] [US1] Write unit tests for TavilyRetriever and DuckDuckGoRetriever in `tests/test_retriever_plugins.py` — mock external APIs, test SearchResult field mapping, test error handling for missing API keys and network failures, test DuckDuckGo positional scoring, test multi-retriever deduplication by URL

### Implementation for User Story 1

- [x] T008 <!-- bd:hiveflow-hgv.8 --> [P] [US1] Implement `TavilyRetriever` in `hiveflow/plugins/retrievers/tavily_retriever.py` — use `tavily-python` AsyncTavilyClient per research.md R1; lazy import with clear error message for missing package; map result fields 1:1 to SearchResult contract; structlog logging per FR-034
- [x] T009 <!-- bd:hiveflow-hgv.9 --> [P] [US1] Implement `DuckDuckGoRetriever` in `hiveflow/plugins/retrievers/duckduckgo_retriever.py` — use `duckduckgo-search` DDGS wrapped with `asyncio.to_thread()` per research.md R2; map `href`→`url`, `body`→`content`; assign synthetic positional scores `1.0 - (index * 0.05)`; structlog logging
- [x] T010 <!-- bd:hiveflow-hgv.10 --> [US1] Verify and enhance `RetrieverRegistry.search_all()` in `hiveflow/plugins/retrievers/__init__.py` — ensure parallel dispatch via `asyncio.gather()`, URL-based deduplication (keep highest score), descending sort by score, individual retriever failure isolation with error logging

**Checkpoint**: User Story 1 fully functional — single or multi-retriever search returns normalized, deduplicated results

---

## Phase 4: User Story 2 — Extract Web Content via Scrapers (Priority: P2)

**Goal**: Scrapers extract clean text from URLs; URL-pattern routing selects appropriate scraper; batch scraping with concurrency control and per-URL timeout

**Independent Test**: Provide a URL, run the scraper, verify clean text extracted with ScrapedContent contract fields; test batch of 20 URLs with concurrency 15

### Tests for User Story 2

- [x] T011 <!-- bd:hiveflow-hgv.11 --> [P] [US2] Write unit tests for BS4Scraper and PlaywrightScraper in `tests/test_scraper_plugins.py` — mock HTTP responses, test HTML cleanup (scripts/nav/ads removed), test ScrapedContent field population, test content validation (< 100 chars discarded), test ScraperRouter pattern matching
- [x] T012 <!-- bd:hiveflow-hgv.12 --> [P] [US2] Write scraper timeout behavior tests in `tests/test_scraper_timeout.py` — test per-URL timeout enforcement (default 15s), test that timed-out URLs return errors without blocking batch, test configurable timeout via HIVEFLOW_SCRAPER_TIMEOUT env var

### Implementation for User Story 2

- [x] T013 <!-- bd:hiveflow-hgv.13 --> [P] [US2] Implement `BS4Scraper` in `hiveflow/plugins/scrapers/bs4_scraper.py` — use BeautifulSoup4 with `html.parser` per research.md R3; decompose script/style/nav/footer/header/aside/iframe/form; extract main/article/body content; httpx async client with configurable timeout; structlog logging
- [x] T014 <!-- bd:hiveflow-hgv.14 --> [P] [US2] Implement `PlaywrightScraper` in `hiveflow/plugins/scrapers/playwright_scraper.py` — use Playwright async API per research.md R4; Chromium headless, `networkidle` wait; lazy import with clear error for missing package/binaries; shared browser context, new page per URL; configurable timeout; structlog logging
- [x] T015 <!-- bd:hiveflow-hgv.15 --> [US2] Integrate `ScraperRouter` with `scrape_batch()` — route URLs through ScraperRouter.select() before scraping; apply `validate_scraped_content()` to filter results below 100 chars; ensure per-URL error isolation via `asyncio.gather(return_exceptions=True)`

**Checkpoint**: User Story 2 fully functional — single and batch scraping works with routing, validation, concurrency control, and timeout enforcement

---

## Phase 5: User Story 3 — Embed and Search Content via Embedding Providers (Priority: P3)

**Goal**: Embedding provider generates vectors from text chunks; enables similarity-based filtering and the `relevant_chunks` document mode

**Independent Test**: Configure OpenAI embedding provider, embed text chunks, verify returned vectors have consistent dimensions and cosine similarity produces meaningful rankings

### Tests for User Story 3

- [x] T016 <!-- bd:hiveflow-hgv.16 --> [P] [US3] Write unit tests for OpenAIEmbeddingProvider in `tests/test_embedding_plugins.py` — mock OpenAI API responses, test vector dimensions consistency, test auto-batch splitting when exceeding max_batch_size, test estimate_cost calculation, test error handling for invalid API keys, test embed_single convenience method

### Implementation for User Story 3

- [x] T017 <!-- bd:hiveflow-hgv.17 --> [US3] Implement `OpenAIEmbeddingProvider` in `hiveflow/plugins/embeddings/openai_embeddings.py` — use openai SDK AsyncOpenAI per research.md R5; default model `text-embedding-3-small` (1536 dims); auto-split batches exceeding max_batch_size (100); implement estimate_cost (~$0.02/1M tokens); lazy import with clear error; structlog logging

**Checkpoint**: User Story 3 fully functional — text can be embedded and similarity computed

---

## Phase 6: User Story 4 — Store and Search Vectors via Vector Store Plugins (Priority: P4)

**Goal**: Vector store persists embedded chunks; supports isolated collection namespaces per workflow run; in-memory implementation with numpy-accelerated cosine similarity

**Independent Test**: Add documents with embeddings to store, run similarity search, verify results ranked by relevance with correct scores

### Tests for User Story 4

- [x] T018 <!-- bd:hiveflow-hgv.18 --> [P] [US4] Write unit tests for MemoryVectorStore in `tests/test_vector_store_plugins.py` — test add/search/delete/clear/count operations, test upsert behavior, test collection namespace isolation, test cosine similarity ranking, test doc_id validation, test numpy fallback to pure-Python path, test ephemeral vs persistent collection cleanup via CollectionManager

### Implementation for User Story 4

- [x] T019 <!-- bd:hiveflow-hgv.19 --> [US4] Implement `MemoryVectorStore` in `hiveflow/plugins/vector_stores/memory_store.py` — refactor from existing `SimpleVectorStore` to conform to `VectorStorePlugin` interface per contracts/vector_store.py; all methods async; numpy vectorized cosine similarity per research.md R6 with pure-Python fallback; doc_id-based upsert, delete, count; structlog logging
- [x] T020 <!-- bd:hiveflow-hgv.20 --> [US4] Implement `CollectionManager` namespace isolation in `hiveflow/plugins/vector_stores/__init__.py` — `{collection_prefix}_{session_id}` naming; ephemeral cleanup on workflow completion (best-effort with warning on failure); persist mode skips cleanup

**Checkpoint**: User Story 4 fully functional — vectors stored, searched, and isolated per workflow run

---

## Phase 7: User Story 5 — Filter Ingested Content via Semantic Compression (Priority: P5)

**Goal**: Automatic chunking-and-filtering pipeline: split content into chunks, embed each, filter by cosine similarity threshold, assemble focused context with source attribution

**Independent Test**: Provide a large text block and query, verify output contains only relevant chunks above similarity threshold with source attribution

### Tests for User Story 5

- [x] T021 <!-- bd:hiveflow-hgv.21 --> [P] [US5] Write end-to-end semantic filtering tests in `tests/test_semantic_filtering.py` — test full pipeline: chunk → embed → similarity filter → assemble; test similarity threshold filtering (0.35 default, 0.7 strict); test source attribution preservation; test graceful fallback to full content when no embedding provider configured; test with multiple source documents

### Implementation for User Story 5

- [x] T022 <!-- bd:hiveflow-hgv.22 --> [US5] Implement semantic filtering pipeline in `hiveflow/core/documents.py` — enhance `relevant_chunks` document mode to use embedding provider + vector store instead of falling back to `full` mode; chunk content, embed chunks, compute cosine similarity against task/query, filter by configurable similarity threshold (default 0.35), retain source attribution per chunk; fall back to full content with warning when no embedding provider configured (FR-021)

**Checkpoint**: User Story 5 fully functional — large documents compressed to only relevant chunks with source tracking

---

## Phase 8: User Story 6 — Rank Sources by Credibility Before Deep Extraction (Priority: P6)

**Goal**: Multi-signal credibility scoring pipeline filters retriever results before full scraping; signals: domain authority, content relevance, freshness, LLM judgment

**Independent Test**: Provide mixed-quality URLs, verify high-quality sources score above threshold while low-quality sources are filtered out

### Tests for User Story 6

- [x] T023 <!-- bd:hiveflow-hgv.23 --> [P] [US6] Write source curation unit tests in `tests/test_source_curation.py` — test score_domain_authority (allow/block lists, unknown domains), test score_freshness (within/beyond max_age_days, no date), test score_content_relevance (mock embeddings), test score_llm_judgment (mock LLM), test SourceCurationPipeline.curate() end-to-end, test min_score filtering, test max_sources limit, test reweighting when no embedding provider

### Implementation for User Story 6

- [x] T024 <!-- bd:hiveflow-hgv.24 --> [US6] Implement `SourceCurationPipeline` with all scoring signals in `hiveflow/core/source_curation.py` — per contracts/source_curation.py: snippet scraping (~500 chars), score_domain_authority (allow/block lists, 0.5 neutral), score_content_relevance (cosine similarity via embedding provider, skip if unavailable), score_freshness (linear decay to 0.3 floor), score_llm_judgment (FAST_LLM 1-10 scale normalized); composite weighted scoring per ScoringWeights; filter by min_score, cap at max_sources; structlog logging

**Checkpoint**: User Story 6 fully functional — low-quality sources filtered before expensive deep scraping

---

## Phase 9: User Story 7 — Configure Citation Tracking via Team Config (Priority: P7)

**Goal**: Declarative citation configuration in team config; automatic URL tracking, inline references, and formatted reference section in workflow output

**Independent Test**: Add `citations.enabled: true` to team config, run workflow accessing external sources, verify ResultPayload contains formatted reference section

### Tests for User Story 7

- [x] T025 <!-- bd:hiveflow-hgv.25 --> [P] [US7] Write citation config integration tests in `tests/test_citation_config.py` — test config-driven activation (enabled/disabled), test APA/MLA/Chicago/numbered/inline styles, test visited_urls deduplication, test inline reference insertion, test reference section generation, test no-op when citations disabled

### Implementation for User Story 7

- [x] T026 <!-- bd:hiveflow-hgv.26 --> [P] [US7] Add MLA and Chicago citation formats to `hiveflow/core/citations.py` — extend existing citation formatter with MLA and Chicago style support per FR-028; preserve existing apa, numbered, inline formats
- [x] T027 <!-- bd:hiveflow-hgv.27 --> [US7] Integrate `CitationConfig` with workflow engine in `hiveflow/core/workflow.py` — when `citations.enabled: true`: initialize `visited_urls` set in workflow state, track all URLs accessed during workflow, auto-assemble reference section in configured style into ResultPayload; skip all citation processing when disabled (FR-027)

**Checkpoint**: User Story 7 fully functional — citations tracked and formatted automatically based on team config

---

## Phase 10: User Story 8 — Load Documents from Cloud Storage and URLs (Priority: P8)

**Goal**: Azure Blob Storage and URL document loaders extend the DocumentPipeline to cloud and web sources

**Independent Test**: Provide a cloud storage path or URL, verify loaded document matches same structure as locally loaded documents with chunks, token estimates, and source metadata

### Tests for User Story 8

- [x] T028 <!-- bd:hiveflow-hgv.28 --> [P] [US8] Write Azure Blob loader tests in `tests/test_azure_blob_loader.py` — mock Azure SDK, test content extraction and chunking, test DefaultAzureCredential and connection string auth, test URL format parsing (account/container/blob), test clear error for invalid credentials, test format detection from blob path extension
- [x] T029 <!-- bd:hiveflow-hgv.29 --> [P] [US8] Write URL loader tests in `tests/test_url_loader.py` — mock scraper pipeline, test URL content loaded as Document with chunks and token estimates, test source metadata population, test error handling for unsupported content types

### Implementation for User Story 8

- [x] T030 <!-- bd:hiveflow-hgv.30 --> [P] [US8] Implement `AzureBlobLoader` in `hiveflow/plugins/documents/azure_blob_loader.py` — use `azure-storage-blob` async API per research.md R7; support DefaultAzureCredential, connection string, SAS token; parse Azure blob URL format; download and wrap in Document format with chunking; lazy import with clear error for missing package; structlog logging
- [x] T031 <!-- bd:hiveflow-hgv.31 --> [P] [US8] Implement `URLLoader` in `hiveflow/plugins/documents/url_loader.py` — use scraper pipeline to fetch and extract content; wrap result in standard Document format with chunks, token estimates, and source metadata; structlog logging

**Checkpoint**: User Story 8 fully functional — documents loaded identically from local, cloud, and web sources

---

## Phase 11: Polish & Cross-Cutting Concerns

**Purpose**: Exports, documentation, and regression validation

- [x] T032 <!-- bd:hiveflow-hgv.32 --> [P] Update `hiveflow/__init__.py` with new public exports — VectorStorePlugin, VectorStoreRegistry, MemoryVectorStore, CollectionManager, SourceCurationPipeline, CitationConfig, SourceCurationConfig, VectorStoreConfig, ScraperRouter
- [x] T033 <!-- bd:hiveflow-hgv.33 --> [P] Update `CHANGELOG.md` with all feature additions under appropriate version heading
- [x] T034 <!-- bd:hiveflow-hgv.34 --> [P] Update `README.md` with new plugin documentation — retriever, scraper, embedding, vector store plugin types; configuration examples; entry point registration
- [x] T035 <!-- bd:hiveflow-hgv.35 --> Run quickstart.md code examples for validation (smoke test key integration points)
- [x] T036 <!-- bd:hiveflow-hgv.36 --> Run full test suite (`uv run pytest`) and fix any regressions — ensure existing tests still pass (SC-008)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Setup (Phase 1) completion — BLOCKS all user stories
- **User Stories (Phases 3–10)**: All depend on Foundational (Phase 2) completion
  - US1 (Retrievers): No dependencies on other stories
  - US2 (Scrapers): No dependencies on other stories
  - US3 (Embeddings): No dependencies on other stories
  - US4 (Vector Stores): No dependencies on other stories
  - US5 (Semantic Filtering): Depends on US3 (embedding provider) and US4 (vector store)
  - US6 (Source Curation): Uses scraper (US2) and optionally embedding provider (US3), but can operate without them
  - US7 (Citations): No dependencies on other stories (extends existing CitationTracker)
  - US8 (Document Loaders): Uses scraper pipeline (US2) for URLLoader, but AzureBlobLoader is independent
- **Polish (Phase 11)**: Depends on all user stories being complete

### User Story Dependencies

```text
Phase 2 (Foundational)
  ├── US1 (Retrievers)     ─── independent
  ├── US2 (Scrapers)       ─── independent
  ├── US3 (Embeddings)     ─── independent
  ├── US4 (Vector Stores)  ─── independent
  ├── US5 (Semantic Filter) ── depends on US3 + US4
  ├── US6 (Source Curation) ── soft depends on US2, US3 (degrades gracefully)
  ├── US7 (Citations)      ─── independent
  └── US8 (Doc Loaders)    ── URLLoader soft depends on US2
```

### Within Each User Story

- Tests written FIRST, ensure they FAIL before implementation
- Base implementations before integration
- Core logic before error handling polish
- Story complete before moving to next priority

### Parallel Opportunities

- Phase 2: T003, T004, T005, T006 — all parallel (different files)
- Phase 3: T007, T008, T009 — all parallel (different files); T010 after T008+T009
- Phase 4: T011, T012, T013, T014 — all parallel (different files); T015 after T013+T014
- Phase 5: T016 parallel with T017 (different files)
- Phase 6: T018 parallel (different file); T019 after T004; T020 after T019
- Phases 3, 4, 5, 6, 7 can run in parallel (independent stories)
- Phase 10: T028, T029, T030, T031 — all parallel (different files)
- Phase 11: T032, T033, T034 — all parallel; T035, T036 sequential after all stories

---

## Parallel Example: User Story 1

```bash
# Launch all parallel tasks for User Story 1 together:
Task T007: "Write unit tests for retriever plugins in tests/test_retriever_plugins.py"
Task T008: "Implement TavilyRetriever in hiveflow/plugins/retrievers/tavily_retriever.py"
Task T009: "Implement DuckDuckGoRetriever in hiveflow/plugins/retrievers/duckduckgo_retriever.py"

# Then sequential:
Task T010: "Verify/enhance RetrieverRegistry.search_all()" (depends on T008, T009)
```

## Parallel Example: User Story 2

```bash
# Launch all parallel tasks for User Story 2 together:
Task T011: "Write unit tests for scraper plugins in tests/test_scraper_plugins.py"
Task T012: "Write timeout tests in tests/test_scraper_timeout.py"
Task T013: "Implement BS4Scraper in hiveflow/plugins/scrapers/bs4_scraper.py"
Task T014: "Implement PlaywrightScraper in hiveflow/plugins/scrapers/playwright_scraper.py"

# Then sequential:
Task T015: "Integrate ScraperRouter with scrape_batch()" (depends on T013, T014)
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL — blocks all stories)
3. Complete Phase 3: User Story 1 (Retrievers)
4. **STOP and VALIDATE**: Run `uv run pytest tests/test_retriever_plugins.py` — all tests pass
5. Deploy/demo if ready — agents can now search external sources

### Incremental Delivery

1. Setup + Foundational → Foundation ready
2. Add US1 (Retrievers) → Test → **MVP: Agents search the web**
3. Add US2 (Scrapers) → Test → **Agents extract full page content**
4. Add US3 (Embeddings) → Test → **Text can be vectorized**
5. Add US4 (Vector Stores) → Test → **Vectors can be persisted and searched**
6. Add US5 (Semantic Filtering) → Test → **relevant_chunks mode works**
7. Add US6 (Source Curation) → Test → **Low-quality sources filtered**
8. Add US7 (Citations) → Test → **Automatic citation tracking**
9. Add US8 (Doc Loaders) → Test → **Cloud and URL document loading**
10. Polish → Full regression test → **Feature complete**

### Parallel Team Strategy

With multiple developers after Foundational phase:

- Developer A: US1 (Retrievers) + US2 (Scrapers)
- Developer B: US3 (Embeddings) + US4 (Vector Stores)
- Developer C: US7 (Citations) + US8 (Doc Loaders)
- Then: US5 (Semantic Filtering) after US3+US4; US6 (Source Curation) after US2+US3

---

## Notes

- [P] tasks = different files, no dependencies on incomplete tasks
- [Story] label maps task to specific user story for traceability
- All new plugins use structlog (not StreamChannel) per FR-034 / spec clarification
- Existing interfaces (RetrieverPlugin, ScraperPlugin, EmbeddingProvider, SearchResult, ScrapedContent) are preserved — only extended
- SimpleVectorStore remains available but deprecated after MemoryVectorStore ships
- All optional dependencies use lazy imports with clear error messages for missing packages
- Per-URL scrape timeout defaults to 15s, configurable via HIVEFLOW_SCRAPER_TIMEOUT
