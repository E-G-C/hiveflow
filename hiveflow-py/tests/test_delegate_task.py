"""Unit tests for DelegateTaskTool."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hiveflow.core.agent import Agent, AgentBehaviorType
from hiveflow.core.collaboration import CollaborationRuntime
from hiveflow.core.schema import CollaborationConfig
from hiveflow.plugins.llm import LLMConfig
from hiveflow.plugins.tools.delegate_task import DelegateTaskTool


def _make_agent(agent_id: str, role: str = "Test") -> Agent:
    return Agent(
        agent_id=agent_id,
        role=role,
        system_prompt=f"You are a {role.lower()}.",
        behavior_type=AgentBehaviorType.LLM_ONLY,
    )


def _make_runtime(agents: dict[str, Agent] | None = None) -> CollaborationRuntime:
    if agents is None:
        agents = {}
    config = CollaborationConfig(enabled=True)
    archetype_lib = MagicMock()
    archetype_lib.get.return_value = None
    tool_registry = MagicMock()
    tool_registry.get.return_value = None
    return CollaborationRuntime(
        config=config,
        agents=agents,
        archetype_library=archetype_lib,
        tool_registry=tool_registry,
        llm_provider=MagicMock(),
        llm_config=LLMConfig(),
    )


class TestDelegateTaskTool:
    @pytest.mark.asyncio
    async def test_successful_delegation(self):
        delegate = _make_agent("worker", "Worker")
        delegate.execute = AsyncMock(return_value={"worker_output": "done"})
        boss = _make_agent("boss")
        rt = _make_runtime(agents={"worker": delegate, "boss": boss})

        tool = DelegateTaskTool(runtime=rt, caller_agent_id="boss", state={})
        result = await tool.execute({"task": "do work", "delegate_to": "worker"})

        assert result["status"] == "completed"
        assert result["result"] == "done"
        assert result["agent_id"] == "worker"

    @pytest.mark.asyncio
    async def test_auto_selection(self):
        researcher = _make_agent("r1", "Deep researcher and analyst expert")
        researcher.execute = AsyncMock(return_value={"r1_output": "found it"})
        boss = _make_agent("boss")
        rt = _make_runtime(agents={"r1": researcher, "boss": boss})

        tool = DelegateTaskTool(runtime=rt, caller_agent_id="boss", state={})
        result = await tool.execute({
            "task": "deep researcher and analyst expert needed",
            "delegate_to": "auto",
        })

        assert result["status"] == "completed"
        assert result["agent_id"] == "r1"

    @pytest.mark.asyncio
    async def test_fallback_agent_creation(self):
        """When auto-select finds no match, a fallback agent is spawned."""
        boss = _make_agent("boss")
        rt = _make_runtime(agents={"boss": boss})

        # The runtime will spawn a fallback agent; we need to make it executable
        original_spawn = rt.spawn_from_definition

        def mock_spawn(definition, spawned_by, **kwargs):
            agent = _make_agent("spawned_General_Assistant_abc123", "General Assistant")
            agent.execute = AsyncMock(return_value={
                f"{agent.agent_id}_output": "fallback result"
            })
            rt._agent_pool[agent.agent_id] = agent
            rt._spawned_count += 1
            return agent

        rt.spawn_from_definition = mock_spawn

        tool = DelegateTaskTool(runtime=rt, caller_agent_id="boss", state={})
        result = await tool.execute({
            "task": "something obscure xyz",
            "delegate_to": "auto",
        })

        assert result["status"] == "completed"
        assert "fallback result" in result["result"]

    @pytest.mark.asyncio
    async def test_depth_limit_refusal(self):
        config = CollaborationConfig(enabled=True, max_delegation_depth=1)
        worker = _make_agent("worker")
        boss = _make_agent("boss")
        rt = _make_runtime(agents={"worker": worker, "boss": boss})
        rt.config = config

        # Already at depth 1, so depth+1 = 2 > max of 1
        tool = DelegateTaskTool(
            runtime=rt, caller_agent_id="boss",
            state={"_delegation_depth": 1},
        )
        result = await tool.execute({"task": "do it", "delegate_to": "worker"})

        assert result["status"] == "failed"
        assert "depth" in result["result"].lower()

    @pytest.mark.asyncio
    async def test_timeout_handling(self):
        config = CollaborationConfig(enabled=True, delegation_timeout_seconds=1)

        async def slow_execute(state):
            await asyncio.sleep(10)
            return state

        worker = _make_agent("worker")
        worker.execute = slow_execute
        boss = _make_agent("boss")
        rt = _make_runtime(agents={"worker": worker, "boss": boss})
        rt.config = config

        tool = DelegateTaskTool(runtime=rt, caller_agent_id="boss", state={})
        result = await tool.execute({"task": "slow task", "delegate_to": "worker"})

        assert result["status"] == "timeout"

    @pytest.mark.asyncio
    async def test_self_delegation_rejection(self):
        boss = _make_agent("boss")
        rt = _make_runtime(agents={"boss": boss})

        tool = DelegateTaskTool(runtime=rt, caller_agent_id="boss", state={})
        result = await tool.execute({"task": "do it", "delegate_to": "boss"})

        assert result["status"] == "failed"
        assert "self-delegation" in result["result"].lower()

    @pytest.mark.asyncio
    async def test_failure_propagation(self):
        worker = _make_agent("worker")
        worker.execute = AsyncMock(side_effect=RuntimeError("agent crashed"))
        boss = _make_agent("boss")
        rt = _make_runtime(agents={"worker": worker, "boss": boss})

        tool = DelegateTaskTool(runtime=rt, caller_agent_id="boss", state={})
        result = await tool.execute({"task": "do it", "delegate_to": "worker"})

        assert result["status"] == "failed"
        assert "agent crashed" in result["result"]

    @pytest.mark.asyncio
    async def test_unknown_agent_returns_failed(self):
        boss = _make_agent("boss")
        rt = _make_runtime(agents={"boss": boss})

        tool = DelegateTaskTool(runtime=rt, caller_agent_id="boss", state={})
        result = await tool.execute({"task": "do it", "delegate_to": "nonexistent"})

        assert result["status"] == "failed"
        assert "not found" in result["result"].lower()

    def test_tool_spec_format(self):
        tool = DelegateTaskTool(runtime=MagicMock(), caller_agent_id="test", state={})
        spec = tool.to_llm_tool_spec()
        assert spec["type"] == "function"
        assert spec["function"]["name"] == "delegate_task"
        assert "task" in spec["function"]["parameters"]["required"]
