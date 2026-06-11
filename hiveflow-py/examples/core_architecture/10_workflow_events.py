#!/usr/bin/env python3
"""Example: Workflow event stream -- observe the full lifecycle via callbacks.

Demonstrates how to:
1. Register event callbacks on a WorkflowEngine
2. Observe step_start / step_complete events during execution
3. Observe gate_requested and checkpoint_saved events at pause points
4. Observe approval and output events on resume
5. Build an event log for audit or debugging

The workflow engine emits events at every significant point in the
lifecycle. These events enable real-time UIs, audit trails, and
debugging without modifying the workflow itself.

Event types emitted by the engine:
  step_start         -- a workflow step begins execution
  step_complete      -- a workflow step finishes
  gate_requested     -- a gated step pauses for approval
  checkpoint_saved   -- a checkpoint was persisted to storage
  approval           -- an approval response was applied on resume
  output             -- terminal workflow output produced on completion

By default uses a mock LLM provider (no API keys needed).
Set AZURE_OPENAI_ENDPOINT to use Azure OpenAI with RBAC auth:

    export AZURE_OPENAI_ENDPOINT=https://<resource>.cognitiveservices.azure.com
    uv run python examples/core_architecture/10_workflow_events.py
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hiveflow import (
    Agent,
    AgentBehaviorType,
    FileCheckpointStorage,
)
from hiveflow.core.workflow import StepType, WorkflowEngine, WorkflowStep
from hiveflow.plugins.llm import LLMConfig, LLMMessage, LLMProvider, LLMResponse, TokenUsage


class MockProvider(LLMProvider):
    """Returns a canned response."""

    def __init__(self, response: str = "Done."):
        self._response = response

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def plugin_id(self) -> str:
        return "mock"

    @property
    def description(self) -> str:
        return "Mock LLM"

    async def chat(self, messages: list[LLMMessage], config: LLMConfig) -> LLMResponse:
        return LLMResponse(
            content=self._response,
            model="mock",
            usage=TokenUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
        )


def _get_provider(fallback_response: str = "Done.") -> LLMProvider:
    """Return Azure provider if AZURE_OPENAI_ENDPOINT is set, else mock."""
    if os.environ.get("AZURE_OPENAI_ENDPOINT"):
        from hiveflow.plugins.llm import get_llm_registry
        registry = get_llm_registry()
        deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
        provider, _ = registry.resolve_model(f"azure:{deployment}")
        return provider
    return MockProvider(fallback_response)


def _get_model() -> str | None:
    """Return the Azure deployment name if using Azure, else None."""
    if os.environ.get("AZURE_OPENAI_ENDPOINT"):
        return os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
    return None


# -- Event logger -- collects and prints events in real time ----------------

class EventLogger:
    """Collects events and prints them as they arrive."""

    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    def __call__(self, event_type: str, agent_id: str, data: dict) -> None:
        self.events.append((event_type, agent_id, data))
        # Print each event as it arrives (like a live dashboard)
        agent_str = f" [{agent_id}]" if agent_id else ""
        print(f"  >> {event_type}{agent_str}: {_summarize(data)}")


def _summarize(data: dict) -> str:
    """Summarize event data for display."""
    if not data:
        return "{}"
    # Show key fields, truncate long values
    parts = []
    for k, v in data.items():
        v_str = str(v)
        if len(v_str) > 60:
            v_str = v_str[:57] + "..."
        parts.append(f"{k}={v_str}")
    return ", ".join(parts)


async def main() -> None:
    """Execute a workflow with event logging, then resume and log more events."""
    live = bool(os.environ.get("AZURE_OPENAI_ENDPOINT"))
    mode = "Azure OpenAI (RBAC)" if live else "Mock provider"
    print(f"Workflow Event Stream Example  [{mode}]")
    print("=" * 60)

    provider = _get_provider()
    model = _get_model()
    model_kwarg = {"model": f"azure:{model}"} if model else {}

    agents = {
        "researcher": Agent(
            agent_id="researcher",
            role="Researcher",
            system_prompt="You are a researcher. Provide 2-3 key findings about the given topic. Be concise.",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=provider,
            **model_kwarg,
        ),
        "writer": Agent(
            agent_id="writer",
            role="Writer",
            system_prompt="You are a writer. Write a short summary based on the research findings. Be concise.",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            llm_provider=provider,
            **model_kwarg,
        ),
    }

    steps = [
        WorkflowStep(
            agent="researcher",
            step_type=StepType.SEQUENTIAL,
            next_step="review_gate",
        ),
        WorkflowStep(
            agent="review_gate",
            step_type=StepType.GATED,
            gate_id="review_gate",
            gate_description="Review research before writing",
            next_step="writer",
        ),
        WorkflowStep(
            agent="writer",
            step_type=StepType.SEQUENTIAL,
        ),
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        storage = FileCheckpointStorage(directory=tmpdir)
        logger = EventLogger()

        # -- Execute until gate (events: step_start, step_complete, gate_requested, checkpoint_saved) --
        print("\n--- Execute phase (pauses at gate) ---")
        engine = WorkflowEngine(steps)
        engine.on_event(logger)

        result = await engine.execute(
            agents,
            {"task": "Write an AI safety overview"},
            checkpoint_storage=storage,
            session_id="events-demo",
        )

        print(f"\nResult: {result.status.value}")
        print(f"Events captured: {len(logger.events)}")

        # Show summary of event types
        event_types = [e[0] for e in logger.events]
        print(f"Event sequence: {' -> '.join(event_types)}")

        # -- Resume (events: approval, step_start, step_complete, output) --
        print("\n--- Resume phase (continues after gate) ---")
        logger.events.clear()

        checkpoint = await storage.load("events-demo")
        assert checkpoint is not None

        engine2 = WorkflowEngine(steps)
        engine2.on_event(logger)

        result2 = await engine2.resume(
            agents,
            checkpoint,
            responses={"approved": True},
        )

        print(f"\nResult: {result2.status.value}")
        print(f"Events captured: {len(logger.events)}")
        event_types2 = [e[0] for e in logger.events]
        print(f"Event sequence: {' -> '.join(event_types2)}")

        # -- Summary --
        print("\n--- Event type reference ---")
        all_types = sorted(set(event_types + event_types2))
        for t in all_types:
            count = event_types.count(t) + event_types2.count(t)
            print(f"  {t}: {count} occurrence(s)")


if __name__ == "__main__":
    asyncio.run(main())
