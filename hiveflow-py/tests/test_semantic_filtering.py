"""End-to-end tests for semantic filtering pipeline (relevant_chunks mode)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from hiveflow.core.documents import DocumentPipeline


class TestSemanticFiltering:
    """Tests for the relevant_chunks document mode with semantic filtering."""

    def _make_doc(self, name, chunks):
        """Helper to create a document dict with chunks."""
        return {
            "name": name,
            "format": "txt",
            "size_bytes": 1000,
            "chunk_count": len(chunks),
            "total_tokens_estimate": len(chunks) * 100,
            "chunks": [
                {"index": i, "content": text} for i, text in enumerate(chunks)
            ],
        }

    def _make_agent(self, mode="relevant_chunks", documents=None, max_tokens=None):
        """Helper to create a mock agent definition."""
        agent = MagicMock()
        agent.id = "test-agent"
        agent.document_mode = mode
        agent.documents = documents
        agent.max_document_tokens = max_tokens
        return agent

    async def test_relevant_chunks_with_embedding_provider(self):
        """Chunks above similarity threshold are kept."""
        mock_provider = AsyncMock()
        mock_provider.embed_single = AsyncMock(return_value=[1.0, 0.0, 0.0])
        # 3 chunks: one very similar, one medium, one orthogonal
        mock_provider.embed = AsyncMock(
            return_value=[
                [0.9, 0.1, 0.0],  # high similarity
                [0.5, 0.5, 0.5],  # medium similarity
                [0.0, 0.0, 1.0],  # low similarity
            ]
        )

        pipeline = DocumentPipeline(
            embedding_provider=mock_provider,
            similarity_threshold=0.5,
        )

        doc = self._make_doc("test.txt", ["very relevant", "somewhat relevant", "irrelevant"])
        agent = self._make_agent(mode="relevant_chunks")

        scoped = pipeline.scope_for_agent([doc], agent, task="find relevant info")
        result = await pipeline.filter_relevant_chunks(scoped)

        assert len(result) == 1  # one document
        # Should have filtered out the orthogonal chunk
        chunks = result[0]["chunks"]
        assert len(chunks) < 3

    async def test_relevant_chunks_fallback_without_provider(self):
        """Falls back to full mode when no embedding provider configured."""
        pipeline = DocumentPipeline(embedding_provider=None)

        doc = self._make_doc("test.txt", ["chunk 1", "chunk 2"])
        agent = self._make_agent(mode="relevant_chunks")

        scoped = pipeline.scope_for_agent([doc], agent, task="test task")

        # Without provider, should return all chunks (full mode fallback)
        assert len(scoped) == 1
        assert len(scoped[0]["chunks"]) == 2

    async def test_relevant_chunks_fallback_without_task(self):
        """Falls back to full mode when no task string provided."""
        mock_provider = AsyncMock()
        pipeline = DocumentPipeline(embedding_provider=mock_provider)

        doc = self._make_doc("test.txt", ["chunk 1"])
        agent = self._make_agent(mode="relevant_chunks")

        scoped = pipeline.scope_for_agent([doc], agent, task="")
        # No task = falls back to full mode
        assert len(scoped) == 1

    async def test_higher_threshold_fewer_chunks(self):
        """Raising threshold keeps fewer chunks."""
        mock_provider = AsyncMock()
        mock_provider.embed_single = AsyncMock(return_value=[1.0, 0.0])
        mock_provider.embed = AsyncMock(
            return_value=[
                [0.9, 0.1],  # sim ~0.99
                [0.5, 0.5],  # sim ~0.71
                [0.1, 0.9],  # sim ~0.11
            ]
        )

        # Low threshold: keeps more
        pipeline_low = DocumentPipeline(
            embedding_provider=mock_provider,
            similarity_threshold=0.3,
        )
        doc = self._make_doc("t.txt", ["a", "b", "c"])
        agent = self._make_agent()
        scoped = pipeline_low.scope_for_agent([doc], agent, task="q")
        result_low = await pipeline_low.filter_relevant_chunks(scoped)

        # High threshold: keeps fewer
        pipeline_high = DocumentPipeline(
            embedding_provider=mock_provider,
            similarity_threshold=0.9,
        )
        doc2 = self._make_doc("t.txt", ["a", "b", "c"])
        scoped2 = pipeline_high.scope_for_agent([doc2], agent, task="q")
        result_high = await pipeline_high.filter_relevant_chunks(scoped2)

        low_count = len(result_low[0]["chunks"])
        high_count = len(result_high[0]["chunks"])
        assert high_count <= low_count

    async def test_source_attribution_preserved(self):
        """Filtered chunks retain source document metadata."""
        mock_provider = AsyncMock()
        mock_provider.embed_single = AsyncMock(return_value=[1.0, 0.0])
        mock_provider.embed = AsyncMock(return_value=[[0.9, 0.1]])

        pipeline = DocumentPipeline(
            embedding_provider=mock_provider,
            similarity_threshold=0.3,
        )

        doc = self._make_doc("source.txt", ["relevant content"])
        agent = self._make_agent()
        scoped = pipeline.scope_for_agent([doc], agent, task="query")
        result = await pipeline.filter_relevant_chunks(scoped)

        assert result[0]["name"] == "source.txt"
        assert result[0]["format"] == "txt"

    async def test_multiple_source_documents(self):
        """Filtering works across multiple source documents."""
        mock_provider = AsyncMock()
        mock_provider.embed_single = AsyncMock(return_value=[1.0, 0.0])
        mock_provider.embed = AsyncMock(
            side_effect=[
                [[0.9, 0.1]],  # doc1 chunk passes
                [[0.0, 1.0]],  # doc2 chunk fails
            ]
        )

        pipeline = DocumentPipeline(
            embedding_provider=mock_provider,
            similarity_threshold=0.5,
        )

        doc1 = self._make_doc("good.txt", ["relevant"])
        doc2 = self._make_doc("bad.txt", ["irrelevant"])
        agent = self._make_agent()
        scoped = pipeline.scope_for_agent([doc1, doc2], agent, task="query")
        result = await pipeline.filter_relevant_chunks(scoped)

        # doc1 passes, doc2 gets all chunks kept (fallback when nothing passes)
        names = [d["name"] for d in result]
        assert "good.txt" in names

    async def test_embedding_failure_graceful_fallback(self):
        """If embedding fails, falls back to full content."""
        mock_provider = AsyncMock()
        mock_provider.embed_single = AsyncMock(side_effect=RuntimeError("API down"))

        pipeline = DocumentPipeline(
            embedding_provider=mock_provider,
            similarity_threshold=0.3,
        )

        doc = self._make_doc("test.txt", ["chunk 1", "chunk 2"])
        agent = self._make_agent()
        scoped = pipeline.scope_for_agent([doc], agent, task="query")
        result = await pipeline.filter_relevant_chunks(scoped)

        # Should gracefully return all chunks
        assert len(result) == 1
        assert len(result[0]["chunks"]) == 2
