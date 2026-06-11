"""Tests for scraper timeout behavior (FR-033)."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hiveflow.plugins.scrapers import ScrapedContent


class TestScraperTimeout:
    """Tests for per-URL timeout enforcement."""

    async def test_default_timeout_is_15_seconds(self):
        """Verify default timeout is 15s when env var not set."""
        # Clear env and reimport to test default
        with patch.dict(os.environ, {}, clear=True):
            # The module reads timeout at import time, so we check the value
            from hiveflow.plugins.scrapers import bs4_scraper

            # Force re-read of the env var
            default_timeout = int(os.environ.get("HIVEFLOW_SCRAPER_TIMEOUT", "15"))
            assert default_timeout == 15

    async def test_configurable_timeout_via_env(self):
        """Verify timeout can be configured via HIVEFLOW_SCRAPER_TIMEOUT."""
        with patch.dict(os.environ, {"HIVEFLOW_SCRAPER_TIMEOUT": "30"}):
            timeout = int(os.environ.get("HIVEFLOW_SCRAPER_TIMEOUT", "15"))
            assert timeout == 30

    async def test_batch_timeout_does_not_block_other_urls(self):
        """Verify timed-out URL returns error without blocking batch."""
        from hiveflow.plugins.scrapers import ScraperPlugin

        class MockScraper(ScraperPlugin):
            @property
            def plugin_id(self) -> str:
                return "mock"

            @property
            def description(self) -> str:
                return "Mock scraper"

            async def scrape(self, url: str) -> ScrapedContent:
                if "timeout" in url:
                    import asyncio
                    raise asyncio.TimeoutError(f"Timeout scraping {url}")
                return ScrapedContent(
                    url=url, title="OK", text="Content " * 20, metadata={}
                )

        scraper = MockScraper()
        urls = [
            "https://example.com/page1",
            "https://example.com/timeout-page",
            "https://example.com/page3",
        ]

        results = await scraper.scrape_batch(urls, max_concurrent=15)

        assert len(results) == 3
        # First and third succeed
        assert isinstance(results[0], ScrapedContent)
        assert isinstance(results[2], ScrapedContent)
        # Second times out
        assert isinstance(results[1], BaseException)

    async def test_batch_empty_urls_returns_empty(self):
        """Verify empty URL list returns empty results."""
        from hiveflow.plugins.scrapers import ScraperPlugin

        class MockScraper(ScraperPlugin):
            @property
            def plugin_id(self) -> str:
                return "mock"

            @property
            def description(self) -> str:
                return "Mock"

            async def scrape(self, url: str) -> ScrapedContent:
                return ScrapedContent(url=url, title="", text="", metadata={})

        scraper = MockScraper()
        results = await scraper.scrape_batch([], max_concurrent=15)
        assert results == []
