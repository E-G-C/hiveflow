#!/usr/bin/env python3
"""HiveFlow Console Example - End-to-end multi-agent workflow using llama.cpp.

Demonstrates:
  1. Configuring OpenAIProvider with a custom base_url (llama.cpp)
  2. Defining agents with system prompts and behavior types
  3. Building a sequential workflow graph with summary propagation
  4. Context budgets and code-level assembly
  5. Executing the workflow and printing results

Usage:
  uv run python examples/console_app/main.py
  uv run python examples/console_app/main.py --task "Explain quantum computing"
  uv run python examples/console_app/main.py --config examples/console_app/team_config.json
"""

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# Ensure hiveflow is importable when running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hiveflow import (
    Agent,
    AgentBehaviorType,
    SummaryGenerator,
    TeamConfiguration,
    WorkflowEngine,
    WorkflowStep,
)
from hiveflow.plugins.llm import LLMConfig
from hiveflow.plugins.llm.openai_provider import OpenAIProvider

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# LLAMACPP_BASE_URL = os.environ.get("OPENAI_BASE_URL", "http://localhost:8080/v1")

# LiteLLM
LLAMACPP_BASE_URL = os.environ.get("OPENAI_BASE_URL", "http://localhost:4000/v1") # 

MODEL_NAME = "claude-opus-4-6"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("console_app")


# ---------------------------------------------------------------------------
# Build agents directly (no config file needed)
# ---------------------------------------------------------------------------
def build_agents_direct(provider: OpenAIProvider) -> dict[str, Agent]:
    """Create agents programmatically."""
    researcher = Agent(
        agent_id="researcher",
        role="Research Analyst",
        system_prompt=(
            "You are a research analyst. Given a topic, provide a concise but "
            "comprehensive summary of the key facts, concepts, and recent "
            "developments. Focus on accuracy and cite specific details."
        ),
        behavior_type=AgentBehaviorType.LLM_ONLY,
        model=MODEL_NAME,
        llm_provider=provider,
        llm_config=LLMConfig(model=MODEL_NAME, temperature=0.3, max_tokens=8192),
    )

    writer = Agent(
        agent_id="writer",
        role="Report Writer",
        system_prompt=(
            "You are a professional writer. Using the research provided by "
            "the previous analyst, write a clear, well-structured short article "
            "(3-4 paragraphs). Make it engaging and accessible to a general audience."
        ),
        behavior_type=AgentBehaviorType.LLM_ONLY,
        model=MODEL_NAME,
        llm_provider=provider,
        llm_config=LLMConfig(model=MODEL_NAME, temperature=0.7, max_tokens=8192),
        # Limit context so the writer receives condensed research, not raw dump
        context_budget=4000,
    )

    reviewer = Agent(
        agent_id="reviewer",
        role="Quality Reviewer",
        system_prompt=(
            "You are a quality reviewer. Read the article produced by the writer "
            "and provide a brief review: note any factual issues, suggest "
            "improvements, and give it a rating from 1-5. Be constructive."
        ),
        behavior_type=AgentBehaviorType.LLM_ONLY,
        model=MODEL_NAME,
        llm_provider=provider,
        llm_config=LLMConfig(model=MODEL_NAME, temperature=0.4, max_tokens=8192),
    )

    return {
        "researcher": researcher,
        "writer": writer,
        "reviewer": reviewer,
    }


def build_workflow_direct(provider: OpenAIProvider) -> WorkflowEngine:
    """Create a sequential 3-step workflow with summary propagation."""
    steps = [
        WorkflowStep(agent="researcher", step_type="sequential", next_step="writer"),
        WorkflowStep(agent="writer", step_type="sequential", next_step="reviewer"),
        WorkflowStep(agent="reviewer", step_type="sequential"),
    ]
    # Summary propagation: after each step the engine generates a compact
    # summary so downstream agents see condensed context instead of full output.
    # Assembly: the writer's full output is stitched into final_output at the end.
    summarizer = SummaryGenerator(llm_provider=provider, model=MODEL_NAME, max_summary_tokens=8192)
    return WorkflowEngine(
        steps,
        summarizer=summarizer,
        assembly_agents=["writer"],
    )


