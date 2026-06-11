"""Source Curation Pipeline Interface Contract.

Defines the public contract for the source curation pipeline. This is
a framework-internal module (not a plugin type) that scores and filters
retriever results before committing to full content extraction.

NOTE: This is a NEW module. It will live in hiveflow/core/source_curation.py.
All items marked # NEW.
"""

from typing import Any


# --- Data Contract ---

class SourceScore:                                        # NEW
    """Credibility score for a single source URL.

    Fields:
        url: Source URL
        domain_authority: Domain reputation score (0.0 - 1.0)
        content_relevance: Cosine similarity of snippet vs. query (0.0 - 1.0)
        freshness: Time-decay score (0.0 - 1.0)
        llm_judgment: LLM quality rating normalized to 0.0 - 1.0
        composite_score: Weighted sum of all signals (0.0 - 1.0)
    """
    url: str
    domain_authority: float
    content_relevance: float
    freshness: float
    llm_judgment: float
    composite_score: float


# --- Pipeline ---

class SourceCurationPipeline:                             # NEW
    """Multi-signal source credibility scoring and filtering.

    Scoring signals (configurable weights, defaults below):
        - domain_authority  (0.25): Known-domain heuristic
        - content_relevance (0.30): Cosine similarity of snippet embedding vs query
        - freshness         (0.15): Time-decay based on content age
        - llm_judgment      (0.30): LLM quality assessment via FAST_LLM tier

    When no embedding provider is configured, the content_relevance
    signal is skipped and the remaining signals are reweighted
    proportionally.

    Pipeline steps:
        1. Snippet scraping — lightweight scrape of each URL (first ~500 chars)
        2. Domain scoring — allow/block list + known-domain heuristics
        3. Content relevance scoring — embed snippet, compare to query
        4. Freshness scoring — extract dates, apply time-decay
        5. LLM judgment — FAST_LLM rates quality on 1-10 scale, normalized to 0-1
        6. Composite scoring — weighted sum of all signals
        7. Filtering — discard below min_score, keep top max_sources
    """

    def __init__(
        self,
        scraper: "ScraperPlugin",
        embedding_provider: "EmbeddingProvider | None" = None,
        llm_provider: "Any | None" = None,
        min_score: float = 0.4,
        max_sources: int = 10,
        freshness_max_age_days: int = 730,
        domain_allow_list: list[str] | None = None,
        domain_block_list: list[str] | None = None,
        scoring_weights: "ScoringWeights | None" = None,
    ) -> None:
        """
        Args:
            scraper: Scraper for lightweight snippet extraction.
            embedding_provider: Optional; for content relevance scoring.
            llm_provider: Optional; for LLM judgment scoring (FAST_LLM).
            min_score: Minimum composite score to pass (default: 0.4).
            max_sources: Maximum URLs to return (default: 10).
            freshness_max_age_days: Content older than this is penalized (default: 730).
            domain_allow_list: Domains that receive a boosted authority score.
            domain_block_list: Domains that receive authority score of 0.
            scoring_weights: Custom signal weights. Defaults to ScoringWeights().
        """
        ...

    async def curate(                                     # NEW
        self,
        results: "list[SearchResult]",
        query: str,
    ) -> "list[SearchResult]":
        """Score and filter a list of search results.

        Steps:
            1. Snippet-scrape each URL (lightweight, ~500 chars)
            2. Score each URL on all configured signals
            3. Compute composite score
            4. Discard URLs below min_score
            5. Sort by composite score descending
            6. Return top max_sources

        Args:
            results: Raw search results from retrievers.
            query: The original search query (used for relevance scoring).

        Returns:
            Filtered and ranked list of SearchResult.
            Length is min(len(passing_results), max_sources).
        """
        ...

    async def score_single(                               # NEW
        self,
        url: str,
        snippet: str,
        query: str,
    ) -> SourceScore:
        """Score a single URL against all signals.

        This is the per-URL scoring logic used by curate().

        Args:
            url: Source URL.
            snippet: Extracted text snippet from the URL.
            query: Original search query.

        Returns:
            SourceScore with all signal scores and composite.
        """
        ...


# --- Signal Scorers (internal) ---

def score_domain_authority(                               # NEW
    url: str,
    allow_list: list[str] | None = None,
    block_list: list[str] | None = None,
) -> float:
    """Score domain authority based on allow/block lists.

    - Block list match -> 0.0
    - Allow list match -> 1.0
    - Unknown domain -> 0.5 (neutral)

    Args:
        url: Source URL.
        allow_list: Boosted domains.
        block_list: Blocked domains.

    Returns:
        Score between 0.0 and 1.0.
    """
    ...


async def score_content_relevance(                        # NEW
    snippet: str,
    query: str,
    embedding_provider: "EmbeddingProvider",
) -> float:
    """Score content relevance via cosine similarity.

    Embeds the snippet and query, returns cosine similarity.

    Args:
        snippet: Extracted text snippet.
        query: Original search query.
        embedding_provider: Provider to generate embeddings.

    Returns:
        Cosine similarity between 0.0 and 1.0.
    """
    ...


def score_freshness(                                      # NEW
    published_date: str | None,
    max_age_days: int = 730,
) -> float:
    """Score content freshness based on publication date.

    - Within max_age_days: linear decay from 1.0 to 0.3
    - Beyond max_age_days: 0.3 (floor)
    - No date available: 0.5 (neutral)

    Args:
        published_date: ISO date string or None.
        max_age_days: Maximum age before receiving minimum score.

    Returns:
        Score between 0.3 and 1.0.
    """
    ...


async def score_llm_judgment(                             # NEW
    snippet: str,
    query: str,
    llm_provider: "Any",
) -> float:
    """Score content quality via LLM judgment.

    Uses FAST_LLM tier to rate quality on a 1-10 scale,
    then normalizes to 0.0 - 1.0.

    Args:
        snippet: Extracted text snippet.
        query: Original search query (for relevance context).
        llm_provider: LLM provider (FAST_LLM tier).

    Returns:
        Normalized quality score between 0.0 and 1.0.
    """
    ...
