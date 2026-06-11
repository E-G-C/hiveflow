#!/usr/bin/env python3
"""Advanced Workflows 01: Fan-out report generation.

Demonstrates HiveFlow's orchestrator -> parallel fan-out -> assembly pipeline:
  1. **Planner** (orchestrator) decomposes a topic into 4-6 independent sections
  2. **Writer** (parallel fan-out) runs once per section in parallel
  3. **Assembly** -- code-level concatenation into ``final_output``

Uses a mock LLM by default. Set AZURE_OPENAI_ENDPOINT for live results.

Usage:
    uv run python examples/advanced_workflows/01_fan_out_report.py

    # With Azure OpenAI:
    AZURE_OPENAI_ENDPOINT=https://<resource>.cognitiveservices.azure.com \
        uv run python examples/advanced_workflows/01_fan_out_report.py

    # Custom topic:
    uv run python examples/advanced_workflows/01_fan_out_report.py \
        --task "The history and future of space exploration"

Expected output:
    See sample_output/advanced_workflows/01_fan_out_report.txt
"""

import argparse
import asyncio
import json
import os
import time
from pathlib import Path

from hiveflow import (
    Agent,
    AgentBehaviorType,
    SummaryGenerator,
    WorkflowEngine,
    WorkflowStatus,
    WorkflowStep,
)
from hiveflow.plugins.llm import LLMConfig, LLMMessage, LLMProvider, LLMResponse, TokenUsage


# ---------------------------------------------------------------------------
# Mock provider
# ---------------------------------------------------------------------------

class MockProvider(LLMProvider):
    """Returns realistic mock responses for planner/writer roles."""

    def __init__(self) -> None:
        self._writer_calls = 0

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def plugin_id(self) -> str:
        return "mock"

    @property
    def description(self) -> str:
        return "Mock LLM for fan-out demo"

    async def chat(self, messages: list[LLMMessage], config: LLMConfig) -> LLMResponse:
        system = next((m.content for m in messages if m.role == "system"), "")

        if "planner" in system.lower() or "decompose" in system.lower():
            content = json.dumps({
                "sub_tasks": [
                    "Section 1: Current State of AI -- Overview of foundation models and capabilities",
                    "Section 2: Enterprise Adoption -- How businesses are integrating AI",
                    "Section 3: Economic Impact -- Job market changes and productivity gains",
                    "Section 4: Risks and Challenges -- Bias, safety, and regulatory landscape",
                    "Section 5: Future Outlook -- Next 5-10 years of AI development",
                ]
            })
            usage = TokenUsage(prompt_tokens=100, completion_tokens=80, total_tokens=180)
        else:
            self._writer_calls += 1
            sections = {
                1: "## 1. Current State of AI\n\nFoundation models have transformed...",
                2: "## 2. Enterprise Adoption\n\nBusinesses across sectors are integrating...",
                3: "## 3. Economic Impact\n\nThe economic effects of AI are far-reaching...",
                4: "## 4. Risks and Challenges\n\nDespite the potential, AI faces significant...",
                5: "## 5. Future Outlook\n\nLooking ahead to the next decade...",
            }
            content = sections.get(self._writer_calls, f"## Section {self._writer_calls}\n\nContent...")
            # Expand content to be more realistic
            content += (
                "\n\nLorem ipsum dolor sit amet, consectetur adipiscing elit. "
                "Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. "
            ) * 8
            usage = TokenUsage(prompt_tokens=200, completion_tokens=300, total_tokens=500)

        return LLMResponse(content=content, model="mock-model", usage=usage)


def get_provider() -> tuple[LLMProvider, str]:
    """Return Azure provider if configured, else mock."""
    if os.environ.get("AZURE_OPENAI_ENDPOINT"):
        from hiveflow.plugins.llm.azure_provider import AzureOpenAIProvider
        endpoint = os.environ["AZURE_OPENAI_ENDPOINT"]
        deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
        return AzureOpenAIProvider(azure_endpoint=endpoint), f"azure:{deployment}"
    return MockProvider(), "mock-model"


# ---------------------------------------------------------------------------
# Build agents and workflow
# ---------------------------------------------------------------------------

