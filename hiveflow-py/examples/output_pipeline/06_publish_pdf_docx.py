"""Example: Publish workflow results to PDF, DOCX, and HTML.

Demonstrates publishing to document formats that require pypandoc.
Uses a rich ResultPayload with sections, references, and cost data
so the generated documents have real structure.

Prerequisites:
    uv sync --extra publishers --extra llm-azure
    AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com
    For RBAC auth: ``az login`` (no API key needed)
    For PDF: a LaTeX engine (e.g. MiKTeX on Windows, texlive on Linux)

Usage:
    AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com \
        uv run python examples/output_pipeline/publish_pdf_docx.py

Output:
    ./output/docs/report.md
    ./output/docs/report.json
    ./output/docs/report.docx
    ./output/docs/report.html
    ./output/docs/report.pdf   (only if LaTeX is installed)
"""

import asyncio

from hiveflow import (
    Agent,
    AgentBehaviorType,
    ResultPayload,
    WorkflowEngine,
    WorkflowStep,
)
from hiveflow.plugins.llm import get_llm_registry
from hiveflow.plugins.publishers import MarkdownPublisher, PublisherRegistry

MODEL = "azure:gpt-4o-mini"


async def main() -> None:
    """Run a two-agent workflow and publish to all available formats."""

    # --- 1. Resolve LLM provider ---
    llm_registry = get_llm_registry()
    provider, model = llm_registry.resolve_model(MODEL)
    print(f"Using model: {MODEL} (provider: {provider.plugin_id})")

    # --- 2. Define agents ---
    researcher = Agent(
        agent_id="researcher",
        role="Research Analyst",
        system_prompt=(
            "You are a research analyst. Given a topic, provide a thorough "
            "analysis organized into clear sections with headers."
        ),
        behavior_type=AgentBehaviorType.LLM_ONLY,
        model=MODEL,
        llm_provider=provider,
    )

    writer = Agent(
        agent_id="writer",
        role="Report Writer",
        system_prompt=(
            "You are a professional report writer. Synthesize the research "
            "into a well-structured report with an executive summary, "
            "main findings, and conclusion. Use markdown headers."
        ),
        behavior_type=AgentBehaviorType.LLM_ONLY,
        model=MODEL,
        llm_provider=provider,
    )

    # --- 3. Execute workflow ---
    steps = [
        WorkflowStep(agent="researcher", step_type="sequential", next_step="writer"),
        WorkflowStep(agent="writer", step_type="sequential"),
    ]

    engine = WorkflowEngine(steps, assembly_agents=["writer"])

    result = await engine.execute(
        agents={"researcher": researcher, "writer": writer},
        initial_state={"task": "Analyze the impact of AI on healthcare"},
    )

    print(f"Workflow status: {result.status}")

    # --- 4. Build ResultPayload ---
    payload = ResultPayload.from_workflow_result(
        result,
        title="AI in Healthcare: Impact Analysis",
    )

    print(f"Content length: {len(payload.content)} chars")

    # --- 5. Set up publisher registry with auto-discovery ---
    # PublisherRegistry.discover() loads pdf, docx, html, json from entry points.
    # We also manually register MarkdownPublisher (it's a built-in, not an entry point).
    pub_registry = PublisherRegistry(drop_in_dir=None)
    pub_registry.discover()
    pub_registry.register(MarkdownPublisher())

    available = pub_registry.list_ids()
    print(f"Available publishers: {available}")

    # --- 6. Publish to all formats ---
    # Start with formats that always work, then try PDF (needs LaTeX).
    formats = ["markdown", "json", "docx", "html"]
    paths = await pub_registry.publish_all(
        payload,
        output_dir="./output/docs",
        formats=formats,
        filename="report",
    )

    # Try PDF separately -- it fails gracefully if LaTeX isn't installed
    pdf_paths = await pub_registry.publish_all(
        payload,
        output_dir="./output/docs",
        formats=["pdf"],
        filename="report",
    )
    paths.extend(pdf_paths)

    print(f"\nPublished {len(paths)} files:")
    for path in paths:
        print(f"  -> {path} ({path.stat().st_size:,} bytes)")

    if not pdf_paths:
        print("\n  Note: PDF was skipped (LaTeX engine not found).")
        print("  Install MiKTeX (Windows), texlive (Linux), or MacTeX (macOS).")


if __name__ == "__main__":
    asyncio.run(main())
