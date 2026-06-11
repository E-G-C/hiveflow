"""PDF document loader using pymupdf."""

from pathlib import Path

from hiveflow.plugins.documents import Document, DocumentLoaderPlugin


class PDFLoader(DocumentLoaderPlugin):
    """Loader for PDF files using pymupdf."""

    @property
    def plugin_id(self) -> str:
        return "pdf"

    @property
    def description(self) -> str:
        return "PDF file loader using pymupdf"

    @property
    def supported_extensions(self) -> list[str]:
        return [".pdf"]

    async def load(self, file_path: str | Path) -> Document:
        try:
            import pymupdf
        except ImportError as exc:
            raise ImportError(
                "pymupdf is required for PDF support. Install with: pip install pymupdf"
            ) from exc

        path = Path(file_path)
        pages: list[str] = []
        with pymupdf.open(str(path)) as doc:
            for i, page in enumerate(doc):
                text = page.get_text()
                if text.strip():
                    pages.append(f"[Page {i + 1}]\n{text}")

        content = "\n\n".join(pages)
        return Document(
            content=content,
            source=str(path),
            metadata={
                "filename": path.name,
                "size_bytes": path.stat().st_size,
                "page_count": len(pages),
            },
        )
