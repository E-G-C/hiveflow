#!/usr/bin/env python3
"""Document Input Pipeline 04: Prompt Template Variables for Documents.

Demonstrates User Story 4 -- template variables ``$document_count``,
``$document_names``, and ``$document_summary`` that are auto-populated
from workflow state when documents are loaded.

What this example covers:
  - PromptTemplate with document variables
  - Agent._resolve_document_variables() (internal mechanics)
  - Variables in system prompts resolved at execution time
  - Default values when no documents are loaded
  - Full workflow using document-aware prompts

Uses the Azure OpenAI endpoint for the workflow demo.

Usage:
    $env:AZURE_OPENAI_ENDPOINT = "https://foundry-aisbx-we.cognitiveservices.azure.com"
    uv run python examples/document_input_pipeline/04_template_variables.py
"""

import asyncio
import sys
import tempfile
import time
from pathlib import Path
from string import Template

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from _helpers import get_provider, is_live, print_kv, print_section

from hiveflow import Agent, AgentBehaviorType, WorkflowEngine, WorkflowStep
from hiveflow.core.documents import DocumentPipeline
from hiveflow.core.prompts import PromptTemplate
from hiveflow.core.schema import AgentBehaviorTypeSchema, AgentDefinition


# ---------------------------------------------------------------------------
# Sample documents
# ---------------------------------------------------------------------------

PROPOSAL_DOC = """\
# Project Proposal: ML-Powered Search

## Objective
Replace the current keyword-based search with a machine learning model
that understands semantic similarity and user intent.

## Scope
- Training data collection (3 months of search logs)
- Model development and evaluation (transformer-based)
- A/B testing framework for gradual rollout
- Monitoring and feedback loop

## Budget: $450K over 6 months
## Team: 2 ML engineers, 1 backend engineer, 1 PM
"""

TIMELINE_DOC = """\
# Project Timeline

| Phase | Duration | Deliverable |
|-------|----------|-------------|
| Research | 4 weeks | Model architecture selection |
| Data prep | 3 weeks | Training dataset (100K queries) |
| Training | 3 weeks | Fine-tuned model, eval metrics |
| Integration | 4 weeks | API endpoint, latency benchmarks |
| A/B test | 4 weeks | Statistical significance report |
| Rollout | 2 weeks | 100% traffic migration |

Total: ~20 weeks (5 months)
"""

RISKS_DOC = """\
# Risk Assessment

1. **Data quality** (HIGH): Search logs may contain PII that needs scrubbing
2. **Model latency** (MEDIUM): Target p99 < 100ms may be challenging
3. **A/B test duration** (LOW): May need 6+ weeks for statistical significance
4. **Team availability** (MEDIUM): ML engineers are shared with recommender team

Mitigation:
- PII scrubbing pipeline already exists for analytics team
- Start with distilled model, upgrade if latency allows
- Plan for 6-week A/B test in timeline
- Get commitment from engineering manager for dedicated allocation
"""


async def demo_template_resolution() -> None:
    """Part 1: Manual template variable resolution."""
    print_section("1. PromptTemplate with Document Variables")

    template = PromptTemplate(
        template=(
            "You are reviewing $document_count document(s): $document_names.\n\n"
            "Document overview: $document_summary\n\n"
            "Provide a thorough review covering risks, feasibility, "
            "and recommendations."
        ),
        name="doc_reviewer_prompt",
        description="Reviewer prompt with document variables",
    )

    # Simulate state with documents
    state_with_docs = {
        "documents": [
            {"name": "proposal.md", "format": "md", "chunk_count": 1},
            {"name": "timeline.md", "format": "md", "chunk_count": 1},
            {"name": "risks.md", "format": "md", "chunk_count": 1},
        ],
        "document_summary": (
            "3 documents loaded: proposal.md (1 chunks, ~120 tokens), "
            "timeline.md (1 chunks, ~95 tokens), risks.md (1 chunks, ~110 tokens)"
        ),
    }

    # Resolve using the same mechanism as Agent._resolve_document_variables
    docs = state_with_docs["documents"]
    doc_vars = {
        "document_count": str(len(docs)),
        "document_names": ", ".join(d["name"] for d in docs),
        "document_summary": state_with_docs["document_summary"],
    }
    resolved = Template(template.template).safe_substitute(**doc_vars)

    print("  Template (raw):")
    for line in template.template.splitlines()[:3]:
        print(f"    {line}")

    print("\n  Resolved:")
    for line in resolved.splitlines()[:4]:
        print(f"    {line}")

    print_kv("\n  $document_count", doc_vars["document_count"])
    print_kv("$document_names", doc_vars["document_names"])
    print_kv("$document_summary", doc_vars["document_summary"][:60] + "...")


async def demo_default_values() -> None:
    """Part 2: Default values when no documents are loaded."""
    print_section("2. Default Values (No Documents Loaded)")

    template_str = (
        "Documents available: $document_count\n"
        "Names: $document_names\n"
        "Summary: $document_summary"
    )

    # Empty state -- no documents key
    empty_state: dict = {}
    docs = empty_state.get("documents", [])
    doc_vars = {
        "document_count": str(len(docs)),
        "document_names": ", ".join(
            d.get("name", "") for d in docs if isinstance(d, dict)
        ),
        "document_summary": empty_state.get("document_summary", ""),
    }
    resolved = Template(template_str).safe_substitute(**doc_vars)

    print("  Resolved with empty state:")
    for line in resolved.splitlines():
        print(f"    {line}")

    print("\n  Defaults: count=0, names='', summary=''")


