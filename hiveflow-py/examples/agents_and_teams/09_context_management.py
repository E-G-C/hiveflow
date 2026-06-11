#!/usr/bin/env python3
"""Example 09: End-to-end context management showcase.

Demonstrates every context management strategy in HiveFlow through a
multi-agent report-writing pipeline with full instrumentation:

  Strategies exercised:
    1. Summary propagation -- downstream agents receive ~200-token summaries
    2. Differential compression -- reasoning outputs get 2x budget, data 0.5x
    3. Orchestrator decomposition -- breaks task into parallel sub-tasks
    4. Parallel fan-out -- each sub-task runs in its own isolated context
    5. Context budget enforcement -- agents capped at N words of context
    6. Sliding window -- old summaries collapsed after window size exceeded
    7. Context TTL expiry -- early-step summaries expire after N downstream steps
    8. Redundancy detection -- trigram overlap >60% replaced with back-references
    9. Intelligent context reduction (ContextReducer) -- LLM-based waste removal
   10. Code-level assembly -- final output stitched by Python, not LLM

  Pipeline:
    planner (orchestrator, output_type=structured_data)
      -> researcher (parallel_fan_out, context_ttl=2)
        -> analyst (sequential, output_type=reasoning, context_budget=3000)
          -> writer (sequential, sliding_window=2)
            -> reviewer (sequential)

  The example instruments every event callback and produces a detailed
  efficiency report alongside the team output, then publishes both as
  Markdown (.md) and Word (.docx).

Usage:
    uv run python examples/agents_and_teams/09_context_management.py

    # Custom task:
    uv run python examples/agents_and_teams/09_context_management.py \\
        --task "Compare Kubernetes vs serverless for ML inference workloads"

    # Different deployment:
    AZURE_OPENAI_DEPLOYMENT=gpt-4o \\
        uv run python examples/agents_and_teams/09_context_management.py
"""

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hiveflow.core.agent import Agent, AgentBehaviorType
from hiveflow.core.config import HiveFlowConfig
from hiveflow.core.context_reducer import ContextReducer
from hiveflow.core.summarizer import SummaryGenerator
from hiveflow.core.workflow import (
    WorkflowEngine,
    WorkflowResult,
    WorkflowStatus,
    WorkflowStep,
)
from hiveflow.plugins.llm import LLMConfig

AZURE_ENDPOINT = "https://foundry-aisbx-we.cognitiveservices.azure.com"


# -- Instrumentation collector ------------------------------------------------

