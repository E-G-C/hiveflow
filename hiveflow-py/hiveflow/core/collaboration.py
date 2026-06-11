"""Dynamic Agent Collaboration Runtime.

Provides the CollaborationRuntime class which manages dynamic delegation,
agent spawning, inter-agent messaging, and budget enforcement during
workflow execution.
"""

import asyncio
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog

from hiveflow.core.agent import Agent, AgentBehaviorType
from hiveflow.core.schema import BudgetPolicy, CollaborationConfig
from hiveflow.core.streaming import StreamChannel, StreamEvent, StreamEventType
from hiveflow.plugins.llm import LLMConfig, LLMProvider
from hiveflow.plugins.tools import ToolPlugin, ToolRegistry

logger = structlog.get_logger()


class BudgetExhaustedError(Exception):
    """Raised when a delegation chain exceeds its token budget."""


@dataclass
class DelegationRecord:
    """Audit record for a single delegation event."""

    delegation_id: str
    task: str
    delegated_by: str
    delegate_to: str
    depth: int
    status: str = "started"
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    duration_ms: int | None = None
    tokens_used: int | None = None
    result_summary: str | None = None
    error: str | None = None


@dataclass
class SubTask:
    """A single sub-task within a TaskPlan."""

    id: str
    description: str
    assigned_to: str = "auto"
    depends_on: list[str] = field(default_factory=list)
    expected_output: str = "text"
    status: str = "pending"
    result: Any = None


