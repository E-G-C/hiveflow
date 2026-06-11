"""DuckDuckGo search retriever plugin.

Uses the duckduckgo-search package wrapped with asyncio.to_thread()
to perform web searches and return normalized SearchResult objects.

Requires:
    pip install duckduckgo-search>=7.1.0
"""

import asyncio

import structlog

from hiveflow.plugins.retrievers import RetrieverPlugin, SearchResult

logger = structlog.get_logger(__name__)


class DuckDuckGoRetriever(RetrieverPlugin):
    """DuckDuckGo search retriever."""

    @property
    def plugin_id(self) -> str:
        return "duckduckgo"

    @property
    def description(self) -> str:
        return "Web search via DuckDuckGo (no API key required)"

    async def search(
        self,
        query: str,
        max_results: int = 10,
    ) -> list[SearchResult]:
        """Execute a search query via DuckDuckGo.

        DuckDuckGo does not provide relevance scores, so synthetic
        positional scores are assigned: 1.0 - (index * 0.05).

        Args:
            query: Search query string.
            max_results: Maximum results to return.

        Returns:
            List of SearchResult objects with positional scores.

        Raises:
            ImportError: If duckduckgo-search is not installed.
            ValueError: If query is empty.
        """
        if not query.strip():
            raise ValueError("Search query cannot be empty")

        try:
            from duckduckgo_search import DDGS
        except ImportError:
            raise ImportError(
                "duckduckgo-search is required for the DuckDuckGo retriever. "
                "Install it with: pip install duckduckgo-search>=7.1.0"
            ) from None

        logger.debug("retriever.duckduckgo.search", query=query, max_results=max_results)

        def _sync_search() -> list[dict]:
            ddgs = DDGS()
            return list(ddgs.text(keywords=query, max_results=max_results))

        raw_results = await asyncio.to_thread(_sync_search)

        results: list[SearchResult] = []
        for index, item in enumerate(raw_results):
            score = max(0.0, 1.0 - (index * 0.05))
            results.append(
                SearchResult(
                    title=item.get("title", ""),
                    url=item.get("href", ""),
                    content=item.get("body", ""),
                    score=score,
                    metadata={
                        "provider": "duckduckgo",
                        "position": index,
                    },
                )
            )

        logger.info("retriever.duckduckgo.results", count=len(results), query=query)
        return results
