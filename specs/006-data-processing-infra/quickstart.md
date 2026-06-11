# Quickstart: Data Processing Infrastructure

**Feature**: 006-data-processing-infra
**Date**: 2026-02-25

---

## Minimal Working Example

### 1. Configure a retriever and run a search

```yaml
# team_config.yaml
retrievers:
  - tavily
```

```python
from hiveflow.plugins.retrievers import RetrieverRegistry

registry = RetrieverRegistry()
results = await registry.search_all("best practices for async Python", max_results=5)

for r in results:
    print(f"[{r.score:.2f}] {r.title} — {r.url}")
```

### 2. Scrape content from search results

```python
from hiveflow.plugins.scrapers import ScraperPlugin

scraper = ScraperPlugin()  # uses default (beautifulsoup)
urls = [r.url for r in results]
scraped = await scraper.scrape_batch(urls, max_concurrent=15)

for item in scraped:
    if isinstance(item, Exception):
        print(f"Error: {item}")
    else:
        print(f"{item.title}: {len(item.text)} chars")
```

### 3. Embed text chunks and search by similarity

```python
from hiveflow.plugins.embeddings import EmbeddingProviderRegistry
from hiveflow.plugins.vector_stores import VectorStoreRegistry

# Embed
emb_registry = EmbeddingProviderRegistry()
provider, model = emb_registry.resolve_model("openai:text-embedding-3-small")

texts = ["chunk 1 text...", "chunk 2 text...", "chunk 3 text..."]
vectors = await provider.embed(texts, model=model)

# Store
vs_registry = VectorStoreRegistry()
store = vs_registry.get_or_raise("memory")
docs = [{"doc_id": f"chunk-{i}", "text": t} for i, t in enumerate(texts)]
await store.add(vectors, docs)

# Search
query_vec = await provider.embed_single("What is async Python?", model=model)
results = await store.search(query_vec, top_k=3)

for doc, score in results:
    print(f"[{score:.3f}] {doc['text'][:80]}...")
```

### 4. Enable source curation (optional)

```yaml
# team_config.yaml
source_curation:
  enabled: true
  min_score: 0.4
  max_sources: 10
  domain_block_list:
    - pinterest.com
    - quora.com
```

### 5. Enable citation tracking (optional)

```yaml
# team_config.yaml
citations:
  enabled: true
  style: apa
  inline: true
  generate_reference_section: true
```

---

## Key Integration Points

| Component | Where | What changes |
|-----------|-------|--------------|
| Team config schema | `hiveflow/core/schema.py` | Add `CitationConfig`, `SourceCurationConfig`, `VectorStoreConfig` models |
| Document pipeline | `hiveflow/core/documents.py` | `relevant_chunks` mode uses embedding pipeline instead of falling back to `full` |
| Workflow engine | `hiveflow/core/workflow.py` | `visited_urls` tracking when citations enabled |
| Citation formatter | `hiveflow/core/citations.py` | Add MLA + Chicago styles; config-driven activation |
| Source curation | `hiveflow/core/source_curation.py` | NEW module: multi-signal scoring pipeline |
| Vector store plugins | `hiveflow/plugins/vector_stores/` | NEW plugin type: `VectorStorePlugin` + `MemoryVectorStore` |
| Retriever impls | `hiveflow/plugins/retrievers/` | NEW: `TavilyRetriever`, `DuckDuckGoRetriever` |
| Scraper impls | `hiveflow/plugins/scrapers/` | NEW: `BS4Scraper`, `PlaywrightScraper` |
| Embedding impl | `hiveflow/plugins/embeddings/` | NEW: `OpenAIEmbeddingProvider` |
| Document loaders | `hiveflow/plugins/documents/` | NEW: `AzureBlobLoader`, `URLLoader` |

## Dependencies (pyproject.toml extras)

```toml
[project.optional-dependencies]
retrieval = [
    "tavily-python",
    "duckduckgo-search>=7.1.0",
]
scraping = [
    "beautifulsoup4>=4.12.0",
    "playwright>=1.40.0",
]
embeddings = [
    "numpy>=2.2.0",
]
documents-azure = [
    "azure-storage-blob>=12.20.0",
    "aiohttp>=3.9.0",
]
```

## Entry Points

```toml
[project.entry-points."hiveflow.retrievers"]
tavily = "hiveflow.plugins.retrievers.tavily_retriever:TavilyRetriever"
duckduckgo = "hiveflow.plugins.retrievers.duckduckgo_retriever:DuckDuckGoRetriever"

[project.entry-points."hiveflow.scrapers"]
beautifulsoup = "hiveflow.plugins.scrapers.bs4_scraper:BS4Scraper"
playwright = "hiveflow.plugins.scrapers.playwright_scraper:PlaywrightScraper"

[project.entry-points."hiveflow.embeddings"]
openai = "hiveflow.plugins.embeddings.openai_embeddings:OpenAIEmbeddingProvider"

[project.entry-points."hiveflow.vector_stores"]
memory = "hiveflow.plugins.vector_stores.memory_store:MemoryVectorStore"
```
