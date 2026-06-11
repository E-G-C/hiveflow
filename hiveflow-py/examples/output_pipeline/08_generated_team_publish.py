"""Example: Auto team generation + fan-out + multi-format publishing.

Demonstrates the full HiveFlow pipeline: TeamGenerator dynamically creates
a planner/writer/reviewer team from a task description, the workflow fans
out for parallel section writing, and results are published to Markdown,
DOCX, and HTML.

This is the highest-level API -- no manual agent or workflow definition needed.

Prerequisites:
    uv sync --extra publishers --extra llm-azure
    AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com
    For RBAC auth: ``az login`` (no API key needed)

Usage:
    AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com \
        uv run python examples/output_pipeline/generated_team_publish.py

Output:
    ./output/generated/report.md
    ./output/generated/report.json
    ./output/generated/report.docx
    ./output/generated/report.html
"""

import asyncio

from hiveflow import ResultPayload, TeamGenerator
from hiveflow.plugins.llm import get_llm_registry
from hiveflow.plugins.publishers import MarkdownPublisher, PublisherRegistry

MODEL = "azure:gpt-4o-mini"
TASK = "Write a comparative analysis of electric vs hydrogen fuel cell vehicles"


async def main() -> None:
    """Generate a team, execute the workflow, and publish to multiple formats."""

    # --- 1. Resolve LLM provider ---
    llm_registry = get_llm_registry()
    provider, model = llm_registry.resolve_model(MODEL)
    print(f"Using model: {MODEL}")

    # --- 2. Generate team configuration ---
    # TeamGenerator creates a team config dict from a task description.
    # agent_types controls which archetypes to include:
    #   "planner"  -> orchestrator that decomposes into parallel_items
    #   "writer"   -> fan-out writer, runs once per parallel_item
    #   "reviewer" -> optional quality gate (conditional step)
    generator = TeamGenerator()
    config = generator.generate_team(
        task_description=TASK,
        agent_types=["planner", "writer"],
        include_review=True,  # Adds a reviewer with conditional loop
    )

    print(f"Team: {config['team_name']}")
    print(f"Agents: {[a['id'] for a in config['agents']]}")
    print(f"Workflow steps: {len(config['workflow']['steps'])}")
    for step in config["workflow"]["steps"]:
        print(f"  - {step['agent']} ({step['type']})")

    # --- 3. Build live agents and engine ---
    # TeamGenerator.build() wires llm_provider into all agents automatically,
    # detects parallel_fan_out steps, enables summarizer, and sets up assembly.
    agents, engine = generator.build(
        config,
        provider,
        model=model,
        max_tokens=4096,
        enable_summaries=True,
        max_summary_tokens=200,
    )

    # Observability
    def on_event(event_type: str, agent_id: str, _data: dict) -> None:  # type: ignore[type-arg]
        print(f"  [{event_type}] {agent_id}")

    engine.on_event(on_event)

    # --- 4. Execute workflow ---
    print(f"\nExecuting workflow for: {TASK}")
    result = await engine.execute(
        agents=agents,
        initial_state={"task": TASK},
    )

    print(f"\nWorkflow status: {result.status}")
    print(f"Steps executed: {len(result.step_results)}")

    # Show what the engine produced
    final_output = result.state.get("final_output", "")
    parallel_items = result.state.get("parallel_items", [])
    print(f"Parallel items: {len(parallel_items)}")
    print(f"Assembled output: {len(final_output)} chars")

    # --- 5. Build ResultPayload ---
    payload = ResultPayload.from_workflow_result(
        result,
        title="Electric vs Hydrogen Vehicles: Comparative Analysis",
    )

    print(f"\nPayload: {payload.title}")
    print(f"  Content: {len(payload.content)} chars")
    print(f"  Sections: {len(payload.sections)}")

    # --- 6. Publish to multiple formats ---
    pub_registry = PublisherRegistry(drop_in_dir=None)
    pub_registry.discover()  # Loads json, docx, html, pdf from entry points
    pub_registry.register(MarkdownPublisher())

    formats = ["markdown", "json", "docx", "html"]
    paths = await pub_registry.publish_all(
        payload,
        output_dir="./output/generated",
        formats=formats,
        filename="report",
    )

    print(f"\nPublished {len(paths)} files:")
    for path in paths:
        print(f"  -> {path} ({path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    asyncio.run(main())
