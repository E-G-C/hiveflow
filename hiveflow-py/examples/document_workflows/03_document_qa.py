#!/usr/bin/env python3
"""Document Workflows 03: Document Q&A with DocumentRetrieverTool.

Loads two technical documents, then runs a tool_user agent that answers
questions by retrieving relevant chunks on demand.

Demonstrates:
  - Loading multiple documents into workflow state
  - tool_user agent with DocumentRetrieverTool
  - On-demand retrieval (agent decides which doc/chunks to fetch)
  - Tool calling loop: LLM -> tool call -> result -> LLM -> final answer

Uses a mock LLM by default. Set AZURE_OPENAI_ENDPOINT for live results.

Usage:
    uv run python examples/document_workflows/03_document_qa.py

    # Custom question:
    uv run python examples/document_workflows/03_document_qa.py \
        --question "What was the root cause of the outage?"

Expected output:
    See sample_output/document_workflows/03_document_qa.txt
"""

import argparse
import asyncio
import json
import os
import tempfile
from pathlib import Path

from hiveflow.plugins.llm import LLMConfig, LLMMessage, LLMProvider, LLMResponse, TokenUsage
from hiveflow.plugins.tools.document_retriever import DocumentRetrieverTool


# ---------------------------------------------------------------------------
# Sample documents
# ---------------------------------------------------------------------------

ARCHITECTURE_REVIEW = """\
# Architecture Review: Payment Service

## Current State
The payment service handles ~50K transactions/day through a monolithic
Django application backed by PostgreSQL. The service has grown organically
over 3 years without significant refactoring.

## Identified Issues
1. **Single point of failure**: No redundancy for the payment processor
2. **Database bottleneck**: All queries route through a single primary
3. **No circuit breaker**: External API failures cascade across the system
4. **Missing idempotency**: Retry logic can cause duplicate charges

## Recommendations
- Implement circuit breaker pattern for external APIs
- Add database read replicas for reporting queries
- Introduce idempotency keys for all payment operations
- Set up active-passive failover for the payment processor
"""

INCIDENT_REPORT = """\
# Incident Report: Payment Service Outage (2025-02-15)

## Timeline
- 14:23 UTC: Monitoring alerts on high error rate (>5%)
- 14:25 UTC: Payment processor API returning 503 errors
- 14:28 UTC: Django application thread pool exhausted waiting for API responses
- 14:30 UTC: Full service outage -- all payment requests failing
- 14:45 UTC: Manual failover to backup processor initiated
- 15:10 UTC: Service restored with backup processor

## Root Cause
The primary payment processor experienced a partial outage. Without a
circuit breaker, the Django application kept sending requests to the
failing endpoint, exhausting its thread pool. This matches Issue #1
and #3 from the architecture review.

## Impact
- 47 minutes of downtime
- ~3,800 failed transactions estimated at $2.1M in delayed revenue
- 12 duplicate charges from retry logic (Issue #4)

## Remediation
- [DONE] Failover procedure documented
- [TODO] Implement circuit breaker (ETA: 2 weeks)
- [TODO] Fix idempotency for retry logic (ETA: 1 week)
"""

DEFAULT_QUESTION = (
    "Based on the architecture review and the incident report, what are the "
    "top 3 most urgent changes needed, and which ones have already been addressed?"
)


# ---------------------------------------------------------------------------
# Mock provider
# ---------------------------------------------------------------------------

