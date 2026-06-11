[< Back to Index](README.md)

---

## State Management

Each workflow needs a flexible state container. Rather than hardcoded TypedDicts,
the framework uses:

- A **generic dictionary-based state** (`dict[str, Any]`) that flows between
  agents, with an optional `WorkflowState` wrapper that adds history tracking
- An optional **state schema** declared in the team config (documenting which
  keys each agent reads and writes), with enforcement modes: `off` (default),
  `warn`, or `strict`
- **Immutable state merging** between steps (consistent with the pattern of
  `{**prev_state, **new_output}`)

### Extended State for Action-Oriented Workflows

For workflows that perform real-world actions, the state includes agent-prefixed
keys to ensure isolation when multiple agents of the same type coexist:

- **`{agent_id}_action_records`** — A log of all side effects executed by that
  agent, stored as `ActionRecord` dataclass instances
- **`{agent_id}_proposed_actions`** — Actions pending human approval before
  execution
- **`awaiting_action_approval`** — Boolean flag indicating the workflow is
  paused for action approval
- **`awaiting_gate_approval`** — Boolean flag indicating the workflow is paused
  at a gated step
- **`pending_gate_id`** / **`pending_gate_description`** — Identifies which gate
  is awaiting approval
- **`resume_responses`** — Human approval decisions injected on resume

Rollback is configured per-agent via `rollback_on_failure` and `rollback_action`
in the `AgentDefinition`, not tracked as a state-level stack.

```json
{
  "task": "Deploy API v2 to staging",
  "plan": { "steps": ["build", "test", "deploy", "verify"] },
  "builder_output": "Image api:v2.0.1 built successfully",
  "tester_output": "142 passed, 0 failed",
  "deployer_action_records": [
    {
      "action_id": "a1", "action_type": "api_call",
      "description": "docker_build", "status": "completed",
      "agent_id": "deployer", "reversible": true,
      "rollback_action": "rollback_deploy"
    },
    {
      "action_id": "a2", "action_type": "api_call",
      "description": "deploy_staging", "status": "completed",
      "agent_id": "deployer", "reversible": true
    }
  ],
  "awaiting_gate_approval": false,
  "resume_responses": {
    "deploy_approval": true
  }
}
```

### Additional Workflow State Keys

The engine manages several internal state keys:

| Key | Type | Purpose |
|-----|------|---------|
| `_step_order` | `list[str]` | Tracks agent execution order |
| `_context_ttl` | `dict[str, int]` | Per-agent context time-to-live counters |
| `{agent_id}_output` | `str` | Agent's primary text output |
| `{agent_id}_outputs` | `list` | Collected outputs from parallel fan-out |
| `{agent_id}_summary` | `str` | LLM-generated summary of agent output |
| `{agent_id}_summaries` | `dict` | Per-item summaries from parallel execution |
| `{agent_id}_outline` | `str` | Cross-cutting outline from multiple summaries |
| `{agent_id}_approved` / `_rejected` | `bool` | Gate/conditional approval flags |
| `parallel_items` / `current_item` / `item_index` | various | Parallel fan-out tracking |
| `final_output` | `str` | Assembled output from divide-and-conquer workflows |

---

## Data Processing Infrastructure

The framework provides composable, pluggable data processing components beneath
the agent layer.

### Retriever System (Search Backends)

Retrievers are tool plugins that execute search queries and return a normalized
result set. The framework supports **multi-retriever orchestration** via
`RetrieverRegistry.search_all()` — querying multiple search engines in parallel,
deduplicating results by URL, and sorting by score.

**Retriever result contract** (`SearchResult` class):

```json
[{
  "url": "https://...",
  "title": "Page Title",
  "content": "Snippet text...",
  "score": 0.85,
  "metadata": {}
}]
```

**Plugin interface** (`RetrieverPlugin`, discovered via `hiveflow.retrievers`
entry point group):

```
RetrieverPlugin(BasePlugin)
├── plugin_id: str                                    # e.g. "tavily", "duckduckgo"
├── description: str
└── search(query, max_results=10) -> list[SearchResult]  # async
```

**Built-in retriever plugins:**

