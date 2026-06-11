#!/usr/bin/env python3
"""Example 14: Full-auto pipeline — file in, LLM designs everything, multi-format out.

The most autonomous mode of HiveFlow. You provide a task file and the
framework handles everything else:

  1. Load the task from a markdown file
  2. LLM analyzes the task and generates a complete team configuration
     (agents, roles, system prompts, workflow graph)
  3. Collaboration is injected so orchestrators can delegate, spawn
     specialists, and create structured plans at runtime
  4. The LLM-designed team executes the workflow against Azure OpenAI
  5. Results are published to Markdown, JSON, and DOCX

No manual agent definitions, no hardcoded workflows — the LLM decides
the team composition, and collaboration lets agents self-organize.

Uses Azure OpenAI with DefaultAzureCredential (Entra ID RBAC).

Usage:
    # Default task file:
    uv run python examples/agents_and_teams/14_full_auto_pipeline.py

    # Custom task file:
    uv run python examples/agents_and_teams/14_full_auto_pipeline.py \
        --task-file path/to/your_task.md

    # Pass a target file for the task to operate on:
    uv run python examples/agents_and_teams/14_full_auto_pipeline.py \
        --target-file path/to/code_to_review.py

    # Different deployment:
    AZURE_OPENAI_DEPLOYMENT=gpt-4o \
        uv run python examples/agents_and_teams/14_full_auto_pipeline.py
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
from hiveflow.core.teams import ArchetypeLibrary
from hiveflow.plugins.llm import LLMProviderRegistry
from hiveflow.plugins.llm.azure_provider import AzureOpenAIProvider

AZURE_ENDPOINT = "https://foundry-aisbx-we.cognitiveservices.azure.com"
DEFAULT_TASK_FILE = Path(__file__).parent / "tasks" / "ai_code_review_brief.md"


# -- Event handler for live progress ------------------------------------------

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


async def main(task_file: Path, deployment: str, target_file: Path | None = None) -> None:
    os.environ.setdefault("AZURE_OPENAI_ENDPOINT", AZURE_ENDPOINT)

    provider = AzureOpenAIProvider(azure_endpoint=AZURE_ENDPOINT)
    generator = TeamGenerator()
    archetype_library = ArchetypeLibrary.default()

    azure_model = f"azure:{deployment}"

    # =========================================================================
    # PHASE 0: Load the task from file
    # =========================================================================
    print("=" * 70)
    print("PHASE 0: Loading task")
    print("=" * 70)

    if not task_file.exists():
        print(f"  ERROR: Task file not found: {task_file}")
        print("  Create a .md file with your task description, or use --task-file")
        return

    task_text = task_file.read_text(encoding="utf-8").strip()
    word_count = len(task_text.split())
    print(f"  File:     {task_file.name}")
    print(f"  Words:    {word_count}")
    print(f"  Preview:  {task_text[:120]}...")

    # Load optional target file and append its content to the task
    target_content: str | None = None
    if target_file is not None:
        if not target_file.exists():
            print(f"  ERROR: Target file not found: {target_file}")
            return
        target_content = target_file.read_text(encoding="utf-8")
        task_text += (
            f"\n\n---\n## Target File: {target_file.name}\n"
            f"```\n{target_content}\n```"
        )
        print(f"  Target:   {target_file.name} ({len(target_content.split())} words)")

    print()

    # =========================================================================
    # PHASE 1: LLM designs the team
    # =========================================================================
    print("=" * 70)
    print("PHASE 1: LLM generating team configuration")
    print("=" * 70)
    print(f"  Endpoint:   {AZURE_ENDPOINT}")
    print(f"  Deployment: {deployment}")
    print()

    # Show available archetypes (the LLM sees these too)
    archetype_names = archetype_library.list_archetypes()
    print(f"  Available archetypes ({len(archetype_names)}):")
    for name in archetype_names:
        arch = archetype_library.get(name)
        print(f"    - {name:16s}  {arch['role']}")
    print()

    t0 = time.time()
    result = await generator.generate_team_from_llm(
        task_description=task_text,
        llm_provider=provider,
        model=deployment,
        archetype_library=archetype_library,
        auto_approve=False,
    )
    config = result.config
    gen_elapsed = time.time() - t0

    print(f"  Generated in {gen_elapsed:.1f}s")
    print(f"  Team name: {config.get('team_name', 'unnamed')}")
    print()

    # Display agent roster
    print("  Agent roster:")
    for agent in config.get("agents", []):
        print(
            f"    {agent['id']:20s}  {agent.get('role', ''):30s}  "
            f"[{agent.get('behavior_type', '')}]"
        )
    print()

    # Display workflow graph
    print("  Workflow:")
    for step in config.get("workflow", {}).get("steps", []):
        nxt = step.get("next") or step.get("next_on_accept") or "(end)"
        print(f"    {step['agent']:20s}  [{step['type']}]  -> {nxt}")
    print()

    # Capability gaps
    if result.capability_gaps:
        print(f"  Capability gaps ({len(result.capability_gaps)}):")
        for gap in result.capability_gaps:
            print(f"    [{gap.severity}] {gap.resource_type}:{gap.resource_id}")
        if result.has_blocking_gaps:
            print("\n  ** Blocking gaps -- cannot execute. Fix tool registrations.")
            return
    print()

    # =========================================================================
    # PHASE 2: Inject collaboration + build agents
    # =========================================================================
    print("=" * 70)
    print("PHASE 2: Injecting collaboration and building agents")
    print("=" * 70)

    # Inject collaboration config — this turns the static team dynamic.
    # Orchestrator agents will get delegate_task, spawn_agent, plan_and_execute,
    # send_message, and read_messages tools automatically.
    config["collaboration"] = {
        "enabled": True,
        "max_delegation_depth": 3,
        "max_spawned_agents": 8,
        "delegation_timeout_seconds": 120,
    }
    print("  Collaboration: ENABLED")
    print("    max_delegation_depth:  3")
    print("    max_spawned_agents:    8")
    print()

    # Set all agents to use our Azure deployment and enhance system prompts
    # for richer output.  The LLM-generated prompts are often one-liners;
    # appending depth guidance makes each agent produce comprehensive content.
    depth_instruction = (
        "\n\nIMPORTANT: Produce a thorough, detailed, and well-structured "
        "response.  Use markdown formatting with headings, sub-headings, "
        "bullet points, and numbered lists where appropriate.  Aim for "
        "depth over brevity — include specific examples, data points, "
        "comparisons, and actionable recommendations.  Your output will "
        "be part of a professional report."
    )
    for agent in config.get("agents", []):
        agent["model"] = azure_model
        agent["system_prompt"] += depth_instruction

    # Strip unregistered tool references (they come from LLM generation
    # and are not available — the agent falls back to llm_only behavior)
    for agent in config.get("agents", []):
        if agent.get("tools"):
            print(f"  Note: stripping tools from {agent['id']} (not registered)")
            agent["tools"] = []

    agents, engine = generator.build(
        config,
        provider,
        model=azure_model,
        max_tokens=16000,
        summary_threshold=4000,
    )
    engine.on_event(on_event)

    print(f"  Built {len(agents)} agents, {len(engine.steps)} workflow steps")
    print()

    # Show generated config (condensed)
    print("  Generated config:")
    print(json.dumps(config, indent=2)[:1200])
    if len(json.dumps(config)) > 1200:
        print("  ...")
    print()

    # =========================================================================
    # PHASE 3: Execute
    # =========================================================================
    print("=" * 70)
    print("PHASE 3: Executing workflow")
    print("=" * 70)

    t1 = time.time()
    initial_state: dict[str, Any] = {"task": task_text}
    if target_content is not None:
        initial_state["target_file"] = target_content
        initial_state["target_file_name"] = str(target_file)
    wf_result = await engine.execute(
        agents=agents,
        initial_state=initial_state,
    )
    exec_elapsed = time.time() - t1

    print()
    print(f"  Status:  {wf_result.status.value}")
    print(f"  Steps:   {len(wf_result.step_results)}")
    print(f"  Elapsed: {exec_elapsed:.1f}s")
    print()

    if wf_result.status == WorkflowStatus.FAILED:
        print(f"  Error: {wf_result.error}")
        return

    # =========================================================================
    # PHASE 4: Results
    # =========================================================================
    print("=" * 70)
    print("PHASE 4: Results")
    print("=" * 70)

    state = wf_result.state

    total_tokens = 0
    for agent_def in config.get("agents", []):
        aid = agent_def["id"]
        output = state.get(f"{aid}_output", "")
        usage = state.get(f"{aid}_usage")
        words = len(output.split()) if isinstance(output, str) else 0
        tokens = usage.get("total_tokens", 0) if usage else 0
        total_tokens += tokens
        print(f"  {aid:20s}  {words:>5d} words  {tokens:>5d} tokens")

    print(f"  {'TOTAL':20s}  {'':>5s}        {total_tokens:>5d} tokens")
    print()

    # Show final assembled output
    final = state.get("final_output", "")
    if not final:
        # Fall back to last agent's output
        last_agent = config["agents"][-1]["id"]
        final = state.get(f"{last_agent}_output", "")

    if final:
        print("  --- Final output (first 2000 chars) ---")
        print(final[:2000])
        if len(final) > 2000:
            print(f"  ... ({len(final)} chars total)")
        print()

    # =========================================================================
    # PHASE 5: Publish — Markdown + JSON + DOCX
    # =========================================================================
    print("=" * 70)
    print("PHASE 5: Publishing (Markdown + JSON + DOCX)")
    print("=" * 70)

    from hiveflow.core.result_payload import ResultPayload
    from hiveflow.plugins.llm import LLMConfig as _LLMConfig, LLMMessage
    from hiveflow.plugins.publishers import MarkdownPublisher, PublisherRegistry
    from hiveflow.plugins.publishers.json_publisher import JSONPublisher

    # Ask the LLM to generate a document title from the task
    title_messages = [
        LLMMessage(
            role="user",
            content=(
                "Generate a short, professional document title (max 10 words) "
                "for a report on the following topic. Respond with ONLY the "
                "title, no quotes or extra punctuation.\n\n"
                f"Topic: {task_text[:500]}"
            ),
        ),
    ]
    title_config = _LLMConfig(model=deployment, max_tokens=50, temperature=0.3)
    title_response = await provider.chat(title_messages, title_config)
    report_title = title_response.content.strip().strip('"').strip("'")
    print(f"  Title: {report_title}")

    # Build payload
    payload = ResultPayload.from_workflow_result(wf_result, title=report_title)

    timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_dir = Path("./output/full_auto")
    filename = f"report_{timestamp}"

    # Register publishers
    pub_registry = PublisherRegistry(drop_in_dir=None)
    pub_registry.register(MarkdownPublisher())
    pub_registry.register(JSONPublisher())

    formats = ["markdown", "json"]

    # Check for pandoc (needed by DOCX and HTML publishers)
    _has_pandoc = False
    try:
        import pypandoc
        pypandoc.get_pandoc_version()  # actually invokes the binary
        _has_pandoc = True
    except (ImportError, OSError, FileNotFoundError, AttributeError):
        pass

    # Try DOCX (requires pypandoc + pandoc binary)
    if _has_pandoc:
        try:
            from hiveflow.plugins.publishers.docx_publisher import DOCXPublisher
            pub_registry.register(DOCXPublisher())
            formats.append("docx")
        except ImportError:
            pass

    # Try HTML (requires pypandoc + pandoc binary)
    if _has_pandoc:
        try:
            from hiveflow.plugins.publishers.html_publisher import HTMLPublisher
            pub_registry.register(HTMLPublisher())
            formats.append("html")
        except ImportError:
            pass

    if not _has_pandoc:
        print("  Note: pandoc not found -- skipping DOCX and HTML output")
        print("        Install pandoc: https://pandoc.org/installing.html")

    paths = await pub_registry.publish_all(
        payload,
        output_dir=str(output_dir),
        formats=formats,
        filename=filename,
    )

    print()
    print(f"  Published {len(paths)} files:")
    for p in paths:
        size = p.stat().st_size if hasattr(p, "stat") else 0
        print(f"    {p} ({size:,} bytes)")
    print()

    # =========================================================================
    # Summary
    # =========================================================================
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"  Task file:       {task_file.name}")
    print(f"  Team generated:  {config.get('team_name', 'unnamed')}")
    print(f"  Agents created:  {len(config.get('agents', []))}")
    print(f"  Collaboration:   enabled")
    print(f"  Workflow status:  {wf_result.status.value}")
    print(f"  Total tokens:    {total_tokens:,}")
    print(f"  Generation time: {gen_elapsed:.1f}s")
    print(f"  Execution time:  {exec_elapsed:.1f}s")
    print(f"  Output formats:  {', '.join(formats)}")
    print(f"  Output dir:      {output_dir}")
    print()


def cli() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Full-auto pipeline: load task from file, LLM designs the team, "
            "collaboration enables dynamic delegation, publish multi-format output"
        ),
    )
    parser.add_argument(
        "--task-file",
        type=Path,
        default=DEFAULT_TASK_FILE,
        help=f"Path to a .md task file (default: {DEFAULT_TASK_FILE.name})",
    )
    parser.add_argument(
        "--target-file",
        type=Path,
        default=None,
        help="Path to a file the task should operate on (e.g. source code to review)",
    )
    parser.add_argument(
        "--deployment",
        default=os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini"),
        help="Azure OpenAI deployment name (default: gpt-4o-mini)",
    )
    args = parser.parse_args()
    asyncio.run(main(task_file=args.task_file, deployment=args.deployment, target_file=args.target_file))


if __name__ == "__main__":
    cli()