async def demo_agent_system_prompt() -> None:
    """Part 3: Agent system prompt with document variables resolved at execution."""
    print_section("3. Agent System Prompt with Document Variables")

    provider, deployment = get_provider()

    # Create an agent with document variables in its system prompt
    agent = Agent(
        agent_id="doc_reviewer",
        role="Document Reviewer",
        system_prompt=(
            "You are reviewing $document_count documents: $document_names.\n\n"
            "Context: $document_summary\n\n"
            "Analyze each document and provide a unified assessment. "
            "Focus on alignment between the proposal, timeline, and risks."
        ),
        behavior_type=AgentBehaviorType.LLM_ONLY,
        llm_provider=provider,
        model=f"{provider.plugin_id}:{deployment}",
    )

    # Build a state that mimics what the workflow engine produces
    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir)
        (work_dir / "proposal.md").write_text(PROPOSAL_DOC, encoding="utf-8")
        (work_dir / "timeline.md").write_text(TIMELINE_DOC, encoding="utf-8")
        (work_dir / "risks.md").write_text(RISKS_DOC, encoding="utf-8")

        pipeline = DocumentPipeline(working_dir=work_dir)
        docs, doc_summary = await pipeline.load([
            "proposal.md", "timeline.md", "risks.md",
        ])

        state = {
            "task": "Review the ML Search project documents",
            "documents": docs,
            "document_summary": doc_summary,
        }

        # Show what _resolve_document_variables produces
        resolved_prompt = agent._resolve_document_variables(
            agent.system_prompt, state
        )

        print("  System prompt BEFORE resolution:")
        print(f"    {agent.system_prompt[:80]}...")
        print("\n  System prompt AFTER resolution:")
        for line in resolved_prompt.splitlines()[:4]:
            print(f"    {line}")

        # Execute the agent
        print(f"\n  Executing agent with {provider.plugin_id}:{deployment}...")
        t0 = time.time()
        result = await agent.execute(state)
        elapsed = time.time() - t0

        output = result.get(f"{agent.agent_id}_output", "")
        print(f"  Done in {elapsed:.1f}s ({len(output.split())} words)")
        print("\n  Agent output:")
        print("  " + "-" * 58)
        for line in output.splitlines()[:12]:
            print(f"  {line}")
        if len(output.splitlines()) > 12:
            print(f"  ... ({len(output.splitlines())} lines total)")


async def demo_workflow_with_template_vars() -> None:
    """Part 4: Full workflow where agents use document template variables."""
    print_section("4. Workflow with Document Template Variables")

    provider, deployment = get_provider()
    model_str = f"{provider.plugin_id}:{deployment}"
    print_kv("Provider", model_str)

    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir)
        (work_dir / "proposal.md").write_text(PROPOSAL_DOC, encoding="utf-8")
        (work_dir / "risks.md").write_text(RISKS_DOC, encoding="utf-8")

        pipeline = DocumentPipeline(working_dir=work_dir)
        docs, doc_summary = await pipeline.load(["proposal.md", "risks.md"])

        # Agent definitions with document template variables in prompts
        analyst_def = AgentDefinition(
            id="analyst",
            role="Project Analyst",
            system_prompt=(
                "You are analyzing $document_count project document(s): "
                "$document_names.\n\n"
                "Overview: $document_summary\n\n"
                "Extract key facts, budget, timeline, and risk items. "
                "Present as a structured bullet list."
            ),
            behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
            document_mode="full",
        )

        advisor_def = AgentDefinition(
            id="advisor",
            role="Executive Advisor",
            system_prompt=(
                "You are an executive advisor. You have $document_count "
                "document(s) available ($document_names).\n\n"
                "Based on the analyst's findings, provide a go/no-go "
                "recommendation with supporting rationale. Be decisive."
            ),
            behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
            document_mode="metadata_only",
        )

        # Build agents
        analyst = Agent(
            agent_id="analyst",
            role=analyst_def.role,
            system_prompt=analyst_def.system_prompt,
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=provider,
            model=model_str,
            agent_definition=analyst_def,
        )

        advisor = Agent(
            agent_id="advisor",
            role=advisor_def.role,
            system_prompt=advisor_def.system_prompt,
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=provider,
            model=model_str,
            agent_definition=advisor_def,
        )

        steps = [
            WorkflowStep(agent="analyst", step_type="sequential", next_step="advisor"),
            WorkflowStep(agent="advisor", step_type="sequential"),
        ]
        engine = WorkflowEngine(steps)

        def on_event(event_type: str, agent_id: str, data: dict) -> None:
            if event_type == "step_start":
                print(f"    > {agent_id}...", flush=True)
            elif event_type == "step_complete":
                print(f"    * {agent_id} done", flush=True)

        engine.on_event(on_event)

        t0 = time.time()
        result = await engine.execute(
            agents={"analyst": analyst, "advisor": advisor},
            initial_state={
                "task": "Evaluate the ML Search project proposal",
                "documents": docs,
                "document_summary": doc_summary,
            },
        )
        elapsed = time.time() - t0

        print(f"\n  Status: {result.status.value}, elapsed: {elapsed:.1f}s")

        for agent_id in ["analyst", "advisor"]:
            output = result.state.get(f"{agent_id}_output", "")
            if output:
                words = len(output.split())
                print(f"\n  --- {agent_id} ({words} words) ---")
                for line in output.splitlines()[:8]:
                    print(f"  {line}")
                if len(output.splitlines()) > 8:
                    print(f"  ...")


async def main() -> None:
    print("=" * 64)
    print("  Document Input Pipeline -- 04: Template Variables")
    print("=" * 64)

    await demo_template_resolution()
    await demo_default_values()
    await demo_agent_system_prompt()
    await demo_workflow_with_template_vars()

    print_section("Done")
    print("  All template variable demonstrations completed successfully.")


if __name__ == "__main__":
    asyncio.run(main())
