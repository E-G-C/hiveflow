# Feature Specification: Data Processing Infrastructure

**Feature Branch**: `006-data-processing-infra`
**Created**: 2026-02-25
**Status**: Draft
**Input**: User description: "Data processing infrastructure: retrievers, scrapers, embeddings, vector stores, document loading enhancements, context compression, citations, and source curation — as defined in requirements/05-data-processing.md"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Search External Sources via Retrievers (Priority: P1)

A workflow author configures one or more search backends (e.g., Tavily, DuckDuckGo) in their team config. When an agent needs external information, it invokes a retriever tool. The framework queries all configured retrievers in parallel, deduplicates results by URL, and returns a ranked list of search results that the agent can use as context.

**Why this priority**: Retrievers are the entry point for all external data acquisition. Without them, agents operate in a closed context and cannot access web search, academic databases, or other live information sources. Every downstream capability (scraping, curation, embedding-based filtering) depends on retriever output.

**Independent Test**: Can be fully tested by configuring a single retriever, running a search query, and verifying that results are returned in the normalized contract format with URL, title, content, score, and metadata fields.

**Acceptance Scenarios**:

1. **Given** a team config with `retrievers: ["tavily"]`, **When** an agent issues a search query, **Then** the framework returns a list of `SearchResult` objects with all contract fields populated.
2. **Given** a team config with `retrievers: ["tavily", "duckduckgo"]`, **When** a search query is executed, **Then** both retrievers are queried in parallel and results are deduplicated by URL and sorted by score descending.
3. **Given** a retriever that fails (network error, invalid API key), **When** other retrievers succeed, **Then** the failing retriever's error is logged and the successful results are still returned.
4. **Given** no retriever plugins are installed, **When** the framework attempts to search, **Then** a clear error message indicates which retriever package is missing.

---

### User Story 2 - Extract Web Content via Scrapers (Priority: P2)

A workflow author configures a scraper backend. When the framework has URLs to process (from retriever results or direct input), scrapers extract clean text content from those pages. The framework selects the appropriate scraper based on URL patterns (e.g., PDF URLs use a PDF-specific scraper, ArXiv URLs use a structured academic scraper, everything else uses the configured default).

**Why this priority**: Retrievers return snippets, but agents need full page content to do meaningful work. Scrapers bridge the gap between search result URLs and usable text context. They are the second link in the data acquisition chain.

**Independent Test**: Can be fully tested by providing a URL, running the scraper, and verifying that clean text content is extracted with the ScrapedContent contract fields.

**Acceptance Scenarios**:

1. **Given** a URL pointing to a standard web page, **When** the default scraper processes it, **Then** clean text is extracted with navigation, ads, and scripts removed.
2. **Given** a batch of 20 URLs, **When** `scrape_batch()` is called with max concurrency of 15, **Then** no more than 15 scrape operations run simultaneously, and each result (or error) is returned independently.
3. **Given** a URL that returns fewer than 100 characters of useful content, **When** content validation is enabled, **Then** that URL's content is discarded as insufficient.
4. **Given** a URL matching `*.pdf`, **When** scraper routing is active, **Then** the PDF-specific scraper is selected instead of the default web scraper.
5. **Given** a scraper that times out on one URL in a batch, **When** the batch completes, **Then** the timed-out URL returns an error while all other URLs return their content.

---

### User Story 3 - Embed and Search Content via Embedding Providers (Priority: P3)

A workflow author selects an embedding provider (e.g., OpenAI, Ollama). The framework uses it to generate vector embeddings from text chunks, enabling similarity-based filtering and retrieval. This powers the `relevant_chunks` document mode, which currently falls back to `full` mode.

**Why this priority**: Embedding providers are the enabler for semantic search, context filtering, and the `relevant_chunks` document mode that is already defined in the framework but non-functional without embeddings. This unblocks a core feature that workflow authors have access to in the schema but cannot use.

**Independent Test**: Can be fully tested by configuring an embedding provider, embedding a set of text chunks, and verifying that the returned vectors have the expected dimensions and that cosine similarity produces meaningful rankings.

**Acceptance Scenarios**:

