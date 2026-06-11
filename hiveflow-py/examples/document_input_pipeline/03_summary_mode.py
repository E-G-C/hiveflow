#!/usr/bin/env python3
"""Document Input Pipeline 03: Summary Document Mode (LLM-Based).

Demonstrates User Story 3 -- agents with ``document_mode="summary"`` receive
a concise LLM-generated summary of each document instead of raw chunks.

What this example covers:
  - DocumentPipeline.generate_summaries() with a live LLM
  - Summary caching in workflow state (second agent reuses, no extra LLM call)
  - scope_for_agent() returning single summary chunks
  - Fallback to metadata_only when no LLM is available
  - Token savings comparison: full vs summary mode
  - Running summaries through WorkflowEngine automatically

Uses the Azure OpenAI endpoint at foundry-aisbx-we.cognitiveservices.azure.com.

Usage:
    $env:AZURE_OPENAI_ENDPOINT = "https://foundry-aisbx-we.cognitiveservices.azure.com"
    uv run python examples/document_input_pipeline/03_summary_mode.py
"""

import asyncio
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from _helpers import get_provider, is_live, print_kv, print_section

from hiveflow import Agent, AgentBehaviorType, WorkflowEngine, WorkflowStep
from hiveflow.core.documents import DocumentPipeline
from hiveflow.core.schema import AgentBehaviorTypeSchema, AgentDefinition
from hiveflow.plugins.documents import DocumentLoaderRegistry


# ---------------------------------------------------------------------------
# Sample documents
# ---------------------------------------------------------------------------

ARCHITECTURE_DOC = """\
# System Architecture -- Order Processing Platform

## Overview
The order processing platform handles 200K+ orders daily across three
geographic regions (US, EU, APAC). Built on a microservices architecture
deployed on Kubernetes with PostgreSQL and Redis as primary data stores.

## Service Topology
1. **API Gateway** (Kong) -- rate limiting, auth, routing
2. **Order Service** -- order lifecycle management, validation
3. **Payment Service** -- payment processing, refunds, fraud checks
4. **Inventory Service** -- stock management, reservations
5. **Notification Service** -- email, SMS, push notifications
6. **Analytics Service** -- real-time dashboards, reporting

## Data Flow
Orders enter through the API Gateway, are validated by the Order Service,
payment is processed asynchronously via the Payment Service, inventory is
reserved by the Inventory Service, and confirmations are sent by the
Notification Service. All events are published to Kafka for analytics.

## Reliability
- Circuit breakers on all inter-service calls (Resilience4j)
- Automatic retries with exponential backoff
- Database read replicas for reporting queries
- Active-passive failover for payment processing
- Daily automated backups with point-in-time recovery
"""

INCIDENT_DOC = """\
# Incident Report: Order Processing Delays -- Feb 15, 2026

## Summary
Orders experienced 15-45 minute processing delays between 09:00-11:30 UTC.
Approximately 8,200 orders were affected. No data loss occurred.

## Timeline
- 09:00 UTC: Kafka consumer lag alerts triggered
- 09:15 UTC: Investigation started -- consumer lag growing at 500 msgs/min
- 09:30 UTC: Root cause identified -- inventory service database connection
  pool exhausted (max_connections=50, all in use)
- 09:45 UTC: Temporary fix applied -- increased pool to 100 connections
- 10:15 UTC: Consumer lag stabilizing
- 11:30 UTC: All backlog cleared, normal operation restored

## Root Cause
A slow query in the inventory reservation path (avg 2.3s, previously 50ms)
caused connection pool exhaustion. The slow query was traced to a missing
index on the `reservations` table after a schema migration on Feb 14.

## Impact
- 8,200 orders delayed (4.1% of daily volume)
- 12 customer complaints received
- No revenue lost (all orders eventually processed)
- SLA breach: p99 latency exceeded 30s target for 2.5 hours

## Action Items
- [DONE] Added missing index on reservations table
- [DONE] Increased connection pool to 100 with monitoring
- [TODO] Add query performance regression tests to CI
- [TODO] Implement connection pool exhaustion alerts
- [TODO] Review all recent schema migrations for index coverage
"""

ROADMAP_DOC = """\
# Product Roadmap -- Q1 2026

## Theme: Reliability & Scale

### Milestone 1: Infrastructure Hardening (Jan-Feb)
- Implement connection pool monitoring and auto-scaling
- Add query performance regression tests to CI pipeline
- Deploy database read replicas in APAC region
- Upgrade Kafka cluster to handle 2x current throughput

### Milestone 2: Developer Experience (Feb-Mar)
- Launch developer portal with API documentation
- Implement SDK for Python, JavaScript, and Go
- Add OpenTelemetry distributed tracing across all services
- Create runbook automation for common incident responses

### Milestone 3: New Capabilities (Mar)
- Multi-currency support for EU and APAC markets
- Real-time order tracking with WebSocket notifications
- Bulk order API for enterprise customers
- Advanced fraud detection with ML model integration

## Success Metrics
- p99 latency < 500ms for order placement
- Zero unplanned downtime (99.99% availability target)
- Developer onboarding time < 1 hour
- 50% reduction in mean-time-to-resolve for incidents
"""


