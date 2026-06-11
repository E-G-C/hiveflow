"""Tavily search retriever plugin.

Uses the Tavily Search API via the tavily-python SDK to perform
web searches and return normalized SearchResult objects.

Requires:
    pip install tavily-python
    TAVILY_API_KEY environment variable
"""

import os

import structlog

from hiveflow.plugins.retrievers import RetrieverPlugin, SearchResult

logger = structlog.get_logger(__name__)


class TavilyRetriever(RetrieverPlugin):
    """Tavily search API retriever."""

    @property
    def plugin_id(self) -> str:
        return "tavily"

    @property
    def description(self) -> str:
        return "Web search via Tavily Search API"

    async def search(
        self,
        query: str,
        max_results: int = 10,
    ) -> list[SearchResult]:
        """Execute a search query via Tavily.

        Args:
            query: Search query string.
            max_results: Maximum results to return (1-20).

        Returns:
            List of SearchResult objects sorted by score descending.

        Raises:
            ImportError: If tavily-python is not installed.
            ValueError: If query is empty or API key is missing.
        """
        if not query.strip():
            raise ValueError("Search query cannot be empty")

        try:
            from tavily import AsyncTavilyClient
        except ImportError:
            raise ImportError(
                "tavily-python is required for the Tavily retriever. "
                "Install it with: pip install tavily-python"
            ) from None

        api_key = os.environ.get("TAVILY_API_KEY")
        if not api_key:
            raise ValueError("TAVILY_API_KEY environment variable is required for Tavily retriever")

        logger.debug("retriever.tavily.search", query=query, max_results=max_results)

        client = AsyncTavilyClient(api_key=api_key)
        response = await client.search(
            query=query,
            max_results=min(max_results, 20),
        )

        results: list[SearchResult] = []
        for item in response.get("results", []):
            results.append(
                SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    content=item.get("content", ""),
                    score=float(item.get("score", 0.0)),
                    metadata={
                        "provider": "tavily",
                        "published_date": item.get("published_date"),
                        "raw_content": item.get("raw_content"),
                    },
                )
            )

        results.sort(key=lambda r: r.score, reverse=True)
        logger.info("retriever.tavily.results", count=len(results), query=query)
        return results
