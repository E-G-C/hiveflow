#!/usr/bin/env python3
"""Fan-out report generation using the divide-and-conquer pattern.

Demonstrates HiveFlow's orchestrator -> parallel fan-out -> assembly pipeline
for producing long-form reports.  The workflow has two steps:

  1. **Planner** (orchestrator) -- decomposes the topic into 4-6 independent
     section descriptions and stores them as ``parallel_items``.
  2. **Writer** (parallel fan-out) -- runs once per section in parallel,
     each instance receiving its section description via ``current_item``
     plus the full report outline and its section number for proper ordering.
  3. **Assembly** -- code-level (no LLM) concatenation of every writer
     output into a single ``final_output`` document.

The assembled report is written to a markdown file in the output directory.

Usage:
  uv run python examples/fan_out_report.py
  uv run python examples/fan_out_report.py --task "The history and future of space exploration"
  uv run python examples/fan_out_report.py --base-url http://localhost:8080/v1
  uv run python examples/fan_out_report.py --output-dir ./reports
"""

import argparse
import asyncio
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# Ensure hiveflow is importable when running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hiveflow import (
    Agent,
    AgentBehaviorType,
    SummaryGenerator,
    WorkflowEngine,
    WorkflowStep,
)
from hiveflow.plugins.llm import LLMConfig
from hiveflow.plugins.llm.openai_provider import OpenAIProvider

# ---------------------------------------------------------------------------
# Configuration -- point at any OpenAI-compatible server (llama.cpp, vLLM, ...)
# ---------------------------------------------------------------------------
DEFAULT_BASE_URL = os.environ.get("OPENAI_BASE_URL", "http://localhost:8080/v1")
MODEL_NAME = "local-model"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("fan_out_report")


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------
def build_agents(provider: OpenAIProvider) -> dict[str, Agent]:
    """Create the planner (orchestrator) and writer (fan-out worker)."""

    planner = Agent(
        agent_id="planner",
        role="Report Planner",
        system_prompt=(
            "You are a report planner. Your job is to decompose a broad topic "
            "into 4-6 independent sections for a comprehensive report.\n\n"
            "Rules:\n"
            "- Each section must cover a distinct, non-overlapping aspect.\n"
            "- Sections must be self-contained (written in parallel by "
            "different writers who cannot see each other's work).\n"
            "- Number sections sequentially starting at 1.\n"
            "- Include a descriptive title and a one-sentence scope.\n\n"
            "Respond with ONLY a JSON object in this exact format:\n"
            '{"sub_tasks": [\n'
            '  "Section 1: <Title> - <one-sentence scope>",\n'
            '  "Section 2: <Title> - <one-sentence scope>",\n'
            "  ...\n"
            "]}"
        ),
        behavior_type=AgentBehaviorType.ORCHESTRATOR,
        model=MODEL_NAME,
        llm_provider=provider,
        llm_config=LLMConfig(model=MODEL_NAME, temperature=0.4, max_tokens=1024),
    )

    writer = Agent(
        agent_id="writer",
        role="Section Writer",
        system_prompt=(
            "You are a professional long-form writer producing one section of "
            "a larger report. You will receive:\n"
            "- Your specific section assignment\n"
            "- Your section number and total section count\n"
            "- The full report outline (all sections)\n\n"
            "Rules:\n"
            "- Write ONLY your assigned section.\n"
            "- Start with a markdown heading using your assigned section number "
            "(e.g. ## 3. Title).\n"
            "- Produce detailed, well-structured content with multiple "
            "paragraphs, subheadings, examples, and data.\n"
            "- Aim for at least 800 words.\n"
            "- Do NOT repeat content that belongs to other sections.\n"
            "- Do NOT include an introduction or conclusion for the full report."
        ),
        behavior_type=AgentBehaviorType.LLM_ONLY,
        model=MODEL_NAME,
        llm_provider=provider,
        llm_config=LLMConfig(model=MODEL_NAME, temperature=0.7, max_tokens=4096),
        context_budget=2000,
    )

    return {"planner": planner, "writer": writer}


# ---------------------------------------------------------------------------
# Workflow: orchestrator -> parallel fan-out -> assembly
# ---------------------------------------------------------------------------
def build_workflow(provider: OpenAIProvider) -> WorkflowEngine:
    """Two-step divide-and-conquer pipeline with assembly."""
    steps = [
        # Step 1: planner decomposes task -> populates parallel_items
        WorkflowStep(agent="planner", step_type="sequential", next_step="writer"),
        # Step 2: writer runs in parallel on each item
        WorkflowStep(agent="writer", step_type="parallel_fan_out"),
    ]
    summarizer = SummaryGenerator(llm_provider=provider, max_summary_tokens=200)
    return WorkflowEngine(
        steps,
        summarizer=summarizer,
        assembly_agents=["writer"],
    )


# ---------------------------------------------------------------------------
# Event handler -- detailed console logging
# ---------------------------------------------------------------------------
_step_start_times: dict[str, float] = {}