class ContextManagementMetrics:
    """Collects metrics during workflow execution for the efficiency report."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.summaries_generated: list[dict[str, Any]] = []
        self.outlines_generated: list[dict[str, Any]] = []
        self.steps_completed: list[dict[str, Any]] = []
        self.start_time: float = 0.0
        self.end_time: float = 0.0

    def on_event(self, event_type: str, agent_id: str, data: dict[str, Any]) -> None:
        """Capture every workflow event for analysis."""
        timestamp = time.time()
        entry = {
            "time": timestamp,
            "type": event_type,
            "agent": agent_id,
            "data": data,
        }
        self.events.append(entry)

        # Live progress output
        if event_type == "step_start":
            step_type = data.get("step_type", "")
            print(f"  > {agent_id} ({step_type})...", flush=True)
        elif event_type == "step_complete":
            print(f"  * {agent_id} done", flush=True)
            self.steps_completed.append(entry)
        elif event_type == "step_error":
            print(f"  X {agent_id} FAILED: {data.get('error', '')}", flush=True)
        elif event_type == "summary_generated":
            length = data.get("summary_length", 0)
            print(f"    -> summary generated ({length} words)", flush=True)
            self.summaries_generated.append(entry)
        elif event_type == "outline_generated":
            count = data.get("num_items", 0)
            print(f"    -> outline assembled from {count} items", flush=True)
            self.outlines_generated.append(entry)
        elif event_type == "assembly_complete":
            sections = data.get("num_sections", 0)
            words = data.get("total_words", 0)
            print(f"  ! Final output assembled: {sections} sections, {words} words", flush=True)

    def build_report(self, state: dict[str, Any], config_summary: dict[str, Any]) -> str:
        """Build a Markdown efficiency report from collected metrics."""
        elapsed = self.end_time - self.start_time
        lines: list[str] = []
        lines.append("# Context Management Efficiency Report")
        lines.append("")
        lines.append(f"**Generated:** {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
        lines.append(f"**Total elapsed:** {elapsed:.1f}s")
        lines.append("")

        # Configuration summary
        lines.append("## Configuration")
        lines.append("")
        lines.append("| Parameter | Value |")
        lines.append("|-----------|-------|")
        for key, val in config_summary.items():
            lines.append(f"| {key} | {val} |")
        lines.append("")

        # Pipeline summary
        lines.append("## Pipeline Execution")
        lines.append("")
        lines.append(f"- **Steps completed:** {len(self.steps_completed)}")
        lines.append(f"- **Summaries generated:** {len(self.summaries_generated)}")
        lines.append(f"- **Outlines generated:** {len(self.outlines_generated)}")
        lines.append(f"- **Total events:** {len(self.events)}")
        lines.append("")

        # Per-agent token usage
        lines.append("## Token Usage by Agent")
        lines.append("")
        lines.append("| Agent | Words | Tokens (prompt) | Tokens (completion) | Tokens (total) |")
        lines.append("|-------|-------|-----------------|--------------------:|---------------:|")
        total_prompt = 0
        total_completion = 0
        total_tokens = 0
        for key in state:
            if key.endswith("_output") and not key.endswith("_outputs"):
                agent_name = key.replace("_output", "")
                output = state[key]
                words = len(output.split()) if isinstance(output, str) else 0
                usage = state.get(f"{agent_name}_usage", {})
                if usage:
                    pt = usage.get("prompt_tokens", 0)
                    ct = usage.get("completion_tokens", 0)
                    tt = usage.get("total_tokens", 0)
                else:
                    pt = ct = tt = 0
                total_prompt += pt
                total_completion += ct
                total_tokens += tt
                lines.append(f"| {agent_name} | {words:,} | {pt:,} | {ct:,} | {tt:,} |")
        lines.append(f"| **TOTAL** | | **{total_prompt:,}** | **{total_completion:,}** | **{total_tokens:,}** |")
        lines.append("")

        # Context management impact
        lines.append("## Context Management Strategies in Action")
        lines.append("")

        # Summary propagation
        lines.append("### 1. Summary Propagation")
        lines.append("")
        for entry in self.summaries_generated:
            agent = entry["agent"]
            summary_words = entry["data"].get("summary_length", 0)
            full_output = state.get(f"{agent}_output", "")
            full_words = len(full_output.split()) if isinstance(full_output, str) else 0
            if full_words > 0:
                ratio = summary_words / full_words * 100
                saving = full_words - summary_words
                lines.append(
                    f"- **{agent}:** {full_words:,} words -> {summary_words} words "
                    f"({ratio:.0f}% of original, saved {saving:,} words)"
                )
        lines.append("")

        # Outline generation
        if self.outlines_generated:
            lines.append("### 2. Outline Generation (Parallel Fan-Out)")
            lines.append("")
            for entry in self.outlines_generated:
                agent = entry["agent"]
                count = entry["data"].get("num_items", 0)
                outline = state.get(f"{agent}_outline", "")
                words = len(outline.split()) if isinstance(outline, str) else 0
                lines.append(f"- **{agent}:** {count} parallel items -> {words}-word outline")
            lines.append("")

        # Context TTL
        ttl_map = state.get("_context_ttl", {})
        if ttl_map:
            lines.append("### 3. Context TTL Expiry")
            lines.append("")
            step_order = state.get("_step_order", [])
            lines.append(f"- Step execution order: {' -> '.join(step_order)}")
            for agent, ttl in ttl_map.items():
                lines.append(f"- **{agent}:** TTL={ttl} steps (expires for agents >{ttl} steps downstream)")
            lines.append("")

        # Parallel fan-out
        parallel_items = state.get("parallel_items", [])
        if parallel_items:
            lines.append("### 4. Orchestrator Decomposition + Parallel Fan-Out")
            lines.append("")
            lines.append(f"- **Sub-tasks generated:** {len(parallel_items)}")
            for i, item in enumerate(parallel_items):
                lines.append(f"  {i+1}. {item[:100]}{'...' if len(item) > 100 else ''}")
            lines.append("")

        # Final assembly
        final_output = state.get("final_output", "")
        if final_output:
            lines.append("### 5. Code-Level Assembly")
            lines.append("")
            words = len(final_output.split())
            lines.append(f"- **Final assembled output:** {words:,} words")
            lines.append("- Assembly method: Python concatenation (no LLM call)")
            lines.append("")

        # Summary vs full output comparison
        lines.append("## Efficiency Summary")
        lines.append("")
        total_full_words = 0
        total_summary_words = 0
        for key in state:
            if key.endswith("_output") and not key.endswith("_outputs"):
                agent_name = key.replace("_output", "")
                output = state[key]
                if isinstance(output, str):
                    total_full_words += len(output.split())
                summary = state.get(f"{agent_name}_summary", "")
                if isinstance(summary, str) and summary:
                    total_summary_words += len(summary.split())

        if total_full_words > 0 and total_summary_words > 0:
            compression_ratio = (1 - total_summary_words / total_full_words) * 100
            lines.append(f"- **Total raw output:** {total_full_words:,} words")
            lines.append(f"- **Total summaries:** {total_summary_words:,} words")
            lines.append(f"- **Compression ratio:** {compression_ratio:.1f}% reduction")
            lines.append(f"- **Context saved per downstream agent:** ~{total_full_words - total_summary_words:,} words")
        lines.append(f"- **Total tokens used:** {total_tokens:,}")
        lines.append(f"- **Wall-clock time:** {elapsed:.1f}s")
        lines.append("")

        # Event timeline
        lines.append("## Event Timeline")
        lines.append("")
        lines.append("| Time (s) | Event | Agent | Details |")
        lines.append("|----------|-------|-------|---------|")
        for entry in self.events:
            t = entry["time"] - self.start_time
            etype = entry["type"]
            agent = entry["agent"]
            details = ""
            if etype == "summary_generated":
                details = f"{entry['data'].get('summary_length', '?')} words"
            elif etype == "outline_generated":
                details = f"{entry['data'].get('num_items', '?')} items"
            elif etype == "assembly_complete":
                details = f"{entry['data'].get('num_sections', '?')} sections"
            elif etype == "step_error":
                details = str(entry["data"].get("error", ""))[:60]
            lines.append(f"| {t:.2f} | {etype} | {agent} | {details} |")
        lines.append("")

        return "\n".join(lines)


# -- Team configuration -------------------------------------------------------

def build_team(
    provider: Any,
    model: str,
    config: HiveFlowConfig,
) -> tuple[dict[str, Agent], WorkflowEngine, ContextManagementMetrics, dict[str, Any]]:
    """Build the instrumented context management showcase team.

    Returns:
        (agents, engine, metrics, config_summary)
    """
    metrics = ContextManagementMetrics()

    # --- Agents ---

    planner = Agent(
        agent_id="planner",
        role="Task Decomposition Planner",
        system_prompt=(
            "You are a task decomposition expert. Analyze the given task and "
            "break it into 3-5 independent sub-tasks that can be researched "
            "and written in parallel.\n\n"
            "Respond with ONLY a JSON object:\n"
            '{"sub_tasks": ["Sub-task 1: ...", "Sub-task 2: ...", ...]}'
        ),
        behavior_type=AgentBehaviorType.ORCHESTRATOR,
        model=model,
        llm_provider=provider,
        llm_config=LLMConfig(model=model, max_tokens=2000),
        output_type="structured_data",  # Gets 2x summary budget
    )

    researcher = Agent(
        agent_id="researcher",
        role="Parallel Research Writer",
        system_prompt=(
            "You are a thorough researcher and writer. For your assigned "
            "sub-task, produce a detailed, well-structured section of "
            "approximately 500-800 words.\n\n"
            "SECTION FORMAT -- this section will be merged into a larger "
            "document by an automated pipeline. A separate agent writes "
            "the introduction and conclusion for the full document.\n\n"
            "Structure your output exactly as follows:\n"
            "1. Begin with: ## <number>. <Section Title>\n"
            "2. Use ### sub-headings to organize major points.\n"
            "3. End on a substantive point (a fact, data, example, or "
            "analysis). The last paragraph must contain specific content, "
            "not a restatement of what was covered.\n\n"
            "Omit any of the following -- they are handled elsewhere:\n"
            "- Section-level conclusion, summary, or 'in summary' paragraph\n"
            "- Overall document introduction or preamble\n"
            "- Content that belongs to other sections"
        ),
        behavior_type=AgentBehaviorType.LLM_ONLY,
        model=model,
        llm_provider=provider,
        llm_config=LLMConfig(model=model, max_tokens=4096),
        output_type="data",  # Gets 0.5x summary budget (aggressive compression)
    )

    analyst = Agent(
        agent_id="analyst",
        role="Cross-Cutting Analyst",
        system_prompt=(
            "You are a senior analyst. Review the outline of research "
            "findings and produce a cross-cutting analysis that identifies "
            "themes, trade-offs, and strategic recommendations. Focus on "
            "insights that span multiple sub-topics. Write 400-600 words."
        ),
        behavior_type=AgentBehaviorType.LLM_ONLY,
        model=model,
        llm_provider=provider,
        llm_config=LLMConfig(model=model, max_tokens=4096),
        context_budget=3000,  # Enforce context budget
        context_reducer=ContextReducer(
            llm_provider=provider,
            model=model,
            overflow_threshold=1.5,
        ),
        output_type="reasoning",  # Gets 2x summary budget
        context_recency_window=0,  # No window limit here (gets outline)
    )

    writer = Agent(
        agent_id="writer",
        role="Executive Summary Writer",
        system_prompt=(
            "You are an executive report writer. Using the analysis and "
            "research summaries provided, write a polished executive "
            "summary (300-500 words) that a C-level audience can act on. "
            "Include key findings, recommendations, and next steps."
        ),
        behavior_type=AgentBehaviorType.LLM_ONLY,
        model=model,
        llm_provider=provider,
        llm_config=LLMConfig(model=model, max_tokens=4096),
        context_recency_window=2,  # Sliding window: only 2 most recent summaries
    )

    reviewer = Agent(
        agent_id="reviewer",
        role="Quality Reviewer",
        system_prompt=(
            "You are a quality reviewer. Evaluate the assembled report for "
            "accuracy, completeness, structure, and clarity. Provide a "
            "brief quality assessment and any final recommendations for "
            "improvement. Write 200-300 words."
        ),
        behavior_type=AgentBehaviorType.LLM_ONLY,
        model=model,
        llm_provider=provider,
        llm_config=LLMConfig(model=model, max_tokens=2048),
        context_recency_window=3,  # See writer + analyst + outline
    )

    agents = {
        "planner": planner,
        "researcher": researcher,
        "analyst": analyst,
        "writer": writer,
        "reviewer": reviewer,
    }

    # --- Workflow Steps ---

    steps = [
        WorkflowStep(
            agent="planner",
            step_type="sequential",
            next_step="researcher",
            context_ttl=2,  # Planner summary expires after 2 downstream steps
        ),
        WorkflowStep(
            agent="researcher",
            step_type="parallel_fan_out",
            next_step="analyst",
            context_ttl=3,  # Research summaries visible for 3 steps
        ),
        WorkflowStep(
            agent="analyst",
            step_type="sequential",
            next_step="writer",
        ),
        WorkflowStep(
            agent="writer",
            step_type="sequential",
            next_step="reviewer",
        ),
        WorkflowStep(
            agent="reviewer",
            step_type="sequential",
            next_step=None,  # Terminal step
        ),
    ]

    # --- Summary propagation with differential compression ---

    summarizer = SummaryGenerator(
        llm_provider=provider,
        model=model,
        max_summary_tokens=200,
        max_outline_tokens=800,
        summary_threshold=100,  # Only summarize outputs > 100 words
    )

    # --- Code-level assembly: stitch researcher + writer for final output ---

    engine = WorkflowEngine(
        workflow_steps=steps,
        summarizer=summarizer,
        assembly_agents=["researcher", "writer"],
    )
    engine.on_event(metrics.on_event)

    # Config summary for the report
    config_summary = {
        "Model": model,
        "Summary propagation": "Enabled (200 tokens/summary, 800 tokens/outline)",
        "Summary threshold": "100 words (below = passthrough)",
        "Differential compression": "reasoning=2x, data=0.5x",
        "Context budget (analyst)": "3,000 words",
        "Context reducer": "Enabled (overflow threshold=1.5x)",
        "Sliding window (writer)": "2 most recent summaries",
        "Sliding window (reviewer)": "3 most recent summaries",
        "Context TTL (planner)": "2 steps",
        "Context TTL (researcher)": "3 steps",
        "Code-level assembly": "researcher + writer outputs",
        "Pipeline": "planner -> researcher (fan-out) -> analyst -> writer -> reviewer",
    }

    return agents, engine, metrics, config_summary


# -- Main execution ------------------------------------------------------------

async def main(task: str, deployment: str) -> None:
    os.environ.setdefault("AZURE_OPENAI_ENDPOINT", AZURE_ENDPOINT)

    from hiveflow.plugins.llm.azure_provider import AzureOpenAIProvider

    provider = AzureOpenAIProvider(azure_endpoint=AZURE_ENDPOINT)
    config = HiveFlowConfig()

    azure_model = deployment

    print("=" * 70)
    print("HIVEFLOW CONTEXT MANAGEMENT SHOWCASE")
    print("=" * 70)
    print(f"  Endpoint:   {AZURE_ENDPOINT}")
    print(f"  Deployment: {deployment}")
    print(f"  Task:       {task}")
    print()

    # =========================================================================
    # PHASE 1: Build the instrumented team
    # =========================================================================
    print("=" * 70)
    print("PHASE 1: Building instrumented team")
    print("=" * 70)

    agents, engine, metrics, config_summary = build_team(provider, azure_model, config)

    print(f"  Agents:  {list(agents.keys())}")
    print(f"  Steps:   {len(engine.steps)}")
    print()

    # Show agent configuration
    print("  Agent configuration:")
    for aid, agent in agents.items():
        features = []
        if agent.context_budget:
            features.append(f"budget={agent.context_budget}")
        if agent.context_recency_window > 0:
            features.append(f"window={agent.context_recency_window}")
        if agent.context_reducer:
            features.append("reducer=ON")
        if agent.output_type:
            features.append(f"type={agent.output_type}")
        feat_str = ", ".join(features) if features else "defaults"
        print(f"    {aid:15s}  [{agent.behavior_type.value:15s}]  {feat_str}")
    print()

    # =========================================================================
    # PHASE 2: Execute the workflow
    # =========================================================================
    print("=" * 70)
    print("PHASE 2: Executing workflow")
    print("=" * 70)

    metrics.start_time = time.time()
    wf_result: WorkflowResult = await engine.execute(
        agents=agents,
        initial_state={"task": task},
    )
    metrics.end_time = time.time()

    elapsed = metrics.end_time - metrics.start_time
    print()
    print(f"  Status:  {wf_result.status.value}")
    print(f"  Steps:   {len(wf_result.step_results)}")
    print(f"  Elapsed: {elapsed:.1f}s")
    print()

    if wf_result.status == WorkflowStatus.FAILED:
        print(f"  Error: {wf_result.error}")
        return

    state = wf_result.state

    # =========================================================================
    # PHASE 3: Display results
    # =========================================================================
    print("=" * 70)
    print("PHASE 3: Results")
    print("=" * 70)

    # Per-agent token summary
    total_tokens = 0
    for aid in agents:
        output = state.get(f"{aid}_output", "")
        usage = state.get(f"{aid}_usage")
        words = len(output.split()) if isinstance(output, str) else 0
        summary = state.get(f"{aid}_summary", "")
        summary_words = len(summary.split()) if isinstance(summary, str) and summary else 0
        tokens = usage.get("total_tokens", 0) if usage else 0
        total_tokens += tokens
        summary_info = f"  summary={summary_words}w" if summary_words else ""
        print(f"  {aid:15s}  {words:5d} words  {tokens:5d} tokens{summary_info}")

    print(f"  {'TOTAL':15s}  {'':5s}        {total_tokens:5d} tokens")
    print()

    # Context management observations
    print("  Context management observations:")
    step_order = state.get("_step_order", [])
    print(f"    Step order: {' -> '.join(step_order)}")

    ttl_map = state.get("_context_ttl", {})
    if ttl_map:
        print(f"    Context TTL: {ttl_map}")

    parallel_items = state.get("parallel_items", [])
    if parallel_items:
        print(f"    Parallel sub-tasks: {len(parallel_items)}")

    researcher_outline = state.get("researcher_outline", "")
    if researcher_outline:
        print(f"    Researcher outline: {len(researcher_outline.split())} words")

    final = state.get("final_output", "")
    if final:
        print(f"    Final assembled output: {len(final.split())} words")
    print()

    # Show abbreviated outputs
    for aid in agents:
        output = state.get(f"{aid}_output", "")
        if not output:
            continue
        print(f"--- {aid} ({agents[aid].role}) ---")
        if isinstance(output, str):
            print(output[:800])
            if len(output) > 800:
                print(f"  ... ({len(output)} chars total)")
        print()

    # =========================================================================
    # PHASE 4: Generate report title and efficiency report
    # =========================================================================
    print("=" * 70)
    print("PHASE 4: Generating report title + efficiency report")
    print("=" * 70)

    # Generate a concise document title from the task description via LLM
    from hiveflow.plugins.llm import LLMMessage

    title_messages = [
        LLMMessage(
            role="user",
            content=(
                "Generate a short, professional document title (max 10 words) "
                "for a report on the following topic. Respond with ONLY "
                "the title, no quotes or punctuation around it.\n\n"
                f"Topic: {task}"
            ),
        ),
    ]
    title_config = LLMConfig(model=azure_model, max_tokens=50, temperature=0.3)
    title_response = await provider.chat(title_messages, title_config)
    report_title = title_response.content.strip().strip('"').strip("'")
    print(f"  Generated title: {report_title}")

    # Inject into state so ResultPayload picks it up
    state["report_title"] = report_title

    report = metrics.build_report(state, config_summary)
    print(f"  Report generated: {len(report.split())} words")
    print()

    # =========================================================================
    # PHASE 5: Publish output (Markdown + Word)
    # =========================================================================
    print("=" * 70)
    print("PHASE 5: Publishing output (Markdown + Word)")
    print("=" * 70)

    from hiveflow.core.result_payload import ResultPayload
    from hiveflow.plugins.publishers import MarkdownPublisher, PublisherRegistry

    # Build payload with the generated title (the engine's internal payload
    # was built before we generated the title, so rebuild it here)
    payload = ResultPayload.from_workflow_result(wf_result, title=report_title)

    timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_dir = Path("./output")
    output_dir.mkdir(parents=True, exist_ok=True)

    # --- Publish main report ---

    filename_main = f"context_mgmt_report_{timestamp}"
    registry = PublisherRegistry(drop_in_dir=None)
    registry.register(MarkdownPublisher())

    formats = ["markdown"]
    try:
        from hiveflow.plugins.publishers.docx_publisher import DOCXPublisher
        registry.register(DOCXPublisher())
        formats.append("docx")
    except ImportError:
        print("  Note: pypandoc not installed -- skipping DOCX output")
        print("        Install with: uv pip install 'hiveflow[publishers]'")

    paths = await registry.publish_all(
        payload,
        output_dir=str(output_dir),
        formats=formats,
        filename=filename_main,
    )

    for p in paths:
        print(f"  Saved: {p}")

    # --- Publish efficiency report ---

    filename_efficiency = f"context_mgmt_efficiency_{timestamp}"
    md_path = output_dir / f"{filename_efficiency}.md"
    md_path.write_text(report, encoding="utf-8")
    print(f"  Saved: {md_path}")

    # Also produce a Word version of the efficiency report if pypandoc available
    try:
        import pypandoc
        docx_path = output_dir / f"{filename_efficiency}.docx"
        pypandoc.convert_text(
            report,
            "docx",
            format="md",
            outputfile=str(docx_path),
        )
        print(f"  Saved: {docx_path}")
    except ImportError:
        pass
    except Exception as e:
        print(f"  Warning: DOCX efficiency report failed: {e}")

    print()
    print("=" * 70)
    print("DONE")
    print("=" * 70)


def cli() -> None:
    parser = argparse.ArgumentParser(
        description="End-to-end context management showcase with instrumentation and output publishing",
    )
    parser.add_argument(
        "--task",
        default=(
            "Write a comprehensive comparison of three approaches to "
            "building AI-powered applications: prompt engineering with "
            "foundation models, fine-tuning open-source models, and "
            "training custom models from scratch. Cover cost, quality, "
            "latency, and team skill requirements."
        ),
        help="Task description for the team to execute",
    )
    parser.add_argument(
        "--deployment",
        default=os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini"),
        help="Azure OpenAI deployment name (default: gpt-4o-mini)",
    )
    args = parser.parse_args()
    asyncio.run(main(task=args.task, deployment=args.deployment))


if __name__ == "__main__":
    cli()
