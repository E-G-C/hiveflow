#!/usr/bin/env python3
"""Example 10: Task-driven pipeline -- read task from markdown, auto-generate team, execute, publish audit trail.

Demonstrates the full autonomous pipeline driven by a markdown task file:
  1. Read a task description from a .md file
  2. Inspect available archetypes in the library
  3. LLM generates a complete TeamConfiguration (agents + workflow)
  4. Inspect capability gaps and new archetypes
  5. Build live agents from the generated config
  6. Execute the workflow against Azure OpenAI
  7. Publish two markdown outputs:
     - An **execution report** documenting every decision and result
     - The **team output** (the actual content produced by the agents)

The execution report is the key deliverable -- it makes the entire
multi-agent process transparent by documenting what archetypes were
available, what the LLM decided, how agents performed, and the full
event timeline.

Use ``--dry-run`` to stop after team generation and inspect the LLM's
design decisions without executing the workflow or consuming tokens on
agent calls.

Uses Azure OpenAI with Entra ID RBAC authentication.

Usage:
    uv run python examples/agents_and_teams/10_task_driven_pipeline.py

    # Custom task file:
    uv run python examples/agents_and_teams/10_task_driven_pipeline.py --task-file path/to/my_task.md

    # Dry run -- see what the LLM designs without executing:
    uv run python examples/agents_and_teams/10_task_driven_pipeline.py --dry-run

    # Different deployment:
    AZURE_OPENAI_DEPLOYMENT=gpt-4o \\
        uv run python examples/agents_and_teams/10_task_driven_pipeline.py
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

from hiveflow import TeamGenerator, WorkflowStatus
from hiveflow.core.teams import ArchetypeLibrary, TeamGenerationResult
from hiveflow.plugins.llm.azure_provider import AzureOpenAIProvider

AZURE_ENDPOINT = "https://foundry-aisbx-we.cognitiveservices.azure.com"


# -- Instrumentation collector ------------------------------------------------

class PipelineMetrics:
    """Collects events and timing data during workflow execution."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.start_time: float = 0.0
        self.end_time: float = 0.0

    def on_event(self, event_type: str, agent_id: str, data: dict[str, Any]) -> None:
        """Capture every workflow event for the execution report."""
        self.events.append({
            "time": time.time(),
            "type": event_type,
            "agent": agent_id,
            "data": data,
        })

        # Live progress output to console
        if event_type == "step_start":
            step_type = data.get("step_type", "")
            print(f"  > {agent_id} ({step_type})...", flush=True)
        elif event_type == "step_complete":
            print(f"  * {agent_id} done", flush=True)
        elif event_type == "step_error":
            print(f"  X {agent_id} FAILED: {data.get('error', '')}", flush=True)
        elif event_type == "assembly_complete":
            sections = data.get("num_sections", 0)
            words = data.get("total_words", 0)
            print(f"  ! Assembled: {sections} sections, {words} words", flush=True)

    def agent_elapsed(self, agent_id: str) -> float | None:
        """Compute elapsed time for an agent from step_start to step_complete."""
        start = None
        for e in self.events:
            if e["agent"] == agent_id and e["type"] == "step_start":
                start = e["time"]
            elif e["agent"] == agent_id and e["type"] == "step_complete" and start:
                return e["time"] - start
        return None


# -- Execution report builder -------------------------------------------------

