"""Streaming & Message Protocol - Real-time token streaming for agents.

Provides an async event protocol for streaming LLM output, tool calls,
and workflow state updates to frontends and API consumers. Includes
structured event metadata and a JSON-lines audit log writer.
"""

import asyncio
import contextlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()


class StreamEventType(StrEnum):
    """Types of streaming events."""

    TOKEN = "token"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_END = "tool_call_end"
    AGENT_START = "agent_start"
    AGENT_END = "agent_end"
    STEP_START = "step_start"
    STEP_END = "step_end"
    ERROR = "error"
    STATE_UPDATE = "state_update"
    WORKFLOW_START = "workflow_start"
    WORKFLOW_END = "workflow_end"
    CHECKPOINT_SAVED = "checkpoint_saved"
    ACTION_PROPOSED = "action_proposed"
    ACTION_EXECUTED = "action_executed"
    GATE_REQUESTED = "gate_requested"
    OUTPUT = "output"
    APPROVAL = "approval"
    # New event types (FR-021)
    LOG = "log"
    HUMAN_REQUEST = "human_request"
    COST = "cost"
    ROLLBACK = "rollback"
    SUMMARY_GENERATED = "summary_generated"
    OUTLINE_GENERATED = "outline_generated"
    ASSEMBLY_COMPLETE = "assembly_complete"
    EXECUTOR_INVOKED = "executor_invoked"
    EXECUTOR_COMPLETED = "executor_completed"
    # Collaboration events (010-dynamic-agent-collaboration)
    AGENT_SPAWNED = "agent_spawned"
    DELEGATION_STARTED = "delegation_started"
    DELEGATION_COMPLETED = "delegation_completed"
    DELEGATION_FAILED = "delegation_failed"
    MESSAGE_SENT = "message_sent"
    PLAN_CREATED = "plan_created"


@dataclass
class EventMetadata:
    """Structured metadata for stream events (FR-020)."""

    tokens_used: int | None = None
    latency_ms: float | None = None
    model: str | None = None
    cost_usd: float | None = None


