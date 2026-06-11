"""Plain text document loader."""

from pathlib import Path

from hiveflow.plugins.documents import Document, DocumentLoaderPlugin


class PlainTextLoader(DocumentLoaderPlugin):
    """Built-in loader for plain text files."""

    @property
    def plugin_id(self) -> str:
        return "text"

    @property
    def description(self) -> str:
        return "Plain text file loader"

    @property
    def supported_extensions(self) -> list[str]:
        return [".txt", ".text", ".log", ".csv", ".tsv"]

    async def load(self, file_path: str | Path) -> Document:
        path = Path(file_path)
        content = path.read_text(encoding="utf-8")
        return Document(
            content=content,
            source=str(path),
            metadata={"filename": path.name, "size_bytes": path.stat().st_size},
        )
