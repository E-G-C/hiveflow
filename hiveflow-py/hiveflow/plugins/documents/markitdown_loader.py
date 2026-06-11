"""Universal document loader using Microsoft MarkItDown.

Converts documents to Markdown text, which is ideal for LLM consumption.
Supports PDF, DOCX, PPTX, XLSX, XLS, HTML, CSV, TSV, JSON, XML, EPUB, and ZIP.

Install with: pip install 'markitdown[all]'
"""

from pathlib import Path

from hiveflow.plugins.documents import Document, DocumentLoaderPlugin


class MarkItDownLoader(DocumentLoaderPlugin):
    """Universal loader that converts documents to Markdown via MarkItDown."""

    @property
    def plugin_id(self) -> str:
        return "markitdown"

    @property
    def description(self) -> str:
        return "Universal document loader using Microsoft MarkItDown"

    @property
    def supported_extensions(self) -> list[str]:
        return [
            ".pdf",
            ".docx",
            ".pptx",
            ".xlsx",
            ".xls",
            ".html",
            ".htm",
            ".csv",
            ".tsv",
            ".json",
            ".xml",
            ".epub",
            ".zip",
        ]

    async def load(self, file_path: str | Path) -> Document:
        try:
            from markitdown import MarkItDown
        except ImportError as exc:
            raise ImportError(
                "markitdown is required for universal document conversion. "
                "Install with: pip install 'markitdown[all]'"
            ) from exc

        path = Path(file_path)
        md = MarkItDown(enable_plugins=False)
        result = md.convert(str(path))
        content = result.text_content or ""

        return Document(
            content=content,
            source=str(path),
            metadata={
                "filename": path.name,
                "size_bytes": path.stat().st_size,
                "converter": "markitdown",
            },
        )