@dataclass
class StreamEvent:
    """A single event in the streaming protocol."""

    event_type: StreamEventType
    agent_id: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    token: str = ""
    step_id: str = ""
    content: str = ""
    metadata: EventMetadata | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Serialize event for transmission."""
        result: dict[str, Any] = {
            "type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
        }
        if self.agent_id:
            result["agent_id"] = self.agent_id
        if self.step_id:
            result["step_id"] = self.step_id
        if self.content:
            result["content"] = self.content
        if self.token:
            result["token"] = self.token
        if self.data:
            result["data"] = self.data
        if self.metadata:
            result["metadata"] = {
                k: v
                for k, v in {
                    "tokens_used": self.metadata.tokens_used,
                    "latency_ms": self.metadata.latency_ms,
                    "model": self.metadata.model,
                    "cost_usd": self.metadata.cost_usd,
                }.items()
                if v is not None
            }
        return result


class StreamChannel:
    """Async channel for publishing and consuming stream events.

    Publishers (agents, workflow engine) push events. Consumers (API endpoints,
    frontend WebSockets) read events asynchronously.

    Supports multiple concurrent consumers via fan-out.
    """

    def __init__(self, max_buffer: int = 1000) -> None:
        """Initialize stream channel.

        Args:
            max_buffer: Maximum events to buffer per consumer
        """
        self._subscribers: list[asyncio.Queue[StreamEvent | None]] = []
        self._max_buffer = max_buffer
        self._closed = False

    def subscribe(self) -> "StreamConsumer":
        """Create a new consumer subscription.

        Returns:
            StreamConsumer that receives events from this channel
        """
        queue: asyncio.Queue[StreamEvent | None] = asyncio.Queue(maxsize=self._max_buffer)
        self._subscribers.append(queue)
        return StreamConsumer(queue, self)

    def _unsubscribe(self, queue: asyncio.Queue[StreamEvent | None]) -> None:
        """Remove a consumer subscription.

        Args:
            queue: The consumer's queue to remove
        """
        if queue in self._subscribers:
            self._subscribers.remove(queue)

    async def publish(self, event: StreamEvent) -> None:
        """Publish an event to all subscribers.

        Args:
            event: Event to publish
        """
        if self._closed:
            return

        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(
                    "Stream consumer buffer full, dropping event: %s",
                    event.event_type,
                )

    async def close(self) -> None:
        """Close the channel, signaling all consumers to stop."""
        self._closed = True
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(None)  # Sentinel for end of stream
            except asyncio.QueueFull:
                # Drain one item to make room for the sentinel
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    continue
                queue.put_nowait(None)

    @property
    def is_closed(self) -> bool:
        """Whether the channel has been closed."""
        return self._closed


class StreamConsumer:
    """Async iterator over stream events from a channel.

    Usage:
        consumer = channel.subscribe()
        async for event in consumer:
            process(event)
    """

    def __init__(
        self,
        queue: asyncio.Queue[StreamEvent | None],
        channel: StreamChannel,
    ) -> None:
        self._queue = queue
        self._channel = channel

    def __aiter__(self) -> "StreamConsumer":
        return self

    async def __anext__(self) -> StreamEvent:
        event = await self._queue.get()
        if event is None:
            raise StopAsyncIteration
        return event

    async def close(self) -> None:
        """Unsubscribe from the channel."""
        self._channel._unsubscribe(self._queue)


class StreamingAgent:
    """Mixin providing streaming capabilities for agents.

    Wraps an agent's LLM provider to emit token events as they arrive.
    """

    @staticmethod
    async def stream_tokens(
        provider: Any,
        messages: list[Any],
        config: Any,
        channel: StreamChannel,
        agent_id: str,
    ) -> str:
        """Stream LLM tokens through a channel.

        Args:
            provider: LLM provider with chat_stream() method
            messages: Conversation messages
            config: LLM configuration
            channel: Stream channel to publish tokens to
            agent_id: Agent identifier for events

        Returns:
            Complete response text
        """
        full_text = ""

        await channel.publish(
            StreamEvent(
                event_type=StreamEventType.AGENT_START,
                agent_id=agent_id,
            )
        )

        try:
            async for token in provider.chat_stream(messages, config):
                full_text += token
                await channel.publish(
                    StreamEvent(
                        event_type=StreamEventType.TOKEN,
                        agent_id=agent_id,
                        token=token,
                    )
                )
        except Exception as e:
            await channel.publish(
                StreamEvent(
                    event_type=StreamEventType.ERROR,
                    agent_id=agent_id,
                    data={"error": type(e).__name__},
                )
            )
            raise

        await channel.publish(
            StreamEvent(
                event_type=StreamEventType.AGENT_END,
                agent_id=agent_id,
                data={"output_length": len(full_text)},
            )
        )

        return full_text


class JsonLinesWriter:
    """Async subscriber that writes StreamEvents as JSON lines to a file.

    Writes to {output_dir}/events-{YYYY-MM-DD}.jsonl using synchronous I/O
    (adequate for the append-only audit log pattern). Opened lazily on first
    event, closed explicitly or on garbage collection.

    Supports async context manager for guaranteed cleanup:
        async with JsonLinesWriter("/logs") as writer:
            await writer.on_event(event)
    """

    def __init__(self, output_dir: str) -> None:
        self._output_dir = Path(output_dir)
        self._file: Any = None
        self._current_date: str = ""

    async def __aenter__(self) -> "JsonLinesWriter":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    def __del__(self) -> None:
        if self._file:
            with contextlib.suppress(Exception):
                self._file.close()
            self._file = None

    def _ensure_file(self) -> None:
        """Open or rotate the log file based on current date."""
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        if self._file is None or today != self._current_date:
            if self._file:
                self._file.close()
            self._output_dir.mkdir(parents=True, exist_ok=True)
            path = self._output_dir / f"events-{today}.jsonl"
            self._file = open(path, "a", encoding="utf-8")  # noqa: SIM115
            self._current_date = today

    async def on_event(self, event: StreamEvent) -> None:
        """Append event as JSON line to the date-based file."""
        self._ensure_file()
        line = json.dumps(event.to_dict(), default=str)
        self._file.write(line + "\n")
        self._file.flush()

    async def close(self) -> None:
        """Flush and close the current file."""
        if self._file:
            self._file.close()
            self._file = None
