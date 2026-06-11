"""BeautifulSoup4 scraper plugin.

Lightweight HTML scraper that extracts clean text content from web pages
by removing navigation, ads, scripts, and other non-content elements.

Requires:
    pip install beautifulsoup4>=4.12.0
"""

import os

import structlog

from hiveflow.plugins.scrapers import ScrapedContent, ScraperPlugin

logger = structlog.get_logger(__name__)

_SCRAPE_TIMEOUT = int(os.environ.get("HIVEFLOW_SCRAPER_TIMEOUT", "15"))
_DECOMPOSE_TAGS = ["script", "style", "nav", "footer", "header", "aside", "iframe", "form"]


class BS4Scraper(ScraperPlugin):
    """BeautifulSoup4-based HTML scraper."""

    @property
    def plugin_id(self) -> str:
        return "beautifulsoup"

    @property
    def description(self) -> str:
        return "Lightweight HTML scraper using BeautifulSoup4"

    async def scrape(self, url: str) -> ScrapedContent:
        """Scrape content from a URL using BeautifulSoup4.

        Removes script, style, nav, footer, header, aside, iframe, form tags.
        Extracts text from main/article/body elements.

        Args:
            url: URL to scrape.

        Returns:
            Extracted clean text content.

        Raises:
            ImportError: If beautifulsoup4 is not installed.
            asyncio.TimeoutError: If scraping exceeds timeout.
        """
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            raise ImportError(
                "beautifulsoup4 is required for the BS4 scraper. "
                "Install it with: pip install beautifulsoup4>=4.12.0"
            ) from None

        import httpx

        from hiveflow.validation.url_security import validate_url

        validate_url(url)

        logger.debug("scraper.bs4.fetch", url=url, timeout=_SCRAPE_TIMEOUT)

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(_SCRAPE_TIMEOUT),
            follow_redirects=True,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            html = response.text

        soup = BeautifulSoup(html, "html.parser")

        # Remove non-content elements
        for tag in _DECOMPOSE_TAGS:
            for element in soup.find_all(tag):
                element.decompose()

        # Extract title
        title_tag = soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else ""

        # Find main content area
        content_element = soup.find("main") or soup.find("article") or soup.find("body") or soup

        text = content_element.get_text(separator="\n", strip=True)

        logger.info("scraper.bs4.done", url=url, chars=len(text))

        return ScrapedContent(
            url=url,
            title=title,
            text=text,
            html=html,
            metadata={"scraper": "beautifulsoup"},
        )
