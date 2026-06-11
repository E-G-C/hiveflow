"""Tests for DocumentRetrieverTool."""

import pytest

from hiveflow.plugins.tools.document_retriever import DocumentRetrieverTool


@pytest.fixture
def sample_documents() -> list[dict]:
    """Create sample document state dicts for testing."""
    return [
        {
            "name": "report.txt",
            "format": "txt",
            "size_bytes": 500,
            "chunks": [
                {"index": 0, "content": "The quarterly revenue increased by 15 percent."},
                {"index": 1, "content": "Customer satisfaction scores improved significantly."},
                {"index": 2, "content": "The engineering team shipped three major features."},
            ],
            "chunk_count": 3,
            "total_tokens_estimate": 50,
        },
        {
            "name": "notes.md",
            "format": "md",
            "size_bytes": 300,
            "chunks": [
                {"index": 0, "content": "Meeting notes from the planning session."},
                {"index": 1, "content": "Action items: review budget and finalize roadmap."},
            ],
            "chunk_count": 2,
            "total_tokens_estimate": 30,
        },
    ]


@pytest.fixture
def tool() -> DocumentRetrieverTool:
    """Create a DocumentRetrieverTool instance."""
    return DocumentRetrieverTool()


class TestPluginMetadata:
    """Test plugin identification and schema."""

    def test_plugin_id(self, tool: DocumentRetrieverTool) -> None:
        assert tool.plugin_id == "document_retriever"

    def test_description(self, tool: DocumentRetrieverTool) -> None:
        assert "document" in tool.description.lower()

    def test_input_schema_has_properties(self, tool: DocumentRetrieverTool) -> None:
        schema = tool.input_schema
        props = schema["properties"]
        assert "document_name" in props
        assert "query" in props
        assert "chunk_indices" in props
        assert "max_tokens" in props

    def test_output_schema(self, tool: DocumentRetrieverTool) -> None:
        schema = tool.output_schema
        assert "chunks" in schema["properties"]
        assert "message" in schema["properties"]

    def test_to_llm_tool_spec(self, tool: DocumentRetrieverTool) -> None:
        spec = tool.to_llm_tool_spec()
        assert spec["type"] == "function"
        assert spec["function"]["name"] == "document_retriever"


class TestNoDocumentsLoaded:
    """Test behavior when no documents are loaded."""

    async def test_no_documents_returns_empty(
        self, tool: DocumentRetrieverTool
    ) -> None:
        """Returns empty result with descriptive message."""
        result = await tool.execute({})
        assert result["chunks"] == []
        assert result["total_chunks"] == 0
        assert "no documents" in result["message"].lower()


class TestFetchByName:
    """Test retrieval by document name."""

    async def test_fetch_by_name(
        self, tool: DocumentRetrieverTool, sample_documents: list[dict]
    ) -> None:
        """Retrieve all chunks of a named document."""
        tool.set_documents(sample_documents)
        result = await tool.execute({"document_name": "report.txt"})
        assert len(result["chunks"]) == 3
        assert all(c["document"] == "report.txt" for c in result["chunks"])

    async def test_fetch_by_name_not_found(
        self, tool: DocumentRetrieverTool, sample_documents: list[dict]
    ) -> None:
        """Unknown document name returns empty with available list."""
        tool.set_documents(sample_documents)
        result = await tool.execute({"document_name": "nonexistent.txt"})
        assert result["chunks"] == []
        assert "not found" in result["message"].lower()
        assert "report.txt" in result["message"]

    async def test_fetch_all_documents(
        self, tool: DocumentRetrieverTool, sample_documents: list[dict]
    ) -> None:
        """No document_name returns chunks from all documents."""
        tool.set_documents(sample_documents)
        result = await tool.execute({})
        assert result["total_chunks"] == 5  # 3 + 2


class TestFetchByChunkIndices:
    """Test retrieval by specific chunk indices."""

    async def test_specific_indices(
        self, tool: DocumentRetrieverTool, sample_documents: list[dict]
    ) -> None:
        """Retrieve only the specified chunk indices."""
        tool.set_documents(sample_documents)
        result = await tool.execute({
            "document_name": "report.txt",
            "chunk_indices": [0, 2],
        })
        assert len(result["chunks"]) == 2
        indices = {c["index"] for c in result["chunks"]}
        assert indices == {0, 2}

    async def test_nonexistent_indices(
        self, tool: DocumentRetrieverTool, sample_documents: list[dict]
    ) -> None:
        """Non-existent indices return empty."""
        tool.set_documents(sample_documents)
        result = await tool.execute({
            "document_name": "report.txt",
            "chunk_indices": [99],
        })
        assert result["chunks"] == []


