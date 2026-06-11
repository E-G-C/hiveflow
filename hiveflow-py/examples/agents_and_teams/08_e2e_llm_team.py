#!/usr/bin/env python3
"""Example 08: End-to-end LLM team generation -> build -> execute -> publish.

The full autonomous pipeline:
  1. Describe a task in plain English
  2. LLM generates a complete TeamConfiguration (agents + workflow)
  3. Inspect the generated config and capability gaps
  4. Build live agents from the config
  5. Execute the workflow against Azure OpenAI
  6. Display per-agent outputs and final results
  7. Publish final output as Markdown and Word (.docx) with a unique timestamp

No pre-built template or manual config required -- the LLM decides
which agents to create, what roles they play, and how they collaborate.

Uses Azure OpenAI with Entra ID RBAC authentication.

Usage:
    uv run python examples/agents_and_teams/08_e2e_llm_team.py

    # Custom task:
    uv run python examples/agents_and_teams/08_e2e_llm_team.py \
        --task "Write a technical blog post comparing REST vs GraphQL"

    # Different deployment:
    AZURE_OPENAI_DEPLOYMENT=gpt-4o \
        uv run python examples/agents_and_teams/08_e2e_llm_team.py
"""

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hiveflow import TeamGenerator, WorkflowStatus
from hiveflow.core.teams import ArchetypeLibrary
from hiveflow.plugins.llm.azure_provider import AzureOpenAIProvider

AZURE_ENDPOINT = "https://foundry-aisbx-we.cognitiveservices.azure.com"


# -- Event handler for live progress ------------------------------------------

def on_event(event_type: str, agent_id: str, data: dict[str, Any]) -> None:
    if event_type == "step_start":
        step_type = data.get("step_type", "")
        print(f"  > {agent_id} ({step_type})...", flush=True)
    elif event_type == "step_complete":
        print(f"  * {agent_id} done", flush=True)
    elif event_type == "step_error":
        print(f"  X {agent_id} FAILED: {data.get('error', '')}", flush=True)


