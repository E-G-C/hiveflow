#!/usr/bin/env python3
"""Example 15: Task preprocessing — automatic large-input chunking and summarization.

Demonstrates the task preprocessing pipeline with a real document-processing
use case end to end:

  1. A large task (instructions from a prompt file + a 16K-word transcript)
     is submitted as a single combined input.
  2. TaskPreprocessor detects the input exceeds the model-derived threshold.
  3. Boundary detection separates instructions from data.
  4. Data is chunked into model-appropriate segments.
  5. An LLM generates a compact summary and manifest of the chunks.
  6. The original (potentially huge) instructions are distilled into a concise
     worker directive via LLM, so each worker gets focused guidance.
  7. Workers fan out over ``task_data`` (the actual chunks), each receiving
     the distilled instructions + their assigned chunk content.
  8. A writer agent synthesizes all worker outputs into a final document.
  9. Output is published to Markdown, JSON, and (if pandoc available) DOCX/HTML.

Uses Azure OpenAI with Entra ID RBAC authentication.

Usage:
    # Default: uses bundled transcript task (td.md + aw.txt)
    uv run python examples/agents_and_teams/15_task_preprocessing.py

    # Use synthetic data instead (no external files needed):
    uv run python examples/agents_and_teams/15_task_preprocessing.py --synthetic

    # Different deployment:
    AZURE_OPENAI_DEPLOYMENT=gpt-4o \\
        uv run python examples/agents_and_teams/15_task_preprocessing.py
"""

import argparse
import asyncio
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hiveflow.core.agent import Agent, AgentBehaviorType
from hiveflow.core.preprocessing import (
    PreprocessingConfig,
    TaskPreprocessor,
)
from hiveflow.core.summarizer import SummaryGenerator
from hiveflow.core.workflow import WorkflowEngine, WorkflowStatus, WorkflowStep
from hiveflow.plugins.llm import LLMConfig, LLMMessage

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
        print(f"  * {agent_id} done", flush=True)
    elif event_type == "step_error":
        print(f"  X {agent_id} FAILED: {data.get('error', '')}", flush=True)
    elif event_type == "summary_generated":
        length = data.get("summary_length", 0)
        print(f"    -> summary generated ({length} words)", flush=True)
    elif event_type == "assembly_complete":
        sections = data.get("num_sections", 0)
        words = data.get("total_words", 0)
        print(f"  ! Assembled: {sections} sections, {words} words", flush=True)


# -- Synthetic large task generator -------------------------------------------

def generate_synthetic_task() -> str:
    """Generate a ~20K-word synthetic task with instructions + data section.

    Produces a fake meeting transcript in WEBVTT format so the preprocessing
    pipeline exercises the same boundary detection as the real transcript files.
    """
    instructions = (
        "Analyze the following meeting transcript and produce a professional\n"
        "documentation report. The report should include:\n\n"
        "1. An executive summary of the meeting topics\n"
        "2. Per-topic detailed analysis sections\n"
        "3. A table of key decisions and action items\n"
        "4. Strategic recommendations based on the discussion\n\n"
        "Structure the report with clear headings, tables where appropriate,\n"
        "and a consolidated recommendations section.\n"
    )

    topics = [
        ("cloud migration", "migrating from on-premise to Azure cloud"),
        ("API redesign", "restructuring the REST API for v3"),
        ("security audit", "quarterly security review findings"),
        ("hiring plan", "engineering headcount for Q2"),
        ("performance tuning", "database query optimization"),
        ("onboarding portal", "new employee onboarding system"),
        ("CI/CD pipeline", "improving build and deployment automation"),
        ("customer feedback", "NPS survey results and action plan"),
    ]

    speakers = ["Alex", "Jordan", "Morgan", "Taylor", "Casey"]

    data_lines = ["\n---\n## Data\n\nWEBVTT\n"]
    word_count = 0
    ts_seconds = 0

    while word_count < 18000:
        topic_name, topic_desc = random.choice(topics)
        num_exchanges = random.randint(8, 15)
        for _ in range(num_exchanges):
            speaker = random.choice(speakers)
            start_ts = f"{ts_seconds // 3600:02d}:{(ts_seconds % 3600) // 60:02d}:{ts_seconds % 60:02d}.000"
            duration = random.randint(5, 25)
            ts_seconds += duration
            end_ts = f"{ts_seconds // 3600:02d}:{(ts_seconds % 3600) // 60:02d}:{ts_seconds % 60:02d}.000"

            utterances = [
                f"Regarding the {topic_name} initiative, {topic_desc} is progressing well.",
                f"We need to finalize the {topic_name} timeline before the end of the sprint.",
                f"The {topic_name} work has some blockers. We should discuss the dependencies.",
                f"I've reviewed the {topic_name} proposal and have some feedback on the approach.",
                f"From a budget perspective, {topic_name} requires additional resources.",
                f"The team has been working on {topic_name} and completed the first milestone.",
                f"Our metrics show the {topic_name} effort is tracking ahead of schedule.",
                f"We need stakeholder sign-off on {topic_name} before moving to the next phase.",
            ]
            text = random.choice(utterances)
            detail = (
                f" The current status shows {random.randint(40, 95)}% completion. "
                f"We have {random.randint(2, 8)} team members assigned. "
                f"The estimated budget impact is ${random.randint(10, 500) * 1000:,}. "
                f"Key stakeholders include the engineering and product teams. "
                f"The priority level is {'high' if random.random() > 0.5 else 'medium'}."
            )
            text += detail
            word_count += len(text.split())

            data_lines.append(f"\n{start_ts} --> {end_ts}")
            data_lines.append(f"<v {speaker}>{text}</v>")

    return instructions + "\n".join(data_lines)


