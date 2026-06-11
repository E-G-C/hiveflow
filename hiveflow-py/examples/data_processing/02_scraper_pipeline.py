#!/usr/bin/env python3
"""Data Processing 02: Web scraping with routing and content validation.

Demonstrates the scraper plugin system:
  1. BS4Scraper extracts clean text from HTML pages
  2. ScraperRouter selects scrapers based on URL patterns
  3. Content validation rejects low-quality pages (< 100 chars)
  4. Batch scraping with concurrency control and error isolation

No API keys required -- uses mock HTTP responses.

Usage:
    uv run python examples/data_processing/02_scraper_pipeline.py
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hiveflow.plugins.scrapers import (
    MIN_CONTENT_LENGTH,
    ScrapedContent,
    ScraperPlugin,
    ScraperRegistry,
    ScraperRouter,
    validate_scraped_content,
)


def print_section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}\n")


# -- Mock scraper for demo (avoids real HTTP calls) --


class DemoScraper(ScraperPlugin):
    """Mock scraper returning pre-built content."""

    PAGES = {
        "https://example.com/good-article": ScrapedContent(
            url="https://example.com/good-article",
            title="Understanding AI Agents",
            text=(
                "Artificial intelligence agents are autonomous software entities "
                "that perceive their environment and take actions to achieve goals. "
                "Modern AI agents combine large language models with tool use, "
                "planning capabilities, and memory systems to accomplish complex "
                "tasks. Multi-agent systems coordinate multiple specialized agents "
                "to solve problems that no single agent could handle alone."
            ),
            html="<html>...</html>",
            metadata={"scraper": "demo"},
        ),
        "https://example.com/thin-page": ScrapedContent(
            url="https://example.com/thin-page",
            title="Empty Page",
            text="Login required.",
            html="<html>Login required.</html>",
            metadata={"scraper": "demo"},
        ),
        "https://example.com/research.pdf": ScrapedContent(
            url="https://example.com/research.pdf",
            title="Research Paper",
            text=(
                "Abstract: This paper presents a novel approach to multi-agent "
                "coordination using hierarchical task decomposition. We show that "
                "our method outperforms existing baselines on three benchmark tasks."
            ),
            html="",
            metadata={"scraper": "demo", "format": "pdf"},
        ),
    }

    @property
    def plugin_id(self) -> str:
        return "beautifulsoup"

    @property
    def description(self) -> str:
        return "Demo scraper (mock HTTP)"

    async def scrape(self, url: str) -> ScrapedContent:
        if url in self.PAGES:
            return self.PAGES[url]
        if "timeout" in url:
            raise asyncio.TimeoutError(f"Timeout scraping {url}")
        raise ConnectionError(f"URL not found: {url}")


async def main() -> None:
    # -- 1. Basic scraping --
    print_section("1. Basic scraping")

    scraper = DemoScraper()
    result = await scraper.scrape("https://example.com/good-article")

    print(f"  Title:      {result.title}")
    print(f"  URL:        {result.url}")
    print(f"  Word count: {result.word_count}")
    print(f"  Text:       {result.text[:100]}...")

    # -- 2. Content validation --
    print_section("2. Content validation (MIN_CONTENT_LENGTH = {})".format(MIN_CONTENT_LENGTH))

    good = await scraper.scrape("https://example.com/good-article")
    thin = await scraper.scrape("https://example.com/thin-page")

    print(f"  Good article: {len(good.text)} chars -> valid={validate_scraped_content(good)}")
    print(f"  Thin page:    {len(thin.text)} chars -> valid={validate_scraped_content(thin)}")

    # -- 3. ScraperRouter URL-pattern routing --
    print_section("3. ScraperRouter -- URL-pattern-based selection")

    registry = ScraperRegistry(drop_in_dir=None)
    registry.register(scraper)

    router = ScraperRouter(registry, default_scraper_id="beautifulsoup")

    test_urls = [
        "https://example.com/page.html",
        "https://example.com/research.pdf",
        "https://arxiv.org/abs/2401.00001",
    ]

    for url in test_urls:
        try:
            selected = router.select(url)
            print(f"  {url}")
            print(f"    -> scraper: {selected.plugin_id}")
        except KeyError:
            print(f"  {url}")
            print(f"    -> fallback to default (pattern matched but no plugin)")
        print()

    # -- 4. Batch scraping with error isolation --
    print_section("4. Batch scraping with error isolation")

    urls = [
        "https://example.com/good-article",
        "https://example.com/timeout-page",  # will timeout
        "https://example.com/research.pdf",
        "https://example.com/nonexistent",   # will error
    ]

    print(f"  Scraping {len(urls)} URLs with max_concurrent=15...")
    results = await scraper.scrape_batch(urls, max_concurrent=15)

    for url, result in zip(urls, results):
        if isinstance(result, BaseException):
            print(f"  ERROR  {url}")
            print(f"         {type(result).__name__}: {result}")
        else:
            valid = validate_scraped_content(result)
            print(f"  {'OK   ' if valid else 'THIN '} {url}")
            print(f"         {result.word_count} words, valid={valid}")
        print()

    successes = sum(1 for r in results if not isinstance(r, BaseException))
    errors = sum(1 for r in results if isinstance(r, BaseException))
    print(f"  Summary: {successes} succeeded, {errors} failed (errors isolated)")


if __name__ == "__main__":
    asyncio.run(main())
