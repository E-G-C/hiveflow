# Data Model: Data Processing Infrastructure

**Feature**: 006-data-processing-infra
**Date**: 2026-02-25

---

## Entities

### SearchResult (existing — no changes)

Located in `hiveflow/plugins/retrievers/__init__.py`.

| Field      | Type              | Description                        |
| ---------- | ----------------- | ---------------------------------- |
| `title`    | `str`             | Page title                         |
| `url`      | `str`             | Source URL (deduplicated)          |
| `content`  | `str`             | Snippet / description text         |
| `score`    | `float`           | Relevance score (0.0 - 1.0)       |
| `metadata` | `dict[str, Any]`  | Provider-specific metadata         |

**Identity**: Deduplicated by `url` during multi-retriever merge.

---

### ScrapedContent (existing — no changes)

Located in `hiveflow/plugins/scrapers/__init__.py`.

| Field      | Type              | Description                        |
| ---------- | ----------------- | ---------------------------------- |
| `url`      | `str`             | Source URL                         |
| `title`    | `str`             | Page title                         |
| `text`     | `str`             | Extracted clean text               |
| `html`     | `str`             | Raw HTML (optional)                |
| `metadata` | `dict[str, Any]`  | Extraction metadata                |

**Computed property**: `word_count` (approximate word count of `text`).

---

### EmbeddingProvider (existing interface — enhanced)

Located in `hiveflow/plugins/embeddings/__init__.py`.

| Property/Method       | Type/Signature                                      | Status   |
| --------------------- | --------------------------------------------------- | -------- |
| `plugin_id`           | `str`                                               | Existing |
| `description`         | `str`                                               | Existing |
| `max_batch_size`      | `int` (default: 100)                                | Existing |
| `embedding_dimension` | `int` (default: 0)                                  | Existing |
| `embed()`             | `async (texts, model?) -> list[list[float]]`        | Existing |
| `embed_single()`      | `async (text, model?) -> list[float]`               | Existing |
| `estimate_cost()`     | `(num_tokens: int) -> float`                        | **NEW**  |

---

### VectorStorePlugin (new)

To be created in `hiveflow/plugins/vector_stores/__init__.py`.

| Property/Method       | Type/Signature                                              | Description                      |
| --------------------- | ----------------------------------------------------------- | -------------------------------- |
| `plugin_id`           | `str`                                                       | e.g., "memory", "chroma"        |
| `description`         | `str`                                                       | Human-readable description       |
| `add()`               | `async (vectors: list[list[float]], docs: list[dict]) -> None` | Upsert documents with embeddings |
| `search()`            | `async (query_vector: list[float], top_k: int, filters?) -> list[tuple[dict, float]]` | Similarity search |
| `delete()`            | `async (doc_ids: list[str]) -> None`                        | Remove documents by ID           |
| `clear()`             | `async () -> None`                                          | Wipe collection                  |
| `count()`             | `async () -> int`                                           | Number of stored documents       |

**Identity**: Documents identified by `doc_id` field in their metadata dict.
**Lifecycle**: Collections are namespaced by `{collection_prefix}_{session_id}`. Ephemeral collections are cleared on workflow completion. Persistent collections survive across runs.

---

### CitationConfig (new Pydantic model)

To be added in `hiveflow/core/schema.py` as part of `TeamConfiguration`.

| Field                       | Type   | Default | Description                          |
| --------------------------- | ------ | ------- | ------------------------------------ |
| `enabled`                   | `bool` | `False` | Activate citation tracking           |
| `style`                     | `str`  | `"apa"` | Format: apa, numbered, inline, mla, chicago |
| `inline`                    | `bool` | `True`  | Include inline `[source](url)` refs  |
| `generate_reference_section`| `bool` | `True`  | Append reference list to output      |

---

### SourceCurationConfig (new Pydantic model)

To be added in `hiveflow/core/schema.py` as part of `TeamConfiguration`.

| Field                | Type              | Default     | Description                        |
| -------------------- | ----------------- | ----------- | ---------------------------------- |
| `enabled`            | `bool`            | `False`     | Activate source curation           |
| `min_score`          | `float`           | `0.4`       | Minimum composite score            |
| `max_sources`        | `int`             | `10`        | Maximum URLs to deep-scrape        |
| `freshness_max_age_days` | `int`         | `730`       | Penalize content older than this   |
| `domain_allow_list`  | `list[str]`       | `[]`        | Boosted domains                    |
| `domain_block_list`  | `list[str]`       | `[]`        | Zero-score domains                 |
| `scoring_weights`    | `ScoringWeights`  | (see below) | Signal weights                     |

**ScoringWeights** (nested model):

| Field               | Type    | Default |
| ------------------- | ------- | ------- |
| `domain_authority`  | `float` | `0.25`  |
| `content_relevance` | `float` | `0.30`  |
| `freshness`         | `float` | `0.15`  |
| `llm_judgment`      | `float` | `0.30`  |

---

### VectorStoreConfig (new Pydantic model)

To be added in `hiveflow/core/schema.py` as part of `TeamConfiguration`.

| Field               | Type   | Default        | Description                  |
| ------------------- | ------ | -------------- | ---------------------------- |
| `backend`           | `str`  | `"memory"`     | Vector store plugin ID       |
| `collection_prefix` | `str`  | `"workflow_"`  | Namespace prefix             |
| `persist`           | `bool` | `False`        | Survive across workflow runs |
| `similarity_metric` | `str`  | `"cosine"`     | Distance metric              |

---

### SourceScore (internal dataclass)

Used internally by `SourceCurationPipeline`. Not persisted in state.

| Field               | Type    | Description                              |
| ------------------- | ------- | ---------------------------------------- |
| `url`               | `str`   | Source URL                               |
| `domain_authority`  | `float` | 0.0 - 1.0                               |
| `content_relevance` | `float` | Cosine similarity of snippet vs. query   |
| `freshness`         | `float` | Time-decay score (0.0 - 1.0)            |
| `llm_judgment`      | `float` | LLM quality rating normalized to 0.0-1.0|
| `composite_score`   | `float` | Weighted sum of all signals              |

---

## Relationships

```text
TeamConfiguration
├── citations: CitationConfig (optional)
├── source_curation: SourceCurationConfig (optional)
└── vector_store: VectorStoreConfig (optional)

RetrieverRegistry ──uses──> RetrieverPlugin ──produces──> SearchResult
ScraperRegistry ──uses──> ScraperPlugin ──produces──> ScrapedContent

SourceCurationPipeline
├── consumes: list[SearchResult]
├── uses: ScraperPlugin (snippet scraping)
├── uses: EmbeddingProvider (content relevance)
├── uses: LLMProvider (LLM judgment via FAST_LLM)
└── produces: list[SearchResult] (filtered, ranked)

SemanticFilterPipeline
├── consumes: text chunks (from DocumentPipeline)
├── uses: EmbeddingProvider
├── uses: VectorStorePlugin
└── produces: filtered chunks with source attribution

CitationTracker
├── consumes: URLs from retrievers/scrapers
├── produces: visited_urls set in state
└── produces: reference section in ResultPayload
```

---

## State Additions

New optional keys added to workflow state when features are enabled:

| Key             | Type        | Set by              | Condition             |
| --------------- | ----------- | ------------------- | --------------------- |
| `visited_urls`  | `set[str]`  | Workflow engine      | When `citations.enabled` |
