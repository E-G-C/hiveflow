"""Tests for citation config integration (MLA, Chicago, config-driven activation)."""

import pytest

from hiveflow.core.citations import Citation, CitationTracker
from hiveflow.core.schema import CitationConfig


class TestCitationFormats:
    """Tests for MLA and Chicago citation format methods."""

    @pytest.fixture
    def citation(self):
        return Citation(
            url="https://example.com/article",
            title="Test Article",
            author="Smith, J.",
            date="2025",
            source="Example Journal",
        )

    def test_format_mla(self, citation):
        mla = citation.format_mla()
        assert "Smith, J." in mla
        assert '"Test Article."' in mla
        assert "*Example Journal*" in mla
        assert "https://example.com/article" in mla

    def test_format_chicago(self, citation):
        chicago = citation.format_chicago()
        assert "Smith, J." in chicago
        assert '"Test Article."' in chicago
        assert "Last modified 2025" in chicago
        assert "https://example.com/article" in chicago

    def test_format_apa_still_works(self, citation):
        apa = citation.format_apa()
        assert "Smith, J." in apa
        assert "(2025)" in apa
        assert "Retrieved from" in apa


class TestCitationTrackerStyles:
    """Tests for format_references with all styles."""

    @pytest.fixture
    def tracker_with_citations(self):
        tracker = CitationTracker()
        tracker.add(Citation(
            url="https://example.com/1",
            title="Article One",
            author="Author A",
            date="2024",
            source="Journal A",
        ))
        tracker.add(Citation(
            url="https://example.com/2",
            title="Article Two",
            author="Author B",
            date="2025",
            source="Journal B",
        ))
        return tracker

    def test_format_references_apa(self, tracker_with_citations):
        refs = tracker_with_citations.format_references(style="apa")
        assert "## References" in refs
        assert "Retrieved from" in refs

    def test_format_references_mla(self, tracker_with_citations):
        refs = tracker_with_citations.format_references(style="mla")
        assert "## References" in refs
        assert '"Article One."' in refs

    def test_format_references_chicago(self, tracker_with_citations):
        refs = tracker_with_citations.format_references(style="chicago")
        assert "## References" in refs
        assert "Last modified" in refs

    def test_format_references_numbered(self, tracker_with_citations):
        refs = tracker_with_citations.format_references(style="numbered")
        assert "1." in refs
        assert "2." in refs

    def test_format_references_inline(self, tracker_with_citations):
        refs = tracker_with_citations.format_references(style="inline")
        assert "[" in refs


class TestCitationConfig:
    """Tests for CitationConfig model."""

    def test_defaults(self):
        config = CitationConfig()
        assert config.enabled is False
        assert config.style == "apa"
        assert config.inline is True
        assert config.generate_reference_section is True

    def test_enabled_config(self):
        config = CitationConfig(enabled=True, style="mla", inline=False)
        assert config.enabled is True
        assert config.style == "mla"
        assert config.inline is False

    def test_deduplication(self):
        """Same URL added twice should only appear once."""
        tracker = CitationTracker()
        c1 = Citation(url="https://example.com/same", title="First")
        c2 = Citation(url="https://example.com/same", title="Second")
        tracker.add(c1)
        tracker.add(c2)
        assert tracker.count == 1
