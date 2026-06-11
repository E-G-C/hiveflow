"""Team Template Library - Pre-built multi-agent team configurations.

Provides ready-to-use team templates for common workflows:
research reports, code review, content creation, etc.
Also includes ArchetypeLibrary for reusable agent definitions,
CapabilityGap for reporting missing capabilities, and
TeamGenerationResult for LLM-generated team results.
"""

import json
from pathlib import Path
from typing import Any

import structlog
from pydantic import BaseModel, Field, computed_field

logger = structlog.get_logger()


class TeamTemplateLibrary:
    """Library of pre-built team configuration templates.

    Templates are JSON files that define complete TeamConfiguration
    objects, ready to be loaded and executed.
    """

    def __init__(self) -> None:
        self._templates: dict[str, dict[str, Any]] = {}

    def register(self, name: str, template: dict[str, Any]) -> None:
        """Register a team template.

        Args:
            name: Template name
            template: Template configuration dict
        """
        self._templates[name] = template

    def get(self, name: str) -> dict[str, Any] | None:
        """Get a template by name.

        Args:
            name: Template name

        Returns:
            Template dict or None
        """
        return self._templates.get(name)

    def list_templates(self) -> list[str]:
        """List all available template names.

        Returns:
            Sorted list of template names
        """
        return sorted(self._templates.keys())

    @classmethod
    def from_directory(cls, directory: str | Path) -> "TeamTemplateLibrary":
        """Load templates from a directory of JSON files.

        Args:
            directory: Path to directory of template JSON files

        Returns:
            Populated TeamTemplateLibrary
        """
        lib = cls()
        dir_path = Path(directory)

        if not dir_path.exists():
            logger.warning("Template directory not found: %s", dir_path)
            return lib

        for file_path in sorted(dir_path.glob("*.json")):
            try:
                with open(file_path, encoding="utf-8") as f:
                    template = json.load(f)
                lib.register(file_path.stem, template)
                logger.debug("Loaded team template: %s", file_path.stem)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load template %s: %s", file_path, e)

        return lib

    @classmethod
    def default(cls) -> "TeamTemplateLibrary":
        """Create library with built-in templates.

        Returns:
            TeamTemplateLibrary with default templates
        """
        lib = cls()

        # Load from bundled templates directory
        templates_dir = Path(__file__).parent.parent / "templates"
        if templates_dir.exists():
            for file_path in sorted(templates_dir.glob("*.json")):
                try:
                    with open(file_path, encoding="utf-8") as f:
                        template = json.load(f)
                    lib.register(file_path.stem, template)
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning("Failed to load bundled template %s: %s", file_path, e)

        return lib


class ArchetypeLibrary:
    """Library of reusable agent definition archetypes.

    Archetypes are building blocks that compose into teams. Each archetype
    is a dict containing role, system_prompt, behavior_type, and optional
    tools — a partial AgentDefinition that gets expanded into a full
    definition when included in a team.
    """

    def __init__(self) -> None:
        self._archetypes: dict[str, dict[str, Any]] = {}

    def register(self, name: str, archetype: dict[str, Any]) -> None:
        """Register an archetype.

        Args:
            name: Archetype name
            archetype: Archetype definition dict
        """
        self._archetypes[name] = archetype

    def get(self, name: str) -> dict[str, Any] | None:
        """Get an archetype by name.

        Args:
            name: Archetype name

        Returns:
            Archetype dict or None
        """
        return self._archetypes.get(name)

    def list_archetypes(self) -> list[str]:
        """List all available archetype names.

        Returns:
            Sorted list of archetype names
        """
        return sorted(self._archetypes.keys())

    @classmethod
    def from_directory(cls, directory: str | Path) -> "ArchetypeLibrary":
        """Load archetypes from a directory of JSON files.

        Args:
            directory: Path to directory of archetype JSON files

        Returns:
            Populated ArchetypeLibrary
        """
        lib = cls()
        dir_path = Path(directory)

        if not dir_path.exists():
            logger.warning("Archetype directory not found: %s", dir_path)
            return lib

        for file_path in sorted(dir_path.glob("*.json")):
            try:
                with open(file_path, encoding="utf-8") as f:
                    archetype = json.load(f)
                lib.register(file_path.stem, archetype)
                logger.debug("Loaded archetype: %s", file_path.stem)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load archetype %s: %s", file_path, e)

        return lib

    @classmethod
    def default(cls) -> "ArchetypeLibrary":
        """Create library with built-in archetypes from TeamGenerator.ARCHETYPES.

        Returns:
            ArchetypeLibrary with default archetypes
        """
        lib = cls()
        # Load from TeamGenerator's static archetypes for backward compatibility
        for name, archetype in TeamGenerator.ARCHETYPES.items():
            lib.register(name, archetype)

        # Also load from bundled archetypes directory if it exists
        archetypes_dir = Path(__file__).parent.parent / "templates" / "archetypes"
        if archetypes_dir.exists():
            for file_path in sorted(archetypes_dir.glob("*.json")):
                try:
                    with open(file_path, encoding="utf-8") as f:
                        archetype = json.load(f)
                    lib.register(file_path.stem, archetype)
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning("Failed to load bundled archetype %s: %s", file_path, e)

        return lib


