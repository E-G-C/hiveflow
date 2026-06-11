"""HTML document loader using beautifulsoup4."""

from pathlib import Path

from hiveflow.plugins.documents import Document, DocumentLoaderPlugin


class HTMLLoader(DocumentLoaderPlugin):
    """Loader for HTML files using beautifulsoup4."""

    @property
    def plugin_id(self) -> str:
        return "html"

    @property
    def description(self) -> str:
        return "HTML file loader using beautifulsoup4"

    @property
    def supported_extensions(self) -> list[str]:
        return [".html", ".htm"]

    async def load(self, file_path: str | Path) -> Document:
        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:
            raise ImportError(
                "beautifulsoup4 is required for HTML support. "
                "Install with: pip install beautifulsoup4"
            ) from exc

        path = Path(file_path)
        raw = path.read_text(encoding="utf-8")
        soup = BeautifulSoup(raw, "html.parser")

        # Remove script, style, nav, and footer elements
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        # Extract main content (prefer <main> or <article> if present)
        main = soup.find("main") or soup.find("article") or soup.find("body") or soup
        content = main.get_text(separator="\n", strip=True)

        return Document(
            content=content,
            source=str(path),
            metadata={
                "filename": path.name,
                "size_bytes": path.stat().st_size,
                "title": soup.title.string if soup.title else None,
            },
        )
