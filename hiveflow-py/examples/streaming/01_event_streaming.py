#!/usr/bin/env python3
"""Streaming Example: Real-time workflow event streaming.

Demonstrates how to:
  1. Subscribe to workflow events via StreamChannel
  2. Handle different event types (step start/end, output, cost)
  3. Use JsonLinesWriter for event persistence
  4. Access EventMetadata for performance metrics

This example uses mock providers -- no API keys required.

Usage:
    uv run python examples/streaming/01_event_streaming.py
"""

import asyncio
import tempfile

from hiveflow import (
    Agent,
    AgentBehaviorType,
    StreamEventType,
    WorkflowEngine,
    WorkflowStep,
)
from hiveflow.core.streaming import JsonLinesWriter, StreamChannel, StreamEvent
from hiveflow.plugins.llm import LLMConfig, LLMMessage, LLMProvider, LLMResponse, TokenUsage


# ---------------------------------------------------------------------------
# Mock LLM provider
# ---------------------------------------------------------------------------

class MockProvider(LLMProvider):
    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def plugin_id(self) -> str:
        return "mock"

    @property
    def description(self) -> str:
        return "Mock LLM for demonstration"

    async def chat(self, messages: list[LLMMessage], config: LLMConfig) -> LLMResponse:
        system = next((m.content for m in messages if m.role == "system"), "")
        if "research" in system.lower():
            content = "Key finding: solar costs dropped 89% since 2010."
            usage = TokenUsage(prompt_tokens=45, completion_tokens=30, total_tokens=75)
        else:
            content = "The renewable energy sector shows remarkable growth potential."
            usage = TokenUsage(prompt_tokens=80, completion_tokens=25, total_tokens=105)
        return LLMResponse(content=content, model="mock-model", usage=usage)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    print("=" * 60)
    print("  HiveFlow -- Streaming: Real-time Workflow Events")
    print("=" * 60)

    provider = MockProvider()

    researcher = Agent(
        agent_id="researcher",
        role="Researcher",
        system_prompt="Research the given topic and provide findings.",
        behavior_type=AgentBehaviorType.LLM_ONLY,
        llm_provider=provider,
    )
    writer = Agent(
        agent_id="writer",
        role="Writer",
        system_prompt="Write a summary based on research findings.",
        behavior_type=AgentBehaviorType.LLM_ONLY,
        llm_provider=provider,
    )

    steps = [
        WorkflowStep(agent="researcher", step_type="sequential", next_step="writer"),
        WorkflowStep(agent="writer", step_type="sequential"),
    ]
    engine = WorkflowEngine(steps, assembly_agents=["writer"])

    # -- 1. Event callback (simple) ---------------------------------------
    print("\n1. Event callbacks:")

    events_log: list[str] = []

    def on_event(event_type: str, agent_id: str, data: dict) -> None:
        msg = f"   [{event_type:14s}] {agent_id}"
        events_log.append(msg)
        print(msg)

    engine.on_event(on_event)

    result = await engine.execute(
        agents={"researcher": researcher, "writer": writer},
        initial_state={"task": "Benefits of renewable energy"},
    )

    print(f"\n   Total events captured: {len(events_log)}")
    print(f"   Workflow status: {result.status.value}")

    # -- 2. StreamChannel (async) -----------------------------------------
    print(f"\n{'=' * 60}")
    print("2. StreamChannel -- async event pub/sub:")

    channel = StreamChannel(max_buffer=100)

    # Publish some events
    await channel.publish(StreamEvent(
        event_type=StreamEventType.WORKFLOW_START,
        content="Workflow started",
        data={"task": "demo"},
    ))
    await channel.publish(StreamEvent(
        event_type=StreamEventType.STEP_START,
        agent_id="researcher",
        content="Researcher starting",
    ))
    await channel.publish(StreamEvent(
        event_type=StreamEventType.OUTPUT,
        agent_id="researcher",
        content="Found 5 key findings",
        data={"word_count": 150},
    ))
    await channel.publish(StreamEvent(
        event_type=StreamEventType.STEP_END,
        agent_id="researcher",
        content="Researcher complete",
    ))
    await channel.publish(StreamEvent(
        event_type=StreamEventType.COST,
        agent_id="researcher",
        data={"tokens": 75, "cost_usd": 0.001},
    ))

    # Close channel
    await channel.close()

    print(f"   Published 5 events to channel")
    print(f"   Channel closed: {channel.is_closed}")

    # -- 3. JsonLinesWriter -----------------------------------------------
    print(f"\n{'=' * 60}")
    print("3. JsonLinesWriter -- persist events to JSONL file:")

    with tempfile.TemporaryDirectory() as tmpdir:
        writer_obj = JsonLinesWriter(output_dir=tmpdir)

        # Write events
        for event_type in [StreamEventType.WORKFLOW_START, StreamEventType.STEP_START,
                           StreamEventType.OUTPUT, StreamEventType.STEP_END]:
            await writer_obj.on_event(StreamEvent(
                event_type=event_type,
                agent_id="researcher",
                content=f"Event: {event_type.value}",
            ))

        await writer_obj.close()
        print(f"   Written 4 events to {tmpdir}/events-*.jsonl")

    # -- 4. Event type reference ------------------------------------------
    print(f"\n{'=' * 60}")
    print("4. All event types:")

    for i, evt in enumerate(StreamEventType, 1):
        print(f"   {i:2d}. {evt.value}")

    print(f"\n   Total: {len(StreamEventType)} event types")

    # -- Summary ----------------------------------------------------------
    print(f"\n{'=' * 60}")
    print("  Summary")
    print("-" * 60)
    print("  engine.on_event()  -- simple callback for event handling")
    print("  StreamChannel      -- async pub/sub with fan-out")
    print("  JsonLinesWriter    -- persist events to JSONL files")
    print(f"  {len(StreamEventType)} event types covering the full workflow lifecycle")


if __name__ == "__main__":
    asyncio.run(main())
