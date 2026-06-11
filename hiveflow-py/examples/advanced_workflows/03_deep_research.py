#!/usr/bin/env python3
"""Advanced Workflows 03: Deep research with recursive branching.

Demonstrates HiveFlow's deep research capability:
  1. Configure research parameters (breadth, depth, concurrency)
  2. Provide custom research and query generation functions
  3. Execute recursive branching research across multiple levels
  4. Track citations across all branches
  5. Merge and compress research findings into workflow state

This example uses mock functions (no LLM or web search needed).
In production, the research_fn would call an LLM with web search tools.

Usage:
    uv run python examples/advanced_workflows/03_deep_research.py

Expected output:
    See sample_output/advanced_workflows/03_deep_research.txt
"""

import asyncio

from hiveflow import (
    DeepResearchConfig,
    DeepResearcher,
)


# ---------------------------------------------------------------------------
# Mock research functions (replace with LLM + web search in production)
# ---------------------------------------------------------------------------

async def mock_research(query: str, context: dict) -> dict:
    """Simulate a research function.

    In production, this would call an LLM with web search tools
    to gather real information about the query.
    """
    depth = context.get("depth", 0)
    return {
        "findings": (
            f"Research findings for '{query}' at depth {depth}. "
            f"This topic has several important aspects including recent "
            f"developments, key challenges, and promising opportunities. "
            f"Multiple sources confirm growing interest and investment."
        ),
        "citations": [
            {
                "url": f"https://example.com/{query.replace(' ', '-').lower()[:40]}",
                "title": f"Source: {query[:50]}",
                "content": f"Detailed content about {query[:50]}",
            }
        ],
    }


async def mock_query_generator(query: str, breadth: int) -> list[str]:
    """Simulate sub-query generation.

    In production, this would use an LLM to decompose the query
    into meaningful sub-questions for deeper exploration.
    """
    aspects = [
        "current state and recent developments",
        "future trends and predictions",
        "key challenges and obstacles",
        "economic impact and market dynamics",
        "policy implications and regulations",
    ]
    return [f"{query}: {aspects[i % len(aspects)]}" for i in range(breadth)]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    """Run deep research with progress tracking and citation management."""
    print("=" * 60)
    print("  HiveFlow -- Deep Research with Recursive Branching")
    print("=" * 60)

    # Configure the research parameters
    config = DeepResearchConfig(
        breadth=3,         # 3 sub-queries per level
        depth=2,           # 2 levels of recursion
        concurrency=4,     # max 4 parallel branches
        max_context_words=25000,
    )

    print(f"\n  Configuration:")
    print(f"    Breadth:     {config.breadth} sub-queries per level")
    print(f"    Depth:       {config.depth} levels of recursion")
    print(f"    Concurrency: {config.concurrency} max parallel branches")
    print(f"    Max context: {config.max_context_words} words")
    print(f"    Total branches: {config.breadth} + {config.breadth}x{config.breadth} = "
          f"{config.breadth + config.breadth ** 2}")

    # Create the researcher
    researcher = DeepResearcher(
        config=config,
        research_fn=mock_research,
        query_generator_fn=mock_query_generator,
    )

    # Execute the research
    query = "Impact of artificial intelligence on education"
    print(f"\n  Query: {query}")
    print(f"\n{'-' * 60}")
    print("Executing research tree...")
    print("-" * 60)

    result = await researcher.research(query)

    # -- Progress report --
    progress = researcher.progress
    print(f"\n  Progress:      {progress.completion_percentage:.0f}%")
    print(f"  Total branches:    {progress.total_branches}")
    print(f"  Completed:         {progress.completed_branches}")
    print(f"  Failed:            {progress.failed_branches}")

    # -- Research tree structure --
    print(f"\n{'-' * 60}")
    print("Research tree:")
    print("-" * 60)
    print(f"  Root: {result.findings[:80]}...")
    print(f"  Sub-branches: {len(result.sub_results)}")
    for i, sub in enumerate(result.sub_results):
        print(f"    [{i+1}] {sub.findings[:60]}...")
        if sub.sub_results:
            for j, leaf in enumerate(sub.sub_results):
                print(f"      [{i+1}.{j+1}] {leaf.findings[:50]}...")

    # -- All findings (flattened) --
    all_findings = result.all_findings
    print(f"\n  Total findings across tree: {len(all_findings)}")

    # -- Citations --
    print(f"\n{'-' * 60}")
    print("Citations:")
    print("-" * 60)
    print(f"  Total citations: {researcher.citations.count}")
    refs = researcher.citations.format_references(style="numbered")
    if refs:
        # Show first few references
        lines = refs.strip().split("\n")
        for line in lines[:5]:
            print(f"  {line}")
        if len(lines) > 5:
            print(f"  ... ({len(lines)} total)")

    # -- Merged state for workflow integration --
    state = researcher.get_research_state(result)
    print(f"\n{'-' * 60}")
    print("Merged research state (for workflow integration):")
    print("-" * 60)
    print(f"  State keys: {sorted(state.keys())}")
    for key, value in state.items():
        if isinstance(value, str):
            print(f"  {key}: {value[:80]}...")
        elif isinstance(value, list):
            print(f"  {key}: [{len(value)} items]")
        else:
            print(f"  {key}: {value}")

    print(f"\n{'-' * 60}")
    print("  In production, replace mock_research() with an LLM+web-search")
    print("  function and mock_query_generator() with an LLM call.")
    print("-" * 60)


if __name__ == "__main__":
    asyncio.run(main())
