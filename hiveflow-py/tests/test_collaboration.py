"""Unit tests for CollaborationRuntime.

Tests agent pool CRUD, auto-selection, depth checking, spawn limits,
budget enforcement, tool scoping, delegation record tracking, and event emission.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from hiveflow.core.agent import Agent, AgentBehaviorType
from hiveflow.core.collaboration import (
    BudgetExhaustedError,
    CollaborationRuntime,
    DelegationRecord,
    SubTask,
    TaskPlan,
)
from hiveflow.core.schema import BudgetPolicy, CollaborationConfig
from hiveflow.core.streaming import StreamChannel, StreamEventType
from hiveflow.plugins.llm import LLMConfig


def _make_agent(agent_id: str, role: str = "Test", behavior: str = "llm_only") -> Agent:
    """Create a minimal test agent."""
    behavior_map = {
        "llm_only": AgentBehaviorType.LLM_ONLY,
        "tool_user": AgentBehaviorType.TOOL_USER,
        "orchestrator": AgentBehaviorType.ORCHESTRATOR,
    }
    return Agent(
        agent_id=agent_id,
        role=role,
        system_prompt=f"You are a {role.lower()}.",
        behavior_type=behavior_map.get(behavior, AgentBehaviorType.LLM_ONLY),
    )


def _make_runtime(
    config: CollaborationConfig | None = None,
    agents: dict[str, Agent] | None = None,
    stream_channel: StreamChannel | None = None,
) -> CollaborationRuntime:
    """Create a test runtime with mocked dependencies."""
    if config is None:
        config = CollaborationConfig(enabled=True)
    if agents is None:
        agents = {}
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
        stream_channel=stream_channel,
    )


# --- Agent Pool CRUD ---


class TestAgentPool:
    def test_register_and_get(self):
        rt = _make_runtime()
        agent = _make_agent("a1", "Tester")
        rt.register_agent(agent)
        assert rt.get_agent("a1") is agent

    def test_get_missing_returns_none(self):
        rt = _make_runtime()
        assert rt.get_agent("nonexistent") is None

    def test_list_agents_sorted(self):
        a = _make_agent("zebra")
        b = _make_agent("alpha")
        rt = _make_runtime(agents={"zebra": a, "alpha": b})
        assert rt.list_agents() == ["alpha", "zebra"]

    def test_duplicate_registration_raises(self):
        rt = _make_runtime()
        agent = _make_agent("a1")
        rt.register_agent(agent)
        with pytest.raises(ValueError, match="already registered"):
            rt.register_agent(agent)

    def test_initial_agents_populated(self):
        a = _make_agent("a1")
        rt = _make_runtime(agents={"a1": a})
        assert rt.get_agent("a1") is a


# --- Auto-Selection ---


class TestAutoSelection:
    def test_selects_best_match(self):
        researcher = _make_agent("r1", "Deep researcher and analyst")
        writer = _make_agent("w1", "Content writer")
        rt = _make_runtime(agents={"r1": researcher, "w1": writer})
        # Use exact words from the role to ensure matching
        assert rt.select_best_agent("deep researcher and analyst needed") == "r1"

    def test_no_match_below_threshold(self):
        agent = _make_agent("a1", "Test agent")
        rt = _make_runtime(agents={"a1": agent})
        assert rt.select_best_agent("x") is None

    def test_empty_pool_returns_none(self):
        rt = _make_runtime()
        assert rt.select_best_agent("anything") is None


# --- Delegation ---


class TestDelegation:
    @pytest.mark.asyncio
    async def test_self_delegation_raises(self):
        agent = _make_agent("a1")
        rt = _make_runtime(agents={"a1": agent})
        with pytest.raises(ValueError, match="Self-delegation not allowed"):
            await rt.delegate("task", "a1", "a1", {})

    @pytest.mark.asyncio
    async def test_depth_limit_raises(self):
        config = CollaborationConfig(enabled=True, max_delegation_depth=2)
        a = _make_agent("a1")
        b = _make_agent("a2")
        rt = _make_runtime(config=config, agents={"a1": a, "a2": b})
        with pytest.raises(ValueError, match="Delegation depth 3 exceeds maximum 2"):
            await rt.delegate("task", "a2", "a1", {}, depth=3)

    @pytest.mark.asyncio
    async def test_unknown_agent_raises(self):
        rt = _make_runtime()
        with pytest.raises(ValueError, match="not found"):
            await rt.delegate("task", "missing", "a1", {})

    @pytest.mark.asyncio
    async def test_successful_delegation(self):
        agent = _make_agent("delegate")
        agent.execute = AsyncMock(return_value={"delegate_output": "result"})
        rt = _make_runtime(agents={"delegate": agent, "boss": _make_agent("boss")})

        result = await rt.delegate("do the thing", "delegate", "boss", {})
        assert result["delegate_output"] == "result"
        assert len(rt.delegation_history) == 1
        assert rt.delegation_history[0].status == "completed"

    @pytest.mark.asyncio
    async def test_delegation_timeout(self):
        config = CollaborationConfig(enabled=True, delegation_timeout_seconds=1)

        async def slow_execute(state):
            await asyncio.sleep(10)
            return state

        agent = _make_agent("slow")
        agent.execute = slow_execute
        rt = _make_runtime(
            config=config,
            agents={"slow": agent, "boss": _make_agent("boss")},
        )

        with pytest.raises(asyncio.TimeoutError):
            await rt.delegate("task", "slow", "boss", {})

        assert rt.delegation_history[0].status == "timeout"

    @pytest.mark.asyncio
    async def test_delegation_records_failure(self):
        agent = _make_agent("bad")
        agent.execute = AsyncMock(side_effect=RuntimeError("boom"))
        rt = _make_runtime(agents={"bad": agent, "boss": _make_agent("boss")})

        with pytest.raises(RuntimeError, match="boom"):
            await rt.delegate("task", "bad", "boss", {})

        assert rt.delegation_history[0].status == "failed"
        assert rt.delegation_history[0].error == "boom"

    @pytest.mark.asyncio
    async def test_delegation_emits_events(self):
        channel = StreamChannel()
        consumer = channel.subscribe()
        events = []

        async def collect():
            async for event in consumer:
                events.append(event)

        agent = _make_agent("delegate")
        agent.execute = AsyncMock(return_value={"delegate_output": "ok"})
        rt = _make_runtime(
            agents={"delegate": agent, "boss": _make_agent("boss")},
            stream_channel=channel,
        )

        task = asyncio.create_task(collect())
        await rt.delegate("task", "delegate", "boss", {})
        await channel.close()
        await task

        event_types = [e.event_type for e in events]
        assert StreamEventType.DELEGATION_STARTED in event_types
        assert StreamEventType.DELEGATION_COMPLETED in event_types


# --- Budget ---


class TestBudget:
    def test_inherit_parent_propagates(self):
        config = CollaborationConfig(enabled=True, budget_policy="inherit_parent")
        rt = _make_runtime(config=config)
        assert rt._allocate_budget(5000) == 5000
        assert rt._allocate_budget(None) is None

    def test_fixed_budget(self):
        config = CollaborationConfig(
            enabled=True, budget_policy="fixed", fixed_budget_tokens=1000
        )
        rt = _make_runtime(config=config)
        assert rt._allocate_budget(5000) == 1000
        assert rt._allocate_budget(None) == 1000

    def test_unlimited_budget(self):
        config = CollaborationConfig(enabled=True, budget_policy="unlimited")
        rt = _make_runtime(config=config)
        assert rt._allocate_budget(5000) is None


# --- Spawning ---


class TestSpawning:
    def test_spawn_from_archetype(self):
        config = CollaborationConfig(enabled=True, max_spawned_agents=5)
        rt = _make_runtime(config=config)
        rt._archetype_library.get.return_value = {
            "role": "Helper",
            "system_prompt": "Help out",
            "behavior_type": "llm_only",
            "tools": [],
        }

        agent = rt.spawn_from_archetype("helper", spawned_by="boss")
        assert agent.role == "Helper"
        assert agent.agent_id in rt.list_agents()
        assert rt.spawned_count == 1
        assert agent.agent_id in rt.spawned_agent_ids

    def test_spawn_limit_enforced(self):
        config = CollaborationConfig(enabled=True, max_spawned_agents=1)
        rt = _make_runtime(config=config)
        rt._archetype_library.get.return_value = {
            "role": "Helper",
            "system_prompt": "Help",
            "behavior_type": "llm_only",
            "tools": [],
        }
        rt.spawn_from_archetype("helper", spawned_by="boss")
        with pytest.raises(ValueError, match="Spawn limit reached"):
            rt.spawn_from_archetype("helper", spawned_by="boss")

    def test_archetype_not_found_raises(self):
        rt = _make_runtime()
        with pytest.raises(ValueError, match="not found"):
            rt.spawn_from_archetype("nonexistent", spawned_by="boss")

    def test_recursive_orchestrator_blocked(self):
        rt = _make_runtime()
        rt._archetype_library.get.return_value = {
            "role": "Orchestrator",
            "system_prompt": "Orchestrate",
            "behavior_type": "orchestrator",
            "tools": [],
        }
        with pytest.raises(ValueError, match="orchestrator agents is not allowed"):
            rt.spawn_from_archetype("orchestrator", spawned_by="boss")

    def test_recursive_orchestrator_allowed(self):
        config = CollaborationConfig(
            enabled=True, allow_recursive_orchestrators=True
        )
        rt = _make_runtime(config=config)
        rt._archetype_library.get.return_value = {
            "role": "Orchestrator",
            "system_prompt": "Orchestrate",
            "behavior_type": "orchestrator",
            "tools": [],
        }
        agent = rt.spawn_from_archetype("orchestrator", spawned_by="boss")
        assert agent.behavior_type == AgentBehaviorType.ORCHESTRATOR

    def test_spawn_from_definition(self):
        rt = _make_runtime()
        agent = rt.spawn_from_definition(
            {
                "role": "Custom",
                "system_prompt": "Custom agent",
                "behavior_type": "tool_user",
                "tools": [],
            },
            spawned_by="boss",
        )
        assert agent.role == "Custom"
        assert agent.behavior_type == AgentBehaviorType.TOOL_USER

    def test_tool_scoping(self):
        """Child tools are scoped to parent tools union archetype tools."""
        parent_tool = MagicMock()
        parent_tool.plugin_id = "allowed_tool"
        blocked_tool = MagicMock()
        blocked_tool.plugin_id = "blocked_tool"

        rt = _make_runtime()
        rt._tool_registry.get.side_effect = lambda tid: (
            parent_tool if tid == "allowed_tool" else blocked_tool
        )
        rt._archetype_library.get.return_value = {
            "role": "Scoped",
            "system_prompt": "Test",
            "behavior_type": "llm_only",
            "tools": ["allowed_tool", "blocked_tool"],
        }

        agent = rt.spawn_from_archetype(
            "scoped",
            spawned_by="boss",
            parent_tools=[parent_tool],
        )
        tool_ids = [t.plugin_id for t in agent.tools]
        assert "allowed_tool" in tool_ids
        assert "blocked_tool" not in tool_ids


# --- DelegationRecord ---


class TestDelegationRecord:
    def test_defaults(self):
        r = DelegationRecord(
            delegation_id="d1",
            task="test",
            delegated_by="a",
            delegate_to="b",
            depth=1,
        )
        assert r.status == "started"
        assert r.completed_at is None
        assert r.error is None


# --- Task Planning (T035) ---


class TestSubTask:
    def test_defaults(self):
        st = SubTask(id="st_1", description="do something")
        assert st.assigned_to == "auto"
        assert st.depends_on == []
        assert st.expected_output == "text"
        assert st.status == "pending"
        assert st.result is None


class TestTaskPlan:
    def test_valid_linear_dag(self):
        """A -> B -> C is a valid DAG."""
        plan = TaskPlan(
            plan_id="p1",
            created_by="boss",
            sub_tasks=[
                SubTask(id="a", description="first"),
                SubTask(id="b", description="second", depends_on=["a"]),
                SubTask(id="c", description="third", depends_on=["b"]),
            ],
        )
        plan.validate_dag()  # Should not raise

    def test_valid_parallel_dag(self):
        """A and B independent, C depends on both."""
        plan = TaskPlan(
            plan_id="p1",
            created_by="boss",
            sub_tasks=[
                SubTask(id="a", description="first"),
                SubTask(id="b", description="second"),
                SubTask(id="c", description="third", depends_on=["a", "b"]),
            ],
        )
        plan.validate_dag()

    def test_cycle_detected(self):
        """A -> B -> A is a cycle."""
        plan = TaskPlan(
            plan_id="p1",
            created_by="boss",
            sub_tasks=[
                SubTask(id="a", description="first", depends_on=["b"]),
                SubTask(id="b", description="second", depends_on=["a"]),
            ],
        )
        with pytest.raises(ValueError, match="Cycle detected"):
            plan.validate_dag()

    def test_unknown_dependency_detected(self):
        plan = TaskPlan(
            plan_id="p1",
            created_by="boss",
            sub_tasks=[
                SubTask(id="a", description="first", depends_on=["nonexistent"]),
            ],
        )
        with pytest.raises(ValueError, match="unknown ID 'nonexistent'"):
            plan.validate_dag()

    def test_topological_groups_linear(self):
        """Linear chain produces one task per group."""
        plan = TaskPlan(
            plan_id="p1",
            created_by="boss",
            sub_tasks=[
                SubTask(id="a", description="first"),
                SubTask(id="b", description="second", depends_on=["a"]),
                SubTask(id="c", description="third", depends_on=["b"]),
            ],
        )
        groups = plan.topological_groups()
        assert len(groups) == 3
        assert [g[0].id for g in groups] == ["a", "b", "c"]

    def test_topological_groups_concurrent(self):
        """Independent tasks in same group, dependent in next."""
        plan = TaskPlan(
            plan_id="p1",
            created_by="boss",
            sub_tasks=[
                SubTask(id="a", description="first"),
                SubTask(id="b", description="second"),
                SubTask(id="c", description="third", depends_on=["a", "b"]),
            ],
        )
        groups = plan.topological_groups()
        assert len(groups) == 2
        group_1_ids = sorted([st.id for st in groups[0]])
        assert group_1_ids == ["a", "b"]
        assert groups[1][0].id == "c"

    def test_self_referencing_cycle(self):
        """A depends on itself."""
        plan = TaskPlan(
            plan_id="p1",
            created_by="boss",
            sub_tasks=[
                SubTask(id="a", description="first", depends_on=["a"]),
            ],
        )
        with pytest.raises(ValueError, match="Cycle detected"):
            plan.validate_dag()

    def test_empty_plan_valid(self):
        plan = TaskPlan(plan_id="p1", created_by="boss", sub_tasks=[])
        plan.validate_dag()
        assert plan.topological_groups() == []


class TestPlanExecution:
    @pytest.mark.asyncio
    async def test_execute_plan_sequential(self):
        """Execute a linear plan: A -> B."""
        agent_a = _make_agent("worker_a", "Worker A")
        agent_a.execute = AsyncMock(return_value={"worker_a_output": "result_a"})
        agent_b = _make_agent("worker_b", "Worker B")
        agent_b.execute = AsyncMock(return_value={"worker_b_output": "result_b"})
        boss = _make_agent("boss", "Boss")

        rt = _make_runtime(agents={
            "worker_a": agent_a, "worker_b": agent_b, "boss": boss,
        })

        plan = TaskPlan(
            plan_id="p1",
            created_by="boss",
            sub_tasks=[
                SubTask(id="st_1", description="task A", assigned_to="worker_a"),
                SubTask(
                    id="st_2", description="task B",
                    assigned_to="worker_b", depends_on=["st_1"],
                ),
            ],
        )

        state = {"_collaboration_runtime": rt, "_delegation_depth": 0}
        results = await rt.execute_plan(plan, state, "boss")

        assert results["st_1"] == "result_a"
        assert results["st_2"] == "result_b"
        assert plan.sub_tasks[0].status == "completed"
        assert plan.sub_tasks[1].status == "completed"
        assert len(rt.delegation_history) == 2

    @pytest.mark.asyncio
    async def test_execute_plan_concurrent(self):
        """Independent tasks execute in same group."""
        agent_a = _make_agent("a", "Worker A")
        agent_a.execute = AsyncMock(return_value={"a_output": "done_a"})
        agent_b = _make_agent("b", "Worker B")
        agent_b.execute = AsyncMock(return_value={"b_output": "done_b"})
        boss = _make_agent("boss")

        rt = _make_runtime(agents={"a": agent_a, "b": agent_b, "boss": boss})

        plan = TaskPlan(
            plan_id="p1",
            created_by="boss",
            sub_tasks=[
                SubTask(id="st_1", description="task A", assigned_to="a"),
                SubTask(id="st_2", description="task B", assigned_to="b"),
            ],
        )

        state = {"_collaboration_runtime": rt, "_delegation_depth": 0}
        results = await rt.execute_plan(plan, state, "boss")

        assert results["st_1"] == "done_a"
        assert results["st_2"] == "done_b"

    @pytest.mark.asyncio
    async def test_execute_plan_failure_tracked(self):
        """Failed sub-task gets status='failed' and error in results."""
        agent = _make_agent("worker", "Worker")
        agent.execute = AsyncMock(side_effect=RuntimeError("boom"))
        boss = _make_agent("boss")

        rt = _make_runtime(agents={"worker": agent, "boss": boss})

        plan = TaskPlan(
            plan_id="p1",
            created_by="boss",
            sub_tasks=[
                SubTask(id="st_1", description="crash task", assigned_to="worker"),
            ],
        )

        state = {"_collaboration_runtime": rt, "_delegation_depth": 0}
        results = await rt.execute_plan(plan, state, "boss")

        assert plan.sub_tasks[0].status == "failed"
        assert "FAILED" in results["st_1"]

    @pytest.mark.asyncio
    async def test_execute_plan_emits_plan_created(self):
        """Plan execution emits PLAN_CREATED event."""
        channel = StreamChannel()
        consumer = channel.subscribe()
        events = []

        async def collect():
            async for event in consumer:
                events.append(event)

        agent = _make_agent("worker")
        agent.execute = AsyncMock(return_value={"worker_output": "ok"})
        boss = _make_agent("boss")

        rt = _make_runtime(
            agents={"worker": agent, "boss": boss},
            stream_channel=channel,
        )

        plan = TaskPlan(
            plan_id="test_plan",
            created_by="boss",
            sub_tasks=[
                SubTask(id="st_1", description="one task", assigned_to="worker"),
            ],
        )

        task = asyncio.create_task(collect())
        state = {"_collaboration_runtime": rt, "_delegation_depth": 0}
        await rt.execute_plan(plan, state, "boss")
        await channel.close()
        await task

        event_types = [e.event_type for e in events]
        assert StreamEventType.PLAN_CREATED in event_types

        plan_event = next(e for e in events if e.event_type == StreamEventType.PLAN_CREATED)
        assert plan_event.data["plan_id"] == "test_plan"
        assert plan_event.data["sub_task_count"] == 1

    @pytest.mark.asyncio
    async def test_execute_plan_invalid_dag_raises(self):
        """Cyclic plan raises ValueError."""
        boss = _make_agent("boss")
        rt = _make_runtime(agents={"boss": boss})

        plan = TaskPlan(
            plan_id="p1",
            created_by="boss",
            sub_tasks=[
                SubTask(id="a", description="first", depends_on=["b"]),
                SubTask(id="b", description="second", depends_on=["a"]),
            ],
        )

        state = {"_collaboration_runtime": rt, "_delegation_depth": 0}
        with pytest.raises(ValueError, match="Cycle detected"):
            await rt.execute_plan(plan, state, "boss")
