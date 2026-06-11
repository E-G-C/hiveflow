"""Unit tests for SpawnAgentTool."""

from unittest.mock import MagicMock

import pytest

from hiveflow.core.agent import Agent, AgentBehaviorType
from hiveflow.core.collaboration import CollaborationRuntime
from hiveflow.core.schema import CollaborationConfig
from hiveflow.plugins.llm import LLMConfig
from hiveflow.plugins.tools.spawn_agent import SpawnAgentTool


def _make_agent(agent_id: str, role: str = "Test") -> Agent:
    return Agent(
        agent_id=agent_id,
        role=role,
        system_prompt=f"You are a {role.lower()}.",
        behavior_type=AgentBehaviorType.LLM_ONLY,
    )


def _make_runtime(
    agents: dict[str, Agent] | None = None,
    config: CollaborationConfig | None = None,
) -> CollaborationRuntime:
    if agents is None:
        agents = {}
    if config is None:
        config = CollaborationConfig(enabled=True, max_spawned_agents=5)
    archetype_lib = MagicMock()
    archetype_lib.list_archetypes.return_value = ["researcher", "writer", "reviewer"]
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


class TestSpawnAgentTool:
    @pytest.mark.asyncio
    async def test_spawn_from_archetype(self):
        boss = _make_agent("boss")
        rt = _make_runtime(agents={"boss": boss})
        rt._archetype_library.get.return_value = {
            "role": "Researcher",
            "system_prompt": "You research things.",
            "behavior_type": "llm_only",
            "tools": [],
        }

        tool = SpawnAgentTool(runtime=rt, caller_agent_id="boss")
        result = await tool.execute({"archetype": "researcher"})

        assert result["status"] == "spawned"
        assert result["role"] == "Researcher"
        assert result["agent_id"]  # non-empty
        assert rt.spawned_count == 1

    @pytest.mark.asyncio
    async def test_spawn_from_custom_definition(self):
        boss = _make_agent("boss")
        rt = _make_runtime(agents={"boss": boss})

        tool = SpawnAgentTool(runtime=rt, caller_agent_id="boss")
        result = await tool.execute({
            "custom_definition": {
                "role": "Data Analyst",
                "system_prompt": "Analyze data.",
                "behavior_type": "llm_only",
                "tools": [],
            }
        })

        assert result["status"] == "spawned"
        assert result["role"] == "Data Analyst"

    @pytest.mark.asyncio
    async def test_spawn_with_custom_id(self):
        boss = _make_agent("boss")
        rt = _make_runtime(agents={"boss": boss})
        rt._archetype_library.get.return_value = {
            "role": "Writer",
            "system_prompt": "Write things.",
            "behavior_type": "llm_only",
            "tools": [],
        }

        tool = SpawnAgentTool(runtime=rt, caller_agent_id="boss")
        result = await tool.execute({
            "archetype": "writer",
            "agent_id": "my_writer",
        })

        assert result["agent_id"] == "my_writer"

    @pytest.mark.asyncio
    async def test_spawn_limit_refusal(self):
        config = CollaborationConfig(enabled=True, max_spawned_agents=1)
        boss = _make_agent("boss")
        rt = _make_runtime(agents={"boss": boss}, config=config)
        rt._archetype_library.get.return_value = {
            "role": "Helper",
            "system_prompt": "Help.",
            "behavior_type": "llm_only",
            "tools": [],
        }

        tool = SpawnAgentTool(runtime=rt, caller_agent_id="boss")
        # First spawn succeeds
        r1 = await tool.execute({"archetype": "helper"})
        assert r1["status"] == "spawned"

        # Second spawn hits limit
        r2 = await tool.execute({"archetype": "helper"})
        assert r2["status"] == "failed"
        assert "limit" in r2["error"].lower()

    @pytest.mark.asyncio
    async def test_unknown_archetype_shows_available(self):
        boss = _make_agent("boss")
        rt = _make_runtime(agents={"boss": boss})
        # archetype_lib.get returns None for unknown

        tool = SpawnAgentTool(runtime=rt, caller_agent_id="boss")
        result = await tool.execute({"archetype": "nonexistent"})

        assert result["status"] == "failed"
        assert "not found" in result["error"].lower()
        assert "researcher" in result["error"]

    @pytest.mark.asyncio
    async def test_recursive_orchestrator_blocked(self):
        config = CollaborationConfig(
            enabled=True, allow_recursive_orchestrators=False
        )
        boss = _make_agent("boss")
        rt = _make_runtime(agents={"boss": boss}, config=config)
        rt._archetype_library.get.return_value = {
            "role": "Sub-orchestrator",
            "system_prompt": "Orchestrate sub-tasks.",
            "behavior_type": "orchestrator",
            "tools": [],
        }

        tool = SpawnAgentTool(runtime=rt, caller_agent_id="boss")
        result = await tool.execute({"archetype": "orchestrator"})

        assert result["status"] == "failed"
        assert "orchestrator" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_no_archetype_or_definition_returns_error(self):
        boss = _make_agent("boss")
        rt = _make_runtime(agents={"boss": boss})

        tool = SpawnAgentTool(runtime=rt, caller_agent_id="boss")
        result = await tool.execute({})

        assert result["status"] == "failed"
        assert "required" in result["error"].lower()

    def test_description_includes_archetypes(self):
        rt = _make_runtime()
        tool = SpawnAgentTool(runtime=rt, caller_agent_id="boss")
        assert "researcher" in tool.description
        assert "writer" in tool.description

    def test_tool_spec_format(self):
        rt = _make_runtime()
        tool = SpawnAgentTool(runtime=rt, caller_agent_id="boss")
        spec = tool.to_llm_tool_spec()
        assert spec["type"] == "function"
        assert spec["function"]["name"] == "spawn_agent"
        assert "archetype" in spec["function"]["parameters"]["properties"]
        assert "custom_definition" in spec["function"]["parameters"]["properties"]
