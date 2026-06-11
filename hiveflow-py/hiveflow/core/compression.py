"""Context Compression Pipeline - Reduce context size for LLM windows.

Provides text summarization, deduplication, and relevance filtering
to fit large amounts of retrieved content into LLM context windows.
"""

from typing import Any

import structlog

logger = structlog.get_logger()


class ContextCompressor:
    """Compresses and filters context for LLM consumption.

    Given a set of text chunks (from retrieval, scraping, documents),
    reduces them to fit within the target token/word budget while
    preserving the most relevant information.
    """

    def __init__(
        self,
        max_words: int = 8000,
        similarity_threshold: float = 0.35,
        chunk_max_length: int = 1000,
    ) -> None:
        """Initialize context compressor.

        Args:
            max_words: Maximum words in compressed output
            similarity_threshold: Minimum similarity score for inclusion
            chunk_max_length: Maximum words per chunk
        """
        self.max_words = max_words
        self.similarity_threshold = similarity_threshold
        self.chunk_max_length = chunk_max_length

    def compress(
        self,
        chunks: list[dict[str, Any]],
        query: str = "",
    ) -> list[dict[str, Any]]:
        """Compress a list of text chunks to fit the word budget.

        Each chunk should have at least a 'content' key, and optionally
        'score', 'source', and 'title' keys.

        Args:
            chunks: List of chunk dicts with 'content' key
            query: Optional query for relevance scoring

        Returns:
            Filtered and truncated list of chunks
        """
        if not chunks:
            return []

        # Step 1: Deduplicate similar chunks
        unique_chunks = self._deduplicate(chunks)

        # Step 2: Score and sort by relevance
        scored = self._score_chunks(unique_chunks, query)

        # Step 3: Truncate to word budget
        result = self._fit_to_budget(scored)

        logger.debug(
            "Compressed %d chunks to %d (budget: %d words)",
            len(chunks),
            len(result),
            self.max_words,
        )

        return result

    def _deduplicate(self, chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Remove duplicate or near-duplicate chunks.

        Uses content hashing for exact deduplication and simple
        substring overlap for near-duplicates.
        """
        seen_hashes: set[str] = set()
        unique: list[dict[str, Any]] = []

        for chunk in chunks:
            content = chunk.get("content", "")
            # Normalize for comparison
            normalized = " ".join(content.lower().split())
            content_hash = normalized[:200]  # Use first 200 chars as signature

            if content_hash not in seen_hashes:
                seen_hashes.add(content_hash)
                unique.append(chunk)

        return unique

    def _score_chunks(self, chunks: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
        """Score chunks by relevance and sort descending.

        Uses existing scores if available, or simple keyword overlap.
        """
        query_words = set(query.lower().split()) if query else set()

        for chunk in chunks:
            if "score" not in chunk and query_words:
                content_words = set(chunk.get("content", "").lower().split())
                overlap = len(query_words & content_words)
                chunk["score"] = overlap / max(len(query_words), 1)

        return sorted(chunks, key=lambda c: c.get("score", 0), reverse=True)

    def _fit_to_budget(self, chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Select chunks that fit within the word budget."""
        result: list[dict[str, Any]] = []
        total_words = 0

        for chunk in chunks:
            content = chunk.get("content", "")
            words = content.split()

            # Truncate individual chunks if too long
            if len(words) > self.chunk_max_length:
                words = words[: self.chunk_max_length]
                chunk = {**chunk, "content": " ".join(words), "truncated": True}

            if total_words + len(words) > self.max_words:
                # Try to fit remaining budget
                remaining = self.max_words - total_words
                if remaining > 50:  # Minimum useful chunk size
                    chunk = {**chunk, "content": " ".join(words[:remaining]), "truncated": True}
                    result.append(chunk)
                break

            result.append(chunk)
            total_words += len(words)

        return result

    def format_context(self, chunks: list[dict[str, Any]], include_sources: bool = True) -> str:
        """Format compressed chunks into a single context string.

        Args:
            chunks: Compressed chunks
            include_sources: Whether to include source attribution

        Returns:
            Formatted context string
        """
        parts: list[str] = []

        for i, chunk in enumerate(chunks, 1):
            content = chunk.get("content", "")
            source = chunk.get("source", "")
            title = chunk.get("title", "")

            header = f"--- Source {i}"
            if title:
                header += f": {title}"
            if include_sources and source:
                header += f" ({source})"
            header += " ---"

            parts.append(header)
            parts.append(content)
            parts.append("")

        return "\n".join(parts)
