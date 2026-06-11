"""Scraper Plugin Interface Contract.

Defines the public contract for scraper plugins. Implementations
must inherit from ScraperPlugin and register via the
hiveflow.scrapers entry point group.

NOTE: This file documents the TARGET interface. The base classes
already exist in hiveflow/plugins/scrapers/__init__.py.
Changes marked with # EXISTING, # CHANGED, or # NEW.
"""

from typing import Any


# --- Data Contract ---

class ScrapedContent:                                  # EXISTING
    """Extracted content from a web page.

    Fields:
        url: Source URL
        title: Page title
        text: Clean extracted text (nav/ads/scripts removed)
        html: Raw HTML (optional, empty string if not available)
        metadata: Extraction metadata dict
    """
    url: str
    title: str
    text: str
    html: str
    metadata: dict[str, Any]

    @property
    def word_count(self) -> int:                       # EXISTING
        """Approximate word count of extracted text."""
        ...


# --- Plugin Interface ---

class ScraperPlugin:                                   # EXISTING
    """Base class for scraper plugins.

    Properties:
        plugin_id: Unique identifier (e.g., "beautifulsoup", "playwright")
        description: Human-readable description
        supports_javascript: Whether this scraper renders JS (default: False)
    """

    @property
    def plugin_id(self) -> str: ...                    # EXISTING

    @property
    def description(self) -> str: ...                  # EXISTING

    @property
    def supports_javascript(self) -> bool:             # EXISTING
        return False

    async def scrape(self, url: str) -> ScrapedContent:  # EXISTING
        """Scrape content from a URL.

        Must respect the per-URL timeout (default 15s, configurable
        via HIVEFLOW_SCRAPER_TIMEOUT).

        Args:
            url: URL to scrape.

        Returns:
            Extracted content.

        Raises:
            asyncio.TimeoutError: If scraping exceeds timeout.
            ConnectionError: If URL is unreachable.
        """
        ...

    async def scrape_batch(                            # CHANGED: default 15
        self,
        urls: list[str],
        max_concurrent: int = 15,
    ) -> list[ScrapedContent | BaseException]:
        """Scrape multiple URLs concurrently.

        Uses asyncio.Semaphore for concurrency control.
        Uses asyncio.gather(return_exceptions=True) for error isolation.

        Args:
            urls: URLs to scrape.
            max_concurrent: Maximum concurrent operations (default: 15).

        Returns:
            List of ScrapedContent or Exception for each URL.
            Order matches input URL order.
        """
        ...


# --- Scraper Router (NEW) ---

class ScraperRouter:                                   # NEW
    """Selects the appropriate scraper based on URL patterns.

    Routing rules:
        *.pdf         -> pdf scraper (if registered)
        arxiv.org/*   -> arxiv scraper (if registered)
        *             -> configured default scraper

    Falls back to the default scraper if no pattern-specific
    scraper is registered.
    """

    def __init__(
        self,
        registry: "ScraperRegistry",
        default_scraper_id: str = "beautifulsoup",
        patterns: dict[str, str] | None = None,
    ) -> None: ...

    def select(self, url: str) -> "ScraperPlugin":
        """Select the best scraper for a URL."""
        ...


# --- Content Validation (NEW) ---

MIN_CONTENT_LENGTH = 100  # chars; discard pages below this


def validate_scraped_content(content: ScrapedContent) -> bool:  # NEW
    """Return True if content meets minimum quality threshold."""
    return len(content.text.strip()) >= MIN_CONTENT_LENGTH


# --- Entry Points (pyproject.toml) ---
# [project.entry-points."hiveflow.scrapers"]
# beautifulsoup = "hiveflow.plugins.scrapers.bs4_scraper:BS4Scraper"
# playwright = "hiveflow.plugins.scrapers.playwright_scraper:PlaywrightScraper"
