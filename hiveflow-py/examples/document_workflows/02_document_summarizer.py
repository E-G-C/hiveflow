#!/usr/bin/env python3
"""Document Workflows 02: Summarize a document with a two-agent workflow.

Loads a sample document, then runs two LLM agents:
  1. **Analyst** -- extracts key metrics and takeaways
  2. **Writer** -- produces a polished executive summary

Demonstrates:
  - DocumentPipeline loading real files into workflow state
  - Documents flowing through WorkflowEngine to agents automatically
  - Per-agent system prompts that reference document content
  - Sequential two-step workflow with state propagation
  - Output written to a markdown file

Uses a mock LLM by default. Set AZURE_OPENAI_ENDPOINT for live results.

Usage:
    uv run python examples/document_workflows/02_document_summarizer.py

    # With Azure OpenAI:
    AZURE_OPENAI_ENDPOINT=https://<resource>.cognitiveservices.azure.com \
        uv run python examples/document_workflows/02_document_summarizer.py

Expected output:
    See sample_output/document_workflows/02_document_summarizer.txt
"""

import asyncio
import os
import tempfile
import time
from pathlib import Path

from hiveflow import (
    Agent,
    AgentBehaviorType,
    WorkflowEngine,
    WorkflowStatus,
    WorkflowStep,
)
from hiveflow.core.documents import DocumentPipeline
from hiveflow.core.schema import AgentBehaviorTypeSchema, AgentDefinition
from hiveflow.plugins.documents import DocumentLoaderRegistry
from hiveflow.plugins.llm import LLMConfig, LLMMessage, LLMProvider, LLMResponse, TokenUsage


# ---------------------------------------------------------------------------
# Mock provider (no API key needed)
# ---------------------------------------------------------------------------

class MockProvider(LLMProvider):
    """Returns realistic mock responses for document summarization."""

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def plugin_id(self) -> str:
        return "mock"

    @property
    def description(self) -> str:
        return "Mock LLM for document summarization demo"

    async def chat(self, messages: list[LLMMessage], config: LLMConfig) -> LLMResponse:
        system = next((m.content for m in messages if m.role == "system"), "")
        if "analyst" in system.lower() or "metric" in system.lower():
            content = (
                "## Key Financial Metrics\n\n"
                "- Revenue: $2.3B (+15% YoY)\n"
                "- Operating margin: 18% (up from 12%)\n"
                "- Gross margin: 64.2%\n"
                "- Free cash flow: $890M\n\n"
                "## Key Takeaways\n\n"
                "1. Cloud services drove 40% of revenue growth\n"
                "2. International expansion contributed 25% of new revenue\n"
                "3. R&D investment increased to 22% of revenue\n"
                "4. Guidance raised for next quarter: $2.5B revenue target"
            )
            usage = TokenUsage(prompt_tokens=200, completion_tokens=120, total_tokens=320)
        else:
            content = (
                "# ACME Corp Q4 Earnings -- Executive Summary\n\n"
                "ACME Corp delivered strong Q4 results, with revenue reaching $2.3B, "
                "a 15% year-over-year increase driven primarily by cloud services growth. "
                "Operating margins improved significantly from 12% to 18%, reflecting "
                "operational efficiency gains and favorable revenue mix.\n\n"
                "The company's cloud services segment was the standout performer, "
                "contributing 40% of revenue growth. International markets added 25% "
                "of new revenue, validating the expansion strategy initiated in Q2.\n\n"
                "Looking ahead, management raised guidance to $2.5B for Q1, "
                "supported by strong pipeline visibility and continued R&D investment "
                "at 22% of revenue. Free cash flow of $890M provides ample runway "
                "for strategic acquisitions and share buybacks."
            )
            usage = TokenUsage(prompt_tokens=350, completion_tokens=180, total_tokens=530)
        return LLMResponse(content=content, model="mock-model", usage=usage)


# ---------------------------------------------------------------------------
# Provider factory
# ---------------------------------------------------------------------------

def get_provider() -> tuple[LLMProvider, str | None]:
    """Return Azure provider if AZURE_OPENAI_ENDPOINT is set, else mock."""
    if os.environ.get("AZURE_OPENAI_ENDPOINT"):
        from hiveflow.plugins.llm.azure_provider import AzureOpenAIProvider
        endpoint = os.environ["AZURE_OPENAI_ENDPOINT"]
        deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
        return AzureOpenAIProvider(azure_endpoint=endpoint), deployment
    return MockProvider(), None