async def demo_generate_summaries() -> None:
    """Part 1: Generate LLM summaries for loaded documents."""
    print_section("1. Generate Document Summaries via LLM")

    provider, deployment = get_provider()
    print_kv("Provider", f"{provider.plugin_id}:{deployment}")

    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir)
        (work_dir / "architecture.md").write_text(ARCHITECTURE_DOC, encoding="utf-8")
        (work_dir / "incident.md").write_text(INCIDENT_DOC, encoding="utf-8")
        (work_dir / "roadmap.md").write_text(ROADMAP_DOC, encoding="utf-8")

        pipeline = DocumentPipeline(working_dir=work_dir)
        docs, summary = await pipeline.load([
            "architecture.md",
            "incident.md",
            "roadmap.md",
        ])
        print(f"  Loaded: {summary}\n")

        # Generate summaries
        state: dict = {"documents": docs}
        t0 = time.time()
        summaries = await pipeline.generate_summaries(
            docs, state, provider, max_tokens=150,
        )
        gen_time = time.time() - t0

        print(f"  Generated {len(summaries)} summaries in {gen_time:.1f}s:\n")
        for name, text in summaries.items():
            words = len(text.split())
            print(f"  [{name}] ({words} words)")
            # Show first 2 lines of summary
            lines = text.strip().splitlines()
            for line in lines[:3]:
                print(f"    {line}")
            if len(lines) > 3:
                print(f"    ...")
            print()


async def demo_summary_caching() -> None:
    """Part 2: Verify that summaries are cached -- second call skips LLM."""
    print_section("2. Summary Caching (No Duplicate LLM Calls)")

    provider, deployment = get_provider()

    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir)
        (work_dir / "architecture.md").write_text(ARCHITECTURE_DOC, encoding="utf-8")
        (work_dir / "incident.md").write_text(INCIDENT_DOC, encoding="utf-8")

        pipeline = DocumentPipeline(working_dir=work_dir)
        docs, _ = await pipeline.load(["architecture.md", "incident.md"])

        state: dict = {"documents": docs}

        # First call: generates summaries (contacts LLM)
        t0 = time.time()
        summaries_1 = await pipeline.generate_summaries(docs, state, provider)
        first_time = time.time() - t0
        print_kv("First call", f"{first_time:.2f}s -- {len(summaries_1)} summaries generated")

        # Second call: should hit cache (instant)
        t0 = time.time()
        summaries_2 = await pipeline.generate_summaries(docs, state, provider)
        second_time = time.time() - t0
        print_kv("Second call", f"{second_time:.4f}s -- cache hit, 0 LLM calls")

        # Verify same content
        assert summaries_1 == summaries_2, "Cache returned different content!"
        print("\n  Cache verified: identical summaries, no re-generation.")


async def demo_scope_for_agent_summary() -> None:
    """Part 3: scope_for_agent with summary mode returns single summary chunks."""
    print_section("3. scope_for_agent() with Summary Mode")

    provider, deployment = get_provider()

    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir)
        (work_dir / "architecture.md").write_text(ARCHITECTURE_DOC, encoding="utf-8")
        (work_dir / "incident.md").write_text(INCIDENT_DOC, encoding="utf-8")

        pipeline = DocumentPipeline(working_dir=work_dir)
        docs, _ = await pipeline.load(["architecture.md", "incident.md"])

        # Generate summaries first
        state: dict = {"documents": docs}
        await pipeline.generate_summaries(docs, state, provider)

        # Define agents with different document modes
        agents = {
            "full": AgentDefinition(
                id="full_agent",
                role="Full Access",
                system_prompt="See all content.",
                behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
                document_mode="full",
            ),
            "summary": AgentDefinition(
                id="summary_agent",
                role="Summary Access",
                system_prompt="See summaries only.",
                behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
                document_mode="summary",
            ),
            "metadata": AgentDefinition(
                id="meta_agent",
                role="Metadata Only",
                system_prompt="See metadata.",
                behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
                document_mode="metadata_only",
            ),
        }

        print(f"  {'Mode':<12}  {'Docs':<5}  {'Chunks':<8}  {'Est. Tokens':<12}")
        print(f"  {'-' * 45}")

        for mode_name, agent_def in agents.items():
            scoped = pipeline.scope_for_agent(docs, agent_def, state=state)
            total_chunks = sum(d.get("chunk_count", 0) for d in scoped)
            total_tokens = sum(d.get("total_tokens_estimate", 0) for d in scoped)
            print(f"  {mode_name:<12}  {len(scoped):<5}  {total_chunks:<8}  ~{total_tokens:<11}")

        print("\n  Summary mode: fewer chunks, far fewer tokens -> big cost savings.")

        # Show what the summary agent actually sees
        summary_scoped = pipeline.scope_for_agent(
            docs,
            agents["summary"],
            state=state,
        )
        print("\n  Summary agent view:")
        for doc in summary_scoped:
            print(f"    [{doc['name']}] chunk_count={doc['chunk_count']}")
            for chunk in doc.get("chunks", []):
                preview = chunk["content"][:100].replace("\n", " ")
                print(f"      -> {preview}...")