# ---------------------------------------------------------------------------
# Build agents from a JSON team configuration file
# ---------------------------------------------------------------------------
def build_from_config(config_path: str, provider: OpenAIProvider) -> tuple[dict[str, Agent], WorkflowEngine]:
    """Load team configuration from JSON and build agents + workflow."""
    team_config = TeamConfiguration.from_json_file(config_path)
    logger.info("Loaded team config: %s", team_config.team_name)

    agents: dict[str, Agent] = {}
    for agent_def in team_config.agents:
        agents[agent_def.id] = Agent.from_definition(
            agent_def,
            llm_provider=provider,
            resolved_model=MODEL_NAME,
        )

    summarizer = SummaryGenerator(llm_provider=provider, model=MODEL_NAME, max_summary_tokens=8192)
    engine = WorkflowEngine.from_schema(
        team_config.workflow,
        summarizer=summarizer,
        assembly_agents=["writer"],
    )
    return agents, engine


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------
def _slugify(text: str) -> str:
    """Turn a task string into a safe filename slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:80] if len(slug) > 80 else slug


def write_report(task: str, result: Any, output_dir: Path) -> Path:
    """Write the assembled report to a markdown file and return the path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = _slugify(task)
    filepath = output_dir / f"{timestamp}-{slug}.md"

    final_output = result.state.get("final_output", "")
    lines = [
        f"# {task}",
        "",
        f"*Generated by HiveFlow console workflow on "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M')}*",
        "",
        f"**Model:** {MODEL_NAME}  ",
        f"**Steps executed:** {len(result.step_results)}  ",
        f"**Status:** {result.status.value}",
        "",
        "---",
        "",
    ]

    # Each agent's output as a section
    for step in result.step_results:
        output = result.state.get(f"{step.agent_id}_output", "")
        lines.append(f"## {step.agent_id.title()} Output")
        lines.append("")
        lines.append(output)
        lines.append("")
        lines.append("---")
        lines.append("")

    # Assembled final output
    if final_output:
        lines.append("## Final Assembled Output")
        lines.append("")
        lines.append(final_output)
        lines.append("")
        lines.append(f"*({len(final_output.split())} words)*")
        lines.append("")

    filepath.write_text("\n".join(lines), encoding="utf-8")
    return filepath


def write_log(
    task: str,
    result: Any,
    event_log: list[dict[str, Any]],
    elapsed_total: float,
    output_dir: Path,
) -> Path:
    """Write a detailed execution log alongside the report."""
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = _slugify(task)
    filepath = output_dir / f"{timestamp}-{slug}-log.md"

    lines = [
        f"# Execution Log: {task}",
        "",
        f"*{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
        "",
        "## Configuration",
        "",
        f"| Parameter | Value |",
        f"|-----------|-------|",
        f"| Model | {MODEL_NAME} |",
        f"| Base URL | {LLAMACPP_BASE_URL} |",
        f"| Status | {result.status.value} |",
        f"| Total elapsed | {elapsed_total:.1f}s |",
        "",
        "---",
        "",
        "## Event Timeline",
        "",
    ]

    for evt in event_log:
        ts = evt.get("timestamp", "")
        etype = evt.get("type", "")
        agent = evt.get("agent_id", "")
        detail = evt.get("detail", "")
        lines.append(f"- **{ts}** `{etype}` {agent} {detail}")
    lines.append("")

    # Token usage table
    lines.append("## Token Usage")
    lines.append("")
    lines.append("| Agent | Prompt | Completion | Total |")
    lines.append("|-------|--------|------------|-------|")
    total_tokens = 0
    for step in result.step_results:
        usage = result.state.get(f"{step.agent_id}_usage")
        if usage:
            lines.append(
                f"| {step.agent_id} | {usage['prompt_tokens']} "
                f"| {usage['completion_tokens']} | {usage['total_tokens']} |"
            )
            total_tokens += usage["total_tokens"]
    lines.append(f"| **Total** | | | **{total_tokens}** |")
    lines.append("")

    # Step timing
    lines.append("## Step Timing")
    lines.append("")
    lines.append("| Agent | Duration |")
    lines.append("|-------|----------|")
    for evt in event_log:
        if evt.get("type") == "step_complete" and "elapsed" in evt:
            lines.append(f"| {evt['agent_id']} | {evt['elapsed']:.1f}s |")
    lines.append("")

    # Errors / warnings
    errors = [e for e in event_log if e.get("type") in ("step_error", "warning")]
    if errors:
        lines.append("## Errors & Warnings")
        lines.append("")
        for err in errors:
            lines.append(f"- **{err.get('type')}** [{err.get('agent_id', '')}]: {err.get('detail', '')}")
        lines.append("")

    if result.error:
        lines.append(f"## Workflow Error")
        lines.append("")
        lines.append(f"```\n{result.error}\n```")
        lines.append("")

    filepath.write_text("\n".join(lines), encoding="utf-8")
    return filepath


# ---------------------------------------------------------------------------
# Event handler for workflow observability
# ---------------------------------------------------------------------------
_event_log: list[dict[str, Any]] = []
_step_times: dict[str, float] = {}


