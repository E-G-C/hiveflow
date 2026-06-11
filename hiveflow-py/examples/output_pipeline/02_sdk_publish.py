"""Example: Programmatic SDK publishing with rich payload.

Demonstrates constructing a full ResultPayload manually with sections,
citations, actions, and cost data -- then publishing to multiple formats
using the SDK. This is the path for applications that build payloads
programmatically without running a full workflow.

Usage:
    uv run python examples/output_pipeline/sdk_publish.py

Output:
    ./output/sdk/analysis.md
    ./output/sdk/analysis.json
"""

import asyncio
from pathlib import Path

from hiveflow import (
    ActionRecord,
    Citation,
    PayloadSection,
    ResultPayload,
)
from hiveflow.core.cost import AgentCostSummary, WorkflowCostReport
from hiveflow.plugins.publishers import MarkdownPublisher, PublisherRegistry
from hiveflow.plugins.publishers.json_publisher import JSONPublisher


async def main() -> None:
    """Build a rich ResultPayload and publish to Markdown + JSON."""

    # --- 1. Build sections ---
    sections = [
        PayloadSection(
            section_id="executive_summary",
            title="Executive Summary",
            content=(
                "This analysis evaluates three cloud providers for our "
                "production workloads. AWS leads in service breadth, Azure "
                "in enterprise integration, and GCP in ML/AI capabilities. "
                "We recommend a multi-cloud strategy with Azure as primary."
            ),
            order=0,
            agent_id="analyst",
        ),
        PayloadSection(
            section_id="aws_analysis",
            title="AWS Analysis",
            content=(
                "**Strengths**: Widest service catalog (200+ services), "
                "mature ecosystem, largest community.\n\n"
                "**Weaknesses**: Complex pricing, steep learning curve for "
                "IAM policies.\n\n"
                "**Cost estimate**: $12,400/month for our workload profile."
            ),
            order=1,
            agent_id="researcher",
        ),
        PayloadSection(
            section_id="azure_analysis",
            title="Azure Analysis",
            content=(
                "**Strengths**: Native AD integration, strong hybrid story, "
                "enterprise agreements, GitHub/DevOps integration.\n\n"
                "**Weaknesses**: Portal UX inconsistency, some services lag "
                "AWS equivalents.\n\n"
                "**Cost estimate**: $11,800/month with EA discount."
            ),
            order=2,
            agent_id="researcher",
        ),
        PayloadSection(
            section_id="gcp_analysis",
            title="GCP Analysis",
            content=(
                "**Strengths**: Best-in-class ML/AI (Vertex AI, TPUs), "
                "strong data analytics (BigQuery), competitive pricing.\n\n"
                "**Weaknesses**: Smaller enterprise footprint, fewer "
                "compliance certifications.\n\n"
                "**Cost estimate**: $10,900/month with committed use."
            ),
            order=3,
            agent_id="researcher",
        ),
        PayloadSection(
            section_id="recommendation",
            title="Recommendation",
            content=(
                "Adopt Azure as primary provider for enterprise workloads "
                "with GCP for ML/AI pipelines. Estimated combined cost: "
                "$14,200/month (32% less than single-provider AWS)."
            ),
            order=4,
            agent_id="analyst",
        ),
    ]

    # --- 2. Build citations ---
    references = [
        Citation(
            url="https://example.com/gartner-cloud-2024",
            title="Gartner Magic Quadrant for Cloud Infrastructure 2024",
            author="Gartner Research",
            date="2024-10",
            source_type="web",
        ),
        Citation(
            url="https://example.com/flexera-cloud-report",
            title="State of the Cloud Report 2024",
            author="Flexera",
            date="2024-09",
            source_type="web",
        ),
        Citation(
            url="https://example.com/internal-cost-model",
            title="Internal Cloud Cost Model v3",
            author="Platform Engineering",
            date="2024-11",
            source_type="document",
        ),
    ]

    # --- 3. Build actions ---
    actions = [
        ActionRecord(
            action_id="act-001",
            action_type="api_call",
            description="Retrieved pricing data from AWS Cost Explorer",
            status="completed",
            agent_id="researcher",
        ),
        ActionRecord(
            action_id="act-002",
            action_type="api_call",
            description="Retrieved pricing data from Azure Cost Management",
            status="completed",
            agent_id="researcher",
        ),
        ActionRecord(
            action_id="act-003",
            action_type="api_call",
            description="Retrieved pricing data from GCP Billing API",
            status="completed",
            agent_id="researcher",
        ),
    ]

    # --- 4. Build cost summary ---
    cost_report = WorkflowCostReport(
        total_prompt_tokens=15200,
        total_completion_tokens=8400,
        total_tokens=23600,
        total_estimated_cost_usd=0.0472,
        agent_summaries={
            "researcher": AgentCostSummary(
                agent_id="researcher",
                total_prompt_tokens=10800,
                total_completion_tokens=6200,
                total_tokens=17000,
                total_estimated_cost_usd=0.034,
                call_count=3,
            ),
            "analyst": AgentCostSummary(
                agent_id="analyst",
                total_prompt_tokens=4400,
                total_completion_tokens=2200,
                total_tokens=6600,
                total_estimated_cost_usd=0.0132,
                call_count=1,
            ),
        },
        duration_seconds=12.3,
    )

    # --- 5. Assemble full payload ---
    payload = ResultPayload(
        title="Cloud Provider Comparison: AWS vs Azure vs GCP",
        content=(
            "This report compares AWS, Azure, and GCP across service "
            "breadth, enterprise integration, ML/AI capabilities, and "
            "cost for our production workload profile."
        ),
        sections=sections,
        metadata={
            "date": "2024-12-01",
            "workflow_id": "cloud-comparison-001",
            "status": "completed",
        },
        references=references,
        actions=actions,
        cost_summary=cost_report,
    )

    print(f"Payload: {payload.title}")
    print(f"  Sections: {len(payload.sections)}")
    print(f"  References: {len(payload.references)}")
    print(f"  Actions: {len(payload.actions)}")
    print(f"  Total tokens: {payload.cost_summary.total_tokens:,}")
    print(f"  Estimated cost: ${payload.cost_summary.total_estimated_cost_usd:.4f}")

    # --- 6. Publish ---
    registry = PublisherRegistry(drop_in_dir=None)
    registry.register(MarkdownPublisher())
    registry.register(JSONPublisher())

    paths = await registry.publish_all(
        payload,
        output_dir="./output/sdk",
        formats=["markdown", "json"],
        filename="analysis",
    )

    print(f"\nPublished {len(paths)} files:")
    for path in paths:
        size = path.stat().st_size
        print(f"  -> {path} ({size:,} bytes)")

    # Show JSON preview
    json_path = Path("./output/sdk/analysis.json")
    if json_path.exists():
        import json
        data = json.loads(json_path.read_text(encoding="utf-8"))
        print(f"\nJSON payload keys: {list(data.keys())}")
        print(f"  sections: {len(data.get('sections', []))}")
        print(f"  references: {len(data.get('references', []))}")
        print(f"  actions: {len(data.get('actions', []))}")


if __name__ == "__main__":
    asyncio.run(main())
