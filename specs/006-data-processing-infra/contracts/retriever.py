"""Retriever Plugin Interface Contract.

Defines the public contract for retriever plugins. Implementations
must inherit from RetrieverPlugin and register via the
hiveflow.retrievers entry point group.

NOTE: This file documents the TARGET interface. The base classes
already exist in hiveflow/plugins/retrievers/__init__.py.
Changes marked with # EXISTING or # NEW.
"""

from typing import Any


# --- Data Contract ---

class SearchResult:                                    # EXISTING
    """Normalized search result from any retriever.

    Fields:
        title: Page title
        url: Source URL (used as deduplication key)
        content: Snippet or description text
        score: Relevance score, 0.0 to 1.0
        metadata: Provider-specific metadata dict
    """
    title: str
    url: str
    content: str
    score: float
    metadata: dict[str, Any]


# --- Plugin Interface ---

class RetrieverPlugin:                                 # EXISTING
    """Base class for retriever plugins.

    Properties:
        plugin_id: Unique identifier (e.g., "tavily", "duckduckgo")
        description: Human-readable description
    """

    @property
    def plugin_id(self) -> str: ...                    # EXISTING

    @property
    def description(self) -> str: ...                  # EXISTING

    async def search(                                  # EXISTING
        self,
        query: str,
        max_results: int = 10,
    ) -> list[SearchResult]:
        """Execute a search query.

        Args:
            query: Search query string.
            max_results: Maximum results to return.

        Returns:
            List of SearchResult, sorted by score descending.

        Raises:
            ConnectionError: If the search service is unreachable.
            ValueError: If query is empty.
        """
        ...


# --- Registry ---

class RetrieverRegistry:                               # EXISTING
    """Registry for retriever plugins.

    Discovery: hiveflow.retrievers entry point group.
    """

    async def search_all(                              # EXISTING
        self,
        query: str,
        max_results: int = 10,
    ) -> list[SearchResult]:
        """Query all registered retrievers in parallel.

        Deduplicates results by URL, sorts by score descending.
        Individual retriever failures are logged and skipped.

        Returns:
            Merged, deduplicated results from all retrievers.
        """
        ...


# --- Entry Points (pyproject.toml) ---
# [project.entry-points."hiveflow.retrievers"]
# tavily = "hiveflow.plugins.retrievers.tavily_retriever:TavilyRetriever"
# duckduckgo = "hiveflow.plugins.retrievers.duckduckgo_retriever:DuckDuckGoRetriever"