def on_workflow_event(event_type: str, agent_id: str, data: dict[str, Any]) -> None:
    """Print workflow events to console and record to event log."""
    ts = datetime.now().strftime("%H:%M:%S")
    entry: dict[str, Any] = {"timestamp": ts, "type": event_type, "agent_id": agent_id}

    if event_type == "step_start":
        _step_times[agent_id] = time.time()
        entry["detail"] = f"step_type={data.get('step_type', '')}"
        print(f"\n{'='*60}")
        print(f"  Starting: {agent_id} ({data.get('step_type', '')})")
        print(f"{'='*60}")
    elif event_type == "step_complete":
        elapsed = time.time() - _step_times.get(agent_id, time.time())
        entry["elapsed"] = elapsed
        entry["detail"] = f"{elapsed:.1f}s"
        print(f"  Completed: {agent_id} ({elapsed:.1f}s)")
    elif event_type == "step_error":
        entry["detail"] = data.get("error", "unknown")
        print(f"  ERROR in {agent_id}: {data.get('error', 'unknown')}")
    elif event_type == "summary_generated":
        entry["detail"] = f"{data.get('summary_length', '?')} words"
        print(f"  Summary generated for {agent_id} ({data.get('summary_length', '?')} words)")
    elif event_type == "outline_generated":
        entry["detail"] = f"{data.get('num_items', '?')} items"
        print(f"  Outline generated for {agent_id} ({data.get('num_items', '?')} items)")
    elif event_type == "assembly_complete":
        entry["detail"] = (f"{data.get('num_sections', '?')} sections, "
                           f"{data.get('total_words', '?')} words")
        print(f"  Assembly complete: {data.get('num_sections', '?')} sections, "
              f"{data.get('total_words', '?')} words")

    _event_log.append(entry)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def run(
    task: str,
    config_path: str | None = None,
    output_dir: Path = Path("output"),
) -> None:
    """Execute the workflow end to end."""
    # Reset event log for this run
    _event_log.clear()
    _step_times.clear()

    # Create provider pointing to llama.cpp
    provider = OpenAIProvider(
        base_url=LLAMACPP_BASE_URL,
        api_key="not-needed",
    )

    # Build agents and workflow
    if config_path:
        agents, engine = build_from_config(config_path, provider)
    else:
        agents = build_agents_direct(provider)
        engine = build_workflow_direct(provider)

    engine.on_event(on_workflow_event)

    initial_state = {"task": task}
    print(f"\nTask: {task}\n")

    # Execute
    start_time = time.time()
    result = await engine.execute(agents=agents, initial_state=initial_state)
    elapsed_total = time.time() - start_time

    # Print results
    print(f"\n{'='*60}")
    print(f"  Workflow finished - status: {result.status.value}")
    print(f"  Steps executed: {len(result.step_results)}")
    print(f"  Total time: {elapsed_total:.1f}s")
    print(f"{'='*60}")

    if result.error:
        print(f"\nError: {result.error}")

    # Print each agent's output
    for step in result.step_results:
        output = result.state.get(f"{step.agent_id}_output", "")
        print(f"\n--- {step.agent_id} output ---")
        print(output)

    # Print assembled final output (from code-level assembly)
    if "final_output" in result.state:
        print(f"\n{'='*60}")
        print("  Assembled final output")
        print(f"{'='*60}")
        final = result.state["final_output"]
        print(final)
        print(f"\n  ({len(final.split())} words)")

    # Print token usage summary
    print(f"\n{'='*60}")
    print("  Token usage summary")
    print(f"{'='*60}")
    total_tokens = 0
    for step in result.step_results:
        usage = result.state.get(f"{step.agent_id}_usage")
        if usage:
            print(f"  {step.agent_id}: {usage['total_tokens']} tokens "
                  f"(prompt={usage['prompt_tokens']}, completion={usage['completion_tokens']})")
            total_tokens += usage["total_tokens"]
    print(f"  Total: {total_tokens} tokens")

    # Write output files
    report_path = write_report(task, result, output_dir)
    log_path = write_log(task, result, _event_log, elapsed_total, output_dir)
    print(f"\n  Report: {report_path}")
    print(f"  Log:    {log_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="HiveFlow Console Example")
    parser.add_argument(
        "--task",
        default="Explain the benefits of renewable energy in 2025",
        help="Topic for the research workflow",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to a team_config.json file (optional, uses built-in config if omitted)",
    )
    parser.add_argument(
        "--output-dir",
        default="output",
        help="Directory for report and log output (default: output/)",
    )
    args = parser.parse_args()
    asyncio.run(run(task=args.task, config_path=args.config, output_dir=Path(args.output_dir)))


if __name__ == "__main__":
    main()
