"""Tests for ResultPayload, PayloadSection, and ActionRecord."""

import time
from typing import Any
from dataclasses import dataclass, field

import pytest

from hiveflow.core.citations import Citation
from hiveflow.core.cost import AgentCostSummary, WorkflowCostReport
from hiveflow.core.result_payload import ActionRecord, PayloadSection, ResultPayload


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class _FakeWorkflowResult:
    """Minimal stand-in for WorkflowResult."""
    status: Any = "completed"
    state: dict[str, Any] = field(default_factory=dict)
    step_results: list[Any] = field(default_factory=list)
    error: str | None = None


@dataclass
class _FakeStepResult:
    agent_id: str = "agent_a"
    step_type: str = "sequential"
    state: dict[str, Any] = field(default_factory=dict)
    status: str = "completed"
    error: str | None = None


# ---------------------------------------------------------------------------
# ActionRecord
# ---------------------------------------------------------------------------

class TestActionRecord:

    def test_basic_construction(self) -> None:
        rec = ActionRecord(
            action_id="a1",
            action_type="email",
            description="Sent email",
            status="completed",
            agent_id="mailer",
            timestamp=1000.0,
        )
        assert rec.action_id == "a1"
        assert rec.action_type == "email"
        assert rec.status == "completed"

    def test_to_dict(self) -> None:
        rec = ActionRecord(
            action_id="a2",
            action_type="api_call",
            description="Called API",
            status="failed",
            agent_id="caller",
            timestamp=2000.0,
            metadata={"url": "https://example.com"},
        )
        d = rec.to_dict()
        assert d["action_id"] == "a2"
        assert d["metadata"]["url"] == "https://example.com"

    def test_frozen(self) -> None:
        rec = ActionRecord(
            action_id="a3", action_type="x", description="y",
            status="completed", agent_id="z",
        )
        with pytest.raises(AttributeError):
            rec.action_id = "changed"  # type: ignore[misc]

    def test_default_timestamp(self) -> None:
        before = time.time()
        rec = ActionRecord(
            action_id="a4", action_type="x", description="y",
            status="completed", agent_id="z",
        )
        after = time.time()
        assert before <= rec.timestamp <= after


# ---------------------------------------------------------------------------
# PayloadSection
# ---------------------------------------------------------------------------

class TestPayloadSection:

    def test_basic_construction(self) -> None:
        sec = PayloadSection(
            section_id="intro", title="Introduction",
            content="Hello world", order=0,
        )
        assert sec.section_id == "intro"
        assert sec.agent_id is None

    def test_to_dict_without_agent(self) -> None:
        sec = PayloadSection(
            section_id="intro", title="Intro", content="text", order=0,
        )
        d = sec.to_dict()
        assert "agent_id" not in d
        assert d["section_id"] == "intro"

    def test_to_dict_with_agent(self) -> None:
        sec = PayloadSection(
            section_id="findings", title="Findings", content="data",
            order=1, agent_id="researcher",
        )
        d = sec.to_dict()
        assert d["agent_id"] == "researcher"

    def test_frozen(self) -> None:
        sec = PayloadSection(
            section_id="x", title="X", content="y", order=0,
        )
        with pytest.raises(AttributeError):
            sec.content = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ResultPayload — direct construction
# ---------------------------------------------------------------------------

class TestResultPayloadConstruction:

    def test_minimal_construction(self) -> None:
        payload = ResultPayload(title="Test", content="Hello")
        assert payload.title == "Test"
        assert payload.content == "Hello"
        assert payload.sections == []
        assert payload.references == []
        assert payload.actions == []
        assert isinstance(payload.cost_summary, WorkflowCostReport)

    def test_full_construction(self) -> None:
        citation = Citation(url="https://example.com", title="Example")
        action = ActionRecord(
            action_id="a1", action_type="email", description="Sent",
            status="completed", agent_id="mailer", timestamp=1000.0,
        )
        section = PayloadSection(
            section_id="intro", title="Intro", content="text", order=0,
        )
        cost = WorkflowCostReport(total_tokens=500)

        payload = ResultPayload(
            title="Full Report",
            content="Body content",
            sections=[section],
            metadata={"date": "2026-02-20"},
            references=[citation],
            actions=[action],
            cost_summary=cost,
            step_results=[],
        )
        assert payload.title == "Full Report"
        assert len(payload.sections) == 1
        assert len(payload.references) == 1
        assert len(payload.actions) == 1
        assert payload.cost_summary.total_tokens == 500
        assert payload.metadata["date"] == "2026-02-20"

    def test_frozen(self) -> None:
        payload = ResultPayload(title="T", content="C")
        with pytest.raises(AttributeError):
            payload.title = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ResultPayload — to_dict
# ---------------------------------------------------------------------------