async def demo_fallback_no_llm() -> None:
    """Part 4: Fallback to metadata_only when no LLM is available."""
    print_section("4. Fallback: No LLM -> metadata_only")

    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir)
        (work_dir / "doc.txt").write_text("Some document content here.", encoding="utf-8")

        pipeline = DocumentPipeline(working_dir=work_dir)
        docs, _ = await pipeline.load(["doc.txt"])

        # State without cached summaries
        state: dict = {"documents": docs}

        summary_agent = AgentDefinition(
            id="needs_summary",
            role="Summary Agent",
            system_prompt="Show me summaries.",
            behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
            document_mode="summary",
        )

        scoped = pipeline.scope_for_agent(docs, summary_agent, state=state)
        print("  No summaries cached -> graceful fallback:")
        for doc in scoped:
            has_chunks = bool(doc.get("chunks"))
            print(f"    {doc['name']}: chunks={has_chunks}, keys={sorted(doc.keys())}")
        print("\n  Falls back to metadata_only (no content, no crash).")


async def demo_workflow_with_summary_mode() -> None:
    """Part 5: Full workflow with summary mode -- engine auto-generates summaries."""
    print_section("5. Workflow Engine with Summary Mode Agents")

    provider, deployment = get_provider()
    model_str = f"{provider.plugin_id}:{deployment}"
    print_kv("Provider", model_str)

    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir)
        (work_dir / "architecture.md").write_text(ARCHITECTURE_DOC, encoding="utf-8")
        (work_dir / "incident.md").write_text(INCIDENT_DOC, encoding="utf-8")
        (work_dir / "roadmap.md").write_text(ROADMAP_DOC, encoding="utf-8")

        # Load documents
        pipeline = DocumentPipeline(working_dir=work_dir)
        docs, doc_summary = await pipeline.load([
            "architecture.md", "incident.md", "roadmap.md",
        ])

        # Agent definitions (with document_mode="summary")
        planner_def = AgentDefinition(
            id="planner",
            role="Project Planner",
            system_prompt=(
                "You are a project planner. Review the document summaries and "
                "identify the top 3 priorities based on the architecture, "
                "incident report, and roadmap. Be concise."
            ),
            behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
            document_mode="summary",
            max_document_tokens=500,
        )

        reviewer_def = AgentDefinition(
            id="reviewer",
            role="Technical Reviewer",
            system_prompt=(
                "You are a technical reviewer. Based on the document summaries "
                "and the planner's priorities, assess feasibility and risks. "
                "Keep your review under 200 words."
            ),
            behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
            document_mode="summary",
            max_document_tokens=500,
        )

        # Build agents
        planner = Agent(
            agent_id="planner",
            role=planner_def.role,
            system_prompt=planner_def.system_prompt,
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=provider,
            model=model_str,
            agent_definition=planner_def,
        )

        reviewer = Agent(
            agent_id="reviewer",
            role=reviewer_def.role,
            system_prompt=reviewer_def.system_prompt,
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=provider,
            model=model_str,
            agent_definition=reviewer_def,
        )

        # Workflow: planner → reviewer
        steps = [
            WorkflowStep(agent="planner", step_type="sequential", next_step="reviewer"),
            WorkflowStep(agent="reviewer", step_type="sequential"),
        ]
        engine = WorkflowEngine(steps, document_pipeline=pipeline)

        # Event callback
        def on_event(event_type: str, agent_id: str, data: dict) -> None:
            if event_type == "step_start":
                print(f"\n    > Running {agent_id}...", flush=True)
            elif event_type == "step_complete":
                print(f"    * {agent_id} complete", flush=True)

        engine.on_event(on_event)

        # Execute
        t0 = time.time()
        result = await engine.execute(
            agents={"planner": planner, "reviewer": reviewer},
            initial_state={
                "task": "Review the system and prioritize improvements",
                "documents": docs,
                "document_summary": doc_summary,
            },
        )
        elapsed = time.time() - t0

        print(f"\n  Status: {result.status.value}, elapsed: {elapsed:.1f}s")

        # Check that summaries were cached
        cached = result.state.get("_document_summaries", {})
        print(f"  Cached summaries: {len(cached)} documents")

        # Show outputs
        for agent_id in ["planner", "reviewer"]:
            output = result.state.get(f"{agent_id}_output", "")
            if output:
                print(f"\n  --- {agent_id} output ---")
                for line in output.splitlines()[:10]:
                    print(f"  {line}")
                if len(output.splitlines()) > 10:
                    print(f"  ... ({len(output.splitlines())} lines total)")


async def main() -> None:
    print("=" * 64)
    print("  Document Input Pipeline -- 03: Summary Document Mode")
    print("=" * 64)

    await demo_generate_summaries()
    await demo_summary_caching()
    await demo_scope_for_agent_summary()
    await demo_fallback_no_llm()
    await demo_workflow_with_summary_mode()

    print_section("Done")
    print("  All summary mode demonstrations completed successfully.")


if __name__ == "__main__":
    asyncio.run(main())
