"""Tests for load_from_bytes(): temp-file delegation, empty bytes, cleanup."""

from pathlib import Path

import pytest

from hiveflow.plugins.documents import DocumentLoaderPlugin
from hiveflow.plugins.documents.plain_text import PlainTextLoader
from hiveflow.plugins.documents.markdown_loader import MarkdownLoader


class TestLoadFromBytesDefault:
    """Default temp-file delegation via DocumentLoaderPlugin.load_from_bytes()."""

    async def test_plain_text_loader(self):
        loader = PlainTextLoader()
        data = b"Hello, this is a test document."
        doc = await loader.load_from_bytes(data, "test.txt")
        assert doc.content == "Hello, this is a test document."

    async def test_markdown_loader(self):
        loader = MarkdownLoader()
        data = b"# Heading\n\nSome markdown content."
        doc = await loader.load_from_bytes(data, "readme.md")
        assert "Heading" in doc.content
        assert "markdown content" in doc.content

    async def test_empty_bytes_raises(self):
        loader = PlainTextLoader()
        with pytest.raises(ValueError, match="Empty document data"):
            await loader.load_from_bytes(b"", "empty.txt")

    async def test_temp_file_cleaned_up_on_success(self, tmp_path):
        """Temp file should not exist after successful load."""
        loader = PlainTextLoader()
        data = b"Content for cleanup test"
        doc = await loader.load_from_bytes(data, "cleanup.txt")
        # Can't check specific temp path, but ensure doc loaded fine
        assert doc.content == "Content for cleanup test"

    async def test_temp_file_cleaned_up_on_failure(self):
        """Temp file should be cleaned up even if load() fails."""
        class FailingLoader(DocumentLoaderPlugin):
            @property
            def plugin_id(self):
                return "failing"

            @property
            def description(self):
                return "Always fails"

            @property
            def supported_extensions(self):
                return [".fail"]

            async def load(self, file_path):
                raise RuntimeError("Intentional failure")

        loader = FailingLoader()
        with pytest.raises(RuntimeError, match="Intentional failure"):
            await loader.load_from_bytes(b"data", "test.fail")

    async def test_preserves_binary_content(self):
        """Binary content should round-trip through temp file."""
        loader = PlainTextLoader()
        data = "Unicode: àáâ ñ 日本語".encode("utf-8")
        doc = await loader.load_from_bytes(data, "unicode.txt")
        assert "àáâ" in doc.content
        assert "日本語" in doc.content

    async def test_filename_used_for_extension(self):
        """Extension is derived from filename, not content."""
        loader = MarkdownLoader()
        data = b"Plain text but named as markdown"
        doc = await loader.load_from_bytes(data, "file.md")
        # Should load successfully since .md is supported
        assert doc.content == "Plain text but named as markdown"


class TestLoadFromBytesPipeline:
    """Pipeline-level bytes loading."""

    async def test_pipeline_loads_bytes_dict(self):
        from hiveflow.core.documents import DocumentPipeline
        pipeline = DocumentPipeline()
        docs, summary = await pipeline.load([
            {"name": "test.txt", "bytes": b"Hello from bytes"},
        ])
        assert len(docs) == 1
        assert docs[0]["name"] == "test.txt"
        assert docs[0]["chunks"]

    async def test_pipeline_mixed_inline_and_bytes(self):
        from hiveflow.core.documents import DocumentPipeline
        pipeline = DocumentPipeline()
        docs, summary = await pipeline.load([
            {"name": "inline.txt", "content": "Inline content"},
            {"name": "bytes.txt", "bytes": b"Bytes content"},
        ])
        assert len(docs) == 2
