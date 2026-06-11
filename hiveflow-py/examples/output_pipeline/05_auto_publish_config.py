"""Example: Auto-publish via team configuration YAML.

Demonstrates end-to-end workflow execution with auto-publishing configured
directly in the team config. When a ``publish`` block is present in the
template, the engine automatically publishes results after execution.

Prerequisites:
    AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com
    For RBAC auth: ``az login`` (no API key needed)

Usage:
    # Using this script:
    AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com \
        uv run python examples/output_pipeline/auto_publish_config.py

Output:
    ./output/auto/output.md
    ./output/auto/output.json
"""

import asyncio
from pathlib import Path

from hiveflow import (
    Agent,
    AgentBehaviorType,
    WorkflowEngine,
    WorkflowStep,
)
from hiveflow.plugins.llm import get_llm_registry

MODEL = "azure:gpt-4o-mini"


async def main() -> None:
    """Run a workflow with auto-publish configured from a dict (mimics YAML config)."""

    # This mirrors what the CLI does when it reads a team config with a
    # publish block.  The publish_config is typically loaded from YAML:
    #
    #   publish:
    #     formats: ["markdown", "json"]
    #     output_dir: "./output/auto"
    #     filename: "output"
    #     layout: "default"
    #
    # Here we pass it as a dict for clarity.

    publish_config = {
        "formats": ["markdown", "json"],
        "output_dir": "./output/auto",
        "filename": "output",
        "layout": "default",
    }

    # --- Resolve LLM provider ---
    registry = get_llm_registry()
    provider, model = registry.resolve_model(MODEL)

    # --- Define agents ---
    researcher = Agent(
        agent_id="researcher",
        role="Research Analyst",
        system_prompt="Research the given topic thoroughly.",
        behavior_type=AgentBehaviorType.LLM_ONLY,
        model=MODEL,
        llm_provider=provider,
    )

    writer = Agent(
        agent_id="writer",
        role="Report Writer",
        system_prompt="Write a clear, structured report from the research.",
        behavior_type=AgentBehaviorType.LLM_ONLY,
        model=MODEL,
        llm_provider=provider,
    )

    # --- Define workflow with auto-publish ---
    steps = [
        WorkflowStep(agent="researcher", step_type="sequential", next_step="writer"),
        WorkflowStep(agent="writer", step_type="sequential"),
    ]

    engine = WorkflowEngine(
        steps,
        assembly_agents=["writer"],
        publish_config=publish_config,  # <-- auto-publish after execution
    )

    # --- Execute (auto-publishes on success) ---
    result = await engine.execute(
        agents={"researcher": researcher, "writer": writer},
        initial_state={"task": "Analyze the benefits of remote work"},
    )

    print(f"Workflow status: {result.status}")

    # Check output files
    output_dir = Path("./output/auto")
    if output_dir.exists():
        for f in sorted(output_dir.iterdir()):
            print(f"  Auto-published: {f} ({f.stat().st_size:,} bytes)")
    else:
        print("  (No output files -- workflow may have failed)")


if __name__ == "__main__":
    asyncio.run(main())
