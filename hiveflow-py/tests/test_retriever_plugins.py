"""Unit tests for retriever plugins (Tavily, DuckDuckGo, Registry)."""

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hiveflow.plugins.retrievers import RetrieverRegistry, SearchResult


# --- TavilyRetriever tests ---


class TestTavilyRetriever:
    """Tests for the Tavily retriever plugin."""

    @pytest.fixture
    def tavily_response(self):
        return {
            "results": [
                {
                    "title": "Python Async Guide",
                    "url": "https://example.com/async",
                    "content": "A guide to async Python programming.",
                    "score": 0.95,
                    "published_date": "2025-01-01",
                },
                {
                    "title": "Asyncio Tutorial",
                    "url": "https://example.com/asyncio",
                    "content": "Learn asyncio basics.",
                    "score": 0.80,
                },
            ]
        }

    async def test_search_returns_search_results(self, tavily_response):
        from hiveflow.plugins.retrievers.tavily_retriever import TavilyRetriever

        retriever = TavilyRetriever()
        mock_client = AsyncMock()
        mock_client.search = AsyncMock(return_value=tavily_response)

        mock_tavily_module = MagicMock()
        mock_tavily_module.AsyncTavilyClient = MagicMock(return_value=mock_client)

        with (
            patch.dict("os.environ", {"TAVILY_API_KEY": "test-key"}),
            patch.dict("sys.modules", {"tavily": mock_tavily_module}),
        ):
            results = await retriever.search("async python", max_results=5)

        assert len(results) == 2
        assert all(isinstance(r, SearchResult) for r in results)
        assert results[0].score >= results[1].score
        assert results[0].title == "Python Async Guide"
        assert results[0].url == "https://example.com/async"
        assert results[0].metadata["provider"] == "tavily"

    async def test_search_empty_query_raises(self):
        from hiveflow.plugins.retrievers.tavily_retriever import TavilyRetriever

        retriever = TavilyRetriever()
        with pytest.raises(ValueError, match="empty"):
            await retriever.search("")

    async def test_search_missing_api_key_raises(self):
        from hiveflow.plugins.retrievers.tavily_retriever import TavilyRetriever

        mock_tavily_module = MagicMock()
        retriever = TavilyRetriever()
        with (
            patch.dict("os.environ", {}, clear=True),
            patch.dict("sys.modules", {"tavily": mock_tavily_module}),
            pytest.raises(ValueError, match="TAVILY_API_KEY"),
        ):
            await retriever.search("test query")


# --- DuckDuckGoRetriever tests ---


class TestDuckDuckGoRetriever:
    """Tests for the DuckDuckGo retriever plugin."""

    @pytest.fixture
    def ddg_results(self):
        return [
            {
                "title": "Result One",
                "href": "https://example.com/one",
                "body": "First result body.",
            },
            {
                "title": "Result Two",
                "href": "https://example.com/two",
                "body": "Second result body.",
            },
            {
                "title": "Result Three",
                "href": "https://example.com/three",
                "body": "Third result body.",
            },
        ]

    async def test_search_returns_search_results(self, ddg_results):
        from hiveflow.plugins.retrievers.duckduckgo_retriever import DuckDuckGoRetriever

        retriever = DuckDuckGoRetriever()
        mock_ddgs_instance = MagicMock()
        mock_ddgs_instance.text.return_value = ddg_results

        mock_ddg_module = MagicMock()
        mock_ddg_module.DDGS = MagicMock(return_value=mock_ddgs_instance)

        with patch.dict("sys.modules", {"duckduckgo_search": mock_ddg_module}):
            results = await retriever.search("test query", max_results=5)

        assert len(results) == 3
        assert all(isinstance(r, SearchResult) for r in results)
        # Map href -> url
        assert results[0].url == "https://example.com/one"
        # Map body -> content
        assert results[0].content == "First result body."
        assert results[0].metadata["provider"] == "duckduckgo"

    async def test_positional_scoring(self, ddg_results):
        from hiveflow.plugins.retrievers.duckduckgo_retriever import DuckDuckGoRetriever

        retriever = DuckDuckGoRetriever()
        mock_ddgs_instance = MagicMock()
        mock_ddgs_instance.text.return_value = ddg_results

        mock_ddg_module = MagicMock()
        mock_ddg_module.DDGS = MagicMock(return_value=mock_ddgs_instance)

        with patch.dict("sys.modules", {"duckduckgo_search": mock_ddg_module}):
            results = await retriever.search("test query")

        # Positional scores: 1.0, 0.95, 0.90
        assert results[0].score == 1.0
        assert results[1].score == pytest.approx(0.95)
        assert results[2].score == pytest.approx(0.90)

    async def test_search_empty_query_raises(self):
        from hiveflow.plugins.retrievers.duckduckgo_retriever import DuckDuckGoRetriever

        retriever = DuckDuckGoRetriever()
        with pytest.raises(ValueError, match="empty"):
            await retriever.search("   ")


# --- RetrieverRegistry.search_all tests ---


class TestRetrieverRegistrySearchAll:
    """Tests for multi-retriever dispatch and deduplication."""

    async def test_search_all_deduplicates_by_url(self):
        registry = RetrieverRegistry(drop_in_dir=None)

        mock_retriever_a = AsyncMock()
        mock_retriever_a.search.return_value = [
            SearchResult(title="A", url="https://example.com/shared", content="from A", score=0.9),
            SearchResult(title="A2", url="https://example.com/a-only", content="only A", score=0.7),
        ]

        mock_retriever_b = AsyncMock()
        mock_retriever_b.search.return_value = [
            SearchResult(title="B", url="https://example.com/shared", content="from B", score=0.8),
            SearchResult(title="B2", url="https://example.com/b-only", content="only B", score=0.6),
        ]

        registry._plugins = {"a": mock_retriever_a, "b": mock_retriever_b}

        results = await registry.search_all("test", retriever_ids=["a", "b"])

        urls = [r.url for r in results]
        assert len(urls) == 3
        assert urls.count("https://example.com/shared") == 1
        # Results sorted by score descending
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    async def test_search_all_isolates_failures(self):
        registry = RetrieverRegistry(drop_in_dir=None)

        mock_good = AsyncMock()
        mock_good.search.return_value = [
            SearchResult(title="Good", url="https://good.com", content="ok", score=0.9),
        ]

        mock_bad = AsyncMock()
        mock_bad.search.side_effect = ConnectionError("Network error")

        registry._plugins = {"good": mock_good, "bad": mock_bad}

        results = await registry.search_all("test", retriever_ids=["good", "bad"])

        assert len(results) == 1
        assert results[0].url == "https://good.com"
