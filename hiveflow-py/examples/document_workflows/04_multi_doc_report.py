#!/usr/bin/env python3
"""Document Workflows 04: Multi-document report with per-agent scoping.

Loads three project documents and routes them through a three-agent pipeline
where each agent sees a different document slice:

  1. **Analyst** (full access) -- reads all documents, extracts risk items
  2. **Planner** (filtered)   -- sees only sprint retro + QA report, plans next steps
  3. **Writer** (no docs)     -- synthesizes a status report from prior agent outputs

Demonstrates:
  - Per-agent document scoping (full, filtered by name, none)
  - Three-step sequential workflow with output propagation
  - Different document_mode settings controlling what each agent sees

Uses mock LLM by default. Set AZURE_OPENAI_ENDPOINT for live results.

Usage:
    uv run python examples/document_workflows/04_multi_doc_report.py

Expected output:
    See sample_output/document_workflows/04_multi_doc_report.txt
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
# Sample documents
# ---------------------------------------------------------------------------

PRODUCT_REQUIREMENTS = """\
Product Requirements: AI Search v2.0

Priority 1 (Must-have):
- Semantic search with vector embeddings
- Sub-200ms p95 latency
- Support for 10M+ documents

Priority 2 (Should-have):
- Multi-language support (EN, ES, FR, DE)
- Faceted filtering
- Query suggestions / autocomplete

Priority 3 (Nice-to-have):
- Visual similarity search
- Federated search across data sources
"""

SPRINT_RETRO = """\
Sprint Retro: Sprint 23 (2025-02-10 -- 2025-02-21)

## What went well
- Semantic search prototype delivered on schedule
- Vector embedding pipeline handles 500K docs/hour
- Team collaboration between ML and platform teams improved

## What didn't go well
- Latency regression: p95 jumped from 180ms to 340ms after embedding integration
- 3 out of 5 planned stories missed due to scope creep
- Test coverage dropped from 87% to 72%

## Action Items
- [OWNER: Alice] Profile and fix latency regression by Sprint 24
- [OWNER: Bob] Implement query caching to meet latency SLA
- [OWNER: Carol] Restore test coverage to >85% before feature freeze
"""

QA_REPORT = """\
QA Report: AI Search v2.0 Beta

Test Execution Summary:
- Total test cases: 847
- Passed: 612 (72.3%)
- Failed: 89 (10.5%)
- Blocked: 146 (17.2%)

Critical Bugs:
- BUG-301: Search returns 0 results for queries with special characters
- BUG-302: Memory leak in embedding service (OOM after 4 hours)
- BUG-303: Race condition in concurrent index updates

Performance Baseline:
- p50 latency: 120ms (target: <100ms)
- p95 latency: 340ms (target: <200ms) <- REGRESSION
- p99 latency: 890ms (target: <500ms) <- REGRESSION
- Throughput: 1,200 queries/sec (target: 2,000)