| Retriever     | Package                   | API                    |
| ------------- | ------------------------- | ---------------------- |
| Google Search | `hiveflow-ret-google`     | Google Custom Search   |
| Bing Search   | `hiveflow-ret-bing`       | Bing Web Search API    |
| ArXiv         | `hiveflow-ret-arxiv`      | ArXiv API              |
| DuckDuckGo    | `hiveflow-ret-duckduckgo` | DuckDuckGo instant     |
| Tavily        | `hiveflow-ret-tavily`     | Tavily Search API      |
| MCP Retriever | `hiveflow-ret-mcp`        | Model Context Protocol |

**Multi-retriever dispatch:** The config specifies one or more retrievers via
`HIVEFLOW_RETRIEVERS` (comma-separated, default: `"tavily"`). The
`RetrieverRegistry.search_all()` method queries all in parallel, deduplicates by
URL, and returns results sorted by score descending.

### Scraper System (Content Extraction)

Scrapers are tool plugins that extract content from URLs. The framework selects
the appropriate scraper based on URL patterns.

**Scraper result contract** (`ScrapedContent` class):

```json
{
  "url": "https://...",
  "title": "Page Title",
  "text": "Extracted content...",
  "html": "<raw html if available>",
  "metadata": {}
}
```

**Plugin interface** (`ScraperPlugin`, discovered via `hiveflow.scrapers` entry
point group):

```
ScraperPlugin(BasePlugin)
├── plugin_id: str                                    # e.g. "beautifulsoup", "playwright"
├── description: str
├── supports_javascript: bool                         # default: False
├── scrape(url) -> ScrapedContent                     # async
└── scrape_batch(urls, max_concurrent=15) -> list[ScrapedContent | Exception]  # async
```

**URL-pattern routing:**

| URL Pattern     | Scraper                                         | Reason                       |
| --------------- | ----------------------------------------------- | ---------------------------- |
| `*.pdf`         | PyMuPDF                                         | Native PDF parsing           |
| `arxiv.org/*`   | ArXiv scraper                                   | Structured academic metadata |
| Everything else | Configured default (BeautifulSoup / Playwright) | General web pages            |

**Scraping infrastructure concerns:**

- **Worker pool** — configurable via `HIVEFLOW_MAX_SCRAPER_WORKERS` (default:
  15); `scrape_batch()` uses an `asyncio.Semaphore` for concurrency control
- **Rate limiting** — configurable via `HIVEFLOW_SCRAPER_RATE_LIMIT_DELAY`
  (default: 0.1s)
- **Error isolation** — `scrape_batch()` uses `asyncio.gather(return_exceptions=True)`;
  failures are returned as exceptions, never crash the pipeline
- **Content validation** — minimum content length threshold (discard pages with
  < 100 chars of useful text)
- **HTML cleaning** — strip navigation, ads, scripts; extract main content
- **Image extraction** — optionally extract and deduplicate images (content
  hash-based), with relevance scoring

### Context Compression

The framework provides **two complementary context compression systems** for
different stages of the pipeline:

#### 1. Ingestion-Time: Embedding-Based Semantic Filtering

For raw scraped or retrieved content that is too large to pass directly to an
LLM, the framework applies a chunking-and-filtering pipeline:

1. **Text splitting** — Character-level recursive splitter with configurable
   `chunk_size` (default: 1000 characters, `HIVEFLOW_BROWSE_CHUNK_MAX_LENGTH`)
   and `chunk_overlap` (default: 200 characters, `HIVEFLOW_CHUNK_OVERLAP`).
   Split boundaries: `\n\n` → `\n` → `. ` → ` ` → `""`
2. **Embedding** — Chunks are embedded using a configurable embedding provider
   (`HIVEFLOW_EMBEDDING_PROVIDER`, `HIVEFLOW_EMBEDDING_MODEL`)
3. **Similarity filtering** — Cosine similarity against the query embedding;
   configurable `similarity_threshold` (default: 0.35,
   `HIVEFLOW_SIMILARITY_THRESHOLD`)
4. **Context assembly** — Passing chunks are assembled into the context with
   source attribution

