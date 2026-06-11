#!/usr/bin/env python3
"""End-to-end: Document Q&A with the DocumentRetrieverTool.

Loads two technical documents (architecture review + incident report), then runs
a tool_user agent that answers questions by retrieving relevant chunks on demand.

Demonstrates:
  - Loading multiple documents into workflow state
  - tool_user agent with DocumentRetrieverTool
  - On-demand retrieval (agent decides which doc/chunks to fetch)
  - Tool calling loop: LLM -> tool call -> result -> LLM -> final answer

Usage:
    uv run python examples/document_qa/main.py
    uv run python examples/document_qa/main.py --question "What was the root cause of the outage?"
    uv run python examples/document_qa/main.py --base-url http://localhost:8080/v1
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
from hiveflow.plugins.tools.document_retriever import DocumentRetrieverTool

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DEFAULT_BASE_URL = os.environ.get("OPENAI_BASE_URL", "http://localhost:8080/v1")
MODEL_NAME = "local-model"

DEFAULT_QUESTION = (
    "Based on the architecture review and the incident report, what are the "
    "top 3 most urgent changes needed, and which ones have already been "
    "addressed after the outage?"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("document_qa")


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------
def build_agents(provider: OpenAIProvider) -> dict[str, Agent]:
    """Create a tool_user agent with document retrieval capability."""

    retriever = DocumentRetrieverTool()

    agent_def = AgentDefinition(
        id="qa_agent",
        role="Technical Q&A Specialist",
        system_prompt=(
            "You are a technical Q&A assistant. You have access to loaded "
            "documents via the document_retriever tool.\n\n"
            "When answering questions:\n"
            "1. Use the document_retriever tool to search for relevant content.\n"
            "   - Use 'query' to search by keywords across all documents\n"
            "   - Use 'document_name' to fetch a specific document\n"
            "2. Cite specific details (numbers, dates, names) from the documents.\n"
            "3. If the documents don't contain enough information, say so.\n"
            "4. Structure your answer clearly with sections if appropriate.\n\n"
            "Available documents are listed in the document summary below."
        ),
        behavior_type=AgentBehaviorTypeSchema.TOOL_USER,
        document_mode="metadata_only",  # Agent sees doc names, uses tool for content
    )
    qa_agent = Agent(
        agent_id="qa_agent",
        role=agent_def.role,
        system_prompt=agent_def.system_prompt,
        behavior_type=AgentBehaviorType.TOOL_USER,
        tools=[retriever],
        model=MODEL_NAME,
        llm_provider=provider,
        llm_config=LLMConfig(model=MODEL_NAME, temperature=0.2, max_tokens=2048),
        max_tool_iterations=5,
        agent_definition=agent_def,
    )

    return {"qa_agent": qa_agent}


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------
def build_workflow() -> WorkflowEngine:
    """Single-agent workflow with document retrieval."""
    pipeline = DocumentPipeline(
        registry=DocumentLoaderRegistry(),
        working_dir=Path(__file__).parent,
    )
    steps = [
        WorkflowStep(agent="qa_agent", step_type="sequential"),
    ]
    return WorkflowEngine(steps, document_pipeline=pipeline)


# ---------------------------------------------------------------------------
# Event handler
# ---------------------------------------------------------------------------
def on_event(event_type: str, agent_id: str, data: dict[str, Any]) -> None:
    if event_type == "documents_loaded":
        logger.info("Documents loaded: %s", data.get("summary", ""))
    elif event_type == "step_start":
        logger.info("--- %s processing ---", agent_id)
    elif event_type == "tool_call":
        tool_name = data.get("tool_name", "?")
        logger.info("  Tool call: %s(%s)", tool_name, data.get("input", ""))
    elif event_type == "step_complete":
        logger.info("--- %s done ---", agent_id)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def run(base_url: str, question: str) -> None:
    start = time.time()

    provider = OpenAIProvider(base_url=base_url, api_key="not-needed")
    agents = build_agents(provider)
    engine = build_workflow()
    engine.on_event(on_event)

    logger.info("Starting document Q&A workflow")
    logger.info("LLM endpoint: %s", base_url)
    logger.info("Documents: architecture_review.md, incident_report.md")
    logger.info("Question: %s", question)
    logger.info("")

    result = await engine.execute(
        agents=agents,
        initial_state={"task": question},
        documents=["architecture_review.md", "incident_report.md"],
    )

    elapsed = time.time() - start

    # -- Output ---------------------------------------------------------------
    print("\n" + "=" * 60)
    print("  QUESTION")
    print("=" * 60)
    print(question)

    print("\n" + "=" * 60)
    print("  ANSWER")
    print("=" * 60)
    print(result.state.get("qa_agent_output", "(no output)"))

    print("\n" + "=" * 60)
    print("  WORKFLOW RESULT")
    print("=" * 60)
    print(f"  Status:     {result.status.value}")
    print(f"  Documents:  {len(result.state.get('documents', []))}")
    print(f"  Elapsed:    {elapsed:.1f}s")

    # Show tool usage if available
    tool_results = result.state.get("qa_agent_tool_results", [])
    if tool_results:
        print(f"  Tool calls: {len(tool_results)}")

    if result.error:
        print(f"  Error:      {result.error}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Answer questions about technical documents",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help="OpenAI-compatible API base URL",
    )
    parser.add_argument(
        "--question",
        default=DEFAULT_QUESTION,
        help="The question to answer",
    )
    args = parser.parse_args()
    asyncio.run(run(base_url=args.base_url, question=args.question))


if __name__ == "__main__":
    main()
