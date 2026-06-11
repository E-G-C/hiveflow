#!/usr/bin/env python3
"""Document Input Pipeline 02: Load Documents from In-Memory Bytes.

Demonstrates User Story 2 — the ``load_from_bytes()`` method that lets
you feed raw byte streams (uploads, blobs, buffers) into the document
pipeline without writing temporary files yourself.

What this example covers:
  - Default temp-file delegation (works for every loader)
  - Inline bytes via DocumentPipeline.load([{"name": ..., "bytes": ...}])
  - Error handling for empty bytes
  - Multiple formats: plain text, markdown, HTML, JSON
  - MarkItDown loader for rich formats (if installed)

No LLM is required — this demonstrates the data pipeline only.

Usage:
    uv run python examples/document_input_pipeline/02_load_from_bytes.py
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from _helpers import print_kv, print_section

from hiveflow.core.documents import DocumentPipeline
from hiveflow.plugins.documents import DocumentLoaderRegistry


# ---------------------------------------------------------------------------
# Sample byte payloads (simulating HTTP uploads, DB blobs, etc.)
# ---------------------------------------------------------------------------

PLAIN_TEXT_BYTES = b"""\
Project Status Update - February 2026

Current sprint velocity: 42 points (target: 40)
Bugs resolved this week: 17
Features shipped: 3 (auth revamp, search v2, dashboard widgets)

Risk items:
- Database migration scheduled for Sunday requires 2h downtime
- Third-party API rate limits may affect batch processing
- QA team at 75% capacity due to PTO
"""

MARKDOWN_BYTES = b"""\
# API Design Review

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /api/v2/users | List users |
| POST | /api/v2/users | Create user |
| GET | /api/v2/users/:id | Get user by ID |
| PUT | /api/v2/users/:id | Update user |
| DELETE | /api/v2/users/:id | Delete user |

## Authentication

All endpoints require Bearer token authentication.
Rate limit: 100 requests per minute per API key.

## Error Codes

