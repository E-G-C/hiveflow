#!/usr/bin/env python3
"""Data Processing 05: Source credibility scoring and filtering.

Demonstrates the SourceCurationPipeline:
  1. Score URLs on domain authority (allow/block lists)
  2. Score freshness based on publication date
  3. Composite scoring with configurable weights
  4. Filter by min_score and cap at max_sources

No API keys required -- uses mock data and scoring signals that
don't need embedding or LLM providers.

Usage:
    uv run python examples/data_processing/05_source_curation.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hiveflow.core.source_curation import (
    SourceCurationPipeline,
    score_domain_authority,
    score_freshness,
)
from hiveflow.plugins.retrievers import SearchResult


def print_section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}\n")


# -- Mock search results (simulating retriever output) --

MOCK_RESULTS = [
    SearchResult(
        title="Comprehensive ML Guide",
        url="https://nature.com/ml-guide",
        content="A thorough overview of modern machine learning techniques...",
        score=0.92,
        metadata={"published_date": "2025-08-15"},
    ),
    SearchResult(
        title="AI Tutorial for Beginners",
        url="https://medium.com/ai-tutorial",
        content="Getting started with artificial intelligence and its applications...",
        score=0.85,
        metadata={"published_date": "2025-06-01"},
    ),
    SearchResult(
        title="Pinterest AI Art Collection",
        url="https://pinterest.com/ai-art",
        content="Collection of AI-generated artwork and creative examples...",
        score=0.78,
        metadata={"published_date": "2024-12-01"},
    ),
    SearchResult(
        title="Outdated ML Techniques",
        url="https://blogspot.com/old-ml",
        content="A 2018 guide to machine learning that covers older approaches...",
        score=0.72,
        metadata={"published_date": "2018-03-20"},
    ),
    SearchResult(
        title="IEEE Research on Deep Learning",
        url="https://ieee.org/deep-learning-2025",
        content="Peer-reviewed research on deep learning architectures...",
        score=0.90,
        metadata={"published_date": "2025-11-01"},
    ),
    SearchResult(
        title="Quora Discussion on AI",
        url="https://quora.com/what-is-ai",
        content="Community answers about what artificial intelligence means...",
        score=0.65,
        metadata={"published_date": "2024-06-15"},
    ),
    SearchResult(
        title="Stanford AI Lab Paper",
        url="https://ai.stanford.edu/papers/llm-2025",
        content="Latest findings on large language model capabilities...",
        score=0.95,
        metadata={"published_date": "2025-10-20"},
    ),
    SearchResult(
        title="Generic AI Blog Post",
        url="https://generic-blog.com/ai-stuff",
        content="Some thoughts on AI and the future of technology...",
        score=0.55,
        metadata={"published_date": "2023-01-10"},
    ),
]


async def main() -> None:
    # -- 1. Individual signal scoring --
    print_section("1. Individual scoring signals")

    print("  Domain Authority (allow/block lists):")
    test_domains = [
        ("https://nature.com/article", ["nature.com", "ieee.org"], ["pinterest.com"]),
        ("https://pinterest.com/pin", ["nature.com"], ["pinterest.com"]),
        ("https://random-site.com/page", [], []),
    ]
    for url, allow, block in test_domains:
        score = score_domain_authority(url, allow_list=allow, block_list=block)
        print(f"    {url:40s} -> {score:.2f}")

    print("\n  Freshness Scoring:")
    test_dates = [
        ("2025-11-01", "Recent (1 month ago)"),
        ("2024-06-01", "Moderate (18 months ago)"),
        ("2018-03-20", "Old (7+ years ago)"),
        (None, "No date available"),
    ]
    for date, label in test_dates:
        score = score_freshness(date)
        print(f"    {label:30s} ({date or 'None':20s}) -> {score:.2f}")

    # -- 2. Full curation pipeline --
    print_section("2. Source curation pipeline")

    pipeline = SourceCurationPipeline(
        embedding_provider=None,  # skip content relevance signal
        llm_provider=None,        # skip LLM judgment signal
        min_score=0.3,
        max_sources=5,
        freshness_max_age_days=730,
        domain_allow_list=["nature.com", "ieee.org", "stanford.edu"],
        domain_block_list=["pinterest.com", "quora.com"],
    )

    print(f"  Input sources:      {len(MOCK_RESULTS)}")
    print(f"  Min score:          {pipeline.min_score}")
    print(f"  Max sources:        {pipeline.max_sources}")
    print(f"  Domain allow list:  {pipeline.domain_allow_list}")
    print(f"  Domain block list:  {pipeline.domain_block_list}")

    curated = await pipeline.curate(MOCK_RESULTS, query="machine learning techniques")

    print(f"\n  Output sources:     {len(curated)}")
    print()

    # -- 3. Show per-source scores --
    print_section("3. Per-source scores (all sources)")

    for result in MOCK_RESULTS:
        url = result.url
        published_date = (result.metadata or {}).get("published_date")
        score_obj = await pipeline.score_single(url, result.content, "machine learning", published_date)

        # Check if it passed
        status = "PASS" if score_obj.composite_score >= pipeline.min_score else "FAIL"
        in_curated = any(r.url == url for r in curated)
        kept = "KEPT" if in_curated else "    "

        print(f"  [{status}] [{kept}] {score_obj.composite_score:.3f}  {result.title}")
        print(f"           domain={score_obj.domain_authority:.2f}  "
              f"fresh={score_obj.freshness:.2f}  "
              f"url={url}")
        print()

    # -- 4. Results summary --
    print_section("4. Curated results (top {} sources)".format(len(curated)))

    for i, result in enumerate(curated, 1):
        print(f"  {i}. [{result.score:.2f}] {result.title}")
        print(f"     {result.url}")

    print(f"\n  Filtered out: {len(MOCK_RESULTS) - len(curated)} sources")
    print(f"    - Blocked domains (pinterest, quora)")
    print(f"    - Old content (low freshness)")
    print(f"    - Below min_score threshold")
    print(f"    - Exceeds max_sources cap")


if __name__ == "__main__":
    asyncio.run(main())