1. **Given** a configured embedding provider, **When** a list of text strings is passed to `embed()`, **Then** a list of vectors is returned with consistent dimensions matching the provider's specification.
2. **Given** batch sizes exceeding the provider's `max_batch_size`, **When** `embed()` is called, **Then** the provider automatically splits the batch and combines results transparently.
3. **Given** a provider that is unavailable (API down, bad key), **When** `embed()` is called, **Then** a clear error is raised rather than returning garbage vectors.
4. **Given** an agent with `document_mode: "relevant_chunks"` and a configured embedding provider, **When** documents are scoped for that agent, **Then** only the most relevant chunks (by cosine similarity against the task) are included instead of falling back to full mode.

---

### User Story 4 - Store and Search Vectors via Vector Store Plugins (Priority: P4)

A workflow author selects a vector store backend (in-memory for development, a persistent store for production). The framework stores embedded document chunks in the vector store and retrieves similar documents during agent execution. Each workflow run operates in an isolated collection namespace.

**Why this priority**: The vector store completes the embedding pipeline. Without persistent storage, embeddings are generated on every run and similarity search has no durable index. The plugin system also decouples the framework from any single vector database vendor.

**Independent Test**: Can be fully tested by adding documents with embeddings to the store, running a similarity search, and verifying that results are ranked by relevance with correct scores.

**Acceptance Scenarios**:

1. **Given** an in-memory vector store, **When** vectors and documents are added, **Then** `search()` returns the most similar documents ranked by cosine similarity.
2. **Given** two concurrent workflow runs, **When** each creates its own collection namespace, **Then** documents from one run are not visible to the other.
3. **Given** a persistent vector store backend, **When** a workflow run completes and a new run starts with the same collection prefix, **Then** previously stored vectors are still available.
4. **Given** a vector store with 1000 documents, **When** `delete()` is called with specific document IDs, **Then** those documents are removed and `count()` reflects the change.
5. **Given** an ephemeral collection configuration, **When** the workflow completes, **Then** the collection is cleaned up automatically.

---

### User Story 5 - Filter Ingested Content via Semantic Compression (Priority: P5)

When raw scraped or retrieved content is too large for the LLM context window, the framework applies an automatic chunking-and-filtering pipeline: split the content into character-level chunks, embed each chunk, compute cosine similarity against the query, and keep only chunks that exceed the similarity threshold. This produces a focused, relevant context with source attribution.

**Why this priority**: This is the end-to-end pipeline that ties together chunking (already implemented), embeddings (P3), and vector stores (P4) into a usable compression flow. Without this, agents receive either all content (potentially overflowing context) or no content.

**Independent Test**: Can be fully tested by providing a large text block and a query, running the pipeline, and verifying that the output contains only the most relevant chunks with source attribution, and that the total size is within the context budget.

**Acceptance Scenarios**:

1. **Given** a 50,000-character document and a specific query, **When** the semantic filtering pipeline runs with a similarity threshold of 0.35, **Then** only chunks with cosine similarity above 0.35 are included in the output.
2. **Given** multiple documents from different sources, **When** filtered chunks are assembled, **Then** each chunk retains attribution to its source document.
3. **Given** a similarity threshold setting, **When** the threshold is raised to 0.7, **Then** fewer chunks pass the filter and the output is more focused.
4. **Given** no embedding provider is configured, **When** content filtering is attempted, **Then** the system falls back gracefully to full content (preserving existing behavior) and logs a warning.

---

### User Story 6 - Rank Sources by Credibility Before Deep Extraction (Priority: P6)

Before committing to full content extraction, the framework applies a multi-signal credibility scoring pipeline to retriever results. It scrapes a brief snippet from each URL, scores it on domain authority, content relevance, freshness, and LLM judgment, then filters out low-quality sources. Only high-scoring URLs proceed to full scraping.

**Why this priority**: Source curation is important for research-oriented workflows but is a quality enhancement on top of the core retrieval and scraping pipeline. It can be bypassed entirely for workflows that don't need it.

**Independent Test**: Can be fully tested by providing a list of URLs with mixed quality, running the curation pipeline, and verifying that high-quality sources score above the threshold while low-quality sources are filtered out.

