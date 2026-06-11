#!/usr/bin/env python3
"""Advanced Workflows 02: Fan-out with dynamic team generation.

Combines two HiveFlow capabilities:
  1. **Team Generation** -- TeamGenerator dynamically selects agent archetypes
     and wires a workflow from a task description alone
  2. **Parallel Fan-Out** -- when the generated team includes a planner and
     worker, the workflow is automatically wired as
     orchestrator -> parallel_fan_out -> assembly

Uses a mock LLM by default. Set AZURE_OPENAI_ENDPOINT for live results.

Usage:
    uv run python examples/advanced_workflows/02_fan_out_generated.py

    # Custom task:
    uv run python examples/advanced_workflows/02_fan_out_generated.py \
        --task "Compare 5 programming languages for web development"

Expected output:
    See sample_output/advanced_workflows/02_fan_out_generated.txt
"""

import argparse
import asyncio
import json
import os
import time
from datetime import datetime
from pathlib import Path

from hiveflow import TeamGenerator
from hiveflow.plugins.llm import LLMConfig, LLMMessage, LLMProvider, LLMResponse, TokenUsage


# ---------------------------------------------------------------------------
# Mock provider
# ---------------------------------------------------------------------------

class MockFanOutProvider(LLMProvider):
    """Mock provider for fan-out team generation demo."""

    def __init__(self) -> None:
        self._call_count = 0

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def plugin_id(self) -> str:
        return "mock"

    @property
    def description(self) -> str:
        return "Mock LLM for fan-out generation demo"

    async def chat(self, messages: list[LLMMessage], config: LLMConfig) -> LLMResponse:
        self._call_count += 1
        system = next((m.content for m in messages if m.role == "system"), "")

        if "planner" in system.lower() or "decompose" in system.lower():
            content = json.dumps({
                "sub_tasks": [
                    "Section 1: Market Overview -- Current renewable energy landscape",
                    "Section 2: Technology Comparison -- Solar vs wind vs hydro",
                    "Section 3: Economic Analysis -- Cost trends and investment patterns",
                    "Section 4: Policy and Regulation -- Government incentives worldwide",
                ]
            })
            usage = TokenUsage(prompt_tokens=80, completion_tokens=60, total_tokens=140)
        elif "review" in system.lower():
            content = (
                "The report is well-structured and covers the key aspects. "
                "Minor suggestion: the economic analysis could include more "
                "recent 2025 data. Overall quality: APPROVED."
            )
            usage = TokenUsage(prompt_tokens=400, completion_tokens=50, total_tokens=450)
        else:
            content = (
                f"## Section Content (Call #{self._call_count})\n\n"
                "This section provides detailed analysis of renewable energy "
                "technologies and their impact on global energy markets. "
                "Key data points include cost reductions, capacity growth, "
                "and policy frameworks driving adoption.\n\n"
                "The analysis reveals significant regional variation in adoption "
                "rates, with Europe and China leading in installed capacity."
            )
            usage = TokenUsage(prompt_tokens=200, completion_tokens=100, total_tokens=300)

        return LLMResponse(content=content, model="mock-model", usage=usage)


def get_provider() -> tuple[LLMProvider, str]:
    """Return Azure provider if configured, else mock."""
    if os.environ.get("AZURE_OPENAI_ENDPOINT"):
        from hiveflow.plugins.llm.azure_provider import AzureOpenAIProvider
        endpoint = os.environ["AZURE_OPENAI_ENDPOINT"]
        deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
        return AzureOpenAIProvider(azure_endpoint=endpoint), f"azure:{deployment}"
    return MockFanOutProvider(), "mock-model"


async def run(task: str, include_review: bool) -> None:
    """Generate a team, execute the fan-out workflow, report results."""
    print("=" * 60)
    print("  HiveFlow -- Fan-Out with Dynamic Team Generation")
    print("=" * 60)

    provider, model = get_provider()
    is_live = "azure" in model
    print(f"  Provider: {'Azure OpenAI' if is_live else 'Mock (no API key)'}")
    print(f"  Task:     {task[:60]}...")

    # -- Step 1: Generate team config --
    generator = TeamGenerator()
    config = generator.generate_team(
        task_description=task,
        agent_types=["planner", "writer"],
        include_review=include_review,
    )

    print(f"\n  Generated team: {config['team_name']}")
    print(f"  Agents: {[a['id'] for a in config['agents']]}")
    flow = " -> ".join(
        f"{s['agent']} ({s['type']})" for s in config["workflow"]["steps"]
    )
    print(f"  Workflow: {flow}")

    # -- Step 2: Build and execute --
    agents, engine = generator.build(config, provider, model=model)

    step_times: dict[str, float] = {}

    def on_event(event_type: str, agent_id: str, data: dict) -> None:
        if event_type == "step_start":
            step_times[agent_id] = time.time()
            print(f"\n  > {agent_id} ({data.get('step_type', '')})", flush=True)
        elif event_type == "step_complete":
            elapsed = time.time() - step_times.get(agent_id, time.time())
            print(f"  * {agent_id} ({elapsed:.1f}s)", flush=True)

    engine.on_event(on_event)

    t0 = time.time()
    result = await engine.execute(
        agents=agents,
        initial_state={"task": task},
    )
    elapsed = time.time() - t0

    # -- Step 3: Report results --
    print(f"\n{'-' * 60}")
    print(f"Status:  {result.status.value}")
    print(f"Steps:   {len(result.step_results)}")
    print(f"Elapsed: {elapsed:.1f}s")

    if result.error:
        print(f"Error:   {result.error}")
        return

    parallel_items = result.state.get("parallel_items", [])
    writer_outputs = result.state.get("writer_outputs", [])
    print(f"\nSections: {len(parallel_items)} planned, {len(writer_outputs)} written")
    for i, item in enumerate(parallel_items):
        output = writer_outputs[i] if i < len(writer_outputs) else ""
        words = len(output.split()) if isinstance(output, str) else 0
        print(f"  {i + 1}. {words:4d} words -- {item[:60]}")

    # Token usage
    total_tokens = 0
    for step in result.step_results:
        usage = result.state.get(f"{step.agent_id}_usage")
        if usage:
            total_tokens += usage.get("total_tokens", 0)
    print(f"\nTotal tokens: {total_tokens}")

    # Save output
    final = result.state.get("final_output", "")
    if final:
        output_path = Path("output/fan_out_generated.md")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            f"# {task}",
            "",
            f"*Generated by HiveFlow (fan-out + team generation) on "
            f"{datetime.now().strftime('%Y-%m-%d %H:%M')}*",
            "",
            "## Generated Team Configuration",
            "",
            "```json",
            json.dumps(config, indent=2),
            "```",
            "",
            "---",
            "",
            final,
        ]
        output_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"\n  Output saved: {output_path} ({len(final.split())} words)")


def main() -> None:
    """Parse args and run."""
    parser = argparse.ArgumentParser(description="Fan-out with dynamic team generation")
    parser.add_argument(
        "--task",
        default="Write a comprehensive analysis of renewable energy technologies "
                "and their impact on global energy markets",
        help="Task description",
    )
    parser.add_argument("--no-review", action="store_true", help="Skip reviewer step")
    args = parser.parse_args()
    asyncio.run(run(task=args.task, include_review=not args.no_review))


if __name__ == "__main__":
    main()
