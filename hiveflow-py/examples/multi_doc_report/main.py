#!/usr/bin/env python3
"""End-to-end: Multi-document project status report with per-agent scoping.

Loads three project documents (requirements, sprint retro, QA report) and routes
them through a three-agent pipeline where each agent sees a different slice:

  1. **Analyst** (full access) -- reads all documents, extracts risk items
  2. **Planner** (filtered)   -- sees only sprint retro + QA report, plans next steps
  3. **Writer** (no docs)     -- synthesizes a status report from prior agent outputs

Demonstrates:
  - Per-agent document scoping (full, filtered by name, none)
  - Three-step sequential workflow with output propagation
  - Different document_mode settings controlling what each agent sees
  - Real LLM calls with document content in context

Usage:
    # Azure RBAC (default -- no API key needed, just `az login`):
    AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com \
        uv run python examples/multi_doc_report/main.py

    # OpenAI:
    OPENAI_API_KEY=sk-... uv run python examples/multi_doc_report/main.py --provider openai

    # Local OpenAI-compatible server (llama.cpp, vLLM, etc.):
    uv run python examples/multi_doc_report/main.py \
        --provider local --base-url http://localhost:8080/v1 --model local-model
"""

import argparse
import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any

from hiveflow import (
    Agent,
    AgentBehaviorType,
    LLMConfig,
    WorkflowEngine,
    WorkflowStep,
)
from hiveflow.core.documents import DocumentPipeline
from hiveflow.core.schema import AgentBehaviorTypeSchema, AgentDefinition
from hiveflow.plugins.documents import DocumentLoaderRegistry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("multi_doc_report")


# ---------------------------------------------------------------------------
# Provider selection
# ---------------------------------------------------------------------------
def get_provider(provider_name: str, base_url: str | None = None):
    """Return an LLM provider instance based on the selected backend."""
    if provider_name == "azure":
        from hiveflow.plugins.llm.azure_provider import AzureOpenAIProvider
        return AzureOpenAIProvider()  # reads AZURE_OPENAI_ENDPOINT from env
    elif provider_name == "openai":
        from hiveflow.plugins.llm.openai_provider import OpenAIProvider
        return OpenAIProvider()  # reads OPENAI_API_KEY from env
    elif provider_name == "local":
        from hiveflow.plugins.llm.openai_provider import OpenAIProvider
        return OpenAIProvider(base_url=base_url, api_key="not-needed")
    else:
        raise ValueError(f"Unknown provider: {provider_name}")


def detect_provider() -> str:
    """Auto-detect the best available provider from environment."""
    if os.environ.get("AZURE_OPENAI_ENDPOINT"):
        return "azure"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    return "azure"  # default -- will fail with a clear error message if unconfigured


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------
def build_agents(provider, model: str) -> dict[str, Agent]:
    """Create three agents with different document scoping."""

    # -- Analyst: sees ALL documents (full mode) --
    analyst_def = AgentDefinition(
        id="analyst",
        role="Project Risk Analyst",
        system_prompt=(
            "You are a project risk analyst. You will receive multiple project "
            "documents including requirements, sprint retrospectives, and QA reports.\n\n"
            "Your job:\n"
            "1. Identify the top 5 risks to the project timeline and quality\n"
            "2. For each risk, note which document(s) it appears in\n"
            "3. Rate each risk as Critical, High, Medium, or Low\n"
            "4. Note any risks that are cross-cutting (appear in multiple documents)\n\n"
            "Be specific. Reference exact details from the documents."
        ),
        behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
        document_mode="full",
    )
    analyst = Agent(
        agent_id="analyst",
        role=analyst_def.role,
        system_prompt=analyst_def.system_prompt,
        behavior_type=AgentBehaviorType.LLM_ONLY,
        model=model,
        llm_provider=provider,
        llm_config=LLMConfig(model=model, temperature=0.3, max_tokens=2048),
        agent_definition=analyst_def,
    )

    # -- Planner: sees only sprint retro + QA report (filtered) --
    planner_def = AgentDefinition(
        id="planner",
        role="Sprint Planner",
        system_prompt=(
            "You are a sprint planner. You will receive the sprint retrospective "
            "and QA test report. You will also receive a risk analysis from the "
            "previous analyst.\n\n"
            "Based on these inputs, create a prioritized action plan for the "
            "next sprint:\n"
            "1. List 5-7 specific work items with owners and priorities\n"
            "2. Flag any items that address risks from the analyst's report\n"
            "3. Estimate story points (S=1, M=3, L=5, XL=8) for each item\n"
            "4. Note dependencies between items\n\n"
            "Focus on actionable items, not vague goals."
        ),
        behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
        documents=["sprint_retro.md", "qa_report.txt"],
        document_mode="full",
    )
    planner = Agent(
        agent_id="planner",
        role=planner_def.role,
        system_prompt=planner_def.system_prompt,
        behavior_type=AgentBehaviorType.LLM_ONLY,
        model=model,
        llm_provider=provider,
        llm_config=LLMConfig(model=model, temperature=0.4, max_tokens=2048),
        agent_definition=planner_def,
    )

    # -- Writer: no documents, synthesizes from analyst + planner output --
    writer_def = AgentDefinition(
        id="writer",
        role="Status Report Writer",
        system_prompt=(
            "You are a technical writer producing a weekly project status report "
            "for senior leadership.\n\n"
            "You will receive a risk analysis and a sprint plan from previous "
            "analysts. Synthesize these into a clear status report with:\n\n"
            "1. **Executive Summary** (2-3 sentences)\n"
            "2. **Current Status** -- Red/Amber/Green with justification\n"
            "3. **Key Risks** -- top 3, with mitigation plans\n"
            "4. **Next Sprint Plan** -- prioritized items\n"
            "5. **Decisions Needed** -- anything requiring leadership input\n\n"
            "Keep it under 500 words. Use bullet points. No jargon."
        ),
        behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
        document_mode="none",
    )
    writer = Agent(
        agent_id="writer",
        role=writer_def.role,
        system_prompt=writer_def.system_prompt,
        behavior_type=AgentBehaviorType.LLM_ONLY,
        model=model,
        llm_provider=provider,
        llm_config=LLMConfig(model=model, temperature=0.5, max_tokens=2048),
        agent_definition=writer_def,
    )

    return {"analyst": analyst, "planner": planner, "writer": writer}


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------
def build_workflow() -> WorkflowEngine:
    """Three-step sequential pipeline: analyst -> planner -> writer."""
    pipeline = DocumentPipeline(
        registry=DocumentLoaderRegistry(),
        working_dir=Path(__file__).parent,
    )
    steps = [
        WorkflowStep(agent="analyst", step_type="sequential", next_step="planner"),
        WorkflowStep(agent="planner", step_type="sequential", next_step="writer"),
        WorkflowStep(agent="writer", step_type="sequential"),
    ]
    return WorkflowEngine(steps, document_pipeline=pipeline)


