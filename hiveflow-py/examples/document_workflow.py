"""Example: Document-driven workflow with per-agent scoping.

Demonstrates a complete workflow that:
1. Loads documents into pipeline state
2. Routes document content to agents based on scoping rules
3. Uses the DocumentRetrieverTool for on-demand lookups
4. Shows equivalent CLI commands for each pattern

Requires an OpenAI-compatible LLM endpoint.

Usage:
    uv run python examples/document_workflow.py
    uv run python examples/document_workflow.py --base-url http://localhost:8080/v1

Equivalent CLI commands (shown in output, no LLM needed to see them):
    hiveflow run --template content_rewriter --doc ./transcript.txt \\
                 --instructions "Rewrite as a blog post"

    hiveflow run --template research_report --doc ./paper.txt \\
                 --instructions-file ./prompts/analysis.md

    hiveflow run --template contract_analyzer --doc ./contract.txt \\
                 --doc ./amendment.txt --instructions "Identify risks"
"""

import asyncio
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hiveflow.core.documents import DocumentPipeline
from hiveflow.core.schema import AgentBehaviorTypeSchema, AgentDefinition
from hiveflow.plugins.documents import DocumentLoaderRegistry
from hiveflow.plugins.tools.document_retriever import DocumentRetrieverTool


def print_section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}\n")


async def demo_cli_patterns(work_dir: Path) -> None:
    """Show CLI command equivalents for common document patterns."""

    print_section("CLI Patterns (no LLM needed)")

    print("  # Single document with inline instructions:")
    print("  hiveflow run --template content_rewriter \\")
    print("               --doc ./transcript.txt \\")
    print('               --instructions "Rewrite as a blog post"')
    print()

    print("  # Instructions from file:")
    print("  hiveflow run --template research_report \\")
    print("               --doc ./data.csv \\")
    print("               --instructions-file ./prompts/analysis.md")
    print()

    print("  # Multiple documents:")
    print("  hiveflow run --template contract_analyzer \\")
    print("               --doc ./contract.txt \\")
    print("               --doc ./amendment.txt \\")
    print('               --instructions "Identify risks across these documents"')
    print()

    print("  # Pipe from stdin:")
    print('  echo "Summarize this" | hiveflow run --template summarizer \\')
    print("               --instructions - --doc ./report.txt")


async def demo_programmatic_loading(work_dir: Path) -> tuple[list[dict[str, Any]], str]:
    """Show how to load documents programmatically and inspect results."""

    print_section("Programmatic Document Loading")

    registry = DocumentLoaderRegistry()
    pipeline = DocumentPipeline(registry=registry, working_dir=work_dir)

    # Load files
    docs, summary = await pipeline.load([
        "transcript.txt",
        "contract.txt",
    ])
    print(f"  Loaded: {summary}")

    # Load instructions
    instructions = await pipeline.load_instructions_file("prompts/detailed-analysis.md")
    print(f"  Instructions: {instructions[:60]}...")

    # Show how documents flow into agent state
    print("\n  Documents are injected into workflow state as:")
    print('    state["documents"] = [')
    for doc in docs:
        print(f'      {{"name": "{doc["name"]}", "chunks": {doc["chunk_count"]}, '
              f'"tokens": ~{doc["total_tokens_estimate"]}}},')
    print("    ]")
    print(f'    state["task"] = "<instructions text>"')

    return docs, instructions


