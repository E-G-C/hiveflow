"""Tests for streaming protocol: event types, EventMetadata, JsonLinesWriter,
paired executor events."""

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from hiveflow.core.streaming import (
    EventMetadata,
    JsonLinesWriter,
    StreamChannel,
    StreamEvent,
    StreamEventType,
)


class TestStreamEventTypes:
    """All 32 event types are instantiable."""

    def test_total_event_types(self):
        assert len(StreamEventType) == 32

    @pytest.mark.parametrize("event_type", list(StreamEventType))
    def test_each_type_instantiable(self, event_type):
        event = StreamEvent(event_type=event_type)
        assert event.event_type == event_type

    def test_new_types_present(self):
        new_types = [
            "LOG", "HUMAN_REQUEST", "COST", "ROLLBACK",
            "SUMMARY_GENERATED", "OUTLINE_GENERATED", "ASSEMBLY_COMPLETE",
            "EXECUTOR_INVOKED", "EXECUTOR_COMPLETED",
        ]
        for name in new_types:
            assert hasattr(StreamEventType, name)


class TestEventMetadata:
    """EventMetadata fields and serialization."""

    def test_all_fields_default_none(self):
        m = EventMetadata()
        assert m.tokens_used is None
        assert m.latency_ms is None
        assert m.model is None
        assert m.cost_usd is None

    def test_populated_metadata(self):
        m = EventMetadata(tokens_used=100, latency_ms=50.5, model="gpt-4o", cost_usd=0.01)
        assert m.tokens_used == 100
        assert m.latency_ms == 50.5
        assert m.model == "gpt-4o"
        assert m.cost_usd == 0.01


class TestStreamEventSerialization:
    """StreamEvent.to_dict() includes new fields."""

    def test_minimal_event(self):
        event = StreamEvent(event_type=StreamEventType.TOKEN, token="hello")
        d = event.to_dict()
        assert d["type"] == "token"
        assert d["token"] == "hello"
        assert "timestamp" in d

    def test_full_event(self):
        m = EventMetadata(tokens_used=100, model="gpt-4o")
        event = StreamEvent(
            event_type=StreamEventType.EXECUTOR_COMPLETED,
            agent_id="agent-1",
            step_id="step-42",
            content="output text",
            metadata=m,
        )
        d = event.to_dict()
        assert d["agent_id"] == "agent-1"
        assert d["step_id"] == "step-42"
        assert d["content"] == "output text"
        assert d["metadata"]["tokens_used"] == 100
        assert d["metadata"]["model"] == "gpt-4o"
        assert "latency_ms" not in d["metadata"]  # None fields excluded

    def test_timestamp_is_utc(self):
        event = StreamEvent(event_type=StreamEventType.LOG)
        assert event.timestamp.tzinfo is not None


class TestJsonLinesWriter:
    """JsonLinesWriter creates date-based files and writes JSON lines."""

    async def test_creates_file(self, tmp_path):
        writer = JsonLinesWriter(str(tmp_path))
        event = StreamEvent(
            event_type=StreamEventType.LOG,
            agent_id="test",
            content="hello",
        )
        await writer.on_event(event)
        await writer.close()

        files = list(tmp_path.glob("events-*.jsonl"))
        assert len(files) == 1

    async def test_writes_valid_json_lines(self, tmp_path):
        writer = JsonLinesWriter(str(tmp_path))
        for i in range(3):
            await writer.on_event(StreamEvent(
                event_type=StreamEventType.OUTPUT,
                agent_id=f"agent-{i}",
            ))
        await writer.close()

        files = list(tmp_path.glob("events-*.jsonl"))
        lines = files[0].read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 3
        for line in lines:
            data = json.loads(line)
            assert "type" in data

    async def test_file_name_contains_date(self, tmp_path):
        writer = JsonLinesWriter(str(tmp_path))
        await writer.on_event(StreamEvent(event_type=StreamEventType.LOG))
        await writer.close()

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        files = list(tmp_path.glob(f"events-{today}.jsonl"))
        assert len(files) == 1

    async def test_close_is_idempotent(self, tmp_path):
        writer = JsonLinesWriter(str(tmp_path))
        await writer.on_event(StreamEvent(event_type=StreamEventType.LOG))
        await writer.close()
        await writer.close()  # Should not raise


class TestPairedExecutorEvents:
    """EXECUTOR_INVOKED and EXECUTOR_COMPLETED event creation."""

    def test_invoked_event(self):
        event = StreamEvent(
            event_type=StreamEventType.EXECUTOR_INVOKED,
            agent_id="researcher",
            step_id="step-1",
            content="Starting research",
            data={"task": "analyze data"},
        )
        d = event.to_dict()
        assert d["type"] == "executor_invoked"
        assert d["agent_id"] == "researcher"
        assert d["step_id"] == "step-1"

    def test_completed_event_with_metadata(self):
        event = StreamEvent(
            event_type=StreamEventType.EXECUTOR_COMPLETED,
            agent_id="researcher",
            step_id="step-1",
            content="Research complete",
            metadata=EventMetadata(latency_ms=1500, tokens_used=4000),
        )
        d = event.to_dict()
        assert d["type"] == "executor_completed"
        assert d["metadata"]["latency_ms"] == 1500
        assert d["metadata"]["tokens_used"] == 4000