# ---------------------------------------------------------------------------
# Event handler
# ---------------------------------------------------------------------------
_step_times: dict[str, float] = {}


def on_event(event_type: str, agent_id: str, data: dict[str, Any]) -> None:
    if event_type == "documents_loaded":
        logger.info("Documents loaded: %s", data.get("summary", ""))
    elif event_type == "step_start":
        _step_times[agent_id] = time.time()
        mode = ""
        if agent_id == "analyst":
            mode = " [full access -- all 3 documents]"
        elif agent_id == "planner":
            mode = " [filtered -- sprint_retro.md + qa_report.txt only]"
        elif agent_id == "writer":
            mode = " [no documents -- uses prior outputs]"
        logger.info("--- Step: %s%s ---", agent_id, mode)
    elif event_type == "step_complete":
        elapsed = time.time() - _step_times.get(agent_id, time.time())
        logger.info("--- %s complete (%.1fs) ---", agent_id, elapsed)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def run(provider_name: str, model: str, base_url: str | None) -> None:
    start = time.time()

    provider = get_provider(provider_name, base_url=base_url)
    agents = build_agents(provider, model)
    engine = build_workflow()
    engine.on_event(on_event)

    logger.info("Starting multi-document report workflow")
    logger.info("Provider: %s | Model: %s", provider_name, model)
    logger.info("Documents:")
    logger.info("  - product_requirements.txt  (analyst only)")
    logger.info("  - sprint_retro.md           (analyst + planner)")
    logger.info("  - qa_report.txt             (analyst + planner)")
    logger.info("")

    result = await engine.execute(
        agents=agents,
        initial_state={
            "task": (
                "Analyze the project documents, identify risks, plan the next "
                "sprint, and produce a leadership status report."
            ),
        },
        documents=[
            "product_requirements.txt",
            "sprint_retro.md",
            "qa_report.txt",
        ],
    )

    elapsed = time.time() - start

    # -- Output ---------------------------------------------------------------
    print("\n" + "=" * 60)
    print("  RISK ANALYSIS (analyst -- sees all 3 docs)")
    print("=" * 60)
    print(result.state.get("analyst_output", "(no output)"))

    print("\n" + "=" * 60)
    print("  SPRINT PLAN (planner -- sees retro + QA only)")
    print("=" * 60)
    print(result.state.get("planner_output", "(no output)"))

    print("\n" + "=" * 60)
    print("  STATUS REPORT (writer -- no docs, prior outputs only)")
    print("=" * 60)
    print(result.state.get("writer_output", "(no output)"))

    print("\n" + "=" * 60)
    print("  WORKFLOW RESULT")
    print("=" * 60)
    print(f"  Status:     {result.status.value}")
    print(f"  Steps:      {len(result.step_results)}")
    print(f"  Documents:  {len(result.state.get('documents', []))}")
    print(f"  Elapsed:    {elapsed:.1f}s")

    for step in result.step_results:
        usage = result.state.get(f"{step.agent_id}_usage")
        if usage:
            print(
                f"  {step.agent_id}: {usage.get('total_tokens', '?')} tokens "
                f"(prompt={usage.get('prompt_tokens', '?')}, "
                f"completion={usage.get('completion_tokens', '?')})"
            )

    if result.error:
        print(f"  Error:      {result.error}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Multi-document project status report with per-agent scoping",
    )
    parser.add_argument(
        "--provider",
        choices=["azure", "openai", "local"],
        default=None,
        help="LLM provider (default: auto-detect from env)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model / deployment name (default: gpt-4o-mini)",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Base URL for local OpenAI-compatible server (only with --provider local)",
    )
    args = parser.parse_args()

    provider_name = args.provider or detect_provider()
    model = args.model or "gpt-4o-mini"

    asyncio.run(run(provider_name=provider_name, model=model, base_url=args.base_url))


if __name__ == "__main__":
    main()
