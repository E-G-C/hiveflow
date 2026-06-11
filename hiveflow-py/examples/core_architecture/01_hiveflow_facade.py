#!/usr/bin/env python3
"""Example: HiveFlow facade -- the primary entry point.

Demonstrates how to:
1. Create a HiveFlow instance with sensible defaults
2. Run a workflow with an inline team configuration via run_sync()
3. Inspect the WorkflowSession result

This example uses a mock LLM provider and runs without API keys.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hiveflow import (
    Agent,
    AgentBehaviorType,
    HiveFlow,
    WorkflowStatus,
)
from hiveflow.plugins.llm import LLMConfig, LLMMessage, LLMProvider, LLMResponse, TokenUsage


# -- Mock provider (no API key needed) -----------------------------------------

class MockProvider(LLMProvider):
    """Returns fixed responses for demonstration purposes."""

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def plugin_id(self) -> str:
        return "mock"

    @property
    def description(self) -> str:
        return "Mock LLM for examples"

    async def chat(self, messages: list[LLMMessage], config: LLMConfig) -> LLMResponse:
        # Simulate a simple response based on the task
        task = messages[-1].content if messages else "unknown"
        return LLMResponse(
            content=f"Here is a well-structured summary of: {task}",
            model="mock-model",
            usage=TokenUsage(prompt_tokens=20, completion_tokens=30, total_tokens=50),
        )


# -- Main -----------------------------------------------------------------------

def main() -> None:
    """Run a simple two-agent workflow through the HiveFlow facade."""

    # Register our mock provider so HiveFlow can resolve it
    from hiveflow.plugins.llm import LLMProviderRegistry

    registry = LLMProviderRegistry()
    registry.register(MockProvider())

    hf = HiveFlow(llm_registry=registry)

    # Inline team config -- no JSON file needed
    session = hf.run_sync(
        team={
            "team_name": "summarizer",
            "description": "Research and summarize a topic",
            "agents": [
                {
                    "id": "researcher",
                    "role": "Researcher",
                    "system_prompt": "Find relevant information about the topic.",
                    "behavior_type": "llm_only",
                    "model": "mock:default",
                },
                {
                    "id": "writer",
                    "role": "Writer",
                    "system_prompt": "Write a clear summary based on research.",
                    "behavior_type": "llm_only",
                    "model": "mock:default",
                },
            ],
            "workflow": {
                "steps": [
                    {"agent": "researcher", "type": "sequential", "next": "writer"},
                    {"agent": "writer", "type": "sequential"},
                ],
            },
        },
        task="Explain the benefits of renewable energy",
    )

    # Inspect the result
    print(f"Session ID : {session.session_id}")
    print(f"Status     : {session.status.value}")

    if session.status == WorkflowStatus.COMPLETED:
        print(f"State keys : {list(session.result.state.keys())}")
        writer_output = session.result.state.get("writer_output", "")
        print(f"Writer out : {writer_output[:200]}...")
    elif session.status == WorkflowStatus.FAILED:
        print(f"Error      : {session.error}")

    # Session is also JSON-serializable
    import json
    snapshot = session.to_dict()
    print(f"\nJSON snapshot keys: {list(snapshot.keys())}")


if __name__ == "__main__":
    main()
