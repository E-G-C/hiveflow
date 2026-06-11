"""Example: Load Documents from In-Memory Bytes.

Demonstrates how to:
1. Use load_from_bytes() on individual document loaders
2. Load bytes through the DocumentPipeline
3. Mix file paths, inline content, and byte content

No live LLM needed — purely document loading.

Usage:
    uv run python examples/config_operations/07_load_from_bytes.py
"""

import asyncio

from hiveflow.core.documents import DocumentPipeline
from hiveflow.plugins.documents.plain_text import PlainTextLoader
from hiveflow.plugins.documents.markdown_loader import MarkdownLoader


async def main() -> None:
    # -- 1. Direct loader: plain text bytes ------------------------------------
    print("--- 1. PlainTextLoader.load_from_bytes() ---")
    loader = PlainTextLoader()
    text_bytes = b"This is a plain text document loaded from bytes.\nIt has two lines."
    doc = await loader.load_from_bytes(text_bytes, "notes.txt")
    print(f"  Name:    {doc.name or 'notes.txt'}")
    print(f"  Content: {doc.content[:60]}...")
    print(f"  Size:    {len(text_bytes)} bytes")

    # -- 2. Direct loader: markdown bytes --------------------------------------
    print("\n--- 2. MarkdownLoader.load_from_bytes() ---")
    loader = MarkdownLoader()
    md_bytes = b"# Meeting Notes\n\n## Action Items\n\n- Review Q3 budget\n- Schedule follow-up\n"
    doc = await loader.load_from_bytes(md_bytes, "meeting-notes.md")
    print(f"  Content: {doc.content[:80]}...")

    # -- 3. Empty bytes error --------------------------------------------------
    print("\n--- 3. Empty bytes validation ---")
    try:
        await PlainTextLoader().load_from_bytes(b"", "empty.txt")
    except ValueError as e:
        print(f"  Caught: {e}")

    # -- 4. Pipeline: bytes dict -----------------------------------------------
    print("\n--- 4. DocumentPipeline with bytes dict ---")
    pipeline = DocumentPipeline()
    docs, summary = await pipeline.load([
        {"name": "report.txt", "bytes": b"Quarterly revenue increased 15% YoY."},
        {"name": "notes.txt", "bytes": b"Key takeaway: invest in AI infrastructure."},
    ])
    print(f"  Documents loaded: {len(docs)}")
    print(f"  Summary: {summary}")
    for d in docs:
        print(f"    {d['name']}: {d['chunk_count']} chunks, ~{d['total_tokens_estimate']} tokens")

    # -- 5. Pipeline: mixed content types --------------------------------------
    print("\n--- 5. Mixed loading (inline + bytes) ---")
    docs, summary = await pipeline.load([
        {"name": "inline.txt", "content": "This is inline string content."},
        {"name": "bytes.txt", "bytes": b"This is byte content from an upload."},
    ])
    print(f"  Documents: {len(docs)}")
    for d in docs:
        chunks = d.get("chunks", [])
        content = chunks[0]["content"][:50] if chunks else "—"
        print(f"    {d['name']}: {content}...")

    # -- 6. Simulated API upload scenario --------------------------------------
    print("\n--- 6. Simulated API upload ---")
    # In a real API, you'd receive bytes from request.body()
    uploaded_content = (
        b"AGREEMENT\n\n"
        b"This Service Level Agreement is entered into between Acme Corp "
        b"and Client Inc, effective January 1, 2026.\n\n"
        b"1. Service Commitment: 99.9% uptime guarantee\n"
        b"2. Response Time: Critical issues within 1 hour\n"
        b"3. Compensation: Service credits for SLA breaches\n"
    )

    docs, summary = await pipeline.load([
        {"name": "sla-agreement.txt", "bytes": uploaded_content},
    ])
    print(f"  Loaded: {docs[0]['name']} ({docs[0]['size_bytes']} bytes)")
    print(f"  Chunks: {docs[0]['chunk_count']}")
    print(f"  Preview: {docs[0]['chunks'][0]['content'][:80]}...")


if __name__ == "__main__":
    asyncio.run(main())