> **Current status:** The `DocumentPipeline` implements character-based chunking.
> The `relevant_chunks` agent document mode is defined but falls back to `full`
> mode until an embedding provider is configured. Token estimation uses the
> `word_count / 0.75` approximation.

#### 2. Runtime: LLM-Based Intelligent Context Reduction

During workflow execution, accumulated agent context is compressed by the
`ContextReducer` — an LLM-based waste classification system inspired by
AgentDiet's trajectory reduction approach:

1. **Overflow detection** — Triggers only when context exceeds
   `budget * overflow_threshold` (default: 1.5x)
2. **LLM reflection** — Uses the FAST_LLM tier to classify and remove waste:
   - **USELESS:** Irrelevant metadata, verbose boilerplate, debug traces,
     repeated headers
   - **REDUNDANT:** Information that appears multiple times across sections
   - **EXPIRED:** Context from earlier steps fully superseded by later outputs
3. **Preservation rules** — Key facts, decisions, requirements, action items,
   and task descriptions are kept; removed content is replaced with brief
   placeholders (e.g., `[earlier research incorporated above]`)
4. **Mechanical fallback** — If LLM reduction still exceeds budget, word-level
   truncation with a `[truncated to fit context budget]` marker

Additionally, the `SummaryGenerator` provides differential compression between
workflow steps:

- Default summary budget: ~200 tokens (configurable via
  `HIVEFLOW_MAX_SUMMARY_LENGTH`)
- **Output-type multipliers:** Reasoning outputs get 2x budget; data/side-effect
  outputs get 0.5x budget
- **Outline assembly:** Combines multiple agent summaries into a cross-cutting
  outline (budget: `HIVEFLOW_MAX_OUTLINE_LENGTH`, default 1000 tokens)
- **Threshold activation:** Summaries are skipped when text is below
  `HIVEFLOW_SUMMARY_THRESHOLD` words
- **Recency windowing:** `HIVEFLOW_CONTEXT_RECENCY_WINDOW` controls how many
  recent agent summaries remain full (0 = no limit)

### Embedding Provider System

Embeddings power similarity search throughout the framework. The embedding
client follows the same **plugin architecture** as LLM providers — each is an
independently installable package discovered via the `hiveflow.embeddings`
entry point group.

**Embedding provider interface (async-first):**

```
EmbeddingProvider(BasePlugin)
├── plugin_id: str                                       # e.g. "openai", "ollama"
├── description: str
├── max_batch_size: int                                  # default: 100
├── embedding_dimension: int                             # default: 0 (set by provider)
├── embed(texts: list[str], model=None) -> list[vector]  # async batch embed
├── embed_single(text: str, model=None) -> vector        # async convenience wrapper
└── estimate_cost(num_tokens: int) -> float              # cost estimation (enhancement)
```

The `EmbeddingProviderRegistry` supports model resolution via `provider:model`
format (e.g., `openai:text-embedding-3-small`).

**Built-in embedding provider plugins:**

| Provider | Package | Notes |
|---|---|---|
| OpenAI | `hiveflow-emb-openai` | Default; `text-embedding-3-small` |
| Azure OpenAI | `hiveflow-emb-azure` | Enterprise deployments |
| Cohere | `hiveflow-emb-cohere` | Alternative commercial |
| Ollama | `hiveflow-emb-ollama` | Local/self-hosted |
| HuggingFace | `hiveflow-emb-huggingface` | Open-source models; runs locally |
| Google | `hiveflow-emb-google` | Vertex AI embeddings |
| Together | `hiveflow-emb-together` | Cloud-hosted open-source models |
| Voyage | `hiveflow-emb-voyage` | High-quality retrieval embeddings |

Configuration: `HIVEFLOW_EMBEDDING_PROVIDER=openai`,
`HIVEFLOW_EMBEDDING_MODEL=text-embedding-3-small`

### Vector Store System

The framework provides a **pluggable vector store** for similarity search over
embedded documents. A basic `SimpleVectorStore` (in-memory, cosine similarity)
is included for development; production deployments should use a proper vector
database plugin.

**Current in-memory implementation** (`SimpleVectorStore` in
`hiveflow.plugins.embeddings`):

