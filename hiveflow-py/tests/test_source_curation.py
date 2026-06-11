"""Unit tests for source curation pipeline."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from hiveflow.core.source_curation import (
    SourceCurationPipeline,
    SourceScore,
    score_domain_authority,
    score_freshness,
)


class TestScoreDomainAuthority:
    def test_blocked_domain(self):
        assert score_domain_authority(
            "https://pinterest.com/pin/123", block_list=["pinterest.com"]
        ) == 0.0

    def test_allowed_domain(self):
        assert score_domain_authority(
            "https://nature.com/articles/123", allow_list=["nature.com"]
        ) == 1.0

    def test_unknown_domain(self):
        assert score_domain_authority("https://example.com/page") == 0.5

    def test_www_stripped(self):
        assert score_domain_authority(
            "https://www.pinterest.com/pin", block_list=["pinterest.com"]
        ) == 0.0


class TestScoreFreshness:
    def test_no_date_neutral(self):
        assert score_freshness(None) == 0.5

    def test_recent_content_high_score(self):
        from datetime import datetime, timezone
        recent = datetime.now(timezone.utc).isoformat()
        score = score_freshness(recent)
        assert score > 0.9

    def test_old_content_low_score(self):
        score = score_freshness("2020-01-01T00:00:00+00:00", max_age_days=730)
        assert score == 0.3  # Beyond max age

    def test_invalid_date_neutral(self):
        assert score_freshness("not-a-date") == 0.5


class TestSourceCurationPipeline:
    def _make_result(self, url, content="some content", score=0.5, published_date=None):
        result = MagicMock()
        result.url = url
        result.content = content
        result.score = score
        result.metadata = {"published_date": published_date}
        return result

    async def test_curate_filters_by_min_score(self):
        pipeline = SourceCurationPipeline(
            min_score=0.4,
            max_sources=10,
            domain_block_list=["bad.com"],
        )

        results = [
            self._make_result("https://good.com/article", content="relevant"),
            self._make_result("https://bad.com/spam", content="spam"),
        ]

        curated = await pipeline.curate(results, "test query")

        urls = [r.url for r in curated]
        assert "https://bad.com/spam" not in urls

    async def test_curate_respects_max_sources(self):
        pipeline = SourceCurationPipeline(max_sources=2)

        results = [
            self._make_result(f"https://example.com/{i}", content=f"content {i}")
            for i in range(10)
        ]

        curated = await pipeline.curate(results, "test query")
        assert len(curated) <= 2

    async def test_curate_empty_input(self):
        pipeline = SourceCurationPipeline()
        curated = await pipeline.curate([], "test")
        assert curated == []

    async def test_curate_with_embedding_provider(self):
        mock_emb = AsyncMock()
        mock_emb.embed = AsyncMock(
            return_value=[[0.9, 0.1], [1.0, 0.0]]  # snippet, query
        )

        pipeline = SourceCurationPipeline(
            embedding_provider=mock_emb,
            min_score=0.0,
        )

        results = [self._make_result("https://example.com", content="relevant")]
        curated = await pipeline.curate(results, "test query")
        assert len(curated) == 1

    async def test_curate_with_llm_provider(self):
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(return_value="8")

        pipeline = SourceCurationPipeline(
            llm_provider=mock_llm,
            min_score=0.0,
        )

        results = [self._make_result("https://example.com", content="quality content")]
        curated = await pipeline.curate(results, "test query")
        assert len(curated) == 1

    async def test_reweighting_without_embedding_provider(self):
        """Without embedding provider, remaining weights are reweighted."""
        pipeline = SourceCurationPipeline(
            embedding_provider=None,
            llm_provider=None,
            min_score=0.0,
        )

        result = self._make_result("https://example.com")
        score = await pipeline.score_single("https://example.com", "snippet", "query")

        # Should still produce a composite score from domain + freshness
        assert score.composite_score > 0.0
        assert score.content_relevance == 0.0
        assert score.llm_judgment == 0.0

    async def test_score_single_all_signals(self):
        mock_emb = AsyncMock()
        mock_emb.embed = AsyncMock(
            return_value=[[0.7, 0.7], [0.7, 0.7]]  # high similarity
        )
        mock_llm = AsyncMock()
        mock_llm.generate = AsyncMock(return_value="7")

        pipeline = SourceCurationPipeline(
            embedding_provider=mock_emb,
            llm_provider=mock_llm,
            domain_allow_list=["example.com"],
        )

        score = await pipeline.score_single(
            "https://example.com/article",
            "great content",
            "find quality articles",
        )

        assert score.domain_authority == 1.0
        assert score.content_relevance > 0.0
        assert score.llm_judgment == 0.7
        assert score.composite_score > 0.0
