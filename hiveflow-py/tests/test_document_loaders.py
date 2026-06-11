"""Unit tests for document format loaders."""

import json
from pathlib import Path

import pytest

from hiveflow.plugins.documents import Document


class TestMarkdownLoader:
    """Tests for MarkdownLoader."""

    async def test_load_markdown(self, tmp_path: Path) -> None:
        from hiveflow.plugins.documents.markdown_loader import MarkdownLoader

        (tmp_path / "test.md").write_text("# Title\n\nSome content.\n\n## Section\n\nMore text.")
        loader = MarkdownLoader()
        doc = await loader.load(tmp_path / "test.md")
        assert isinstance(doc, Document)
        assert "Title" in doc.content
        assert "Section" in doc.content
        assert doc.metadata["headings"] == ["Title", "Section"]

    def test_supported_extensions(self) -> None:
        from hiveflow.plugins.documents.markdown_loader import MarkdownLoader

        loader = MarkdownLoader()
        assert ".md" in loader.supported_extensions
        assert ".markdown" in loader.supported_extensions

    def test_plugin_id(self) -> None:
        from hiveflow.plugins.documents.markdown_loader import MarkdownLoader

        assert MarkdownLoader().plugin_id == "markdown"


class TestJSONLoader:
    """Tests for JSONLoader."""

    async def test_load_json(self, tmp_path: Path) -> None:
        from hiveflow.plugins.documents.json_loader import JSONLoader

        data = {"key": "value", "nested": {"a": 1}}
        (tmp_path / "test.json").write_text(json.dumps(data))
        loader = JSONLoader()
        doc = await loader.load(tmp_path / "test.json")
        assert isinstance(doc, Document)
        assert "key" in doc.content
        assert "value" in doc.content
        # Verify it's pretty-printed
        parsed = json.loads(doc.content)
        assert parsed == data

    async def test_load_jsonl(self, tmp_path: Path) -> None:
        from hiveflow.plugins.documents.json_loader import JSONLoader

        lines = ['{"a": 1}', '{"b": 2}']
        (tmp_path / "test.jsonl").write_text("\n".join(lines))
        loader = JSONLoader()
        doc = await loader.load(tmp_path / "test.jsonl")
        assert "---" in doc.content  # JSONL separator

    def test_supported_extensions(self) -> None:
        from hiveflow.plugins.documents.json_loader import JSONLoader

        loader = JSONLoader()
        assert ".json" in loader.supported_extensions
        assert ".jsonl" in loader.supported_extensions


class TestXMLLoader:
    """Tests for XMLLoader."""

    async def test_load_xml(self, tmp_path: Path) -> None:
        from hiveflow.plugins.documents.xml_loader import XMLLoader

        xml_content = "<root><item>Hello</item><item>World</item></root>"
        (tmp_path / "test.xml").write_text(xml_content)
        loader = XMLLoader()
        doc = await loader.load(tmp_path / "test.xml")
        assert isinstance(doc, Document)
        assert "Hello" in doc.content
        assert "World" in doc.content
        assert doc.metadata["root_tag"] == "root"

    def test_supported_extensions(self) -> None:
        from hiveflow.plugins.documents.xml_loader import XMLLoader

        assert ".xml" in XMLLoader().supported_extensions


class TestPDFLoader:
    """Tests for PDFLoader."""

    def test_plugin_id(self) -> None:
        from hiveflow.plugins.documents.pdf_loader import PDFLoader

        assert PDFLoader().plugin_id == "pdf"

    def test_supported_extensions(self) -> None:
        from hiveflow.plugins.documents.pdf_loader import PDFLoader

        assert ".pdf" in PDFLoader().supported_extensions

    async def test_import_error_message(self, tmp_path: Path) -> None:
        """Verify graceful error when pymupdf is not installed."""
        # This test validates the import error path.
        # If pymupdf IS installed, this will just load normally.
        from hiveflow.plugins.documents.pdf_loader import PDFLoader

        loader = PDFLoader()
        # We can only test the error if pymupdf is NOT installed
        try:
            import pymupdf  # noqa: F401
            pytest.skip("pymupdf is installed, cannot test import error path")
        except ImportError:
            with pytest.raises(ImportError, match="pymupdf"):
                await loader.load(tmp_path / "nonexist.pdf")


class TestDocxLoader:
    """Tests for DocxLoader."""

    def test_plugin_id(self) -> None:
        from hiveflow.plugins.documents.docx_loader import DocxLoader

        assert DocxLoader().plugin_id == "docx"

    def test_supported_extensions(self) -> None:
        from hiveflow.plugins.documents.docx_loader import DocxLoader

        assert ".docx" in DocxLoader().supported_extensions


