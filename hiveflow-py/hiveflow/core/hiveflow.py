"""HiveFlow - Top-level entry point for the multi-agent framework.

This module provides the ``HiveFlow`` facade class — the primary interface
for developers to run workflows, generate teams, resume paused sessions,
and discover available resources.
"""

import asyncio
from pathlib import Path
from typing import Any

import structlog

from hiveflow.core.config import HiveFlowConfig, get_config
from hiveflow.core.session import WorkflowSession
from hiveflow.core.teams import (
    ArchetypeLibrary,
    TeamGenerationResult,
    TeamGenerator,
    TeamTemplateLibrary,
)
from hiveflow.core.workflow import WorkflowStatus
from hiveflow.plugins.llm import LLMProviderRegistry
from hiveflow.plugins.tools import ToolRegistry

logger = structlog.get_logger()


class HiveFlow:
    """Top-level entry point for the HiveFlow multi-agent framework.

    Provides a consistent, facade-style API for running workflows from any
    context: embedded Python, behind a REST API, from a CLI, or within a
    native application.

    Usage::

        hf = HiveFlow()
        session = hf.run_sync(team="summarizer", task="Summarize the history of computing")
        print(session.result.state)
    """

    def __init__(
        self,
        *,
        config: HiveFlowConfig | None = None,
        team_library: TeamTemplateLibrary | None = None,
        archetype_library: ArchetypeLibrary | None = None,
        tool_registry: ToolRegistry | None = None,
        skill_registry: Any | None = None,
        llm_registry: LLMProviderRegistry | None = None,
        checkpoint_storage: Any | None = None,
    ) -> None:
        """Create a HiveFlow instance.

        All parameters are optional — sensible defaults are used when not
        provided. This is the primary entry point for the framework.

        Args:
            config: Framework configuration (uses get_config() default if None)
            team_library: Team template library (uses default templates if None)
            archetype_library: Agent archetype library (uses defaults if None)
            tool_registry: Tool registry (empty if None)
            skill_registry: Skill registry for agent skills (None = no skills)
            llm_registry: LLM provider registry (empty if None)
            checkpoint_storage: Checkpoint storage backend (None = no persistence)
        """
        self._config = config or get_config()
        # Install as the global config so that downstream code using
        # get_config() (e.g. ResilientLLMProvider, tier-variable resolution)
        # picks up the caller-supplied overrides.
        from hiveflow.core.config import set_config

        set_config(self._config)
        self._team_library = team_library or TeamTemplateLibrary.default()
        self._archetype_library = archetype_library or ArchetypeLibrary.default()
        self._tool_registry = tool_registry or ToolRegistry()
        self._skill_registry = skill_registry
        self._llm_registry = llm_registry or LLMProviderRegistry()
        if llm_registry is None:
            self._llm_registry.discover()
        self._checkpoint_storage = checkpoint_storage
        self._active_sessions: dict[str, WorkflowSession] = {}

    async def run(
        self,
        team: str | dict[str, Any] | Any,
        task: str,
        *,
        documents: list[str | dict[str, str]] | None = None,
        initial_state: dict[str, Any] | None = None,
        checkpoint: bool = False,
        instructions_file: str | None = None,
    ) -> WorkflowSession:
        """Execute a multi-agent workflow.

        Args:
            team: Team template name (str), TeamConfiguration-compatible dict,
                  or TeamConfiguration object.
            task: The user's task or query.
            documents: Optional document paths or inline content dicts.
            initial_state: Optional initial state overrides.
            checkpoint: Enable checkpoint persistence at gates.
            instructions_file: Optional path to a text file containing
                instructions. Mutually exclusive with non-empty task.

        Returns:
            WorkflowSession with session_id, status, result, and event stream.

        Raises:
            ValidationError: If team configuration is invalid.
            KeyError: If template name not found in library.
            ValueError: If both task (non-empty) and instructions_file provided.
            FileNotFoundError: If instructions_file doesn't exist.
        """
        # Handle instructions_file — mutually exclusive with non-empty task
        if instructions_file is not None:
            if task.strip():
                raise ValueError(
                    "Cannot provide both 'task' (non-empty) and 'instructions_file'. "
                    "They are mutually exclusive."
                )
            from hiveflow.core.documents import DocumentPipeline

            instr_dir = Path(instructions_file).resolve().parent
            pipeline = DocumentPipeline(
                working_dir=instr_dir,
                allowed_paths=[instr_dir],
            )
            task = await pipeline.load_instructions_file(instructions_file)

        # Resolve team configuration
        config_dict = self._resolve_team_config(team)

        # Validate via schema
        from hiveflow.core.schema import TeamConfiguration

        if isinstance(config_dict, dict):
            team_config = TeamConfiguration(**config_dict)
        else:
            team_config = config_dict

        # Create session
        storage = self._checkpoint_storage if checkpoint else None
        session = WorkflowSession(
            team_config=team_config,
            task=task,
            checkpoint_storage=storage,
        )
        self._active_sessions[session.session_id] = session
        session._set_status(WorkflowStatus.RUNNING)

        # Build agents and engine
        mcp_manager = None
        try:
            # MCP integration: load config and start manager if enabled
            from hiveflow.plugins.mcp.config import MCPConfig
            from hiveflow.plugins.mcp.manager import MCPManager

            mcp_config = MCPConfig.from_file()
            effective_strategy = getattr(team_config, "mcp_strategy", None) or mcp_config.strategy

            if effective_strategy != "disabled":
                mcp_config = mcp_config.model_copy(update={"strategy": effective_strategy})
                mcp_manager = MCPManager(mcp_config, self._tool_registry)
                await mcp_manager.startup(task=task)

            generator = TeamGenerator()
            config_as_dict = (
                team_config.model_dump() if hasattr(team_config, "model_dump") else config_dict
            )

            # Resolve LLM provider for summarization/preprocessing based on the
            # first configured agent model.
            default_model_ref = None
            if config_as_dict.get("agents"):
                default_model_ref = config_as_dict["agents"][0].get("model")
            llm_provider = self._resolve_llm_provider(default_model_ref)

            agents, engine = generator.build(
                config_as_dict,
                llm_provider,
                tool_registry=self._tool_registry,
                skill_registry=self._skill_registry,
            )

            # Pass team library to engine for sub_workflow step resolution
            engine._team_library = self._team_library

            # Wire collaboration config if present on the team configuration
            if hasattr(team_config, "collaboration") and team_config.collaboration is not None:
                engine.set_collaboration_config(team_config.collaboration)

            # Execute workflow
            state = initial_state or {}
            state["task"] = task
            result = await engine.execute(
                agents,
                state,
                documents=documents,
                checkpoint_storage=storage,
                session_id=session.session_id,
                team_config=config_as_dict,
            )

            session._set_result(result)

        except Exception as e:
            from hiveflow.core.workflow import WorkflowResult

            session._set_result(
                WorkflowResult(
                    status=WorkflowStatus.FAILED,
                    state={},
                    error=str(e),
                )
            )
            logger.exception("Workflow execution failed: %s", e)

        finally:
            if mcp_manager is not None:
                await mcp_manager.shutdown()
            # Remove terminal sessions to prevent unbounded memory growth
            if session.status in (WorkflowStatus.COMPLETED, WorkflowStatus.FAILED):
                self._active_sessions.pop(session.session_id, None)

        return session

    def run_sync(
        self,
        team: str | dict[str, Any] | Any,
        task: str,
        **kwargs: Any,
    ) -> WorkflowSession:
        """Synchronous wrapper around run().

        Blocks until the workflow completes or pauses. Creates a new event
        loop if none is running.

        Args:
            team: Team template name, dict, or TeamConfiguration.
            task: The user's task or query.
            **kwargs: Additional keyword arguments passed to run().

        Returns:
            WorkflowSession with session_id, status, and result.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # Already in an async context — use nest_asyncio pattern or create task
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, self.run(team, task, **kwargs))
                return future.result()
        else:
            return asyncio.run(self.run(team, task, **kwargs))

    async def generate_team(
        self,
        task: str,
        *,
        model: str | None = None,
        auto_approve: bool = False,
    ) -> TeamGenerationResult:
        """Generate a team configuration using an LLM.

        Args:
            task: Description of the problem to solve.
            model: LLM to use for generation (defaults to config's strategic model).
            auto_approve: If True and no blocking gaps, execute immediately.

        Returns:
            TeamGenerationResult with config, capability_gaps, and new_archetypes.
        """
        generator = TeamGenerator()
        generate_kwargs: dict[str, Any] = {"task_description": task}
        if model:
            generate_kwargs["model"] = model
        config = generator.generate_team(**generate_kwargs)

        # Check for capability gaps (tool availability)
        from hiveflow.core.teams import CapabilityGap

        gaps: list[CapabilityGap] = []
        registered_tools = set(self._tool_registry.list_ids())

        for agent_def in config.get("agents", []):
            for tool_id in agent_def.get("tools", []):
                if tool_id not in registered_tools:
                    gaps.append(
                        CapabilityGap(
                            resource_type="tool",
                            resource_id=tool_id,
                            severity="degraded",
                            description=f"Tool '{tool_id}' is not registered",
                            fallback_strategy="Agent will operate without this tool",
                        )
                    )

        result = TeamGenerationResult(
            config=config,
            capability_gaps=gaps,
        )

        if auto_approve and not result.has_blocking_gaps:
            # Execute immediately
            await self.run(team=config, task=task)
            return result

        return result

    async def resume(
        self,
        session_id: str,
        responses: dict[str, Any],
        *,
        checkpoint_id: str | None = None,
    ) -> WorkflowSession:
        """Resume a paused workflow session.

        Loads the checkpoint, rebuilds agents and engine from the team
        configuration, and re-executes from the paused step forward.

        Args:
            session_id: Session to resume.
            responses: Approval responses keyed by request_id.
            checkpoint_id: Optional specific checkpoint to resume from.
                If None, resumes from the latest checkpoint.

        Returns:
            Updated WorkflowSession.

        Raises:
            KeyError: If session_id not found or checkpoint not found.
        """
        # Check in-memory sessions first
        session = self._active_sessions.get(session_id)

        # Load checkpoint from storage
        if self._checkpoint_storage is not None:
            checkpoint = await self._checkpoint_storage.load(session_id, checkpoint_id)
        else:
            checkpoint = None

        # Create session from checkpoint if not in memory
        if session is None and checkpoint is not None:
            session = WorkflowSession(
                session_id=session_id,
                task=checkpoint.task,
                checkpoint_storage=self._checkpoint_storage,
            )
            session._set_status(WorkflowStatus.PAUSED)
            self._active_sessions[session_id] = session

        if session is None:
            raise KeyError(f"Session '{session_id}' not found")

        if checkpoint is None:
            raise KeyError(
                f"No checkpoint found for session '{session_id}'"
                + (f" with checkpoint_id '{checkpoint_id}'" if checkpoint_id else "")
            )

        # Rebuild agents and engine from team configuration
        team_config = session._team_config
        if team_config is not None:
            config_as_dict = (
                team_config.model_dump() if hasattr(team_config, "model_dump") else team_config
            )
        elif checkpoint.team_config:
            config_as_dict = checkpoint.team_config
        else:
            raise KeyError(f"No team configuration available to rebuild session '{session_id}'")

        try:
            generator = TeamGenerator()
            default_model_ref = None
            if config_as_dict.get("agents"):
                default_model_ref = config_as_dict["agents"][0].get("model")
            llm_provider = self._resolve_llm_provider(default_model_ref)
            agents, engine = generator.build(
                config_as_dict,
                llm_provider,
                tool_registry=self._tool_registry,
                skill_registry=self._skill_registry,
            )

            # Clear pending requests before resume
            session._pending_requests.clear()
            session._set_status(WorkflowStatus.RUNNING)

            storage = self._checkpoint_storage
            result = await engine.resume(
                agents,
                checkpoint,
                responses=responses,
                checkpoint_storage=storage,
                session_id=session_id,
            )

            session._set_result(result)

        except Exception as e:
            from hiveflow.core.workflow import WorkflowResult

            session._set_result(
                WorkflowResult(
                    status=WorkflowStatus.FAILED,
                    state={},
                    error=str(e),
                )
            )
            logger.exception("Workflow resume failed: %s", e)

        finally:
            # Remove terminal sessions to prevent unbounded memory growth
            if session.status in (WorkflowStatus.COMPLETED, WorkflowStatus.FAILED):
                self._active_sessions.pop(session.session_id, None)

        return session

    def team_library(self) -> TeamTemplateLibrary:
        """Access the team template library."""
        return self._team_library

    def archetype_library(self) -> ArchetypeLibrary:
        """Access the archetype library."""
        return self._archetype_library

    def tool_registry(self) -> ToolRegistry:
        """Access the tool registry."""
        return self._tool_registry

    def model_registry(self) -> LLMProviderRegistry:
        """Access the LLM provider/model registry."""
        return self._llm_registry

    async def list_checkpoints(self, session_id: str) -> list[dict[str, Any]]:
        """List all checkpoints for a workflow session.

        Args:
            session_id: Session to list checkpoints for.

        Returns:
            List of checkpoint summary dicts with keys: checkpoint_id,
            session_id, step_index, current_agent_id, created_at.

        Raises:
            ValueError: If no checkpoint storage is configured.
        """
        if self._checkpoint_storage is None:
            raise ValueError("No checkpoint storage configured")

        checkpoints = await self._checkpoint_storage.list_checkpoints(session_id)
        return [
            {
                "checkpoint_id": cp.checkpoint_id,
                "session_id": cp.session_id,
                "step_index": cp.step_index,
                "current_agent_id": cp.current_agent_id,
                "created_at": cp.created_at,
            }
            for cp in checkpoints
        ]

    def _resolve_team_config(self, team: str | dict[str, Any] | Any) -> dict[str, Any] | Any:
        """Resolve team argument to a configuration dict or object.

        Args:
            team: Template name, dict, or TeamConfiguration

        Returns:
            Team configuration dict or object

        Raises:
            KeyError: If template name not found
        """
        if isinstance(team, str):
            config = self._team_library.get(team)
            if config is None:
                raise KeyError(f"Team template '{team}' not found in library")
            return config
        return team

    def _resolve_llm_provider(self, model_ref: str | None = None) -> Any:
        """Resolve the default LLM provider from a configured model reference.

        Returns:
            LLM provider instance or None
        """
        from hiveflow.core.config import get_config

        resolved_model_ref = model_ref or get_config().SMART_LLM
        if resolved_model_ref.startswith("$"):
            resolved_model_ref = get_config().resolve_model(resolved_model_ref)

        if ":" in resolved_model_ref:
            try:
                provider, _model_name = self._llm_registry.resolve_model(resolved_model_ref)
                return provider
            except (KeyError, ValueError):
                logger.debug("Could not resolve LLM provider for model %s", resolved_model_ref)

        providers = self._llm_registry.list_ids()
        if providers:
            return self._llm_registry.get(providers[0])
        return None