# -- Instruction distillation -------------------------------------------------

async def distill_instructions(
    provider: Any,
    model: str,
    full_instructions: str,
    data_summary: str,
) -> str:
    """Use an LLM to distill long instructions into a concise worker directive.

    When the original instructions are very long (e.g., a 4000-word prompt
    template with extensive formatting rules and examples), workers can't
    effectively follow them alongside large data chunks. This distills the
    instructions into a focused 200-300 word directive.
    """
    messages = [
        LLMMessage(
            role="system",
            content=(
                "You are a task simplifier. Given a long set of instructions "
                "and a summary of the data to be processed, produce a concise "
                "directive (200-300 words max) that captures the CORE task. "
                "Focus on: what the output should be, what format to use, "
                "and the key quality rules. Strip out examples, meta-commentary, "
                "and formatting minutiae. Write in imperative mood."
            ),
        ),
        LLMMessage(
            role="user",
            content=(
                f"## Original instructions ({len(full_instructions.split())} words):\n\n"
                f"{full_instructions[:6000]}\n\n"
                f"## Data summary:\n{data_summary}\n\n"
                "Distill into a concise worker directive."
            ),
        ),
    ]
    # Strip azure: prefix for direct provider calls
    raw_model = model.split(":", 1)[-1] if ":" in model else model
    config = LLMConfig(model=raw_model, max_tokens=500, temperature=0.2)
    response = await provider.chat(messages, config)
    return response.content.strip()


# -- Main execution -----------------------------------------------------------

