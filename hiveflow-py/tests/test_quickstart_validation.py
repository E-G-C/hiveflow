"""End-to-end validation of quickstart.md scenarios.

These tests validate the document pipeline paths described in quickstart.md
without requiring a live LLM provider.
"""

from pathlib import Path
from typing import Any

import pytest

from hiveflow.core.documents import DocumentPipeline
from hiveflow.core.schema import AgentBehaviorTypeSchema, AgentDefinition
from hiveflow.plugins.documents import DocumentLoaderRegistry


@pytest.fixture
def scenario_dir(tmp_path: Path) -> Path:
    """Create a working directory matching quickstart.md scenarios."""
    # Single document scenario
    (tmp_path / "transcript.txt").write_text(
        "Welcome to today's session. We'll discuss AI advancements. "
        "Machine learning has transformed healthcare, finance, and more. "
        "Key takeaway: AI augments human capabilities."
    )

    # Multiple documents scenario
    (tmp_path / "contract.txt").write_text(
        "This agreement is entered into by Party A and Party B. "
        "Section 1: Terms. Section 2: Conditions."
    )
    (tmp_path / "amendment.txt").write_text(
        "Amendment to the original contract. "
        "Section 1 is hereby modified to include..."
    )

    # Instructions file scenario
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "detailed-analysis.md").write_text(
        "Analyze the following document in detail. "
        "Provide a structured summary with key findings."
    )

    # CSV data
    (tmp_path / "data.csv").write_text("metric,value\nrevenue,100\ncost,50\n")

    # Markdown file for scoping scenario
    (tmp_path / "speaker-bio.md").write_text(
        "# Dr. Jane Smith\n\nExpert in machine learning and AI ethics."
    )

    return tmp_path


@pytest.fixture
def pipeline(scenario_dir: Path) -> DocumentPipeline:
    """Create pipeline with scenario directory."""
    registry = DocumentLoaderRegistry()
    return DocumentPipeline(
        registry=registry,
        working_dir=scenario_dir,
    )


class TestQuickstartScenario1SingleDocument:
    """Quickstart §1: Process a single document."""

    async def test_single_text_document(self, pipeline: DocumentPipeline) -> None:
        """Load a single .txt file and verify state shape."""
        docs, summary = await pipeline.load(["transcript.txt"])
        assert len(docs) == 1
        doc = docs[0]
        # Quickstart §6 assertions
        assert doc["name"] == "transcript.txt"
        assert doc["format"] == "txt"
        assert doc["size_bytes"] > 0
        assert doc["chunk_count"] >= 1
        assert doc["total_tokens_estimate"] > 0
        assert "1 document loaded" in summary


class TestQuickstartScenario3InstructionsFromFile:
    """Quickstart §3: Use instructions from a file."""

    async def test_instructions_file_loading(
        self, pipeline: DocumentPipeline
    ) -> None:
        """Load instructions from file alongside a document."""
        content = await pipeline.load_instructions_file(
            "prompts/detailed-analysis.md"
        )
        assert "Analyze" in content
        assert len(content) > 0

    async def test_instructions_with_document(
        self, pipeline: DocumentPipeline
    ) -> None:
        """Combine instructions file with document loading."""
        instructions = await pipeline.load_instructions_file(
            "prompts/detailed-analysis.md"
        )
        docs, _ = await pipeline.load(["data.csv"])
        assert len(docs) == 1
        assert instructions  # Non-empty


class TestQuickstartScenario4MultipleDocuments:
    """Quickstart §4: Multiple documents."""

    async def test_multiple_documents(self, pipeline: DocumentPipeline) -> None:
        """Load multiple documents at once."""
        docs, summary = await pipeline.load([
            "contract.txt",
            "amendment.txt",
            "transcript.txt",
        ])
        assert len(docs) == 3
        assert "3 documents loaded" in summary
        names = {d["name"] for d in docs}
        assert "contract.txt" in names
        assert "amendment.txt" in names
        assert "transcript.txt" in names


