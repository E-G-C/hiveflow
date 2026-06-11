"""Example: Publish workflow results to Markdown and JSON.

Demonstrates the simplest output pipeline usage -- run a two-agent workflow
and publish the results to Markdown and JSON with zero extra dependencies.

Prerequisites:
    AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com
    For RBAC auth: ``az login`` (no API key needed)

Usage:
    AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com \
        uv run python examples/output_pipeline/basic_publish.py

Output:
    ./output/basic/report.md
    ./output/basic/report.json
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
from hiveflow.plugins.publishers.json_publisher import JSONPublisher

MODEL = "azure:gpt-4o-mini"


async def main() -> None:
    """Run a researcher -> writer workflow and publish to Markdown + JSON."""

    # --- 1. Resolve LLM provider ---
    registry = get_llm_registry()
    provider, model = registry.resolve_model(MODEL)
    print(f"Using model: {MODEL} (provider: {provider.plugin_id})")

    # --- 2. Define agents ---
    researcher = Agent(
        agent_id="researcher",
        role="Research Analyst",
        system_prompt=(
            "You are a research analyst. Given a topic, provide a thorough "
            "summary of key findings with supporting evidence."
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
            "into a clear, well-structured report with an executive summary."
        ),
        behavior_type=AgentBehaviorType.LLM_ONLY,
        model=MODEL,
        llm_provider=provider,
    )

    # --- 3. Define workflow ---
    steps = [
        WorkflowStep(agent="researcher", step_type="sequential", next_step="writer"),
        WorkflowStep(agent="writer", step_type="sequential"),
    ]

    engine = WorkflowEngine(
        steps,
        assembly_agents=["writer"],  # Assemble writer output into final_output
    )

    # --- 4. Execute workflow ---
    result = await engine.execute(
        agents={"researcher": researcher, "writer": writer},
        initial_state={"task": "Explain the current state of quantum computing"},
    )

    print(f"Workflow status: {result.status}")

    # --- 5. Assemble ResultPayload ---
    payload = ResultPayload.from_workflow_result(
        result,
        title="Quantum Computing Report",
    )

    print(f"Payload title: {payload.title}")
    print(f"Content length: {len(payload.content)} chars")
    print(f"Sections: {len(payload.sections)}")

    # --- 6. Set up publisher registry ---
    pub_registry = PublisherRegistry(drop_in_dir=None)
    pub_registry.register(MarkdownPublisher())
    pub_registry.register(JSONPublisher())

    # --- 7. Publish to Markdown + JSON ---
    paths = await pub_registry.publish_all(
        payload,
        output_dir="./output/basic",
        formats=["markdown", "json"],
        filename="report",
    )

    print(f"\nPublished {len(paths)} files:")
    for path in paths:
        print(f"  -> {path}")


if __name__ == "__main__":
    asyncio.run(main())
