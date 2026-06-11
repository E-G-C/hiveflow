"""Source Curation Pipeline - Multi-signal credibility scoring and filtering.

Scores and filters retriever results before committing to full content
extraction, using domain authority, content relevance, freshness, and
LLM judgment signals.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class SourceScore:
    """Credibility score for a single source URL."""

    url: str
    domain_authority: float = 0.0
    content_relevance: float = 0.0
    freshness: float = 0.0
    llm_judgment: float = 0.0
    composite_score: float = 0.0


def score_domain_authority(
    url: str,
    allow_list: list[str] | None = None,
    block_list: list[str] | None = None,
) -> float:
    """Score domain authority based on allow/block lists.

    - Block list match -> 0.0
    - Allow list match -> 1.0
    - Unknown domain -> 0.5 (neutral)
    """
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    # Strip www. prefix
    if domain.startswith("www."):
        domain = domain[4:]

    if block_list:
        for blocked in block_list:
            if blocked.lower() in domain:
                return 0.0

    if allow_list:
        for allowed in allow_list:
            if allowed.lower() in domain:
                return 1.0

    return 0.5


def score_freshness(
    published_date: str | None,
    max_age_days: int = 730,
) -> float:
    """Score content freshness based on publication date.

    - Within max_age_days: linear decay from 1.0 to 0.3
    - Beyond max_age_days: 0.3 (floor)
    - No date available: 0.5 (neutral)
    """
    if not published_date:
        return 0.5

    try:
        pub_dt = datetime.fromisoformat(published_date.replace("Z", "+00:00"))
        now = datetime.now(UTC)
        age_days = (now - pub_dt).days

        if age_days < 0:
            return 1.0
        if age_days >= max_age_days:
            return 0.3

        # Linear decay from 1.0 to 0.3
        return 1.0 - (age_days / max_age_days) * 0.7
    except (ValueError, TypeError):
        return 0.5


async def score_content_relevance(
    snippet: str,
    query: str,
    embedding_provider: Any,
) -> float:
    """Score content relevance via cosine similarity of embeddings."""
    try:
        embeddings = await embedding_provider.embed([snippet, query])
        snippet_vec = embeddings[0]
        query_vec = embeddings[1]

        # Cosine similarity
        dot = sum(a * b for a, b in zip(snippet_vec, query_vec))
        norm_a = sum(a * a for a in snippet_vec) ** 0.5
        norm_b = sum(b * b for b in query_vec) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return max(0.0, dot / (norm_a * norm_b))
    except Exception:
        logger.warning("content_relevance scoring failed", exc_info=True)
        return 0.5


async def score_llm_judgment(
    snippet: str,
    query: str,
    llm_provider: Any,
) -> float:
    """Score content quality via LLM judgment (1-10 scale, normalized to 0-1)."""
    try:
        prompt = (
            f"Rate the quality and relevance of this content snippet for the query "
            f"'{query}' on a scale of 1-10. Reply with ONLY a number.\n\n"
            f"Content: {snippet[:500]}"
        )
        response = await llm_provider.generate(prompt)
        text = str(response).strip()
        # Extract first number
        match = re.search(r"\d+", text)
        if match:
            score = int(match.group())
            return min(1.0, max(0.0, score / 10.0))
        return 0.5
    except Exception:
        logger.warning("llm_judgment scoring failed", exc_info=True)
        return 0.5


class SourceCurationPipeline:
    """Multi-signal source credibility scoring and filtering."""

    def __init__(
        self,
        scraper: Any = None,
        embedding_provider: Any = None,
        llm_provider: Any = None,
        min_score: float = 0.4,
        max_sources: int = 10,
        freshness_max_age_days: int = 730,
        domain_allow_list: list[str] | None = None,
        domain_block_list: list[str] | None = None,
        scoring_weights: Any = None,
    ) -> None:
        self._scraper = scraper
        self._embedding_provider = embedding_provider
        self._llm_provider = llm_provider
        self.min_score = min_score
        self.max_sources = max_sources
        self.freshness_max_age_days = freshness_max_age_days
        self.domain_allow_list = domain_allow_list or []
        self.domain_block_list = domain_block_list or []

        # Default weights
        if scoring_weights is not None:
            self._weights = {
                "domain_authority": getattr(scoring_weights, "domain_authority", 0.25),
                "content_relevance": getattr(scoring_weights, "content_relevance", 0.30),
                "freshness": getattr(scoring_weights, "freshness", 0.15),
                "llm_judgment": getattr(scoring_weights, "llm_judgment", 0.30),
            }
        else:
            self._weights = {
                "domain_authority": 0.25,
                "content_relevance": 0.30,
                "freshness": 0.15,
                "llm_judgment": 0.30,
            }

    async def curate(
        self,
        results: list[Any],
        query: str,
    ) -> list[Any]:
        """Score and filter a list of search results.

        Args:
            results: Raw search results from retrievers.
            query: The original search query.

        Returns:
            Filtered and ranked list of SearchResult.
        """
        if not results:
            return []

        scores: list[tuple[Any, SourceScore]] = []

        for result in results:
            url = getattr(result, "url", "")
            snippet = getattr(result, "content", "")
            published_date = (getattr(result, "metadata", {}) or {}).get("published_date")

            source_score = await self.score_single(url, snippet, query, published_date)
            scores.append((result, source_score))

        # Filter by min_score
        passing = [(r, s) for r, s in scores if s.composite_score >= self.min_score]

        # Sort by composite score descending
        passing.sort(key=lambda x: x[1].composite_score, reverse=True)

        # Cap at max_sources
        passing = passing[: self.max_sources]

        logger.info(
            "source_curation.complete",
            total=len(results),
            passing=len(passing),
            min_score=self.min_score,
        )

        return [r for r, _ in passing]

    async def score_single(
        self,
        url: str,
        snippet: str,
        query: str,
        published_date: str | None = None,
    ) -> SourceScore:
        """Score a single URL against all signals."""
        source = SourceScore(url=url)

        # Domain authority (always available)
        source.domain_authority = score_domain_authority(
            url, self.domain_allow_list, self.domain_block_list
        )

        # Freshness (always available)
        source.freshness = score_freshness(published_date, self.freshness_max_age_days)

        # Content relevance (needs embedding provider)
        active_weights = dict(self._weights)
        if self._embedding_provider is not None and snippet:
            source.content_relevance = await score_content_relevance(
                snippet, query, self._embedding_provider
            )
        else:
            # Skip content relevance, reweight
            source.content_relevance = 0.0
            relevance_weight = active_weights.pop("content_relevance", 0.0)
            total_remaining = sum(active_weights.values())
            if total_remaining > 0:
                for key in active_weights:
                    active_weights[key] *= 1.0 + relevance_weight / total_remaining

        # LLM judgment (needs LLM provider)
        if self._llm_provider is not None and snippet:
            source.llm_judgment = await score_llm_judgment(snippet, query, self._llm_provider)
        else:
            source.llm_judgment = 0.0
            llm_weight = active_weights.pop("llm_judgment", 0.0)
            total_remaining = sum(active_weights.values())
            if total_remaining > 0:
                for key in active_weights:
                    active_weights[key] *= 1.0 + llm_weight / total_remaining

        # Composite score
        source.composite_score = (
            active_weights.get("domain_authority", 0) * source.domain_authority
            + active_weights.get("content_relevance", 0) * source.content_relevance
            + active_weights.get("freshness", 0) * source.freshness
            + active_weights.get("llm_judgment", 0) * source.llm_judgment
        )

        return source
