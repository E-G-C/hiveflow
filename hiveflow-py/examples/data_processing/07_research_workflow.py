#!/usr/bin/env python3
"""Data Processing 07: Full research pipeline -- retrieve, curate, scrape, embed, cite.

Demonstrates the complete data processing pipeline end-to-end:
  1. Search multiple retrievers for a research topic
  2. Score and filter sources via the curation pipeline
  3. Scrape full content from curated URLs
  4. Embed content chunks and store in a vector store
  5. Perform semantic similarity search
  6. Track citations and generate a formatted reference section

Uses mock retrievers/scrapers (no web access needed).
Uses Azure OpenAI for embeddings via DefaultAzureCredential.

Usage:
    uv run python examples/data_processing/07_research_workflow.py
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hiveflow.core.citations import Citation, CitationTracker
from hiveflow.core.source_curation import SourceCurationPipeline
from hiveflow.plugins.retrievers import RetrieverPlugin, RetrieverRegistry, SearchResult
from hiveflow.plugins.scrapers import ScrapedContent, ScraperPlugin, validate_scraped_content
from hiveflow.plugins.vector_stores import CollectionManager
from hiveflow.plugins.vector_stores.memory_store import MemoryVectorStore

# AZURE_ENDPOINT = "https://foundry-aisbx-we.cognitiveservices.azure.com"
AZURE_ENDPOINT = "https://127.0.0.1:4000/v1"  # For local testing with Azure OpenAI emulator
EMBEDDING_MODEL = "text-embedding-3-small"


def print_section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}\n")


# --- Mock implementations (simulate external services) ---


class MockRetrieverA(RetrieverPlugin):
    @property
    def plugin_id(self) -> str:
        return "search_engine_a"

    @property
    def description(self) -> str:
        return "Mock Search Engine A"

    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        return [
            SearchResult(
                title="Transformer Architecture Deep Dive",
                url="https://nature.com/transformers-2025",
                content="An in-depth analysis of transformer architecture...",
                score=0.95,
                metadata={"published_date": "2025-09-01"},
            ),
            SearchResult(
                title="Multi-Agent Systems Survey",
                url="https://ieee.org/multi-agent-survey",
                content="A comprehensive survey of multi-agent system design...",
                score=0.90,
                metadata={"published_date": "2025-07-15"},
            ),
            SearchResult(
                title="Spam AI Blog",
                url="https://pinterest.com/ai-spam",
                content="Check out these cool AI pictures...",
                score=0.60,
                metadata={"published_date": "2024-01-01"},
            ),
        ]


class MockRetrieverB(RetrieverPlugin):
    @property
    def plugin_id(self) -> str:
        return "search_engine_b"

    @property
    def description(self) -> str:
        return "Mock Search Engine B"

    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        return [
            SearchResult(
                title="LLM Reasoning Capabilities",
                url="https://ai.stanford.edu/llm-reasoning",
                content="Recent advances in LLM reasoning and planning...",
                score=0.93,
                metadata={"published_date": "2025-10-20"},
            ),
            SearchResult(
                title="Transformer Architecture Deep Dive",  # Duplicate URL
                url="https://nature.com/transformers-2025",
                content="Analysis of attention mechanisms in transformers...",
                score=0.88,
                metadata={"published_date": "2025-09-01"},
            ),
        ]


class MockScraper(ScraperPlugin):
    CONTENT = {
        "https://nature.com/transformers-2025": (
            "The transformer architecture, introduced in 'Attention Is All You Need' "
            "(Vaswani et al., 2017), has become the foundation of modern AI systems. "
            "Self-attention mechanisms allow models to weigh the importance of different "
            "parts of the input when producing each element of the output. Recent advances "
            "include sparse attention, linear attention, and mixture-of-experts approaches "
            "that dramatically improve efficiency at scale."
        ),
        "https://ieee.org/multi-agent-survey": (
            "Multi-agent systems (MAS) consist of multiple autonomous agents that interact "
            "to achieve individual or collective goals. Key challenges include coordination, "
            "communication, and conflict resolution. Modern MAS leverage large language "
            "models as reasoning engines, combined with tool use and memory systems. "
            "Applications range from software engineering to scientific research."
        ),
        "https://ai.stanford.edu/llm-reasoning": (
            "Large language models have shown surprising capabilities in reasoning tasks "
            "including mathematical problem solving, code generation, and strategic planning. "
            "Chain-of-thought prompting, tree-of-thought search, and self-reflection enable "
            "multi-step reasoning. However, limitations persist in spatial reasoning, "
            "causal inference, and handling novel problem structures."
        ),
    }

    @property
    def plugin_id(self) -> str:
        return "mock_scraper"

    @property
    def description(self) -> str:
        return "Mock content scraper"

    async def scrape(self, url: str) -> ScrapedContent:
        text = self.CONTENT.get(url, "")
        return ScrapedContent(
            url=url,
            title=url.split("/")[-1].replace("-", " ").title(),
            text=text,
            metadata={"scraper": "mock"},
        )


async def main() -> None:
    os.environ.setdefault("AZURE_OPENAI_ENDPOINT", AZURE_ENDPOINT)

    # --- Step 1: Multi-retriever search ---
    print_section("Step 1: Multi-retriever search")

    registry = RetrieverRegistry(drop_in_dir=None)
    registry.register(MockRetrieverA())
    registry.register(MockRetrieverB())

    query = "transformer architecture and multi-agent AI systems"
    print(f"  Query: {query!r}")

    results = await registry.search_all(
        query=query,
        retriever_ids=["search_engine_a", "search_engine_b"],
    )

    print(f"  Results after dedup: {len(results)}")
    for r in results:
        print(f"    [{r.score:.2f}] {r.title} ({r.url})")

    # --- Step 2: Source curation ---
    print_section("Step 2: Source curation (credibility filtering)")

    pipeline = SourceCurationPipeline(
        min_score=0.3,
        max_sources=5,
        domain_allow_list=["nature.com", "ieee.org", "stanford.edu"],
        domain_block_list=["pinterest.com", "quora.com"],
    )

    curated = await pipeline.curate(results, query=query)

    print(f"  Before curation: {len(results)} sources")
    print(f"  After curation:  {len(curated)} sources")
    print()
    for r in curated:
        print(f"    KEPT: {r.title} ({r.url})")
    removed = set(r.url for r in results) - set(r.url for r in curated)
    for url in removed:
        print(f"    DROP: {url}")

    # --- Step 3: Scrape curated sources ---
    print_section("Step 3: Scrape curated sources")

    scraper = MockScraper()
    scraped_content = []

    for r in curated:
        content = await scraper.scrape(r.url)
        valid = validate_scraped_content(content)
        print(f"  {r.url}")
        print(f"    Words: {content.word_count}, Valid: {valid}")
        if valid:
            scraped_content.append(content)

    print(f"\n  Valid content: {len(scraped_content)} pages")

    # --- Step 4: Embed and store ---
    print_section("Step 4: Embed and store in vector store")

    try:
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider
        from openai import AsyncAzureOpenAI

        credential = DefaultAzureCredential()
        token_provider = get_bearer_token_provider(
            credential, "https://cognitiveservices.azure.com/.default"
        )
        client = AsyncAzureOpenAI(
            azure_endpoint=AZURE_ENDPOINT,
            azure_ad_token_provider=token_provider,
            api_version="2024-06-01",
        )
    except ImportError:
        print("  ERROR: azure-identity not installed. Skipping embedding steps.")
        print("  Install with: pip install azure-identity")
        return

    store = MemoryVectorStore()
    mgr = CollectionManager(store, collection_prefix="research_", persist=False)

    all_chunks = []
    all_docs = []

    for content in scraped_content:
        # Simple chunking by sentences
        sentences = content.text.split(". ")
        for i, sentence in enumerate(sentences):
            if sentence.strip():
                chunk_id = f"{content.url}#chunk-{i}"
                all_chunks.append(sentence.strip() + ".")
                all_docs.append({
                    "doc_id": chunk_id,
                    "text": sentence.strip() + ".",
                    "source_url": content.url,
                    "source_title": content.title,
                })

    print(f"  Total chunks: {len(all_chunks)}")

    # Embed all chunks
    response = await client.embeddings.create(model=EMBEDDING_MODEL, input=all_chunks)
    vectors = [item.embedding for item in response.data]

    await store.add(vectors, all_docs)
    print(f"  Stored in vector store: {await store.count()} documents")
    print(f"  Collection: {mgr.collection_name('demo-session')}")

    # --- Step 5: Semantic search ---
    print_section("Step 5: Semantic similarity search")

    search_queries = [
        "How do transformer attention mechanisms work?",
        "What are the challenges in multi-agent coordination?",
        "Can LLMs do mathematical reasoning?",
    ]

    for sq in search_queries:
        print(f"  Q: {sq}")
        q_resp = await client.embeddings.create(model=EMBEDDING_MODEL, input=[sq])
        q_vec = q_resp.data[0].embedding

        hits = await store.search(q_vec, top_k=2)
        for doc, score in hits:
            print(f"    [{score:.3f}] {doc['text'][:70]}...")
            print(f"            Source: {doc['source_url']}")
        print()

    # --- Step 6: Citation tracking ---
    print_section("Step 6: Citation tracking")

    tracker = CitationTracker()

    for content in scraped_content:
        matching = [r for r in curated if r.url == content.url]
        if matching:
            r = matching[0]
            tracker.add(Citation(
                url=r.url,
                title=r.title,
                content_snippet=content.text[:200],
                date=r.metadata.get("published_date", ""),
                source_type="web",
            ))

    print(f"  Tracked {tracker.count} citations")
    print()

    # APA references
    print(tracker.format_references(style="apa"))
    print()

    # MLA references
    print(tracker.format_references(style="mla"))

    # --- Cleanup ---
    print_section("Cleanup")
    await mgr.cleanup()
    print(f"  Vector store cleared: {await store.count()} documents")
    print("\nPipeline complete!")


if __name__ == "__main__":
    asyncio.run(main())
