"""Playwright scraper plugin.

JavaScript-capable scraper that uses Playwright to render pages
before extracting content. Suitable for SPAs and JS-heavy sites.

Requires:
    pip install playwright>=1.40.0
    playwright install chromium
"""

import os

import structlog

from hiveflow.plugins.scrapers import ScrapedContent, ScraperPlugin

logger = structlog.get_logger(__name__)

_SCRAPE_TIMEOUT = int(os.environ.get("HIVEFLOW_SCRAPER_TIMEOUT", "15"))
_TIMEOUT_MS = _SCRAPE_TIMEOUT * 1000


class PlaywrightScraper(ScraperPlugin):
    """Playwright-based JavaScript-capable scraper."""

    @property
    def plugin_id(self) -> str:
        return "playwright"

    @property
    def description(self) -> str:
        return "JavaScript-capable scraper using Playwright + Chromium"

    @property
    def supports_javascript(self) -> bool:
        return True

    async def scrape(self, url: str) -> ScrapedContent:
        """Scrape content from a URL using Playwright.

        Launches headless Chromium, navigates to the URL, waits for
        network idle, then extracts visible text content.

        Args:
            url: URL to scrape.

        Returns:
            Extracted content after JS rendering.

        Raises:
            ImportError: If playwright is not installed.
            RuntimeError: If Chromium binaries are not installed.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise ImportError(
                "playwright is required for the Playwright scraper. "
                "Install it with: pip install playwright>=1.40.0"
            ) from None

        logger.debug("scraper.playwright.fetch", url=url, timeout=_SCRAPE_TIMEOUT)

        from hiveflow.validation.url_security import validate_url

        validate_url(url)

        async with async_playwright() as p:
            try:
                browser = await p.chromium.launch(headless=True)
            except Exception as exc:
                raise RuntimeError(
                    'Chromium binaries not found. Run "playwright install chromium" '
                    "to download them (~150MB)."
                ) from exc

            try:
                context = await browser.new_context()
                page = await context.new_page()

                await page.goto(url, wait_until="networkidle", timeout=_TIMEOUT_MS)

                title = await page.title()
                text = await page.inner_text("body")
                html = await page.content()

                logger.info("scraper.playwright.done", url=url, chars=len(text))

                return ScrapedContent(
                    url=url,
                    title=title,
                    text=text,
                    html=html,
                    metadata={"scraper": "playwright", "js_rendered": True},
                )
            finally:
                await browser.close()
