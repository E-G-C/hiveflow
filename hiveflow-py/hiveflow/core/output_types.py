"""Output type routing — models and registry.

Defines the data models for output type routing (FR-021–FR-027) and the
OutputTypeRegistry that maps output type IDs to pipeline shapes and prompt
template sets.  Includes the standalone ``route_output()`` function for
routing an output type to a TeamConfiguration-compatible dict.
"""

from enum import StrEnum
from pathlib import Path
from typing import Any

import structlog
import yaml
from pydantic import BaseModel, Field

logger = structlog.get_logger()


class OutputOptions(BaseModel):
    """Per-output-type configuration parameters (FR-026)."""

    max_sections: int | None = Field(default=None, description="Maximum number of content sections")
    words_per_section: int | None = Field(default=None, description="Target words per section")
    include_introduction: bool = Field(default=True, description="Include introduction section")
    include_conclusion: bool = Field(default=True, description="Include conclusion section")
    include_table_of_contents: bool = Field(default=True, description="Include table of contents")


class CitationsConfig(BaseModel):
    """Citation behavior control (FR-027)."""

    enabled: bool = Field(default=True, description="Enable citation tracking")
    style: str = Field(default="apa", description="Citation format style")
    inline: bool = Field(default=True, description="Include inline citations in text")
    generate_reference_section: bool = Field(
        default=True, description="Generate references section in output"
    )


class PromptTemplateSet(BaseModel):
    """Prompts associated with an output type (FR-023).

    Each field is an optional prompt template string. When set, it overrides
    the default prompt for that pipeline stage.
    """

    query_generation: str | None = Field(
        default=None, description="How sub-queries are derived from the main topic"
    )
    writing: str | None = Field(
        default=None,
        description="Structure, length, and style instructions for writers",
    )
    review: str | None = Field(default=None, description="Quality criteria for reviewers")
    action: str | None = Field(default=None, description="Guidelines for action-executing agents")
    introduction: str | None = Field(default=None, description="Opening section generation prompt")
    conclusion: str | None = Field(default=None, description="Closing section generation prompt")


class OutputTypeId(StrEnum):
    """Built-in output type identifiers (FR-021)."""

    DETAILED_REPORT = "detailed_report"
    QUICK_REPORT = "quick_report"
    OUTLINE = "outline"
    RESOURCE_LIST = "resource_list"
    DEEP_RESEARCH = "deep_research"
    DECISION_RECORD = "decision_record"
    ACTION_PLAN = "action_plan"
    CODE_ARTIFACT = "code_artifact"
    INCIDENT_REPORT = "incident_report"
    CUSTOM = "custom"


class OutputTypeDefinition(BaseModel):
    """A registered output type with its pipeline configuration (FR-021).

    Each output type maps to a pipeline shape (agent sequence) and a set of
    prompt templates that govern agent behavior for that deliverable type.
    """

    type_id: str = Field(description="Unique output type identifier")
    label: str = Field(description="Human-readable name")
    description: str = Field(default="", description="What this type produces")
    pipeline_shape: list[str] = Field(
        description=(
            "Ordered pipeline step types "
            "(e.g., ['decompose', 'collect', 'evaluate', 'produce', 'emit'])"
        )
    )
    prompt_template_set: PromptTemplateSet = Field(
        default_factory=PromptTemplateSet,
        description="Prompts for each pipeline stage",
    )
    default_output_options: OutputOptions = Field(
        default_factory=OutputOptions,
        description="Default options for this output type",
    )


# ---------------------------------------------------------------------------
# Built-in output type definitions
# ---------------------------------------------------------------------------

