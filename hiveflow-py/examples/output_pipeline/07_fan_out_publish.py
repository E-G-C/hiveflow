"""Example: Fan-out workflow with multi-format publishing.

Demonstrates the divide-and-conquer pattern: an orchestrator decomposes a
topic into parallel sub-tasks, a writer agent fans out to handle each one
concurrently, and the assembled output is published to multiple formats.

Prerequisites:
    uv sync --extra publishers --extra llm-azure
    AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com
    For RBAC auth: ``az login`` (no API key needed)

Usage:
    AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com \
        uv run python examples/output_pipeline/fan_out_publish.py

Output:
    ./output/fanout/report.md
    ./output/fanout/report.json
    ./output/fanout/report.docx
"""

import asyncio

from hiveflow import (
    Agent,
    AgentBehaviorType,
    ResultPayload,
    SummaryGenerator,
    WorkflowEngine,
    WorkflowStep,
)
from hiveflow.plugins.llm import LLMConfig, get_llm_registry
from hiveflow.plugins.publishers import MarkdownPublisher, PublisherRegistry

MODEL = "azure:gpt-4o-mini"


async def main() -> None:
    """Run an orchestrator -> fan-out writer workflow, then publish."""

    # --- 1. Resolve LLM provider ---
    llm_registry = get_llm_registry()
    provider, model = llm_registry.resolve_model(MODEL)
    print(f"Using model: {MODEL}")

    # --- 2. Define agents ---

    # The planner decomposes the topic into parallel_items
    planner = Agent(
        agent_id="planner",
        role="Report Planner",
        system_prompt=(
            "You are a report planner. Given a topic, break it down into "
            "4 independent sections that can be researched separately. "
            "Return ONLY a JSON array of section descriptions, e.g.:\n"
            '[{"title": "Section 1", "description": "What to cover"}]\n'
            "No other text."
        ),
        behavior_type=AgentBehaviorType.ORCHESTRATOR,
        model=MODEL,
        llm_provider=provider,
        llm_config=LLMConfig(model=model, temperature=0.3, max_tokens=1024),
    )

    # The writer runs once per parallel_item (fan-out)
    writer = Agent(
        agent_id="writer",
        role="Section Writer",
        system_prompt=(
            "You are a section writer. You will receive a specific section "
            "assignment in 'current_item'. Write 2-3 paragraphs covering "
            "that section thoroughly. Use markdown formatting."
        ),
        behavior_type=AgentBehaviorType.LLM_ONLY,
        model=MODEL,
        llm_provider=provider,
        llm_config=LLMConfig(model=model, temperature=0.7, max_tokens=2048),
    )

    # --- 3. Build workflow ---
    # Planner runs first (sequential), then writer fans out in parallel.
    # assembly_agents stitches all writer outputs into final_output.
    summarizer = SummaryGenerator(
        llm_provider=provider, model=model, max_summary_tokens=200
    )

    steps = [
        WorkflowStep(agent="planner", step_type="sequential", next_step="writer"),
        WorkflowStep(agent="writer", step_type="parallel_fan_out"),
    ]

    engine = WorkflowEngine(
        steps,
        summarizer=summarizer,
        assembly_agents=["writer"],
    )

    # Observability
    def on_event(event_type: str, agent_id: str, _data: dict) -> None:  # type: ignore[type-arg]
        if event_type in ("step_start", "step_complete", "assembly_complete"):
            print(f"  [{event_type}] {agent_id}")

    engine.on_event(on_event)

    # --- 4. Execute ---
    print("Executing fan-out workflow...")
    result = await engine.execute(
        agents={"planner": planner, "writer": writer},
        initial_state={
            "task": "Write a comprehensive guide to sustainable urban planning"
        },
    )

    print(f"\nWorkflow status: {result.status}")

    # Show fan-out details
    parallel_items = result.state.get("parallel_items", [])
    writer_outputs = result.state.get("writer_outputs", [])
    final_output = result.state.get("final_output", "")

    print(f"Parallel items: {len(parallel_items)}")
    print(f"Writer outputs: {len(writer_outputs)}")
    print(f"Assembled output: {len(final_output)} chars")

    # --- 5. Build ResultPayload ---
    payload = ResultPayload.from_workflow_result(
        result,
        title="Sustainable Urban Planning Guide",
    )

    # --- 6. Publish to multiple formats ---
    pub_registry = PublisherRegistry(drop_in_dir=None)
    pub_registry.discover()  # Loads json, docx, html, pdf from entry points
    pub_registry.register(MarkdownPublisher())

    paths = await pub_registry.publish_all(
        payload,
        output_dir="./output/fanout",
        formats=["markdown", "json", "docx"],
        filename="report",
    )

    print(f"\nPublished {len(paths)} files:")
    for path in paths:
        print(f"  -> {path} ({path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    asyncio.run(main())