class TestPptxLoader:
    """Tests for PptxLoader."""

    def test_plugin_id(self) -> None:
        from hiveflow.plugins.documents.pptx_loader import PptxLoader

        assert PptxLoader().plugin_id == "pptx"

    def test_supported_extensions(self) -> None:
        from hiveflow.plugins.documents.pptx_loader import PptxLoader

        assert ".pptx" in PptxLoader().supported_extensions


class TestExcelLoader:
    """Tests for ExcelLoader."""

    def test_plugin_id(self) -> None:
        from hiveflow.plugins.documents.excel_loader import ExcelLoader

        assert ExcelLoader().plugin_id == "excel"

    def test_supported_extensions(self) -> None:
        from hiveflow.plugins.documents.excel_loader import ExcelLoader

        exts = ExcelLoader().supported_extensions
        assert ".xlsx" in exts


class TestHTMLLoader:
    """Tests for HTMLLoader."""

    def test_plugin_id(self) -> None:
        from hiveflow.plugins.documents.html_loader import HTMLLoader

        assert HTMLLoader().plugin_id == "html"

    def test_supported_extensions(self) -> None:
        from hiveflow.plugins.documents.html_loader import HTMLLoader

        exts = HTMLLoader().supported_extensions
        assert ".html" in exts
        assert ".htm" in exts

    async def test_load_html(self, tmp_path: Path) -> None:
        """Test loading HTML content (requires beautifulsoup4)."""
        try:
            from bs4 import BeautifulSoup  # noqa: F401
        except ImportError:
            pytest.skip("beautifulsoup4 not installed")

        from hiveflow.plugins.documents.html_loader import HTMLLoader

        html = "<html><head><title>Test</title></head><body><p>Hello World</p></body></html>"
        (tmp_path / "test.html").write_text(html)
        loader = HTMLLoader()
        doc = await loader.load(tmp_path / "test.html")
        assert "Hello World" in doc.content
        assert doc.metadata["title"] == "Test"


class TestPlainTextLoader:
    """Tests for PlainTextLoader."""

    async def test_load_text(self, tmp_path: Path) -> None:
        from hiveflow.plugins.documents.plain_text import PlainTextLoader

        (tmp_path / "readme.txt").write_text("Hello, world!", encoding="utf-8")
        loader = PlainTextLoader()
        doc = await loader.load(tmp_path / "readme.txt")
        assert isinstance(doc, Document)
        assert doc.content == "Hello, world!"
        assert doc.metadata["filename"] == "readme.txt"
        assert doc.metadata["size_bytes"] > 0

    def test_supported_extensions(self) -> None:
        from hiveflow.plugins.documents.plain_text import PlainTextLoader

        loader = PlainTextLoader()
        assert ".txt" in loader.supported_extensions
        assert ".log" in loader.supported_extensions
        assert ".csv" in loader.supported_extensions

    def test_plugin_id(self) -> None:
        from hiveflow.plugins.documents.plain_text import PlainTextLoader

        loader = PlainTextLoader()
        assert loader.plugin_id == "text"


class TestLoaderRegistration:
    """Test that all loaders can be discovered via entry points."""

    def test_registry_discovers_loaders(self) -> None:
        """Registry discovers registered loaders."""
        from hiveflow.plugins.documents import DocumentLoaderRegistry

        registry = DocumentLoaderRegistry()
        registry.discover()
        ids = registry.list_ids()
        # At minimum, text should always be available
        assert "text" in ids

    def test_markdown_loader_discoverable(self) -> None:
        """Markdown loader is discoverable via entry points."""
        from hiveflow.plugins.documents import DocumentLoaderRegistry

        registry = DocumentLoaderRegistry()
        registry.discover()
        loader = registry.get_loader_for_file("test.md")
        assert loader is not None
        assert loader.plugin_id == "markdown"

    def test_json_loader_discoverable(self) -> None:
        """JSON loader is discoverable via entry points."""
        from hiveflow.plugins.documents import DocumentLoaderRegistry

        registry = DocumentLoaderRegistry()
        registry.discover()
        loader = registry.get_loader_for_file("test.json")
        assert loader is not None
        assert loader.plugin_id == "json"

    def test_xml_loader_discoverable(self) -> None:
        """XML loader is discoverable via entry points."""
        from hiveflow.plugins.documents import DocumentLoaderRegistry

        registry = DocumentLoaderRegistry()
        registry.discover()
        loader = registry.get_loader_for_file("test.xml")
        assert loader is not None
        assert loader.plugin_id in ("xml", "markitdown")