def on_event(event_type: str, agent_id: str, data: dict[str, Any]) -> None:
    """Log workflow events with timing information."""
    if event_type == "step_start":
        _step_start_times[agent_id] = time.time()
        step_type = data.get("step_type", "")
        logger.info("=" * 60)
        logger.info("STEP START: %s (%s)", agent_id, step_type)
        logger.info("=" * 60)
    elif event_type == "step_complete":
        elapsed = time.time() - _step_start_times.get(agent_id, time.time())
        logger.info("STEP COMPLETE: %s (%.1fs)", agent_id, elapsed)
    elif event_type == "step_error":
        logger.error("STEP ERROR: %s -- %s", agent_id, data.get("error", "unknown"))
    elif event_type == "summary_generated":
        logger.info(
            "  Summary generated for %s (%s words)",
            agent_id,
            data.get("summary_length", "?"),
        )
    elif event_type == "outline_generated":
        logger.info(
            "  Outline generated for %s (%s items)",
            agent_id,
            data.get("num_items", "?"),
        )
    elif event_type == "assembly_complete":
        logger.info(
            "  Assembly complete: %s sections, %s words",
            data.get("num_sections", "?"),
            data.get("total_words", "?"),
        )


# ---------------------------------------------------------------------------
# Markdown output helper
# ---------------------------------------------------------------------------
def _slugify(text: str) -> str:
    """Turn a task string into a safe filename slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:80] if len(slug) > 80 else slug


def write_report(
    task: str,
    final_output: str,
    parallel_items: list[str],
    output_dir: Path,
) -> Path:
    """Write the assembled report to a markdown file and return the path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = _slugify(task)
    filename = f"{timestamp}-{slug}.md"
    filepath = output_dir / filename

    lines = [
        f"# {task}",
        "",
        f"*Generated by HiveFlow fan-out pipeline on "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M')}*",
        "",
        f"**Sections planned:** {len(parallel_items)}  ",
        f"**Word count:** {len(final_output.split())}",
        "",
        "---",
        "",
    ]

    # Add table of contents from parallel items
    lines.append("## Table of Contents")
    lines.append("")
    for i, item in enumerate(parallel_items, 1):
        lines.append(f"{i}. {item}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Add the assembled report body
    lines.append(final_output)
    lines.append("")

    filepath.write_text("\n".join(lines), encoding="utf-8")
    return filepath


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def run(task: str, base_url: str, output_dir: Path) -> None:
    start_time = time.time()

    provider = OpenAIProvider(base_url=base_url, api_key="not-needed")
    agents = build_agents(provider)
    engine = build_workflow(provider)
    engine.on_event(on_event)

    logger.info("Task: %s", task)
    logger.info("Base URL: %s", base_url)
    logger.info("Output dir: %s", output_dir)
    logger.info("")

    result = await engine.execute(
        agents=agents,
        initial_state={"task": task},
    )

    elapsed = time.time() - start_time

    # -- Log results -----------------------------------------------------------
    logger.info("")
    logger.info("=" * 60)
    logger.info("WORKFLOW COMPLETE")
    logger.info("=" * 60)
    logger.info("  Status:   %s", result.status.value)
    logger.info("  Steps:    %d", len(result.step_results))
    logger.info("  Elapsed:  %.1fs", elapsed)

    if result.error:
        logger.error("  Error: %s", result.error)
        return

    # Section details
    parallel_items = result.state.get("parallel_items", [])
    writer_outputs = result.state.get("writer_outputs", [])
    logger.info("  Sections planned: %d", len(parallel_items))
    logger.info("  Sections written: %d", len(writer_outputs))

    for i, item in enumerate(parallel_items, 1):
        output = writer_outputs[i - 1] if i - 1 < len(writer_outputs) else ""
        words = len(output.split()) if isinstance(output, str) else 0
        logger.info("    Section %d: %d words -- %s", i, words, item[:60])

    # Token usage
    logger.info("")
    logger.info("Token usage:")
    total_tokens = 0
    for step in result.step_results:
        usage = result.state.get(f"{step.agent_id}_usage")
        if usage:
            logger.info(
                "  %s: %d tokens (prompt=%d, completion=%d)",
                step.agent_id,
                usage["total_tokens"],
                usage["prompt_tokens"],
                usage["completion_tokens"],
            )
            total_tokens += usage["total_tokens"]
    logger.info("  Total: %d tokens", total_tokens)

    # -- Write markdown report -------------------------------------------------
    final = result.state.get("final_output", "")
    if final:
        word_count = len(final.split())
        filepath = write_report(task, final, parallel_items, output_dir)
        logger.info("")
        logger.info("Report written: %s (%d words)", filepath, word_count)
    else:
        logger.warning("No final output was assembled.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a long-form report using fan-out parallelism",
    )
    parser.add_argument(
        "--task",
        default=(
            "Write a comprehensive report on the current state "
            "and future of artificial intelligence"
        ),
        help="The report topic",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help="OpenAI-compatible API base URL",
    )
    parser.add_argument(
        "--output-dir",
        default="output",
        help="Directory for the generated markdown report (default: ./output)",
    )
    args = parser.parse_args()
    asyncio.run(
        run(
            task=args.task,
            base_url=args.base_url,
            output_dir=Path(args.output_dir),
        )
    )


if __name__ == "__main__":
    main()
