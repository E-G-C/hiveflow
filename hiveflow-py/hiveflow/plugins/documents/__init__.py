"""Document Loader System - Load and parse various document formats.

Supports PDF, DOCX, PPTX, CSV, Excel, and plain text files with
text extraction and optional chunking for LLM context windows.
"""

from abc import abstractmethod
from pathlib import Path
from typing import Any

import structlog

from hiveflow.core.registry import BasePlugin, PluginRegistry

logger = structlog.get_logger()


class Document:
    """A loaded document with text content and metadata."""

    def __init__(
        self,
        content: str,
        source: str,
        metadata: dict[str, Any] | None = None,
        name: str = "",
        format: str = "",
        size_bytes: int = 0,
        total_tokens_estimate: int = 0,
    ) -> None:
        self.content = content
        self.source = source
        self.metadata = metadata or {}
        self.name = name
        self.format = format
        self.size_bytes = size_bytes
        self.total_tokens_estimate = total_tokens_estimate
        self.chunks: list[DocumentChunk] = []

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "content": self.content,
            "source": self.source,
            "metadata": self.metadata,
        }

    def to_state_dict(self) -> dict[str, Any]:
        """Convert to state dictionary for workflow state injection."""
        return {
            "name": self.name,
            "format": self.format,
            "size_bytes": self.size_bytes,
            "chunks": [chunk.to_state_dict() for chunk in self.chunks],
            "chunk_count": len(self.chunks),
            "total_tokens_estimate": self.total_tokens_estimate,
        }

    @property
    def word_count(self) -> int:
        """Approximate word count."""
        return len(self.content.split())


class DocumentChunk:
    """A chunk of a document for LLM context windows."""

    def __init__(
        self,
        content: str,
        source: str,
        chunk_index: int,
        total_chunks: int,
        metadata: dict[str, Any] | None = None,
        token_estimate: int = 0,
    ) -> None:
        self.content = content
        self.source = source
        self.chunk_index = chunk_index
        self.total_chunks = total_chunks
        self.metadata = metadata or {}
        self.token_estimate = token_estimate

    def to_state_dict(self) -> dict[str, Any]:
        """Convert to state dictionary for workflow state injection."""
        return {
            "index": self.chunk_index,
            "content": self.content,
        }


class DocumentLoaderPlugin(BasePlugin):
    """Base class for document loader plugins."""

    @property
    @abstractmethod
    def plugin_id(self) -> str:
        """Loader identifier (e.g., 'pdf', 'docx')."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description."""
        ...

    @property
    @abstractmethod
    def supported_extensions(self) -> list[str]:
        """File extensions this loader handles (e.g., ['.pdf', '.PDF'])."""
        ...

    @abstractmethod
    async def load(self, file_path: str | Path) -> Document:
        """Load and parse a document.

        Args:
            file_path: Path to the document file

        Returns:
            Parsed Document
        """
        ...

    async def load_from_bytes(self, data: bytes, filename: str) -> Document:
        """Load a document from in-memory bytes.

        Default implementation writes to a temp file and delegates to load().
        Subclasses may override for direct byte-stream processing.

        Args:
            data: Raw file bytes.
            filename: Original filename (for extension detection and naming).

        Returns:
            Parsed Document.

        Raises:
            ValueError: If data is empty (zero-length bytes).
        """
        if not data:
            raise ValueError(f"Empty document data for '{filename}'")

        import tempfile

        suffix = Path(filename).suffix
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix=suffix, delete=False, prefix="hiveflow_"
            ) as tmp:
                tmp.write(data)
                tmp_path = tmp.name
            return await self.load(tmp_path)
        finally:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)


from hiveflow.plugins.documents.plain_text import PlainTextLoader  # noqa: F811, E402

__all__ = [
    "Document",
    "DocumentChunk",
    "DocumentLoaderPlugin",
    "PlainTextLoader",
    "DocumentLoaderRegistry",
    "chunk_text",
]


class DocumentLoaderRegistry(PluginRegistry["DocumentLoaderPlugin"]):
    """Registry for document loader plugins."""

    def __init__(self, drop_in_dir: str | None = "document_loaders") -> None:
        super().__init__(
            entry_point_group="hiveflow.document_loaders",
            drop_in_dir=drop_in_dir,
        )

    def get_loader_for_file(self, file_path: str | Path) -> DocumentLoaderPlugin | None:
        """Find appropriate loader for a file based on extension.

        Args:
            file_path: Path to the file

        Returns:
            Matching loader or None
        """
        ext = Path(file_path).suffix.lower()
        for plugin_id in self.list_ids():
            loader = self.get(plugin_id)
            if loader and ext in loader.supported_extensions:
                return loader
        return None

    def get_all_loaders_for_file(self, file_path: str | Path) -> list[DocumentLoaderPlugin]:
        """Find all loaders that support a file's extension.

        Returns loaders in alphabetical plugin_id order, allowing callers
        to try each one until one succeeds (fallback pattern).

        Args:
            file_path: Path to the file

        Returns:
            List of matching loaders (may be empty)
        """
        ext = Path(file_path).suffix.lower()
        loaders = []
        for plugin_id in self.list_ids():
            loader = self.get(plugin_id)
            if loader and ext in loader.supported_extensions:
                loaders.append(loader)
        return loaders


def chunk_text(
    text: str,
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
) -> list[str]:
    """Split text into overlapping chunks by word count.

    Args:
        text: Text to chunk
        chunk_size: Target words per chunk
        chunk_overlap: Words to overlap between chunks

    Returns:
        List of text chunks
    """
    words = text.split()
    if len(words) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(words):
        end = start + chunk_size
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        start += chunk_size - chunk_overlap

    return chunks