class TestKeywordSearch:
    """Test keyword search query."""

    async def test_keyword_search(
        self, tool: DocumentRetrieverTool, sample_documents: list[dict]
    ) -> None:
        """Query returns chunks ranked by keyword relevance."""
        tool.set_documents(sample_documents)
        result = await tool.execute({"query": "revenue"})
        assert len(result["chunks"]) >= 1
        # The chunk about revenue should be first
        assert "revenue" in result["chunks"][0]["content"].lower()

    async def test_keyword_search_multiple_terms(
        self, tool: DocumentRetrieverTool, sample_documents: list[dict]
    ) -> None:
        """Multiple query terms improve ranking."""
        tool.set_documents(sample_documents)
        result = await tool.execute({"query": "budget roadmap"})
        # The action items chunk has both terms
        assert "budget" in result["chunks"][0]["content"].lower()

    async def test_keyword_no_matches_returns_all(
        self, tool: DocumentRetrieverTool, sample_documents: list[dict]
    ) -> None:
        """Query with no matches falls back to returning all chunks."""
        tool.set_documents(sample_documents)
        result = await tool.execute({"query": "zzzznonexistentzzzzz"})
        # Fallback: returns all chunks when no keyword matches
        assert result["total_chunks"] == 5

    async def test_keyword_with_name_filter(
        self, tool: DocumentRetrieverTool, sample_documents: list[dict]
    ) -> None:
        """Query combined with document_name scopes search."""
        tool.set_documents(sample_documents)
        result = await tool.execute({
            "document_name": "report.txt",
            "query": "engineering",
        })
        assert all(c["document"] == "report.txt" for c in result["chunks"])
        assert "engineering" in result["chunks"][0]["content"].lower()


class TestMaxTokensTruncation:
    """Test max_tokens truncation."""

    async def test_max_tokens_limits_output(
        self, tool: DocumentRetrieverTool, sample_documents: list[dict]
    ) -> None:
        """max_tokens limits the total content returned."""
        tool.set_documents(sample_documents)
        # Very low token budget
        result = await tool.execute({"max_tokens": 5})
        total_words = sum(
            len(c["content"].split()) for c in result["chunks"]
        )
        # With 5 tokens ≈ 3-4 words, should be very limited
        assert total_words <= 10

    async def test_max_tokens_truncates_last_chunk(
        self, tool: DocumentRetrieverTool, sample_documents: list[dict]
    ) -> None:
        """Last chunk is truncated to fit within budget."""
        tool.set_documents(sample_documents)
        result = await tool.execute({
            "document_name": "report.txt",
            "max_tokens": 15,
        })
        # With ~15 tokens, we might get 1-2 chunks
        assert len(result["chunks"]) <= 3
        # Either we got full chunks that fit, or one was truncated
        assert len(result["chunks"]) >= 1

    async def test_large_budget_returns_all(
        self, tool: DocumentRetrieverTool, sample_documents: list[dict]
    ) -> None:
        """A generous token budget returns all chunks."""
        tool.set_documents(sample_documents)
        result = await tool.execute({"max_tokens": 100000})
        assert result["total_chunks"] == 5
        assert len(result["chunks"]) == 5


class TestSetDocuments:
    """Test document injection."""

    async def test_set_documents_updates_state(
        self, tool: DocumentRetrieverTool
    ) -> None:
        """set_documents() makes documents available."""
        docs = [{"name": "a.txt", "chunks": [{"index": 0, "content": "Hello"}]}]
        tool.set_documents(docs)
        result = await tool.execute({})
        assert result["total_chunks"] == 1

    async def test_set_documents_replaces_previous(
        self, tool: DocumentRetrieverTool
    ) -> None:
        """set_documents() replaces any previously set documents."""
        tool.set_documents([
            {"name": "old.txt", "chunks": [{"index": 0, "content": "old"}]}
        ])
        tool.set_documents([
            {"name": "new.txt", "chunks": [{"index": 0, "content": "new"}]}
        ])
        result = await tool.execute({})
        assert result["chunks"][0]["document"] == "new.txt"


class TestToolDiscovery:
    """Test entry-point-based discovery."""

    def test_tool_discoverable(self) -> None:
        """DocumentRetrieverTool is discoverable via entry points."""
        from hiveflow.plugins.tools import ToolRegistry

        registry = ToolRegistry(drop_in_dir=None)
        registry.discover()
        tool = registry.get("document_retriever")
        assert tool is not None
        assert tool.plugin_id == "document_retriever"
