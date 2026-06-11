"""Example: LLM-Based Document Summary Mode.

Demonstrates how to:
1. Generate LLM summaries of documents via DocumentPipeline
2. Cache summaries in workflow state for reuse across agents
3. Scope documents in summary mode for agents
4. See token savings compared to full document content

Uses live Azure OpenAI via RBAC for summary generation.

Prerequisites:
    AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com
    uv sync --extra llm-azure

Usage:
    AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com \
        uv run python examples/config_operations/08_document_summary_mode.py
"""

import asyncio
import os
from typing import Any

from hiveflow.core.documents import DocumentPipeline


def _make_long_document(name: str, paragraphs: int = 5) -> dict[str, Any]:
    """Create a document state dict with multiple paragraphs."""
    content = "\n\n".join(
        f"Paragraph {i+1}: This section discusses important findings about "
        f"artificial intelligence and its applications in enterprise software. "
        f"Key metrics show significant improvements in productivity, with "
        f"organizations reporting 20-40% efficiency gains. The technology "
        f"landscape continues to evolve rapidly, requiring adaptive strategies."
        for i in range(paragraphs)
    )
    words = len(content.split())
    return {
        "name": name,
        "format": "txt",
        "size_bytes": len(content.encode()),
        "chunk_count": paragraphs,
        "total_tokens_estimate": words * 2,
        "chunks": [
            {"index": i, "content": p}
            for i, p in enumerate(content.split("\n\n"))
        ],
    }


async def main() -> None:
    pipeline = DocumentPipeline()

    # -- 1. Create test documents ----------------------------------------------
    print("--- 1. Test documents ---")
    docs = [
        _make_long_document("market-analysis.txt", paragraphs=8),
        _make_long_document("competitor-report.txt", paragraphs=6),
        _make_long_document("financial-summary.txt", paragraphs=4),
    ]
    for d in docs:
        print(f"  {d['name']}: {d['chunk_count']} chunks, "
              f"~{d['total_tokens_estimate']} tokens")
    total_tokens = sum(d["total_tokens_estimate"] for d in docs)
    print(f"  Total: ~{total_tokens} tokens")

    # -- 2. Generate summaries with live LLM -----------------------------------
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    if not endpoint:
        print("\n--- 2. Skipped (set AZURE_OPENAI_ENDPOINT for live demo) ---")
        print("  Will demonstrate caching and scoping with mock summaries.")
        # Create mock summaries for demonstration
        state: dict[str, Any] = {
            "documents": docs,
            "_document_summaries": {
                "market-analysis.txt": "AI market growing 35% YoY with enterprise adoption accelerating.",
                "competitor-report.txt": "Top 3 competitors investing heavily in generative AI capabilities.",
                "financial-summary.txt": "Q3 revenue exceeded targets by 12%, driven by AI product line.",
            },
        }
    else:
        print("\n--- 2. Generate summaries with live LLM ---")
        from hiveflow.plugins.llm import LLMConfig, get_llm_registry

        registry = get_llm_registry()
        if "azure" not in registry.list_ids():
            print("  Azure provider not available. Install with: uv sync --extra llm-azure")
            return

        deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
        provider, model = registry.resolve_model(f"azure:{deployment}")

        state: dict[str, Any] = {"documents": docs}
        summaries = await pipeline.generate_summaries(
            docs, state, provider, max_tokens=100
        )

        for name, summary in summaries.items():
            print(f"  {name}: {summary[:80]}...")

    # -- 3. Caching demonstration ----------------------------------------------
    print("\n--- 3. Summary caching ---")
    cache = state.get("_document_summaries", {})
    print(f"  Cached summaries: {len(cache)}")
    for name in cache:
        print(f"    {name}: cached [ok]")
    print("  (Second call for same docs would skip LLM -- zero additional cost)")

    # -- 4. Scope documents in summary mode ------------------------------------
    print("\n--- 4. Agent scoping with summary mode ---")

    class PlannerAgent:
        """Mock agent definition with summary mode."""
        documents = None
        document_mode = "summary"
        max_document_tokens = None

    scoped = pipeline.scope_for_agent(docs, PlannerAgent(), state=state)
    summary_tokens = 0
    for d in scoped:
        chunks = d.get("chunks", [])
        content = chunks[0]["content"] if chunks else "—"
        tokens = d.get("total_tokens_estimate", 0)
        summary_tokens += tokens
        print(f"  {d['name']}: {content[:60]}... ({tokens} tokens)")

    # -- 5. Token savings comparison -------------------------------------------
    print(f"\n--- 5. Token savings ---")
    print(f"  Full documents:    ~{total_tokens} tokens")
    print(f"  Summary mode:      ~{summary_tokens} tokens")
    if total_tokens > 0:
        savings = (1 - summary_tokens / total_tokens) * 100
        print(f"  Savings:           {savings:.0f}%")

    # -- 6. Contrast with other document modes ---------------------------------
    print("\n--- 6. Document mode comparison ---")
    modes = {
        "full": lambda: type("A", (), {"documents": None, "document_mode": "full", "max_document_tokens": None})(),
        "summary": lambda: type("A", (), {"documents": None, "document_mode": "summary", "max_document_tokens": None})(),
        "metadata_only": lambda: type("A", (), {"documents": None, "document_mode": "metadata_only", "max_document_tokens": None})(),
        "none": lambda: type("A", (), {"documents": None, "document_mode": "none", "max_document_tokens": None})(),
    }
    for mode_name, make_def in modes.items():
        scoped = pipeline.scope_for_agent(docs, make_def(), state=state)
        total = sum(d.get("total_tokens_estimate", 0) for d in scoped)
        has_chunks = any(d.get("chunks") for d in scoped)
        print(f"  {mode_name:15s}: {len(scoped)} docs, ~{total} tokens, chunks={'yes' if has_chunks else 'no'}")


if __name__ == "__main__":
    asyncio.run(main())
