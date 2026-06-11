#!/usr/bin/env python3
"""Data Processing 06: Citation tracking with multiple styles.

Demonstrates the citation system:
  1. Track citations from multiple sources
  2. Format references in APA, MLA, Chicago, numbered, and inline styles
  3. CitationConfig for declarative team-level configuration
  4. URL deduplication in the tracker

No API keys required.

Usage:
    uv run python examples/data_processing/06_citations.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hiveflow.core.citations import Citation, CitationTracker
from hiveflow.core.schema import CitationConfig


def print_section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}\n")


async def main() -> None:
    # -- 1. Create and populate a citation tracker --
    print_section("1. Track citations from research sources")

    tracker = CitationTracker()

    citations = [
        Citation(
            url="https://nature.com/quantum-computing-2025",
            title="Advances in Quantum Computing",
            author="Chen, L. et al.",
            date="2025",
            source="Nature Physics",
            content_snippet="Quantum computing has reached a milestone...",
        ),
        Citation(
            url="https://arxiv.org/abs/2501.12345",
            title="Scalable Error Correction for Quantum Systems",
            author="Smith, A. and Jones, B.",
            date="2025",
            source="arXiv preprint",
            content_snippet="We present a novel error correction scheme...",
        ),
        Citation(
            url="https://ieee.org/quantum-applications",
            title="Industrial Applications of Quantum Computing",
            author="IEEE Standards Association",
            date="2024",
            source="IEEE Spectrum",
            content_snippet="Quantum computing is finding real-world applications...",
        ),
        Citation(
            url="https://ai.stanford.edu/llm-quantum",
            title="LLM-Assisted Quantum Circuit Design",
            author="Patel, R.",
            date="2025",
            source="Stanford AI Lab",
            content_snippet="Large language models can assist in quantum circuit...",
        ),
    ]

    for c in citations:
        tracker.add(c)
        print(f"  Added: [{c.citation_id}] {c.title}")

    print(f"\n  Total citations: {tracker.count}")

    # -- 2. Test deduplication --
    print_section("2. Deduplication (same URL added twice)")

    duplicate = Citation(
        url="https://nature.com/quantum-computing-2025",
        title="Duplicate Entry",
        author="Nobody",
    )
    tracker.add(duplicate)
    print(f"  After adding duplicate: {tracker.count} citations (unchanged)")

    # -- 3. Format in all styles --
    print_section("3. Reference formatting -- APA style")
    print(tracker.format_references(style="apa"))

    print_section("4. Reference formatting -- MLA style")
    print(tracker.format_references(style="mla"))

    print_section("5. Reference formatting -- Chicago style")
    print(tracker.format_references(style="chicago"))

    print_section("6. Reference formatting -- Numbered style")
    print(tracker.format_references(style="numbered"))

    print_section("7. Reference formatting -- Inline style")
    print(tracker.format_references(style="inline"))

    # -- 4. Individual citation formats --
    print_section("8. Individual citation formatting")

    c = citations[0]
    print(f"  APA:     {c.format_apa()}")
    print(f"  MLA:     {c.format_mla()}")
    print(f"  Chicago: {c.format_chicago()}")
    print(f"  Inline:  {c.format_inline()}")
    print(f"  ID:      {c.citation_id}")

    # -- 5. CitationConfig (team-level configuration) --
    print_section("9. CitationConfig -- declarative configuration")

    configs = [
        CitationConfig(enabled=True, style="apa", inline=True, generate_reference_section=True),
        CitationConfig(enabled=True, style="mla", inline=False),
        CitationConfig(enabled=False),
    ]

    for cfg in configs:
        print(f"  enabled={cfg.enabled}, style={cfg.style!r}, "
              f"inline={cfg.inline}, refs={cfg.generate_reference_section}")

    print("\n  When enabled=False, no citation processing occurs (default).")
    print("  When enabled=True, the workflow engine auto-tracks visited URLs")
    print("  and assembles a reference section in the configured style.")

    # -- 6. Export to state dict --
    print_section("10. Export to workflow state")

    state_dict = tracker.to_state_dict()
    print(f"  Keys: {list(state_dict.keys())}")
    print(f"  Citation count: {state_dict['citation_count']}")
    print(f"  First citation URL: {state_dict['citations'][0]['url']}")

    print("\nDone!")


if __name__ == "__main__":
    asyncio.run(main())