_BUILTIN_OUTPUT_TYPES: list[OutputTypeDefinition] = [
    OutputTypeDefinition(
        type_id=OutputTypeId.DETAILED_REPORT,
        label="Detailed Report",
        description="Long-form report with sections; citations optional",
        pipeline_shape=["decompose", "collect", "evaluate", "produce", "emit"],
        prompt_template_set=PromptTemplateSet(
            query_generation=(
                "Decompose the topic into 4-8 independent sub-topics that "
                "together provide comprehensive coverage. Each sub-topic "
                "should be researchable independently."
            ),
            writing=(
                "Write a detailed, well-structured section of 600-1000 words. "
                "Use clear headings, evidence-based arguments, and cite "
                "sources inline. Maintain an objective, analytical tone."
            ),
            review=(
                "Evaluate for factual accuracy, logical coherence, source "
                "quality, and completeness. Flag unsupported claims and "
                "gaps in coverage."
            ),
            introduction=(
                "Write a concise introduction that frames the topic, states "
                "the scope, and previews the structure of the report."
            ),
            conclusion=(
                "Synthesize the key findings across all sections. Highlight "
                "implications and suggest areas for further investigation."
            ),
        ),
        default_output_options=OutputOptions(
            max_sections=8,
            words_per_section=800,
        ),
    ),
    OutputTypeDefinition(
        type_id=OutputTypeId.QUICK_REPORT,
        label="Quick Report",
        description="Short summary; 1–2 pages",
        pipeline_shape=["collect", "produce"],
        prompt_template_set=PromptTemplateSet(
            query_generation=(
                "Identify the 2-3 most important aspects of this topic "
                "that can be summarized briefly."
            ),
            writing=(
                "Write a concise summary in 300-500 words. Lead with the "
                "key takeaway, then provide supporting details. Use short "
                "paragraphs and bullet points where appropriate."
            ),
            introduction=("Open with a single sentence stating what this summary covers."),
            conclusion=("End with a brief 'bottom line' statement."),
        ),
        default_output_options=OutputOptions(
            max_sections=3,
            words_per_section=400,
            include_table_of_contents=False,
        ),
    ),
    OutputTypeDefinition(
        type_id=OutputTypeId.OUTLINE,
        label="Outline",
        description="Bullet-point outline with sources",
        pipeline_shape=["collect"],
        prompt_template_set=PromptTemplateSet(
            query_generation=(
                "Identify the main themes and sub-themes for a structured outline of this topic."
            ),
            writing=(
                "Produce a hierarchical bullet-point outline. Use top-level "
                "bullets for major sections and nested bullets for sub-points. "
                "Annotate each point with its source."
            ),
        ),
        default_output_options=OutputOptions(
            include_introduction=False,
            include_conclusion=False,
            include_table_of_contents=False,
        ),
    ),
    OutputTypeDefinition(
        type_id=OutputTypeId.RESOURCE_LIST,
        label="Resource List",
        description="Curated list of sources with summaries",
        pipeline_shape=["collect"],
        prompt_template_set=PromptTemplateSet(
            query_generation=(
                "Search broadly for the most authoritative and diverse sources on this topic."
            ),
            writing=(
                "For each resource, provide: title, URL/reference, a 2-3 "
                "sentence summary of its content, and a relevance rating "
                "(high/medium/low). Group resources by sub-topic."
            ),
        ),
        default_output_options=OutputOptions(
            include_introduction=False,
            include_conclusion=False,
            include_table_of_contents=False,
        ),
    ),
    OutputTypeDefinition(
        type_id=OutputTypeId.DEEP_RESEARCH,
        label="Deep Research",
        description="Exhaustive multi-branch exploration",
        pipeline_shape=["decompose", "collect", "evaluate", "collect", "produce"],
        prompt_template_set=PromptTemplateSet(
            query_generation=(
                "Perform multi-level decomposition: break the topic into "
                "major branches, then break each branch into specific "
                "research questions. Aim for 6-10 branches total."
            ),
            writing=(
                "Write an exhaustive analysis of 1000-1500 words per section. "
                "Cover all angles: historical context, current state, "
                "competing viewpoints, and evidence quality. Cite all sources."
            ),
            review=(
                "Critically evaluate evidence quality, identify gaps in "
                "coverage, and flag areas needing deeper investigation. "
                "Check for contradictory findings across sources."
            ),
            introduction=(
                "Provide a research overview: scope, methodology, and the "
                "key questions being investigated."
            ),
            conclusion=(
                "Present a synthesis of findings with confidence levels. "
                "Identify open questions and recommend next research steps."
            ),
        ),
        default_output_options=OutputOptions(
            max_sections=10,
            words_per_section=1200,
        ),
    ),
    OutputTypeDefinition(
        type_id=OutputTypeId.DECISION_RECORD,
        label="Decision Record",
        description="Structured decision with evidence",
        pipeline_shape=["decompose", "collect", "evaluate", "produce"],
        prompt_template_set=PromptTemplateSet(
            query_generation=(
                "Identify the decision context, the options under "
                "consideration, and the criteria for evaluation."
            ),
            writing=(
                "Structure the output as: Context, Options Considered, "
                "Evaluation Criteria, Analysis per Option, Recommended "
                "Decision, and Consequences. Be objective and evidence-based."
            ),
            review=(
                "Verify that all options are fairly evaluated, criteria "
                "are consistently applied, and the recommendation follows "
                "logically from the analysis."
            ),
        ),
        default_output_options=OutputOptions(
            max_sections=6,
            words_per_section=600,
            include_table_of_contents=False,
        ),
    ),
    OutputTypeDefinition(
        type_id=OutputTypeId.ACTION_PLAN,
        label="Action Plan",
        description="Step-by-step executable plan",
        pipeline_shape=["decompose", "collect", "evaluate"],
        prompt_template_set=PromptTemplateSet(
            query_generation=(
                "Break the objective into concrete, sequenceable action "
                "items with clear ownership and dependencies."
            ),
            writing=(
                "For each action item provide: step number, description, "
                "responsible party (if applicable), prerequisites, expected "
                "outcome, and estimated effort. Use a numbered list format."
            ),
            review=(
                "Check that steps are in the correct order, dependencies "
                "are satisfied, and no critical steps are missing. Verify "
                "the plan is actionable without ambiguity."
            ),
            action=(
                "Execute each action step sequentially. Report status and blockers for each step."
            ),
        ),
        default_output_options=OutputOptions(
            include_introduction=True,
            include_conclusion=False,
            include_table_of_contents=False,
        ),
    ),
    OutputTypeDefinition(
        type_id=OutputTypeId.CODE_ARTIFACT,
        label="Code Artifact",
        description="Generated and tested code",
        pipeline_shape=["produce", "evaluate", "produce", "emit"],
        prompt_template_set=PromptTemplateSet(
            writing=(
                "Generate clean, well-documented code that follows "
                "established conventions. Include type hints, docstrings, "
                "and inline comments for complex logic."
            ),
            review=(
                "Review for correctness, edge cases, security issues, "
                "performance, and adherence to coding standards. Suggest "
                "specific improvements with code examples."
            ),
            action=(
                "Run the generated code, execute tests, and report results. "
                "Fix any failures before marking complete."
            ),
        ),
        default_output_options=OutputOptions(
            include_introduction=False,
            include_conclusion=False,
            include_table_of_contents=False,
        ),
    ),
    OutputTypeDefinition(
        type_id=OutputTypeId.INCIDENT_REPORT,
        label="Incident Report",
        description="Post-mortem with timeline and RCA",
        pipeline_shape=["collect", "produce", "evaluate", "emit"],
        prompt_template_set=PromptTemplateSet(
            query_generation=(
                "Gather all relevant facts: timeline of events, systems "
                "affected, actions taken, and contributing factors."
            ),
            writing=(
                "Structure as: Executive Summary, Incident Timeline, "
                "Impact Assessment, Root Cause Analysis, Contributing "
                "Factors, Remediation Actions, and Lessons Learned. "
                "Use precise timestamps and factual language."
            ),
            review=(
                "Verify the timeline is accurate and complete, the root "
                "cause analysis is supported by evidence, and remediation "
                "actions address all contributing factors."
            ),
        ),
        default_output_options=OutputOptions(
            max_sections=7,
            words_per_section=500,
        ),
    ),
    OutputTypeDefinition(
        type_id=OutputTypeId.CUSTOM,
        label="Custom",
        description="Fully custom team config provided by the user",
        pipeline_shape=[],
    ),
]