# ---------------------------------------------------------------------------
# Sample document
# ---------------------------------------------------------------------------

SAMPLE_EARNINGS = """\
ACME Corp Q4 2025 Earnings Call Transcript

CFO: Total revenue for Q4 came in at $2.3 billion, representing 15% growth
year-over-year. Operating margins improved to 18%, up from 12% in the prior
year period. Gross margins were 64.2%.

Cloud services revenue grew 40% to $920 million, now representing our largest
segment. Enterprise subscriptions grew 28% with net retention rate of 125%.

International revenue reached $575 million, contributing 25% of total. Our
expansion into APAC markets drove a significant portion of this growth.

R&D investment was $506 million, or 22% of revenue, reflecting our continued
commitment to product innovation. Key launches included AI-powered analytics
and our new developer platform.

Free cash flow was $890 million. We returned $400 million to shareholders
through buybacks and dividends.

Looking ahead, we're raising our Q1 guidance to $2.5 billion in revenue
with operating margins of 19-20%, reflecting strong pipeline visibility
and operational leverage.
"""


async def main() -> None:
    """Run the document summarization workflow."""
    print("=" * 60)
    print("  HiveFlow -- Document Summarizer")
    print("=" * 60)

    provider, model = get_provider()
    model_kwarg = {"model": f"azure:{model}"} if model else {}
    live = model is not None
    print(f"  Provider: {'Azure OpenAI' if live else 'Mock (no API key)'}")

    # Create a temp directory with the sample document
    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir)
        doc_path = work_dir / "earnings_call.txt"
        doc_path.write_text(SAMPLE_EARNINGS)

        # Load document via the pipeline
        registry = DocumentLoaderRegistry()
        pipeline = DocumentPipeline(registry=registry, working_dir=work_dir)
        docs, summary = await pipeline.load(["earnings_call.txt"])
        print(f"  Documents: {summary}")

        # Build agents
        analyst = Agent(
            agent_id="analyst",
            role="Financial Analyst",
            system_prompt=(
                "You are a financial analyst. Extract key financial metrics "
                "and strategic takeaways from the earnings call transcript. "
                "Present them in a structured format with clear categories."
            ),
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=provider,
            **model_kwarg,
        )

        writer = Agent(
            agent_id="writer",
            role="Executive Summary Writer",
            system_prompt=(
                "You are a senior business writer. Using the analyst's "
                "findings, write a polished executive summary (200-300 words) "
                "suitable for board presentation. Include a title."
            ),
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=provider,
            **model_kwarg,
        )

        # Build workflow
        steps = [
            WorkflowStep(agent="analyst", step_type="sequential", next_step="writer"),
            WorkflowStep(agent="writer", step_type="sequential"),
        ]
        engine = WorkflowEngine(steps, assembly_agents=["writer"])

        def on_event(event_type: str, agent_id: str, data: dict) -> None:
            if event_type == "step_start":
                print(f"\n  > {agent_id}...", flush=True)
            elif event_type == "step_complete":
                print(f"  * {agent_id} done", flush=True)

        engine.on_event(on_event)

        # Execute
        t0 = time.time()
        result = await engine.execute(
            agents={"analyst": analyst, "writer": writer},
            initial_state={
                "task": "Analyze and summarize the Q4 earnings call",
                "documents": docs,
            },
        )
        elapsed = time.time() - t0

        # Display results
        print(f"\n{'-' * 60}")
        print(f"Status:  {result.status.value}")
        print(f"Elapsed: {elapsed:.1f}s")

        for aid in ["analyst", "writer"]:
            output = result.state.get(f"{aid}_output", "")
            usage = result.state.get(f"{aid}_usage", {})
            words = len(output.split()) if output else 0
            tokens = usage.get("total_tokens", 0) if usage else 0
            print(f"  {aid:10s}  {words:4d} words  {tokens:4d} tokens")

        # Show outputs
        print(f"\n{'-' * 60}")
        print("Analyst output:")
        print("-" * 60)
        print(result.state.get("analyst_output", "(no output)"))

        print(f"\n{'-' * 60}")
        print("Writer output (Executive Summary):")
        print("-" * 60)
        final = result.state.get("final_output", result.state.get("writer_output", ""))
        print(final)

        # Write output to file
        output_path = Path("output/document_summarizer.md")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(final, encoding="utf-8")
        print(f"\n  Output saved: {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