```
SimpleVectorStore
├── add(vectors: list[list[float]], documents: list[dict]) -> None
├── search(query_vector, top_k=5) -> list[tuple[dict, float]]
├── clear() -> None
└── size: int (property)
```

**Target plugin interface** (discovered via `hiveflow.vector_stores` entry point
group):

```
VectorStorePlugin(BasePlugin)
├── plugin_id: str                                      # e.g. "memory", "chroma", "qdrant"
├── description: str
├── add(vectors, documents) -> None                     # upsert documents with embeddings
├── search(query_vector, top_k, filters=None) -> list[tuple[dict, float]]
├── delete(doc_ids: list[str]) -> None                  # remove documents
├── clear() -> None                                     # wipe the collection
└── count() -> int                                      # number of stored documents
```

**Built-in vector store plugins:**

| Backend      | Package                   | Notes                                         |
| ------------ | ------------------------- | --------------------------------------------- |
| **In-Memory** | `hiveflow-vs-memory`     | Default; cosine similarity; no persistence     |
| **ChromaDB** | `hiveflow-vs-chroma`     | Lightweight embedded DB; good for local dev    |
| **FAISS**    | `hiveflow-vs-faiss`      | Facebook AI; fast CPU/GPU similarity search    |
| **Qdrant**   | `hiveflow-vs-qdrant`     | Production-grade; filtering, payload storage   |
| **Pinecone** | `hiveflow-vs-pinecone`   | Managed cloud; zero-ops                        |
| **Weaviate** | `hiveflow-vs-weaviate`   | Hybrid search (vector + keyword)               |
| **pgvector** | `hiveflow-vs-pgvector`   | PostgreSQL extension; reuse existing infra     |

**Collection lifecycle:**

- Each workflow run creates an **isolated collection** (namespace) so parallel
  runs don't interfere
- Collections can be configured for **persistence** (survive across runs for
  incremental work) or **ephemeral** (cleaned up on completion)

```json
{
  "vector_store": {
    "backend": "chroma",
    "collection_prefix": "workflow_",
    "persist": true,
    "similarity_metric": "cosine"
  }
}
```

Discovery uses the `hiveflow.vector_stores` entry point group.

### Document Loading (Multi-Format Ingestion)

The `DocumentPipeline` orchestrates document loading, chunking, and state
injection. Each format is handled by a `DocumentLoaderPlugin` discovered via the
`hiveflow.document_loaders` entry point group. The registry supports **fallback
loader chains** — if a primary loader fails, the next matching loader is tried
automatically.

**Implemented loaders:**

| Format      | Loader             | Library           |
| ----------- | ------------------ | ----------------- |
| PDF         | `PDFLoader`        | PyMuPDF           |
| DOCX        | `DocxLoader`       | python-docx       |
| TXT, LOG    | `PlainTextLoader`  | Built-in          |
| MD          | `MarkdownLoader`   | Built-in          |
| PPTX        | `PptxLoader`       | python-pptx       |
| XLSX, XLS   | `ExcelLoader`      | openpyxl          |
| CSV, TSV    | `PlainTextLoader`  | Built-in          |
| HTML, HTM   | `HTMLLoader`       | Built-in          |
| JSON        | `JSONLoader`       | Built-in          |
| XML         | `XMLLoader`        | Built-in          |
| **Any**     | `MarkItDownLoader` | Microsoft MarkItDown (universal fallback) |

**Planned loaders** (not yet implemented):

| Format      | Loader             | Library           |
| ----------- | ------------------ | ----------------- |
| Azure Blob  | `AzureBlobLoader`  | Azure SDK         |
| URLs        | `URLLoader`        | Scraper pipeline  |

**Pipeline features:**

- **Path security:** Validates paths against traversal attacks and an optional
  allowed-paths whitelist
- **Size limits:** Enforces a configurable total byte limit (default: 50 MB)
- **Chunking:** Character-based splitting via `chunk_text()` with configurable
  `chunk_size` (default: 1000) and `chunk_overlap` (default: 200)
- **Token estimation:** Approximation via `word_count / 0.75`
- **Agent scoping:** `scope_for_agent()` filters documents per agent's
  `document_mode` (`none`, `metadata_only`, `full`, `relevant_chunks`, `summary`)
  and `max_document_tokens` budget

