"""Messaging Tools - Inter-agent communication.

Implements send_message and read_messages tool plugins for inter-agent
communication within collaborative workflows.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog

from hiveflow.core.streaming import StreamChannel, StreamEvent, StreamEventType
from hiveflow.plugins.tools import ToolPlugin

logger = structlog.get_logger()


class SendMessageTool(ToolPlugin):
    """Tool for sending messages to other agents.

    Messages are stored in workflow state under _messages and delivered
    to the recipient's next execution context.
    """

    def __init__(
        self,
        caller_agent_id: str,
        state: dict[str, Any],
        stream_channel: StreamChannel | None = None,
    ) -> None:
        self._caller_agent_id = caller_agent_id
        self._state = state
        self._stream_channel = stream_channel

    @property
    def plugin_id(self) -> str:
        return "send_message"

    @property
    def description(self) -> str:
        return (
            "Send a message to another agent. The message will be "
            "available in their next execution context."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Target agent ID, or 'broadcast' to send to all",
                },
                "subject": {
                    "type": "string",
                    "description": "Brief subject line",
                },
                "body": {
                    "type": "string",
                    "description": "The message content",
                },
                "requires_response": {
                    "type": "boolean",
                    "description": "Whether you need a response",
                    "default": False,
                },
            },
            "required": ["to", "body"],
        }

    @property
    def output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "message_id": {"type": "string"},
                "to": {"type": "string"},
            },
        }

    async def execute(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        to_agent = tool_input["to"]
        body = tool_input["body"]
        subject = tool_input.get("subject")
        requires_response = tool_input.get("requires_response", False)

        message_id = str(uuid.uuid4())
        message = {
            "message_id": message_id,
            "from_agent": self._caller_agent_id,
            "to_agent": to_agent,
            "subject": subject,
            "body": body,
            "requires_response": requires_response,
            "timestamp": datetime.now(UTC).isoformat(),
            "read": False,
        }

        # Store in state under _messages
        messages = self._state.setdefault("_messages", {})
        recipient_key = "_broadcast" if to_agent == "broadcast" else to_agent
        messages.setdefault(recipient_key, []).append(message)

        # Emit event
        if self._stream_channel is not None:
            await self._stream_channel.publish(
                StreamEvent(
                    event_type=StreamEventType.MESSAGE_SENT,
                    data={
                        "message_id": message_id,
                        "from_agent": self._caller_agent_id,
                        "to_agent": to_agent,
                        "subject": subject,
                    },
                )
            )

        return {
            "status": "sent",
            "message_id": message_id,
            "to": to_agent,
        }


class ReadMessagesTool(ToolPlugin):
    """Tool for reading messages from other agents.

    Reads messages stored in workflow state under _messages for the
    calling agent, including broadcast messages.
    """

    def __init__(self, caller_agent_id: str, state: dict[str, Any]) -> None:
        self._caller_agent_id = caller_agent_id
        self._state = state

    @property
    def plugin_id(self) -> str:
        return "read_messages"

    @property
    def description(self) -> str:
        return "Read messages sent to you by other agents."

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "unread_only": {
                    "type": "boolean",
                    "description": "If true, only return unread messages",
                    "default": True,
                },
            },
        }

    @property
    def output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "messages": {
                    "type": "array",
                    "items": {"type": "object"},
                },
                "count": {"type": "integer"},
            },
        }

    async def execute(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        unread_only = tool_input.get("unread_only", True)

        messages_store = self._state.get("_messages", {})

        # Collect direct messages + broadcast messages
        direct = messages_store.get(self._caller_agent_id, [])
        broadcast = messages_store.get("_broadcast", [])
        all_messages = direct + broadcast

        # Filter by read status if needed
        if unread_only:
            result_messages = [m for m in all_messages if not m.get("read", False)]
        else:
            result_messages = list(all_messages)

        # Mark as read
        for msg in result_messages:
            msg["read"] = True

        # Format for output
        formatted = [
            {
                "from": msg["from_agent"],
                "subject": msg.get("subject"),
                "body": msg["body"],
                "requires_response": msg.get("requires_response", False),
                "timestamp": msg["timestamp"],
            }
            for msg in result_messages
        ]

        return {
            "messages": formatted,
            "count": len(formatted),
        }
