#!/usr/bin/env python3
"""Document Input Pipeline 05: Full Pipeline -- All 4 Enhancements.

End-to-end example combining every enhancement from spec 009:

  1. **instructions_file** -- Workflow instructions loaded from a markdown file
  2. **load_from_bytes** -- Some documents arrive as byte streams (e.g. uploads)
  3. **summary mode** -- Planner agent sees LLM-generated summaries, not raw chunks
  4. **template variables** -- Agent prompts use $document_count, $document_names

Scenario: An engineering team receives a project proposal (file), a risk
assessment (byte upload), and a competitor analysis (inline text). Three
agents collaborate -- analyst (full docs), planner (summaries), and writer
(template variables + metadata) -- to produce a decision brief.

Uses the live Azure OpenAI endpoint for all LLM calls.

Usage:
    $env:AZURE_OPENAI_ENDPOINT = "https://foundry-aisbx-we.cognitiveservices.azure.com"
    uv run python examples/document_input_pipeline/05_full_pipeline.py
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
# Instructions file content (Enhancement 1)
# ---------------------------------------------------------------------------

INSTRUCTIONS_MD = """\
# Decision Brief -- Instructions

Produce a structured decision brief for the executive team covering:

1. **Executive Summary** (3-4 sentences max)
2. **Opportunity Assessment** -- What is the potential upside?
3. **Risk Analysis** -- Top 3 risks with severity ratings
4. **Competitive Position** -- How does this compare to alternatives?
5. **Recommendation** -- Clear GO / NO-GO / CONDITIONAL-GO with rationale

Guidelines:
- Be concise: total brief should be under 500 words
- Use bullet points where possible
- Rate risks as HIGH / MEDIUM / LOW
- Reference specific documents to support claims
"""

# ---------------------------------------------------------------------------
# Document content -- mixed sources
# ---------------------------------------------------------------------------

# Source 1: File on disk
PROPOSAL_FILE_CONTENT = """\
# Platform Modernization Proposal

## Background
Our current monolithic e-commerce platform processes 50K orders/day but is
reaching capacity limits. Peak-hour response times have increased 40% YoY.

## Proposal
Migrate to a microservices architecture over 9 months:
- Phase 1 (3 months): Extract payment and inventory services
- Phase 2 (3 months): Build new API gateway and order service
- Phase 3 (3 months): Migration, testing, and cutover

## Investment
- Team: 6 engineers, 1 architect, 1 PM (9 months)
- Infrastructure: $180K additional cloud spend during migration
- Total estimated cost: $1.2M

## Expected Outcomes
- 3x throughput capacity (50K → 150K orders/day)
- 60% reduction in p99 latency
- Independent service deployments (faster release cycles)
- Better fault isolation (no cascading failures)
"""

# Source 2: Byte stream (simulating an HTTP upload) -- Enhancement 2
RISK_ASSESSMENT_BYTES = """\
# Risk Assessment: Platform Modernization

## Technical Risks
1. **Data migration** (HIGH): Moving 5 years of order history requires
   careful schema mapping. Estimated 2TB of data.
2. **Service boundaries** (MEDIUM): Incorrect domain boundaries will
   create distributed monolith anti-pattern.
3. **Observability gap** (MEDIUM): Current monitoring tools won't work
   across microservices without significant investment.

## Organizational Risks
4. **Team readiness** (HIGH): Only 2 of 6 engineers have microservices
   experience. Training needed.
5. **Timeline pressure** (MEDIUM): 9-month timeline is aggressive given
   team experience level.

## Mitigation Strategies
- Hire 1 senior architect with microservices migration experience
- Start with strangler fig pattern instead of big-bang rewrite
- Invest in OpenTelemetry from day 1
- Build automated data migration pipeline with rollback capability
- Add 2-month buffer to timeline (11 months total)
""".encode("utf-8")

# Source 3: Inline text content
COMPETITOR_ANALYSIS_INLINE = {
    "name": "competitor-analysis.txt",
    "content": """\
Competitor Analysis: Platform Modernization

Competitor A (TechRival):
- Completed similar migration in 2024, took 14 months (planned 10)
- Reported 30% improvement in throughput but 4 weeks of degraded service
- Key lesson: underestimated integration testing time

Competitor B (ShopFast):
- Still on monolith, investing in vertical scaling
- Achieved 80K orders/day with hardware upgrades ($500K/year)
- Plans to revisit microservices in 2027

Industry benchmark:
- Average microservices migration takes 12-18 months for similar scale
- Success rate: ~65% complete on time, ~40% within budget
- Top failure mode: underestimating operational complexity