Document loaders feed into the same chunking → embedding → vector store pipeline
used for web content (once embedding providers are configured).

### Source Citation & Reference Tracking (Optional)

For workflows that involve external sources (research, analysis, data
gathering), the framework **optionally** supports source tracking and citation
via the `CitationTracker` and `Citation` classes. This feature is **not enabled
by default** — it is activated by creating a `CitationTracker` instance and
passing citations to the `ResultPayload`.

**Citation model** (`Citation` dataclass):

| Field | Type | Description |
|-------|------|-------------|
| `url` | `str` | Source URL |
| `title` | `str` | Source title |
| `content_snippet` | `str` | First 500 chars of content |
| `author` | `str` | Author name |
| `date` | `str` | Publication date |
| `source_type` | `str` | `"web"`, `"academic"`, `"document"`, `"api"` |
| `metadata` | `dict` | Additional metadata |
| `citation_id` | `str` (computed) | Stable 8-char MD5 hash of URL |

**CitationTracker features:**

- **Deduplication** by URL
- **Convenience methods:** `add_from_search_result(title, url, content)`
- **Lookup:** By URL or by citation_id
- **Reference formatting** via `format_references(style)`:
  - `"apa"` — APA-style bullet list (default)
  - `"numbered"` — Numbered reference list
  - `"inline"` — References prefixed with `[citation_id]`
- **State export:** `to_state_dict()` for workflow state persistence
- **ResultPayload integration:** Citations stored as `references` in the final
  `ResultPayload`

**Enhancement: Citation configuration in team config:**

```json
{
  "citations": {
    "enabled": false,
    "style": "apa",
    "inline": true,
    "generate_reference_section": true
  }
}
```

When `citations.enabled` is `false` (the default), the framework skips all
citation-related prompt injection, reference tracking, and reference section
assembly.

**Enhancement: Additional citation styles** (MLA, Chicago) to be added alongside
the existing apa, numbered, and inline formats.

**Enhancement: `visited_urls` tracking** — A deduplicated set of all URLs
accessed during the workflow, assembled automatically for reference sections.

---

## Source Curation & Credibility Ranking

Not all sources are equal. Before raw content enters the context window, the
framework **ranks source quality** so that high-credibility material is
prioritized and low-quality content is filtered out.

### Multi-Signal Scoring

Each retrieved URL is scored on multiple dimensions:

| Signal               | Method                                    | Weight (default) |
| -------------------- | ----------------------------------------- | ---------------- |
| **Domain authority**  | Maintain a configurable allow/block list; boost `.edu`, `.gov`, known journals | 0.25 |
| **Content relevance** | Cosine similarity of page content vs. the query | 0.30 |
| **Freshness**         | Penalize content older than a configurable threshold (e.g., 2 years) | 0.15 |
| **LLM judgment**      | Ask the FAST_LLM to rate source quality on a 1–10 scale given a snippet | 0.30 |

### LLM-Based Source Ranking Pipeline

1. **Retrieve** — Multi-retriever returns raw URL list (via
   `RetrieverRegistry.search_all()`)
2. **Scrape snippet** — Fetch the first ~500 chars from each URL (lightweight
   scrape)
3. **Score** — Apply the multi-signal scoring model
4. **Filter** — Discard URLs below a configurable threshold (default: 0.4)
5. **Rank** — Sort remaining URLs by score; take the top N (configurable,
   default: 10, aligned with `HIVEFLOW_MAX_SEARCH_RESULTS_PER_QUERY`)
6. **Deep scrape** — Only the surviving URLs proceed to full content extraction

### Configuration

```json
{
  "source_curation": {
    "enabled": true,
    "min_score": 0.4,
    "max_sources": 10,
    "freshness_max_age_days": 730,
    "domain_allow_list": [".edu", ".gov", "nature.com", "arxiv.org"],
    "domain_block_list": ["pinterest.com", "quora.com"],
    "scoring_weights": {
      "domain_authority": 0.25,
      "content_relevance": 0.30,
      "freshness": 0.15,
      "llm_judgment": 0.30
    }
  }
}
```

---

---

[Next: Integrations >](06-integrations.md)