**Acceptance Scenarios**:

1. **Given** a list of 20 retriever results and `source_curation.enabled: true`, **When** the curation pipeline runs with `min_score: 0.4`, **Then** URLs scoring below 0.4 are discarded before full scraping.
2. **Given** a domain block list containing `["pinterest.com", "quora.com"]`, **When** results include URLs from those domains, **Then** those URLs receive a domain authority score of 0 regardless of other signals.
3. **Given** content older than `freshness_max_age_days` (default 730), **When** freshness scoring is applied, **Then** that content receives a reduced freshness score.
4. **Given** `source_curation.enabled: false` (or absent), **When** retriever results are returned, **Then** all results proceed directly to scraping with no filtering.
5. **Given** `max_sources: 10`, **When** 15 URLs pass the minimum score threshold, **Then** only the top 10 by score proceed to deep scraping.

---

### User Story 7 - Configure Citation Tracking via Team Config (Priority: P7)

A workflow author enables citation tracking in the team configuration. When enabled, the framework automatically tracks all source URLs accessed during the workflow, generates inline citations in agent output, and assembles a reference section in the final result using the configured style.

**Why this priority**: The CitationTracker and Citation classes already exist and work. This story adds the configuration layer and automatic integration so that workflow authors can enable citations declaratively rather than programmatically.

**Independent Test**: Can be fully tested by adding `citations.enabled: true` to a team config, running a workflow that accesses external sources, and verifying that the ResultPayload contains a reference section in the configured style.

**Acceptance Scenarios**:

1. **Given** a team config with `citations.enabled: true` and `style: "apa"`, **When** the workflow accesses external sources, **Then** the final ResultPayload includes an APA-formatted reference section.
2. **Given** `citations.enabled: false` (or absent), **When** the workflow runs, **Then** no citation-related processing occurs (preserving current default behavior).
3. **Given** `citations.inline: true`, **When** agents produce output referencing sources, **Then** their output includes inline `[source](url)` references.
4. **Given** a workflow that accesses the same URL multiple times, **When** citations are assembled, **Then** the URL appears only once in the reference section (deduplication).

---

### User Story 8 - Load Documents from Cloud Storage and URLs (Priority: P8)

A workflow author provides Azure Blob Storage paths or raw URLs as document inputs. The framework loads content from these sources using the same pipeline as local files — with chunking, token estimation, and agent scoping applied identically.

**Why this priority**: Local file loaders are fully implemented. Cloud and URL loaders extend reach to enterprise and web sources, but are additive and non-blocking for other features.

**Independent Test**: Can be fully tested by providing a cloud storage path or URL, loading it through the DocumentPipeline, and verifying that the output matches the same structure as locally loaded documents.

**Acceptance Scenarios**:

1. **Given** an Azure Blob Storage URL with valid credentials, **When** the DocumentPipeline loads it, **Then** the content is extracted and chunked identically to a local file of the same format.
2. **Given** a public web URL, **When** the URL loader processes it via the scraper pipeline, **Then** the result is a Document object with chunks, token estimates, and source metadata.
3. **Given** an Azure Blob URL with invalid or missing credentials, **When** loading is attempted, **Then** a clear error indicates the authentication issue.
4. **Given** a URL that returns unsupported content, **When** loading is attempted, **Then** the error message identifies the unsupported format.

---

### Edge Cases

- What happens when all configured retrievers fail simultaneously? The framework returns an empty result set with logged errors, not an unhandled exception.
- What happens when a scraper encounters a CAPTCHA or login wall? The content validation check (< 100 chars) catches it, discards the result, and logs a warning.
- What happens when the embedding provider returns vectors with inconsistent dimensions within a batch? The framework rejects the batch with a validation error before storing.
- What happens when a vector store reaches its capacity? The error propagates to the caller with a clear message; the workflow can proceed without vector search by falling back to full content.
- What happens when the source curation pipeline is enabled but no embedding provider is configured? The content relevance signal (which requires embeddings) is skipped, and the remaining three signals (domain authority, freshness, LLM judgment) produce the score with reweighted proportions.
- What happens when two retriever plugins register with the same plugin ID? The later registration overwrites the earlier one, consistent with the existing PluginRegistry behavior.
- What happens when `scrape_batch()` is called with an empty URL list? An empty result list is returned immediately.