class CapabilityGap(BaseModel):
    """Report of a missing capability in an LLM-generated team.

    When the LLM generates a team that requires tools or capabilities
    not available in the current registry, these gaps are reported
    with severity levels so the caller can decide whether to proceed.
    """

    resource_type: str = Field(
        ..., description="Type of missing resource: tool, model, or capability"
    )
    resource_id: str = Field(..., description="Identifier of the missing resource")
    severity: str = Field(
        ..., description="Impact level: blocking, degraded, or functional_but_limited"
    )
    description: str = Field(..., description="What's missing and why it matters")
    fallback_strategy: str | None = Field(default=None, description="Suggested workaround")


class TeamGenerationResult(BaseModel):
    """Result of LLM-based team generation.

    Wraps the generated TeamConfiguration along with any capability gaps
    and novel archetypes invented by the LLM during generation.
    """

    config: dict[str, Any] = Field(
        ..., description="Generated team configuration (TeamConfiguration-compatible dict)"
    )
    capability_gaps: list[CapabilityGap] = Field(
        default_factory=list, description="Missing capabilities"
    )
    new_archetypes: list[dict[str, Any]] = Field(
        default_factory=list, description="Novel archetypes invented by LLM"
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_blocking_gaps(self) -> bool:
        """True if any capability gap is blocking."""
        return any(g.severity == "blocking" for g in self.capability_gaps)


class TeamGenerator:
    """Generates team configurations dynamically from requirements.

    Given a task description, generates an appropriate team configuration
    by selecting agents, tools, and workflow patterns.

    Usage::

        generator = TeamGenerator()
        config = generator.generate_team("Write a market analysis report")
        agents, engine = generator.build(config, llm_provider)
        result = await engine.execute(agents=agents, initial_state={"task": ...})
    """

    # Pre-defined agent archetypes
    ARCHETYPES: dict[str, dict[str, Any]] = {
        "researcher": {
            "role": "Deep Researcher",
            "system_prompt": (
                "You are a thorough research agent. Search for information, "
                "evaluate source quality, and synthesize findings."
            ),
            "behavior_type": "tool_user",
            "tools": ["web_search"],
        },
        "planner": {
            "role": "Task Planner",
            "system_prompt": (
                "You are a task planner. Decompose the given task into 4-6 "
                "independent sub-tasks that can be executed in parallel. "
                "Each sub-task should be self-contained.\n\n"
                "Respond with ONLY a JSON object in this exact format:\n"
                '{"sub_tasks": [\n'
                '  "Sub-task 1: <title> - <one-sentence scope>",\n'
                '  "Sub-task 2: <title> - <one-sentence scope>",\n'
                "  ...\n"
                "]}"
            ),
            "behavior_type": "orchestrator",
        },
        "writer": {
            "role": "Content Writer",
            "system_prompt": (
                "You are a professional writer. Transform research findings "
                "into clear, well-structured documents."
            ),
            "behavior_type": "llm_only",
        },
        "reviewer": {
            "role": "Quality Reviewer",
            "system_prompt": (
                "You are a quality reviewer. Evaluate documents for accuracy, "
                "completeness, and clarity. Provide specific feedback."
            ),
            "behavior_type": "llm_only",
        },
        "editor": {
            "role": "Task Editor",
            "system_prompt": (
                "You are a task editor. Break down complex tasks into clear "
                "sub-tasks and coordinate agent workflows."
            ),
            "behavior_type": "orchestrator",
        },
        "human_reviewer": {
            "role": "Human Review Gate",
            "system_prompt": "Pause for human review and approval.",
            "behavior_type": "human_gate",
        },
    }

    def generate_team(
        self,
        task_description: str,
        agent_types: list[str] | None = None,
        model: str = "$SMART_LLM",
        include_review: bool = True,
    ) -> dict[str, Any]:
        """Generate a team configuration dict.

        The returned dict is compatible with ``TeamConfiguration`` and can
        be passed directly to :meth:`build` to obtain runnable agents and
        a workflow engine.

        Args:
            task_description: What the team should accomplish
            agent_types: Which agent archetypes to use (default: researcher, writer)
            model: Default LLM model reference
            include_review: Whether to add a review step

        Returns:
            TeamConfiguration-compatible dict
        """
        types = agent_types or ["researcher", "writer"]
        if include_review and "reviewer" not in types:
            types.append("reviewer")

        agents = []
        steps = []
        prev_agent_id: str | None = None

        for i, agent_type in enumerate(types):
            archetype = self.ARCHETYPES.get(agent_type, self.ARCHETYPES["writer"])
            agent_id = f"{agent_type}_{i}" if types.count(agent_type) > 1 else agent_type

            agents.append(
                {
                    "id": agent_id,
                    "role": archetype["role"],
                    "system_prompt": archetype["system_prompt"],
                    "behavior_type": archetype["behavior_type"],
                    "tools": archetype.get("tools", []),
                    "model": model,
                }
            )

            # Build workflow step.
            # When the *previous* agent is an orchestrator, this agent
            # becomes a parallel_fan_out worker (it runs once per
            # parallel_item produced by the orchestrator).
            is_last = i == len(types) - 1
            next_id = (
                types[i + 1]
                if not is_last and types.count(types[i + 1]) <= 1
                else f"{types[i + 1]}_{i + 1}"
                if not is_last
                else None
            )

            prev_is_orchestrator = (
                i > 0
                and self.ARCHETYPES.get(types[i - 1], {}).get("behavior_type") == "orchestrator"
            )

            if prev_is_orchestrator:
                # Fan-out: this agent runs in parallel on each sub-task
                steps.append(
                    {
                        "agent": agent_id,
                        "type": "parallel_fan_out",
                        "next": next_id,
                    }
                )
            elif agent_type == "reviewer" and not is_last:
                steps.append(
                    {
                        "agent": agent_id,
                        "type": "conditional",
                        "next_on_accept": next_id,
                        "next_on_reject": prev_agent_id,
                    }
                )
            else:
                steps.append(
                    {
                        "agent": agent_id,
                        "type": "sequential",
                        "next": next_id,
                    }
                )

            prev_agent_id = agent_id

        return {
            "team_name": f"Generated Team: {task_description[:50]}",
            "description": task_description,
            "agents": agents,
            "workflow": {"steps": steps},
        }

    def generate_team_for_output_type(
        self,
        output_type: str,
        task_description: str,
        model: str = "$SMART_LLM",
        _output_options: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Generate a team configuration from an output type ID (FR-022).

        Delegates to :func:`~hiveflow.core.output_types.route_output` for
        known types.  Returns ``None`` if the output type is unrecognized
        (caller should fall back to LLM generation via
        :meth:`generate_team_from_llm`).

        Args:
            output_type: Output type identifier (e.g., ``"detailed_report"``)
            task_description: What the team should accomplish
            model: Default LLM model reference
            output_options: Per-type options (max_sections, words_per_section, etc.)

        Returns:
            TeamConfiguration-compatible dict, or ``None`` for unknown types
        """
        from hiveflow.core.output_types import route_output

        return route_output(
            output_type,
            task_description,
            model=model,
        )

    async def generate_team_from_llm(
        self,
        task_description: str,
        llm_provider: Any,
        *,
        model: str | None = None,
        tool_registry: Any | None = None,
        archetype_library: Any | None = None,
        auto_approve: bool = False,
    ) -> "TeamGenerationResult":
        """Generate a team configuration using an LLM.

        Builds a structured prompt with the task description, available tool
        registry specs, and archetype library examples, then calls the LLM
        to produce a TeamConfiguration. Validates the result and detects
        capability gaps by comparing requested tools/models against registries.

        Args:
            task_description: What the team should accomplish
            llm_provider: LLM provider instance for generation
            model: Model/deployment name to use (e.g. 'gpt-4o-mini')
            tool_registry: Available tools (for gap detection)
            archetype_library: Available archetypes (for prompt context)
            auto_approve: If True and blocking gaps exist, raise ValueError

        Returns:
            TeamGenerationResult with config, gaps, and new archetypes

        Raises:
            ValueError: If auto_approve=True and blocking gaps detected
        """
        from hiveflow.plugins.llm import LLMConfig, LLMMessage

        # Build context for the LLM prompt
        archetype_examples = ""
        if archetype_library:
            names = (
                archetype_library.list_archetypes()
                if hasattr(archetype_library, "list_archetypes")
                else []
            )
            for name in names[:6]:
                arch = archetype_library.get(name)
                if arch:
                    archetype_examples += (
                        f"  - {name}: {arch.get('role', '')} ({arch.get('behavior_type', '')})\n"
                    )

        available_tools = ""
        if tool_registry and hasattr(tool_registry, "list_tools"):
            for tool_id in tool_registry.list_tools():
                available_tools += f"  - {tool_id}\n"

        prompt = (
            f"Generate a multi-agent team configuration for this task:\n\n"
            f"Task: {task_description}\n\n"
            f"Available archetypes:\n{archetype_examples or '  (none)'}\n\n"
            f"Available tools:\n{available_tools or '  (none)'}\n\n"
            f"Respond with ONLY a JSON object matching TeamConfiguration schema:\n"
            f'{{"team_name": "...", "description": "...", '
            f'"agents": [{{"id": "...", "role": "...", "system_prompt": "...", '
            f'"behavior_type": "llm_only|tool_user|orchestrator|human_gate|action_executor", '
            f'"tools": [...], "model": "$SMART_LLM"}}], '
            f'"workflow": {{"steps": [{{"agent": "...", "type": "sequential|parallel_fan_out|conditional", '
            f'"next": "..."}}]}}}}'
        )

        messages = [LLMMessage(role="user", content=prompt)]
        config = LLMConfig(model=model or "gpt-4o-mini", temperature=0.3)
        response = await llm_provider.chat(messages, config)

        # Parse and validate JSON response
        try:
            import json_repair

            team_config = json_repair.loads(response.content)
        except Exception:
            import json as json_mod

            team_config = json_mod.loads(response.content)

        # Validate against TeamConfiguration schema
        from hiveflow.core.schema import TeamConfiguration

        TeamConfiguration(**team_config)

        # Detect capability gaps
        capability_gaps: list[CapabilityGap] = []
        available_tool_ids = set()
        if tool_registry and hasattr(tool_registry, "list_tools"):
            available_tool_ids = set(tool_registry.list_tools())

        for agent in team_config.get("agents", []):
            for tool_id in agent.get("tools", []):
                if tool_id and tool_id not in available_tool_ids:
                    capability_gaps.append(
                        CapabilityGap(
                            resource_type="tool",
                            resource_id=tool_id,
                            severity="blocking",
                            description=f"Agent '{agent['id']}' requires tool '{tool_id}' which is not registered",
                            fallback_strategy=f"Remove tool requirement or register '{tool_id}'",
                        )
                    )

        # Detect new archetypes
        new_archetypes: list[dict[str, Any]] = []
        known_archetypes = set(self.ARCHETYPES.keys())
        for agent in team_config.get("agents", []):
            agent_id = agent.get("id", "")
            if agent_id and agent_id not in known_archetypes:
                new_archetypes.append(agent)

        result = TeamGenerationResult(
            config=team_config,
            capability_gaps=capability_gaps,
            new_archetypes=new_archetypes,
        )

        # T039: Blocking gap rejection
        if auto_approve and result.has_blocking_gaps:
            gap_details = "; ".join(
                f"{g.resource_type}:{g.resource_id} ({g.severity})"
                for g in result.capability_gaps
                if g.severity == "blocking"
            )
            raise ValueError(f"Cannot auto-approve team with blocking gaps: {gap_details}")

        return result

    def build(
        self,
        config: dict[str, Any],
        llm_provider: Any,
        *,
        model: str | None = None,
        max_tokens: int = 8192,
        enable_summaries: bool = True,
        max_summary_tokens: int = 200,
        summary_threshold: int | None = None,
        tool_registry: Any | None = None,
        skill_registry: Any | None = None,
        enable_context_reducer: bool = False,
        context_reducer_overflow: float = 1.5,
    ) -> tuple[dict[str, Any], Any]:
        """Build runnable agents and a workflow engine from a generated config.

        This is the recommended way to go from ``generate_team()`` output to
        execution.  It handles behavior-type fallback (``tool_user`` without
        registered tools becomes ``llm_only``), wires a
        :class:`SummaryGenerator`, and sets up code-level assembly for
        writer agents.

        Args:
            config: Dict returned by :meth:`generate_team`
            llm_provider: An :class:`LLMProvider` instance
            model: Override model name for all agents (default: use config value)
            max_tokens: Default ``max_tokens`` for each agent's LLM config
            enable_summaries: Whether to create a ``SummaryGenerator``
            max_summary_tokens: Max tokens per summary (output budget)
            summary_threshold: Minimum word count before an agent output is
                summarized.  Outputs shorter than this are passed through to
                downstream agents unchanged.  Default ``None`` preserves
                legacy behavior (threshold equals ``max_summary_tokens``).
            tool_registry: Optional :class:`ToolRegistry` for resolving tool
                IDs declared in agent definitions to :class:`ToolPlugin`
                instances.
            skill_registry: Optional :class:`SkillRegistry` for resolving skill
                names declared in agent definitions to :class:`Skill`
                instances.
            enable_context_reducer: When ``True``, auto-creates a
                :class:`ContextReducer` for agents that have ``context_budget``
                set.  The reducer uses LLM-based waste removal before falling
                back to mechanical truncation.
            context_reducer_overflow: Overflow threshold for the context
                reducer.  Only invokes LLM reduction when context exceeds
                ``context_budget * overflow``.  Default 1.5 (150%).

        Returns:
            ``(agents, engine)`` tuple ready for ``engine.execute(agents=agents, ...)``
        """
        # Import here to avoid circular imports at module level
        from hiveflow.core.summarizer import SummaryGenerator
        from hiveflow.core.tone import ToneCatalog, inject_tone, should_inject_tone
        from hiveflow.core.workflow import WorkflowEngine

        tone_def = None
        raw_tone = config.get("tone")
        if raw_tone is not None:
            catalog = ToneCatalog()
            tone_def = catalog.resolve_from_config(raw_tone)

        # Identify which agents run as parallel_fan_out workers
        fan_out_agent_ids = {
            step_def["agent"]
            for step_def in config["workflow"]["steps"]
            if step_def["type"] == "parallel_fan_out"
        }

        # Source mode routing (FR-sourcemode)
        from hiveflow.core.source_mode import SourceModeRouter

        source_router = SourceModeRouter(
            source_mode=config.get("source_mode"),
            source_options=config.get("source_options"),
        )

        agents = self._build_agents(
            config=config,
            llm_provider=llm_provider,
            model=model,
            max_tokens=max_tokens,
            tool_registry=tool_registry,
            skill_registry=skill_registry,
            enable_context_reducer=enable_context_reducer,
            context_reducer_overflow=context_reducer_overflow,
            fan_out_agent_ids=fan_out_agent_ids,
            source_router=source_router,
            tone_def=tone_def,
            inject_tone=inject_tone,
            should_inject_tone=should_inject_tone,
        )

        steps = self._build_workflow_steps(config)

        # Wire summary propagation and code-level assembly
        summarizer = None
        if enable_summaries:
            summary_model = model or ""
            if not summary_model and config["agents"]:
                summary_model = config["agents"][0].get("model", "")
            summarizer = SummaryGenerator(
                llm_provider=llm_provider,
                model=summary_model,
                max_summary_tokens=max_summary_tokens,
                summary_threshold=summary_threshold,
            )

        writer_ids = [a["id"] for a in config["agents"] if "writer" in a["id"]]

        task_preprocessor = self._build_task_preprocessor(
            config,
            llm_provider,
            model,
        )

        engine = WorkflowEngine(
            steps,
            summarizer=summarizer,
            assembly_agents=writer_ids or None,
            task_preprocessor=task_preprocessor,
        )

        return agents, engine

    def _build_agents(
        self,
        config: dict[str, Any],
        llm_provider: Any,
        *,
        model: str | None,
        max_tokens: int,
        tool_registry: Any | None,
        skill_registry: Any | None,
        enable_context_reducer: bool,
        context_reducer_overflow: float,
        fan_out_agent_ids: set[str],
        source_router: Any,
        tone_def: Any | None,
        inject_tone: Any,
        should_inject_tone: Any,
    ) -> dict[str, Any]:
        """Build Agent instances from config agent definitions."""
        from hiveflow.core.agent import Agent, AgentBehaviorType
        from hiveflow.plugins.llm import LLMConfig, get_llm_registry

        behavior_map = {
            "llm_only": AgentBehaviorType.LLM_ONLY,
            "tool_user": AgentBehaviorType.TOOL_USER,
            "orchestrator": AgentBehaviorType.ORCHESTRATOR,
            "human_gate": AgentBehaviorType.HUMAN_GATE,
            "action_executor": AgentBehaviorType.ACTION_EXECUTOR,
        }

        agents: dict[str, Agent] = {}
        for agent_def in config["agents"]:
            agent_model = model or agent_def.get("model", "")
            # Resolve tier variables like $SMART_LLM, $STRATEGIC_LLM
            if agent_model.startswith("$"):
                from hiveflow.core.config import get_config

                agent_model = get_config().resolve_model(agent_model)
            agent_provider = llm_provider
            if ":" in agent_model:
                try:
                    agent_provider, _resolved_model_name = get_llm_registry().resolve_model(
                        agent_model
                    )
                except (KeyError, ValueError):
                    agent_provider = llm_provider
            raw_behavior = agent_def["behavior_type"]
            behavior = behavior_map.get(raw_behavior, AgentBehaviorType.LLM_ONLY)

            # Resolve tool plugins from the registry when tool IDs are
            # declared in the agent definition.
            agent_tool_ids = agent_def.get("tools", []) or []
            # Apply source mode filtering before tool resolution
            if source_router.is_active:
                agent_tool_ids = source_router.filter_tools(agent_tool_ids)
            resolved_tools = None
            if agent_tool_ids and tool_registry is not None:
                resolved_tools = tool_registry.get_tools_for_agent(agent_tool_ids)

            # Resolve skill instances from the skill registry
            agent_skill_names = agent_def.get("skills", []) or []
            resolved_skills = None
            if agent_skill_names and skill_registry is not None:
                resolved_skills = skill_registry.get_skills(agent_skill_names)

            # Auto-inject SkillActivationTool for tool_user/action_executor
            # agents with skills, enabling on-demand skill loading via the
            # LLM tool-calling loop (progressive disclosure).
            if resolved_skills and behavior in (
                AgentBehaviorType.TOOL_USER,
                AgentBehaviorType.ACTION_EXECUTOR,
            ):
                from hiveflow.plugins.skills.activation_tool import SkillActivationTool

                skill_tool = SkillActivationTool(
                    available_skills={s.name: s for s in resolved_skills},
                )
                if resolved_tools is None:
                    resolved_tools = []
                resolved_tools.append(skill_tool)

            # Graceful fallback: tool_user without registered tool plugins
            # becomes llm_only so the agent can still produce useful output.
            if behavior == AgentBehaviorType.TOOL_USER and not resolved_tools:
                behavior = AgentBehaviorType.LLM_ONLY

            system_prompt = agent_def["system_prompt"]

            # Fan-out workers need to know they are producing one piece of
            # a larger output.
            if agent_def["id"] in fan_out_agent_ids:
                system_prompt += (
                    "\n\nSECTION FORMAT — this section will be merged into "
                    "a larger document by an automated pipeline. A separate "
                    "agent writes the introduction and conclusion for the "
                    "full document.\n\n"
                    "Structure your output exactly as follows:\n"
                    "1. Begin with a markdown heading using your assigned "
                    "item number (e.g. ## 3. Section Title).\n"
                    "2. Write ONLY your assigned section.\n"
                    "3. End on a substantive point (a fact, data, example, "
                    "or analysis). The last paragraph must contain specific "
                    "content, not a restatement of what was covered.\n"
                    "4. Maintain a consistent tone so sections read as a "
                    "unified whole.\n\n"
                    "Omit any of the following — they are handled "
                    "elsewhere:\n"
                    "- Section-level conclusion, summary, or 'in summary' "
                    "paragraph\n"
                    "- Overall document introduction or preamble\n"
                    "- Content that belongs to other sections"
                )

            # Inject tone into text-producing agents (FR-030)
            if tone_def is not None and should_inject_tone(raw_behavior):
                system_prompt = inject_tone(system_prompt, tone_def)

            # Auto-create ContextReducer for agents with context_budget
            agent_context_budget = agent_def.get("context_budget")
            agent_reducer = None
            if enable_context_reducer and agent_context_budget and agent_provider:
                from hiveflow.core.context_reducer import ContextReducer

                agent_reducer = ContextReducer(
                    llm_provider=agent_provider,
                    model=agent_model,
                    overflow_threshold=context_reducer_overflow,
                )

            agents[agent_def["id"]] = Agent(
                agent_id=agent_def["id"],
                role=agent_def["role"],
                system_prompt=system_prompt,
                behavior_type=behavior,
                tools=resolved_tools,
                model=agent_model,
                llm_provider=agent_provider,
                llm_config=LLMConfig(model=agent_model, max_tokens=max_tokens),
                action_policy=agent_def.get("action_policy"),
                output_type=agent_def.get("output_type"),
                context_recency_window=agent_def.get("context_recency_window", 0),
                context_budget=agent_context_budget,
                context_reducer=agent_reducer,
                skills=resolved_skills,
            )

        return agents

    @staticmethod
    def _build_workflow_steps(config: dict[str, Any]) -> list:
        """Build WorkflowStep instances from config."""
        from hiveflow.core.workflow import WorkflowStep

        steps = []
        for step_def in config["workflow"]["steps"]:
            steps.append(
                WorkflowStep(
                    agent=step_def["agent"],
                    step_type=step_def["type"],
                    next_step=step_def.get("next"),
                    next_on_accept=step_def.get("next_on_accept"),
                    next_on_reject=step_def.get("next_on_reject"),
                    max_iterations=step_def.get("max_iterations", 3),
                    gate_id=step_def.get("gate_id"),
                    gate_description=step_def.get("gate_description"),
                    context_ttl=step_def.get("context_ttl"),
                    source=step_def.get("source"),
                )
            )
        return steps

    @staticmethod
    def _build_task_preprocessor(
        config: dict[str, Any],
        llm_provider: Any,
        model: str | None,
    ) -> Any | None:
        """Build TaskPreprocessor if configured."""
        preprocessing_cfg = config.get("preprocessing")
        if isinstance(preprocessing_cfg, dict):
            from hiveflow.core.preprocessing import PreprocessingConfig, TaskPreprocessor

            pp_config = PreprocessingConfig(**preprocessing_cfg)
            pp_model = model or ""
            if not pp_model and config["agents"]:
                pp_model = config["agents"][0].get("model", "")
            return TaskPreprocessor(
                llm_provider=llm_provider,
                model=pp_model,
                config=pp_config,
            )
        elif preprocessing_cfg is None:
            # Auto-create preprocessor with defaults (zero-config)
            from hiveflow.core.preprocessing import TaskPreprocessor

            pp_model = model or ""
            if not pp_model and config["agents"]:
                pp_model = config["agents"][0].get("model", "")
            if llm_provider is not None:
                return TaskPreprocessor(
                    llm_provider=llm_provider,
                    model=pp_model,
                )
        return None