class OutputTypeRegistry:
    """Registry of output type definitions (FR-022).

    Resolves output type IDs to their definitions containing pipeline shapes
    and prompt template sets.
    """

    def __init__(self) -> None:
        """Initialize with all built-in output types pre-registered."""
        self._types: dict[str, OutputTypeDefinition] = {}
        for defn in _BUILTIN_OUTPUT_TYPES:
            self._types[defn.type_id] = defn

    def resolve(self, output_type: str) -> OutputTypeDefinition | None:
        """Resolve an output type by ID.

        Returns the definition or ``None`` if not found.
        """
        return self._types.get(output_type)

    def register(self, defn: OutputTypeDefinition) -> None:
        """Register a custom output type (overrides built-in on ID collision)."""
        self._types[defn.type_id] = defn

    def list_types(self) -> list[str]:
        """Return all registered output type IDs."""
        return list(self._types.keys())

    def load_from_yaml(self, path: str | Path) -> OutputTypeDefinition:
        """Load and register an output type definition from a YAML file.

        The YAML file should contain fields matching
        :class:`OutputTypeDefinition` (type_id, label, pipeline_shape, etc.).

        Args:
            path: Path to the YAML file.

        Returns:
            The loaded and registered definition.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If the YAML content is invalid.
        """
        file_path = Path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"Output type file not found: {file_path}")

        with open(file_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not isinstance(data, dict):
            raise ValueError(f"Expected a YAML mapping in {file_path}")

        defn = OutputTypeDefinition.model_validate(data)
        self.register(defn)
        logger.debug("Loaded output type '%s' from %s", defn.type_id, file_path)
        return defn

    def load_from_directory(self, directory: str | Path) -> list[OutputTypeDefinition]:
        """Load all output type definitions from YAML files in a directory.

        Files must have ``.yaml`` or ``.yml`` extensions.

        Args:
            directory: Path to directory containing YAML definition files.

        Returns:
            List of loaded definitions.
        """
        dir_path = Path(directory)
        if not dir_path.is_dir():
            logger.warning("Output type directory not found: %s", dir_path)
            return []

        loaded: list[OutputTypeDefinition] = []
        for file_path in sorted(dir_path.glob("*.y*ml")):
            try:
                defn = self.load_from_yaml(file_path)
                loaded.append(defn)
            except (ValueError, FileNotFoundError, yaml.YAMLError) as exc:
                logger.warning("Failed to load output type from %s: %s", file_path, exc)

        return loaded


# ---------------------------------------------------------------------------
# Standalone routing function
# ---------------------------------------------------------------------------


def route_output(
    output_type: str,
    task_description: str,
    *,
    config: dict[str, Any] | None = None,
    registry: OutputTypeRegistry | None = None,
    model: str = "$SMART_LLM",
) -> dict[str, Any] | None:
    """Route an output type to a TeamConfiguration-compatible dict.

    Implements the routing logic from the output pipeline spec::

        1. If output_type is in the registry → generate team from definition
        2. If output_type is "custom" → return config["custom_team"]
        3. If unknown → return None (caller should use LLM fallback)

    Args:
        output_type: Output type identifier (e.g. ``"detailed_report"``).
        task_description: What the team should accomplish.
        config: Optional configuration dict.  When *output_type* is
            ``"custom"``, this should contain a ``"custom_team"`` key.
        registry: An :class:`OutputTypeRegistry` instance.  A default
            registry (built-in types only) is created when ``None``.
        model: Default LLM model reference for generated agents.

    Returns:
        A TeamConfiguration-compatible dict, or ``None`` when the output
        type is unknown (caller should fall back to LLM generation via
        :meth:`~hiveflow.core.teams.TeamGenerator.generate_team_from_llm`).
    """
    if registry is None:
        registry = OutputTypeRegistry()

    config = config or {}

    # Custom type: caller provides full config
    if output_type == OutputTypeId.CUSTOM:
        custom_team = config.get("custom_team")
        if custom_team:
            return custom_team
        logger.warning("output_type is 'custom' but no 'custom_team' in config")
        return None

    defn = registry.resolve(output_type)
    if defn is None:
        logger.info(
            "Unknown output_type '%s'; available: %s. Caller should use LLM fallback.",
            output_type,
            ", ".join(registry.list_types()),
        )
        return None

    # Map pipeline shape to agent archetypes
    from hiveflow.core.teams import TeamGenerator

    generator = TeamGenerator()
    shape_to_agents: dict[str, str] = {
        "decompose": "planner",
        "collect": "researcher",
        "evaluate": "reviewer",
        "produce": "writer",
        "emit": "editor",
    }

    agent_types = []
    for step in defn.pipeline_shape:
        archetype = shape_to_agents.get(step)
        if archetype:
            agent_types.append(archetype)

    if not agent_types:
        agent_types = ["researcher", "writer"]

    team_config = generator.generate_team(
        task_description=task_description,
        agent_types=agent_types,
        model=model,
        include_review=False,
    )

    # Attach prompt template set to the config for downstream consumption
    team_config["prompt_template_set"] = defn.prompt_template_set.model_dump(
        exclude_none=True,
    )
    team_config["output_type"] = defn.type_id
    team_config["default_output_options"] = defn.default_output_options.model_dump()

    return team_config