class MockToolProvider(LLMProvider):
    """Simulates a tool-calling LLM for demonstration."""

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
        return "Mock LLM with tool calls"

    async def chat(self, messages: list[LLMMessage], config: LLMConfig) -> LLMResponse:
        self._call_count += 1

        # First call: retrieve the architecture review
        if self._call_count == 1:
            return LLMResponse(
                content="Let me retrieve the relevant documents.",
                model="mock",
                tool_calls=[{
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "retrieve_document",
                        "arguments": json.dumps({"document_name": "architecture_review.md"}),
                    },
                }],
                usage=TokenUsage(prompt_tokens=100, completion_tokens=20, total_tokens=120),
            )

        # Second call: retrieve the incident report
        if self._call_count == 2:
            return LLMResponse(
                content="Now let me check the incident report.",
                model="mock",
                tool_calls=[{
                    "id": "call_2",
                    "type": "function",
                    "function": {
                        "name": "retrieve_document",
                        "arguments": json.dumps({"document_name": "incident_report.md"}),
                    },
                }],
                usage=TokenUsage(prompt_tokens=200, completion_tokens=20, total_tokens=220),
            )

        # Third call: final answer
        return LLMResponse(
            content=(
                "Based on the architecture review and incident report, the top 3 "
                "most urgent changes are:\n\n"
                "1. **Circuit breaker implementation** (CRITICAL) -- The lack of a "
                "circuit breaker was the direct cause of the outage, turning a "
                "partial processor failure into a full service outage. Status: TODO, "
                "ETA 2 weeks.\n\n"
                "2. **Idempotency keys for payment operations** (HIGH) -- The missing "
                "idempotency caused 12 duplicate charges during the incident. Status: "
                "TODO, ETA 1 week.\n\n"
                "3. **Payment processor failover** (HIGH) -- While a manual failover "
                "was performed during the incident, an automated active-passive "
                "failover should be implemented. Status: Failover procedure documented "
                "(DONE), but automated failover is not yet in place.\n\n"
                "The database bottleneck (Issue #2) is lower priority as it didn't "
                "contribute to this incident."
            ),
            model="mock",
            usage=TokenUsage(prompt_tokens=500, completion_tokens=180, total_tokens=680),
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main(question: str) -> None:
    """Run the document Q&A workflow."""
    print("=" * 60)
    print("  HiveFlow -- Document Q&A with Retriever Tool")
    print("=" * 60)

    # -- Set up documents --
    with tempfile.TemporaryDirectory() as tmpdir:
        work_dir = Path(tmpdir)
        (work_dir / "architecture_review.md").write_text(ARCHITECTURE_REVIEW)
        (work_dir / "incident_report.md").write_text(INCIDENT_REPORT)

        from hiveflow.core.documents import DocumentPipeline
        from hiveflow.plugins.documents import DocumentLoaderRegistry

        registry = DocumentLoaderRegistry()
        pipeline = DocumentPipeline(registry=registry, working_dir=work_dir)
        docs, summary = await pipeline.load([
            "architecture_review.md",
            "incident_report.md",
        ])
        print(f"  Documents loaded: {summary}")

        # -- Set up retriever tool --
        tool = DocumentRetrieverTool()
        tool.set_documents(docs)

        print(f"\n  Question: {question[:80]}...")

        # -- Demonstrate direct tool usage --
        print(f"\n{'-' * 60}")
        print("Direct tool usage (without LLM):")
        print("-" * 60)

        # Fetch by document name
        result = await tool.execute({"document_name": "architecture_review.md"})
        print(f"  Fetch 'architecture_review.md': {result['total_chunks']} chunk(s)")
        for chunk in result["chunks"][:2]:
            print(f"    [{chunk['index']}] {chunk['content'][:70]}...")

        # Search by query
        result = await tool.execute({"query": "circuit breaker outage"})
        print(f"\n  Search 'circuit breaker outage': {result['total_chunks']} match(es)")
        for chunk in result["chunks"][:3]:
            doc_name = chunk.get("document", "?")
            print(f"    [{doc_name}:{chunk['index']}] {chunk['content'][:70]}...")

        # -- Mock LLM tool-calling loop --
        print(f"\n{'-' * 60}")
        print("LLM tool-calling loop (mock):")
        print("-" * 60)

        provider = MockToolProvider()
        messages = [
            LLMMessage(role="system", content=(
                "You are a technical analyst. Answer questions about the provided "
                "documents. Use the retrieve_document tool to fetch document content."
            )),
            LLMMessage(role="user", content=question),
        ]

        config = LLMConfig(model="mock")
        total_tokens = 0

        for turn in range(5):  # Max 5 turns
            response = await provider.chat(messages, config)
            total_tokens += response.usage.total_tokens if response.usage else 0

            if response.tool_calls:
                for tc in response.tool_calls:
                    args = json.loads(tc["function"]["arguments"])
                    tool_result = await tool.execute(args)
                    chunk_count = tool_result.get("total_chunks", 0)
                    print(f"  Turn {turn + 1}: tool call -> {tc['function']['name']}({args}) -> {chunk_count} chunks")
                    messages.append(LLMMessage(
                        role="tool",
                        content=json.dumps(tool_result),
                        tool_call_id=tc["id"],
                    ))
            else:
                print(f"  Turn {turn + 1}: final answer ({len(response.content.split())} words)")
                break

        print(f"\n{'-' * 60}")
        print("Answer:")
        print("-" * 60)
        print(response.content)
        print(f"\n  Total tokens: {total_tokens}")


def cli() -> None:
    """Parse arguments and run."""
    parser = argparse.ArgumentParser(description="Document Q&A with retriever tool")
    parser.add_argument("--question", default=DEFAULT_QUESTION, help="Question to ask")
    args = parser.parse_args()
    asyncio.run(main(question=args.question))


if __name__ == "__main__":
    cli()
