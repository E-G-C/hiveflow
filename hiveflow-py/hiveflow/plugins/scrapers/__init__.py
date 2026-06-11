"""Scraper System - Web content extraction for agent workflows.

Scrapers extract clean text content from web pages for use as
context in agent workflows. Supports BeautifulSoup and Playwright backends.
"""

import re
from abc import abstractmethod
from typing import Any
from urllib.parse import urlparse

import structlog

from hiveflow.core.registry import BasePlugin, PluginRegistry

logger = structlog.get_logger()

MIN_CONTENT_LENGTH = 100  # chars; discard pages below this


class ScrapedContent:
    """Extracted content from a web page."""

    def __init__(
        self,
        url: str,
        title: str,
        text: str,
        html: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.url = url
        self.title = title
        self.text = text
        self.html = html
        self.metadata = metadata or {}

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "url": self.url,
            "title": self.title,
            "text": self.text,
            "metadata": self.metadata,
        }

    @property
    def word_count(self) -> int:
        """Approximate word count of extracted text."""
        return len(self.text.split())


class ScraperPlugin(BasePlugin):
    """Base class for scraper plugins."""

    @property
    @abstractmethod
    def plugin_id(self) -> str:
        """Scraper identifier (e.g., 'beautifulsoup', 'playwright')."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description."""
        ...

    @property
    def supports_javascript(self) -> bool:
        """Whether this scraper can render JavaScript."""
        return False

    @abstractmethod
    async def scrape(self, url: str) -> ScrapedContent:
        """Scrape content from a URL.

        Args:
            url: URL to scrape

        Returns:
            Extracted content
        """
        ...

    async def scrape_batch(
        self, urls: list[str], max_concurrent: int = 15
    ) -> list[ScrapedContent | BaseException]:
        """Scrape multiple URLs concurrently.

        Args:
            urls: URLs to scrape
            max_concurrent: Maximum concurrent scrape operations

        Returns:
            List of ScrapedContent or Exception for each URL
        """
        import asyncio

        semaphore = asyncio.Semaphore(max_concurrent)

        async def _scrape_one(url: str) -> ScrapedContent:
            async with semaphore:
                return await self.scrape(url)

        tasks = [_scrape_one(url) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return list(results)


class ScraperRegistry(PluginRegistry["ScraperPlugin"]):
    """Registry for scraper plugins."""

    def __init__(self, drop_in_dir: str | None = "scrapers") -> None:
        super().__init__(
            entry_point_group="hiveflow.scrapers",
            drop_in_dir=drop_in_dir,
        )


# Default URL pattern-to-scraper mappings
_DEFAULT_PATTERNS: dict[str, str] = {
    r"\.pdf$": "pdf",
    r"arxiv\.org/": "arxiv",
}


class ScraperRouter:
    """Selects the appropriate scraper based on URL patterns.

    Falls back to the default scraper if no pattern-specific
    scraper is registered.
    """

    def __init__(
        self,
        registry: ScraperRegistry,
        default_scraper_id: str = "beautifulsoup",
        patterns: dict[str, str] | None = None,
    ) -> None:
        self._registry = registry
        self._default_scraper_id = default_scraper_id
        self._patterns = patterns or _DEFAULT_PATTERNS

    def select(self, url: str) -> ScraperPlugin:
        """Select the best scraper for a URL.

        Checks URL against registered patterns. Falls back to
        the default scraper if no pattern matches or the matched
        scraper is not registered.
        """
        parsed = urlparse(url)
        url_str = parsed.geturl()

        for pattern, scraper_id in self._patterns.items():
            if re.search(pattern, url_str, re.IGNORECASE):
                try:
                    return self._registry.get_or_raise(scraper_id)
                except KeyError:
                    logger.debug(
                        "scraper_router.pattern_match_no_plugin",
                        pattern=pattern,
                        scraper_id=scraper_id,
                        url=url,
                    )

        return self._registry.get_or_raise(self._default_scraper_id)


def validate_scraped_content(content: ScrapedContent) -> bool:
    """Return True if content meets minimum quality threshold.

    Args:
        content: Scraped content to validate.

    Returns:
        True if text has at least MIN_CONTENT_LENGTH characters.
    """
    return len(content.text.strip()) >= MIN_CONTENT_LENGTH
