"""Example: Custom layout template for published output.

Demonstrates how to create and use a custom layout template that controls
which sections appear in published output and in what order. Uses the
"executive-brief" layout from the layouts/ subdirectory.

Usage:
    uv run python examples/output_pipeline/custom_layout.py

Output:
    ./output/layout/executive-brief.md
"""

import asyncio
from pathlib import Path

from hiveflow import (
    Citation,
    PayloadSection,
    ResultPayload,
    load_layout,
)
from hiveflow.plugins.publishers import MarkdownPublisher, PublisherRegistry


async def main() -> None:
    """Publish a ResultPayload using a custom layout template."""

    # --- 1. Build a ResultPayload with sections ---
    # In a real workflow, this comes from ResultPayload.from_workflow_result().
    # Here we construct it manually to show the full data model.

    payload = ResultPayload(
        title="Q4 Market Analysis",
        content=(
            "The global AI market grew 38% year-over-year in Q4, driven by "
            "enterprise adoption of large language models. Key growth areas "
            "include code generation (+52%), customer service automation (+41%), "
            "and document processing (+35%).\n\n"
            "Three dominant trends emerged: (1) shift from cloud-only to "
            "hybrid deployment, (2) increasing demand for domain-specific "
            "fine-tuning, and (3) growing emphasis on AI governance and "
            "compliance frameworks."
        ),
        sections=[
            PayloadSection(
                section_id="executive_summary",
                title="Executive Summary",
                content=(
                    "The AI market expanded significantly in Q4, with enterprise "
                    "adoption driving 38% year-over-year growth. Hybrid deployment "
                    "models and domain-specific solutions are the key trends."
                ),
                order=0,
                agent_id="researcher",
            ),
            PayloadSection(
                section_id="market_data",
                title="Market Data",
                content=(
                    "- Global AI market size: $196B (Q4 estimate)\n"
                    "- Year-over-year growth: 38%\n"
                    "- Enterprise adoption rate: 67% of Fortune 500\n"
                    "- Top growth segment: Code generation (+52%)"
                ),
                order=1,
                agent_id="researcher",
            ),
        ],
        metadata={
            "date": "2025-01-15",
            "workflow_id": "mkt-analysis-q4",
        },
        references=[
            Citation(
                url="https://example.com/ai-market-report",
                title="Global AI Market Report Q4 2024",
                author="TechAnalytics Research",
                date="2025-01",
            ),
            Citation(
                url="https://example.com/enterprise-ai-survey",
                title="Enterprise AI Adoption Survey",
                author="McKinley & Associates",
                date="2024-12",
            ),
        ],
    )

    # --- 2. Load a custom layout template ---
    # The layout is a YAML file in the layouts/ subdirectory.
    layouts_dir = str(Path(__file__).parent / "layouts")
    layout = load_layout("executive-brief", extra_dirs=[layouts_dir])

    print(f"Layout: {layout.name}")
    print(f"Description: {layout.description}")
    print(f"Sections defined: {len(layout.sections)}")
    for sec in layout.sections:
        req = "required" if sec.required else "optional"
        print(f"  - {sec.id} ({req}) -> source: {sec.source}")

    # --- 3. Apply layout to see rendered sections ---
    rendered = layout.apply(payload)
    print(f"\nRendered {len(rendered)} sections:")
    for sec in rendered:
        print(f"  - {sec.section_id}: {sec.heading or '(no heading)'}")

    # --- 4. Publish with the custom layout ---
    registry = PublisherRegistry(drop_in_dir=None)
    registry.register(MarkdownPublisher())

    paths = await registry.publish_all(
        payload,
        output_dir="./output/layout",
        formats=["markdown"],
        filename="executive-brief",
        layout=layout,  # Apply custom layout
    )

    print(f"\nPublished {len(paths)} files:")
    for path in paths:
        print(f"  -> {path} ({path.stat().st_size:,} bytes)")

    # Show a preview of the output
    if paths:
        content = paths[0].read_text(encoding="utf-8")
        lines = content.split("\n")
        preview = "\n".join(lines[:30])
        print(f"\nPreview (first 30 lines):\n{preview}")
        if len(lines) > 30:
            print(f"  ... ({len(lines) - 30} more lines)")


if __name__ == "__main__":
    asyncio.run(main())