@dataclass
class TaskPlan:
    """A structured plan of dependency-ordered sub-tasks.

    The sub_tasks list must form a directed acyclic graph (DAG)
    via the depends_on fields. Cycles are rejected at validation time.
    """

    plan_id: str
    created_by: str
    sub_tasks: list[SubTask] = field(default_factory=list)

    def validate_dag(self) -> None:
        """Validate that sub-tasks form a DAG (no cycles).

        Uses Kahn's algorithm for topological sort. If not all nodes
        are visited, a cycle exists.

        Raises:
            ValueError: If depends_on references unknown sub-task IDs
            ValueError: If the dependency graph contains cycles
        """
        ids = {st.id for st in self.sub_tasks}

        # Check for unknown references
        for st in self.sub_tasks:
            for dep in st.depends_on:
                if dep not in ids:
                    raise ValueError(f"SubTask '{st.id}' depends on unknown ID '{dep}'")

        # Kahn's algorithm
        in_degree: dict[str, int] = {st.id: 0 for st in self.sub_tasks}
        adjacency: dict[str, list[str]] = {st.id: [] for st in self.sub_tasks}

        for st in self.sub_tasks:
            for dep in st.depends_on:
                adjacency[dep].append(st.id)
                in_degree[st.id] += 1

        queue = deque(sid for sid, deg in in_degree.items() if deg == 0)
        visited = 0

        while queue:
            node = queue.popleft()
            visited += 1
            for neighbor in adjacency[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if visited != len(self.sub_tasks):
            raise ValueError("Cycle detected in sub-task dependencies")

    def topological_groups(self) -> list[list[SubTask]]:
        """Return sub-tasks grouped by topological level.

        Tasks in the same group have all dependencies satisfied
        and can be executed concurrently.

        Returns:
            List of groups, each group is a list of SubTask instances
            that can run in parallel.
        """
        task_map = {st.id: st for st in self.sub_tasks}
        in_degree: dict[str, int] = {st.id: 0 for st in self.sub_tasks}
        adjacency: dict[str, list[str]] = {st.id: [] for st in self.sub_tasks}

        for st in self.sub_tasks:
            for dep in st.depends_on:
                adjacency[dep].append(st.id)
                in_degree[st.id] += 1

        groups: list[list[SubTask]] = []
        ready = [sid for sid, deg in in_degree.items() if deg == 0]

        while ready:
            group = [task_map[sid] for sid in ready]
            groups.append(group)
            next_ready: list[str] = []
            for sid in ready:
                for neighbor in adjacency[sid]:
                    in_degree[neighbor] -= 1
                    if in_degree[neighbor] == 0:
                        next_ready.append(neighbor)
            ready = next_ready

        return groups


class CollaborationRuntime:
    """Runtime manager for dynamic agent collaboration.

    Created per workflow execution when collaboration is enabled.
    Manages agent pool, delegation, spawning, and budget enforcement.
    """

    def __init__(
        self,
        config: CollaborationConfig,
        agents: dict[str, Agent],
        archetype_library: Any,
        tool_registry: ToolRegistry,
        llm_provider: LLMProvider,
        llm_config: LLMConfig,
        stream_channel: StreamChannel | None = None,
    ) -> None:
        """Initialize collaboration runtime.

        Args:
            config: Merged collaboration configuration
            agents: Initial agents from team configuration
            archetype_library: Source of agent archetypes for spawning
            tool_registry: Global tool registry for resolving tool references
            llm_provider: LLM provider for spawned agents
            llm_config: Base LLM config for spawned agents
            stream_channel: Optional stream channel for emitting events
        """
        self.config = config
        self._agent_pool: dict[str, Agent] = dict(agents)
        self._archetype_library = archetype_library
        self._tool_registry = tool_registry
        self._llm_provider = llm_provider
        self._llm_config = llm_config
        self._stream_channel = stream_channel
        self._spawned_count: int = 0
        self._spawned_agent_ids: set[str] = set()
        self._delegation_history: list[DelegationRecord] = []
        self._budget_used: dict[str, int] = {}  # delegation_id -> tokens used

    # -- Agent Pool Management (T006) --

    def get_agent(self, agent_id: str) -> Agent | None:
        """Look up an agent by ID.

        Args:
            agent_id: The agent identifier

        Returns:
            Agent instance or None if not found
        """
        return self._agent_pool.get(agent_id)

    def list_agents(self) -> list[str]:
        """List all agent IDs in the pool.

        Returns:
            Sorted list of agent IDs
        """
        return sorted(self._agent_pool.keys())

    def register_agent(self, agent: Agent) -> None:
        """Register an agent in the pool.

        Args:
            agent: Agent to register

        Raises:
            ValueError: If agent ID already exists
        """
        if agent.agent_id in self._agent_pool:
            raise ValueError(f"Agent '{agent.agent_id}' already registered")
        self._agent_pool[agent.agent_id] = agent

    # -- Auto-Selection (T007) --

    def select_best_agent(self, task_description: str) -> str | None:
        """Select the best agent for a task using keyword matching.

        Matches task description words against agent roles and system prompts.
        Returns None if no agent scores above threshold.

        Args:
            task_description: Description of the task

        Returns:
            Agent ID of the best match, or None
        """
        task_words = set(task_description.lower().split())
        best_id: str | None = None
        best_score = 0

        for agent_id, agent in self._agent_pool.items():
            role_words = set(agent.role.lower().split())
            prompt_words = set(agent.system_prompt.lower().split()[:100])
            overlap = len(task_words & (role_words | prompt_words))
            if overlap > best_score:
                best_score = overlap
                best_id = agent_id

        # Require at least 2 matching words as threshold
        if best_score < 2:
            return None
        return best_id

    # -- Delegation (T008, T009) --

    @property
    def delegation_history(self) -> list[DelegationRecord]:
        """All delegation records for this execution."""
        return list(self._delegation_history)

    @property
    def spawned_count(self) -> int:
        """Number of agents spawned in this execution."""
        return self._spawned_count

    @property
    def spawned_agent_ids(self) -> set[str]:
        """IDs of all dynamically spawned agents."""
        return set(self._spawned_agent_ids)

    async def delegate(
        self,
        task: str,
        delegate_to: str,
        delegated_by: str,
        state: dict[str, Any],
        depth: int = 1,
        parent_budget_tokens: int | None = None,
    ) -> dict[str, Any]:
        """Execute a delegation to another agent.

        Builds filtered sub-state, enforces depth/timeout limits,
        detects self-delegation, emits events, and records audit trail.

        Args:
            task: Description of the sub-task
            delegate_to: Agent ID to delegate to
            delegated_by: Agent ID doing the delegation
            state: Current workflow state
            depth: Current delegation depth
            parent_budget_tokens: Token budget inherited from parent

        Returns:
            Updated state dict from the delegated execution

        Raises:
            ValueError: If delegate_to is same as delegated_by (self-delegation)
            ValueError: If depth exceeds max_delegation_depth
            ValueError: If delegate_to agent not found
            asyncio.TimeoutError: If delegation exceeds timeout
            BudgetExhaustedError: If token budget is exceeded
        """
        # FR-012: Self-delegation guard
        if delegate_to == delegated_by:
            raise ValueError(
                f"Self-delegation not allowed: agent '{delegated_by}' cannot delegate to itself"
            )

        # FR-009: Depth limit
        if depth > self.config.max_delegation_depth:
            raise ValueError(
                f"Delegation depth {depth} exceeds maximum {self.config.max_delegation_depth}"
            )

        # Resolve agent
        agent = self.get_agent(delegate_to)
        if agent is None:
            raise ValueError(f"Agent '{delegate_to}' not found in pool")

        # Budget allocation
        budget_tokens = self._allocate_budget(parent_budget_tokens)

        # Create delegation record
        delegation_id = str(uuid.uuid4())
        record = DelegationRecord(
            delegation_id=delegation_id,
            task=task,
            delegated_by=delegated_by,
            delegate_to=delegate_to,
            depth=depth,
        )
        self._delegation_history.append(record)

        logger.info(
            "delegation.started",
            delegation_id=delegation_id,
            task=task[:100],
            delegate_to=delegate_to,
            delegated_by=delegated_by,
            depth=depth,
        )

        # FR-018: Emit DELEGATION_STARTED
        await self._emit(
            StreamEventType.DELEGATION_STARTED,
            {
                "delegation_id": delegation_id,
                "task": task,
                "delegate_to": delegate_to,
                "delegated_by": delegated_by,
                "depth": depth,
            },
        )

        # FR-008: Build filtered sub-state
        sub_state = self._build_sub_state(state, task, depth)

        start_time = time.monotonic()
        try:
            # FR-011: Timeout enforcement
            result_state = await asyncio.wait_for(
                agent.execute(sub_state),
                timeout=self.config.delegation_timeout_seconds,
            )

            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            tokens_used = self._extract_tokens_used(result_state, delegate_to)

            # Budget enforcement
            if (
                budget_tokens is not None
                and tokens_used is not None
                and tokens_used > budget_tokens
            ):
                raise BudgetExhaustedError(
                    f"Delegation used {tokens_used} tokens, exceeding budget of {budget_tokens}"
                )

            # Update record
            record.status = "completed"
            record.completed_at = datetime.now(UTC)
            record.duration_ms = elapsed_ms
            record.tokens_used = tokens_used
            record.result_summary = self._summarize_result(result_state, delegate_to)

            logger.info(
                "delegation.completed",
                delegation_id=delegation_id,
                delegate_to=delegate_to,
                duration_ms=elapsed_ms,
                tokens_used=tokens_used,
            )

            # FR-018: Emit DELEGATION_COMPLETED
            await self._emit(
                StreamEventType.DELEGATION_COMPLETED,
                {
                    "delegation_id": delegation_id,
                    "task": task,
                    "delegate_to": delegate_to,
                    "delegated_by": delegated_by,
                    "result_summary": record.result_summary,
                    "duration_ms": elapsed_ms,
                    "tokens_used": tokens_used,
                },
            )

            return result_state

        except TimeoutError:
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            record.status = "timeout"
            record.completed_at = datetime.now(UTC)
            record.duration_ms = elapsed_ms
            record.error = f"Timed out after {self.config.delegation_timeout_seconds}s"

            logger.warning(
                "delegation.timeout",
                delegation_id=delegation_id,
                delegate_to=delegate_to,
                timeout_seconds=self.config.delegation_timeout_seconds,
                duration_ms=elapsed_ms,
            )

            await self._emit(
                StreamEventType.DELEGATION_FAILED,
                {
                    "delegation_id": delegation_id,
                    "task": task,
                    "delegate_to": delegate_to,
                    "error": record.error,
                    "duration_ms": elapsed_ms,
                },
            )
            raise

        except BudgetExhaustedError:
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            record.status = "failed"
            record.completed_at = datetime.now(UTC)
            record.duration_ms = elapsed_ms
            record.error = "Budget exhausted"

            logger.warning(
                "delegation.budget_exhausted",
                delegation_id=delegation_id,
                delegate_to=delegate_to,
                duration_ms=elapsed_ms,
            )

            await self._emit(
                StreamEventType.DELEGATION_FAILED,
                {
                    "delegation_id": delegation_id,
                    "task": task,
                    "delegate_to": delegate_to,
                    "error": record.error,
                    "duration_ms": elapsed_ms,
                },
            )
            raise

        except Exception as e:
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            record.status = "failed"
            record.completed_at = datetime.now(UTC)
            record.duration_ms = elapsed_ms
            record.error = str(e)

            logger.error(
                "delegation.failed",
                delegation_id=delegation_id,
                delegate_to=delegate_to,
                error=str(e),
                duration_ms=elapsed_ms,
            )

            await self._emit(
                StreamEventType.DELEGATION_FAILED,
                {
                    "delegation_id": delegation_id,
                    "task": task,
                    "delegate_to": delegate_to,
                    "error": str(e),
                    "duration_ms": elapsed_ms,
                },
            )
            raise

    # -- Plan Execution (T033) --

    async def execute_plan(
        self,
        plan: TaskPlan,
        state: dict[str, Any],
        caller_agent_id: str,
        depth: int = 1,
    ) -> dict[str, Any]:
        """Execute a task plan, respecting dependency order and concurrency.

        Topologically sorts sub-tasks, runs each group concurrently via
        asyncio.gather, and delegates each sub-task via delegate().

        Assignment modes for sub-tasks:
        - Literal agent ID: delegates directly
        - "auto": uses select_best_agent() for auto-selection
        - "spawn:{archetype}": spawns an agent from archetype first

        Args:
            plan: Validated TaskPlan with sub-tasks
            state: Current workflow state
            caller_agent_id: Agent ID creating/executing the plan
            depth: Current delegation depth

        Returns:
            Dict mapping sub-task IDs to their results

        Raises:
            ValueError: If plan DAG validation fails
        """
        plan.validate_dag()

        logger.info(
            "plan.execution_started",
            plan_id=plan.plan_id,
            created_by=plan.created_by,
            sub_task_count=len(plan.sub_tasks),
        )

        # FR-021: Emit PLAN_CREATED event
        await self._emit(
            StreamEventType.PLAN_CREATED,
            {
                "plan_id": plan.plan_id,
                "created_by": plan.created_by,
                "sub_task_count": len(plan.sub_tasks),
            },
        )

        groups = plan.topological_groups()
        results: dict[str, Any] = {}

        for group in groups:
            # Run all tasks in this group concurrently
            coros = []
            for sub_task in group:
                coros.append(
                    self._execute_sub_task(sub_task, plan, state, caller_agent_id, depth, results)
                )
            await asyncio.gather(*coros)

        return results

    async def _execute_sub_task(
        self,
        sub_task: SubTask,
        _plan: TaskPlan,
        state: dict[str, Any],
        caller_agent_id: str,
        depth: int,
        results: dict[str, Any],
    ) -> None:
        """Execute a single sub-task within a plan.

        Resolves the assigned agent (auto-select or spawn), delegates,
        and updates the sub-task status and result.

        Args:
            sub_task: The sub-task to execute
            plan: Parent plan (for context)
            state: Workflow state
            caller_agent_id: Agent creating the plan
            depth: Current delegation depth
            results: Shared results dict to update
        """
        sub_task.status = "in_progress"
        assigned_to = sub_task.assigned_to

        try:
            # Resolve assignment
            if assigned_to == "auto":
                resolved = self.select_best_agent(sub_task.description)
                if resolved is None:
                    # Spawn a fallback general agent
                    fallback = self.spawn_from_definition(
                        definition={
                            "role": "General Assistant",
                            "system_prompt": (
                                "You are a helpful general-purpose assistant. "
                                "Complete the assigned task to the best of your ability."
                            ),
                            "behavior_type": "llm_only",
                            "tools": [],
                        },
                        spawned_by=caller_agent_id,
                    )
                    resolved = fallback.agent_id
                assigned_to = resolved
            elif assigned_to.startswith("spawn:"):
                archetype_name = assigned_to[len("spawn:") :]
                spawned = self.spawn_from_archetype(archetype_name, spawned_by=caller_agent_id)
                assigned_to = spawned.agent_id

            # Delegate execution
            result_state = await self.delegate(
                task=sub_task.description,
                delegate_to=assigned_to,
                delegated_by=caller_agent_id,
                state=state,
                depth=depth,
            )

            # Extract output
            output = result_state.get(f"{assigned_to}_output", "")
            sub_task.status = "completed"
            sub_task.result = str(output) if output else ""
            results[sub_task.id] = sub_task.result

        except Exception as e:
            sub_task.status = "failed"
            sub_task.result = str(e)
            results[sub_task.id] = f"FAILED: {e}"
            logger.warning(
                "plan.sub_task_failed",
                sub_task_id=sub_task.id,
                error=str(e),
            )

    # -- Budget Control (T010) --

    def _allocate_budget(self, parent_budget_tokens: int | None) -> int | None:
        """Determine token budget for a child delegation.

        Args:
            parent_budget_tokens: Token budget from parent, if any

        Returns:
            Token budget for the child, or None if unlimited
        """
        policy = self.config.budget_policy
        if policy == BudgetPolicy.UNLIMITED:
            return None
        if policy == BudgetPolicy.FIXED:
            return self.config.fixed_budget_tokens
        # inherit_parent
        return parent_budget_tokens

    # -- Spawning (T011) --

    def spawn_from_archetype(
        self,
        archetype_name: str,
        spawned_by: str,
        agent_id: str | None = None,
        extra_tools: list[ToolPlugin] | None = None,
        parent_tools: list[ToolPlugin] | None = None,
    ) -> Agent:
        """Spawn a new agent from an archetype.

        Args:
            archetype_name: Name of the archetype to use
            spawned_by: Agent ID of the spawner
            agent_id: Optional explicit ID, auto-generated if None
            extra_tools: Additional tools beyond the archetype defaults
            parent_tools: Parent agent's tools for scoping enforcement

        Returns:
            The newly created Agent

        Raises:
            ValueError: If spawn limit reached
            ValueError: If archetype not found
            ValueError: If recursive orchestrator not allowed
        """
        # FR-010: Spawn limit
        if self._spawned_count >= self.config.max_spawned_agents:
            raise ValueError(f"Spawn limit reached ({self.config.max_spawned_agents})")

        archetype = self._archetype_library.get(archetype_name)
        if archetype is None:
            raise ValueError(f"Archetype '{archetype_name}' not found")

        # FR-020: Recursive orchestrator restriction
        behavior = archetype.get("behavior_type", "llm_only")
        if behavior == "orchestrator" and not self.config.allow_recursive_orchestrators:
            raise ValueError(
                "Spawning orchestrator agents is not allowed (allow_recursive_orchestrators=False)"
            )

        return self._create_spawned_agent(
            archetype=archetype,
            spawned_by=spawned_by,
            agent_id=agent_id,
            extra_tools=extra_tools,
            parent_tools=parent_tools,
        )

    def spawn_from_definition(
        self,
        definition: dict[str, Any],
        spawned_by: str,
        agent_id: str | None = None,
        parent_tools: list[ToolPlugin] | None = None,
    ) -> Agent:
        """Spawn a new agent from an inline definition.

        Args:
            definition: Dict with role, system_prompt, behavior_type, tools
            spawned_by: Agent ID of the spawner
            agent_id: Optional explicit ID, auto-generated if None
            parent_tools: Parent agent's tools for scoping enforcement

        Returns:
            The newly created Agent

        Raises:
            ValueError: If spawn limit reached
            ValueError: If recursive orchestrator not allowed
        """
        if self._spawned_count >= self.config.max_spawned_agents:
            raise ValueError(f"Spawn limit reached ({self.config.max_spawned_agents})")

        behavior = definition.get("behavior_type", "llm_only")
        if behavior == "orchestrator" and not self.config.allow_recursive_orchestrators:
            raise ValueError(
                "Spawning orchestrator agents is not allowed (allow_recursive_orchestrators=False)"
            )

        return self._create_spawned_agent(
            archetype=definition,
            spawned_by=spawned_by,
            agent_id=agent_id,
            extra_tools=None,
            parent_tools=parent_tools,
        )

    # -- Private Helpers --

    def _create_spawned_agent(
        self,
        archetype: dict[str, Any],
        spawned_by: str,
        agent_id: str | None,
        extra_tools: list[ToolPlugin] | None,
        parent_tools: list[ToolPlugin] | None,
    ) -> Agent:
        """Internal: create and register a spawned agent.

        Args:
            archetype: Dict with role, system_prompt, behavior_type, tools
            spawned_by: Agent ID of the spawner
            agent_id: Explicit ID or None for auto-generation
            extra_tools: Additional tools
            parent_tools: Parent's tools for scoping

        Returns:
            Newly created and registered Agent
        """
        # FR-006: Unique ID
        if agent_id is None:
            agent_id = f"spawned_{archetype.get('role', 'agent')}_{uuid.uuid4().hex[:8]}"

        # Resolve behavior type
        behavior_str = archetype.get("behavior_type", "llm_only")
        behavior_map = {
            "llm_only": AgentBehaviorType.LLM_ONLY,
            "tool_user": AgentBehaviorType.TOOL_USER,
            "orchestrator": AgentBehaviorType.ORCHESTRATOR,
            "human_gate": AgentBehaviorType.HUMAN_GATE,
            "action_executor": AgentBehaviorType.ACTION_EXECUTOR,
        }
        behavior_type = behavior_map.get(behavior_str, AgentBehaviorType.LLM_ONLY)

        # FR-027: Tool scoping — child can only use tools from parent + archetype
        tools = self._resolve_scoped_tools(
            archetype_tool_ids=archetype.get("tools", []),
            extra_tools=extra_tools,
            parent_tools=parent_tools,
        )

        agent = Agent(
            agent_id=agent_id,
            role=archetype.get("role", "Dynamic Agent"),
            system_prompt=archetype.get("system_prompt", "You are a helpful assistant."),
            behavior_type=behavior_type,
            tools=tools,
            model=archetype.get("model", "$SMART_LLM"),
            llm_provider=self._llm_provider,
            llm_config=self._llm_config,
        )

        self._agent_pool[agent_id] = agent
        self._spawned_count += 1
        self._spawned_agent_ids.add(agent_id)

        logger.info(
            "agent.spawned",
            agent_id=agent_id,
            role=archetype.get("role", "Dynamic Agent"),
            behavior_type=behavior_str,
            spawned_by=spawned_by,
            total_spawned=self._spawned_count,
        )

        return agent

    def _resolve_scoped_tools(
        self,
        archetype_tool_ids: list[str],
        extra_tools: list[ToolPlugin] | None,
        parent_tools: list[ToolPlugin] | None,
    ) -> list[ToolPlugin]:
        """Resolve tools for a spawned agent with scoping enforcement.

        The child agent's tools are: archetype tools + extra tools,
        but only if they appear in the parent tools set or registry.

        Args:
            archetype_tool_ids: Tool IDs from the archetype definition
            extra_tools: Extra tool instances
            parent_tools: Parent agent's tool instances

        Returns:
            List of resolved ToolPlugin instances
        """
        resolved: list[ToolPlugin] = []

        # Build parent tool set for scoping
        parent_ids: set[str] | None = None
        if parent_tools is not None:
            parent_ids = {t.plugin_id for t in parent_tools}

        # Resolve archetype tool IDs
        for tool_id in archetype_tool_ids:
            tool = self._tool_registry.get(tool_id)
            if tool is not None and (parent_ids is None or tool_id in parent_ids):
                resolved.append(tool)

        # Add extra tools (with scoping)
        if extra_tools:
            for tool in extra_tools:
                if (parent_ids is None or tool.plugin_id in parent_ids) and tool not in resolved:
                    resolved.append(tool)

        return resolved

    def _build_sub_state(
        self,
        state: dict[str, Any],
        task: str,
        depth: int,
        chunk_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Build filtered sub-state for delegation.

        Passes through relevant state, sets task and depth.
        Propagates preprocessing keys when present.

        Args:
            state: Full workflow state
            task: Delegated task description
            depth: Current delegation depth
            chunk_ids: Optional list of chunk IDs to filter task_data

        Returns:
            Filtered state dict for the delegate
        """
        sub_state: dict[str, Any] = {
            "task": task,
            "_delegation_depth": depth,
            "_collaboration_runtime": state.get("_collaboration_runtime"),
        }
        # Pass through messages if they exist
        if "_messages" in state:
            sub_state["_messages"] = state["_messages"]

        # Propagate preprocessing keys (R5)
        if "task_instructions" in state:
            sub_state["task_instructions"] = state["task_instructions"]
        if "task_data_summary" in state:
            sub_state["task_data_summary"] = state["task_data_summary"]
        if "task_data_manifest" in state:
            sub_state["task_data_manifest"] = state["task_data_manifest"]
        if "task_data" in state:
            task_data = state["task_data"]
            if chunk_ids:
                task_data = [
                    c for c in task_data if isinstance(c, dict) and c.get("chunk_id") in chunk_ids
                ]
            sub_state["task_data"] = task_data

        return sub_state

    def _extract_tokens_used(self, result_state: dict[str, Any], agent_id: str) -> int | None:
        """Extract token usage from result state if available."""
        # Check for cost tracking data
        cost_key = f"{agent_id}_cost"
        cost_data = result_state.get(cost_key)
        if isinstance(cost_data, dict):
            return cost_data.get("total_tokens")
        return None

    def _summarize_result(self, result_state: dict[str, Any], agent_id: str) -> str | None:
        """Extract a brief summary from delegation result."""
        output = result_state.get(f"{agent_id}_output", "")
        if isinstance(output, str) and output:
            return output[:200]
        return None

    async def _emit(self, event_type: StreamEventType, data: dict[str, Any]) -> None:
        """Emit a stream event if channel is available."""
        if self._stream_channel is not None:
            await self._stream_channel.publish(
                StreamEvent(
                    event_type=event_type,
                    data=data,
                )
            )
