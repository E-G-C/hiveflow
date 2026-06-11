"""Unit tests for path security validation."""

import os
import tempfile
from pathlib import Path

import pytest

from hiveflow.validation.path_security import validate_document_path


@pytest.fixture
def work_dir(tmp_path: Path) -> Path:
    """Create a working directory with test files."""
    # Create some test files
    (tmp_path / "file.txt").write_text("hello")
    (tmp_path / "subdir").mkdir()
    (tmp_path / "subdir" / "nested.txt").write_text("nested content")
    return tmp_path


class TestValidateDocumentPath:
    """Tests for validate_document_path()."""

    def test_valid_relative_path(self, work_dir: Path) -> None:
        """Valid relative path within working dir returns resolved path."""
        result = validate_document_path("file.txt", work_dir)
        assert result == (work_dir / "file.txt").resolve()

    def test_valid_nested_path(self, work_dir: Path) -> None:
        """Valid nested relative path within working dir."""
        result = validate_document_path("subdir/nested.txt", work_dir)
        assert result == (work_dir / "subdir" / "nested.txt").resolve()

    def test_valid_absolute_path(self, work_dir: Path) -> None:
        """Valid absolute path within working dir."""
        abs_path = str(work_dir / "file.txt")
        result = validate_document_path(abs_path, work_dir)
        assert result == (work_dir / "file.txt").resolve()

    def test_traversal_rejected(self, work_dir: Path) -> None:
        """Paths with '..' are rejected."""
        with pytest.raises(ValueError, match="traversal"):
            validate_document_path("../escape.txt", work_dir)

    def test_traversal_in_middle_rejected(self, work_dir: Path) -> None:
        """Paths with '..' in the middle are rejected."""
        with pytest.raises(ValueError, match="traversal"):
            validate_document_path("subdir/../../escape.txt", work_dir)

    def test_outside_working_dir_rejected(self, work_dir: Path) -> None:
        """Absolute path outside working dir is rejected."""
        # Create a file in a different temp directory
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"outside")
            outside_path = f.name
        try:
            with pytest.raises(ValueError, match="outside allowed"):
                validate_document_path(outside_path, work_dir)
        finally:
            os.unlink(outside_path)

    def test_file_not_found(self, work_dir: Path) -> None:
        """Non-existent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="Document not found"):
            validate_document_path("nonexistent.txt", work_dir)

    def test_directory_rejected(self, work_dir: Path) -> None:
        """Directory path is rejected."""
        with pytest.raises(ValueError, match="not a file"):
            validate_document_path("subdir", work_dir)

    def test_allowed_paths_permits_external(self, tmp_path: Path) -> None:
        """Files in allowed_paths directories are permitted."""
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        external_dir = tmp_path / "external"
        external_dir.mkdir()
        (external_dir / "allowed.txt").write_text("allowed content")

        result = validate_document_path(
            str(external_dir / "allowed.txt"),
            work_dir,
            allowed_paths=[external_dir],
        )
        assert result == (external_dir / "allowed.txt").resolve()

    def test_allowed_paths_rejects_other_external(self, tmp_path: Path) -> None:
        """Files outside both working dir and allowed_paths are rejected."""
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        allowed_dir = tmp_path / "allowed"
        allowed_dir.mkdir()
        other_dir = tmp_path / "other"
        other_dir.mkdir()
        (other_dir / "file.txt").write_text("content")

        with pytest.raises(ValueError, match="outside allowed"):
            validate_document_path(
                str(other_dir / "file.txt"),
                work_dir,
                allowed_paths=[allowed_dir],
            )

    @pytest.mark.skipif(os.name == "nt", reason="Symlinks may require elevated privileges on Windows")
    def test_symlink_outside_rejected(self, tmp_path: Path) -> None:
        """Symlinks that resolve outside working dir are rejected."""
        work_dir = tmp_path / "work"
        work_dir.mkdir()
        external = tmp_path / "external.txt"
        external.write_text("external")
        link = work_dir / "link.txt"
        link.symlink_to(external)

        with pytest.raises(ValueError, match="outside allowed"):
            validate_document_path("link.txt", work_dir)
