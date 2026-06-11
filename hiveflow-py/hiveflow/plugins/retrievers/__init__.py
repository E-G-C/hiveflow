"""Retriever System - Pluggable information retrieval backends.

Retrievers fetch relevant information from external sources to provide
context for agent workflows. Supports web search, academic databases,
and custom data sources.
"""

from abc import abstractmethod
from typing import Any

import structlog

from hiveflow.core.registry import BasePlugin, PluginRegistry

logger = structlog.get_logger()


class SearchResult:
    """A single search result from a retriever."""

    def __init__(
        self,
        title: str,
        url: str,
        content: str,
        score: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.title = title
        self.url = url
        self.content = content
        self.score = score
        self.metadata = metadata or {}

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "title": self.title,
            "url": self.url,
            "content": self.content,
            "score": self.score,
            "metadata": self.metadata,
        }


class RetrieverPlugin(BasePlugin):
    """Base class for retriever plugins."""

    @property
    @abstractmethod
    def plugin_id(self) -> str:
        """Retriever identifier (e.g., 'tavily', 'duckduckgo')."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description."""
        ...

    @abstractmethod
    async def search(
        self,
        query: str,
        max_results: int = 10,
    ) -> list[SearchResult]:
        """Execute a search query.

        Args:
            query: Search query string
            max_results: Maximum number of results to return

        Returns:
            List of SearchResult objects
        """
        ...


class RetrieverRegistry(PluginRegistry["RetrieverPlugin"]):
    """Registry for retriever plugins.

    Discovers retrievers from:
    - Python entry points under 'hiveflow.retrievers'
    - Drop-in directory
    """

    def __init__(self, drop_in_dir: str | None = "retrievers") -> None:
        super().__init__(
            entry_point_group="hiveflow.retrievers",
            drop_in_dir=drop_in_dir,
        )

    async def search_all(
        self,
        query: str,
        retriever_ids: list[str],
        max_results_per: int = 10,
    ) -> list[SearchResult]:
        """Search across multiple retrievers and merge results.

        Args:
            query: Search query
            retriever_ids: List of retriever IDs to use
            max_results_per: Max results per retriever

        Returns:
            Merged and deduplicated search results
        """
        import asyncio

        tasks = []
        for rid in retriever_ids:
            retriever = self.get(rid)
            if retriever:
                tasks.append(retriever.search(query, max_results=max_results_per))
            else:
                logger.warning("Retriever '%s' not found", rid)

        if not tasks:
            return []

        results_lists = await asyncio.gather(*tasks, return_exceptions=True)

        all_results: list[SearchResult] = []
        seen_urls: set[str] = set()

        for results in results_lists:
            if isinstance(results, BaseException):
                logger.error("Retriever search failed: %s", results)
                continue
            for result in results:
                if result.url not in seen_urls:
                    seen_urls.add(result.url)
                    all_results.append(result)

        # Sort by score descending
        all_results.sort(key=lambda r: r.score, reverse=True)
        return all_results
