"""Markdown document loader."""

import re
from pathlib import Path

from hiveflow.plugins.documents import Document, DocumentLoaderPlugin


class MarkdownLoader(DocumentLoaderPlugin):
    """Loader for Markdown files that splits on heading boundaries."""

    @property
    def plugin_id(self) -> str:
        return "markdown"

    @property
    def description(self) -> str:
        return "Markdown file loader with heading-aware splitting"

    @property
    def supported_extensions(self) -> list[str]:
        return [".md", ".markdown", ".mdown", ".mkd"]

    async def load(self, file_path: str | Path) -> Document:
        path = Path(file_path)
        content = path.read_text(encoding="utf-8")
        return Document(
            content=content,
            source=str(path),
            metadata={
                "filename": path.name,
                "size_bytes": path.stat().st_size,
                "headings": self._extract_headings(content),
            },
        )

    def _extract_headings(self, content: str) -> list[str]:
        """Extract markdown headings for metadata."""
        return re.findall(r"^#{1,6}\s+(.+)$", content, re.MULTILINE)
