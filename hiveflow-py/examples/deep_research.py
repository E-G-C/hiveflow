"""Example: Deep research with recursive branching.

Demonstrates how to:
1. Configure deep research parameters
2. Provide custom research and query generation functions
3. Merge and compress research findings
4. Track citations across branches
"""

import asyncio

from hiveflow import (
    DeepResearchConfig,
    DeepResearcher,
)


async def mock_research(query: str, context: dict) -> dict:  # type: ignore[type-arg]
    """Simulate a research function.

    In production, this would call an LLM with web search tools.
    """
    depth = context.get("depth", 0)
    return {
        "findings": (
            f"Research findings for '{query}' at depth {depth}. "
            f"This topic has several important aspects worth exploring."
        ),
        "citations": [
            {
                "url": f"https://example.com/{query.replace(' ', '-')}",
                "title": f"Source: {query}",
                "content": f"Content about {query}",
            }
        ],
    }


async def mock_query_generator(query: str, breadth: int) -> list[str]:
    """Simulate sub-query generation.

    In production, this would use an LLM to decompose the query.
    """
    aspects = [
        "current state",
        "future trends",
        "challenges",
        "economic impact",
        "policy implications",
    ]
    return [f"{query}: {aspects[i % len(aspects)]}" for i in range(breadth)]


async def main() -> None:
    """Run deep research with progress tracking."""

    config = DeepResearchConfig(
        breadth=3,       # 3 sub-queries per level
        depth=2,         # 2 levels of recursion
        concurrency=4,   # max 4 parallel branches
        max_context_words=25000,
    )

    researcher = DeepResearcher(
        config=config,
        research_fn=mock_research,
        query_generator_fn=mock_query_generator,
    )

    print("Starting deep research...")
    result = await researcher.research("Impact of artificial intelligence on education")

    # Check progress
    progress = researcher.progress
    print(f"\nProgress: {progress.completion_percentage:.0f}%")
    print(f"Total branches: {progress.total_branches}")
    print(f"Completed: {progress.completed_branches}")
    print(f"Failed: {progress.failed_branches}")

    # Get findings
    print(f"\nRoot findings: {result.findings[:100]}...")
    print(f"Sub-branches: {len(result.sub_results)}")
    print(f"Total findings across tree: {len(result.all_findings)}")

    # Citations
    print(f"\nTotal citations: {researcher.citations.count}")
    refs = researcher.citations.format_references(style="numbered")
    if refs:
        print(f"\n{refs[:500]}...")

    # Get merged state for further processing
    state = researcher.get_research_state(result)
    print(f"\nMerged research state keys: {list(state.keys())}")


if __name__ == "__main__":
    asyncio.run(main())
