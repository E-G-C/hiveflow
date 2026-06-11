"""XML document loader using defusedxml for safe parsing."""

import xml.etree.ElementTree as ET
from pathlib import Path

try:
    import defusedxml.ElementTree as SafeET
except ImportError:
    SafeET = None  # type: ignore[assignment]

from hiveflow.plugins.documents import Document, DocumentLoaderPlugin


class XMLLoader(DocumentLoaderPlugin):
    """Loader for XML files using stdlib xml.etree."""

    @property
    def plugin_id(self) -> str:
        return "xml"

    @property
    def description(self) -> str:
        return "XML file loader"

    @property
    def supported_extensions(self) -> list[str]:
        return [".xml"]

    async def load(self, file_path: str | Path) -> Document:
        path = Path(file_path)
        parser = SafeET if SafeET is not None else ET
        tree = parser.parse(str(path))
        root = tree.getroot()

        content = self._extract_text(root)

        return Document(
            content=content,
            source=str(path),
            metadata={
                "filename": path.name,
                "size_bytes": path.stat().st_size,
                "root_tag": root.tag,
            },
        )

    def _extract_text(self, element: ET.Element, depth: int = 0) -> str:
        """Recursively extract text from XML elements."""
        parts: list[str] = []
        indent = "  " * depth
        tag = element.tag.split("}")[-1] if "}" in element.tag else element.tag

        text = (element.text or "").strip()
        tail = (element.tail or "").strip()

        children = list(element)
        if children:
            parts.append(f"{indent}<{tag}>")
            if text:
                parts.append(f"{indent}  {text}")
            for child in children:
                parts.append(self._extract_text(child, depth + 1))
            parts.append(f"{indent}</{tag}>")
        elif text:
            parts.append(f"{indent}<{tag}> {text} </{tag}>")

        if tail:
            parts.append(f"{indent}{tail}")

        return "\n".join(parts)