Our advantage: Strong DevOps culture, existing CI/CD pipeline,
containerized development already in place.
""",
}


async def main() -> None:
    print("=" * 64)
    print("  Document Input Pipeline -- 05: Full Pipeline")
    print("  Combining all 4 enhancements in one workflow")
    print("=" * 64)

    provider, deployment = get_provider()
    model_str = f"{provider.plugin_id}:{deployment}"
    mode = "Azure OpenAI" if is_live() else "Mock"

    print_kv("\nProvider", f"{mode} ({model_str})")

    # -----------------------------------------------------------------------
    # Step 1: Set up files and byte sources
    # -----------------------------------------------------------------------
    print_section("Step 1: Prepare Documents (File + Bytes + Inline)")

    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir)

        # Enhancement 1: Instructions file on disk
        instr_path = work_dir / "instructions.md"
        instr_path.write_text(INSTRUCTIONS_MD, encoding="utf-8")
        print_kv("Instructions file", "instructions.md (Enhancement 1)")

        # Source 1: Proposal file on disk
        proposal_path = work_dir / "proposal.md"
        proposal_path.write_text(PROPOSAL_FILE_CONTENT, encoding="utf-8")
        print_kv("File document", "proposal.md")

        # Source 2: Risk assessment as bytes (Enhancement 2)
        print_kv("Bytes document", "risk-assessment.md (simulated upload)")

        # Source 3: Inline competitor analysis
        print_kv("Inline document", "competitor-analysis.txt")

        # -----------------------------------------------------------------------
        # Step 2: Load instructions from file (Enhancement 1)
        # -----------------------------------------------------------------------
        print_section("Step 2: Load Instructions from File (Enhancement 1)")

        pipeline = DocumentPipeline(working_dir=work_dir)
        instructions = await pipeline.load_instructions_file("instructions.md")
        print(f"  Loaded {len(instructions)} chars of instructions")
        print(f"  First line: {instructions.splitlines()[0]}")

        # -----------------------------------------------------------------------
        # Step 3: Load documents from mixed sources (Enhancement 2)
        # -----------------------------------------------------------------------
        print_section("Step 3: Load Documents -- Mixed Sources (Enhancement 2)")

        docs, doc_summary = await pipeline.load([
            # File on disk
            "proposal.md",
            # Byte stream (simulated HTTP upload)
            {"name": "risk-assessment.md", "bytes": RISK_ASSESSMENT_BYTES},
            # Inline content
            COMPETITOR_ANALYSIS_INLINE,
        ])

        print(f"  {doc_summary}\n")
        for doc in docs:
            source = "file" if doc["name"] == "proposal.md" else (
                "bytes" if doc["name"] == "risk-assessment.md" else "inline"
            )
            print(f"    [{source:6s}] {doc['name']:30s} "
                  f"{doc['chunk_count']} chunk(s), ~{doc['total_tokens_estimate']} tokens")

        # -----------------------------------------------------------------------
        # Step 4: Generate document summaries (Enhancement 3)
        # -----------------------------------------------------------------------
        print_section("Step 4: Generate LLM Summaries (Enhancement 3)")

        state: dict = {"documents": docs, "document_summary": doc_summary}

        t0 = time.time()
        summaries = await pipeline.generate_summaries(
            docs, state, provider, max_tokens=150,
        )
        summary_time = time.time() - t0

        print(f"  Generated {len(summaries)} summaries in {summary_time:.1f}s:\n")
        for name, text in summaries.items():
            preview = text[:120].replace("\n", " ")
            print(f"    {name}: {preview}...")

        # -----------------------------------------------------------------------
        # Step 5: Build workflow with different document modes
        # -----------------------------------------------------------------------
        print_section("Step 5: Build Multi-Agent Workflow")

        # Agent 1: Analyst -- sees FULL documents
        analyst_def = AgentDefinition(
            id="analyst",
            role="Technical Analyst",
            system_prompt=(
                "You are a technical analyst reviewing $document_count document(s): "
                "$document_names.\n\n"
                "Extract key facts: costs, timelines, team size, risks, and "
                "competitive insights. Output a structured analysis with "
                "clear categories. Be comprehensive but concise."
            ),
            behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
            document_mode="full",
        )

        # Agent 2: Planner -- sees SUMMARIES only (Enhancement 3)
        planner_def = AgentDefinition(
            id="planner",
            role="Strategic Planner",
            system_prompt=(
                "You are a strategic planner. You have summaries of "
                "$document_count document(s): $document_names.\n\n"
                "$document_summary\n\n"
                "Using the analyst's findings and document summaries, "
                "produce a risk-adjusted project plan with GO/NO-GO "
                "recommendation. Consider timeline feasibility and "
                "resource constraints."
            ),
            behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
            document_mode="summary",
            max_document_tokens=400,
        )

        # Agent 3: Writer -- uses template variables (Enhancement 4)
        writer_def = AgentDefinition(
            id="writer",
            role="Decision Brief Writer",
            system_prompt=(
                "You are an executive brief writer. This brief covers "
                "$document_count source document(s): $document_names.\n\n"
                "Using the analyst's analysis and planner's recommendation, "
                "produce a polished decision brief following the instructions. "
                "Keep it under 500 words. Be decisive and clear."
            ),
            behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
            document_mode="metadata_only",
        )

        print("  Agents configured:")
        print(f"    analyst  -> document_mode=full          (sees all chunks)")
        print(f"    planner  -> document_mode=summary       (sees LLM summaries)")
        print(f"    writer   -> document_mode=metadata_only (sees names + metadata)")
        print(f"    All use $document_count, $document_names template vars")

        # Build agents
        agents = {}
        for agent_def in [analyst_def, planner_def, writer_def]:
            agents[agent_def.id] = Agent(
                agent_id=agent_def.id,
                role=agent_def.role,
                system_prompt=agent_def.system_prompt,
                behavior_type=AgentBehaviorType.LLM_ONLY,
                llm_provider=provider,
                model=model_str,
                agent_definition=agent_def,
            )

        # Workflow: analyst → planner → writer
        steps = [
            WorkflowStep(
                agent="analyst", step_type="sequential", next_step="planner",
            ),
            WorkflowStep(
                agent="planner", step_type="sequential", next_step="writer",
            ),
            WorkflowStep(
                agent="writer", step_type="sequential",
            ),
        ]
        engine = WorkflowEngine(
            steps,
            document_pipeline=pipeline,
            assembly_agents=["writer"],
        )

        # -----------------------------------------------------------------------
        # Step 6: Execute the workflow
        # -----------------------------------------------------------------------
        print_section("Step 6: Execute Workflow")

        def on_event(event_type: str, agent_id: str, data: dict) -> None:
            if event_type == "step_start":
                print(f"    > {agent_id} starting...", flush=True)
            elif event_type == "step_complete":
                usage = data.get("usage", {})
                tokens = usage.get("total_tokens", 0) if usage else 0
                print(f"    * {agent_id} done ({tokens} tokens)", flush=True)

        engine.on_event(on_event)

        t0 = time.time()
        result = await engine.execute(
            agents=agents,
            initial_state={
                "task": instructions,  # Enhancement 1: from file
                "documents": docs,
                "document_summary": doc_summary,
                "_document_summaries": summaries,  # Enhancement 3: pre-cached
            },
        )
        elapsed = time.time() - t0

        # -----------------------------------------------------------------------
        # Step 7: Display results
        # -----------------------------------------------------------------------
        print_section("Step 7: Results")

        print_kv("Status", result.status.value)
        print_kv("Total time", f"{elapsed:.1f}s")
        print_kv("Cached summaries", f"{len(result.state.get('_document_summaries', {}))} docs")

        for agent_id in ["analyst", "planner", "writer"]:
            output = result.state.get(f"{agent_id}_output", "")
            usage = result.state.get(f"{agent_id}_usage", {})
            words = len(output.split()) if output else 0
            tokens = usage.get("total_tokens", 0) if usage else 0
            print(f"    {agent_id:10s}  {words:4d} words  {tokens:5d} tokens")

        # Show each agent's output
        for agent_id in ["analyst", "planner", "writer"]:
            output = result.state.get(f"{agent_id}_output", "")
            if output:
                print(f"\n  {'=' * 58}")
                print(f"  {agent_id.upper()} OUTPUT")
                print(f"  {'=' * 58}")
                lines = output.splitlines()
                for line in lines[:15]:
                    print(f"  {line}")
                if len(lines) > 15:
                    print(f"  ... ({len(lines)} lines total)")

        # Final output (from writer / assembly)
        final = result.state.get("final_output", result.state.get("writer_output", ""))
        if final:
            print(f"\n  {'=' * 58}")
            print(f"  FINAL DECISION BRIEF")
            print(f"  {'=' * 58}")
            print(f"  {final}")

            # Save to file
            output_dir = Path("output")
            output_dir.mkdir(exist_ok=True)
            output_path = output_dir / "decision_brief.md"
            output_path.write_text(final, encoding="utf-8")
            print(f"\n  Saved to: {output_path}")

        # -----------------------------------------------------------------------
        # Summary of enhancements used
        # -----------------------------------------------------------------------
        print_section("Enhancements Used")
        print("  1. instructions_file  -- Instructions loaded from instructions.md")
        print("  2. load_from_bytes    -- risk-assessment.md loaded from byte stream")
        print("  3. summary mode       -- Planner used LLM-generated summaries")
        print("  4. template variables -- All agents used $document_count/$document_names")
        print()


if __name__ == "__main__":
    asyncio.run(main())
