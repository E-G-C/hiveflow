"""Tests for summary document mode: LLM generation, caching, fallback."""

from unittest.mock import AsyncMock
from typing import Any

import pytest

from hiveflow.core.documents import DocumentPipeline


def _make_doc(name: str, content: str) -> dict[str, Any]:
    """Create a minimal document state dict."""
    return {
        "name": name,
        "format": "txt",
        "size_bytes": len(content.encode()),
        "chunk_count": 1,
        "total_tokens_estimate": len(content.split()) * 2,
        "chunks": [{"index": 0, "content": content}],
    }


class MockLLMResponse:
    def __init__(self, content: str):
        self.content = content


class TestGenerateSummaries:
    """DocumentPipeline.generate_summaries() with LLM."""

    async def test_generates_summary(self):
        provider = AsyncMock()
        provider.chat.return_value = MockLLMResponse("This is a summary.")

        pipeline = DocumentPipeline()
        docs = [_make_doc("report.txt", "Long document content here with many words.")]
        state: dict[str, Any] = {}

        result = await pipeline.generate_summaries(docs, state, provider)
        assert "report.txt" in result
        assert result["report.txt"] == "This is a summary."
        provider.chat.assert_called_once()

    async def test_caching_avoids_duplicate_calls(self):
        provider = AsyncMock()
        provider.chat.return_value = MockLLMResponse("Cached summary.")

        pipeline = DocumentPipeline()
        docs = [_make_doc("report.txt", "Content here.")]
        state: dict[str, Any] = {}

        await pipeline.generate_summaries(docs, state, provider)
        assert provider.chat.call_count == 1

        # Second call should use cache — no additional LLM call
        await pipeline.generate_summaries(docs, state, provider)
        assert provider.chat.call_count == 1

    async def test_fallback_on_llm_failure(self):
        provider = AsyncMock()
        provider.chat.side_effect = RuntimeError("LLM unavailable")

        pipeline = DocumentPipeline()
        docs = [_make_doc("report.txt", "Content.")]
        state: dict[str, Any] = {}

        result = await pipeline.generate_summaries(docs, state, provider)
        assert "report.txt" in result
        assert "report.txt" in result["report.txt"]  # Metadata fallback

    async def test_empty_document_summary(self):
        provider = AsyncMock()
        pipeline = DocumentPipeline()
        docs = [_make_doc("empty.txt", "")]
        docs[0]["chunks"] = [{"index": 0, "content": ""}]
        state: dict[str, Any] = {}

        result = await pipeline.generate_summaries(docs, state, provider)
        assert "empty.txt" in result
        assert "Empty document" in result["empty.txt"]
        provider.chat.assert_not_called()  # No LLM call for empty doc


class TestScopeForAgentSummary:
    """scope_for_agent() with document_mode='summary'."""

    def test_returns_summary_chunk_when_cached(self):
        pipeline = DocumentPipeline()

        class MockAgentDef:
            documents = None
            document_mode = "summary"
            max_document_tokens = None

        docs = [_make_doc("report.txt", "Original long content here.")]
        state = {"_document_summaries": {"report.txt": "Brief summary."}}

        result = pipeline.scope_for_agent(docs, MockAgentDef(), state=state)
        assert len(result) == 1
        assert result[0]["chunks"][0]["content"] == "Brief summary."
        assert result[0]["chunk_count"] == 1

    def test_falls_back_to_metadata_without_cache(self):
        pipeline = DocumentPipeline()

        class MockAgentDef:
            documents = None
            document_mode = "summary"
            max_document_tokens = None

        docs = [_make_doc("report.txt", "Content.")]
        # No _document_summaries in state
        result = pipeline.scope_for_agent(docs, MockAgentDef(), state={})
        assert len(result) == 1
        assert "chunks" not in result[0]  # metadata_only fallback
