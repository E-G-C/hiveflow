"""Unit tests for messaging tools (SendMessageTool, ReadMessagesTool)."""

import asyncio
from unittest.mock import MagicMock

import pytest

from hiveflow.core.streaming import StreamChannel, StreamEventType
from hiveflow.plugins.tools.message import ReadMessagesTool, SendMessageTool


class TestSendMessageTool:
    @pytest.mark.asyncio
    async def test_send_direct_message(self):
        state: dict = {}
        tool = SendMessageTool(caller_agent_id="sender", state=state)
        result = await tool.execute({
            "to": "receiver",
            "body": "Hello!",
            "subject": "Greeting",
        })

        assert result["status"] == "sent"
        assert result["to"] == "receiver"
        assert result["message_id"]
        assert "receiver" in state["_messages"]
        assert len(state["_messages"]["receiver"]) == 1
        msg = state["_messages"]["receiver"][0]
        assert msg["from_agent"] == "sender"
        assert msg["body"] == "Hello!"
        assert msg["subject"] == "Greeting"
        assert msg["read"] is False

    @pytest.mark.asyncio
    async def test_send_broadcast_message(self):
        state: dict = {}
        tool = SendMessageTool(caller_agent_id="sender", state=state)
        result = await tool.execute({
            "to": "broadcast",
            "body": "Attention everyone!",
        })

        assert result["status"] == "sent"
        assert result["to"] == "broadcast"
        assert "_broadcast" in state["_messages"]

    @pytest.mark.asyncio
    async def test_send_with_requires_response(self):
        state: dict = {}
        tool = SendMessageTool(caller_agent_id="sender", state=state)
        await tool.execute({
            "to": "receiver",
            "body": "Please reply",
            "requires_response": True,
        })

        msg = state["_messages"]["receiver"][0]
        assert msg["requires_response"] is True

    @pytest.mark.asyncio
    async def test_send_emits_event(self):
        channel = StreamChannel()
        consumer = channel.subscribe()
        events = []

        async def collect():
            async for event in consumer:
                events.append(event)

        state: dict = {}
        tool = SendMessageTool(
            caller_agent_id="sender", state=state, stream_channel=channel
        )

        task = asyncio.create_task(collect())
        await tool.execute({"to": "receiver", "body": "Hi"})
        await channel.close()
        await task

        assert any(e.event_type == StreamEventType.MESSAGE_SENT for e in events)

    @pytest.mark.asyncio
    async def test_multiple_messages_accumulate(self):
        state: dict = {}
        tool = SendMessageTool(caller_agent_id="sender", state=state)
        await tool.execute({"to": "receiver", "body": "First"})
        await tool.execute({"to": "receiver", "body": "Second"})

        assert len(state["_messages"]["receiver"]) == 2

    def test_tool_spec(self):
        tool = SendMessageTool(caller_agent_id="test", state={})
        spec = tool.to_llm_tool_spec()
        assert spec["function"]["name"] == "send_message"
        assert "to" in spec["function"]["parameters"]["required"]
        assert "body" in spec["function"]["parameters"]["required"]


class TestReadMessagesTool:
    @pytest.mark.asyncio
    async def test_read_unread_messages(self):
        state = {
            "_messages": {
                "reader": [
                    {
                        "message_id": "m1",
                        "from_agent": "sender",
                        "to_agent": "reader",
                        "subject": "Hello",
                        "body": "Hi there",
                        "requires_response": False,
                        "timestamp": "2026-01-01T00:00:00Z",
                        "read": False,
                    }
                ]
            }
        }
        tool = ReadMessagesTool(caller_agent_id="reader", state=state)
        result = await tool.execute({"unread_only": True})

        assert result["count"] == 1
        assert result["messages"][0]["body"] == "Hi there"
        # Message should now be marked read
        assert state["_messages"]["reader"][0]["read"] is True

    @pytest.mark.asyncio
    async def test_read_skips_already_read(self):
        state = {
            "_messages": {
                "reader": [
                    {
                        "message_id": "m1",
                        "from_agent": "sender",
                        "to_agent": "reader",
                        "body": "Already read",
                        "timestamp": "2026-01-01T00:00:00Z",
                        "read": True,
                    }
                ]
            }
        }
        tool = ReadMessagesTool(caller_agent_id="reader", state=state)
        result = await tool.execute({"unread_only": True})

        assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_read_all_messages(self):
        state = {
            "_messages": {
                "reader": [
                    {
                        "message_id": "m1",
                        "from_agent": "sender",
                        "to_agent": "reader",
                        "body": "Read one",
                        "timestamp": "2026-01-01T00:00:00Z",
                        "read": True,
                    },
                    {
                        "message_id": "m2",
                        "from_agent": "sender",
                        "to_agent": "reader",
                        "body": "Unread one",
                        "timestamp": "2026-01-01T00:00:01Z",
                        "read": False,
                    },
                ]
            }
        }
        tool = ReadMessagesTool(caller_agent_id="reader", state=state)
        result = await tool.execute({"unread_only": False})

        assert result["count"] == 2

    @pytest.mark.asyncio
    async def test_includes_broadcast_messages(self):
        state = {
            "_messages": {
                "reader": [
                    {
                        "message_id": "m1",
                        "from_agent": "sender",
                        "to_agent": "reader",
                        "body": "Direct",
                        "timestamp": "2026-01-01T00:00:00Z",
                        "read": False,
                    },
                ],
                "_broadcast": [
                    {
                        "message_id": "m2",
                        "from_agent": "announcer",
                        "to_agent": "broadcast",
                        "body": "Broadcast",
                        "timestamp": "2026-01-01T00:00:01Z",
                        "read": False,
                    },
                ],
            }
        }
        tool = ReadMessagesTool(caller_agent_id="reader", state=state)
        result = await tool.execute({"unread_only": True})

        assert result["count"] == 2

    @pytest.mark.asyncio
    async def test_no_messages_returns_empty(self):
        state: dict = {}
        tool = ReadMessagesTool(caller_agent_id="reader", state=state)
        result = await tool.execute({})

        assert result["count"] == 0
        assert result["messages"] == []

    def test_tool_spec(self):
        tool = ReadMessagesTool(caller_agent_id="test", state={})
        spec = tool.to_llm_tool_spec()
        assert spec["function"]["name"] == "read_messages"
