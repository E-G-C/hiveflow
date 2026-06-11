#!/usr/bin/env python3
"""Example 16: Large-input pipeline — transcript + instructions → preprocessed auto-team → output.

End-to-end demonstration of processing a document that exceeds normal context
limits. Combines task preprocessing with LLM-generated teams:

  1. Load a task file (instructions) and a data file (e.g. a 16K-word transcript)
  2. TaskPreprocessor detects the combined input exceeds the threshold
  3. Instructions are separated from data; data is chunked and summarized
  4. LLM generates a team configuration tailored to the task
  5. The team executes with preprocessing-aware context routing:
     - Orchestrator receives instructions + data summary + chunk manifest
     - Workers receive instructions + their assigned chunk content
     - Final writer receives summaries of all prior agents
  6. Results are published to Markdown (+ DOCX if pypandoc available)

This is the pattern for any "document in → structured output out" pipeline
where the input document may be very large.

Uses Azure OpenAI with Entra ID RBAC authentication.

Usage:
    # Default: uses bundled transcript task (td.md + aw.txt)
    uv run python examples/agents_and_teams/16_large_input_processing.py

    # Custom files:
    uv run python examples/agents_and_teams/16_large_input_processing.py \
        --task-file path/to/instructions.md \
        --data-file path/to/large_document.txt

    # Dry run (preprocess + team generation only, no execution):
    uv run python examples/agents_and_teams/16_large_input_processing.py --dry-run

    # Different deployment:
    AZURE_OPENAI_DEPLOYMENT=gpt-4o \
        uv run python examples/agents_and_teams/16_large_input_processing.py
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
from hiveflow.core.preprocessing import PreprocessingConfig, TaskPreprocessor
from hiveflow.core.teams import ArchetypeLibrary
from hiveflow.plugins.llm import LLMConfig, LLMMessage
from hiveflow.plugins.llm.azure_provider import AzureOpenAIProvider

AZURE_ENDPOINT = "https://foundry-aisbx-we.cognitiveservices.azure.com"
DEFAULT_TASK_FILE = Path(__file__).parent / "tasks" / "td.md"
DEFAULT_DATA_FILE = Path(__file__).parent / "tasks" / "aw.txt"


# -- Event handler ------------------------------------------------------------

def on_event(event_type: str, agent_id: str, data: dict[str, Any]) -> None:
    """Print live progress for each workflow step."""
    if event_type == "step_start":
        step_type = data.get("step_type", "")
        print(f"  > {agent_id} ({step_type})...", flush=True)
    elif event_type == "step_complete":
        words = data.get("word_count", 0)
        print(f"  * {agent_id} done ({words} words)", flush=True)
    elif event_type == "step_error":
        print(f"  X {agent_id} FAILED: {data.get('error', '')}", flush=True)
    elif event_type == "summary_generated":
        length = data.get("summary_length", 0)
        print(f"    -> summary ({length} words)", flush=True)
    elif event_type == "assembly_complete":
        sections = data.get("num_sections", 0)
        words = data.get("total_words", 0)
        print(f"  ! Assembled: {sections} sections, {words} words", flush=True)


# -- Main execution -----------------------------------------------------------

async def main(
    task_file: Path,
    data_file: Path | None,
    deployment: str,
    dry_run: bool = False,
) -> None:
    os.environ.setdefault("AZURE_OPENAI_ENDPOINT", AZURE_ENDPOINT)

    provider = AzureOpenAIProvider(azure_endpoint=AZURE_ENDPOINT)
    azure_model = f"azure:{deployment}"

    print("=" * 70)
    print("HIVEFLOW LARGE-INPUT PROCESSING PIPELINE")
    print("=" * 70)
    print(f"  Endpoint:   {AZURE_ENDPOINT}")
    print(f"  Deployment: {deployment}")
    print()

    # =========================================================================
    # PHASE 0: Load the task + data
    # =========================================================================
    print("=" * 70)
    print("PHASE 0: Loading input files")
    print("=" * 70)

    if not task_file.exists():
        print(f"  ERROR: Task file not found: {task_file}")
        sys.exit(1)

    task_text = task_file.read_text(encoding="utf-8").strip()
    print(f"  Task file:  {task_file.name} ({len(task_text.split()):,} words)")

    if data_file and data_file.exists():
        data_content = data_file.read_text(encoding="utf-8")
        data_words = len(data_content.split())
        task_text += f"\n\n---\n## Data\n\n{data_content}"
        print(f"  Data file:  {data_file.name} ({data_words:,} words)")

    total_words = len(task_text.split())
    print(f"  Combined:   {total_words:,} words")
    print()

    # =========================================================================
    # PHASE 1: Preprocess the large input
    # =========================================================================
    print("=" * 70)
    print("PHASE 1: Task preprocessing")
    print("=" * 70)

    pp_config = PreprocessingConfig()
    preprocessor = TaskPreprocessor(
        llm_provider=provider,
        model=azure_model,
        config=pp_config,
    )

    state: dict[str, Any] = {"task": task_text}
    agent_count = 4  # estimate for team generation

    t0 = time.time()
    state = await preprocessor.preprocess(state, agent_count=agent_count)
    pp_elapsed = time.time() - t0

    print(f"  Preprocessing completed in {pp_elapsed:.1f}s")

    if "task_instructions" in state:
        instructions = state["task_instructions"]
        summary = state.get("task_data_summary", "")
        manifest = state.get("task_data_manifest", {})
        chunks = state.get("task_data", [])

        print(f"  Status: ACTIVATED")
        print(f"    Instructions:    {len(instructions.split()):,} words")
        print(f"    Data summary:    {len(summary.split()):,} words")
        print(f"    Chunks:          {len(chunks)}")
        print(f"    Boundary method: {manifest.get('boundary_method', '?')}")
        print(f"    Threshold:       {manifest.get('effective_threshold', '?'):,} words")
        print()

        # Show chunk manifest
        print("  Chunk manifest:")
        for chunk in chunks:
            cid = chunk["chunk_id"] if isinstance(chunk, dict) else chunk.chunk_id
            words = chunk["words"] if isinstance(chunk, dict) else chunk.words
            hint = chunk.get("topic_hint", "") if isinstance(chunk, dict) else chunk.topic_hint
            print(f"    {cid}: {words:,} words -- {hint[:70]}")

        # Context reduction stats
        planner_ctx = len(instructions.split()) + len(summary.split())
        reduction = (1 - planner_ctx / total_words) * 100
        print()
        print(f"  Context reduction: {total_words:,} -> {planner_ctx:,} words ({reduction:.0f}% reduction)")
    else:
        print(f"  Status: SKIPPED (input below threshold at {total_words:,} words)")
    print()

    # =========================================================================
    # PHASE 2: LLM team generation
    # =========================================================================
    print("=" * 70)
    print("PHASE 2: LLM team generation")
    print("=" * 70)

    generator = TeamGenerator()
    archetype_library = ArchetypeLibrary.default()

    archetype_names = archetype_library.list_archetypes()
    print(f"  Archetypes available: {len(archetype_names)}")

    # Use instructions (if preprocessed) for team generation so the LLM
    # designs based on the task itself, not the raw data
    gen_task = state.get("task_instructions", state["task"])[:3000]

    t1 = time.time()
    gen_result = await generator.generate_team_from_llm(
        task_description=gen_task,
        llm_provider=provider,
        model=deployment,
        archetype_library=archetype_library,
        auto_approve=False,
    )
    gen_elapsed = time.time() - t1

    config = gen_result.config
    print(f"  Generated in {gen_elapsed:.1f}s")
    print(f"  Team: {config.get('team_name', 'unnamed')}")
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

    if gen_result.capability_gaps:
        print(f"  Capability gaps: {len(gen_result.capability_gaps)}")
        for gap in gen_result.capability_gaps:
            print(f"    [{gap.severity}] {gap.resource_type}:{gap.resource_id}")
        if gen_result.has_blocking_gaps:
            print("\n  ** Blocking gaps -- cannot execute.")
            return
        print()

    # =========================================================================
    # DRY-RUN EXIT
    # =========================================================================
    if dry_run:
        print("=" * 70)
        print("DRY RUN -- stopping before execution")
        print("=" * 70)
        print()
        print("  Rerun without --dry-run to execute the workflow.")
        print(f"  Config preview:")
        print(json.dumps(config, indent=2)[:1500])
        return

    # =========================================================================
    # PHASE 3: Build and execute
    # =========================================================================
    print("=" * 70)
    print("PHASE 3: Building agents and executing workflow")
    print("=" * 70)

    # Prepare agents
    for agent in config.get("agents", []):
        agent["model"] = azure_model
        if agent.get("tools"):
            agent["tools"] = []

    agents, engine = generator.build(
        config,
        provider,
        model=azure_model,
        summary_threshold=4000,
    )
    # Do NOT attach preprocessor -- we already ran it manually in PHASE 1.
    # Passing the pre-processed state avoids a redundant second preprocessing
    # pass (extra LLM calls for boundary detection + summarization).
    engine.on_event(on_event)

    print(f"  Built {len(agents)} agents, {len(engine.steps)} steps")
    print(f"  Task preprocessor: reusing PHASE 1 results")
    print()

    t2 = time.time()
    wf_result = await engine.execute(
        agents=agents,
        initial_state=state,
    )
    exec_elapsed = time.time() - t2

    print()
    print(f"  Status:  {wf_result.status.value}")
    print(f"  Steps:   {len(wf_result.step_results)}")
    print(f"  Elapsed: {exec_elapsed:.1f}s")
    print()

    if wf_result.status == WorkflowStatus.FAILED:
        print(f"  Error: {wf_result.error}")
        return

    # =========================================================================
    # PHASE 4: Results + Publish
    # =========================================================================
    print("=" * 70)
    print("PHASE 4: Results + Publishing")
    print("=" * 70)

    result_state = wf_result.state

    total_tokens = 0
    for agent_def in config.get("agents", []):
        aid = agent_def["id"]
        output = result_state.get(f"{aid}_output", "")
        usage = result_state.get(f"{aid}_usage")
        words = len(output.split()) if isinstance(output, str) else 0
        tokens = usage.get("total_tokens", 0) if usage else 0
        total_tokens += tokens
        print(f"  {aid:20s}  {words:>5d} words  {tokens:>5d} tokens")

    print(f"  {'TOTAL':20s}  {'':>5s}        {total_tokens:>5d} tokens")
    print()

    # -- Generate title via LLM -----------------------------------------------
    title_messages = [
        LLMMessage(
            role="user",
            content=(
                "Generate a short, professional document title (max 10 words) "
                "for a report on the following topic. Respond with ONLY the "
                "title, no quotes.\n\n"
                f"Topic: {gen_task[:500]}"
            ),
        ),
    ]
    title_config = LLMConfig(model=deployment, max_tokens=50, temperature=0.3)
    title_response = await provider.chat(title_messages, title_config)
    report_title = title_response.content.strip().strip('"').strip("'")
    print(f"  Title: {report_title}")

    # -- Build execution report (Markdown) ------------------------------------
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    agents_list = config.get("agents", [])
    workflow_steps = config.get("workflow", {}).get("steps", [])

    rpt: list[str] = []
    rpt.append(f"# Execution Report: {report_title}")
    rpt.append("")
    rpt.append(f"**Generated:** {now}  ")
    rpt.append(f"**Model:** {deployment}  ")
    rpt.append(f"**Input:** {total_words:,} words  ")
    rpt.append(f"**Status:** {wf_result.status.value}")
    rpt.append("")
    rpt.append("---")
    rpt.append("")

    # Preprocessing section
    rpt.append("## 1. Preprocessing")
    rpt.append("")
    if "task_instructions" in state:
        instructions = state["task_instructions"]
        summary = state.get("task_data_summary", "")
        manifest = state.get("task_data_manifest", {})
        chunks = state.get("task_data", [])
        planner_ctx = len(instructions.split()) + len(summary.split())
        reduction = (1 - planner_ctx / total_words) * 100

        rpt.append("| Parameter | Value |")
        rpt.append("|-----------|-------|")
        rpt.append(f"| Status | **ACTIVATED** |")
        rpt.append(f"| Boundary method | {manifest.get('boundary_method', '?')} |")
        rpt.append(f"| Threshold | {manifest.get('effective_threshold', '?'):,} words |")
        rpt.append(f"| Instructions | {len(instructions.split()):,} words |")
        rpt.append(f"| Data summary | {len(summary.split()):,} words |")
        rpt.append(f"| Chunks | {len(chunks)} |")
        rpt.append(f"| Context reduction | {reduction:.0f}% ({total_words:,} → {planner_ctx:,} words) |")
        rpt.append(f"| Time | {pp_elapsed:.1f}s |")
        rpt.append("")
        rpt.append("### Data Summary")
        rpt.append("")
        rpt.append(f"> {summary}")
        rpt.append("")
        rpt.append("### Chunk Manifest")
        rpt.append("")
        rpt.append("| Chunk | Words | Topic |")
        rpt.append("|-------|------:|-------|")
        for chunk in chunks:
            cid = chunk["chunk_id"] if isinstance(chunk, dict) else chunk.chunk_id
            cw = chunk["words"] if isinstance(chunk, dict) else chunk.words
            hint = chunk.get("topic_hint", "") if isinstance(chunk, dict) else chunk.topic_hint
            rpt.append(f"| {cid} | {cw:,} | {hint} |")
        rpt.append("")
    else:
        rpt.append(f"Preprocessing **skipped** — input ({total_words:,} words) below threshold.")
        rpt.append("")

    # Team design
    rpt.append("## 2. LLM Team Design")
    rpt.append("")
    rpt.append(f"**Team:** {config.get('team_name', 'unnamed')}  ")
    rpt.append(f"**Generation time:** {gen_elapsed:.1f}s")
    rpt.append("")
    rpt.append("### Agent Roster")
    rpt.append("")
    rpt.append("| Agent | Role | Behavior | System Prompt (excerpt) |")
    rpt.append("|-------|------|----------|------------------------|")
    for agent_def in agents_list:
        prompt_excerpt = agent_def.get("system_prompt", "")[:80].replace("|", "\\|").replace("\n", " ")
        rpt.append(
            f"| {agent_def['id']} | {agent_def.get('role', '')} | "
            f"{agent_def.get('behavior_type', '')} | {prompt_excerpt}... |"
        )
    rpt.append("")
    rpt.append("### Workflow")
    rpt.append("")
    rpt.append("```")
    graph_parts = [f"{s['agent']} [{s['type']}]" for s in workflow_steps]
    rpt.append(" -> ".join(graph_parts))
    rpt.append("```")
    rpt.append("")

    # Execution results
    rpt.append("## 3. Execution Results")
    rpt.append("")
    rpt.append(f"**Execution time:** {exec_elapsed:.1f}s")
    rpt.append("")
    rpt.append("| Agent | Words | Tokens |")
    rpt.append("|-------|------:|-------:|")
    for agent_def in agents_list:
        aid = agent_def["id"]
        output = result_state.get(f"{aid}_output", "")
        usage = result_state.get(f"{aid}_usage")
        w = len(output.split()) if isinstance(output, str) else 0
        t = usage.get("total_tokens", 0) if usage else 0
        rpt.append(f"| {aid} | {w:,} | {t:,} |")
    rpt.append(f"| **TOTAL** | | **{total_tokens:,}** |")
    rpt.append("")

    # Agent outputs
    rpt.append("## 4. Agent Outputs")
    rpt.append("")
    for agent_def in agents_list:
        aid = agent_def["id"]
        output = result_state.get(f"{aid}_output", "")
        if not output:
            continue
        role = agent_def.get("role", aid)
        rpt.append(f"### {aid} ({role})")
        rpt.append("")
        if isinstance(output, str) and len(output) > 3000:
            rpt.append(output[:3000])
            rpt.append("")
            rpt.append(f"*... truncated ({len(output):,} chars total)*")
        else:
            rpt.append(str(output))
        rpt.append("")

    # Final output
    final = result_state.get("final_output", "")
    if not final:
        last_agent = config["agents"][-1]["id"]
        final = result_state.get(f"{last_agent}_output", "")

    rpt.append("## 5. Final Output")
    rpt.append("")
    if final:
        rpt.append(final)
    else:
        rpt.append("*No final output assembled.*")
    rpt.append("")

    # Process metadata
    rpt.append("## 6. Process Metadata")
    rpt.append("")
    rpt.append("| Property | Value |")
    rpt.append("|----------|-------|")
    rpt.append(f"| Azure endpoint | {AZURE_ENDPOINT} |")
    rpt.append(f"| Deployment | {deployment} |")
    rpt.append(f"| Task file | `{task_file}` |")
    rpt.append(f"| Data file | `{data_file}` |")
    rpt.append(f"| Input words | {total_words:,} |")
    rpt.append(f"| Preprocessing time | {pp_elapsed:.1f}s |")
    rpt.append(f"| Team generation time | {gen_elapsed:.1f}s |")
    rpt.append(f"| Execution time | {exec_elapsed:.1f}s |")
    rpt.append(f"| Total tokens | {total_tokens:,} |")
    rpt.append(f"| Agents | {len(agents_list)} |")
    rpt.append(f"| Workflow steps | {len(workflow_steps)} |")
    rpt.append("")

    report_md = "\n".join(rpt)

    # -- Publish files ---------------------------------------------------------
    from hiveflow.core.result_payload import ResultPayload
    from hiveflow.plugins.publishers import MarkdownPublisher, PublisherRegistry
    from hiveflow.plugins.publishers.json_publisher import JSONPublisher

    payload = ResultPayload.from_workflow_result(wf_result, title=report_title)

    timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_dir = Path("./output/large_input")
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"processed_{timestamp}"

    # Register publishers
    pub_registry = PublisherRegistry(drop_in_dir=None)
    pub_registry.register(MarkdownPublisher())
    pub_registry.register(JSONPublisher())

    formats = ["markdown", "json"]

    _has_pandoc = False
    try:
        import pypandoc
        pypandoc.get_pandoc_version()
        _has_pandoc = True
    except (ImportError, OSError, FileNotFoundError, AttributeError):
        pass

    if _has_pandoc:
        try:
            from hiveflow.plugins.publishers.docx_publisher import DOCXPublisher
            pub_registry.register(DOCXPublisher())
            formats.append("docx")
        except ImportError:
            pass
        try:
            from hiveflow.plugins.publishers.html_publisher import HTMLPublisher
            pub_registry.register(HTMLPublisher())
            formats.append("html")
        except ImportError:
            pass

    if not _has_pandoc:
        print("  Note: pandoc not found -- skipping DOCX and HTML output")

    # Publish team output
    content_filename = f"{filename}_team_output"
    paths = await pub_registry.publish_all(
        payload,
        output_dir=str(output_dir),
        formats=formats,
        filename=content_filename,
    )

    for p in paths:
        print(f"  Saved: {p}")

    # Publish execution report
    report_path = output_dir / f"{filename}_execution_report.md"
    report_path.write_text(report_md, encoding="utf-8")
    print(f"  Saved: {report_path}")

    if _has_pandoc:
        try:
            docx_report = output_dir / f"{filename}_execution_report.docx"
            pypandoc.convert_text(
                report_md, "docx", format="md", outputfile=str(docx_report),
            )
            print(f"  Saved: {docx_report}")
        except Exception as e:
            print(f"  Warning: DOCX report failed: {e}")

    print()

    # =========================================================================
    # Summary
    # =========================================================================
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"  Input:              {total_words:,} words")
    print(f"  Preprocessing:      {pp_elapsed:.1f}s")
    if "task_data" in state:
        print(f"  Chunks:             {len(state.get('task_data', []))}")
        print(f"  Boundary method:    {state.get('task_data_manifest', {}).get('boundary_method', 'N/A')}")
    print(f"  Team generation:    {gen_elapsed:.1f}s ({config.get('team_name', '?')})")
    print(f"  Workflow execution: {exec_elapsed:.1f}s")
    print(f"  Total tokens:       {total_tokens:,}")
    print(f"  Status:             {wf_result.status.value}")
    print(f"  Output formats:     {', '.join(formats)}")
    print(f"  Output dir:         {output_dir}")
    print()


def cli() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Large-input pipeline: task file + data file → preprocessing → "
            "LLM team generation → execution → published output"
        ),
    )
    parser.add_argument(
        "--task-file",
        type=Path,
        default=DEFAULT_TASK_FILE,
        help=f"Path to task/instructions file (default: {DEFAULT_TASK_FILE.name})",
    )
    parser.add_argument(
        "--data-file",
        type=Path,
        default=DEFAULT_DATA_FILE,
        help=f"Path to data file to process (default: {DEFAULT_DATA_FILE.name})",
    )
    parser.add_argument(
        "--deployment",
        default=os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini"),
        help="Azure OpenAI deployment name (default: gpt-4o-mini)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Preprocess + generate team only, skip workflow execution",
    )
    args = parser.parse_args()
    asyncio.run(main(
        task_file=args.task_file,
        data_file=args.data_file,
        deployment=args.deployment,
        dry_run=args.dry_run,
    ))


if __name__ == "__main__":
    cli()