def build_execution_report(
    task_text: str,
    task_file: Path,
    archetype_catalog: list[dict[str, Any]],
    generation_result: TeamGenerationResult,
    generation_elapsed: float,
    config: dict[str, Any],
    wf_result: Any,
    metrics: PipelineMetrics,
    deployment: str,
    report_title: str,
    output_filename: str,
) -> str:
    """Build the detailed markdown execution report (audit trail)."""
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    total_elapsed = metrics.end_time - metrics.start_time + generation_elapsed
    state = wf_result.state

    lines: list[str] = []

    # -- Header ---------------------------------------------------------------
    lines.append(f"# Execution Report: {report_title}")
    lines.append("")
    lines.append(f"**Generated:** {now}  ")
    lines.append(f"**Task file:** `{task_file}`  ")
    lines.append(f"**Model deployment:** {deployment}  ")
    lines.append(f"**Total elapsed:** {total_elapsed:.1f}s")
    lines.append("")
    lines.append("---")
    lines.append("")

    # -- 1. Task Description --------------------------------------------------
    lines.append("## 1. Task Description")
    lines.append("")
    for line in task_text.strip().splitlines():
        lines.append(f"> {line}")
    lines.append("")

    # -- 2. Available Archetypes ----------------------------------------------
    lines.append("## 2. Available Archetypes")
    lines.append("")
    lines.append(f"The archetype library contained **{len(archetype_catalog)}** archetypes at generation time:")
    lines.append("")
    lines.append("| Archetype | Role | Behavior Type |")
    lines.append("|-----------|------|---------------|")
    for arch in archetype_catalog:
        lines.append(f"| {arch['name']} | {arch['role']} | {arch['behavior_type']} |")
    lines.append("")

    # -- 3. LLM Team Design Decisions -----------------------------------------
    lines.append("## 3. LLM Team Design Decisions")
    lines.append("")
    lines.append(f"**Generation time:** {generation_elapsed:.1f}s")
    lines.append("")

    # 3.1 Team overview
    agents_list = config.get("agents", [])
    workflow_steps = config.get("workflow", {}).get("steps", [])

    lines.append("### 3.1 Team Overview")
    lines.append("")
    lines.append("| Property | Value |")
    lines.append("|----------|-------|")
    lines.append(f"| Team name | {config.get('team_name', 'unnamed')} |")
    lines.append(f"| Description | {config.get('description', 'N/A')[:120]} |")
    lines.append(f"| Agent count | {len(agents_list)} |")
    lines.append(f"| Workflow steps | {len(workflow_steps)} |")
    lines.append("")

    # 3.2 Agent roster
    lines.append("### 3.2 Agent Roster")
    lines.append("")
    lines.append("| Agent ID | Role | Behavior Type | System Prompt (excerpt) |")
    lines.append("|----------|------|---------------|------------------------|")
    for agent in agents_list:
        prompt_excerpt = agent.get("system_prompt", "")[:80].replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {agent['id']} | {agent.get('role', '')} | "
            f"{agent.get('behavior_type', '')} | {prompt_excerpt}... |"
        )
    lines.append("")

    # 3.3 Workflow graph
    lines.append("### 3.3 Workflow Graph")
    lines.append("")

    # Text visualization
    graph_parts = []
    for step in workflow_steps:
        graph_parts.append(f"{step['agent']} [{step['type']}]")
    lines.append("```")
    lines.append(" -> ".join(graph_parts))
    lines.append("```")
    lines.append("")

    # Table
    lines.append("| Step | Agent | Type | Next |")
    lines.append("|------|-------|------|------|")
    for i, step in enumerate(workflow_steps, 1):
        nxt = step.get("next") or step.get("next_on_accept") or "(end)"
        lines.append(f"| {i} | {step['agent']} | {step['type']} | {nxt} |")
    lines.append("")

    # 3.4 Capability gaps
    lines.append("### 3.4 Capability Gaps")
    lines.append("")
    if generation_result.capability_gaps:
        lines.append("| Severity | Resource | Description | Fallback |")
        lines.append("|----------|----------|-------------|----------|")
        for gap in generation_result.capability_gaps:
            desc = gap.description[:80].replace("|", "\\|")
            fallback = (gap.fallback_strategy or "N/A")[:60].replace("|", "\\|")
            lines.append(
                f"| {gap.severity} | {gap.resource_type}:{gap.resource_id} | {desc} | {fallback} |"
            )
    else:
        lines.append("No capability gaps detected.")
    lines.append("")

    # 3.5 New archetypes
    lines.append("### 3.5 New Archetypes")
    lines.append("")
    if generation_result.new_archetypes:
        lines.append("These agents were invented by the LLM and do not exist in the default archetype library:")
        lines.append("")
        lines.append("| Agent ID | Role | Behavior Type |")
        lines.append("|----------|------|---------------|")
        for arch in generation_result.new_archetypes:
            lines.append(
                f"| {arch.get('id', '?')} | {arch.get('role', '')} | {arch.get('behavior_type', '')} |"
            )
    else:
        lines.append("All agents matched known archetypes.")
    lines.append("")

    # -- 4. Execution Results -------------------------------------------------
    exec_elapsed = metrics.end_time - metrics.start_time
    lines.append("## 4. Execution Results")
    lines.append("")
    lines.append(f"**Execution time:** {exec_elapsed:.1f}s  ")
    lines.append(f"**Status:** {wf_result.status.value}")
    lines.append("")

    # 4.1 Per-agent summary table
    lines.append("### 4.1 Per-Agent Summary")
    lines.append("")
    lines.append("| Agent | Words | Prompt Tokens | Completion Tokens | Total Tokens | Elapsed |")
    lines.append("|-------|------:|:-------------:|:-----------------:|:------------:|--------:|")

    total_prompt = 0
    total_completion = 0
    total_tokens = 0
    for agent_def in agents_list:
        aid = agent_def["id"]
        output = state.get(f"{aid}_output", "")
        words = len(output.split()) if isinstance(output, str) else 0
        usage = state.get(f"{aid}_usage")
        pt = usage.get("prompt_tokens", 0) if usage else 0
        ct = usage.get("completion_tokens", 0) if usage else 0
        tt = usage.get("total_tokens", 0) if usage else 0
        total_prompt += pt
        total_completion += ct
        total_tokens += tt

        agent_time = metrics.agent_elapsed(aid)
        time_str = f"~{agent_time:.1f}s" if agent_time else "N/A"

        lines.append(
            f"| {aid} | {words:,} | {pt:,} | {ct:,} | {tt:,} | {time_str} |"
        )

    lines.append(
        f"| **TOTAL** | | **{total_prompt:,}** | **{total_completion:,}** | "
        f"**{total_tokens:,}** | **{exec_elapsed:.1f}s** |"
    )
    lines.append("")

    # 4.2 Agent outputs (truncated)
    lines.append("### 4.2 Agent Outputs")
    lines.append("")
    for agent_def in agents_list:
        aid = agent_def["id"]
        output = state.get(f"{aid}_output", "")
        if not output:
            continue
        role = agent_def.get("role", aid)
        lines.append(f"#### {aid} ({role})")
        lines.append("")
        if isinstance(output, str) and len(output) > 2000:
            lines.append(output[:2000])
            lines.append("")
            lines.append(
                f"*... truncated ({len(output):,} chars total -- "
                f"see full output in `{output_filename}_team_output.md`)*"
            )
        else:
            lines.append(str(output))
        lines.append("")

    # -- 5. Final Assembled Output -------------------------------------------
    final = state.get("final_output", "")
    lines.append("## 5. Final Assembled Output")
    lines.append("")
    if final:
        if len(final) > 3000:
            lines.append(final[:3000])
            lines.append("")
            lines.append(
                f"*... truncated ({len(final):,} chars total -- "
                f"see full output in `{output_filename}_team_output.md`)*"
            )
        else:
            lines.append(final)
    else:
        # Fall back to last agent's output
        if agents_list:
            last_agent = agents_list[-1]["id"]
            last_output = state.get(f"{last_agent}_output", "(no output)")
            lines.append(f"*No assembled `final_output` -- showing last agent ({last_agent}) output:*")
            lines.append("")
            lines.append(str(last_output)[:3000])
    lines.append("")

    # -- 6. Event Timeline ---------------------------------------------------
    lines.append("## 6. Event Timeline")
    lines.append("")
    lines.append("| Time (s) | Event | Agent | Details |")
    lines.append("|----------|-------|-------|---------|")
    for entry in metrics.events:
        t = entry["time"] - metrics.start_time
        etype = entry["type"]
        agent = entry["agent"]
        details = ""
        if etype == "step_start":
            details = entry["data"].get("step_type", "")
        elif etype == "assembly_complete":
            details = f"{entry['data'].get('num_sections', '?')} sections, {entry['data'].get('total_words', '?')} words"
        elif etype == "step_error":
            details = str(entry["data"].get("error", ""))[:60]
        elif etype == "summary_generated":
            details = f"{entry['data'].get('summary_length', '?')} words"
        lines.append(f"| {t:.2f} | {etype} | {agent} | {details} |")
    lines.append("")

    # -- 7. Process Metadata -------------------------------------------------
    lines.append("## 7. Process Metadata")
    lines.append("")
    lines.append("| Property | Value |")
    lines.append("|----------|-------|")
    lines.append(f"| Azure endpoint | {AZURE_ENDPOINT} |")
    lines.append(f"| Deployment | {deployment} |")
    lines.append(f"| Task file | `{task_file}` |")
    lines.append(f"| Task file size | {len(task_text):,} bytes |")
    lines.append(f"| Generation time | {generation_elapsed:.1f}s |")
    lines.append(f"| Execution time | {exec_elapsed:.1f}s |")
    lines.append(f"| Total wall-clock | {total_elapsed:.1f}s |")
    lines.append(f"| Total tokens | {total_tokens:,} |")
    lines.append(f"| Agents created | {len(agents_list)} |")
    lines.append(f"| Workflow steps | {len(workflow_steps)} |")
    lines.append(f"| Capability gaps | {len(generation_result.capability_gaps)} |")
    lines.append(f"| New archetypes | {len(generation_result.new_archetypes)} |")
    lines.append("")

    # -- 8. Full Generated Config (JSON) -------------------------------------
    lines.append("## 8. Generated Team Configuration (JSON)")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(config, indent=2))
    lines.append("```")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("*This report was generated by HiveFlow Example 10: Task-Driven Pipeline.*")

    return "\n".join(lines)


