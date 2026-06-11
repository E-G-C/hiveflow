"""Tests for the HiveFlow CLI."""

from io import StringIO
from unittest.mock import patch

import pytest

from hiveflow.cli.main import (
    EXIT_USAGE_ERROR,
    build_parser,
    resolve_stdin_inputs,
    validate_args,
)


class TestBuildParser:
    """Test argument parser construction."""

    def test_run_command_with_template(self) -> None:
        """Parse basic run command with template."""
        parser = build_parser()
        args = parser.parse_args(["run", "--template", "my_template"])
        assert args.command == "run"
        assert args.template == "my_template"

    def test_run_with_instructions(self) -> None:
        """Parse --instructions flag."""
        parser = build_parser()
        args = parser.parse_args([
            "run", "--template", "t", "--instructions", "Do something"
        ])
        assert args.instructions == "Do something"

    def test_run_with_instructions_file(self) -> None:
        """Parse --instructions-file flag."""
        parser = build_parser()
        args = parser.parse_args([
            "run", "--template", "t", "--instructions-file", "prompt.md"
        ])
        assert args.instructions_file == "prompt.md"

    def test_run_with_single_doc(self) -> None:
        """Parse single --doc flag."""
        parser = build_parser()
        args = parser.parse_args([
            "run", "--template", "t", "--doc", "file.txt"
        ])
        assert args.doc == ["file.txt"]

    def test_run_with_multiple_docs(self) -> None:
        """Parse multiple --doc flags."""
        parser = build_parser()
        args = parser.parse_args([
            "run", "--template", "t",
            "--doc", "file1.txt",
            "--doc", "file2.txt",
        ])
        assert args.doc == ["file1.txt", "file2.txt"]

    def test_run_with_config(self) -> None:
        """Parse --config flag."""
        parser = build_parser()
        args = parser.parse_args([
            "run", "--template", "t", "--config", "config.yaml"
        ])
        assert args.config == "config.yaml"


class TestValidateArgs:
    """Test argument validation."""

    def test_no_command_returns_error(self) -> None:
        """No command returns usage error."""
        parser = build_parser()
        args = parser.parse_args([])
        result = validate_args(args)
        assert result == EXIT_USAGE_ERROR

    def test_mutual_exclusivity_instructions(self) -> None:
        """Both --instructions and --instructions-file returns error."""
        parser = build_parser()
        args = parser.parse_args([
            "run", "--template", "t",
            "--instructions", "text",
            "--instructions-file", "file.md",
        ])
        result = validate_args(args)
        assert result == EXIT_USAGE_ERROR

    def test_dual_stdin_rejected(self) -> None:
        """Both --instructions - and --doc - returns error."""
        parser = build_parser()
        args = parser.parse_args([
            "run", "--template", "t",
            "--instructions", "-",
            "--doc", "-",
        ])
        result = validate_args(args)
        assert result == EXIT_USAGE_ERROR

    def test_valid_args_return_none(self) -> None:
        """Valid args return None (no error)."""
        parser = build_parser()
        args = parser.parse_args([
            "run", "--template", "t", "--instructions", "text"
        ])
        result = validate_args(args)
        assert result is None


class TestResolveStdinInputs:
    """Test stdin resolution."""

    def test_instructions_stdin(self) -> None:
        """--instructions - reads from stdin."""
        parser = build_parser()
        args = parser.parse_args([
            "run", "--template", "t", "--instructions", "-"
        ])
        with patch("sys.stdin", StringIO("stdin instructions")):
            resolved = resolve_stdin_inputs(args)
        assert resolved.instructions == "stdin instructions"

    def test_doc_stdin(self) -> None:
        """--doc - reads from stdin and creates inline dict."""
        parser = build_parser()
        args = parser.parse_args([
            "run", "--template", "t", "--doc", "-"
        ])
        with patch("sys.stdin", StringIO("stdin content")):
            resolved = resolve_stdin_inputs(args)
        assert len(resolved.doc) == 1
        assert isinstance(resolved.doc[0], dict)
        assert resolved.doc[0]["name"] == "stdin.txt"
        assert resolved.doc[0]["content"] == "stdin content"

    def test_no_stdin_passthrough(self) -> None:
        """Non-stdin args pass through unchanged."""
        parser = build_parser()
        args = parser.parse_args([
            "run", "--template", "t",
            "--instructions", "regular text",
            "--doc", "file.txt",
        ])
        resolved = resolve_stdin_inputs(args)
        assert resolved.instructions == "regular text"
        assert resolved.doc == ["file.txt"]

    def test_mixed_doc_and_stdin(self) -> None:
        """Mix of file paths and stdin in --doc."""
        parser = build_parser()
        args = parser.parse_args([
            "run", "--template", "t",
            "--doc", "file.txt",
            "--doc", "-",
        ])
        with patch("sys.stdin", StringIO("from stdin")):
            resolved = resolve_stdin_inputs(args)
        assert resolved.doc[0] == "file.txt"
        assert isinstance(resolved.doc[1], dict)
        assert resolved.doc[1]["content"] == "from stdin"


class TestMainExitCodes:
    """Test main() exit codes."""

    def test_no_args_exits_usage_error(self) -> None:
        """No arguments exits with usage error."""
        with patch("sys.argv", ["hiveflow"]):
            with pytest.raises(SystemExit) as exc_info:
                from hiveflow.cli.main import main
                main()
            assert exc_info.value.code == EXIT_USAGE_ERROR
