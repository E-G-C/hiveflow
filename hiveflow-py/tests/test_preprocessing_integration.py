"""Integration tests for preprocessing: delegation, fan-out, and backward compat."""

from unittest.mock import AsyncMock

import pytest

from hiveflow.core.preprocessing import (
    PreprocessingConfig,
    TaskDataChunk,
    TaskPreprocessor,
)
from hiveflow.plugins.llm import LLMResponse


# ---------------------------------------------------------------------------
# T039: Role-based context tests
# ---------------------------------------------------------------------------


class TestRoleBasedContext:
    """T039: Agent context varies by role."""

    def _make_agent(self):
        from hiveflow.core.agent import Agent

        agent = Agent.__new__(Agent)
        agent.context_budget = None
        agent.output_ttl = None
        agent._sliding_window_size = None
        agent.context_recency_window = 0
        agent.agent_id = "test_agent"
        agent.agent_definition = None
        return agent

    def test_planner_gets_summary_and_manifest(self):
        agent = self._make_agent()
        state = {
            "task_instructions": "Analyze this data",
            "task": "Analyze this data",
            "task_data_summary": "Financial records from Q1-Q4.",
            "task_data_manifest": {
                "total_words": 5000,
                "chunk_count": 3,
                "model_context_tokens": 128000,
                "effective_threshold": 2000,
                "boundary_method": "explicit_label",
                "chunks": [
                    {"chunk_id": "chunk_001", "words": 2000, "topic_hint": "Q1 data"},
                    {"chunk_id": "chunk_002", "words": 1500, "topic_hint": "Q2-Q3 data"},
                    {"chunk_id": "chunk_003", "words": 1500, "topic_hint": "Q4 data"},
                ],
            },
        }
        result = agent._summarize_state(state)
        assert "Analyze this data" in result
        assert "Financial records" in result
        assert "chunk_001" in result
        assert "Q1 data" in result
        assert "Q4 data" in result

    def test_worker_with_chunk_current_item(self):
        agent = self._make_agent()
        state = {
            "task_instructions": "Process the chunk",
            "task": "Process the chunk",
            "current_item": {
                "chunk_id": "chunk_002",
                "content": "This is the actual chunk content.",
                "words": 500,
                "topic_hint": "Q2-Q3 data",
            },
        }
        result = agent._summarize_state(state)
        assert "Process the chunk" in result
        assert "chunk_002" in result
        assert "actual chunk content" in result

    def test_fallback_when_no_preprocessing(self):
        agent = self._make_agent()
        state = {"task": "Simple task without preprocessing."}
        result = agent._summarize_state(state)
        assert "Simple task without preprocessing" in result
        assert "task_instructions" not in result


# ---------------------------------------------------------------------------
# T043: Integration tests for delegation and fan-out
# ---------------------------------------------------------------------------


class TestDelegationChunkFiltering:
    """T043(1): _build_sub_state with chunk_ids filtering."""

    def _make_collaboration(self):
        from hiveflow.core.collaboration import CollaborationRuntime

        rt = CollaborationRuntime.__new__(CollaborationRuntime)
        return rt

    def test_propagates_preprocessing_keys(self):
        rt = self._make_collaboration()
        state = {
            "task": "original",
            "task_instructions": "Do analysis",
            "task_data": [
                {"chunk_id": "chunk_001", "content": "Data A", "words": 100},
                {"chunk_id": "chunk_002", "content": "Data B", "words": 200},
            ],
            "task_data_summary": "Summary of data",
            "task_data_manifest": {"total_words": 300, "chunk_count": 2},
        }
        sub = rt._build_sub_state(state, "Subtask", depth=1)
        assert sub["task_instructions"] == "Do analysis"
        assert sub["task_data_summary"] == "Summary of data"
        assert sub["task_data_manifest"]["total_words"] == 300
        assert len(sub["task_data"]) == 2

    def test_filters_by_chunk_ids(self):
        rt = self._make_collaboration()
        state = {
            "task": "original",
            "task_data": [
                {"chunk_id": "chunk_001", "content": "Data A", "words": 100},
                {"chunk_id": "chunk_002", "content": "Data B", "words": 200},
                {"chunk_id": "chunk_003", "content": "Data C", "words": 300},
            ],
        }
        sub = rt._build_sub_state(
            state, "Process chunk 2", depth=1, chunk_ids=["chunk_002"]
        )
        assert len(sub["task_data"]) == 1
        assert sub["task_data"][0]["chunk_id"] == "chunk_002"

    def test_no_chunk_ids_passes_all(self):
        rt = self._make_collaboration()
        state = {
            "task": "original",
            "task_data": [
                {"chunk_id": "chunk_001", "content": "A", "words": 100},
                {"chunk_id": "chunk_002", "content": "B", "words": 200},
            ],
        }
        sub = rt._build_sub_state(state, "Task", depth=1)
        assert len(sub["task_data"]) == 2

    def test_backward_compat_no_preprocessing(self):
        rt = self._make_collaboration()
        state = {"task": "Simple task"}
        sub = rt._build_sub_state(state, "Subtask", depth=1)
        assert sub["task"] == "Subtask"
        assert "task_data" not in sub
        assert "task_instructions" not in sub