- `400` -- Invalid request body
- `401` -- Missing or invalid auth token
- `404` -- Resource not found
- `429` -- Rate limit exceeded
"""

HTML_BYTES = (
    b"<!DOCTYPE html>\n"
    b"<html>\n"
    b"<head><title>Meeting Notes</title></head>\n"
    b"<body>\n"
    b"<h1>Engineering Standup - Feb 28, 2026</h1>\n"
    b"<h2>Updates</h2>\n"
    b"<ul>\n"
    b"  <li><strong>Alice</strong>: Completed CI/CD pipeline migration</li>\n"
    b"  <li><strong>Bob</strong>: Working on WebSocket reconnection logic</li>\n"
    b"  <li><strong>Carol</strong>: Shipped accessibility fixes for WCAG 2.1</li>\n"
    b"</ul>\n"
    b"<h2>Blockers</h2>\n"
    b"<p>Staging environment SSL cert expires tomorrow.</p>\n"
    b"</body>\n"
    b"</html>\n"
)

JSON_BYTES = json.dumps({
    "project": "HiveFlow",
    "version": "0.1.0",
    "features": [
        {"name": "Document Pipeline", "status": "complete"},
        {"name": "Summary Mode", "status": "in-progress"},
        {"name": "Template Variables", "status": "planned"},
    ],
    "metrics": {
        "test_coverage": 87.3,
        "open_issues": 12,
        "contributors": 5,
    },
}, indent=2).encode("utf-8")


async def demo_load_from_bytes_direct() -> None:
    """Use DocumentLoaderPlugin.load_from_bytes() directly."""
    print_section("1. Direct load_from_bytes() on Loaders")

    registry = DocumentLoaderRegistry()
    registry.discover()

    # Plain text loader
    text_loader = registry.get_loader_for_file("report.txt")
    assert text_loader is not None, "No loader found for .txt"

    doc = await text_loader.load_from_bytes(PLAIN_TEXT_BYTES, "status-update.txt")
    print_kv("Loader", text_loader.plugin_id)
    print_kv("Document name", doc.name or "(from loader)")
    print_kv("Content length", f"{len(doc.content)} chars")
    print_kv("First line", doc.content.splitlines()[0])

    # Markdown loader
    md_loader = registry.get_loader_for_file("design.md")
    if md_loader:
        doc = await md_loader.load_from_bytes(MARKDOWN_BYTES, "api-design.md")
        print(f"\n  Markdown loader ({md_loader.plugin_id}):")
        print_kv("Content length", f"{len(doc.content)} chars", indent=4)
        print_kv("First line", doc.content.splitlines()[0], indent=4)

    # JSON loader
    json_loader = registry.get_loader_for_file("data.json")
    if json_loader:
        doc = await json_loader.load_from_bytes(JSON_BYTES, "project.json")
        print(f"\n  JSON loader ({json_loader.plugin_id}):")
        print_kv("Content length", f"{len(doc.content)} chars", indent=4)


async def demo_pipeline_bytes_loading() -> None:
    """Load bytes through the DocumentPipeline using dict format."""
    print_section("2. DocumentPipeline with Bytes Dicts")

    pipeline = DocumentPipeline()

    # Load multiple byte-stream documents at once
    docs, summary = await pipeline.load([
        {"name": "status-update.txt", "bytes": PLAIN_TEXT_BYTES},
        {"name": "api-design.md", "bytes": MARKDOWN_BYTES},
        {"name": "project-info.json", "bytes": JSON_BYTES},
    ])

    print(f"  Summary: {summary}\n")
    for doc in docs:
        print_kv("Name", doc["name"])
        print_kv("Format", doc["format"])
        print_kv("Size", f"{doc['size_bytes']} bytes")
        print_kv("Chunks", doc["chunk_count"])
        print_kv("Tokens", f"~{doc['total_tokens_estimate']}")
        first_chunk = doc["chunks"][0]["content"][:80] if doc["chunks"] else "(empty)"
        print_kv("Preview", first_chunk + "...")
        print()


async def demo_empty_bytes_error() -> None:
    """Verify that empty bytes raise a clear error."""
    print_section("3. Error Handling: Empty Bytes")

    registry = DocumentLoaderRegistry()
    registry.discover()
    loader = registry.get_loader_for_file("test.txt")
    assert loader is not None

    try:
        await loader.load_from_bytes(b"", "empty.txt")
        print("  ERROR: Should have raised ValueError")
    except ValueError as exc:
        print(f"  Caught expected ValueError:")
        print(f"    {exc}")

    # Via pipeline: empty bytes fall back to an empty text document
    # (the pipeline catches loader errors and falls back gracefully)
    pipeline = DocumentPipeline()
    docs, summary = await pipeline.load([{"name": "nothing.txt", "bytes": b""}])
    doc = docs[0]
    print(f"\n  Pipeline fallback for empty bytes:")
    print(f"    Name: {doc['name']}, Chunks: {doc['chunk_count']}, "
          f"Content: {repr(doc['chunks'][0]['content'][:30]) if doc['chunks'] else '(none)'}")


async def demo_mixed_sources() -> None:
    """Combine file, inline, and bytes sources in one pipeline.load() call."""
    print_section("4. Mixed Sources: File + Inline + Bytes")

    import tempfile
    work_dir = Path(tempfile.mkdtemp())

    # Create a real file
    (work_dir / "config.txt").write_text(
        "max_workers = 8\ntimeout = 30\nretry_count = 3\n",
        encoding="utf-8",
    )

    pipeline = DocumentPipeline(working_dir=work_dir)

    docs, summary = await pipeline.load([
        # File path (string)
        "config.txt",
        # Inline content (dict with 'content')
        {"name": "readme.txt", "content": "This is an inline document for testing."},
        # Byte stream (dict with 'bytes')
        {"name": "upload.txt", "bytes": PLAIN_TEXT_BYTES},
    ])

    print(f"  Summary: {summary}\n")
    for doc in docs:
        source_type = "file" if doc.get("name") == "config.txt" else (
            "bytes" if doc.get("name") == "upload.txt" else "inline"
        )
        print(f"  [{source_type:6s}] {doc['name']:20s}  "
              f"{doc['chunk_count']} chunk(s)  ~{doc['total_tokens_estimate']} tokens")


async def demo_markitdown_bytes() -> None:
    """Demonstrate load_from_bytes with MarkItDown for HTML content."""
    print_section("5. MarkItDown Loader with Bytes (HTML)")

    registry = DocumentLoaderRegistry()
    registry.discover()

    # Get HTML loaders — MarkItDown registers for .html
    loaders = registry.get_all_loaders_for_file("page.html")
    if not loaders:
        print("  No HTML loaders available. Skipping.")
        return

    for loader in loaders:
        try:
            doc = await loader.load_from_bytes(HTML_BYTES, "standup-notes.html")
            print_kv("Loader", loader.plugin_id)
            print_kv("Content length", f"{len(doc.content)} chars")
            print_kv("Content preview", doc.content[:120].replace("\n", " ") + "...")
            print()
        except Exception as exc:
            print(f"  Loader '{loader.plugin_id}' failed: {exc}")


async def main() -> None:
    print("=" * 64)
    print("  Document Input Pipeline -- 02: Load from Bytes")
    print("=" * 64)

    await demo_load_from_bytes_direct()
    await demo_pipeline_bytes_loading()
    await demo_empty_bytes_error()
    await demo_mixed_sources()
    await demo_markitdown_bytes()

    print_section("Done")
    print("  All load_from_bytes demonstrations completed successfully.")


if __name__ == "__main__":
    asyncio.run(main())