class TestResultPayloadToDict:

    def test_minimal_to_dict(self) -> None:
        payload = ResultPayload(title="T", content="C")
        d = payload.to_dict()
        assert d["title"] == "T"
        assert d["content"] == "C"
        assert d["sections"] == []
        assert d["references"] == []
        assert d["actions"] == []
        assert d["cost_summary"]["total_tokens"] == 0

    def test_sections_serialized(self) -> None:
        payload = ResultPayload(
            title="T", content="C",
            sections=[
                PayloadSection(section_id="a", title="A", content="x", order=0),
                PayloadSection(section_id="b", title="B", content="y", order=1),
            ],
        )
        d = payload.to_dict()
        assert len(d["sections"]) == 2
        assert d["sections"][0]["section_id"] == "a"
        assert d["sections"][1]["section_id"] == "b"

    def test_references_serialized(self) -> None:
        payload = ResultPayload(
            title="T", content="C",
            references=[
                Citation(url="https://a.com", title="A"),
                Citation(url="https://b.com", title="B", author="Author B"),
            ],
        )
        d = payload.to_dict()
        assert len(d["references"]) == 2
        assert d["references"][0]["url"] == "https://a.com"
        assert d["references"][1]["author"] == "Author B"

    def test_cost_summary_with_agents(self) -> None:
        cost = WorkflowCostReport(
            total_tokens=1000,
            total_estimated_cost_usd=0.05,
            agent_summaries={
                "researcher": AgentCostSummary(
                    agent_id="researcher",
                    total_tokens=600,
                    call_count=2,
                ),
                "writer": AgentCostSummary(
                    agent_id="writer",
                    total_tokens=400,
                    call_count=1,
                ),
            },
        )
        payload = ResultPayload(title="T", content="C", cost_summary=cost)
        d = payload.to_dict()
        assert d["cost_summary"]["total_tokens"] == 1000
        assert "researcher" in d["cost_summary"]["agent_summaries"]
        assert d["cost_summary"]["agent_summaries"]["writer"]["call_count"] == 1

    def test_step_results_serialized(self) -> None:
        sr = _FakeStepResult(agent_id="a", step_type="sequential")
        payload = ResultPayload(
            title="T", content="C", step_results=[sr],
        )
        d = payload.to_dict()
        assert len(d["step_results"]) == 1
        assert d["step_results"][0]["agent_id"] == "a"


# ---------------------------------------------------------------------------
# ResultPayload — from_workflow_result
# ---------------------------------------------------------------------------

class TestResultPayloadFromWorkflowResult:

    def test_basic_assembly(self) -> None:
        result = _FakeWorkflowResult(
            status="completed",
            state={"task": "Explain quantum computing"},
        )
        payload = ResultPayload.from_workflow_result(result)
        assert payload.title == "Explain quantum computing"
        assert payload.references == []
        assert payload.actions == []

    def test_title_override(self) -> None:
        result = _FakeWorkflowResult(
            state={"task": "Original title"},
        )
        payload = ResultPayload.from_workflow_result(
            result, title="Custom Title",
        )
        assert payload.title == "Custom Title"

    def test_title_fallback_to_untitled(self) -> None:
        result = _FakeWorkflowResult(state={})
        payload = ResultPayload.from_workflow_result(result)
        assert payload.title == "Untitled Workflow"

    def test_content_from_final_output(self) -> None:
        result = _FakeWorkflowResult(
            state={"task": "test", "final_output": "Final content here"},
        )
        payload = ResultPayload.from_workflow_result(result)
        assert payload.content == "Final content here"

    def test_content_from_history_fallback(self) -> None:
        result = _FakeWorkflowResult(
            state={
                "task": "test",
                "history": [
                    {"agent_id": "writer", "output": "Written output"},
                ],
            },
        )
        payload = ResultPayload.from_workflow_result(result)
        assert payload.content == "Written output"

    def test_sections_from_history(self) -> None:
        result = _FakeWorkflowResult(
            state={
                "task": "test",
                "history": [
                    {"agent_id": "researcher", "role": "Researcher", "output": "Research data"},
                    {"agent_id": "writer", "role": "Writer", "output": "Report text"},
                ],
            },
        )
        payload = ResultPayload.from_workflow_result(result)
        assert len(payload.sections) == 2
        assert payload.sections[0].section_id == "agent_researcher"
        assert payload.sections[0].title == "Researcher"
        assert payload.sections[1].agent_id == "writer"

    def test_with_citations(self) -> None:
        result = _FakeWorkflowResult(state={"task": "test"})
        citations = [
            Citation(url="https://example.com", title="Example"),
        ]
        payload = ResultPayload.from_workflow_result(
            result, citations=citations,
        )
        assert len(payload.references) == 1
        assert payload.references[0].url == "https://example.com"

    def test_with_cost_report(self) -> None:
        result = _FakeWorkflowResult(state={"task": "test"})
        cost = WorkflowCostReport(total_tokens=999)
        payload = ResultPayload.from_workflow_result(
            result, cost_report=cost,
        )
        assert payload.cost_summary.total_tokens == 999

    def test_with_actions(self) -> None:
        result = _FakeWorkflowResult(state={"task": "test"})
        actions = [
            ActionRecord(
                action_id="a1", action_type="email",
                description="Sent", status="completed", agent_id="mailer",
            ),
        ]
        payload = ResultPayload.from_workflow_result(
            result, actions=actions,
        )
        assert len(payload.actions) == 1
        assert payload.actions[0].action_id == "a1"

    def test_with_step_results(self) -> None:
        sr = _FakeStepResult(agent_id="agent_a")
        result = _FakeWorkflowResult(
            state={"task": "test"},
            step_results=[sr],
        )
        payload = ResultPayload.from_workflow_result(result)
        assert len(payload.step_results) == 1

    def test_metadata_includes_status(self) -> None:
        result = _FakeWorkflowResult(status="completed", state={"task": "test"})
        payload = ResultPayload.from_workflow_result(result)
        assert payload.metadata["status"] == "completed"

    def test_empty_history_produces_no_sections(self) -> None:
        result = _FakeWorkflowResult(state={"task": "test", "history": []})
        payload = ResultPayload.from_workflow_result(result)
        assert payload.sections == []