## Requirements *(mandatory)*

### Functional Requirements

**Retriever System:**

- **FR-001**: System MUST provide a `RetrieverPlugin` base class with an async `search(query, max_results)` method returning `list[SearchResult]`
- **FR-002**: System MUST provide a `RetrieverRegistry` that discovers retriever plugins via the `hiveflow.retrievers` entry point group
- **FR-003**: System MUST support multi-retriever dispatch — querying all configured retrievers in parallel and deduplicating results by URL
- **FR-004**: System MUST support at least two built-in retriever plugin packages at launch (e.g., Tavily and DuckDuckGo)

**Scraper System:**

- **FR-005**: System MUST provide a `ScraperPlugin` base class with an async `scrape(url)` method returning `ScrapedContent`
- **FR-006**: System MUST provide `scrape_batch()` with configurable concurrency via `asyncio.Semaphore`, defaulting to 15 concurrent operations
- **FR-007**: System MUST support URL-pattern-based scraper routing, selecting specialized scrapers for known URL patterns before falling back to the default
- **FR-008**: System MUST validate scraped content length and discard results with fewer than 100 characters of useful text
- **FR-009**: `scrape_batch()` MUST isolate errors per-URL — a single failure MUST NOT prevent other URLs from being scraped
- **FR-033**: Each scrape operation MUST enforce a configurable per-URL timeout (default: 15 seconds, configurable via `HIVEFLOW_SCRAPER_TIMEOUT`); timed-out URLs MUST return a timeout error without blocking the batch
- **FR-032**: System MUST support at least two built-in scraper plugin packages at launch: a lightweight HTML scraper (BeautifulSoup) and a JavaScript-capable scraper (Playwright)
- **FR-034**: All new plugin types (retriever, scraper, embedding, vector store) MUST use structlog for structured diagnostic logging; StreamChannel events remain reserved for workflow-level progress (agent, step, gate events)

**Embedding Providers:**

- **FR-010**: System MUST provide an `EmbeddingProvider` base class with an async `embed(texts, model)` method returning `list[list[float]]`
- **FR-011**: System MUST provide an `EmbeddingProviderRegistry` that discovers providers via the `hiveflow.embeddings` entry point group
- **FR-012**: Embedding providers MUST automatically split oversized batches based on their `max_batch_size` property
- **FR-013**: System MUST support at least one built-in embedding provider plugin at launch (e.g., OpenAI)

**Vector Stores:**

- **FR-014**: System MUST provide a `VectorStorePlugin` base class with `add()`, `search()`, `delete()`, `clear()`, and `count()` methods
- **FR-015**: System MUST provide a `VectorStoreRegistry` that discovers plugins via the `hiveflow.vector_stores` entry point group
- **FR-016**: System MUST support isolated collection namespaces per workflow run
- **FR-017**: System MUST support both ephemeral (cleaned up on completion) and persistent (survives across runs) collection modes
- **FR-018**: The existing `SimpleVectorStore` MUST be refactored to conform to the `VectorStorePlugin` interface

**Semantic Filtering Pipeline:**

- **FR-019**: System MUST provide an ingestion-time pipeline that chunks content, embeds chunks, filters by cosine similarity, and assembles the result with source attribution
- **FR-020**: The `relevant_chunks` document mode MUST use the semantic filtering pipeline when an embedding provider is configured, instead of falling back to full mode
- **FR-021**: System MUST fall back gracefully to full content when no embedding provider is configured, preserving existing behavior

**Source Curation:**

- **FR-022**: System MUST provide a configurable source curation pipeline with multi-signal scoring (domain authority, content relevance, freshness, LLM judgment)
- **FR-023**: Source curation MUST support configurable domain allow/block lists
- **FR-024**: Source curation MUST be disabled by default and activated via team config (`source_curation.enabled: true`)
- **FR-025**: The curation pipeline MUST perform lightweight snippet scraping before scoring, and only deep-scrape URLs that pass the minimum score threshold