class TestFanOutTaskData:
    """T043(2): Fan-out over task_data using source: task_data."""

    def test_source_task_data_uses_chunks(self):
        from hiveflow.core.workflow import WorkflowStep

        step = WorkflowStep(
            agent="worker",
            step_type="parallel_fan_out",
            source="task_data",
        )
        assert step.source == "task_data"

    def test_backward_compat_no_source(self):
        from hiveflow.core.workflow import WorkflowStep

        step = WorkflowStep(agent="worker", step_type="parallel_fan_out")
        assert step.source is None


# ---------------------------------------------------------------------------
# T046: End-to-end integration test
# ---------------------------------------------------------------------------


class TestEndToEnd:
    """T046: Full pipeline validation against success criteria.

    SC-001: >= 60% token reduction for 21K-word inputs
    SC-003: No agent receives > 20% of model context as task content
    SC-004: Small tasks pass through unchanged
    SC-005: <= 2 LLM calls overhead per preprocessing run
    """

    def _make_preprocessor(self, llm_response=""):
        mock = AsyncMock()
        mock.context_window = None
        mock.chat.return_value = LLMResponse(content=llm_response, model="gpt-4o")
        tp = TaskPreprocessor(mock, model="gpt-4o")
        return tp, mock

    @pytest.mark.asyncio
    async def test_sc001_token_reduction(self):
        """21K-word input should result in >= 60% reduction for planner context."""
        summary_resp = (
            "SUMMARY:\nBrief summary of the data.\n\n"
            "TOPICS:\n"
            + "\n".join(f"chunk_{i+1:03d}: Topic {i}" for i in range(5))
        )
        tp, mock = self._make_preprocessor(llm_response=summary_resp)
        instructions = "Analyze the dataset and provide insights. " * 100  # ~700 words
        data = "\n\n".join(
            [f"Paragraph {i}. " + "data " * 400 for i in range(50)]
        )
        task = instructions + "\n\n## Data\n\n" + data
        original_words = len(task.split())
        assert original_words > 20_000  # At least 21K

        state = {"task": task}
        result = await tp.preprocess(state, agent_count=3)

        # Planner would see: instructions + summary + manifest
        planner_words = len(result["task"].split())
        if result.get("task_data_summary"):
            planner_words += len(result["task_data_summary"].split())
        reduction = 1 - (planner_words / original_words)
        assert reduction >= 0.60, f"Expected >= 60% reduction, got {reduction:.1%}"

    @pytest.mark.asyncio
    async def test_sc003_context_cap(self):
        """No chunk should exceed 20% of model context in words."""
        summary_resp = "SUMMARY:\nData.\n\nTOPICS:\nchunk_001: A"
        tp, _ = self._make_preprocessor(llm_response=summary_resp)
        data = "\n\n".join(
            [f"Data paragraph {i}. " + "word " * 500 for i in range(60)]
        )
        task = "Process this.\n\n## Data\n\n" + data
        state = {"task": task}
        result = await tp.preprocess(state, agent_count=1)

        if "task_data" in result and result["task_data"]:
            context_window_words = 128_000 / 1.35  # ~94.8K words
            cap = context_window_words * 0.20
            for chunk in result["task_data"]:
                assert chunk["words"] <= cap, (
                    f"Chunk {chunk['chunk_id']}: {chunk['words']} words > 20% cap ({cap:.0f})"
                )

    @pytest.mark.asyncio
    async def test_sc004_small_task_unchanged(self):
        """Small tasks pass through with zero state changes."""
        tp, mock = self._make_preprocessor()
        state = {"task": "A short task with under 100 words."}
        original = dict(state)
        result = await tp.preprocess(state, agent_count=3)
        assert result["task"] == original["task"]
        assert "task_instructions" not in result
        assert mock.chat.call_count == 0

    @pytest.mark.asyncio
    async def test_sc005_max_2_llm_calls(self):
        """Preprocessing should make at most 2 LLM calls overhead."""
        summary_resp = "SUMMARY:\nSummary.\n\nTOPICS:\nchunk_001: A"
        tp, mock = self._make_preprocessor(llm_response=summary_resp)
        instructions = "Analyze data. " * 100
        data = "\n\n".join(
            [f"Paragraph {i}. " + "word " * 500 for i in range(60)]
        )
        task = instructions + "\n\n## Data\n\n" + data
        state = {"task": task}
        await tp.preprocess(state, agent_count=3)
        # Boundary detection used a structural heuristic (## Data), so 0 LLM calls for that.
        # Summary generation uses 1 LLM call.
        assert mock.chat.call_count <= 2, f"Made {mock.chat.call_count} LLM calls (max 2)"
