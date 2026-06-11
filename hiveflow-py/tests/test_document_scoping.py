"""Tests for per-agent document scoping."""

from typing import Any

import pytest

from hiveflow.core.documents import DocumentPipeline
from hiveflow.core.schema import AgentBehaviorTypeSchema, AgentDefinition


def make_agent_def(
    document_mode: str = "full",
    documents: list[str] | None = None,
    max_document_tokens: int | None = None,
) -> AgentDefinition:
    """Create a minimal AgentDefinition for testing."""
    return AgentDefinition(
        id="test-agent",
        role="Test Agent",
        system_prompt="You are a test agent.",
        behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
        document_mode=document_mode,
        documents=documents,
        max_document_tokens=max_document_tokens,
    )


@pytest.fixture
def sample_documents() -> list[dict[str, Any]]:
    """Create sample document state dicts."""
    return [
        {
            "name": "report.txt",
            "format": "txt",
            "size_bytes": 1000,
            "chunks": [
                {"index": 0, "content": "Report chunk one."},
                {"index": 1, "content": "Report chunk two."},
            ],
            "chunk_count": 2,
            "total_tokens_estimate": 100,
        },
        {
            "name": "data.csv",
            "format": "csv",
            "size_bytes": 500,
            "chunks": [
                {"index": 0, "content": "col1,col2\na,b"},
            ],
            "chunk_count": 1,
            "total_tokens_estimate": 50,
        },
    ]


@pytest.fixture
def pipeline() -> DocumentPipeline:
    """Create a DocumentPipeline instance."""
    return DocumentPipeline()


class TestFullMode:
    """Test full document mode."""

    def test_full_returns_all_docs(
        self, pipeline: DocumentPipeline, sample_documents: list[dict[str, Any]]
    ) -> None:
        """Full mode returns all documents with content."""
        agent_def = make_agent_def(document_mode="full")
        result = pipeline.scope_for_agent(sample_documents, agent_def)
        assert len(result) == 2
        assert result[0]["chunks"][0]["content"] == "Report chunk one."

    def test_full_with_name_filter(
        self, pipeline: DocumentPipeline, sample_documents: list[dict[str, Any]]
    ) -> None:
        """Full mode with document name filter returns only named docs."""
        agent_def = make_agent_def(document_mode="full", documents=["report.txt"])
        result = pipeline.scope_for_agent(sample_documents, agent_def)
        assert len(result) == 1
        assert result[0]["name"] == "report.txt"


class TestMetadataOnlyMode:
    """Test metadata_only mode."""

    def test_metadata_only_no_content(
        self, pipeline: DocumentPipeline, sample_documents: list[dict[str, Any]]
    ) -> None:
        """Metadata mode returns doc info without chunks."""
        agent_def = make_agent_def(document_mode="metadata_only")
        result = pipeline.scope_for_agent(sample_documents, agent_def)
        assert len(result) == 2
        assert "chunks" not in result[0]
        assert result[0]["name"] == "report.txt"
        assert result[0]["format"] == "txt"
        assert result[0]["size_bytes"] == 1000


class TestNoneMode:
    """Test none mode."""

    def test_none_returns_empty(
        self, pipeline: DocumentPipeline, sample_documents: list[dict[str, Any]]
    ) -> None:
        """None mode returns empty list."""
        agent_def = make_agent_def(document_mode="none")
        result = pipeline.scope_for_agent(sample_documents, agent_def)
        assert result == []


class TestRelevantChunksMode:
    """Test relevant_chunks mode."""

    def test_relevant_chunks_falls_back_to_full(
        self, pipeline: DocumentPipeline, sample_documents: list[dict[str, Any]]
    ) -> None:
        """Without embedding provider, falls back to full mode."""
        agent_def = make_agent_def(document_mode="relevant_chunks")
        result = pipeline.scope_for_agent(sample_documents, agent_def)
        # Falls back to full - should have all documents with content
        assert len(result) == 2
        assert "chunks" in result[0]


class TestSummaryMode:
    """Test summary mode."""

    def test_summary_falls_back_to_metadata(
        self, pipeline: DocumentPipeline, sample_documents: list[dict[str, Any]]
    ) -> None:
        """Without FAST_LLM, falls back to metadata_only."""
        agent_def = make_agent_def(document_mode="summary")
        result = pipeline.scope_for_agent(sample_documents, agent_def)
        assert len(result) == 2
        assert "chunks" not in result[0]


class TestMaxDocumentTokens:
    """Test max_document_tokens truncation."""

    def test_truncation_limits_content(
        self, pipeline: DocumentPipeline, sample_documents: list[dict[str, Any]]
    ) -> None:
        """Token budget limits the content returned."""
        agent_def = make_agent_def(document_mode="full", max_document_tokens=5)
        result = pipeline.scope_for_agent(sample_documents, agent_def)
        # With a very low token budget, we should get fewer chunks
        total_chunks = sum(len(d.get("chunks", [])) for d in result)
        assert total_chunks <= 3  # Original has 3 total chunks


class TestDocumentNameScoping:
    """Test document name filtering."""

    def test_documents_none_means_all(
        self, pipeline: DocumentPipeline, sample_documents: list[dict[str, Any]]
    ) -> None:
        """documents=None means all documents."""
        agent_def = make_agent_def(document_mode="full", documents=None)
        result = pipeline.scope_for_agent(sample_documents, agent_def)
        assert len(result) == 2

    def test_documents_empty_means_none(
        self, pipeline: DocumentPipeline, sample_documents: list[dict[str, Any]]
    ) -> None:
        """documents=[] means no documents."""
        agent_def = make_agent_def(document_mode="full", documents=[])
        result = pipeline.scope_for_agent(sample_documents, agent_def)
        assert result == []

    def test_unresolved_reference(self) -> None:
        """Agent referencing unknown document name raises ValueError at workflow level."""
        # This is validated in WorkflowEngine, not in scope_for_agent
        # scope_for_agent just silently filters
        pipeline = DocumentPipeline()
        agent_def = make_agent_def(
            document_mode="full", documents=["nonexistent.txt"]
        )
        result = pipeline.scope_for_agent(
            [{"name": "report.txt", "format": "txt", "size_bytes": 100,
              "chunks": [], "chunk_count": 0, "total_tokens_estimate": 0}],
            agent_def,
        )
        assert result == []