Recommendation: Do NOT release to production until BUG-302 (memory leak)
and latency regression are resolved.
"""


# ---------------------------------------------------------------------------
# Mock provider
# ---------------------------------------------------------------------------

class MockProvider(LLMProvider):
    """Returns mock responses for each agent role."""

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def plugin_id(self) -> str:
        return "mock"

    @property
    def description(self) -> str:
        return "Mock LLM for multi-doc demo"

    async def chat(self, messages: list[LLMMessage], config: LLMConfig) -> LLMResponse:
        system = next((m.content for m in messages if m.role == "system"), "")

        if "risk" in system.lower() or "analyst" in system.lower():
            content = (
                "## Risk Analysis\n\n"
                "**Critical Risks:**\n"
                "1. Latency regression (p95: 340ms vs 200ms target) blocks release\n"
                "2. Memory leak (BUG-302) causes OOM after 4 hours -- production blocker\n"
                "3. 17.2% blocked test cases suggest infrastructure instability\n\n"
                "**Medium Risks:**\n"
                "4. Test coverage dropped to 72% -- below quality bar\n"
                "5. Race condition in concurrent updates (BUG-303)\n"
                "6. Throughput at 60% of target (1,200 vs 2,000 qps)\n\n"
                "**Recommendation:** Delay release until items 1-3 are resolved."
            )
        elif "planner" in system.lower() or "next step" in system.lower():
            content = (
                "## Sprint 24 Plan\n\n"
                "**Week 1 -- Critical fixes:**\n"
                "- Alice: Profile latency regression, implement optimization\n"
                "- Bob: Implement query caching layer\n"
                "- DevOps: Fix BUG-302 memory leak in embedding service\n\n"
                "**Week 2 -- Quality restoration:**\n"
                "- Carol: Restore test coverage to >85%\n"
                "- Team: Unblock 146 blocked test cases\n"
                "- Alice: Validate latency targets after optimization\n\n"
                "**Release gate:** All critical bugs resolved + p95 < 200ms"
            )
        else:
            content = (
                "# AI Search v2.0 -- Project Status Report\n\n"
                "## Executive Summary\n"
                "Sprint 23 delivered the semantic search prototype on schedule, but "
                "introduced critical performance regressions that block the v2.0 release.\n\n"
                "## Key Findings\n"
                "The risk analysis identified 3 critical blockers: latency regression "
                "(p95 at 340ms vs 200ms target), a memory leak causing OOM after 4 hours, "
                "and 17% blocked test cases indicating infrastructure instability.\n\n"
                "## Recommended Plan\n"
                "Sprint 24 should focus exclusively on critical fixes in Week 1 "
                "(latency optimization, query caching, memory leak fix) followed by "
                "quality restoration in Week 2. No new features until the release "
                "gate is passed: all critical bugs resolved and p95 < 200ms."
            )

        usage = TokenUsage(prompt_tokens=300, completion_tokens=150, total_tokens=450)
        return LLMResponse(content=content, model="mock-model", usage=usage)


def get_provider() -> tuple[LLMProvider, str | None]:
    """Return Azure provider if configured, else mock."""
    if os.environ.get("AZURE_OPENAI_ENDPOINT"):
        from hiveflow.plugins.llm.azure_provider import AzureOpenAIProvider
        endpoint = os.environ["AZURE_OPENAI_ENDPOINT"]
        deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
        return AzureOpenAIProvider(azure_endpoint=endpoint), deployment
    return MockProvider(), None


async def main() -> None:
    """Run the multi-document report workflow."""
    print("=" * 60)
    print("  HiveFlow -- Multi-Document Report with Per-Agent Scoping")
    print("=" * 60)

    provider, model = get_provider()
    model_kwarg = {"model": f"azure:{model}"} if model else {}
    print(f"  Provider: {'Azure OpenAI' if model else 'Mock (no API key)'}")

    # Create temp directory with sample documents
    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir)
        (work_dir / "product_requirements.txt").write_text(PRODUCT_REQUIREMENTS)
        (work_dir / "sprint_retro.md").write_text(SPRINT_RETRO)
        (work_dir / "qa_report.txt").write_text(QA_REPORT)

        # Load all documents
        registry = DocumentLoaderRegistry()
        pipeline = DocumentPipeline(registry=registry, working_dir=work_dir)
        docs, summary = await pipeline.load([
            "product_requirements.txt",
            "sprint_retro.md",
            "qa_report.txt",
        ])
        print(f"  Documents: {summary}")

        # Show per-agent scoping
        agent_defs = {
            "analyst": AgentDefinition(
                id="analyst", role="Risk Analyst",
                system_prompt="Analyze risks across all documents.",
                behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
                document_mode="full",
            ),
            "planner": AgentDefinition(
                id="planner", role="Sprint Planner",
                system_prompt="Plan next steps from recent sprints.",
                behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
                documents=["sprint_retro.md", "qa_report.txt"],
                document_mode="full",
            ),
            "writer": AgentDefinition(
                id="writer", role="Status Writer",
                system_prompt="Write status report from prior analysis.",
                behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
                document_mode="none",
            ),
        }

        print(f"\n  Document scoping:")
        for name, agent_def in agent_defs.items():
            scoped = pipeline.scope_for_agent(docs, agent_def)
            doc_names = [d["name"] for d in scoped]
            mode = agent_def.document_mode or "none"
            print(f"    {name:10s} mode={mode:14s} -> sees {len(scoped)} doc(s): {doc_names}")

        # Build agents
        agents = {}
        for name in ["analyst", "planner", "writer"]:
            agents[name] = Agent(
                agent_id=name,
                role=agent_defs[name].role,
                system_prompt=agent_defs[name].system_prompt,
                behavior_type=AgentBehaviorType.LLM_ONLY,
                llm_provider=provider,
                **model_kwarg,
            )

        # Build workflow
        steps = [
            WorkflowStep(agent="analyst", step_type="sequential", next_step="planner"),
            WorkflowStep(agent="planner", step_type="sequential", next_step="writer"),
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
            agents=agents,
            initial_state={
                "task": "Produce a project status report",
                "documents": docs,
            },
        )
        elapsed = time.time() - t0

        # Display results
        print(f"\n{'-' * 60}")
        print(f"Status:  {result.status.value}")
        print(f"Elapsed: {elapsed:.1f}s")

        for name in ["analyst", "planner", "writer"]:
            output = result.state.get(f"{name}_output", "")
            usage = result.state.get(f"{name}_usage", {})
            words = len(output.split()) if output else 0
            tokens = usage.get("total_tokens", 0) if usage else 0
            print(f"  {name:10s}  {words:4d} words  {tokens:4d} tokens")

        # Show each agent's output
        for name in ["analyst", "planner", "writer"]:
            output = result.state.get(f"{name}_output", "")
            if output:
                print(f"\n{'-' * 60}")
                print(f"{name} output:")
                print("-" * 60)
                print(output)

        # Save final output
        final = result.state.get("final_output", result.state.get("writer_output", ""))
        if final:
            output_path = Path("output/multi_doc_report.md")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(final, encoding="utf-8")
            print(f"\n  Output saved: {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
