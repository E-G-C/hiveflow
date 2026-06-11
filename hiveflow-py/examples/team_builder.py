#!/usr/bin/env python3
"""Team Builder -- generate a team configuration and publish it via the output pipeline.

Given a task description, this example uses ``TeamGenerator`` to compose an
appropriate team of agents and a workflow, then publishes the resulting
blueprint as **Markdown** and **Word (.docx)** files using HiveFlow's
publisher pipeline.  No LLM calls are made -- the output is a deterministic
team blueprint.

This is useful when you want to:
  - Preview which agents and workflow HiveFlow would create for a task.
  - Publish the generated config as formatted documents (Markdown + Word).
  - Save the raw JSON config for later editing or execution.
  - Integrate team generation into a larger pipeline where execution happens
    separately.

Prerequisites (for DOCX output):
  uv sync --extra publishers

Usage:
  uv run python examples/team_builder.py
  uv run python examples/team_builder.py --task "Design a microservices architecture for an e-commerce platform"
  uv run python examples/team_builder.py --task "Write a legal brief" --agents planner writer reviewer
  uv run python examples/team_builder.py --task "Research quantum computing" --no-review
  uv run python examples/team_builder.py --task "Audit our API security" --json
"""

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Ensure hiveflow is importable when running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hiveflow import PayloadSection, ResultPayload, TeamGenerator
from hiveflow.plugins.publishers import MarkdownPublisher, PublisherRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:60]


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def display_team(config: dict[str, Any]) -> None:
    """Pretty-print the generated team configuration."""
    print(f"\n{'=' * 60}")
    print(f"  Team: {config['team_name']}")
    print(f"  Task: {config['description']}")
    print(f"{'=' * 60}\n")

    # Agents summary
    print("Agents:")
    for agent in config["agents"]:
        behavior = agent["behavior_type"]
        tools = agent.get("tools", [])
        tools_str = f"  tools={tools}" if tools else ""
        print(f"  - {agent['id']:20s}  role={agent['role']:<25s}  behavior={behavior}{tools_str}")

    # Workflow
    print("\nWorkflow:")
    steps = config["workflow"]["steps"]
    for i, step in enumerate(steps):
        arrow = "  ->  " if i < len(steps) - 1 else ""
        step_type = step["type"]
        next_info = ""
        if step_type == "conditional":
            next_info = f"  (accept->{step.get('next_on_accept')}, reject->{step.get('next_on_reject')})"
        elif step.get("next"):
            next_info = f"  (next->{step['next']})"
        print(f"  {i + 1}. {step['agent']} [{step_type}]{next_info}{arrow}")

    # Visual flow
    flow = " -> ".join(
        s["agent"] + (" ||" if s["type"] == "parallel_fan_out" else "")
        for s in steps
    )
    print(f"\n  Flow: {flow}")
    print()


# ---------------------------------------------------------------------------
# Build a ResultPayload from the generated config (no workflow execution)
# ---------------------------------------------------------------------------
def build_payload(task: str, config: dict[str, Any]) -> ResultPayload:
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
                + (f" (accept->{s.get('next_on_accept')}, reject->{s.get('next_on_reject')})"
                   if s["type"] == "conditional" else "")
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
        title=f"Team Blueprint: {task}",
        content=f"Auto-generated team configuration for: {task}",
        sections=sections,
        metadata={
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "team_name": config["team_name"],
            "agent_count": len(config["agents"]),
        },
    )


# ---------------------------------------------------------------------------
# Publish via the output pipeline
# ---------------------------------------------------------------------------
async def publish(payload: ResultPayload, output_dir: Path, slug: str) -> list[Path]:
    """Publish the payload as Markdown and DOCX using the framework pipeline."""
    registry = PublisherRegistry(drop_in_dir=None)
    registry.register(MarkdownPublisher())

    # DOCX requires the publishers extra (pypandoc); register if available
    formats = ["markdown"]
    try:
        from hiveflow.plugins.publishers.docx_publisher import DOCXPublisher
        registry.register(DOCXPublisher())
        formats.append("docx")
    except ImportError:
        print("  (DOCX skipped -- install with: uv sync --extra publishers)")

    ts = _timestamp()
    filename = f"{ts}-{slug}"

    paths = await registry.publish_all(
        payload,
        output_dir=str(output_dir),
        formats=formats,
        filename=filename,
    )
    return paths


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def run(args: argparse.Namespace) -> None:
    generator = TeamGenerator()
    config = generator.generate_team(
        task_description=args.task,
        agent_types=args.agents,
        include_review=not args.no_review,
    )

    # Print to console
    if args.json:
        print(json.dumps(config, indent=2))
    else:
        display_team(config)

    # Build payload and publish
    slug = _slugify(args.task)
    output_dir = Path(args.output_dir)
    payload = build_payload(args.task, config)

    paths = await publish(payload, output_dir, slug)

    print(f"Published {len(paths)} file(s):")
    for p in paths:
        print(f"  -> {p}  ({p.stat().st_size:,} bytes)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a HiveFlow team configuration and publish as Markdown + Word",
    )
    parser.add_argument(
        "--task",
        default="Analyze the impact of AI on software development and write a comprehensive report",
        help="Task description to generate a team for",
    )
    parser.add_argument(
        "--agents",
        nargs="+",
        default=None,
        metavar="TYPE",
        help=(
            "Agent archetypes to include (default: researcher, writer). "
            "Available: researcher, planner, writer, reviewer, editor"
        ),
    )
    parser.add_argument(
        "--no-review",
        action="store_true",
        help="Skip the reviewer agent",
    )
    parser.add_argument(
        "--output-dir",
        default="output/team-builder",
        help="Directory for published files (default: output/team-builder)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print raw JSON to console instead of the formatted summary",
    )
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
