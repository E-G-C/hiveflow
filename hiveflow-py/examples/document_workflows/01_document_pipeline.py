#!/usr/bin/env python3
"""Document Workflows 01: Document pipeline -- loading, chunking, and scoping.

Demonstrates the document data pipeline without any LLM calls:
  1. Load documents from files (txt, md) and inline content
  2. Inspect the state dict shape (chunks, tokens, metadata)
  3. Load instructions from a file
  4. Scope documents per-agent (full, metadata_only, none, filtered)
  5. Apply token budgets for large documents

No LLM provider is needed -- this shows the data pipeline only.

Usage:
    uv run python examples/document_workflows/01_document_pipeline.py

Expected output:
    See sample_output/document_workflows/01_document_pipeline.txt
"""

import asyncio
import json
import tempfile
from pathlib import Path

from hiveflow.core.documents import DocumentPipeline
from hiveflow.core.schema import AgentBehaviorTypeSchema, AgentDefinition
from hiveflow.plugins.documents import DocumentLoaderRegistry


def print_section(title: str) -> None:
    """Print a labeled section divider."""
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}\n")


def create_sample_files(work_dir: Path) -> None:
    """Create sample documents for the demo."""
    (work_dir / "transcript.txt").write_text(
        "Welcome to today's session on artificial intelligence.\n"
        "We'll cover three main topics: machine learning fundamentals,\n"
        "neural network architectures, and practical applications.\n\n"
        "Machine learning is a subset of AI that enables systems to\n"
        "learn from data without being explicitly programmed. Key\n"
        "approaches include supervised learning, unsupervised learning,\n"
        "and reinforcement learning.\n\n"
        "Neural networks are computing systems inspired by biological\n"
        "neural networks. Deep learning uses multiple layers to\n"
        "progressively extract higher-level features from raw input.\n\n"
        "Practical applications span healthcare diagnostics, autonomous\n"
        "vehicles, natural language processing, and financial modeling."
    )

    (work_dir / "meeting-notes.md").write_text(
        "# Q4 Planning Meeting\n\n"
        "## Attendees\n"
        "- Alice (Engineering Lead)\n"
        "- Bob (Product Manager)\n"
        "- Carol (Design Lead)\n\n"
        "## Decisions\n"
        "1. Launch v2.0 by end of quarter\n"
        "2. Prioritize mobile responsiveness\n"
        "3. Defer internationalization to Q1\n\n"
        "## Action Items\n"
        "- Alice: finalize API contracts by Friday\n"
        "- Bob: update roadmap and share with stakeholders\n"
        "- Carol: deliver mobile wireframes next week\n"
    )

    prompts_dir = work_dir / "prompts"
    prompts_dir.mkdir()
    (prompts_dir / "analysis.md").write_text(
        "Analyze the provided documents thoroughly.\n"
        "Identify key themes, decisions, and action items.\n"
        "Produce a structured summary with clear sections."
    )


async def demo_load_files(pipeline: DocumentPipeline) -> list[dict]:
    """Load documents from files and display metadata."""
    print_section("1. Load documents from files")

    docs, summary = await pipeline.load(["transcript.txt", "meeting-notes.md"])

    print(f"Summary: {summary}\n")
    for doc in docs:
        print(f"  Name:   {doc['name']}")
        print(f"  Format: {doc['format']}")
        print(f"  Size:   {doc['size_bytes']} bytes")
        print(f"  Chunks: {doc['chunk_count']}")
        print(f"  Tokens: ~{doc['total_tokens_estimate']}")
        print()

    return docs


def demo_state_shape(docs: list[dict]) -> None:
    """Show the dict structure that agents receive."""
    print_section("2. State dict shape (what agents see)")

    doc = docs[0]
    print(json.dumps(
        {
            "name": doc["name"],
            "format": doc["format"],
            "size_bytes": doc["size_bytes"],
            "chunk_count": doc["chunk_count"],
            "total_tokens_estimate": doc["total_tokens_estimate"],
            "chunks": [
                {"index": c["index"], "content": c["content"][:80] + "..."}
                for c in doc["chunks"]
            ],
        },
        indent=2,
    ))