**Citation Enhancements:**

- **FR-026**: System MUST support a `citations` configuration block in the team config with `enabled`, `style`, `inline`, and `generate_reference_section` fields
- **FR-027**: When `citations.enabled` is false or absent, the system MUST skip all citation-related processing (preserving current default)
- **FR-028**: System MUST preserve all existing citation formats (apa, numbered, inline) and add MLA and Chicago as new options
- **FR-029**: System MUST automatically track all URLs accessed during a workflow in a deduplicated `visited_urls` set when citations are enabled

**Document Loading Enhancements:**

- **FR-030**: System MUST provide an Azure Blob Storage document loader discovered via the standard entry point group
- **FR-031**: System MUST provide a URL document loader that uses the scraper pipeline to extract content and wraps it in the standard Document format

### Key Entities

- **SearchResult**: A normalized search result with url, title, content, score, and metadata. Produced by retrievers, consumed by scrapers and the curation pipeline.
- **ScrapedContent**: Extracted web page content with url, title, text, html, and metadata. Produced by scrapers, consumed by the chunking pipeline.
- **EmbeddingProvider**: A plugin that converts text into dense vector representations. Configured per-framework, used by the semantic filtering pipeline and vector stores.
- **VectorStorePlugin**: A plugin that persists and searches vector embeddings. Supports isolated collections per workflow run. Used by the semantic filtering pipeline.
- **SourceCurationPipeline**: A configurable scoring and filtering system that ranks retrieved URLs by credibility before committing to full extraction.
- **CitationConfig**: A team-level configuration block controlling whether citation tracking, inline references, and reference section assembly are active.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Workflow authors can configure at least two different search backends and receive merged, deduplicated results from a single search call
- **SC-002**: Batch scraping of 20 URLs completes with all individual success/failure results reported, and no single failure blocks the batch
- **SC-003**: The semantic filtering pipeline reduces a 50,000-character document to only relevant chunks (typically 20-40% of original size depending on query specificity) while preserving source attribution
- **SC-004**: The `relevant_chunks` document mode produces meaningfully different (smaller, more relevant) output compared to `full` mode when an embedding provider is configured
- **SC-005**: Source curation with a score threshold of 0.4 filters out at least 30% of low-quality sources in a mixed-quality result set, while retaining all high-authority sources
- **SC-006**: Citation tracking, when enabled, produces a correctly formatted reference section for all accessed sources without manual intervention
- **SC-007**: All new plugin types (retriever, scraper, embedding, vector store) are discoverable via entry points and can be installed/swapped without changing framework code
- **SC-008**: Existing workflows that do not configure any new features continue to function identically — no regressions in document loading, context management, or citation behavior

### Assumptions

- Retriever plugins will require external API keys managed by the workflow author (the framework does not manage API key provisioning)
- The `scrape_batch()` concurrency default of 15 is appropriate for most use cases; users who need higher concurrency can adjust via config
- Character-based chunking (current behavior) is retained as the default; token-based chunking may be added as an optional mode in a future iteration
- The existing openpyxl-based Excel loader and PlainTextLoader-based CSV loader remain unchanged; no migration to pandas
- The source curation LLM judgment signal uses the FAST_LLM tier to keep costs low
- Vector store collection cleanup for ephemeral mode is best-effort — if the process crashes, stale collections may remain

## Clarifications

### Session 2026-02-25

- Q: How many built-in scraper plugins must be included at launch? → A: At least two — BeautifulSoup (lightweight HTML) and Playwright (JavaScript-capable), matching the retriever minimum.
- Q: What should the default per-URL scrape timeout be? → A: 15 seconds, configurable via `HIVEFLOW_SCRAPER_TIMEOUT`. Aggressive fast-failure preferred; timed-out URLs return errors without blocking the batch.
- Q: Should new plugin types emit events to StreamChannel or use structlog? → A: structlog only. StreamChannel remains reserved for workflow-level events (agent, step, gate). Plugins use structured logging for diagnostics.