def build_agents(provider: LLMProvider, model: str) -> dict[str, Agent]:
    """Create planner + writer agents."""
    planner = Agent(
        agent_id="planner",
        role="Report Planner",
        system_prompt=(
            "You are a report planner. Decompose a broad topic into 4-6 "
            "independent sections for a comprehensive report.\n\n"
            "Rules:\n"
            "- Each section must cover a distinct, non-overlapping aspect\n"
            "- Sections must be self-contained\n"
            "- Number sections sequentially starting at 1\n"
            "- Include a descriptive title and a one-sentence scope\n\n"
            "Respond with ONLY a JSON object:\n"
            '{"sub_tasks": ["Section 1: <Title> - <scope>", ...]}'
        ),
        behavior_type=AgentBehaviorType.ORCHESTRATOR,
        model=model,
        llm_provider=provider,
        llm_config=LLMConfig(model=model, temperature=0.4, max_tokens=1024),
    )

    writer = Agent(
        agent_id="writer",
        role="Section Writer",
        system_prompt=(
            "You are a professional long-form writer producing one section of a report.\n"
            "Rules:\n"
            "- Write ONLY your assigned section\n"
            "- Start with a markdown heading\n"
            "- Produce detailed content with multiple paragraphs\n"
            "- Aim for at least 300 words\n"
            "- Do NOT repeat content from other sections"
        ),
        behavior_type=AgentBehaviorType.LLM_ONLY,
        model=model,
        llm_provider=provider,
        llm_config=LLMConfig(model=model, temperature=0.7, max_tokens=4096),
        context_budget=2000,
    )

    return {"planner": planner, "writer": writer}


def build_workflow() -> WorkflowEngine:
    """Create planner -> parallel writer workflow with assembly."""
    steps = [
        WorkflowStep(agent="planner", step_type="sequential", next_step="writer"),
        WorkflowStep(agent="writer", step_type="parallel_fan_out"),
    ]
    return WorkflowEngine(steps, assembly_agents=["writer"])


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run(task: str) -> None:
    """Execute the fan-out report pipeline."""
    print("=" * 60)
    print("  HiveFlow -- Fan-Out Report Generation")
    print("=" * 60)

    provider, model = get_provider()
    is_live = "azure" in model
    print(f"  Provider: {'Azure OpenAI' if is_live else 'Mock (no API key)'}")
    print(f"  Task:     {task[:60]}...")

    agents = build_agents(provider, model)
    engine = build_workflow()

    # Event callback for live progress
    step_times: dict[str, float] = {}

    def on_event(event_type: str, agent_id: str, data: dict) -> None:
        if event_type == "step_start":
            step_times[agent_id] = time.time()
            print(f"\n  > {agent_id} ({data.get('step_type', '')})", flush=True)
        elif event_type == "step_complete":
            elapsed = time.time() - step_times.get(agent_id, time.time())
            print(f"  * {agent_id} ({elapsed:.1f}s)", flush=True)
        elif event_type == "assembly_complete":
            print(f"  ! Assembled: {data.get('num_sections', '?')} sections, "
                  f"{data.get('total_words', '?')} words", flush=True)

    engine.on_event(on_event)

    # Execute
    t0 = time.time()
    result = await engine.execute(
        agents=agents,
        initial_state={"task": task},
    )
    elapsed = time.time() - t0

    # Display results
    print(f"\n{'-' * 60}")
    print(f"Status:  {result.status.value}")
    print(f"Steps:   {len(result.step_results)}")
    print(f"Elapsed: {elapsed:.1f}s")

    if result.error:
        print(f"Error:   {result.error}")
        return

    # Section breakdown
    parallel_items = result.state.get("parallel_items", [])
    writer_outputs = result.state.get("writer_outputs", [])
    print(f"\nSections planned: {len(parallel_items)}")
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

    # Final output
    final = result.state.get("final_output", "")
    if final:
        word_count = len(final.split())
        print(f"\nFinal output: {word_count} words")
        print(f"\n{'-' * 60}")
        print(final[:2000])
        if len(final) > 2000:
            print(f"\n  ... ({len(final)} chars total)")

        # Save to file
        output_path = Path("output/fan_out_report.md")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            f"# {task}\n\n"
            f"*Generated by HiveFlow fan-out pipeline*\n\n"
            f"**Sections:** {len(parallel_items)}  \n"
            f"**Words:** {word_count}\n\n---\n\n"
            + final,
            encoding="utf-8",
        )
        print(f"\n  Output saved: {output_path}")


def main() -> None:
    """Parse args and run."""
    parser = argparse.ArgumentParser(description="Fan-out report generation")
    parser.add_argument(
        "--task",
        default="Write a comprehensive report on the current state and future of artificial intelligence",
        help="The report topic",
    )
    args = parser.parse_args()
    asyncio.run(run(task=args.task))


if __name__ == "__main__":
    main()
