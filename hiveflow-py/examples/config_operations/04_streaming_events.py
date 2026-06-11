"""Example: Streaming Events, EventMetadata, and JSON-Lines Audit Log.

Demonstrates how to:
1. Create stream events with the 26 event types
2. Attach structured EventMetadata (tokens, latency, model, cost)
3. Use JsonLinesWriter to persist events to a date-based audit file
4. Subscribe to a StreamChannel for real-time fan-out
5. Make a live LLM call and observe the executor events

Uses live Azure OpenAI via RBAC for the agent execution demo.

Prerequisites:
    AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com
    uv sync --extra llm-azure

Usage:
    AZURE_OPENAI_ENDPOINT=https://foundry-aisbx-we.cognitiveservices.azure.com \
        uv run python examples/config_operations/04_streaming_events.py
"""

import asyncio
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from hiveflow.core.streaming import (
    EventMetadata,
    JsonLinesWriter,
    StreamChannel,
    StreamEvent,
    StreamEventType,
)


async def main() -> None:
    # -- 1. All 26 event types -------------------------------------------------
    print("--- 1. All StreamEventType values ---")
    for i, evt_type in enumerate(StreamEventType, 1):
        print(f"  {i:2d}. {evt_type.value}")
    print(f"  Total: {len(StreamEventType)}")

    # -- 2. Create events with metadata ----------------------------------------
    print("\n--- 2. StreamEvent with EventMetadata ---")
    event = StreamEvent(
        event_type=StreamEventType.EXECUTOR_COMPLETED,
        agent_id="researcher",
        step_id="step-42",
        content="Analysis of renewable energy trends complete.",
        metadata=EventMetadata(
            tokens_used=1500,
            latency_ms=2340.5,
            model="gpt-4o",
            cost_usd=0.0045,
        ),
    )
    print(f"  Event type:  {event.event_type}")
    print(f"  Agent:       {event.agent_id}")
    print(f"  Step:        {event.step_id}")
    print(f"  Timestamp:   {event.timestamp.isoformat()}")
    print(f"  Metadata:    tokens={event.metadata.tokens_used}, "
          f"latency={event.metadata.latency_ms}ms, "
          f"cost=${event.metadata.cost_usd}")
    print(f"  Serialized:  {json.dumps(event.to_dict(), default=str)[:120]}...")

    # -- 3. JsonLinesWriter audit log ------------------------------------------
    print("\n--- 3. JsonLinesWriter audit log ---")
    output_dir = Path(tempfile.mkdtemp(prefix="hiveflow_events_"))
    writer = JsonLinesWriter(str(output_dir))

    events = [
        StreamEvent(event_type=StreamEventType.WORKFLOW_START, content="Workflow begins"),
        StreamEvent(event_type=StreamEventType.EXECUTOR_INVOKED, agent_id="researcher",
                    step_id="s1", content="Starting research"),
        StreamEvent(event_type=StreamEventType.TOKEN, agent_id="researcher", token="The"),
        StreamEvent(event_type=StreamEventType.TOKEN, agent_id="researcher", token=" answer"),
        StreamEvent(event_type=StreamEventType.EXECUTOR_COMPLETED, agent_id="researcher",
                    step_id="s1", content="Research done",
                    metadata=EventMetadata(tokens_used=500, latency_ms=1200)),
        StreamEvent(event_type=StreamEventType.COST, data={"total_usd": 0.003}),
        StreamEvent(event_type=StreamEventType.WORKFLOW_END, content="Workflow complete"),
    ]

    for evt in events:
        await writer.on_event(evt)
    await writer.close()

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log_file = output_dir / f"events-{today}.jsonl"
    print(f"  Written to: {log_file}")
    lines = log_file.read_text(encoding="utf-8").strip().split("\n")
    print(f"  Lines written: {len(lines)}")
    for line in lines:
        data = json.loads(line)
        print(f"    {data['type']:25s} {data.get('agent_id', ''):15s} {data.get('content', '')[:40]}")

    # -- 4. StreamChannel fan-out ----------------------------------------------
    print("\n--- 4. StreamChannel fan-out ---")
    channel = StreamChannel()
    consumer = channel.subscribe()

    # Publish events
    for evt in events[:3]:
        await channel.publish(evt)
    await channel.close()

    # Consume
    received = []
    async for evt in consumer:
        received.append(evt)
    print(f"  Published: {len(events[:3])} events")
    print(f"  Received:  {len(received)} events")

    # -- 5. Live agent execution with executor events --------------------------
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    if not endpoint:
        print("\n--- 5. Skipped (set AZURE_OPENAI_ENDPOINT for live demo) ---")
        return

    print("\n--- 5. Live agent execution with executor events ---")
    from hiveflow.plugins.llm import LLMConfig, LLMMessage, get_llm_registry
    from hiveflow import Agent, AgentBehaviorType

    registry = get_llm_registry()
    if "azure" not in registry.list_ids():
        print("  Azure provider not available. Install with: uv sync --extra llm-azure")
        return

    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini")
    provider, model = registry.resolve_model(f"azure:{deployment}")

    channel = StreamChannel()
    consumer = channel.subscribe()

    agent = Agent(
        agent_id="demo_agent",
        role="Brief answerer",
        system_prompt="You answer questions in one sentence.",
        behavior_type=AgentBehaviorType.LLM_ONLY,
        llm_provider=provider,
        llm_config=LLMConfig(model=model, max_tokens=50),
    )

    state = {
        "task": "What is the speed of light?",
        "_stream_channel": channel,
    }

    try:
        result = await agent.execute(state)
    except Exception as e:
        await channel.close()
        print(f"  Agent call failed (expected if behind VNet): {type(e).__name__}")
        return

    await channel.close()

    received = []
    async for evt in consumer:
        received.append(evt)

    print(f"  Agent output: {result.get('demo_agent_output', '')[:100]}")
    print(f"  Stream events received: {len(received)}")
    for evt in received:
        meta = ""
        if evt.metadata and evt.metadata.latency_ms:
            meta = f" ({evt.metadata.latency_ms:.0f}ms)"
        print(f"    {evt.event_type.value:25s} {evt.content[:50] if evt.content else ''}{meta}")


if __name__ == "__main__":
    asyncio.run(main())
