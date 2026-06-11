# Data Processing Examples

Examples demonstrating HiveFlow's data processing infrastructure -- retrievers,
scrapers, embeddings, vector stores, semantic filtering, source curation,
citations, and cloud/URL document loading.

## Examples

| # | Script | What it shows | LLM? |
|---|--------|---------------|:----:|
| 01 | `01_retriever_search.py` | Multi-retriever search with deduplication | No |
| 02 | `02_scraper_pipeline.py` | Web scraping with routing and validation | No |
| 03 | `03_embeddings_similarity.py` | Embeddings, vector store, similarity search | Yes (Azure) |
| 04 | `04_semantic_filtering.py` | Semantic filtering of document chunks | Yes (Azure) |
| 05 | `05_source_curation.py` | Source credibility scoring and filtering | No |
| 06 | `06_citations.py` | Citation tracking with MLA/Chicago/APA styles | No |
| 07 | `07_research_workflow.py` | Full pipeline: retrieve, scrape, curate, embed, cite | Yes (Azure) |
| 08 | `source_mode_routing.py` | Source mode tool filtering (web/local/hybrid/cloud/mcp/custom) | No |

## Running

```bash
# No-LLM examples (pure data pipeline):
uv run python examples/data_processing/01_retriever_search.py
uv run python examples/data_processing/02_scraper_pipeline.py
uv run python examples/data_processing/05_source_curation.py
uv run python examples/data_processing/06_citations.py

# With Azure OpenAI embeddings:
uv run python examples/data_processing/03_embeddings_similarity.py
uv run python examples/data_processing/04_semantic_filtering.py

# Full end-to-end pipeline (Azure OpenAI):
uv run python examples/data_processing/07_research_workflow.py
```

## Prerequisites

- **Examples 01, 02, 05, 06**: No API keys required
- **Examples 03, 04, 07**: Azure OpenAI access via DefaultAzureCredential (Entra ID RBAC)
  - Endpoint: `https://foundry-aisbx-we.cognitiveservices.azure.com`
  - Or set `AZURE_OPENAI_ENDPOINT` environment variable

## Key Concepts

- **RetrieverPlugin** -- pluggable search backends (Tavily, DuckDuckGo)
- **ScraperPlugin** -- content extraction (BS4, Playwright) with routing
- **EmbeddingProvider** -- text-to-vector conversion (OpenAI)
- **VectorStorePlugin** -- similarity search (MemoryVectorStore)
- **SourceCurationPipeline** -- multi-signal credibility scoring
- **CitationTracker** -- APA, MLA, Chicago, numbered, inline citation styles
- **ScraperRouter** -- URL-pattern-based scraper selection
- **CollectionManager** -- workflow-scoped vector namespacing
- **SourceModeRouter** -- filters agent tools by data-source category (web, local, hybrid, cloud, mcp, custom)