# -- Dry-run report builder ---------------------------------------------------

def build_dry_run_report(
    task_text: str,
    task_file: Path,
    archetype_catalog: list[dict[str, Any]],
    generation_result: TeamGenerationResult,
    generation_elapsed: float,
    config: dict[str, Any],
    deployment: str,
) -> str:
    """Build a markdown report showing the LLM's design decisions (no execution)."""
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    agents_list = config.get("agents", [])
    workflow_steps = config.get("workflow", {}).get("steps", [])

    lines: list[str] = []

    # -- Header ---------------------------------------------------------------
    lines.append("# Dry-Run Report: Team Design Decisions")
    lines.append("")
    lines.append(f"**Generated:** {now}  ")
    lines.append(f"**Task file:** `{task_file}`  ")
    lines.append(f"**Model deployment:** {deployment}  ")
    lines.append(f"**Mode:** dry-run (no workflow execution)")
    lines.append("")
    lines.append("---")
    lines.append("")

    # -- 1. Task Description --------------------------------------------------
    lines.append("## 1. Task Description")
    lines.append("")
    for line in task_text.strip().splitlines():
        lines.append(f"> {line}")
    lines.append("")

    # -- 2. Available Archetypes ----------------------------------------------
    lines.append("## 2. Available Archetypes")
    lines.append("")
    lines.append(
        f"The archetype library contained **{len(archetype_catalog)}** "
        f"archetypes at generation time:"
    )
    lines.append("")
    lines.append("| Archetype | Role | Behavior Type |")
    lines.append("|-----------|------|---------------|")
    for arch in archetype_catalog:
        lines.append(f"| {arch['name']} | {arch['role']} | {arch['behavior_type']} |")
    lines.append("")

    # -- 3. LLM Team Design Decisions -----------------------------------------
    lines.append("## 3. LLM Team Design Decisions")
    lines.append("")
    lines.append(f"**Generation time:** {generation_elapsed:.1f}s")
    lines.append("")

    # 3.1 Team overview
    lines.append("### 3.1 Team Overview")
    lines.append("")
    lines.append("| Property | Value |")
    lines.append("|----------|-------|")
    lines.append(f"| Team name | {config.get('team_name', 'unnamed')} |")
    lines.append(f"| Description | {config.get('description', 'N/A')[:120]} |")
    lines.append(f"| Agent count | {len(agents_list)} |")
    lines.append(f"| Workflow steps | {len(workflow_steps)} |")
    lines.append("")

    # 3.2 Agent roster
    lines.append("### 3.2 Agent Roster")
    lines.append("")
    lines.append("| Agent ID | Role | Behavior Type | System Prompt (excerpt) |")
    lines.append("|----------|------|---------------|------------------------|")
    for agent in agents_list:
        prompt_excerpt = (
            agent.get("system_prompt", "")[:80].replace("|", "\\|").replace("\n", " ")
        )
        lines.append(
            f"| {agent['id']} | {agent.get('role', '')} | "
            f"{agent.get('behavior_type', '')} | {prompt_excerpt}... |"
        )
    lines.append("")

    # 3.3 Agent system prompts (full -- useful in dry-run to review before executing)
    lines.append("### 3.3 Full Agent System Prompts")
    lines.append("")
    for agent in agents_list:
        lines.append(f"#### {agent['id']} ({agent.get('role', '')})")
        lines.append("")
        lines.append("```")
        lines.append(agent.get("system_prompt", "(none)"))
        lines.append("```")
        lines.append("")

    # 3.4 Workflow graph
    lines.append("### 3.4 Workflow Graph")
    lines.append("")

    graph_parts = []
    for step in workflow_steps:
        graph_parts.append(f"{step['agent']} [{step['type']}]")
    lines.append("```")
    lines.append(" -> ".join(graph_parts))
    lines.append("```")
    lines.append("")

    lines.append("| Step | Agent | Type | Next |")
    lines.append("|------|-------|------|------|")
    for i, step in enumerate(workflow_steps, 1):
        nxt = step.get("next") or step.get("next_on_accept") or "(end)"
        lines.append(f"| {i} | {step['agent']} | {step['type']} | {nxt} |")
    lines.append("")

    # 3.5 Capability gaps
    lines.append("### 3.5 Capability Gaps")
    lines.append("")
    if generation_result.capability_gaps:
        lines.append("| Severity | Resource | Description | Fallback |")
        lines.append("|----------|----------|-------------|----------|")
        for gap in generation_result.capability_gaps:
            desc = gap.description[:80].replace("|", "\\|")
            fallback = (gap.fallback_strategy or "N/A")[:60].replace("|", "\\|")
            lines.append(
                f"| {gap.severity} | {gap.resource_type}:{gap.resource_id} "
                f"| {desc} | {fallback} |"
            )
    else:
        lines.append("No capability gaps detected.")
    lines.append("")

    # 3.6 New archetypes
    lines.append("### 3.6 New Archetypes")
    lines.append("")
    if generation_result.new_archetypes:
        lines.append(
            "These agents were invented by the LLM and do not exist "
            "in the default archetype library:"
        )
        lines.append("")
        lines.append("| Agent ID | Role | Behavior Type |")
        lines.append("|----------|------|---------------|")
        for arch in generation_result.new_archetypes:
            lines.append(
                f"| {arch.get('id', '?')} | {arch.get('role', '')} "
                f"| {arch.get('behavior_type', '')} |"
            )
    else:
        lines.append("All agents matched known archetypes.")
    lines.append("")

    # -- 4. Process Metadata --------------------------------------------------
    lines.append("## 4. Process Metadata")
    lines.append("")
    lines.append("| Property | Value |")
    lines.append("|----------|-------|")
    lines.append(f"| Mode | dry-run |")
    lines.append(f"| Azure endpoint | {AZURE_ENDPOINT} |")
    lines.append(f"| Deployment | {deployment} |")
    lines.append(f"| Task file | `{task_file}` |")
    lines.append(f"| Task file size | {len(task_text):,} bytes |")
    lines.append(f"| Generation time | {generation_elapsed:.1f}s |")
    lines.append(f"| Agents designed | {len(agents_list)} |")
    lines.append(f"| Workflow steps | {len(workflow_steps)} |")
    lines.append(f"| Capability gaps | {len(generation_result.capability_gaps)} |")
    lines.append(f"| New archetypes | {len(generation_result.new_archetypes)} |")
    lines.append("")

    # -- 5. Full Generated Config (JSON) --------------------------------------
    lines.append("## 5. Generated Team Configuration (JSON)")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(config, indent=2))
    lines.append("```")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        "*This dry-run report was generated by HiveFlow Example 10: "
        "Task-Driven Pipeline. Re-run without `--dry-run` to execute "
        "the workflow.*"
    )

    return "\n".join(lines)


