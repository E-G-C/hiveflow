"""Workflow Graph Engine - Orchestrates multi-agent workflows.

This module handles workflow execution including sequential steps, parallel fan-out,
conditional loops, and human-in-the-loop gates. Supports summary propagation for
context management between steps.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import structlog

from hiveflow.core.agent import Agent
from hiveflow.core.schema import WorkflowStepType

if TYPE_CHECKING:
    from hiveflow.core.checkpoint import CheckpointStorage
    from hiveflow.core.documents import DocumentPipeline
    from hiveflow.core.summarizer import SummaryGenerator

logger = structlog.get_logger()

# Backwards-compatible alias
StepType = WorkflowStepType


@dataclass
class WorkflowStep:
    """Represents a single step in the workflow graph."""

    agent: str
    step_type: StepType | str
    next_step: str | None = None
    next_on_accept: str | None = None
    next_on_reject: str | None = None
    max_iterations: int = 3
    gate_id: str | None = None
    gate_description: str | None = None
    team: str | None = None
    input_mapping: dict[str, str] | None = None
    output_mapping: dict[str, str] | None = None
    context_ttl: int | None = None
    source: str | None = None  # Fan-out source: "task_data" for chunk routing
    step_id: str | None = None  # Optional unique ID; defaults to agent ID

    def __post_init__(self) -> None:
        if self.step_id is None:
            self.step_id = self.agent


class WorkflowStatus(StrEnum):
    """Status of a workflow execution."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"  # Waiting for human input


@dataclass
class StepResult:
    """Result of executing a single workflow step."""

    agent_id: str
    step_type: str
    state: dict[str, Any]
    status: str = "completed"
    error: str | None = None


@dataclass
class WorkflowResult:
    """Result of a complete workflow execution."""

    status: WorkflowStatus
    state: dict[str, Any]
    step_results: list[StepResult] = field(default_factory=list)
    error: str | None = None
    result_payload: Any | None = None  # ResultPayload, set on successful completion


# Type alias for event callbacks
EventCallback = Callable[[str, str, dict[str, Any]], None]

# Type alias for completion callbacks (sync or async)
CompletionCallback = Callable[..., Any]