async def demo_inline_content(pipeline: DocumentPipeline) -> None:
    """Load documents from inline dicts (no files on disk)."""
    print_section("3. Load inline content (no files needed)")

    inline_docs, inline_summary = await pipeline.load([
        {"name": "user-feedback.txt", "content": "The search feature is slow. Results are irrelevant."},
        {"name": "metrics.txt", "content": "p50 latency: 340ms, p99: 2100ms, error rate: 0.3%"},
    ])

    print(f"Summary: {inline_summary}\n")
    for doc in inline_docs:
        print(f"  {doc['name']}: {doc['chunk_count']} chunk(s), ~{doc['total_tokens_estimate']} tokens")


async def demo_instructions(pipeline: DocumentPipeline) -> None:
    """Load task instructions from a file."""
    print_section("4. Instructions from file")

    instructions = await pipeline.load_instructions_file("prompts/analysis.md")
    print(f"Instructions ({len(instructions)} chars):")
    print(f"  {instructions}")


def demo_scoping(pipeline: DocumentPipeline, all_docs: list[dict]) -> None:
    """Show how different agents see different document slices."""
    print_section("5. Per-agent document scoping")

    agents = [
        ("summarizer", AgentDefinition(
            id="summarizer", role="Document Summarizer",
            system_prompt="Summarize all documents.",
            behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
            document_mode="full",
        )),
        ("planner", AgentDefinition(
            id="planner", role="Action Planner",
            system_prompt="Extract action items.",
            behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
            documents=["meeting-notes.md"],
            document_mode="full",
        )),
        ("router", AgentDefinition(
            id="router", role="Document Router",
            system_prompt="Decide which agent handles each doc.",
            behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
            document_mode="metadata_only",
        )),
        ("editor", AgentDefinition(
            id="editor", role="Final Editor",
            system_prompt="Polish the final output.",
            behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
            document_mode="none",
        )),
    ]

    for name, agent_def in agents:
        scoped = pipeline.scope_for_agent(all_docs, agent_def)
        mode = agent_def.document_mode or "none"
        doc_filter = agent_def.documents
        doc_names = [d.get("name", "?") for d in scoped] if scoped else []
        filter_str = f", filter={doc_filter}" if doc_filter else ""
        print(f"  {name:12s} mode={mode:14s}{filter_str}")
        print(f"               -> sees {len(scoped)} doc(s): {doc_names}")


def demo_token_budget(pipeline: DocumentPipeline, all_docs: list[dict]) -> None:
    """Show how token budgets limit document content."""
    print_section("6. Token budget enforcement")

    reviewer = AgentDefinition(
        id="reviewer", role="Quick Reviewer",
        system_prompt="Spot-check the documents.",
        behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
        document_mode="full",
        max_document_tokens=20,
    )
    scoped = pipeline.scope_for_agent(all_docs, reviewer)
    total_chunks = sum(len(d.get("chunks", [])) for d in scoped)
    print(f"  reviewer (max_document_tokens=20): {len(scoped)} doc(s), {total_chunks} chunk(s) kept")
    print()
    print("  Token budgets prevent context overflow by trimming chunks that")
    print("  exceed the agent's declared limit.")


async def main() -> None:
    """Run all document pipeline demonstrations."""
    print("=" * 60)
    print("  HiveFlow -- Document Pipeline (No LLM Required)")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir)
        create_sample_files(work_dir)

        registry = DocumentLoaderRegistry()
        pipeline = DocumentPipeline(registry=registry, working_dir=work_dir)

        docs = await demo_load_files(pipeline)
        demo_state_shape(docs)
        await demo_inline_content(pipeline)
        await demo_instructions(pipeline)

        all_docs, _ = await pipeline.load(["transcript.txt", "meeting-notes.md"])
        demo_scoping(pipeline, all_docs)
        demo_token_budget(pipeline, all_docs)

    print(f"\n{'=' * 60}")
    print("  Supported formats: txt, md, csv, json, xml, html, pdf, docx, xlsx, pptx")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
