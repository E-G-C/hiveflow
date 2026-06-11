# Research: Data Processing Infrastructure

**Feature**: 006-data-processing-infra
**Date**: 2026-02-25

---

## R1. Tavily Python SDK

**Decision**: Use `tavily-python` package with `AsyncTavilyClient`.

**Rationale**: Official SDK with full async parity. Result fields (`title`, `url`, `content`, `score`) map 1:1 to hiveflow's `SearchResult` contract. Lightweight, MIT licensed.

**Key details**:
- Package: `tavily-python` (needs adding to `retrieval` extras in pyproject.toml)
- Async: `from tavily import AsyncTavilyClient`
- Search params: `query`, `max_results` (0-20), `search_depth`, `include_domains`/`exclude_domains`
- Result fields: `title`, `url`, `content`, `score`, optional `raw_content`, `published_date`
- Auth: API key via constructor

**Alternatives**: SerpAPI (expensive), direct HTTP (unnecessary given SDK exists)

---

## R2. DuckDuckGo Search Python

**Decision**: Use `duckduckgo-search` package, wrap sync API with `asyncio.to_thread()`.

**Rationale**: Already in pyproject.toml (`retrieval` extras). No native async — must be wrapped. Result fields need mapping (`href` -> `url`, `body` -> `content`). No `score` field — assign synthetic scores by result position.

**Key details**:
- Package: `duckduckgo-search>=7.1.0` (already in pyproject.toml)
- API: `DDGS().text(keywords, max_results=N)` — returns list of dicts
- Result fields: `title`, `href`, `body`
- Async: `await asyncio.to_thread(ddgs.text, ...)`
- No score: use `1.0 - (index * 0.05)` for positional scoring

**Alternatives**: googlesearch-python (less maintained), Brave Search (requires API key)

---

## R3. BeautifulSoup4 Scraping

**Decision**: Use BS4 with `html.parser`, pattern already established in `HTMLLoader`.

**Rationale**: Existing `html_loader.py` demonstrates the exact decompose/extract pattern. Reuse the same approach in the scraper plugin. Pure Python parser (no lxml dependency).

**Key details**:
- Remove: `script`, `style`, `nav`, `footer`, `header`, `aside`, `iframe`, `form`
- Extract: `<main>` or `<article>` or `<body>` or root
- Text: `get_text(separator="\n", strip=True)`
- Title: `soup.find("title").get_text(strip=True)` if present
- Fetch: httpx async client with timeout

**Alternatives**: readability-lxml (good fallback, adds lxml dep), trafilatura (heavier than needed)

---

## R4. Playwright Async Scraping

**Decision**: Use Playwright async API, Chromium only, `networkidle` wait, shared browser context.

**Rationale**: Natural fit for async-first design. Handles JS-rendered pages. Already in pyproject.toml and mypy overrides.

**Key details**:
- API: `async_playwright()` context manager → `chromium.launch(headless=True)` → context → page
- Wait: `page.goto(url, wait_until="networkidle", timeout=15000)`
- Extract: `await page.inner_text("body")` for visible text
- Title: `await page.title()`
- Resource management: One browser instance, one context, new page per URL, close page after extraction
- Concurrency: Limit 5-10 concurrent pages per browser (each page ~50-100MB)
- **Requires**: `playwright install chromium` after package install (~150MB)
- Error handling: Lazy import with clear error message for missing package or binaries

**Alternatives**: Selenium (older, no async), pyppeteer (less maintained)

---

## R5. OpenAI Embeddings API

**Decision**: Use openai SDK (existing core dependency) with `AsyncOpenAI`, model `text-embedding-3-small`.

**Rationale**: SDK already a core dependency. Async client available. Straightforward embedding API.

**Key details**:
- Client: `AsyncOpenAI()` — uses `OPENAI_API_KEY` env var
- Call: `await client.embeddings.create(model="text-embedding-3-small", input=[texts])`
- Model: `text-embedding-3-small` — 1536 dims, max 8191 tokens/item, ~$0.02/1M tokens
- Batch limit: 2048 items per API call (hiveflow `max_batch_size` defaults to 100)
- Response: `response.data[i].embedding` (list[float]), `response.usage.total_tokens`
- Dimension reduction: Optional `dimensions` param to shrink vectors (tradeoff: smaller/faster vs. slight quality loss)

**Alternatives**: Cohere (future plugin), HuggingFace local (future plugin), Ollama (future plugin)

---

## R6. Cosine Similarity with NumPy

**Decision**: Use numpy for vectorized batch cosine similarity. Keep pure Python fallback for when numpy is not installed.

**Rationale**: 100-1000x speedup over existing pure-Python `_cosine_similarity()`. numpy already in `embeddings` extras. Memory is reasonable: 10K vectors at 1536 dims = ~59MB.

**Key details**:
- Batch pattern: normalize query, normalize matrix, matrix multiply
- Memory: float32 — 10K×1536 = ~59MB, 50K×1536 = ~293MB
- Top-k: `np.argpartition` in O(n) vs. O(n log n) for full sort
- Fallback: Keep existing pure-Python path for when numpy is not available
- Already in deps: `numpy>=2.2.0` in `embeddings` extras

**Alternatives**: scikit-learn (heavier import, unnecessary), FAISS (future plugin for 100K+)

---

## R7. Azure Blob Storage SDK

**Decision**: Use `azure-storage-blob` with async API (`azure.storage.blob.aio`). Support `DefaultAzureCredential` and connection string auth.

**Rationale**: Full async parity. `azure-identity` already available via `llm-azure` extras. Standard URL parsing extracts container/blob from Azure blob URLs.

**Key details**:
- Package: `azure-storage-blob>=12.20.0` (new extras group: `documents-azure`)
- Async: `from azure.storage.blob.aio import BlobClient`
- Auth: `DefaultAzureCredential` (AAD), connection string, SAS token in URL, account key
- URL format: `https://<account>.blob.core.windows.net/<container>/<blob_path>`
- Download: `stream = await blob.download_blob(); data = await stream.readall()`
- Format detection: File extension from blob path
- Requires: `aiohttp>=3.9.0` for async transport

**Alternatives**: S3 (different cloud, future plugin), GCS (future plugin), httpx (no AAD auth)

---

## R8. Playwright Browser Installation

**Decision**: Lazy detection with helpful error message. Do NOT auto-install binaries.

**Rationale**: Browser binaries are ~150MB. Auto-downloading in a library context is inappropriate. Follows existing hiveflow pattern for optional dependencies (lazy import with `ImportError` catch).

**Key details**:
- Required step: `playwright install chromium` (~150MB download)
- Detection: Try/catch on `browser_type.launch()` — Playwright already provides a descriptive error
- Error message pattern: `"playwright install chromium" required for JS-capable scraping`
- Version coupling: Each Playwright package version requires matching browser binaries
- Existing precedent: `html_loader.py` uses same lazy-import pattern for optional deps

**Alternatives**: Auto-install on first use (bad UX, security concern), CLI command (unnecessary complexity)