async def main(task: str, deployment: str) -> None:
    os.environ.setdefault("AZURE_OPENAI_ENDPOINT", AZURE_ENDPOINT)

    provider = AzureOpenAIProvider(azure_endpoint=AZURE_ENDPOINT)
    generator = TeamGenerator()
    archetype_library = ArchetypeLibrary.default()

    print(f"Endpoint:   {AZURE_ENDPOINT}")
    print(f"Deployment: {deployment}")
    print(f"Task:       {task}")
    print()

    # =========================================================================
    # PHASE 1: LLM generates the team configuration
    # =========================================================================
    print("=" * 60)
    print("PHASE 1: Generating team configuration via LLM")
    print("=" * 60)
    t0 = time.time()

    result = await generator.generate_team_from_llm(
        task_description=task,
        llm_provider=provider,
        model=deployment,
        archetype_library=archetype_library,
        auto_approve=False,
    )

    config = result.config
    elapsed = time.time() - t0
    print(f"  Generated in {elapsed:.1f}s")
    print(f"  Team:    {config.get('team_name', 'unnamed')}")
    print(f"  Agents:  {[a['id'] for a in config.get('agents', [])]}")
    print()

    # Show agent roster
    print("Agent roster:")
    for agent in config.get("agents", []):
        print(f"  {agent['id']:20s}  {agent.get('role', ''):30s}  [{agent.get('behavior_type', '')}]")
    print()

    # Show workflow
    print("Workflow:")
    for step in config.get("workflow", {}).get("steps", []):
        nxt = step.get("next") or step.get("next_on_accept") or "(end)"
        print(f"  {step['agent']:20s}  [{step['type']}]  -> {nxt}")
    print()

    # Capability gaps
    if result.capability_gaps:
        print(f"WARNING: Capability gaps ({len(result.capability_gaps)}):")
        for gap in result.capability_gaps:
            print(f"  [{gap.severity}] {gap.resource_type}:{gap.resource_id} -- {gap.description}")
        if result.has_blocking_gaps:
            print("\n** Blocking gaps detected -- cannot execute.")
            print("   Remove tool requirements or register the missing tools.")
            return
        print()
    else:
        print("[OK] No capability gaps\n")

    # New archetypes
    if result.new_archetypes:
        print(f"New archetypes ({len(result.new_archetypes)}):")
        for arch in result.new_archetypes:
            print(f"  {arch.get('id', '?'):20s}  {arch.get('role', '')}")
        print()

    # Full config
    print("Generated config (JSON):")
    print(json.dumps(config, indent=2))
    print()

    # =========================================================================
    # PHASE 2: Build live agents from the generated config
    # =========================================================================
    print("=" * 60)
    print("PHASE 2: Building agents and workflow engine")
    print("=" * 60)

    # Ensure all agents use the Azure deployment (the LLM may have put
    # placeholder model names like "$SMART_LLM")
    azure_model = f"azure:{deployment}"
    for agent in config.get("agents", []):
        agent["model"] = azure_model

    # Remove any tool references that would cause tool_user validation to fail
    # (LLM may invent tools that don't exist -- build() gracefully falls back
    # tool_user -> llm_only, but we strip tools to be explicit)
    for agent in config.get("agents", []):
        if agent.get("tools"):
            print(f"  Note: stripping tools from {agent['id']} (not registered)")
            agent["tools"] = []

    # Use adaptive summarization: outputs under 4000 words are passed
    # through in full; only very long outputs get summarized.  This
    # prevents the aggressive compression that caused fragmentary output
    # while still protecting against context overflow in large workflows.
    agents, engine = generator.build(
        config, provider, model=azure_model, summary_threshold=4000,
    )
    engine.on_event(on_event)

    print(f"  Built {len(agents)} agents")
    print(f"  Workflow: {len(engine.steps)} steps")
    print()

    # =========================================================================
    # PHASE 3: Execute the workflow
    # =========================================================================
    print("=" * 60)
    print("PHASE 3: Executing workflow")
    print("=" * 60)
    t1 = time.time()

    wf_result = await engine.execute(
        agents=agents,
        initial_state={"task": task},
    )

    elapsed = time.time() - t1
    print()
    print(f"  Status:  {wf_result.status.value}")
    print(f"  Steps:   {len(wf_result.step_results)}")
    print(f"  Elapsed: {elapsed:.1f}s")
    print()

    if wf_result.status == WorkflowStatus.FAILED:
        print(f"  Error: {wf_result.error}")
        return

    # =========================================================================
    # PHASE 4: Display results
    # =========================================================================
    print("=" * 60)
    print("PHASE 4: Results")
    print("=" * 60)

    state = wf_result.state

    # Per-agent summary
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

    # Show each agent's output
    for agent_def in config.get("agents", []):
        aid = agent_def["id"]
        output = state.get(f"{aid}_output", "")
        if not output:
            continue
        role = agent_def.get("role", aid)
        print(f"--- {aid} ({role}) ---")
        print(output[:1500])
        if len(output) > 1500:
            print(f"  ... ({len(output)} chars total)")
        print()

    # Final assembled output (if available)
    final = state.get("final_output")
    if final:
        print("=" * 60)
        print("FINAL OUTPUT")
        print("=" * 60)
        print(final[:3000])
        if len(final) > 3000:
            print(f"  ... ({len(final)} chars total)")

    # =========================================================================
    # PHASE 5: Publish output as Markdown and Word (.docx)
    # =========================================================================
    print()
    print("=" * 60)
    print("PHASE 5: Publishing output (Markdown + Word)")
    print("=" * 60)

    from hiveflow.core.result_payload import ResultPayload
    from hiveflow.plugins.publishers import MarkdownPublisher, PublisherRegistry

    # Generate a concise document title from the task description
    from hiveflow.plugins.llm import LLMConfig as _LLMConfig, LLMMessage

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
    title_config = _LLMConfig(model=deployment, max_tokens=50, temperature=0.3)
    title_response = await provider.chat(title_messages, title_config)
    report_title = title_response.content.strip().strip('"').strip("'")
    print(f"  Title: {report_title}")

    # Build payload with the generated title
    payload = ResultPayload.from_workflow_result(wf_result, title=report_title)

    timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_dir = Path("./output")
    filename = f"e2e_team_{timestamp}"

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
        filename=filename,
    )

    for p in paths:
        print(f"  Saved: {p}")
    print()


def cli() -> None:
    parser = argparse.ArgumentParser(
        description="End-to-end: LLM generates a team, builds it, and executes the workflow",
    )
    parser.add_argument(
        "--task",
        default="Write a comparative analysis of three cloud providers (AWS, Azure, GCP) for a startup choosing its infrastructure",
        help="Task description -- the LLM designs the team around this",
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
