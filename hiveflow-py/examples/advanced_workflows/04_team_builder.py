#!/usr/bin/env python3
"""Advanced Workflows 04: Team builder -- generate and publish team blueprints.

Given a task description, uses TeamGenerator to compose a team of agents and
a workflow, then publishes the blueprint as Markdown using the output pipeline.
No LLM calls are made -- the output is a deterministic team blueprint.

Demonstrates:
  - TeamGenerator for deterministic team composition
  - ResultPayload construction from structured data
  - PublisherRegistry for multi-format output
  - Combining generation with the output pipeline

Usage:
    uv run python examples/advanced_workflows/04_team_builder.py
    uv run python examples/advanced_workflows/04_team_builder.py \
        --task "Design a microservices architecture for e-commerce"

Expected output:
    See sample_output/advanced_workflows/04_team_builder.txt
"""

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from hiveflow import PayloadSection, ResultPayload, TeamGenerator
from hiveflow.plugins.publishers import MarkdownPublisher, PublisherRegistry


def display_team(config: dict) -> None:
    """Pretty-print the generated team configuration."""
    print(f"\n{'=' * 60}")
    print(f"  Team: {config['team_name']}")
    print(f"  Task: {config['description'][:70]}...")
    print(f"{'=' * 60}\n")

    print("Agents:")
    for agent in config["agents"]:
        behavior = agent["behavior_type"]
        tools = agent.get("tools", [])
        tools_str = f"  tools={tools}" if tools else ""
        print(f"  - {agent['id']:20s}  role={agent['role']:<25s}  [{behavior}]{tools_str}")

    print("\nWorkflow:")
    steps = config["workflow"]["steps"]
    for i, step in enumerate(steps):
        step_type = step["type"]
        nxt = step.get("next") or step.get("next_on_accept", "(end)")
        print(f"  {i + 1}. {step['agent']:20s} [{step_type}] -> {nxt}")

    flow = " -> ".join(
        s["agent"] + (" ||" if s["type"] == "parallel_fan_out" else "")
        for s in steps
    )
    print(f"\n  Flow: {flow}")


def build_payload(task: str, config: dict) -> ResultPayload:
    """Wrap the generated team config into a publishable ResultPayload."""
    sections = [
        PayloadSection(
            section_id="overview",
            title="Task Overview",
            content=config["description"],
            order=0,
        ),
        PayloadSection(
            section_id="agents",
            title="Agents",
            content="\n".join(
                f"- **{a['id']}** -- {a['role']}  \n"
                f"  Behavior: `{a['behavior_type']}`"
                + (f", Tools: {a['tools']}" if a.get("tools") else "")
                + f"  \n  *{a['system_prompt'][:120]}...*"
                for a in config["agents"]
            ),
            order=1,
        ),
        PayloadSection(
            section_id="workflow",
            title="Workflow",
            content="\n".join(
                f"{i + 1}. **{s['agent']}** -- `{s['type']}`"
                + (f" -> {s['next']}" if s.get("next") else "")
                for i, s in enumerate(config["workflow"]["steps"])
            ),
            order=2,
        ),
        PayloadSection(
            section_id="raw_config",
            title="Full JSON Configuration",
            content=f"```json\n{json.dumps(config, indent=2)}\n```",
            order=3,
        ),
    ]

    return ResultPayload(
        title=f"Team Blueprint: {task[:60]}",
        content=f"Auto-generated team configuration for: {task}",
        sections=sections,
        metadata={
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "team_name": config["team_name"],
            "agent_count": len(config["agents"]),
        },
    )


async def run(task: str, output_dir: str) -> None:
    """Generate a team, display it, and publish as Markdown."""
    print("=" * 60)
    print("  HiveFlow -- Team Builder")
    print("=" * 60)

    # Generate team config
    generator = TeamGenerator()
    config = generator.generate_team(task_description=task, include_review=True)
    display_team(config)

    # Build publishable payload
    payload = build_payload(task, config)

    # Publish via the publisher pipeline
    registry = PublisherRegistry(drop_in_dir=None)
    registry.register(MarkdownPublisher())

    formats = ["markdown"]
    try:
        from hiveflow.plugins.publishers.docx_publisher import DOCXPublisher
        registry.register(DOCXPublisher())
        formats.append("docx")
    except ImportError:
        print("\n  (DOCX skipped -- install with: uv sync --extra publishers)")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    paths = await registry.publish_all(
        payload,
        output_dir=output_dir,
        formats=formats,
        filename=f"team-blueprint-{ts}",
    )

    print(f"\nPublished {len(paths)} file(s):")
    for p in paths:
        print(f"  -> {p}  ({p.stat().st_size:,} bytes)")


def main() -> None:
    """Parse args and run."""
    parser = argparse.ArgumentParser(description="Generate and publish a team blueprint")
    parser.add_argument(
        "--task",
        default="Analyze the impact of AI on software development and write a comprehensive report",
        help="Task description",
    )
    parser.add_argument(
        "--output-dir",
        default="output/team-builder",
        help="Output directory for published files",
    )
    args = parser.parse_args()
    asyncio.run(run(task=args.task, output_dir=args.output_dir))


if __name__ == "__main__":
    main()
