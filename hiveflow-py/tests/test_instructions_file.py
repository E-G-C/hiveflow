"""Tests for instructions_file parameter on HiveFlow.run()."""

from pathlib import Path

import pytest

from hiveflow.core.documents import DocumentPipeline


class TestInstructionsFilePipeline:
    """Test instructions file loading via DocumentPipeline."""

    async def test_load_instructions_file(self, tmp_path):
        f = tmp_path / "instructions.md"
        f.write_text("Rewrite this as a blog post", encoding="utf-8")
        pipeline = DocumentPipeline(working_dir=Path(tmp_path))
        result = await pipeline.load_instructions_file(str(f))
        assert result == "Rewrite this as a blog post"

    async def test_load_instructions_file_txt(self, tmp_path):
        f = tmp_path / "instructions.txt"
        f.write_text("Summarize the document", encoding="utf-8")
        pipeline = DocumentPipeline(working_dir=Path(tmp_path))
        result = await pipeline.load_instructions_file(str(f))
        assert result == "Summarize the document"

    async def test_load_instructions_file_empty(self, tmp_path):
        f = tmp_path / "empty.md"
        f.write_text("", encoding="utf-8")
        pipeline = DocumentPipeline(working_dir=Path(tmp_path))
        result = await pipeline.load_instructions_file(str(f))
        assert result == ""

    async def test_load_instructions_file_missing(self):
        pipeline = DocumentPipeline()
        with pytest.raises((FileNotFoundError, ValueError)):
            await pipeline.load_instructions_file("/nonexistent/file.md")

    async def test_load_instructions_preserves_newlines(self, tmp_path):
        f = tmp_path / "multi.md"
        f.write_text("Line 1\nLine 2\nLine 3", encoding="utf-8")
        pipeline = DocumentPipeline(working_dir=Path(tmp_path))
        result = await pipeline.load_instructions_file(str(f))
        assert "Line 1\nLine 2\nLine 3" in result


class TestHiveFlowRunInstructionsFile:
    """Test instructions_file parameter integration on HiveFlow.run()."""

    async def test_mutual_exclusivity_error(self):
        from hiveflow.core.hiveflow import HiveFlow

        hf = HiveFlow()
        with pytest.raises(ValueError, match="mutually exclusive"):
            await hf.run(
                team="test_team",
                task="Non-empty task",
                instructions_file="/some/file.md",
            )

    async def test_empty_task_with_instructions_file_accepted(self, tmp_path):
        """Empty task + instructions_file should not raise ValueError."""
        f = tmp_path / "instructions.md"
        f.write_text("Do something", encoding="utf-8")

        from hiveflow.core.hiveflow import HiveFlow

        hf = HiveFlow()
        # This will fail later (no valid team), but should NOT raise
        # the mutual exclusivity ValueError
        try:
            await hf.run(team="nonexistent_team", task="", instructions_file=str(f))
        except ValueError as e:
            assert "mutually exclusive" not in str(e)
        except (KeyError, FileNotFoundError, RuntimeError):
            pass  # Expected — team doesn't exist

    async def test_whitespace_only_task_accepted(self, tmp_path):
        """Whitespace-only task should not trigger mutual exclusivity."""
        f = tmp_path / "instructions.md"
        f.write_text("Instructions here", encoding="utf-8")

        from hiveflow.core.hiveflow import HiveFlow

        hf = HiveFlow()
        try:
            await hf.run(team="nonexistent", task="   ", instructions_file=str(f))
        except ValueError as e:
            assert "mutually exclusive" not in str(e)
        except (KeyError, FileNotFoundError, RuntimeError):
            pass