async def demo_agent_scoping(docs: list[dict[str, Any]]) -> None:
    """Show how different agents see different slices of the documents."""

    print_section("Per-Agent Document Scoping")

    pipeline = DocumentPipeline()

    agents = [
        ("summarizer", AgentDefinition(
            id="summarizer",
            role="Document Summarizer",
            system_prompt="Summarize the provided documents.",
            behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
            document_mode="full",
        )),
        ("analyst", AgentDefinition(
            id="analyst",
            role="Contract Analyst",
            system_prompt="Analyze contract terms.",
            behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
            documents=["contract.txt"],
            document_mode="full",
        )),
        ("router", AgentDefinition(
            id="router",
            role="Document Router",
            system_prompt="Route documents to specialists.",
            behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
            document_mode="metadata_only",
        )),
        ("editor", AgentDefinition(
            id="editor",
            role="Final Editor",
            system_prompt="Polish the final output.",
            behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
            document_mode="none",
        )),
    ]

    for name, agent_def in agents:
        scoped = pipeline.scope_for_agent(docs, agent_def)
        mode = agent_def.document_mode or "none"
        doc_filter = agent_def.documents
        doc_names = [d.get("name", "?") for d in scoped] if scoped else []

        filter_str = f", filter={doc_filter}" if doc_filter else ""
        print(f"  {name:12s} mode={mode:14s}{filter_str}")
        print(f"               -> sees {len(scoped)} doc(s): {doc_names}")
        print()


async def demo_retriever_tool() -> None:
    """Show DocumentRetrieverTool usage for on-demand lookups."""

    print_section("DocumentRetrieverTool (for tool_user agents)")

    tool = DocumentRetrieverTool()

    # Simulate documents already loaded in workflow state
    sample_docs = [
        {
            "name": "report.txt",
            "format": "txt",
            "size_bytes": 500,
            "chunk_count": 2,
            "total_tokens_estimate": 80,
            "chunks": [
                {"index": 0, "content": "Revenue grew 15% year-over-year to $2.3B."},
                {"index": 1, "content": "Operating margins improved from 12% to 18%."},
            ],
        },
        {
            "name": "forecast.txt",
            "format": "txt",
            "size_bytes": 300,
            "chunk_count": 1,
            "total_tokens_estimate": 40,
            "chunks": [
                {"index": 0, "content": "Q1 2025 revenue projected at $2.5B with 20% margins."},
            ],
        },
    ]

    tool.set_documents(sample_docs)

    # Fetch by name
    result = await tool.execute({"document_name": "report.txt"})
    print(f"  Fetch 'report.txt': {result['total_chunks']} chunk(s)")
    for chunk in result["chunks"]:
        print(f"    [{chunk['index']}] {chunk['content'][:70]}")

    # Keyword search
    print()
    result = await tool.execute({"query": "revenue margins"})
    print(f"  Search 'revenue margins': {result['total_chunks']} match(es)")
    for chunk in result["chunks"]:
        print(f"    [{chunk['document']}:{chunk['index']}] {chunk['content'][:70]}")

    # Token-limited retrieval
    print()
    result = await tool.execute({"max_tokens": 10})
    print(f"  Token-limited (max 10): {len(result['chunks'])} chunk(s) returned")


async def main() -> None:
    # Create sample files
    work_dir = Path(tempfile.mkdtemp())

    (work_dir / "transcript.txt").write_text(
        "Welcome to today's AI session. We'll discuss machine learning,\n"
        "neural networks, and practical applications in healthcare,\n"
        "finance, and autonomous systems."
    )
    (work_dir / "contract.txt").write_text(
        "This agreement is entered into by Party A and Party B.\n"
        "Section 1: Terms of service. Section 2: Payment conditions.\n"
        "Section 3: Termination clause. Section 4: Liability limits."
    )
    prompts_dir = work_dir / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "detailed-analysis.md").write_text(
        "Analyze the following documents in detail.\n"
        "Provide a structured summary with key findings and action items."
    )

    # Run each demo section
    await demo_cli_patterns(work_dir)
    docs, instructions = await demo_programmatic_loading(work_dir)
    await demo_agent_scoping(docs)
    await demo_retriever_tool()

    print_section("Summary")
    print("  The document pipeline handles:")
    print("  - File loading (txt, md, csv, json, xml, html, pdf, docx, xlsx, pptx)")
    print("  - Inline content (dict with 'name' and 'content')")
    print("  - Automatic chunking and token estimation")
    print("  - Per-agent scoping (full, metadata_only, none)")
    print("  - Token budget enforcement")
    print("  - On-demand retrieval via DocumentRetrieverTool")
    print()


if __name__ == "__main__":
    asyncio.run(main())
