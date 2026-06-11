"""Document retriever tool for on-demand document content retrieval.

Allows tool-using agents to fetch document content during execution
by name, keyword query, or chunk index.
"""

from typing import Any

import structlog

from hiveflow.plugins.tools import ToolPlugin

logger = structlog.get_logger()


class DocumentRetrieverTool(ToolPlugin):
    """Tool plugin for on-demand document content retrieval.

    Reads from documents loaded into workflow state, supporting
    retrieval by document name, keyword search, and chunk indices.
    """

    def __init__(self) -> None:
        self._documents: list[dict[str, Any]] = []

    @property
    def plugin_id(self) -> str:
        return "document_retriever"

    @property
    def description(self) -> str:
        return (
            "Retrieve content from loaded documents. Search by document name, "
            "keyword query, or specific chunk indices. Use this to look up "
            "information from attached documents during your reasoning."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "document_name": {
                    "type": "string",
                    "description": "Name of a specific document to retrieve.",
                },
                "query": {
                    "type": "string",
                    "description": (
                        "Keyword search query to find relevant chunks "
                        "across all (or named) documents."
                    ),
                },
                "chunk_indices": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "Specific chunk indices to retrieve.",
                },
                "max_tokens": {
                    "type": "integer",
                    "description": "Maximum approximate tokens in the response.",
                },
            },
            "additionalProperties": False,
        }

    @property
    def output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "chunks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "document": {"type": "string"},
                            "index": {"type": "integer"},
                            "content": {"type": "string"},
                        },
                    },
                },
                "total_chunks": {"type": "integer"},
                "message": {"type": "string"},
            },
        }

    def set_documents(self, documents: list[dict[str, Any]]) -> None:
        """Set the documents available for retrieval.

        Called by the agent before tool execution to inject the
        current workflow state documents.

        Args:
            documents: List of document state dicts from state["documents"]
        """
        self._documents = documents

    async def execute(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        """Execute document retrieval.

        Args:
            tool_input: Parameters matching input_schema

        Returns:
            Result with matching chunks and metadata
        """
        if not self._documents:
            return {
                "chunks": [],
                "total_chunks": 0,
                "message": "No documents are loaded in the current workflow.",
            }

        document_name: str | None = tool_input.get("document_name")
        query: str | None = tool_input.get("query")
        chunk_indices: list[int] | None = tool_input.get("chunk_indices")
        max_tokens: int | None = tool_input.get("max_tokens")

        # Filter documents by name if specified
        if document_name:
            docs = [d for d in self._documents if d.get("name") == document_name]
            if not docs:
                available = [d.get("name", "?") for d in self._documents]
                return {
                    "chunks": [],
                    "total_chunks": 0,
                    "message": (
                        f"Document '{document_name}' not found. Available documents: {available}"
                    ),
                }
        else:
            docs = self._documents

        # Collect all chunks from matching documents
        chunks: list[dict[str, Any]] = []
        for doc in docs:
            doc_name = doc.get("name", "unknown")
            for chunk in doc.get("chunks", []):
                chunks.append(
                    {
                        "document": doc_name,
                        "index": chunk.get("index", 0),
                        "content": chunk.get("content", ""),
                    }
                )

        # Filter by chunk indices if specified
        if chunk_indices is not None:
            index_set = set(chunk_indices)
            chunks = [c for c in chunks if c["index"] in index_set]

        # Apply keyword search if query is provided
        if query:
            chunks = self._keyword_search(chunks, query)

        total_before_truncation = len(chunks)

        # Apply token limit if specified
        if max_tokens is not None:
            chunks = self._apply_token_limit(chunks, max_tokens)

        return {
            "chunks": chunks,
            "total_chunks": total_before_truncation,
            "message": f"Retrieved {len(chunks)} chunk(s).",
        }

    def _keyword_search(self, chunks: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
        """Rank chunks by keyword relevance.

        Scores each chunk by counting how many query terms appear in
        its content. Returns chunks sorted by score descending.
        If no chunks match any terms, returns all chunks unchanged
        (graceful fallback).

        Args:
            chunks: Candidate chunks to search
            query: Space-separated search terms

        Returns:
            Chunks ranked by relevance, or all chunks if no matches
        """
        query_terms = query.lower().split()
        if not query_terms:
            return chunks

        scored: list[tuple[int, dict[str, Any]]] = []
        for chunk in chunks:
            content_lower = chunk["content"].lower()
            score = sum(1 for term in query_terms if term in content_lower)
            if score > 0:
                scored.append((score, chunk))

        if not scored:
            # No keyword matches — return all chunks as fallback
            return chunks

        scored.sort(key=lambda x: x[0], reverse=True)
        return [chunk for _, chunk in scored]

    def _apply_token_limit(
        self, chunks: list[dict[str, Any]], max_tokens: int
    ) -> list[dict[str, Any]]:
        """Truncate chunks to fit within an approximate token budget.

        Uses word_count / 0.75 as the token estimation heuristic
        (consistent with DocumentPipeline).

        Args:
            chunks: Ordered chunks to include
            max_tokens: Maximum approximate token budget

        Returns:
            Chunks fitting within the budget, last chunk possibly truncated
        """
        result: list[dict[str, Any]] = []
        tokens_used = 0

        for chunk in chunks:
            content = chunk["content"]
            words = content.split()
            estimated_tokens = len(words) / 0.75

            if tokens_used + estimated_tokens <= max_tokens:
                result.append(chunk)
                tokens_used += estimated_tokens
            else:
                # Fit a partial chunk if meaningful space remains
                remaining_tokens = max_tokens - tokens_used
                remaining_words = int(remaining_tokens * 0.75)
                if remaining_words > 5:
                    truncated = " ".join(words[:remaining_words]) + " [truncated]"
                    result.append({**chunk, "content": truncated})
                break

        return result
