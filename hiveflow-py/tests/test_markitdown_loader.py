"""Tests for MarkItDown loader and loader fallback mechanism."""

from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip("markitdown", reason="markitdown not installed")

from hiveflow.core.documents import DocumentPipeline
from hiveflow.plugins.documents import DocumentLoaderRegistry


# ---------------------------------------------------------------------------
# MarkItDownLoader unit tests
# ---------------------------------------------------------------------------
class TestMarkItDownLoader:
    """Tests for the MarkItDown-based universal loader."""

    def test_plugin_metadata(self):
        from hiveflow.plugins.documents.markitdown_loader import MarkItDownLoader

        loader = MarkItDownLoader()
        assert loader.plugin_id == "markitdown"
        assert "MarkItDown" in loader.description
        assert ".docx" in loader.supported_extensions
        assert ".pdf" in loader.supported_extensions
        assert ".pptx" in loader.supported_extensions
        assert ".xlsx" in loader.supported_extensions
        assert ".csv" in loader.supported_extensions
        assert ".epub" in loader.supported_extensions

    async def test_load_txt_file(self, tmp_path: Path):
        """MarkItDown can load plain text files."""
        from hiveflow.plugins.documents.markitdown_loader import MarkItDownLoader

        txt_file = tmp_path / "sample.csv"
        txt_file.write_text("name,age,city\nAlice,30,NYC\nBob,25,LA\n")

        loader = MarkItDownLoader()
        doc = await loader.load(txt_file)
        assert doc.content
        assert "Alice" in doc.content
        assert doc.metadata["converter"] == "markitdown"
        assert doc.metadata["filename"] == "sample.csv"

    async def test_load_json_file(self, tmp_path: Path):
        """MarkItDown converts JSON to markdown."""
        from hiveflow.plugins.documents.markitdown_loader import MarkItDownLoader

        json_file = tmp_path / "data.json"
        json_file.write_text('{"name": "Alice", "role": "Engineer"}')

        loader = MarkItDownLoader()
        doc = await loader.load(json_file)
        assert doc.content
        assert "Alice" in doc.content

    async def test_load_xml_file(self, tmp_path: Path):
        """MarkItDown converts XML to markdown."""
        from hiveflow.plugins.documents.markitdown_loader import MarkItDownLoader

        xml_file = tmp_path / "data.xml"
        xml_file.write_text(
            '<?xml version="1.0"?><root><item>Hello</item></root>'
        )

        loader = MarkItDownLoader()
        doc = await loader.load(xml_file)
        assert doc.content
        assert "Hello" in doc.content

    async def test_load_html_file(self, tmp_path: Path):
        """MarkItDown converts HTML to markdown."""
        from hiveflow.plugins.documents.markitdown_loader import MarkItDownLoader

        html_file = tmp_path / "page.html"
        html_file.write_text(
            "<html><body><h1>Title</h1><p>Paragraph text.</p></body></html>"
        )

        loader = MarkItDownLoader()
        doc = await loader.load(html_file)
        assert doc.content
        assert "Title" in doc.content
        assert "Paragraph" in doc.content

    async def test_import_error_when_missing(self):
        """Clear error message when markitdown is not installed."""
        from hiveflow.plugins.documents.markitdown_loader import MarkItDownLoader

        loader = MarkItDownLoader()
        with patch.dict("sys.modules", {"markitdown": None}), pytest.raises(
            ImportError, match="markitdown is required"
        ):
            await loader.load("/fake/path.csv")


# ---------------------------------------------------------------------------
# get_all_loaders_for_file tests
# ---------------------------------------------------------------------------
class TestGetAllLoadersForFile:
    """Tests for the multi-loader discovery method."""

    @pytest.fixture()
    def registry(self):
        """Create a registry with plugins discovered."""
        reg = DocumentLoaderRegistry()
        reg.discover()
        return reg

    def test_returns_multiple_loaders_for_same_extension(self, registry):
        """Multiple loaders that support the same extension are all returned."""
        loaders = registry.get_all_loaders_for_file("test.csv")
        # text and markitdown both handle .csv
        ids = [ldr.plugin_id for ldr in loaders]
        assert "text" in ids
        assert "markitdown" in ids

    def test_returns_empty_for_unknown_extension(self, registry):
        loaders = registry.get_all_loaders_for_file("test.xyz123")
        assert loaders == []

    def test_returns_all_docx_loaders(self, registry):
        """Both docx and markitdown handle .docx files."""
        loaders = registry.get_all_loaders_for_file("test.docx")
        ids = [ldr.plugin_id for ldr in loaders]
        assert "docx" in ids
        assert "markitdown" in ids

    def test_returns_sorted_by_plugin_id(self, registry):
        """Loaders are returned in alphabetical order."""
        loaders = registry.get_all_loaders_for_file("test.html")
        ids = [ldr.plugin_id for ldr in loaders]
        assert ids == sorted(ids)

    def test_epub_only_markitdown(self, registry):
        """Only markitdown handles .epub files."""
        loaders = registry.get_all_loaders_for_file("book.epub")
        assert len(loaders) == 1
        assert loaders[0].plugin_id == "markitdown"