class WorkflowEngine:
    """Executes workflow graphs with multiple agents.

    Supports sequential, parallel fan-out, conditional branching,
    and human-in-the-loop gating.
    """

    def __init__(
        self,
        workflow_steps: list[WorkflowStep],
        max_conditional_loops: int = 5,
        summarizer: "SummaryGenerator | None" = None,
        assembly_agents: list[str] | None = None,
        document_pipeline: "DocumentPipeline | None" = None,
        publish_config: Any | None = None,
        state_schema: Any | None = None,
        team_library: Any | None = None,
        task_preprocessor: Any | None = None,
    ) -> None:
        """Initialize workflow engine.

        Args:
            workflow_steps: List of steps defining the workflow graph
            max_conditional_loops: Max iterations for conditional loops
            summarizer: Optional summary generator for context propagation.
                When provided, summaries are generated after each step so
                downstream agents receive compact context instead of full
                outputs.
            assembly_agents: Optional list of agent IDs whose outputs should
                be assembled into a ``final_output`` key at the end of the
                workflow.  When provided, the engine concatenates the full
                outputs of the listed agents (in the order given) into a
                single document — this is the code-level assembly step from
                the divide-and-conquer pattern.
            document_pipeline: Optional DocumentPipeline instance for loading
                documents and instructions from files.
            publish_config: Optional PublishConfig (or dict) specifying
                output formats, layout, and directory. When provided, the
                engine auto-publishes after successful execution.
        """
        self.steps = workflow_steps
        self.max_conditional_loops = max_conditional_loops
        self.summarizer = summarizer
        self.assembly_agents = assembly_agents
        self._document_pipeline = document_pipeline
        self._publish_config = publish_config
        self._state_schema = state_schema
        self._team_library = team_library
        self._task_preprocessor = task_preprocessor
        self._collaboration_config = None  # Set via set_collaboration_config()

        # Stream channel for real-time event delivery (FR-023)
        self._stream_channel = None
        self._jsonl_writer = None
        self._init_streaming()

        # Build step lookup by step ID (defaults to agent ID)
        self._step_map: dict[str, WorkflowStep] = {
            step.step_id: step
            for step in self.steps  # type: ignore[misc]
        }

        # Event callbacks for observability
        self._callbacks: list[EventCallback] = []

        # Completion callbacks invoked with ResultPayload after workflow ends
        self._completion_callbacks: list[CompletionCallback] = []

    def on_event(self, callback: EventCallback) -> None:
        """Register an event callback.

        Args:
            callback: Function receiving (event_type, agent_id, data)
        """
        self._callbacks.append(callback)

    def set_collaboration_config(self, config: Any) -> None:
        """Set collaboration configuration for this engine.

        When set, execute() will create a CollaborationRuntime and inject
        collaboration tools into orchestrator agents.

        Args:
            config: CollaborationConfig instance
        """
        self._collaboration_config = config

    def _init_streaming(self) -> None:
        """Initialize StreamChannel and JsonLinesWriter if OUTPUT_DIR is configured."""
        try:
            from hiveflow.core.config import get_config
            from hiveflow.core.streaming import JsonLinesWriter, StreamChannel

            config = get_config()
            self._stream_channel = StreamChannel()
            if config.OUTPUT_DIR:
                self._jsonl_writer = JsonLinesWriter(config.OUTPUT_DIR)
        except Exception:
            logger.debug("Streaming initialization skipped")

    def _emit(self, event_type: str, agent_id: str, data: dict[str, Any]) -> None:
        """Emit an event to all registered callbacks."""
        for cb in self._callbacks:
            try:
                cb(event_type, agent_id, data)
            except Exception:
                logger.exception("Event callback failed")

    def _init_collaboration(self, agents: dict[str, Agent], state: dict[str, Any]) -> None:
        """Initialize CollaborationRuntime and inject tools into orchestrators.

        Creates a runtime, registers all pre-configured agents, and injects
        collaboration tools (delegate_task, send_message, read_messages) into
        agents with orchestrator behavior type.

        Args:
            agents: Agent dict from workflow execution
            state: Workflow state dict (runtime stored here)
        """
        from hiveflow.core.collaboration import CollaborationRuntime
        from hiveflow.core.teams import ArchetypeLibrary
        from hiveflow.plugins.llm import LLMConfig
        from hiveflow.plugins.tools import get_tool_registry

        # Get an LLM provider from any agent
        llm_provider = None
        llm_config = LLMConfig()
        for agent in agents.values():
            if agent.llm_provider is not None:
                llm_provider = agent.llm_provider
                llm_config = agent.llm_config
                break

        runtime = CollaborationRuntime(
            config=self._collaboration_config,
            agents=agents,
            archetype_library=ArchetypeLibrary.default(),
            tool_registry=get_tool_registry(),
            llm_provider=llm_provider,
            llm_config=llm_config,
            stream_channel=self._stream_channel,
        )

        state["_collaboration_runtime"] = runtime
        state["_delegation_depth"] = 0

        # Inject collaboration tools into agents
        from hiveflow.core.agent import AgentBehaviorType
        from hiveflow.plugins.tools.delegate_task import DelegateTaskTool
        from hiveflow.plugins.tools.message import ReadMessagesTool, SendMessageTool
        from hiveflow.plugins.tools.plan_and_execute import PlanAndExecuteTool
        from hiveflow.plugins.tools.spawn_agent import SpawnAgentTool

        for agent in agents.values():
            # Messaging tools for ALL agents (FR-014)
            agent.tools.append(
                SendMessageTool(
                    caller_agent_id=agent.agent_id,
                    state=state,
                    stream_channel=self._stream_channel,
                )
            )
            agent.tools.append(
                ReadMessagesTool(
                    caller_agent_id=agent.agent_id,
                    state=state,
                )
            )

            # Delegation and spawning tools only for orchestrators
            if agent.behavior_type == AgentBehaviorType.ORCHESTRATOR:
                agent.tools.append(
                    DelegateTaskTool(
                        runtime=runtime,
                        caller_agent_id=agent.agent_id,
                        state=state,
                    )
                )
                agent.tools.append(
                    SpawnAgentTool(
                        runtime=runtime,
                        caller_agent_id=agent.agent_id,
                    )
                )
                agent.tools.append(
                    PlanAndExecuteTool(
                        runtime=runtime,
                        caller_agent_id=agent.agent_id,
                        state=state,
                    )
                )

        logger.info("Collaboration runtime initialized with %d agents", len(agents))

    def on_complete(self, callback: CompletionCallback) -> None:
        """Register a completion callback invoked with the ResultPayload.

        Callbacks may be synchronous or asynchronous functions. They are
        invoked in registration order after a successful workflow execution.
        Each callback receives the ``ResultPayload`` as its sole argument.
        Errors in one callback do not prevent subsequent callbacks from running.

        Args:
            callback: Sync or async callable receiving the ResultPayload.
        """
        self._completion_callbacks.append(callback)

    async def _invoke_callbacks(self, payload: Any) -> None:
        """Dispatch the ResultPayload to all registered completion callbacks.

        Each callback is invoked in registration order with per-callback error
        isolation — an exception in one callback is logged and does not block
        subsequent callbacks.
        """
        for cb in self._completion_callbacks:
            try:
                result = cb(payload)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception("Completion callback %r failed", cb)

    async def _save_checkpoint(
        self,
        checkpoint_storage: "CheckpointStorage",
        session_id: str,
        step_index: int,
        current_agent_id: str,
        current_step_type: str,
        state: dict[str, Any],
        step_results: list[StepResult],  # noqa: ARG002
        visited_conditionals: dict[str, int],
        team_config: dict[str, Any] | None = None,
        task: str = "",
    ) -> str:
        """Save a checkpoint at a pause point.

        Args:
            checkpoint_storage: Storage backend to persist checkpoint
            session_id: Session identifier
            step_index: Index of the current step in self.steps
            current_agent_id: ID of the agent/gate at this step
            current_step_type: Type of the current step
            state: Current workflow state
            step_results: Step results accumulated so far
            visited_conditionals: Conditional loop iteration counts
            team_config: Team configuration dict for cold-resume
            task: Task description for cold-resume

        Returns:
            The checkpoint_id of the saved checkpoint
        """
        from hiveflow.core.checkpoint import WorkflowCheckpoint

        checkpoint = WorkflowCheckpoint(
            session_id=session_id,
            step_index=step_index,
            state=dict(state),
            current_agent_id=current_agent_id,
            current_step_type=current_step_type,
            iteration_counts=dict(visited_conditionals),
            team_config=team_config or {},
            task=task,
        )
        checkpoint_id = await checkpoint_storage.save(checkpoint)
        self._emit(
            "checkpoint_saved",
            current_agent_id,
            {
                "checkpoint_id": checkpoint_id,
                "session_id": session_id,
                "step_index": step_index,
            },
        )
        logger.debug(
            "Auto-checkpoint saved: session=%s, checkpoint=%s, step=%d, agent=%s",
            session_id,
            checkpoint_id,
            step_index,
            current_agent_id,
        )
        return checkpoint_id

    def _validate_checkpoint(self, checkpoint: Any) -> None:
        """Validate that a checkpoint is compatible with the current workflow.

        Checks that the checkpoint's step_index is in range and that the
        agent ID and step type at that position match the checkpoint metadata.

        Args:
            checkpoint: WorkflowCheckpoint to validate

        Raises:
            CheckpointError: If checkpoint is incompatible with the workflow
        """
        from hiveflow.core.checkpoint import CheckpointError

        step_index = checkpoint.step_index

        # (1) step_index in range
        if step_index < 0 or step_index >= len(self.steps):
            raise CheckpointError(
                f"Checkpoint step_index {step_index} is out of range "
                f"(workflow has {len(self.steps)} steps)"
            )

        step = self.steps[step_index]

        # (2) Agent ID matches
        # For GATED steps, the agent field is the gate_id
        expected_agent = (
            step.gate_id or step.agent if str(step.step_type) == StepType.GATED else step.agent
        )
        if checkpoint.current_agent_id and checkpoint.current_agent_id != expected_agent:
            raise CheckpointError(
                f"Checkpoint agent_id mismatch at step {step_index}: "
                f"checkpoint has '{checkpoint.current_agent_id}', "
                f"workflow has '{expected_agent}'"
            )

        # (3) Step type matches
        if checkpoint.current_step_type and checkpoint.current_step_type != str(step.step_type):
            raise CheckpointError(
                f"Checkpoint step_type mismatch at step {step_index}: "
                f"checkpoint has '{checkpoint.current_step_type}', "
                f"workflow has '{step.step_type}'"
            )

    async def execute(
        self,
        agents: dict[str, Agent],
        initial_state: dict[str, Any],
        *,
        documents: list[str | dict[str, str]] | None = None,
        instructions_file: str | None = None,
        checkpoint_storage: "CheckpointStorage | None" = None,
        session_id: str | None = None,
        team_config: dict[str, Any] | None = None,
    ) -> WorkflowResult:
        """Execute the workflow graph.

        Args:
            agents: Dictionary mapping agent IDs to agent instances
            initial_state: Starting state for the workflow
            documents: Optional list of file paths or inline content dicts
                to load as documents before execution.
            instructions_file: Optional file path to read as the task
                instructions. Mutually exclusive with initial_state['task'].
            checkpoint_storage: Optional checkpoint storage backend for
                automatic checkpointing at pause points.
            session_id: Optional session ID for checkpoint association.
                Required when checkpoint_storage is provided.
            team_config: Optional team configuration dict to persist
                in checkpoints for cold-resume support.

        Returns:
            WorkflowResult with final state and step history
        """
        state = dict(initial_state)
        step_results: list[StepResult] = []
        visited_conditionals: dict[str, int] = {}

        # Handle instructions_file
        if instructions_file is not None:
            if state.get("task"):
                raise ValueError("'instructions' and 'instructions_file' are mutually exclusive")
            if self._document_pipeline is not None:
                content = await self._document_pipeline.load_instructions_file(instructions_file)
                state["task"] = content
            else:
                from hiveflow.core.documents import DocumentPipeline

                pipeline = DocumentPipeline()
                content = await pipeline.load_instructions_file(instructions_file)
                state["task"] = content

        # Load documents if provided
        if documents is not None:
            pipeline = self._document_pipeline
            if pipeline is None:
                from hiveflow.core.documents import DocumentPipeline

                pipeline = DocumentPipeline()
            doc_state, doc_summary = await pipeline.load(documents)
            state["documents"] = doc_state
            state["document_summary"] = doc_summary
            self._emit(
                "documents_loaded",
                "workflow",
                {
                    "count": len(doc_state),
                    "summary": doc_summary,
                },
            )

            # Validate agent document references
            loaded_names = {d["name"] for d in doc_state}
            for agent_id, agent in agents.items():
                agent_def = getattr(agent, "agent_definition", None)
                if agent_def is None:
                    continue
                agent_doc_names = getattr(agent_def, "documents", None)
                if agent_doc_names is not None:
                    for name in agent_doc_names:
                        if name not in loaded_names:
                            raise ValueError(
                                f"Agent '{agent_id}' references unknown document: '{name}'"
                            )

        # Task preprocessing: separate instructions from data for large inputs
        if self._task_preprocessor is not None and state.get("task"):
            agent_count = len(agents) if agents else 1
            state = await self._task_preprocessor.preprocess(state, agent_count)

        if not self.steps:
            return WorkflowResult(
                status=WorkflowStatus.COMPLETED,
                state=state,
                step_results=step_results,
            )

        # Initialize collaboration runtime if configured
        if self._collaboration_config is not None and getattr(
            self._collaboration_config, "enabled", False
        ):
            self._init_collaboration(agents, state)

        # Start with the first step
        current_step: WorkflowStep | None = self.steps[0]

        return await self._execute_loop(
            agents,
            state,
            step_results,
            visited_conditionals,
            current_step,
            checkpoint_storage,
            session_id,
            team_config=team_config,
            task=state.get("task", ""),
        )

    async def resume(
        self,
        agents: dict[str, Agent],
        checkpoint: Any,
        *,
        responses: dict[str, Any] | None = None,
        checkpoint_storage: "CheckpointStorage | None" = None,
        session_id: str | None = None,
    ) -> WorkflowResult:
        """Resume a paused workflow from a checkpoint.

        Args:
            agents: Dictionary mapping agent IDs to agent instances
            checkpoint: WorkflowCheckpoint to resume from
            responses: Approval responses (e.g. gate approvals)
            checkpoint_storage: Optional storage for further checkpoints
            session_id: Optional session ID for checkpoint association

        Returns:
            WorkflowResult with final state and step history
        """
        # (1) Validate checkpoint
        self._validate_checkpoint(checkpoint)

        # (2) Restore state
        state = dict(checkpoint.state)
        step_results: list[StepResult] = []
        visited_conditionals = dict(checkpoint.iteration_counts)

        # (3) Apply responses — clear awaiting flags and store responses
        if responses is not None:
            state["awaiting_human_input"] = False
            state["awaiting_action_approval"] = False
            state["awaiting_gate_approval"] = False
            state["resume_responses"] = responses
            # Apply specific response data into state
            for key, value in responses.items():
                state[key] = value

            # Emit APPROVAL event for each processed response
            gate_id = state.get("pending_gate_id", "")
            self._emit(
                "approval",
                checkpoint.current_agent_id,
                {
                    "responses": responses,
                    "gate_id": gate_id,
                },
            )

        # (4) Resolve current step and advance to next
        current_step = self.steps[checkpoint.step_index]
        try:
            next_step = self._resolve_next_step(current_step, state, visited_conditionals)
        except RuntimeError as e:
            return WorkflowResult(
                status=WorkflowStatus.FAILED,
                state=state,
                step_results=step_results,
                error=str(e),
            )

        # (5) Execute from the next step forward
        return await self._execute_loop(
            agents,
            state,
            step_results,
            visited_conditionals,
            next_step,
            checkpoint_storage,
            session_id,
            team_config=checkpoint.team_config,
            task=checkpoint.task or state.get("task", ""),
        )

    async def _execute_loop(
        self,
        agents: dict[str, Agent],
        state: dict[str, Any],
        step_results: list[StepResult],
        visited_conditionals: dict[str, int],
        current_step: WorkflowStep | None,
        checkpoint_storage: "CheckpointStorage | None" = None,
        session_id: str | None = None,
        team_config: dict[str, Any] | None = None,
        task: str = "",
    ) -> WorkflowResult:
        """Execute the workflow loop from a given starting step.

        Shared between execute() and resume() to avoid code duplication.

        Args:
            agents: Agent instances
            state: Current workflow state
            step_results: Step results accumulated so far
            visited_conditionals: Conditional loop iteration counts
            current_step: Step to start executing from (or None to skip loop)
            checkpoint_storage: Optional storage for auto-checkpointing
            session_id: Optional session ID for checkpoints
            team_config: Team configuration dict for checkpoint persistence
            task: Task description for checkpoint persistence

        Returns:
            WorkflowResult with final state and step history
        """
        while current_step is not None:
            agent_id = current_step.agent
            step_type = str(current_step.step_type)

            # Track step execution order for context expiry
            step_order: list[str] = state.get("_step_order", [])

            # Gated steps don't require an agent — handle before agent validation
            if step_type == StepType.GATED:
                self._emit("step_start", current_step.gate_id or "", {"step_type": step_type})
                self._emit(
                    "gate_requested",
                    current_step.gate_id or "",
                    {
                        "gate_id": current_step.gate_id,
                        "gate_description": current_step.gate_description or "",
                        "step_index": self.steps.index(current_step),
                    },
                )
                state["awaiting_gate_approval"] = True
                state["pending_gate_id"] = current_step.gate_id
                state["pending_gate_description"] = current_step.gate_description or ""
                step_results.append(
                    StepResult(
                        agent_id=current_step.gate_id or "",
                        step_type=step_type,
                        state=state,
                        status="paused",
                    )
                )
                if checkpoint_storage is not None and session_id is not None:
                    await self._save_checkpoint(
                        checkpoint_storage,
                        session_id,
                        step_index=self.steps.index(current_step),
                        current_agent_id=current_step.gate_id or "",
                        current_step_type=step_type,
                        state=state,
                        step_results=step_results,
                        visited_conditionals=visited_conditionals,
                        team_config=team_config,
                        task=task,
                    )
                return WorkflowResult(
                    status=WorkflowStatus.PAUSED,
                    state=state,
                    step_results=step_results,
                )

            # Validate agent exists (non-gated steps require an agent)
            if agent_id not in agents:
                error = f"Agent '{agent_id}' not found in agents dict"
                logger.error(error)
                return WorkflowResult(
                    status=WorkflowStatus.FAILED,
                    state=state,
                    step_results=step_results,
                    error=error,
                )

            self._emit("step_start", agent_id, {"step_type": step_type})

            try:
                if step_type == StepType.PARALLEL_FAN_OUT:
                    state = await self._execute_parallel(current_step, agents, state)
                elif step_type == StepType.HUMAN_GATE:
                    state = await self._execute_agent_with_failure_policy(agents[agent_id], state)
                    if state.get("awaiting_human_input"):
                        step_results.append(
                            StepResult(
                                agent_id=agent_id,
                                step_type=step_type,
                                state=state,
                                status="paused",
                            )
                        )
                        if checkpoint_storage is not None and session_id is not None:
                            await self._save_checkpoint(
                                checkpoint_storage,
                                session_id,
                                step_index=self.steps.index(current_step),
                                current_agent_id=agent_id,
                                current_step_type=step_type,
                                state=state,
                                step_results=step_results,
                                visited_conditionals=visited_conditionals,
                                team_config=team_config,
                                task=task,
                            )
                        return WorkflowResult(
                            status=WorkflowStatus.PAUSED,
                            state=state,
                            step_results=step_results,
                        )
                elif step_type == "sub_workflow":
                    state = await self._execute_sub_workflow(current_step, agents, state)
                else:
                    state = await self._execute_agent_with_failure_policy(agents[agent_id], state)

                # Check if action_executor paused for approval
                if state.get("awaiting_action_approval"):
                    self._emit(
                        "action_proposed",
                        agent_id,
                        {
                            "agent_id": agent_id,
                            "actions": state.get(f"{agent_id}_proposed_actions", []),
                        },
                    )
                    step_results.append(
                        StepResult(
                            agent_id=agent_id,
                            step_type=step_type,
                            state=state,
                            status="paused",
                        )
                    )
                    if checkpoint_storage is not None and session_id is not None:
                        await self._save_checkpoint(
                            checkpoint_storage,
                            session_id,
                            step_index=self.steps.index(current_step),
                            current_agent_id=agent_id,
                            current_step_type=step_type,
                            state=state,
                            step_results=step_results,
                            visited_conditionals=visited_conditionals,
                            team_config=team_config,
                            task=task,
                        )
                    return WorkflowResult(
                        status=WorkflowStatus.PAUSED,
                        state=state,
                        step_results=step_results,
                    )

                # Apply state schema enforcement
                state = self._enforce_state_schema(agent_id, state)

                step_results.append(
                    StepResult(
                        agent_id=agent_id,
                        step_type=step_type,
                        state=state,
                    )
                )
                _output = state.get(f"{agent_id}_output", "")
                _words = len(_output.split()) if isinstance(_output, str) else 0
                self._emit(
                    "step_complete",
                    agent_id,
                    {
                        "step_type": step_type,
                        "word_count": _words,
                    },
                )

                # Generate summary for downstream agents (context management)
                if self.summarizer is not None:
                    agent_output_type = getattr(agents.get(agent_id), "output_type", None)
                    state = await self._generate_summary(
                        agent_id,
                        state,
                        output_type=agent_output_type,
                    )

                # Track step execution order and TTL for context expiry
                step_order = list(state.get("_step_order", []))
                if agent_id not in step_order:
                    step_order.append(agent_id)
                state["_step_order"] = step_order
                if current_step.context_ttl is not None:
                    ttl_map = dict(state.get("_context_ttl", {}))
                    ttl_map[agent_id] = current_step.context_ttl
                    state["_context_ttl"] = ttl_map

            except Exception as e:
                error_msg = f"Agent '{agent_id}' failed: {e}"
                logger.exception(error_msg)

                # Trigger rollback if the agent has rollback_on_failure=True
                agent_for_rollback = agents.get(agent_id)
                if agent_for_rollback:
                    agent_def = getattr(agent_for_rollback, "agent_definition", None)
                    if agent_def and getattr(agent_def, "rollback_on_failure", False):
                        await self._trigger_rollback(agent_for_rollback, state)

                step_results.append(
                    StepResult(
                        agent_id=agent_id,
                        step_type=step_type,
                        state=state,
                        status="failed",
                        error=str(e),
                    )
                )
                self._emit("step_error", agent_id, {"error": str(e)})
                return WorkflowResult(
                    status=WorkflowStatus.FAILED,
                    state=state,
                    step_results=step_results,
                    error=error_msg,
                )

            # Determine next step
            try:
                current_step = self._resolve_next_step(current_step, state, visited_conditionals)
            except RuntimeError as e:
                error_msg = str(e)
                logger.error(error_msg)
                return WorkflowResult(
                    status=WorkflowStatus.FAILED,
                    state=state,
                    step_results=step_results,
                    error=error_msg,
                )

        # Code-level assembly: stitch outputs into final document
        if self.assembly_agents is not None:
            state = self._assemble_outputs(state)

        # Assemble structured ResultPayload for the output pipeline
        payload = None
        try:
            from hiveflow.core.result_payload import ResultPayload

            payload = ResultPayload.from_workflow_result(
                type(
                    "_WR",
                    (),
                    {
                        "status": WorkflowStatus.COMPLETED,
                        "state": state,
                        "step_results": step_results,
                        "error": None,
                    },
                )(),
            )
        except Exception:
            logger.debug("ResultPayload assembly skipped", exc_info=True)

        # Auto-publish if publish_config is set and payload was assembled
        published_paths: list[Any] = []
        if payload is not None and self._publish_config is not None:
            try:
                cfg = self._publish_config
                formats = (
                    getattr(cfg, "formats", None) or cfg.get("formats", [])
                    if isinstance(cfg, dict)
                    else getattr(cfg, "formats", [])
                )

                # Discover all installed publishers via entry points
                from hiveflow.plugins.publishers import PublisherRegistry

                registry = PublisherRegistry.create()

                # If no formats specified, publish to all discovered formats
                if not formats:
                    formats = registry.list_ids()

                if formats:
                    output_dir = (
                        getattr(cfg, "output_dir", "./output")
                        if not isinstance(cfg, dict)
                        else cfg.get("output_dir", "./output")
                    )
                    filename = (
                        getattr(cfg, "filename", "output")
                        if not isinstance(cfg, dict)
                        else cfg.get("filename", "output")
                    )
                    layout_name = (
                        getattr(cfg, "layout", "default")
                        if not isinstance(cfg, dict)
                        else cfg.get("layout", "default")
                    )
                    published_paths = await registry.publish_all(
                        payload,
                        output_dir,
                        formats,
                        filename=filename,
                        layout=layout_name,
                    )
                    logger.info("Auto-published to %d formats", len(published_paths))
            except Exception:
                logger.warning("Auto-publish failed", exc_info=True)

        # Invoke completion callbacks with the payload
        if payload is not None and self._completion_callbacks:
            await self._invoke_callbacks(payload)

        # Emit OUTPUT event with terminal workflow output
        self._emit(
            "output",
            "",
            {
                "result": state.get("final_output", ""),
            },
        )

        return WorkflowResult(
            status=WorkflowStatus.COMPLETED,
            state=state,
            step_results=step_results,
            result_payload=payload,
        )

    async def _execute_agent(self, agent: Agent, state: dict[str, Any]) -> dict[str, Any]:
        """Execute a single agent.

        Args:
            agent: Agent instance to execute
            state: Current state

        Returns:
            Updated state
        """
        # Inject stream channel for executor events (FR-022)
        if self._stream_channel and "_stream_channel" not in state:
            state["_stream_channel"] = self._stream_channel

        # Pre-generate document summaries if agent uses summary mode (FR-009)
        await self._pre_generate_summaries_if_needed(agent, state)

        return await agent.execute(state)

    async def _pre_generate_summaries_if_needed(self, agent: Agent, state: dict[str, Any]) -> None:
        """Pre-generate document summaries if agent uses summary document mode."""
        agent_def = getattr(agent, "agent_definition", None)
        if agent_def is None:
            return
        mode = getattr(agent_def, "document_mode", "none")
        if mode != "summary":
            return
        docs = state.get("documents", [])
        if not docs:
            return
        # Check if summaries already cached
        if all(d.get("name", "") in state.get("_document_summaries", {}) for d in docs):
            return
        # Try to generate using agent's LLM provider
        llm_provider = getattr(agent, "llm_provider", None)
        if llm_provider is None:
            return
        try:
            from hiveflow.core.config import get_config
            from hiveflow.core.documents import DocumentPipeline

            config = get_config()
            pipeline = DocumentPipeline()
            await pipeline.generate_summaries(
                docs, state, llm_provider, max_tokens=config.MAX_SUMMARY_LENGTH
            )
        except Exception:
            logger.debug("Summary pre-generation skipped for agent %s", agent.agent_id)

    def _is_transient_error(self, exc: Exception) -> bool:
        """Check if an exception is a transient LLM/network error worth retrying.

        Recognised transient errors:
        - ConnectionError, TimeoutError, asyncio.TimeoutError
        - httpx.HTTPStatusError with status 429 or >= 500
        - openai.RateLimitError, openai.APIStatusError (>= 500)
        - anthropic.RateLimitError, anthropic.APIStatusError (>= 500)
        """
        if isinstance(exc, (ConnectionError, TimeoutError, asyncio.TimeoutError)):
            return True
        # Lazy imports to avoid import-time SDK dependency (constitution §3.1)
        try:
            import httpx

            if isinstance(exc, httpx.HTTPStatusError):
                status = exc.response.status_code
                return status == 429 or status >= 500
        except ImportError:
            pass
        try:
            import openai

            if isinstance(exc, openai.RateLimitError):
                return True
            if isinstance(exc, openai.APIStatusError) and exc.status_code >= 500:
                return True
        except ImportError:
            pass
        try:
            import anthropic

            if isinstance(exc, anthropic.RateLimitError):
                return True
            if isinstance(exc, anthropic.APIStatusError) and exc.status_code >= 500:
                return True
        except ImportError:
            pass
        return False

    async def _retry_transient(
        self,
        func: Callable,
        state: dict[str, Any],
        base_delay: float = 1.0,
        backoff_factor: float = 2.0,
        max_retries: int = 3,
    ) -> dict[str, Any]:
        """Retry a callable with exponential backoff for transient LLM errors.

        Catches transient errors (HTTP 429/5xx, RateLimitError, ConnectionError,
        TimeoutError) and retries with exponential backoff before re-raising.

        Args:
            func: Async callable (e.g. agent.execute) to invoke
            state: Current workflow state to pass to func
            base_delay: Initial delay in seconds between retries
            backoff_factor: Multiplier for delay on each subsequent retry
            max_retries: Maximum number of retry attempts

        Returns:
            Result from successful func invocation

        Raises:
            Exception: The last transient error if all retries exhausted,
                or any non-transient error immediately.
        """
        slog = structlog.get_logger("hiveflow.workflow.retry")
        delay = base_delay
        for attempt in range(max_retries + 1):
            try:
                return await func(state)
            except Exception as exc:
                if not self._is_transient_error(exc) or attempt == max_retries:
                    raise
                slog.warning(
                    "transient_error_retry",
                    attempt=attempt + 1,
                    max_retries=max_retries,
                    delay=delay,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                await asyncio.sleep(delay)
                delay *= backoff_factor
        # Unreachable, but satisfies type checker
        raise RuntimeError("Unexpected exit from retry loop")

    async def _execute_agent_with_failure_policy(
        self,
        agent: Agent,
        state: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute an agent with transient retry and on_failure policy handling.

        First applies transient-error backoff via _retry_transient. If the call
        still fails, applies the agent's on_failure policy:
        - 'fail' (or None): re-raises the exception (workflow halts)
        - 'retry': retries up to agent.agent_definition.max_retries, then re-raises
        - 'skip': logs warning and returns state unmodified

        Args:
            agent: Agent instance to execute
            state: Current workflow state

        Returns:
            Updated state dict
        """
        slog = structlog.get_logger("hiveflow.workflow.failure_policy")
        agent_def = getattr(agent, "agent_definition", None)
        on_failure = getattr(agent_def, "on_failure", None) if agent_def else None
        max_retries = getattr(agent_def, "max_retries", 1) if agent_def else 1

        async def _run(s: dict[str, Any]) -> dict[str, Any]:
            return await self._execute_agent(agent, s)

        if on_failure == "retry":
            last_exc: Exception | None = None
            for attempt in range(max_retries):
                try:
                    return await self._retry_transient(_run, state)
                except Exception as exc:
                    last_exc = exc
                    slog.warning(
                        "on_failure_retry",
                        agent_id=agent.agent_id,
                        attempt=attempt + 1,
                        max_retries=max_retries,
                        error_type=type(exc).__name__,
                        error=str(exc),
                    )
            raise last_exc  # type: ignore[misc]

        if on_failure == "skip":
            try:
                return await self._retry_transient(_run, state)
            except Exception as exc:
                slog.warning(
                    "on_failure_skip",
                    agent_id=agent.agent_id,
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                return state

        # on_failure is 'fail' or None — re-raise after transient retries
        return await self._retry_transient(_run, state)

    async def _trigger_rollback(
        self,
        agent: Agent,
        state: dict[str, Any],
    ) -> None:
        """Invoke the declared rollback_action tool for an agent.

        If the rollback itself fails, the error is logged but not re-raised
        to avoid masking the original failure.

        Args:
            agent: The agent whose rollback_action should be invoked
            state: Current workflow state (provides context for rollback)
        """
        slog = structlog.get_logger("hiveflow.workflow.rollback")
        agent_def = getattr(agent, "agent_definition", None)
        rollback_action = getattr(agent_def, "rollback_action", None) if agent_def else None
        if not rollback_action:
            return

        tool = agent._tool_map.get(rollback_action) if hasattr(agent, "_tool_map") else None
        if not tool:
            slog.warning(
                "rollback_tool_not_found",
                agent_id=agent.agent_id,
                rollback_action=rollback_action,
            )
            return

        try:
            action_records = state.get(f"{agent.agent_id}_action_records", [])
            context = {"agent_id": agent.agent_id, "action_records": action_records}
            await tool.execute(context)
            slog.info(
                "rollback_succeeded",
                agent_id=agent.agent_id,
                rollback_action=rollback_action,
            )
        except Exception as exc:
            slog.error(
                "rollback_failed",
                agent_id=agent.agent_id,
                rollback_action=rollback_action,
                error_type=type(exc).__name__,
                error=str(exc),
            )

    async def _execute_parallel(
        self,
        step: WorkflowStep,
        agents: dict[str, Agent],
        state: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute the current agent in parallel fan-out mode.

        For parallel fan-out, the agent is executed once per parallel_item.
        When a summarizer is configured, generates per-item summaries and
        assembles an outline for downstream agents.

        Args:
            step: Current workflow step
            agents: All available agents
            state: Current state

        Returns:
            Merged state from parallel execution
        """
        agent = agents[step.agent]

        # Determine items to fan out over.
        # An explicit source="task_data" on the step takes priority — this
        # means the user deliberately wants workers to iterate over the
        # preprocessed data chunks, not over any parallel_items that a
        # preceding orchestrator may have emitted.
        step_source = getattr(step, "source", None)
        if step_source == "task_data" and "task_data" in state:
            parallel_items = state["task_data"]
        else:
            parallel_items = state.get("parallel_items")

        if parallel_items and isinstance(parallel_items, list):
            # Fan out: run agent on each item concurrently
            tasks = []
            for i, item in enumerate(parallel_items):
                item_state = {**state, "current_item": item, "item_index": i}
                tasks.append(self._execute_agent_with_failure_policy(agent, item_state))

            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Merge results back into state
            merged_outputs: list[Any] = []
            parallel_results: dict[str, Any] = {}
            for i, r in enumerate(results):
                if isinstance(r, BaseException):
                    logger.error("Parallel task failed: %s", r)
                    merged_outputs.append({"error": str(r)})
                    parallel_results[f"item_{i}"] = {"error": str(r)}
                else:
                    output_key = f"{step.agent}_output"
                    output_val = r.get(output_key, "")
                    merged_outputs.append(output_val)
                    parallel_results[f"item_{i}"] = r

            state = {
                **state,
                f"{step.agent}_outputs": merged_outputs,
                f"{step.agent}_output": "\n\n".join(
                    str(o) for o in merged_outputs if not isinstance(o, dict)
                ),
                f"{step.agent}_parallel_results": parallel_results,
            }

            # Generate summaries and outline for parallel outputs
            if self.summarizer is not None:
                summaries: dict[str, str] = {}
                for i, output in enumerate(merged_outputs):
                    if isinstance(output, str) and output:
                        try:
                            summary = await self.summarizer.summarize(output)
                            summaries[f"{step.agent}_item_{i}"] = summary
                        except Exception:
                            logger.warning("Summary failed for parallel item %d", i)
                            summaries[f"{step.agent}_item_{i}"] = output[:500]

                if summaries:
                    state[f"{step.agent}_summaries"] = summaries
                    try:
                        outline = await self.summarizer.build_outline(summaries)
                        state[f"{step.agent}_outline"] = outline
                        self._emit(
                            "outline_generated",
                            step.agent,
                            {"num_items": len(summaries)},
                        )
                    except Exception:
                        logger.warning("Outline generation failed for %s", step.agent)
                        state[f"{step.agent}_outline"] = "\n".join(summaries.values())

            return state
        else:
            # No parallel items - just run normally
            return await self._execute_agent_with_failure_policy(agent, state)

    async def _execute_sub_workflow(
        self,
        step: WorkflowStep,
        _agents: dict[str, Agent],
        state: dict[str, Any],
        _depth: int = 0,
    ) -> dict[str, Any]:
        """Execute a nested team configuration as a sub-workflow.

        Args:
            step: The sub_workflow step definition (must have step.team set)
            agents: Current workflow's agents dict
            state: Current workflow state
            _depth: Current recursion depth (max 5)

        Returns:
            Updated state with sub-workflow outputs merged via output_mapping

        Raises:
            RuntimeError: If team_library is not set, team not found, or depth > 5
        """
        if _depth >= 5:
            raise RuntimeError(
                f"Sub-workflow recursion depth exceeded (max 5) at step '{step.agent}'"
            )

        if self._team_library is None:
            raise RuntimeError("Cannot execute sub_workflow: no TeamLibrary configured")

        team_config = self._team_library.get(step.team)
        if team_config is None:
            raise RuntimeError(f"Sub-workflow team '{step.team}' not found in TeamLibrary")

        # Apply input_mapping to build inner state
        if step.input_mapping:
            inner_state = {
                inner_key: state.get(outer_key)
                for inner_key, outer_key in step.input_mapping.items()
            }
        else:
            inner_state = dict(state)

        # Build inner workflow from team config
        from hiveflow.core.teams import TeamGenerator

        generator = TeamGenerator()
        # Derive LLM provider from parent workflow's agents
        parent_provider = next((a.llm_provider for a in _agents.values() if a.llm_provider), None)
        inner_agents, inner_engine = generator.build(
            team_config if isinstance(team_config, dict) else team_config,
            parent_provider,
        )
        inner_engine._team_library = self._team_library

        result = await inner_engine.execute(inner_agents, inner_state)

        if result.status != WorkflowStatus.COMPLETED:
            raise RuntimeError(
                f"Sub-workflow '{step.team}' failed: {result.error or result.status}"
            )

        # Apply output_mapping to merge results
        if step.output_mapping:
            for outer_key, inner_key in step.output_mapping.items():
                state[outer_key] = result.state.get(inner_key)
        else:
            state.update(result.state)

        return state

    def _resolve_next_step(
        self,
        current: WorkflowStep,
        state: dict[str, Any],
        visited_conditionals: dict[str, int],
    ) -> WorkflowStep | None:
        """Determine the next step based on current step type and state.

        Args:
            current: The current step
            state: Current workflow state
            visited_conditionals: Track loop iterations

        Returns:
            Next WorkflowStep or None if workflow is complete
        """
        step_type = str(current.step_type)

        if step_type == StepType.CONDITIONAL:
            # Check for acceptance signal in state
            agent_output = state.get(f"{current.agent}_output", "")
            is_accepted = self._evaluate_condition(current.agent, agent_output, state)

            # Track loop iterations to prevent infinite loops
            loop_key = current.agent
            visited_conditionals[loop_key] = visited_conditionals.get(loop_key, 0) + 1

            # Use per-step max_iterations if set, otherwise fall back to global
            max_iters = (
                current.max_iterations if current.max_iterations > 0 else self.max_conditional_loops
            )

            if visited_conditionals[loop_key] >= max_iters:
                raise RuntimeError(
                    f"Conditional loop for '{current.agent}' exceeded maximum "
                    f"iterations ({max_iters}). Last evaluation: "
                    f"{'accepted' if is_accepted else 'rejected'}. "
                    f"Increase max_iterations on the step or fix the evaluation logic."
                )

            next_id = current.next_on_accept if is_accepted else current.next_on_reject
        else:
            next_id = current.next_step

        if next_id is None:
            return None

        return self._step_map.get(next_id)

    def _evaluate_condition(self, agent_id: str, output: str, state: dict[str, Any]) -> bool:
        """Evaluate whether a conditional step's condition is met.

        Checks for explicit approval signals in state or output.

        Args:
            agent_id: The agent that produced the output
            output: Agent's text output
            state: Current workflow state

        Returns:
            True if condition is accepted
        """
        # Check for explicit state signals
        if state.get(f"{agent_id}_approved") is True:
            return True
        if state.get(f"{agent_id}_rejected") is True:
            return False

        # Heuristic: look for acceptance keywords in output
        output_lower = output.lower()
        accept_keywords = ["approved", "accepted", "pass", "satisfactory", "meets criteria"]
        reject_keywords = ["rejected", "needs revision", "revise", "insufficient", "fail"]

        accept_score = sum(1 for kw in accept_keywords if kw in output_lower)
        reject_score = sum(1 for kw in reject_keywords if kw in output_lower)

        if accept_score == reject_score:
            slog = structlog.get_logger("hiveflow.workflow.condition")
            slog.warning(
                "ambiguous_condition_result",
                agent_id=agent_id,
                accept_score=accept_score,
                reject_score=reject_score,
                message="Tied scores default to reject path",
            )

        return accept_score > reject_score

    def _enforce_state_schema(self, agent_id: str, state: dict[str, Any]) -> dict[str, Any]:
        """Apply state schema enforcement after agent execution.

        Args:
            agent_id: The agent that just wrote to state
            state: Current workflow state

        Returns:
            State, potentially filtered in strict mode
        """
        if self._state_schema is None:
            return state

        mode = getattr(self._state_schema, "enforcement_mode", "off")
        if mode == "off":
            return state

        agent_io = getattr(self._state_schema, "agent_io", {})
        if agent_id not in agent_io:
            return state

        declared_writes = set(agent_io[agent_id].writes)
        if not declared_writes:
            return state

        # Find keys written by this agent (agent-prefixed keys)
        agent_prefix = f"{agent_id}_"
        agent_written_keys = {k for k in state if k.startswith(agent_prefix)}

        undeclared = agent_written_keys - declared_writes
        if not undeclared:
            return state

        if mode == "warn":
            for key in sorted(undeclared):
                logger.warning(
                    "Agent '%s' wrote undeclared state key '%s' (declared writes: %s)",
                    agent_id,
                    key,
                    sorted(declared_writes),
                )
        elif mode == "strict":
            # Filter out undeclared writes
            state = {k: v for k, v in state.items() if k not in undeclared}
            logger.info(
                "Strict enforcement: filtered %d undeclared writes from agent '%s'",
                len(undeclared),
                agent_id,
            )

        return state

    def _assemble_outputs(self, state: dict[str, Any]) -> dict[str, Any]:
        """Assemble full agent outputs into a single final document.

        This is the code-level assembly step from the divide-and-conquer
        pattern.  Instead of using an LLM to generate the final document,
        the engine concatenates the raw outputs from the specified agents
        in order, producing a ``final_output`` state key.

        For parallel fan-out agents, individual item outputs (stored in
        ``{agent}_outputs``) are included as separate sections.

        Args:
            state: Current workflow state

        Returns:
            Updated state with ``final_output`` key added
        """
        sections: list[str] = []

        for agent_id in self.assembly_agents:  # type: ignore[union-attr]
            # Check for parallel outputs first (list of per-item results)
            outputs_key = f"{agent_id}_outputs"
            output_key = f"{agent_id}_output"

            if outputs_key in state and isinstance(state[outputs_key], list):
                # Parallel fan-out: include each item as a section
                for _i, item_output in enumerate(state[outputs_key]):
                    if isinstance(item_output, str) and item_output.strip():
                        sections.append(item_output)
            elif output_key in state and isinstance(state[output_key], str):
                output = state[output_key]
                if output.strip():
                    sections.append(output)

        if sections:
            state = {**state, "final_output": "\n\n".join(sections)}
            self._emit(
                "assembly_complete",
                "workflow",
                {"num_sections": len(sections), "total_words": len(" ".join(sections).split())},
            )

        return state

    async def _generate_summary(
        self,
        agent_id: str,
        state: dict[str, Any],
        output_type: str | None = None,
    ) -> dict[str, Any]:
        """Generate a summary of an agent's output for context propagation.

        If summarization fails, the workflow continues without a summary
        (downstream agents will fall back to full output).

        Args:
            agent_id: The agent whose output to summarize
            state: Current workflow state
            output_type: Agent output type for differential compression

        Returns:
            Updated state with summary added
        """
        output_key = f"{agent_id}_output"
        summary_key = f"{agent_id}_summary"
        agent_output = state.get(output_key, "")

        if not agent_output or not isinstance(agent_output, str):
            return state

        try:
            summary = await self.summarizer.summarize(  # type: ignore[union-attr]
                agent_output,
                output_type=output_type,
            )
            state = {**state, summary_key: summary}
            self._emit(
                "summary_generated",
                agent_id,
                {"summary_length": len(summary.split())},
            )
        except Exception as e:
            logger.warning("Summary generation failed for %s: %s", agent_id, e)

        return state

    @classmethod
    def from_schema(
        cls,
        workflow_graph: Any,
        summarizer: "SummaryGenerator | None" = None,
        assembly_agents: list[str] | None = None,
        state_schema: Any | None = None,
    ) -> "WorkflowEngine":
        """Create WorkflowEngine from a WorkflowGraph schema object.

        Args:
            workflow_graph: WorkflowGraph instance from schema
            summarizer: Optional summary generator for context propagation
            assembly_agents: Optional list of agent IDs for code-level assembly
            state_schema: Optional StateSchema for state enforcement

        Returns:
            Configured WorkflowEngine
        """
        steps = []
        for step_def in workflow_graph.steps:
            max_iterations = getattr(step_def, "max_iterations", None) or 3
            steps.append(
                WorkflowStep(
                    agent=step_def.agent,
                    step_type=step_def.type.value,
                    next_step=step_def.next,
                    next_on_accept=step_def.next_on_accept,
                    next_on_reject=step_def.next_on_reject,
                    max_iterations=max_iterations,
                    gate_id=getattr(step_def, "gate_id", None),
                    gate_description=getattr(step_def, "gate_description", None),
                    team=getattr(step_def, "team", None),
                    input_mapping=getattr(step_def, "input_mapping", None),
                    output_mapping=getattr(step_def, "output_mapping", None),
                    context_ttl=getattr(step_def, "context_ttl", None),
                )
            )
        return cls(
            steps,
            summarizer=summarizer,
            assembly_agents=assembly_agents,
            state_schema=state_schema,
        )
