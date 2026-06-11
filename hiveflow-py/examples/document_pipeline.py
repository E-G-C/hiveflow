"""Example: Document Pipeline -- loading, chunking, and scoping.

Demonstrates how to:
1. Load documents from files and inline content
2. Inspect the state dict shape (chunks, tokens, metadata)
3. Load instructions from a file
4. Scope documents per-agent (full, metadata_only, none)
5. Apply token budgets for large documents

No LLM provider is needed -- this shows the data pipeline only.

Usage:
    uv run python examples/document_pipeline.py
"""

import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hiveflow.core.documents import DocumentPipeline
from hiveflow.core.schema import AgentBehaviorTypeSchema, AgentDefinition
from hiveflow.plugins.documents import DocumentLoaderRegistry


def print_section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}\n")


async def main() -> None:
    # Create sample files in a temp directory
    work_dir = Path(tempfile.mkdtemp())

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

    # -- 1. Load documents from files -------------------------------------

    print_section("1. Load documents from files")

    registry = DocumentLoaderRegistry()
    pipeline = DocumentPipeline(registry=registry, working_dir=work_dir)

    docs, summary = await pipeline.load(["transcript.txt", "meeting-notes.md"])

    print(f"Summary: {summary}\n")
    for doc in docs:
        print(f"  Name:   {doc['name']}")
        print(f"  Format: {doc['format']}")
        print(f"  Size:   {doc['size_bytes']} bytes")
        print(f"  Chunks: {doc['chunk_count']}")
        print(f"  Tokens: ~{doc['total_tokens_estimate']}")
        print()

    # -- 2. Inspect state dict shape --------------------------------------

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

    # -- 3. Load inline content (no file needed) -------------------------

    print_section("3. Load inline content")

    inline_docs, inline_summary = await pipeline.load([
        {"name": "user-feedback.txt", "content": "The search feature is slow. Results are irrelevant."},
        {"name": "metrics.txt", "content": "p50 latency: 340ms, p99: 2100ms, error rate: 0.3%"},
    ])

    print(f"Summary: {inline_summary}\n")
    for doc in inline_docs:
        print(f"  {doc['name']}: {doc['chunk_count']} chunk(s), ~{doc['total_tokens_estimate']} tokens")

    # -- 4. Load instructions from a file ---------------------------------

    print_section("4. Instructions from file")

    instructions = await pipeline.load_instructions_file("prompts/analysis.md")
    print(f"Instructions ({len(instructions)} chars):")
    print(f"  {instructions[:120]}...")

    # -- 5. Per-agent document scoping ------------------------------------

    print_section("5. Per-agent scoping")

    # Reload docs for scoping demo
    all_docs, _ = await pipeline.load(["transcript.txt", "meeting-notes.md"])

    # Agent A: sees everything (full mode)
    summarizer = AgentDefinition(
        id="summarizer",
        role="Document Summarizer",
        system_prompt="Summarize all documents.",
        behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
        document_mode="full",
    )
    scoped = pipeline.scope_for_agent(all_docs, summarizer)
    print(f"  summarizer (mode=full):          {len(scoped)} doc(s), chunks accessible")

    # Agent B: sees only meeting notes
    planner = AgentDefinition(
        id="planner",
        role="Action Planner",
        system_prompt="Extract action items.",
        behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
        documents=["meeting-notes.md"],
        document_mode="full",
    )
    scoped = pipeline.scope_for_agent(all_docs, planner)
    print(f"  planner   (mode=full, filtered): {len(scoped)} doc(s) -- {[d['name'] for d in scoped]}")

    # Agent C: metadata only (no content)
    router = AgentDefinition(
        id="router",
        role="Document Router",
        system_prompt="Decide which agent handles each doc.",
        behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
        document_mode="metadata_only",
    )
    scoped = pipeline.scope_for_agent(all_docs, router)
    print(f"  router    (mode=metadata_only):  {len(scoped)} doc(s), keys: {list(scoped[0].keys())}")

    # Agent D: no documents
    editor = AgentDefinition(
        id="editor",
        role="Final Editor",
        system_prompt="Polish the final output.",
        behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
        document_mode="none",
    )
    scoped = pipeline.scope_for_agent(all_docs, editor)
    print(f"  editor    (mode=none):           {len(scoped)} doc(s)")

    # -- 6. Token budget enforcement --------------------------------------

    print_section("6. Token budget")

    reviewer = AgentDefinition(
        id="reviewer",
        role="Quick Reviewer",
        system_prompt="Spot-check the documents.",
        behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
        document_mode="full",
        max_document_tokens=20,
    )
    scoped = pipeline.scope_for_agent(all_docs, reviewer)
    total_chunks = sum(len(d.get("chunks", [])) for d in scoped)
    print(f"  reviewer (max_document_tokens=20): {len(scoped)} doc(s), {total_chunks} chunk(s) kept")

    print()


if __name__ == "__main__":
    asyncio.run(main())