async def main(
    task_file: Path,
    data_file: Path | None,
    deployment: str,
    use_synthetic: bool,
) -> None:
    os.environ.setdefault("AZURE_OPENAI_ENDPOINT", AZURE_ENDPOINT)

    from hiveflow.plugins.llm.azure_provider import AzureOpenAIProvider

    provider = AzureOpenAIProvider(azure_endpoint=AZURE_ENDPOINT)
    azure_model = f"azure:{deployment}"

    print("=" * 70)
    print("HIVEFLOW TASK PREPROCESSING EXAMPLE")
    print("=" * 70)
    print(f"  Endpoint:   {AZURE_ENDPOINT}")
    print(f"  Deployment: {deployment}")
    print()

    # =========================================================================
    # PHASE 1: Load or generate the task
    # =========================================================================
    print("=" * 70)
    print("PHASE 1: Loading task")
    print("=" * 70)

    if use_synthetic:
        print("  Using synthetic meeting transcript data")
        task_text = generate_synthetic_task()
    elif task_file.exists():
        task_text = task_file.read_text(encoding="utf-8").strip()
        print(f"  Task file: {task_file.name} ({len(task_text.split()):,} words)")

        if data_file and data_file.exists():
            data_content = data_file.read_text(encoding="utf-8")
            task_text += f"\n\n---\n## Data\n\n{data_content}"
            print(f"  Data file: {data_file.name} ({len(data_content.split()):,} words)")
    else:
        print(f"  Task file not found: {task_file}")
        print("  Falling back to synthetic data")
        task_text = generate_synthetic_task()

    word_count = len(task_text.split())
    print(f"  Combined input: {word_count:,} words")
    print()

    # =========================================================================
    # PHASE 2: Preprocess the input (once, manually)
    # =========================================================================
    print("=" * 70)
    print("PHASE 2: Running TaskPreprocessor")
    print("=" * 70)

    pp_config = PreprocessingConfig()
    preprocessor = TaskPreprocessor(
        llm_provider=provider,
        model=azure_model,
        config=pp_config,
    )

    state: dict[str, Any] = {"task": task_text}
    agent_count = 3

    t0 = time.time()
    state = await preprocessor.preprocess(state, agent_count=agent_count)
    preprocess_elapsed = time.time() - t0

    print(f"  Elapsed: {preprocess_elapsed:.1f}s")
    print()

    pp_activated = "task_instructions" in state
    original_instructions = state.get("task_instructions", "")
    data_summary = state.get("task_data_summary", "")

    if pp_activated:
        manifest = state.get("task_data_manifest", {})
        chunks = state.get("task_data", [])

        print("  Preprocessing ACTIVATED:")
        print(f"    Instructions: {len(original_instructions.split()):,} words")
        print(f"    Data summary: {len(data_summary.split()):,} words")
        print(f"    Chunks:       {len(chunks)}")
        if manifest:
            print(f"    Boundary:     {manifest.get('boundary_method', '?')}")
            print(f"    Threshold:    {manifest.get('effective_threshold', '?'):,} words")
        print()

        print("  Chunk manifest:")
        for chunk in chunks:
            cid = chunk["chunk_id"] if isinstance(chunk, dict) else chunk.chunk_id
            cw = chunk["words"] if isinstance(chunk, dict) else chunk.words
            hint = chunk.get("topic_hint", "") if isinstance(chunk, dict) else chunk.topic_hint
            hint_display = hint.replace("\n", " ").strip()[:80] if hint else "(no hint)"
            print(f"    {cid}: {cw:,} words -- {hint_display}")
        print()

        planner_words = len(original_instructions.split()) + len(data_summary.split())
        reduction = (1 - planner_words / word_count) * 100
        print(f"  Context reduction: {reduction:.0f}%")
        print(f"    Original: {word_count:,} -> Planner sees: {planner_words:,} words")
    else:
        print("  Preprocessing SKIPPED (task below threshold)")
        print(f"    Task passes through unchanged at {word_count:,} words")
    print()

    # =========================================================================
    # PHASE 3: Distill instructions + build pipeline
    # =========================================================================
    print("=" * 70)
    print("PHASE 3: Building agent pipeline")
    print("=" * 70)

    # If instructions are very long, distill them for workers.
    # The planner keeps the full instructions (it needs the detail to plan),
    # but workers get a concise directive so they focus on extracting content
    # from their data chunk rather than getting overwhelmed by meta-rules.
    worker_instructions = original_instructions
    if pp_activated and len(original_instructions.split()) > 500:
        print("  Distilling instructions for workers...", flush=True)
        worker_instructions = await distill_instructions(
            provider, azure_model, original_instructions, data_summary,
        )
        print(f"    Original: {len(original_instructions.split()):,} words")
        print(f"    Distilled: {len(worker_instructions.split()):,} words")
        print()
        # Replace instructions in state so workers get the distilled version.
        # The planner already ran (sequential, first step) so it saw the full version
        # via its own context.
        state["task_instructions"] = worker_instructions
        state["task"] = worker_instructions

    planner = Agent(
        agent_id="planner",
        role="Document Planner",
        system_prompt=(
            "You are a document planning expert. You receive instructions for "
            "a documentation task along with a summary of data that has been "
            "split into chunks.\n\n"
            "Create a brief plan for the final document: what sections should "
            "it have, and what approach should each chunk-worker take.\n\n"
            "Respond with ONLY a JSON object:\n"
            '{"sections": ["Section 1: ...", "Section 2: ..."], '
            '"approach": "brief description"}'
        ),
        behavior_type=AgentBehaviorType.ORCHESTRATOR,
        model=azure_model,
        llm_provider=provider,
        llm_config=LLMConfig(model=azure_model, max_tokens=2000),
        output_type="structured_data",
    )

    worker = Agent(
        agent_id="worker",
        role="Chunk Processor",
        system_prompt=(
            "You are a technical writer. You will receive a task directive and "
            "one chunk of raw data (e.g., a meeting transcript in WEBVTT or "
            "similar format).\n\n"
            "YOUR JOB:\n"
            "1. READ the raw data carefully and extract ALL substantive content.\n"
            "2. IGNORE formatting artifacts (timestamps, speaker tags like "
            "'<v Name>', WEBVTT headers, UUIDs).\n"
            "3. TRANSFORM the extracted content into clear, professional "
            "Markdown documentation following the task directive.\n"
            "4. Include headings, tables, and bullet points as appropriate.\n"
            "5. Capture ALL topics, decisions, and action items from the data.\n"
            "6. Do NOT fabricate content -- only document what is in the chunk.\n"
            "7. Be THOROUGH -- extract every distinct topic, example, demo, "
            "and technical detail mentioned. Do not summarize at a high level.\n\n"
            "Write 1500-3000 words depending on content density. "
            "More content in the chunk means more detail in your output."
        ),
        behavior_type=AgentBehaviorType.LLM_ONLY,
        model=azure_model,
        llm_provider=provider,
        llm_config=LLMConfig(model=azure_model, max_tokens=8192),
    )

    writer = Agent(
        agent_id="writer",
        role="Document Synthesizer",
        system_prompt=(
            "You are a senior technical writer producing a FINAL document. "
            "You receive outputs from multiple workers who each processed a "
            "portion of the source data.\n\n"
            "YOUR JOB:\n"
            "1. MERGE all worker outputs into ONE coherent document.\n"
            "2. REMOVE duplication between chunks (same topic may appear twice).\n"
            "3. ADD an executive summary at the top.\n"
            "4. ORGANIZE into logical sections with clear headings.\n"
            "5. ADD a 'Decisions and Action Items' section if applicable.\n"
            "6. Ensure consistent tone and terminology throughout.\n"
            "7. PRESERVE technical depth -- include specific examples, demos, "
            "tool names, code snippets, and concrete details from the workers.\n"
            "8. Do NOT over-summarize. Keep the detail from worker outputs.\n\n"
            "IMPORTANT formatting rules:\n"
            "- Output raw Markdown directly. Do NOT wrap the output in a "
            "code fence (no ```markdown blocks).\n"
            "- Start with a # heading. No preamble or meta commentary.\n"
            "- Target 2000-4000 words. Be comprehensive."
        ),
        behavior_type=AgentBehaviorType.LLM_ONLY,
        model=azure_model,
        llm_provider=provider,
        llm_config=LLMConfig(model=azure_model, max_tokens=8192),
        context_recency_window=3,
    )

    agents = {"planner": planner, "worker": worker}

    # Two-step pipeline: planner plans, workers fan out over data chunks.
    # The writer/synthesis step is done MANUALLY after the engine finishes,
    # so we can feed it the full worker outputs directly (not through the
    # engine's lossy summary/outline context propagation).
    steps = [
        WorkflowStep(
            agent="planner",
            step_type="sequential",
            next_step="worker",
            context_ttl=2,
        ),
        WorkflowStep(
            agent="worker",
            step_type="parallel_fan_out",
            source="task_data",
        ),
    ]

    summarizer = SummaryGenerator(
        llm_provider=provider,
        model=azure_model,
        max_summary_tokens=300,
        max_outline_tokens=1200,
        summary_threshold=100,
    )

    engine = WorkflowEngine(
        workflow_steps=steps,
        summarizer=summarizer,
    )
    engine.on_event(on_event)

    print(f"  Agents: {list(agents.keys())}")
    print(f"  Pipeline:")
    print(f"    planner [sequential] -> worker [fan_out, source=task_data] -> SYNTHESIS (manual)")
    print()

    # =========================================================================
    # PHASE 4: Execute the workflow (planner + workers only)
    # =========================================================================
    print("=" * 70)
    print("PHASE 4: Executing workflow")
    print("=" * 70)

    t1 = time.time()
    wf_result = await engine.execute(
        agents=agents,
        initial_state=state,
    )
    engine_elapsed = time.time() - t1

    print()
    print(f"  Status:  {wf_result.status.value}")
    print(f"  Steps:   {len(wf_result.step_results)}")
    print(f"  Elapsed: {engine_elapsed:.1f}s")
    print()

    if wf_result.status == WorkflowStatus.FAILED:
        print(f"  Error: {wf_result.error}")
        return

    result_state = wf_result.state

    # Collect full worker outputs
    parallel_results = result_state.get("worker_parallel_results", {})
    worker_sections: list[str] = []
    for key in sorted(parallel_results.keys()):
        item = parallel_results[key]
        output = item.get("worker_output", "") if isinstance(item, dict) else ""
        if output and isinstance(output, str) and output.strip():
            worker_sections.append(output.strip())

    total_worker_words = sum(len(s.split()) for s in worker_sections)
    print(f"  Workers produced {len(worker_sections)} sections, {total_worker_words:,} words total")
    print()

    # =========================================================================
    # PHASE 5: Synthesis — merge worker outputs into final document
    # =========================================================================
    # This is done as a manual LLM call (not through the engine) so the
    # synthesizer receives the FULL worker outputs directly, rather than
    # a lossy summary/outline through the engine's context propagation.
    print("=" * 70)
    print("PHASE 5: Synthesis")
    print("=" * 70)

    worker_material = "\n\n---\n\n".join(
        f"## Worker {i+1} of {len(worker_sections)}\n\n{section}"
        for i, section in enumerate(worker_sections)
    )

    synthesis_messages = [
        LLMMessage(
            role="system",
            content=writer.system_prompt,
        ),
        LLMMessage(
            role="user",
            content=(
                f"Below are outputs from {len(worker_sections)} workers who each "
                f"processed a portion of a meeting transcript "
                f"({total_worker_words:,} words total).\n\n"
                f"Merge them into a single comprehensive document.\n\n"
                f"{worker_material}"
            ),
        ),
    ]

    raw_model = azure_model.split(":", 1)[-1] if ":" in azure_model else azure_model
    synthesis_config = LLMConfig(model=raw_model, max_tokens=16384, temperature=0.3)

    t2 = time.time()
    synthesis_response = await provider.chat(synthesis_messages, synthesis_config)
    synthesis_elapsed = time.time() - t2
    writer_output = synthesis_response.content.strip()

    # Strip markdown code fences if the LLM wrapped its output in one
    if writer_output.startswith("```"):
        lines = writer_output.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        writer_output = "\n".join(lines)

    # Strip leading # heading — the template adds its own title
    wr_lines = writer_output.splitlines()
    while wr_lines and (wr_lines[0].strip() == "" or wr_lines[0].startswith("# ")):
        if wr_lines[0].startswith("# ") and not wr_lines[0].startswith("## "):
            wr_lines.pop(0)
        elif wr_lines[0].strip() == "":
            wr_lines.pop(0)
        else:
            break
    writer_output = "\n".join(wr_lines)

    writer_words = len(writer_output.split())
    synthesis_tokens = (synthesis_response.usage.total_tokens
                        if synthesis_response.usage else 0)
    print(f"  Synthesis: {writer_words:,} words in {synthesis_elapsed:.1f}s")
    print(f"  Tokens:    {synthesis_tokens:,}")
    print()

    # =========================================================================
    # PHASE 6: Results + Publish
    # =========================================================================
    print("=" * 70)
    print("PHASE 6: Results + Publishing")
    print("=" * 70)

    total_tokens = synthesis_tokens
    for aid in agents:
        usage = result_state.get(f"{aid}_usage")
        tokens = usage.get("total_tokens", 0) if usage else 0
        total_tokens += tokens

    exec_elapsed = engine_elapsed + synthesis_elapsed

    planner_output = result_state.get("planner_output", "")
    planner_words = len(planner_output.split()) if isinstance(planner_output, str) else 0
    planner_tokens = result_state.get("planner_usage", {}).get("total_tokens", 0)
    print(f"  {'planner':15s}  {planner_words:>5d} words  {planner_tokens:>5d} tokens")
    print(f"  {'workers':15s}  {total_worker_words:>5d} words")
    print(f"  {'synthesis':15s}  {writer_words:>5d} words  {synthesis_tokens:>5d} tokens")
    print(f"  {'TOTAL':15s}  {'':>5s}        {total_tokens:>5d} tokens")
    print()

    # -- Generate title from actual content ------------------------------------
    title_source = writer_output[:600]
    title_messages = [
        LLMMessage(
            role="user",
            content=(
                "Generate a short, professional document title (max 10 words) "
                "for the following document. Respond with ONLY the title, "
                "no quotes or extra punctuation.\n\n"
                f"Document excerpt:\n{title_source}"
            ),
        ),
    ]
    title_config = LLMConfig(model=raw_model, max_tokens=50, temperature=0.3)
    title_response = await provider.chat(title_messages, title_config)
    report_title = title_response.content.strip().strip('"').strip("'")
    print(f"  Title: {report_title}")

    # -- Build preprocessing report (Markdown) --------------------------------
    report_lines: list[str] = []
    report_lines.append(f"# {report_title}")
    report_lines.append("")
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    report_lines.append(f"**Generated:** {now}  ")
    report_lines.append(f"**Model:** {deployment}  ")
    report_lines.append(f"**Input size:** {word_count:,} words")
    report_lines.append("")
    report_lines.append("---")
    report_lines.append("")

    report_lines.append("## Preprocessing")
    report_lines.append("")
    if pp_activated:
        manifest = state.get("task_data_manifest", {})
        chunks = state.get("task_data", [])
        planner_ctx_words = len(original_instructions.split()) + len(data_summary.split())
        distilled_words = len(worker_instructions.split())
        reduction = (1 - planner_ctx_words / word_count) * 100

        report_lines.append("| Parameter | Value |")
        report_lines.append("|-----------|-------|")
        report_lines.append("| Status | **ACTIVATED** |")
        report_lines.append(f"| Boundary method | {manifest.get('boundary_method', '?')} |")
        report_lines.append(f"| Threshold | {manifest.get('effective_threshold', '?'):,} words |")
        report_lines.append(f"| Original instructions | {len(original_instructions.split()):,} words |")
        report_lines.append(f"| Distilled worker instructions | {distilled_words:,} words |")
        report_lines.append(f"| Data summary | {len(data_summary.split()):,} words |")
        report_lines.append(f"| Chunks | {len(chunks)} |")
        report_lines.append(f"| Context reduction | {reduction:.0f}% ({word_count:,} -> {planner_ctx_words:,} words) |")
        report_lines.append(f"| Preprocessing time | {preprocess_elapsed:.1f}s |")
        report_lines.append("")

        report_lines.append("### Data Summary (LLM-generated)")
        report_lines.append("")
        report_lines.append(f"> {data_summary}")
        report_lines.append("")

        report_lines.append("### Distilled Worker Instructions")
        report_lines.append("")
        report_lines.append(f"> {worker_instructions}")
        report_lines.append("")

        report_lines.append("### Chunk Manifest")
        report_lines.append("")
        report_lines.append("| Chunk | Words | Topic |")
        report_lines.append("|-------|------:|-------|")
        for chunk in chunks:
            cid = chunk["chunk_id"] if isinstance(chunk, dict) else chunk.chunk_id
            cw = chunk["words"] if isinstance(chunk, dict) else chunk.words
            hint = chunk.get("topic_hint", "") if isinstance(chunk, dict) else chunk.topic_hint
            hint_safe = hint.replace("\n", " ").replace("|", "-")[:100]
            report_lines.append(f"| {cid} | {cw:,} | {hint_safe} |")
        report_lines.append("")
    else:
        report_lines.append(
            f"Preprocessing **skipped** -- input ({word_count:,} words) below threshold."
        )
        report_lines.append("")

    report_lines.append("## Pipeline Execution")
    report_lines.append("")
    report_lines.append("| Step | Words | Tokens |")
    report_lines.append("|------|------:|-------:|")
    report_lines.append(f"| Planner | {planner_words:,} | {planner_tokens:,} |")
    report_lines.append(f"| Workers ({len(worker_sections)} chunks) | {total_worker_words:,} | -- |")
    report_lines.append(f"| Synthesis | {writer_words:,} | {synthesis_tokens:,} |")
    report_lines.append(f"| **TOTAL** | | **{total_tokens:,}** |")
    report_lines.append("")
    report_lines.append(f"**Execution time:** {exec_elapsed:.1f}s  ")
    report_lines.append(f"**Status:** {wf_result.status.value}")
    report_lines.append("")

    # Worker outputs (diagnostic — shows what each worker extracted)
    if worker_sections:
        report_lines.append(f"## Chunk Processing ({len(worker_sections)} workers)")
        report_lines.append("")
        for i, section in enumerate(worker_sections):
            words = len(section.split())
            report_lines.append(f"### Worker {i+1} ({words:,} words)")
            report_lines.append("")
            report_lines.append(section)
            report_lines.append("")

    # Final synthesized document
    report_lines.append("## Final Synthesized Document")
    report_lines.append("")
    report_lines.append(writer_output)
    report_lines.append("")

    report_md = "\n".join(report_lines)

    # -- Publish the SYNTHESIZED document (not engine state) -------------------
    # Write the synthesis directly as the main output file, bypassing
    # ResultPayload which would use the engine's final_output (which
    # doesn't include the manual synthesis step).
    timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_dir = Path("./output/task_preprocessing")
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"preprocessing_{timestamp}"

    # Main output: the synthesized document as Markdown
    md_path = output_dir / f"{filename}_team_output.md"
    safe_title = report_title.replace('"', '\\"')
    md_content = f'---\ntitle: "{safe_title}"\nstatus: completed\n---\n\n# {report_title}\n\n{writer_output}\n'
    md_path.write_text(md_content, encoding="utf-8")
    print(f"  Saved: {md_path}")

    # JSON output
    json_path = output_dir / f"{filename}_team_output.json"
    json_data = {
        "title": report_title,
        "status": "completed",
        "content": writer_output,
        "metadata": {
            "model": deployment,
            "input_words": word_count,
            "worker_sections": len(worker_sections),
            "synthesis_words": writer_words,
            "total_tokens": total_tokens,
            "execution_time_s": round(exec_elapsed, 1),
        },
    }
    json_path.write_text(json.dumps(json_data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  Saved: {json_path}")

    # DOCX and HTML via pandoc
    _has_pandoc = False
    try:
        import pypandoc
        pypandoc.get_pandoc_version()
        _has_pandoc = True
    except (ImportError, OSError, FileNotFoundError, AttributeError):
        pass

    if _has_pandoc:
        try:
            docx_path = output_dir / f"{filename}_team_output.docx"
            pypandoc.convert_text(
                md_content, "docx", format="md", outputfile=str(docx_path),
            )
            print(f"  Saved: {docx_path}")
        except Exception as e:
            print(f"  Warning: DOCX failed: {e}")
        try:
            html_path = output_dir / f"{filename}_team_output.html"
            pypandoc.convert_text(
                md_content, "html5", format="md", outputfile=str(html_path),
            )
            print(f"  Saved: {html_path}")
        except Exception as e:
            print(f"  Warning: HTML failed: {e}")
    else:
        print("  Note: pandoc not found -- skipping DOCX and HTML output")

    # Preprocessing report
    report_path = output_dir / f"{filename}_preprocessing_report.md"
    report_path.write_text(report_md, encoding="utf-8")
    print(f"  Saved: {report_path}")

    if _has_pandoc:
        try:
            docx_report = output_dir / f"{filename}_preprocessing_report.docx"
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
    print(f"  Input words:        {word_count:,}")
    print(f"  Preprocessing:      {preprocess_elapsed:.1f}s")
    if pp_activated:
        print(f"  Chunks created:     {len(chunks)}")
        print(f"  Boundary method:    {manifest.get('boundary_method', 'N/A')}")
        print(f"  Instruction distill: {len(original_instructions.split()):,} -> {len(worker_instructions.split()):,} words")
    print(f"  Worker output:      {total_worker_words:,} words ({len(worker_sections)} sections)")
    print(f"  Synthesis output:   {writer_words:,} words")
    print(f"  Total time:         {exec_elapsed:.1f}s")
    print(f"  Total tokens:       {total_tokens:,}")
    print(f"  Workflow status:    {wf_result.status.value}")
    print(f"  Output dir:         {output_dir}")
    print()


def cli() -> None:
    parser = argparse.ArgumentParser(
        description="Task preprocessing: automatic chunking and summarization for large inputs",
    )
    parser.add_argument(
        "--task-file",
        type=Path,
        default=DEFAULT_TASK_FILE,
        help=f"Path to a task file (default: {DEFAULT_TASK_FILE.name})",
    )
    parser.add_argument(
        "--data-file",
        type=Path,
        default=DEFAULT_DATA_FILE,
        help="Path to a data file to append to the task",
    )
    parser.add_argument(
        "--synthetic",
        action="store_true",
        default=False,
        help="Use synthetic data instead of task/data files",
    )
    parser.add_argument(
        "--deployment",
        default=os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini"),
        help="Azure OpenAI deployment name (default: gpt-4o-mini)",
    )
    args = parser.parse_args()
    asyncio.run(main(
        task_file=args.task_file,
        data_file=args.data_file,
        deployment=args.deployment,
        use_synthetic=args.synthetic,
    ))


if __name__ == "__main__":
    cli()
