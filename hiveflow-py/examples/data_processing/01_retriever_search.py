#!/usr/bin/env python3
"""Data Processing 01: Multi-retriever search with deduplication.

Demonstrates the retriever plugin system:
  1. Create mock retriever plugins that simulate Tavily and DuckDuckGo
  2. Register them with the RetrieverRegistry
  3. Execute parallel multi-retriever search via search_all()
  4. Observe URL deduplication and score-based ranking

No API keys required -- uses mock retrievers.

Usage:
    uv run python examples/data_processing/01_retriever_search.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hiveflow.plugins.retrievers import RetrieverPlugin, RetrieverRegistry, SearchResult


# -- Mock Retrievers (simulate real backends without API keys) --


class MockTavilyRetriever(RetrieverPlugin):
    """Simulates Tavily search results."""

    @property
    def plugin_id(self) -> str:
        return "tavily"

    @property
    def description(self) -> str:
        return "Mock Tavily search (demo)"

    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        return [
            SearchResult(
                title="Quantum Computing Overview",
                url="https://nature.com/quantum-computing",
                content="Quantum computing leverages quantum mechanical phenomena...",
                score=0.95,
                metadata={"provider": "tavily", "published_date": "2025-06-15"},
            ),
            SearchResult(
                title="Intro to Qubits",
                url="https://arxiv.org/abs/2401.00001",
                content="A qubit is the basic unit of quantum information...",
                score=0.88,
                metadata={"provider": "tavily"},
            ),
            SearchResult(
                title="Quantum vs Classical",
                url="https://ieee.org/quantum-classical",
                content="Comparing quantum and classical computing paradigms...",
                score=0.82,
                metadata={"provider": "tavily"},
            ),
        ][:max_results]


class MockDuckDuckGoRetriever(RetrieverPlugin):
    """Simulates DuckDuckGo search results with positional scoring."""

    @property
    def plugin_id(self) -> str:
        return "duckduckgo"

    @property
    def description(self) -> str:
        return "Mock DuckDuckGo search (demo)"

    async def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        results = [
            SearchResult(
                title="Quantum Computing - Wikipedia",
                url="https://en.wikipedia.org/wiki/Quantum_computing",
                content="Quantum computing is a type of computation...",
                score=1.0,
                metadata={"provider": "duckduckgo", "position": 0},
            ),
            SearchResult(
                title="Quantum Computing Overview",  # duplicate URL with Tavily
                url="https://nature.com/quantum-computing",
                content="Nature's guide to quantum computing...",
                score=0.95,
                metadata={"provider": "duckduckgo", "position": 1},
            ),
            SearchResult(
                title="IBM Quantum",
                url="https://quantum.ibm.com/learn",
                content="IBM Quantum provides cloud access to quantum...",
                score=0.90,
                metadata={"provider": "duckduckgo", "position": 2},
            ),
        ]
        return results[:max_results]


def print_section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}\n")


async def main() -> None:
    # -- 1. Create and register retrievers --
    print_section("1. Register mock retrievers")

    registry = RetrieverRegistry(drop_in_dir=None)
    registry.register(MockTavilyRetriever())
    registry.register(MockDuckDuckGoRetriever())

    print(f"  Registered: {registry.list_ids()}")
    print()

    # -- 2. Search a single retriever --
    print_section("2. Single-retriever search (Tavily only)")

    tavily = registry.get_or_raise("tavily")
    results = await tavily.search("quantum computing", max_results=3)

    for r in results:
        print(f"  [{r.score:.2f}] {r.title}")
        print(f"         {r.url}")
        print(f"         {r.content[:60]}...")
        print()

    # -- 3. Multi-retriever search with deduplication --
    print_section("3. Multi-retriever search (Tavily + DuckDuckGo)")
    print("  Querying both retrievers in parallel...")

    merged = await registry.search_all(
        query="quantum computing",
        retriever_ids=["tavily", "duckduckgo"],
        max_results_per=5,
    )

    print(f"\n  Total results after dedup: {len(merged)}")
    print(f"  (Note: nature.com URL appears in both but is deduplicated)\n")

    for i, r in enumerate(merged, 1):
        provider = r.metadata.get("provider", "unknown")
        print(f"  {i}. [{r.score:.2f}] [{provider:10}] {r.title}")
        print(f"                         {r.url}")

    # -- 4. Verify deduplication --
    print_section("4. Deduplication check")

    urls = [r.url for r in merged]
    unique_urls = set(urls)
    print(f"  Total results: {len(merged)}")
    print(f"  Unique URLs:   {len(unique_urls)}")
    print(f"  Duplicates removed: {len(urls) - len(unique_urls)}")

    if len(urls) == len(unique_urls):
        print("\n  OK -- all URLs are unique (deduplication working)")
    else:
        print("\n  WARNING -- duplicate URLs found")


if __name__ == "__main__":
    asyncio.run(main())
