#!/usr/bin/env python3
"""End-to-end: Summarize a document with a two-agent workflow.

Loads a document from the example directory, passes it through two LLM agents:
  1. **Analyst** -- extracts key financial metrics and takeaways
  2. **Writer** -- produces a polished executive summary

The script auto-discovers documents in its directory -- drop any supported file
(txt, md, docx, pdf, csv, json, xml, html, xlsx, pptx) and it will be loaded.

Demonstrates:
  - DocumentPipeline loading real files into workflow state
  - Documents flowing through WorkflowEngine to agents automatically
  - Per-agent system prompts that reference document content
  - Sequential two-step workflow with state propagation

Usage:
    uv run python examples/document_summarizer/main.py
    uv run python examples/document_summarizer/main.py --base-url http://localhost:8080/v1
    uv run python examples/document_summarizer/main.py --doc "my_file.docx"
"""

import argparse
import asyncio
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

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
from hiveflow.plugins.llm.openai_provider import OpenAIProvider

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DEFAULT_BASE_URL = os.environ.get("OPENAI_BASE_URL", "http://localhost:8080/v1")
MODEL_NAME = "local-model"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("document_summarizer")


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------
def build_agents(provider: OpenAIProvider) -> dict[str, Agent]:
    """Create the analyst and writer agents."""

    # Analyst: reads the full document, extracts structured data
    analyst_def = AgentDefinition(
        id="analyst",
        role="Financial Analyst",
        system_prompt=(
            "You are a financial analyst. You will receive an earnings call "
            "transcript in the Documents section below.\n\n"
            "Extract the following in a structured format:\n"
            "1. Revenue figures (quarterly and annual, with YoY growth)\n"
            "2. Key metrics (margins, ARR, customer counts, retention)\n"
            "3. Segment performance breakdown\n"
            "4. Forward guidance (next quarter and full year)\n"
            "5. Notable quotes from the Q&A session\n\n"
            "Be precise with numbers. Use bullet points."
        ),
        behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
        document_mode="full",
    )
    analyst = Agent(
        agent_id="analyst",
        role=analyst_def.role,
        system_prompt=analyst_def.system_prompt,
        behavior_type=AgentBehaviorType.LLM_ONLY,
        model=MODEL_NAME,
        llm_provider=provider,
        llm_config=LLMConfig(model=MODEL_NAME, temperature=0.3, max_tokens=2048),
        agent_definition=analyst_def,
    )

    # Writer: reads analyst output, produces executive summary (no docs needed)
    writer_def = AgentDefinition(
        id="writer",
        role="Executive Summary Writer",
        system_prompt=(
            "You are a business writer producing executive summaries.\n\n"
            "You will receive an analyst's structured extraction from an "
            "earnings call. Using that data, write a concise executive "
            "summary (300-500 words) suitable for a board presentation.\n\n"
            "Structure:\n"
            "- Opening paragraph with headline numbers\n"
            "- Segment highlights (2-3 sentences each)\n"
            "- Outlook and guidance\n"
            "- Key risks or concerns\n\n"
            "Tone: professional, factual, no jargon."
        ),
        behavior_type=AgentBehaviorTypeSchema.LLM_ONLY,
        document_mode="none",  # Writer works from analyst output, not raw docs
    )
    writer = Agent(
        agent_id="writer",
        role=writer_def.role,
        system_prompt=writer_def.system_prompt,
        behavior_type=AgentBehaviorType.LLM_ONLY,
        model=MODEL_NAME,
        llm_provider=provider,
        llm_config=LLMConfig(model=MODEL_NAME, temperature=0.5, max_tokens=2048),
        agent_definition=writer_def,
    )

    return {"analyst": analyst, "writer": writer}


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------
def build_workflow() -> WorkflowEngine:
    """Two-step sequential pipeline: analyst -> writer."""
    pipeline = DocumentPipeline(
        registry=DocumentLoaderRegistry(),
        working_dir=Path(__file__).parent,
    )
    steps = [
        WorkflowStep(agent="analyst", step_type="sequential", next_step="writer"),
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
        logger.info("--- Step: %s ---", agent_id)
    elif event_type == "step_complete":
        elapsed = time.time() - _step_times.get(agent_id, time.time())
        logger.info("--- %s complete (%.1fs) ---", agent_id, elapsed)


# ---------------------------------------------------------------------------
# Document discovery
# ---------------------------------------------------------------------------
SUPPORTED_EXTENSIONS = {
    ".txt", ".md", ".csv", ".json", ".xml", ".html",
    ".pdf", ".docx", ".xlsx", ".pptx",
}


def discover_documents(directory: Path) -> list[str]:
    """Find all supported document files in the directory.

    Skips files named 'output.*' (generated outputs) and hidden files.
    """
    docs = []
    for f in sorted(directory.iterdir()):
        if not f.is_file():
            continue
        if f.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        if f.stem.lower() == "output" or f.name.startswith("."):
            continue
        docs.append(f.name)
    return docs


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def run(base_url: str, doc: str | None) -> None:
    start = time.time()

    example_dir = Path(__file__).parent

    # Resolve which document(s) to load
    if doc:
        doc_files = [doc]
    else:
        doc_files = discover_documents(example_dir)
        if not doc_files:
            print(
                f"No documents found in {example_dir}.\n"
                f"Drop a supported file ({', '.join(sorted(SUPPORTED_EXTENSIONS))}) "
                f"into the directory, or use --doc <filename>."
            )
            return

    provider = OpenAIProvider(base_url=base_url, api_key="not-needed")
    agents = build_agents(provider)
    engine = build_workflow()
    engine.on_event(on_event)

    logger.info("Starting document summarizer workflow")
    logger.info("LLM endpoint: %s", base_url)
    for f in doc_files:
        logger.info("Document: %s", f)
    logger.info("")

    result = await engine.execute(
        agents=agents,
        initial_state={"task": "Analyze and summarize this earnings call transcript."},
        documents=doc_files,
    )

    elapsed = time.time() - start

    # -- Output ---------------------------------------------------------------
    print("\n" + "=" * 60)
    print("  ANALYST EXTRACTION")
    print("=" * 60)
    print(result.state.get("analyst_output", "(no output)"))

    print("\n" + "=" * 60)
    print("  EXECUTIVE SUMMARY")
    print("=" * 60)
    print(result.state.get("writer_output", "(no output)"))

    print("\n" + "=" * 60)
    print("  WORKFLOW RESULT")
    print("=" * 60)
    print(f"  Status:     {result.status.value}")
    print(f"  Steps:      {len(result.step_results)}")
    print(f"  Documents:  {len(result.state.get('documents', []))}")
    print(f"  Elapsed:    {elapsed:.1f}s")

    if result.error:
        print(f"  Error:      {result.error}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Summarize a document with a two-agent workflow",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help="OpenAI-compatible API base URL",
    )
    parser.add_argument(
        "--doc",
        default=None,
        help="Document filename to load (default: auto-discover in example dir)",
    )
    args = parser.parse_args()
    asyncio.run(run(base_url=args.base_url, doc=args.doc))


if __name__ == "__main__":
    main()
