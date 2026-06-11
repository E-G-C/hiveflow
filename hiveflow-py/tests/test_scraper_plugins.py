"""Unit tests for scraper plugins (BS4, Playwright, ScraperRouter, validation)."""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hiveflow.plugins.scrapers import (
    MIN_CONTENT_LENGTH,
    ScrapedContent,
    ScraperPlugin,
    ScraperRegistry,
    ScraperRouter,
    validate_scraped_content,
)


# --- Content Validation tests ---


class TestValidateScrapedContent:
    def test_valid_content(self):
        content = ScrapedContent(url="http://x.com", title="T", text="a" * 200)
        assert validate_scraped_content(content) is True

    def test_short_content_rejected(self):
        content = ScrapedContent(url="http://x.com", title="T", text="short")
        assert validate_scraped_content(content) is False

    def test_whitespace_only_rejected(self):
        content = ScrapedContent(url="http://x.com", title="T", text="   \n\t  ")
        assert validate_scraped_content(content) is False

    def test_exactly_at_threshold(self):
        content = ScrapedContent(url="http://x.com", title="T", text="a" * MIN_CONTENT_LENGTH)
        assert validate_scraped_content(content) is True

    def test_one_below_threshold(self):
        content = ScrapedContent(
            url="http://x.com", title="T", text="a" * (MIN_CONTENT_LENGTH - 1)
        )
        assert validate_scraped_content(content) is False


# --- ScraperRouter tests ---


class TestScraperRouter:
    def test_pdf_url_routes_to_pdf_scraper(self):
        registry = ScraperRegistry(drop_in_dir=None)
        mock_pdf = MagicMock(spec=ScraperPlugin)
        mock_default = MagicMock(spec=ScraperPlugin)
        registry._plugins = {"pdf": mock_pdf, "beautifulsoup": mock_default}

        router = ScraperRouter(registry)
        selected = router.select("https://example.com/paper.pdf")
        assert selected is mock_pdf

    def test_arxiv_url_routes_to_arxiv_scraper(self):
        registry = ScraperRegistry(drop_in_dir=None)
        mock_arxiv = MagicMock(spec=ScraperPlugin)
        mock_default = MagicMock(spec=ScraperPlugin)
        registry._plugins = {"arxiv": mock_arxiv, "beautifulsoup": mock_default}

        router = ScraperRouter(registry)
        selected = router.select("https://arxiv.org/abs/2301.00001")
        assert selected is mock_arxiv

    def test_normal_url_routes_to_default(self):
        registry = ScraperRegistry(drop_in_dir=None)
        mock_default = MagicMock(spec=ScraperPlugin)
        registry._plugins = {"beautifulsoup": mock_default}

        router = ScraperRouter(registry)
        selected = router.select("https://example.com/page")
        assert selected is mock_default

    def test_pattern_match_without_plugin_falls_to_default(self):
        registry = ScraperRegistry(drop_in_dir=None)
        mock_default = MagicMock(spec=ScraperPlugin)
        # pdf pattern matches but no pdf plugin registered
        registry._plugins = {"beautifulsoup": mock_default}

        router = ScraperRouter(registry)
        selected = router.select("https://example.com/paper.pdf")
        assert selected is mock_default


# --- BS4Scraper tests ---


try:
    import bs4  # noqa: F401
    _has_bs4 = True
except ImportError:
    _has_bs4 = False


@pytest.mark.skipif(not _has_bs4, reason="beautifulsoup4 not installed")
class TestBS4Scraper:
    async def test_scrape_extracts_clean_text(self):
        from hiveflow.plugins.scrapers.bs4_scraper import BS4Scraper

        html = """
        <html>
            <head><title>Test Page</title></head>
            <body>
                <nav>Navigation</nav>
                <script>var x = 1;</script>
                <main>
                    <p>This is the main content of the page.</p>
                </main>
                <footer>Footer info</footer>
            </body>
        </html>
        """

        mock_response = MagicMock()
        mock_response.text = html
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        scraper = BS4Scraper()
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await scraper.scrape("https://example.com")

        assert isinstance(result, ScrapedContent)
        assert result.title == "Test Page"
        assert "main content" in result.text
        assert "Navigation" not in result.text
        assert "var x" not in result.text
        assert "Footer" not in result.text
        assert result.metadata["scraper"] == "beautifulsoup"

    async def test_scrape_handles_no_main_element(self):
        from hiveflow.plugins.scrapers.bs4_scraper import BS4Scraper

        html = "<html><body><p>Simple page content.</p></body></html>"

        mock_response = MagicMock()
        mock_response.text = html
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        scraper = BS4Scraper()
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await scraper.scrape("https://example.com")

        assert "Simple page content" in result.text


# --- PlaywrightScraper tests ---


class TestPlaywrightScraper:
    async def test_scrape_returns_content(self):
        from hiveflow.plugins.scrapers.playwright_scraper import PlaywrightScraper

        mock_page = AsyncMock()
        mock_page.goto = AsyncMock()
        mock_page.title = AsyncMock(return_value="Test Title")
        mock_page.inner_text = AsyncMock(return_value="Page body content here")
        mock_page.content = AsyncMock(return_value="<html>...</html>")

        mock_context = AsyncMock()
        mock_context.new_page = AsyncMock(return_value=mock_page)

        mock_browser = AsyncMock()
        mock_browser.new_context = AsyncMock(return_value=mock_context)
        mock_browser.close = AsyncMock()

        mock_chromium = AsyncMock()
        mock_chromium.launch = AsyncMock(return_value=mock_browser)

        mock_pw = AsyncMock()
        mock_pw.chromium = mock_chromium
        mock_pw.__aenter__ = AsyncMock(return_value=mock_pw)
        mock_pw.__aexit__ = AsyncMock(return_value=False)

        mock_pw_module = MagicMock()
        mock_pw_module.async_api.async_playwright = MagicMock(return_value=mock_pw)

        scraper = PlaywrightScraper()
        with patch.dict("sys.modules", {"playwright": mock_pw_module, "playwright.async_api": mock_pw_module.async_api}):
            with patch("hiveflow.plugins.scrapers.playwright_scraper.async_playwright", return_value=mock_pw, create=True):
                result = await scraper.scrape("https://example.com")

        assert isinstance(result, ScrapedContent)
        assert result.title == "Test Title"
        assert result.text == "Page body content here"
        assert result.metadata["scraper"] == "playwright"
        assert result.metadata["js_rendered"] is True

    async def test_supports_javascript_flag(self):
        from hiveflow.plugins.scrapers.playwright_scraper import PlaywrightScraper

        scraper = PlaywrightScraper()
        assert scraper.supports_javascript is True
