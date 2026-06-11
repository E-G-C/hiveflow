"""Integration tests for the document pipeline."""

from pathlib import Path

import pytest

from hiveflow.core.documents import DocumentPipeline
from hiveflow.plugins.documents import DocumentLoaderRegistry


@pytest.fixture
def work_dir(tmp_path: Path) -> Path:
    """Create a working directory with test files."""
    # Plain text files
    (tmp_path / "hello.txt").write_text("Hello, world! This is a test document.")
    (tmp_path / "report.txt").write_text(
        "This is a longer report. " * 100  # ~600 words
    )
    (tmp_path / "empty.txt").write_text("")

    # Subdirectory
    (tmp_path / "subdir").mkdir()
    (tmp_path / "subdir" / "nested.txt").write_text("Nested content here.")

    # CSV file
    (tmp_path / "data.csv").write_text("col1,col2\na,b\nc,d\n")

    # Unsupported format
    (tmp_path / "image.xyz").write_bytes(b"\x00\x01\x02")

    return tmp_path


@pytest.fixture
def pipeline(work_dir: Path) -> DocumentPipeline:
    """Create a DocumentPipeline with test working directory."""
    registry = DocumentLoaderRegistry()
    return DocumentPipeline(
        registry=registry,
        working_dir=work_dir,
        chunk_size=50,
        chunk_overlap=10,
    )


class TestSingleFileLoading:
    """Test loading a single file."""

    async def test_load_single_text_file(self, pipeline: DocumentPipeline) -> None:
        """Load a single text file and verify state dict shape."""
        docs, summary = await pipeline.load(["hello.txt"])

        assert len(docs) == 1
        doc = docs[0]
        assert doc["name"].endswith("hello.txt")
        assert doc["format"] == "txt"
        assert doc["size_bytes"] > 0
        assert doc["chunk_count"] >= 1
        assert doc["total_tokens_estimate"] > 0
        assert len(doc["chunks"]) >= 1
        assert doc["chunks"][0]["index"] == 0
        assert "Hello" in doc["chunks"][0]["content"]

    async def test_summary_string(self, pipeline: DocumentPipeline) -> None:
        """Summary string describes loaded documents."""
        _, summary = await pipeline.load(["hello.txt"])
        assert "1 document loaded" in summary
        assert "hello.txt" in summary


class TestMultipleFiles:
    """Test loading multiple files."""

    async def test_load_multiple_files(self, pipeline: DocumentPipeline) -> None:
        """Load multiple text files."""
        docs, summary = await pipeline.load(["hello.txt", "subdir/nested.txt"])

        assert len(docs) == 2
        names = {d["name"] for d in docs}
        assert any("hello.txt" in n for n in names)
        assert any("nested.txt" in n for n in names)
        assert "2 documents loaded" in summary


class TestInlineContent:
    """Test loading inline content dicts."""

    async def test_inline_content(self, pipeline: DocumentPipeline) -> None:
        """Load inline content dict."""
        docs, summary = await pipeline.load([
            {"name": "inline-doc", "content": "This is inline content."}
        ])

        assert len(docs) == 1
        assert docs[0]["name"] == "inline-doc"
        assert docs[0]["format"] == "txt"
        assert "inline content" in docs[0]["chunks"][0]["content"]

    async def test_inline_missing_keys(self, pipeline: DocumentPipeline) -> None:
        """Inline dict without required keys raises ValueError."""
        with pytest.raises(ValueError, match="name.*content"):
            await pipeline.load([{"content": "no name"}])


class TestMixedInputs:
    """Test mixed file paths and inline content."""

    async def test_mixed_inputs(self, pipeline: DocumentPipeline) -> None:
        """Load both file paths and inline content."""
        docs, _ = await pipeline.load([
            "hello.txt",
            {"name": "my-inline", "content": "Inline text"},
        ])

        assert len(docs) == 2
        names = [d["name"] for d in docs]
        assert any("hello.txt" in n for n in names)
        assert "my-inline" in names


class TestErrorConditions:
    """Test error handling."""

    async def test_missing_file(self, pipeline: DocumentPipeline) -> None:
        """Missing file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="Document not found"):
            await pipeline.load(["nonexistent.txt"])

    async def test_unsupported_format(self, pipeline: DocumentPipeline) -> None:
        """Unsupported file format raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported document format"):
            await pipeline.load(["image.xyz"])

    async def test_path_traversal_rejected(self, pipeline: DocumentPipeline) -> None:
        """Path traversal is rejected."""
        with pytest.raises(ValueError, match="traversal"):
            await pipeline.load(["../escape.txt"])

    async def test_size_limit_enforcement(self, work_dir: Path) -> None:
        """Size limit is enforced."""
        # Create a pipeline with a very low size limit
        registry = DocumentLoaderRegistry()
        pipeline = DocumentPipeline(
            registry=registry,
            working_dir=work_dir,
            max_total_bytes=10,  # 10 bytes
        )
        with pytest.raises(ValueError, match="exceeds limit"):
            await pipeline.load(["hello.txt"])

    async def test_duplicate_name_rejected(self, pipeline: DocumentPipeline) -> None:
        """Duplicate document names are rejected."""
        with pytest.raises(ValueError, match="Duplicate document name"):
            await pipeline.load([
                {"name": "same-name", "content": "first"},
                {"name": "same-name", "content": "second"},
            ])

    async def test_empty_file_handling(self, pipeline: DocumentPipeline) -> None:
        """Empty file loads without error."""
        docs, _ = await pipeline.load(["empty.txt"])
        assert len(docs) == 1
        assert docs[0]["chunk_count"] >= 1


class TestChunking:
    """Test document chunking behavior."""

    async def test_large_file_is_chunked(self, pipeline: DocumentPipeline) -> None:
        """Large file is split into multiple chunks."""
        docs, _ = await pipeline.load(["report.txt"])
        assert len(docs) == 1
        # With chunk_size=50, a ~600 word doc should produce multiple chunks
        assert docs[0]["chunk_count"] > 1

    async def test_small_file_single_chunk(self, pipeline: DocumentPipeline) -> None:
        """Small file stays as a single chunk."""
        docs, _ = await pipeline.load(["hello.txt"])
        assert docs[0]["chunk_count"] == 1


class TestInstructionsFile:
    """Test instructions file loading."""

    async def test_load_instructions(self, pipeline: DocumentPipeline, work_dir: Path) -> None:
        """Load instructions from file."""
        (work_dir / "prompt.md").write_text("Summarize the attached documents.")
        content = await pipeline.load_instructions_file("prompt.md")
        assert content == "Summarize the attached documents."

    async def test_instructions_path_security(self, pipeline: DocumentPipeline) -> None:
        """Instructions file path is validated for security."""
        with pytest.raises(ValueError, match="traversal"):
            await pipeline.load_instructions_file("../escape.md")