# -- Main execution -----------------------------------------------------------

async def main(
    task_file: Path,
    output_dir: Path,
    deployment: str,
    summary_threshold: int,
    dry_run: bool = False,
) -> None:
    os.environ.setdefault("AZURE_OPENAI_ENDPOINT", AZURE_ENDPOINT)

    # =========================================================================
    # PHASE 0: Load task from markdown file
    # =========================================================================
    print("=" * 60)
    print("PHASE 0: Loading task file")
    print("=" * 60)

    if not task_file.exists():
        print(f"  ERROR: Task file not found: {task_file}")
        sys.exit(1)

    task_text = task_file.read_text(encoding="utf-8")
    print(f"  File:    {task_file}")
    print(f"  Size:    {len(task_text):,} bytes")
    print(f"  Preview: {task_text[:150].replace(chr(10), ' ')}...")
    print()

    # =========================================================================
    # PHASE 1: Initialize provider and inspect archetypes
    # =========================================================================
    print("=" * 60)
    print("PHASE 1: Initializing provider and archetype library")
    print("=" * 60)

    provider = AzureOpenAIProvider(azure_endpoint=AZURE_ENDPOINT)
    generator = TeamGenerator()
    archetype_library = ArchetypeLibrary.default()

    # Collect archetype catalog for the report
    archetype_catalog = []
    for name in archetype_library.list_archetypes():
        arch = archetype_library.get(name)
        archetype_catalog.append({
            "name": name,
            "role": arch.get("role", ""),
            "behavior_type": arch.get("behavior_type", ""),
        })

    print(f"  Endpoint:   {AZURE_ENDPOINT}")
    print(f"  Deployment: {deployment}")
    print(f"  Archetypes: {len(archetype_catalog)}")
    for arch in archetype_catalog:
        print(f"    - {arch['name']:20s}  {arch['role']:30s}  [{arch['behavior_type']}]")
    print()

    # =========================================================================
    # PHASE 2: LLM team generation
    # =========================================================================
    print("=" * 60)
    print("PHASE 2: Generating team configuration via LLM")
    print("=" * 60)

    t0 = time.time()
    generation_result = await generator.generate_team_from_llm(
        task_description=task_text,
        llm_provider=provider,
        model=deployment,
        archetype_library=archetype_library,
        auto_approve=False,
    )
    generation_elapsed = time.time() - t0

    config = generation_result.config
    print(f"  Generated in {generation_elapsed:.1f}s")
    print(f"  Team:    {config.get('team_name', 'unnamed')}")
    print(f"  Agents:  {[a['id'] for a in config.get('agents', [])]}")
    print()

    # Agent roster
    print("  Agent roster:")
    for agent in config.get("agents", []):
        print(
            f"    {agent['id']:20s}  {agent.get('role', ''):30s}  "
            f"[{agent.get('behavior_type', '')}]"
        )
    print()

    # Workflow
    print("  Workflow:")
    for step in config.get("workflow", {}).get("steps", []):
        nxt = step.get("next") or step.get("next_on_accept") or "(end)"
        print(f"    {step['agent']:20s}  [{step['type']}]  -> {nxt}")
    print()

    # Capability gaps
    if generation_result.capability_gaps:
        print(f"  Capability gaps ({len(generation_result.capability_gaps)}):")
        for gap in generation_result.capability_gaps:
            print(f"    [{gap.severity}] {gap.resource_type}:{gap.resource_id}")
            print(f"      {gap.description}")
        if generation_result.has_blocking_gaps:
            print("\n  ** Blocking gaps detected -- cannot execute.")
            return
        print()
    else:
        print("  [OK] No capability gaps")
        print()

    # New archetypes
    if generation_result.new_archetypes:
        print(f"  New archetypes ({len(generation_result.new_archetypes)}):")
        for arch in generation_result.new_archetypes:
            print(f"    {arch.get('id', '?'):20s}  {arch.get('role', '')}")
        print()

    # =========================================================================
    # PHASE 3: Build agents and workflow engine
    # =========================================================================
    print("=" * 60)
    print("PHASE 3: Building agents and workflow engine")
    print("=" * 60)

    azure_model = f"azure:{deployment}"
    for agent in config.get("agents", []):
        agent["model"] = azure_model

    # Strip tools that are not registered (the LLM may invent tools)
    for agent in config.get("agents", []):
        if agent.get("tools"):
            print(f"  Note: stripping tools from {agent['id']} (not registered)")
            agent["tools"] = []

    metrics = PipelineMetrics()
    agents, engine = generator.build(
        config,
        provider,
        model=azure_model,
        summary_threshold=summary_threshold,
    )
    engine.on_event(metrics.on_event)

    print(f"  Built {len(agents)} agents")
    print(f"  Workflow: {len(engine.steps)} steps")
    print()

    # =========================================================================
    # DRY-RUN EXIT: publish design report and stop before execution
    # =========================================================================
    if dry_run:
        print("=" * 60)
        print("DRY RUN: Skipping execution -- publishing design report")
        print("=" * 60)

        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")

        report_md = build_dry_run_report(
            task_text=task_text,
            task_file=task_file,
            archetype_catalog=archetype_catalog,
            generation_result=generation_result,
            generation_elapsed=generation_elapsed,
            config=config,
            deployment=deployment,
        )

        report_path = output_dir / f"task_pipeline_{timestamp}_dry_run.md"
        report_path.write_text(report_md, encoding="utf-8")
        print(f"  Saved: {report_path}")
        print()
        print("  Re-run without --dry-run to execute the workflow.")
        print()
        return

    # =========================================================================
    # PHASE 4: Execute the workflow
    # =========================================================================
    print("=" * 60)
    print("PHASE 4: Executing workflow")
    print("=" * 60)

    metrics.start_time = time.time()
    wf_result = await engine.execute(
        agents=agents,
        initial_state={"task": task_text},
    )
    metrics.end_time = time.time()

    exec_elapsed = metrics.end_time - metrics.start_time
    print()
    print(f"  Status:  {wf_result.status.value}")
    print(f"  Steps:   {len(wf_result.step_results)}")
    print(f"  Elapsed: {exec_elapsed:.1f}s")
    print()

    if wf_result.status == WorkflowStatus.FAILED:
        print(f"  Error: {wf_result.error}")
        return

    # Per-agent summary
    state = wf_result.state
    total_tokens = 0
    for agent_def in config.get("agents", []):
        aid = agent_def["id"]
        output = state.get(f"{aid}_output", "")
        usage = state.get(f"{aid}_usage")
        words = len(output.split()) if isinstance(output, str) else 0
        tokens = usage.get("total_tokens", 0) if usage else 0
        total_tokens += tokens
        print(f"  {aid:20s}  {words:5d} words  {tokens:5d} tokens")

    print(f"  {'TOTAL':20s}  {'':5s}        {total_tokens:5d} tokens")
    print()

    # =========================================================================
    # PHASE 5: Publish execution report + team output
    # =========================================================================
    print("=" * 60)
    print("PHASE 5: Publishing outputs")
    print("=" * 60)

    output_dir.mkdir(parents=True, exist_ok=True)

    # Generate report title via LLM
    from hiveflow.plugins.llm import LLMConfig, LLMMessage

    title_messages = [
        LLMMessage(
            role="user",
            content=(
                "Generate a short, professional document title (max 10 words) "
                "for a report on the following topic. Respond with ONLY "
                "the title, no quotes or punctuation around it.\n\n"
                f"Topic: {task_text[:500]}"
            ),
        ),
    ]
    title_config = LLMConfig(model=deployment, max_tokens=50, temperature=0.3)
    title_response = await provider.chat(title_messages, title_config)
    report_title = title_response.content.strip().strip('"').strip("'")
    print(f"  Title: {report_title}")

    timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_filename = f"task_pipeline_{timestamp}"

    # -- Execution report (custom-built markdown) --
    report_md = build_execution_report(
        task_text=task_text,
        task_file=task_file,
        archetype_catalog=archetype_catalog,
        generation_result=generation_result,
        generation_elapsed=generation_elapsed,
        config=config,
        wf_result=wf_result,
        metrics=metrics,
        deployment=deployment,
        report_title=report_title,
        output_filename=output_filename,
    )

    report_path = output_dir / f"{output_filename}_execution_report.md"
    report_path.write_text(report_md, encoding="utf-8")
    print(f"  Saved: {report_path}")

    # -- Team content output (via ResultPayload + publisher) --
    from hiveflow.core.result_payload import ResultPayload
    from hiveflow.plugins.publishers import MarkdownPublisher, PublisherRegistry

    payload = ResultPayload.from_workflow_result(wf_result, title=report_title)

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

    content_filename = f"{output_filename}_team_output"
    paths = await registry.publish_all(
        payload,
        output_dir=str(output_dir),
        formats=formats,
        filename=content_filename,
    )

    for p in paths:
        print(f"  Saved: {p}")

    # Also produce DOCX of the execution report if pypandoc available
    try:
        import pypandoc
        docx_report_path = output_dir / f"{output_filename}_execution_report.docx"
        pypandoc.convert_text(
            report_md,
            "docx",
            format="md",
            outputfile=str(docx_report_path),
        )
        print(f"  Saved: {docx_report_path}")
    except ImportError:
        pass
    except Exception as e:
        print(f"  Warning: DOCX execution report failed: {e}")

    print()
    print("=" * 60)
    print("DONE")
    print("=" * 60)
    print()
    print(f"  Execution report: {report_path}")
    print(f"  Team output:      {output_dir / (content_filename + '.md')}")
    print()


def cli() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Task-driven pipeline: read task from .md file, "
            "generate team via LLM, execute, publish audit trail"
        ),
    )
    parser.add_argument(
        "--task-file",
        type=Path,
        default=Path(__file__).parent / "tasks" / "sample_task.md",
        help="Path to a Markdown file describing the task (default: tasks/sample_task.md)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("./output/task_driven"),
        help="Directory for output files (default: ./output/task_driven)",
    )
    parser.add_argument(
        "--deployment",
        default=os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini"),
        help="Azure OpenAI deployment name (default: gpt-4o-mini)",
    )
    parser.add_argument(
        "--summary-threshold",
        type=int,
        default=4000,
        help="Word count below which agent outputs pass through unsummarized (default: 4000)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Generate team via LLM and publish design report, but skip workflow execution",
    )
    args = parser.parse_args()
    asyncio.run(main(
        task_file=args.task_file,
        output_dir=args.output_dir,
        deployment=args.deployment,
        summary_threshold=args.summary_threshold,
        dry_run=args.dry_run,
    ))


if __name__ == "__main__":
    cli()