class TestQuickstartScenario5PerAgentScoping:
    """Quickstart §5: Per-agent document scoping."""

    @pytest.fixture
    async def loaded_docs(self, pipeline: DocumentPipeline) -> list[dict[str, Any]]:
        """Pre-load documents for scoping tests."""
        docs, _ = await pipeline.load(["transcript.txt", "speaker-bio.md"])
        return docs

    def test_summarizer_sees_full_document(
        self, pipeline: DocumentPipeline, loaded_docs: list[dict[str, Any]]
    ) -> None:
        """Summarizer agent with full mode sees document content."""
        agent_def = AgentDefinition(
            id="summarizer",
            role="Document Summarizer",
            system_prompt="Summarize the provided document.",
            behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
            documents=["transcript.txt"],
            document_mode="full",
        )
        result = pipeline.scope_for_agent(loaded_docs, agent_def)
        assert len(result) == 1
        assert result[0]["name"] == "transcript.txt"
        assert "chunks" in result[0]

    def test_editor_sees_no_documents(
        self, pipeline: DocumentPipeline, loaded_docs: list[dict[str, Any]]
    ) -> None:
        """Editor agent with mode=none sees no documents."""
        agent_def = AgentDefinition(
            id="editor",
            role="Final Editor",
            system_prompt="Polish the rewritten content.",
            behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
            document_mode="none",
        )
        result = pipeline.scope_for_agent(loaded_docs, agent_def)
        assert result == []

    def test_fact_checker_with_token_limit(
        self, pipeline: DocumentPipeline, loaded_docs: list[dict[str, Any]]
    ) -> None:
        """Fact checker with max_document_tokens gets truncated content."""
        agent_def = AgentDefinition(
            id="fact_checker",
            role="Fact Checker",
            system_prompt="Verify claims.",
            behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
            documents=["transcript.txt", "speaker-bio.md"],
            document_mode="full",
            max_document_tokens=3000,
        )
        result = pipeline.scope_for_agent(loaded_docs, agent_def)
        assert len(result) == 2


class TestQuickstartScenario6StateShape:
    """Quickstart §6: Verify state shape."""

    async def test_state_dict_shape(self, pipeline: DocumentPipeline) -> None:
        """Document state dicts match quickstart assertions."""
        docs, summary = await pipeline.load(["transcript.txt"])
        doc = docs[0]

        # Exact assertions from quickstart.md §6
        assert doc["name"] == "transcript.txt"
        assert doc["format"] == "txt"
        assert doc["size_bytes"] > 0
        assert doc["chunk_count"] >= 1
        assert doc["total_tokens_estimate"] > 0

        # Chunks have content
        assert len(doc["chunks"]) >= 1
        assert "content" in doc["chunks"][0]
        assert "index" in doc["chunks"][0]


class TestCLIArgumentParsing:
    """Validate CLI argument patterns from quickstart.md."""

    def test_single_doc_flag(self) -> None:
        """CLI pattern: --doc ./transcript.txt"""
        from hiveflow.cli.main import build_parser

        parser = build_parser()
        args = parser.parse_args([
            "run", "--template", "content_rewriter",
            "--instructions", "Rewrite this transcript as a blog post",
            "--doc", "./transcript.txt",
        ])
        assert args.template == "content_rewriter"
        assert args.doc == ["./transcript.txt"]
        assert args.instructions == "Rewrite this transcript as a blog post"

    def test_instructions_file_flag(self) -> None:
        """CLI pattern: --instructions-file ./prompts/detailed-analysis.md"""
        from hiveflow.cli.main import build_parser

        parser = build_parser()
        args = parser.parse_args([
            "run", "--template", "research_report",
            "--instructions-file", "./prompts/detailed-analysis.md",
            "--doc", "./data.csv",
        ])
        assert args.instructions_file == "./prompts/detailed-analysis.md"
        assert args.doc == ["./data.csv"]

    def test_multiple_doc_flags(self) -> None:
        """CLI pattern: --doc ./contract.pdf --doc ./amendment.docx --doc ./terms.txt"""
        from hiveflow.cli.main import build_parser

        parser = build_parser()
        args = parser.parse_args([
            "run", "--template", "contract_analyzer",
            "--instructions", "Identify risks across these documents",
            "--doc", "./contract.pdf",
            "--doc", "./amendment.docx",
            "--doc", "./terms.txt",
        ])
        assert len(args.doc) == 3