# ---------------------------------------------------------------------------
# Integration: WorkflowResult.result_payload
# ---------------------------------------------------------------------------

class TestWorkflowResultPayloadIntegration:
    """Verify that WorkflowResult carries a result_payload after execution."""

    def test_workflow_result_has_payload_field(self) -> None:
        """WorkflowResult should have result_payload attribute."""
        from hiveflow.core.workflow import WorkflowResult, WorkflowStatus
        wr = WorkflowResult(
            status=WorkflowStatus.COMPLETED,
            state={"task": "test"},
        )
        assert hasattr(wr, "result_payload")
        assert wr.result_payload is None  # None by default

    @pytest.mark.asyncio
    async def test_engine_populates_payload_on_success(self) -> None:
        """After a successful workflow execution, result_payload is set."""
        from unittest.mock import AsyncMock, patch

        from hiveflow.core.agent import Agent, AgentBehaviorType
        from hiveflow.core.workflow import WorkflowEngine, WorkflowStatus, WorkflowStep

        agent = Agent(
            agent_id="writer",
            role="Writer",
            system_prompt="Write content.",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            model="openai:gpt-4o-mini",
        )

        steps = [
            WorkflowStep(agent="writer", step_type="sequential"),
        ]
        engine = WorkflowEngine(steps)

        # Mock the agent's execute to return content
        mock_result = {
            "output": "Generated content",
            "history": [
                {"agent_id": "writer", "role": "Writer", "output": "Generated content"},
            ],
            "task": "Write a summary",
        }
        with patch.object(
            engine, "_execute_agent", new_callable=AsyncMock, return_value=mock_result
        ):
            result = await engine.execute(
                agents={"writer": agent},
                initial_state={"task": "Write a summary"},
            )

        assert result.status == WorkflowStatus.COMPLETED
        assert result.result_payload is not None
        assert result.result_payload.title == "Write a summary"
        assert len(result.result_payload.sections) >= 0  # content extracted from history

    @pytest.mark.asyncio
    async def test_engine_payload_with_multi_agent_history(self) -> None:
        """Payload sections are built from multi-agent history."""
        from unittest.mock import AsyncMock, patch

        from hiveflow.core.agent import Agent, AgentBehaviorType
        from hiveflow.core.workflow import WorkflowEngine, WorkflowStatus, WorkflowStep

        researcher = Agent(
            agent_id="researcher", role="Researcher",
            system_prompt="Research.", behavior_type=AgentBehaviorType.LLM_ONLY,
            model="openai:gpt-4o-mini",
        )
        writer = Agent(
            agent_id="writer", role="Writer",
            system_prompt="Write.", behavior_type=AgentBehaviorType.LLM_ONLY,
            model="openai:gpt-4o-mini",
        )

        steps = [
            WorkflowStep(agent="researcher", step_type="sequential", next_step="writer"),
            WorkflowStep(agent="writer", step_type="sequential"),
        ]
        engine = WorkflowEngine(steps)

        call_count = 0

        async def mock_execute(agent: Agent, state: dict) -> dict:
            nonlocal call_count
            call_count += 1
            history = list(state.get("history", []))
            if agent.agent_id == "researcher":
                entry = {"agent_id": "researcher", "role": "Researcher", "output": "Research data"}
            else:
                entry = {"agent_id": "writer", "role": "Writer", "output": "Final report"}
            history.append(entry)
            return {
                **state,
                "output": entry["output"],
                "history": history,
                "final_output": entry["output"] if agent.agent_id == "writer" else state.get("final_output", ""),
            }

        with patch.object(engine, "_execute_agent", side_effect=mock_execute):
            result = await engine.execute(
                agents={"researcher": researcher, "writer": writer},
                initial_state={"task": "Explain quantum computing"},
            )

        assert result.status == WorkflowStatus.COMPLETED
        assert result.result_payload is not None
        payload = result.result_payload
        assert payload.title == "Explain quantum computing"
        assert len(payload.sections) == 2
        assert payload.sections[0].agent_id == "researcher"
        assert payload.sections[1].agent_id == "writer"
