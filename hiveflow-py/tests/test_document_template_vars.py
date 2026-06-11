"""Tests for document template variables: $document_count, $document_names, $document_summary."""

from typing import Any

import pytest

from hiveflow.core.agent import Agent, AgentBehaviorType


def _make_agent(system_prompt: str = "Default prompt") -> Agent:
    return Agent(
        agent_id="test",
        role="tester",
        system_prompt=system_prompt,
        behavior_type=AgentBehaviorType.LLM_ONLY,
    )


class TestDocumentVariableResolution:
    """_resolve_document_variables populates from state."""

    def test_document_count(self):
        agent = _make_agent("You have $document_count documents.")
        state = {
            "documents": [
                {"name": "a.txt"},
                {"name": "b.txt"},
            ],
        }
        result = agent._resolve_document_variables(agent.system_prompt, state)
        assert "2" in result

    def test_document_names(self):
        agent = _make_agent("Documents: $document_names")
        state = {
            "documents": [
                {"name": "report.pdf"},
                {"name": "data.csv"},
            ],
        }
        result = agent._resolve_document_variables(agent.system_prompt, state)
        assert "report.pdf" in result
        assert "data.csv" in result

    def test_document_summary(self):
        agent = _make_agent("Summary: $document_summary")
        state = {
            "documents": [],
            "document_summary": "2 documents loaded: a.txt, b.txt",
        }
        result = agent._resolve_document_variables(agent.system_prompt, state)
        assert "2 documents loaded" in result

    def test_defaults_when_no_documents(self):
        agent = _make_agent(
            "Count: $document_count, Names: $document_names, Summary: $document_summary"
        )
        state: dict[str, Any] = {}
        result = agent._resolve_document_variables(agent.system_prompt, state)
        assert "Count: 0" in result
        assert "Names: " in result
        assert "Summary: " in result

    def test_no_substitution_without_variables(self):
        agent = _make_agent("No document variables here.")
        state = {"documents": [{"name": "a.txt"}]}
        result = agent._resolve_document_variables(agent.system_prompt, state)
        assert result == "No document variables here."

    def test_build_messages_integrates_variables(self):
        agent = _make_agent("Processing $document_count documents: $document_names")
        state = {
            "task": "Analyze documents",
            "documents": [
                {"name": "report.pdf"},
                {"name": "notes.md"},
            ],
            "document_summary": "2 docs loaded",
        }
        messages = agent._build_messages(state)
        system_msg = messages[0].content
        assert "2" in system_msg
        assert "report.pdf" in system_msg
        assert "notes.md" in system_msg