# ---------------------------------------------------------------------------
# Loader fallback tests
# ---------------------------------------------------------------------------
class TestLoaderFallback:
    """Tests for the fallback mechanism in DocumentPipeline._load_file()."""

    async def test_fallback_to_second_loader(self, tmp_path: Path):
        """If first loader fails, the second one is tried."""
        txt_file = tmp_path / "data.csv"
        txt_file.write_text("a,b,c\n1,2,3\n")

        registry = DocumentLoaderRegistry()
        registry.discover()
        pipeline = DocumentPipeline(
            registry=registry,
            working_dir=tmp_path,
        )

        # Sabotage the first loader for .csv (alphabetically first)
        original_loaders = registry.get_all_loaders_for_file(txt_file)
        assert len(original_loaders) >= 2, (
            f"Expected at least 2 loaders for .csv, got {len(original_loaders)}: "
            f"{[ldr.plugin_id for ldr in original_loaders]}"
        )

        original_load = original_loaders[0].load

        async def failing_load(path):
            raise RuntimeError("Simulated failure")

        original_loaders[0].load = failing_load

        try:
            docs, summary = await pipeline.load(["data.csv"])
            assert len(docs) == 1
            assert "data.csv" in docs[0]["name"]
        finally:
            original_loaders[0].load = original_load

    async def test_all_loaders_fail_raises_runtime_error(self, tmp_path: Path):
        """When all loaders fail, a RuntimeError with last error is raised."""
        bad_file = tmp_path / "corrupt.csv"
        bad_file.write_bytes(b"\x00\x01\x02\x03")

        registry = DocumentLoaderRegistry()
        registry.discover()
        pipeline = DocumentPipeline(
            registry=registry,
            working_dir=tmp_path,
        )

        # Sabotage all loaders for .csv
        all_csv_loaders = registry.get_all_loaders_for_file("test.csv")
        originals = {}
        for loader in all_csv_loaders:
            originals[loader.plugin_id] = loader.load

            async def failing_load(path, msg=loader.plugin_id):
                raise RuntimeError(f"Simulated failure in {msg}")

            loader.load = failing_load

        try:
            with pytest.raises(RuntimeError, match="All loaders failed"):
                await pipeline.load(["corrupt.csv"])
        finally:
            for loader in all_csv_loaders:
                loader.load = originals[loader.plugin_id]

    async def test_single_loader_success_no_fallback(self, tmp_path: Path):
        """When first loader succeeds, no fallback is needed."""
        txt_file = tmp_path / "notes.txt"
        txt_file.write_text("Hello World")

        pipeline = DocumentPipeline(
            registry=DocumentLoaderRegistry(),
            working_dir=tmp_path,
        )

        docs, summary = await pipeline.load(["notes.txt"])
        assert len(docs) == 1
        assert "Hello" in docs[0]["chunks"][0]["content"]


# ---------------------------------------------------------------------------
# Integration: MarkItDown in pipeline
# ---------------------------------------------------------------------------
class TestMarkItDownPipelineIntegration:
    """End-to-end tests loading files through the pipeline with MarkItDown."""

    async def test_csv_through_pipeline(self, tmp_path: Path):
        """CSV loaded through pipeline gets proper metadata."""
        csv_file = tmp_path / "data.csv"
        csv_file.write_text("name,score\nAlice,95\nBob,87\n")

        pipeline = DocumentPipeline(
            registry=DocumentLoaderRegistry(),
            working_dir=tmp_path,
        )
        docs, summary = await pipeline.load(["data.csv"])
        assert len(docs) == 1
        assert docs[0]["name"] == "data.csv"
        assert docs[0]["format"] == "csv"
        assert docs[0]["chunk_count"] >= 1
        assert docs[0]["total_tokens_estimate"] > 0

    async def test_html_through_pipeline(self, tmp_path: Path):
        """HTML loaded through pipeline via markitdown fallback."""
        html_file = tmp_path / "page.html"
        html_file.write_text("<html><body><p>Content here</p></body></html>")

        pipeline = DocumentPipeline(
            registry=DocumentLoaderRegistry(),
            working_dir=tmp_path,
        )
        docs, summary = await pipeline.load(["page.html"])
        assert len(docs) == 1
        assert "Content" in docs[0]["chunks"][0]["content"]
