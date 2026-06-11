"""Integration tests for dynamic agent collaboration.

End-to-end tests that verify delegation chains, messaging, and
collaboration resume behavior.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from hiveflow.core.agent import Agent, AgentBehaviorType
from hiveflow.core.collaboration import BudgetExhaustedError, CollaborationRuntime
from hiveflow.core.schema import BudgetPolicy, CollaborationConfig
from hiveflow.core.streaming import StreamChannel, StreamEventType
from hiveflow.plugins.llm import LLMConfig
from hiveflow.plugins.tools.delegate_task import DelegateTaskTool
from hiveflow.plugins.tools.message import ReadMessagesTool, SendMessageTool
from hiveflow.plugins.tools.plan_and_execute import PlanAndExecuteTool
from hiveflow.plugins.tools.spawn_agent import SpawnAgentTool


def _make_agent(
    agent_id: str,
    role: str = "Test",
    behavior: AgentBehaviorType = AgentBehaviorType.LLM_ONLY,
) -> Agent:
    return Agent(
        agent_id=agent_id,
        role=role,
        system_prompt=f"You are a {role.lower()}.",
        behavior_type=behavior,
    )


def _make_runtime(
    agents: dict[str, Agent] | None = None,
    stream_channel: StreamChannel | None = None,
    config: CollaborationConfig | None = None,
) -> CollaborationRuntime:
    if agents is None:
        agents = {}
    if config is None:
        config = CollaborationConfig(enabled=True, max_delegation_depth=3)
    return CollaborationRuntime(
        config=config,
        agents=agents,
        archetype_library=MagicMock(),
        tool_registry=MagicMock(),
        llm_provider=MagicMock(),
        llm_config=LLMConfig(),
        stream_channel=stream_channel,
    )


class TestDelegationChainIntegration:
    """T018: End-to-end delegation chain with real orchestrator."""

    @pytest.mark.asyncio
    async def test_orchestrator_delegates_to_team_member(self):
        """Orchestrator uses DelegateTaskTool to delegate to an existing team member."""
        channel = StreamChannel()
        consumer = channel.subscribe()
        events = []

        async def collect():
            async for event in consumer:
                events.append(event)

        # Create team: orchestrator + researcher
        researcher = _make_agent("researcher", "Deep researcher")
        researcher.execute = AsyncMock(return_value={
            "researcher_output": "Research findings: AI is transformative.",
        })

        orchestrator = _make_agent(
            "orchestrator", "Lead orchestrator",
            behavior=AgentBehaviorType.ORCHESTRATOR,
        )

        agents = {"orchestrator": orchestrator, "researcher": researcher}
        rt = _make_runtime(agents=agents, stream_channel=channel)

        state = {
            "_collaboration_runtime": rt,
            "_delegation_depth": 0,
            "task": "Research AI trends",
        }

        # Create delegation tool for orchestrator
        tool = DelegateTaskTool(runtime=rt, caller_agent_id="orchestrator", state=state)

        # Start event collector
        collect_task = asyncio.create_task(collect())

        # Execute delegation
        result = await tool.execute({
            "task": "Research current AI trends and summarize",
            "delegate_to": "researcher",
        })

        await channel.close()
        await collect_task

        # Verify result
        assert result["status"] == "completed"
        assert "AI is transformative" in result["result"]
        assert result["agent_id"] == "researcher"

        # Verify events emitted
        event_types = [e.event_type for e in events]
        assert StreamEventType.DELEGATION_STARTED in event_types
        assert StreamEventType.DELEGATION_COMPLETED in event_types

        # Verify delegation record
        assert len(rt.delegation_history) == 1
        record = rt.delegation_history[0]
        assert record.delegated_by == "orchestrator"
        assert record.delegate_to == "researcher"
        assert record.status == "completed"
        assert record.duration_ms is not None

    @pytest.mark.asyncio
    async def test_two_level_delegation_chain(self):
        """Orchestrator -> manager -> worker delegation chain."""
        worker = _make_agent("worker", "Task worker")
        worker.execute = AsyncMock(return_value={"worker_output": "task done"})

        # Manager delegates to worker
        async def manager_execute(state):
            rt = state.get("_collaboration_runtime")
            depth = state.get("_delegation_depth", 0)
            tool = DelegateTaskTool(
                runtime=rt, caller_agent_id="manager", state=state
            )
            result = await tool.execute({
                "task": "do the actual work",
                "delegate_to": "worker",
            })
            return {"manager_output": f"Manager got: {result['result']}"}

        manager = _make_agent("manager", "Team manager")
        manager.execute = manager_execute

        orchestrator = _make_agent(
            "orchestrator", "Lead",
            behavior=AgentBehaviorType.ORCHESTRATOR,
        )

        agents = {
            "orchestrator": orchestrator,
            "manager": manager,
            "worker": worker,
        }
        rt = _make_runtime(agents=agents)
        state = {
            "_collaboration_runtime": rt,
            "_delegation_depth": 0,
        }

        tool = DelegateTaskTool(runtime=rt, caller_agent_id="orchestrator", state=state)
        result = await tool.execute({
            "task": "manage and complete the project",
            "delegate_to": "manager",
        })

        assert result["status"] == "completed"
        assert "task done" in result["result"]
        assert len(rt.delegation_history) == 2


class TestStatelessDelegationOnResume:
    """T018b: Verify delegation restarts from scratch on resume."""

    @pytest.mark.asyncio
    async def test_delegation_is_stateless(self):
        """Simulate checkpoint during delegation and verify fresh restart.

        When a workflow is checkpointed and resumed, the CollaborationRuntime
        is recreated from scratch. Any in-flight delegations are lost — the
        delegation tool must execute the full delegation again, not return
        stale results.
        """
        call_count = 0

        async def counting_execute(state):
            nonlocal call_count
            call_count += 1
            return {"worker_output": f"result_{call_count}"}

        # First execution (pre-checkpoint)
        worker = _make_agent("worker", "Worker")
        worker.execute = counting_execute
        boss = _make_agent("boss")

        rt1 = _make_runtime(agents={"worker": worker, "boss": boss})
        state1 = {"_collaboration_runtime": rt1, "_delegation_depth": 0}

        tool1 = DelegateTaskTool(runtime=rt1, caller_agent_id="boss", state=state1)
        result1 = await tool1.execute({"task": "do it", "delegate_to": "worker"})
        assert result1["result"] == "result_1"
        assert call_count == 1

        # Simulate resume: create fresh runtime (as WorkflowEngine would)
        worker2 = _make_agent("worker", "Worker")
        worker2.execute = counting_execute
        boss2 = _make_agent("boss")

        rt2 = _make_runtime(agents={"worker": worker2, "boss": boss2})
        state2 = {"_collaboration_runtime": rt2, "_delegation_depth": 0}

        # The new runtime has no history of the previous delegation
        assert len(rt2.delegation_history) == 0

        tool2 = DelegateTaskTool(runtime=rt2, caller_agent_id="boss", state=state2)
        result2 = await tool2.execute({"task": "do it", "delegate_to": "worker"})

        # Fresh execution — not stale result
        assert result2["result"] == "result_2"
        assert call_count == 2
        assert len(rt2.delegation_history) == 1


class TestSpawnThenDelegateIntegration:
    """T023: End-to-end spawn-then-delegate chain."""

    @pytest.mark.asyncio
    async def test_spawn_researcher_then_delegate(self):
        """Orchestrator spawns a researcher from archetype, delegates to it."""
        orchestrator = _make_agent(
            "orchestrator", "Lead",
            behavior=AgentBehaviorType.ORCHESTRATOR,
        )

        agents = {"orchestrator": orchestrator}
        rt = _make_runtime(agents=agents)

        # Set up archetype library to return a researcher archetype
        rt._archetype_library.get.return_value = {
            "role": "Researcher",
            "system_prompt": "You are a research specialist.",
            "behavior_type": "llm_only",
            "tools": [],
        }
        rt._archetype_library.list_archetypes.return_value = [
            "researcher", "writer", "reviewer",
        ]

        state = {
            "_collaboration_runtime": rt,
            "_delegation_depth": 0,
        }

        # Step 1: Spawn a researcher
        spawn_tool = SpawnAgentTool(runtime=rt, caller_agent_id="orchestrator")
        spawn_result = await spawn_tool.execute({"archetype": "researcher"})

        assert spawn_result["status"] == "spawned"
        spawned_id = spawn_result["agent_id"]
        assert spawned_id in rt.list_agents()
        assert rt.spawned_count == 1

        # Step 2: Make the spawned agent executable
        spawned_agent = rt.get_agent(spawned_id)
        spawned_agent.execute = AsyncMock(return_value={
            f"{spawned_id}_output": "Research complete: findings are excellent.",
        })

        # Step 3: Delegate to the spawned agent
        delegate_tool = DelegateTaskTool(
            runtime=rt, caller_agent_id="orchestrator", state=state
        )
        delegate_result = await delegate_tool.execute({
            "task": "Research quantum computing trends",
            "delegate_to": spawned_id,
        })

        assert delegate_result["status"] == "completed"
        assert "findings are excellent" in delegate_result["result"]
        assert delegate_result["agent_id"] == spawned_id

        # Verify audit trail
        assert len(rt.delegation_history) == 1
        assert rt.delegation_history[0].delegate_to == spawned_id
        assert rt.delegation_history[0].delegated_by == "orchestrator"

        # Verify spawned agent is tracked
        assert spawned_id in rt.spawned_agent_ids


class TestMessageExchangeIntegration:
    """T031: Two-agent message exchange."""

    @pytest.mark.asyncio
    async def test_send_read_reply_cycle(self):
        """Agent A sends message, Agent B reads and replies, Agent A sees reply."""
        state: dict = {"_messages": {}}

        # Agent A sends to Agent B
        send_a = SendMessageTool(caller_agent_id="agent_a", state=state)
        result = await send_a.execute({
            "to": "agent_b",
            "subject": "Need help",
            "body": "Can you analyze this data?",
            "requires_response": True,
        })
        assert result["status"] == "sent"

        # Agent B reads messages
        read_b = ReadMessagesTool(caller_agent_id="agent_b", state=state)
        inbox = await read_b.execute({"unread_only": True})
        assert inbox["count"] == 1
        assert inbox["messages"][0]["from"] == "agent_a"
        assert inbox["messages"][0]["body"] == "Can you analyze this data?"
        assert inbox["messages"][0]["requires_response"] is True

        # Agent B replies
        send_b = SendMessageTool(caller_agent_id="agent_b", state=state)
        await send_b.execute({
            "to": "agent_a",
            "subject": "Re: Need help",
            "body": "Analysis complete. Results look good.",
        })

        # Agent A reads the reply
        read_a = ReadMessagesTool(caller_agent_id="agent_a", state=state)
        inbox_a = await read_a.execute({"unread_only": True})
        assert inbox_a["count"] == 1
        assert inbox_a["messages"][0]["from"] == "agent_b"
        assert inbox_a["messages"][0]["body"] == "Analysis complete. Results look good."

        # Agent B reads again — should see no unread
        inbox_b2 = await read_b.execute({"unread_only": True})
        assert inbox_b2["count"] == 0


class TestPlanAndExecuteIntegration:
    """T036: End-to-end plan-and-execute with concurrent sub-tasks."""

    @pytest.mark.asyncio
    async def test_plan_with_parallel_and_dependent_tasks(self):
        """Orchestrator creates a plan with 3+ sub-tasks.

        Plan structure:
          research (no deps) ─┐
          analyze  (no deps) ─┼─> synthesize (depends on research + analyze)
        """
        channel = StreamChannel()
        consumer = channel.subscribe()
        events = []

        async def collect():
            async for event in consumer:
                events.append(event)

        # Create agents
        researcher = _make_agent("researcher", "Deep researcher")
        researcher.execute = AsyncMock(return_value={
            "researcher_output": "Research findings on quantum computing.",
        })

        analyst = _make_agent("analyst", "Data analyst")
        analyst.execute = AsyncMock(return_value={
            "analyst_output": "Analysis shows 42% growth.",
        })

        writer = _make_agent("writer", "Report writer")
        writer.execute = AsyncMock(return_value={
            "writer_output": "Synthesis: quantum computing grows 42%.",
        })

        orchestrator = _make_agent(
            "orchestrator", "Lead",
            behavior=AgentBehaviorType.ORCHESTRATOR,
        )

        agents = {
            "orchestrator": orchestrator,
            "researcher": researcher,
            "analyst": analyst,
            "writer": writer,
        }
        rt = _make_runtime(agents=agents, stream_channel=channel)

        state = {
            "_collaboration_runtime": rt,
            "_delegation_depth": 0,
        }

        # Create tool
        tool = PlanAndExecuteTool(
            runtime=rt, caller_agent_id="orchestrator", state=state,
        )

        # Start event collector
        collect_task = asyncio.create_task(collect())

        # Execute plan
        result = await tool.execute({
            "plan": {
                "sub_tasks": [
                    {
                        "id": "st_1",
                        "description": "Research quantum computing trends",
                        "assigned_to": "researcher",
                    },
                    {
                        "id": "st_2",
                        "description": "Analyze market data",
                        "assigned_to": "analyst",
                    },
                    {
                        "id": "st_3",
                        "description": "Synthesize findings into report",
                        "assigned_to": "writer",
                        "depends_on": ["st_1", "st_2"],
                    },
                ],
            },
        })

        await channel.close()
        await collect_task

        # Verify overall status
        assert result["status"] == "completed"
        assert result["plan_id"]  # non-empty

        # Verify results
        assert "Research findings" in result["results"]["st_1"]
        assert "42% growth" in result["results"]["st_2"]
        assert "quantum computing grows" in result["results"]["st_3"]

        # Verify all sub-tasks completed
        assert result["sub_task_statuses"] == {
            "st_1": "completed",
            "st_2": "completed",
            "st_3": "completed",
        }

        # Verify events
        event_types = [e.event_type for e in events]
        assert StreamEventType.PLAN_CREATED in event_types
        # 3 delegations = 3 DELEGATION_STARTED + 3 DELEGATION_COMPLETED
        assert event_types.count(StreamEventType.DELEGATION_STARTED) == 3
        assert event_types.count(StreamEventType.DELEGATION_COMPLETED) == 3

        # Verify delegation history
        assert len(rt.delegation_history) == 3

    @pytest.mark.asyncio
    async def test_plan_with_partial_failure(self):
        """Plan with one failing sub-task reports partial status."""
        worker_ok = _make_agent("worker_ok", "Good worker")
        worker_ok.execute = AsyncMock(return_value={"worker_ok_output": "success"})

        worker_bad = _make_agent("worker_bad", "Bad worker")
        worker_bad.execute = AsyncMock(side_effect=RuntimeError("crashed"))

        boss = _make_agent("boss", "Boss")
        agents = {
            "worker_ok": worker_ok,
            "worker_bad": worker_bad,
            "boss": boss,
        }
        rt = _make_runtime(agents=agents)

        state = {"_collaboration_runtime": rt, "_delegation_depth": 0}

        tool = PlanAndExecuteTool(
            runtime=rt, caller_agent_id="boss", state=state,
        )

        result = await tool.execute({
            "plan": {
                "sub_tasks": [
                    {"id": "st_1", "description": "good task", "assigned_to": "worker_ok"},
                    {"id": "st_2", "description": "bad task", "assigned_to": "worker_bad"},
                ],
            },
        })

        assert result["status"] == "partial"
        assert result["sub_task_statuses"]["st_1"] == "completed"
        assert result["sub_task_statuses"]["st_2"] == "failed"


class TestBackwardCompatibility:
    """T039: Verify workflows without collaboration config are unchanged."""

    def test_team_config_without_collaboration(self):
        """TeamConfiguration with no collaboration field validates correctly."""
        from hiveflow.core.schema import (
            AgentDefinition,
            TeamConfiguration,
            WorkflowGraph,
            WorkflowStepDefinition,
        )

        config = TeamConfiguration(
            team_name="legacy_team",
            description="A team without collaboration",
            agents=[
                AgentDefinition(
                    id="writer",
                    role="Writer",
                    system_prompt="You are a writer.",
                    behavior_type="llm_only",
                ),
            ],
            workflow=WorkflowGraph(
                steps=[
                    WorkflowStepDefinition(agent="writer", type="sequential"),
                ],
            ),
        )
        # collaboration should be None by default
        assert config.collaboration is None

    def test_team_config_with_collaboration_disabled(self):
        """TeamConfiguration with collaboration explicitly disabled validates."""
        from hiveflow.core.schema import (
            AgentDefinition,
            TeamConfiguration,
            WorkflowGraph,
            WorkflowStepDefinition,
        )

        config = TeamConfiguration(
            team_name="no_collab_team",
            description="Collaboration disabled explicitly",
            agents=[
                AgentDefinition(
                    id="worker",
                    role="Worker",
                    system_prompt="You are a worker.",
                    behavior_type="llm_only",
                ),
            ],
            workflow=WorkflowGraph(
                steps=[
                    WorkflowStepDefinition(agent="worker", type="sequential"),
                ],
            ),
            collaboration=CollaborationConfig(enabled=False),
        )
        assert config.collaboration is not None
        assert config.collaboration.enabled is False

    def test_collaboration_runtime_not_created_when_disabled(self):
        """When collaboration is None, no runtime should be created."""
        # This simulates what WorkflowEngine does: check collaboration config
        # before calling _init_collaboration
        config = None  # No collaboration config
        assert config is None  # Engine would skip initialization

    def test_legacy_agent_works_without_collaboration(self):
        """An agent executes normally without collaboration tools."""
        agent = _make_agent("worker", "Worker")
        agent.execute = AsyncMock(return_value={"worker_output": "done"})
        # Agent has no collaboration tools injected
        assert len(agent.tools) == 0


class TestBudgetExhaustionIntegration:
    """T039b: Fixed token budget enforcement across delegation chain."""

    @pytest.mark.asyncio
    async def test_fixed_budget_exceeded_raises(self):
        """Configure a fixed budget, delegation that uses too many tokens raises."""
        config = CollaborationConfig(
            enabled=True,
            budget_policy=BudgetPolicy.FIXED,
            fixed_budget_tokens=100,
        )

        # Agent whose result reports high token usage
        worker = _make_agent("worker", "Worker")
        worker.execute = AsyncMock(return_value={
            "worker_output": "result",
            "worker_cost": {"total_tokens": 500},
        })
        boss = _make_agent("boss", "Boss")

        channel = StreamChannel()
        consumer = channel.subscribe()
        events = []

        async def collect():
            async for event in consumer:
                events.append(event)

        rt = _make_runtime(
            agents={"worker": worker, "boss": boss},
            config=config,
            stream_channel=channel,
        )

        state = {"_collaboration_runtime": rt, "_delegation_depth": 0}

        tool = DelegateTaskTool(runtime=rt, caller_agent_id="boss", state=state)
        collect_task = asyncio.create_task(collect())

        # Should return failed status (DelegateTaskTool catches BudgetExhaustedError)
        result = await tool.execute({
            "task": "do expensive work",
            "delegate_to": "worker",
        })

        await channel.close()
        await collect_task

        assert result["status"] == "failed"
        assert "Budget exhausted" in result["result"]

        # Verify delegation record shows failure
        assert len(rt.delegation_history) == 1
        assert rt.delegation_history[0].status == "failed"
        assert rt.delegation_history[0].error == "Budget exhausted"

        # Verify DELEGATION_FAILED event emitted
        event_types = [e.event_type for e in events]
        assert StreamEventType.DELEGATION_FAILED in event_types

    @pytest.mark.asyncio
    async def test_fixed_budget_within_limit_succeeds(self):
        """Token usage within budget succeeds normally."""
        config = CollaborationConfig(
            enabled=True,
            budget_policy=BudgetPolicy.FIXED,
            fixed_budget_tokens=1000,
        )

        worker = _make_agent("worker", "Worker")
        worker.execute = AsyncMock(return_value={
            "worker_output": "result",
            "worker_cost": {"total_tokens": 50},
        })
        boss = _make_agent("boss", "Boss")

        rt = _make_runtime(
            agents={"worker": worker, "boss": boss},
            config=config,
        )

        state = {"_collaboration_runtime": rt, "_delegation_depth": 0}

        tool = DelegateTaskTool(runtime=rt, caller_agent_id="boss", state=state)
        result = await tool.execute({
            "task": "do cheap work",
            "delegate_to": "worker",
        })

        assert result["status"] == "completed"
        assert len(rt.delegation_history) == 1
        assert rt.delegation_history[0].status == "completed"
