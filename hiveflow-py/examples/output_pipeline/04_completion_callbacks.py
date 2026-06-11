"""Example: Completion callbacks for post-workflow actions.

Demonstrates how to register sync and async callbacks on the WorkflowEngine
that fire automatically when a workflow completes successfully. Callbacks
receive the ResultPayload and can trigger notifications, write logs, update
databases, or chain into other systems.

Prerequisites:
    AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com
    For RBAC auth: ``az login`` (no API key needed)

Usage:
    AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com \
        uv run python examples/output_pipeline/completion_callbacks.py

Output:
    ./output/callbacks/report.md
    Callback log messages to stdout
"""

import asyncio
import json
from pathlib import Path

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

# --- Callback examples ---


def log_completion(payload: ResultPayload) -> None:
    """Sync callback: log basic completion info.

    This is the simplest callback type -- a plain function that receives
    the ResultPayload. Use this for quick, non-blocking post-processing.
    """
    print("\n[Callback: log_completion]")
    print(f"  Title: {payload.title}")
    print(f"  Sections: {len(payload.sections)}")
    print(f"  Content length: {len(payload.content)} chars")
    print(f"  References: {len(payload.references)}")


async def save_summary(payload: ResultPayload) -> None:
    """Async callback: save a summary JSON file.

    Async callbacks are awaited in registration order. Use these when the
    callback needs to perform I/O (file writes, HTTP requests, etc.).
    """
    summary = {
        "title": payload.title,
        "section_count": len(payload.sections),
        "content_length": len(payload.content),
        "metadata": payload.metadata,
    }

    output_path = Path("./output/callbacks/summary.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(summary, indent=2, default=str),
        encoding="utf-8",
    )

    print("\n[Callback: save_summary]")
    print(f"  Saved summary to {output_path}")


async def publish_to_formats(payload: ResultPayload) -> None:
    """Async callback: publish the result to additional formats.

    Callbacks can use the publisher registry to create output files,
    chain into other pipelines, or trigger downstream workflows.
    """
    registry = PublisherRegistry(drop_in_dir=None)
    registry.register(MarkdownPublisher())

    paths = await registry.publish_all(
        payload,
        output_dir="./output/callbacks",
        formats=["markdown"],
        filename="report",
    )

    print("\n[Callback: publish_to_formats]")
    for p in paths:
        print(f"  Published: {p}")


def count_words(payload: ResultPayload) -> None:
    """Sync callback: word count analytics."""
    words = len(payload.content.split())
    section_words = sum(len(s.content.split()) for s in payload.sections)

    print("\n[Callback: count_words]")
    print(f"  Main content: {words} words")
    print(f"  Across sections: {section_words} words")


async def main() -> None:
    """Run a workflow with multiple completion callbacks."""

    # --- Resolve LLM provider ---
    llm_registry = get_llm_registry()
    provider, model = llm_registry.resolve_model(MODEL)

    # --- Define agents ---
    researcher = Agent(
        agent_id="researcher",
        role="Research Analyst",
        system_prompt="Research the given topic and provide key findings.",
        behavior_type=AgentBehaviorType.LLM_ONLY,
        model=MODEL,
        llm_provider=provider,
    )

    writer = Agent(
        agent_id="writer",
        role="Report Writer",
        system_prompt="Write a structured report from the research.",
        behavior_type=AgentBehaviorType.LLM_ONLY,
        model=MODEL,
        llm_provider=provider,
    )

    # --- Set up engine ---
    steps = [
        WorkflowStep(agent="researcher", step_type="sequential", next_step="writer"),
        WorkflowStep(agent="writer", step_type="sequential"),
    ]

    engine = WorkflowEngine(steps, assembly_agents=["writer"])

    # --- Register callbacks (invoked in order) ---
    engine.on_complete(log_completion)          # Sync
    engine.on_complete(save_summary)            # Async
    engine.on_complete(publish_to_formats)      # Async
    engine.on_complete(count_words)             # Sync

    print("Registered 4 callbacks (2 sync, 2 async)")
    print("Callbacks execute in registration order after workflow completes.\n")

    # --- Execute ---
    result = await engine.execute(
        agents={"researcher": researcher, "writer": writer},
        initial_state={"task": "Summarize recent advances in battery technology"},
    )

    print("\n--- Workflow finished ---")
    print(f"Status: {result.status}")
    print(f"Result payload: {'present' if result.result_payload else 'none'}")

    # Verify callback outputs
    summary_path = Path("./output/callbacks/summary.json")
    if summary_path.exists():
        print(f"\nSummary file created by callback: {summary_path}")
        data = json.loads(summary_path.read_text(encoding="utf-8"))
        print(f"  {json.dumps(data, indent=2)}")


if __name__ == "__main__":
    asyncio.run(main())
