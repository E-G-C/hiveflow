"""Team Configuration Schema - JSON schema for team definitions.

This module defines Pydantic models for team configurations that govern
multi-agent workflows.
"""

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from hiveflow.core.agent import AgentBehaviorType


class WorkflowStepType(StrEnum):
    """Types of workflow steps."""

    SEQUENTIAL = "sequential"
    PARALLEL_FAN_OUT = "parallel_fan_out"
    CONDITIONAL = "conditional"
    HUMAN_GATE = "human_gate"
    GATED = "gated"
    SUB_WORKFLOW = "sub_workflow"


# Backwards-compatible alias -- consolidated to AgentBehaviorType from agent.py
AgentBehaviorTypeSchema = AgentBehaviorType


class DocumentMode(StrEnum):
    """Per-agent document delivery modes."""

    FULL = "full"
    RELEVANT_CHUNKS = "relevant_chunks"
    SUMMARY = "summary"
    METADATA_ONLY = "metadata_only"
    NONE = "none"


class OutputType(StrEnum):
    """Agent output types for differential compression.

    The summary budget multiplier varies by type:
    - reasoning: 2.0x  (reasoning traces have long-term strategic value)
    - structured_data: 2.0x  (planning decisions inform downstream work)
    - data: 0.5x  (data outputs are locally relevant, aggressively compressed)
    - side_effect: 0.5x  (action confirmations need minimal detail)
    - text, composite: 1.0x  (standard budget)
    """

    TEXT = "text"
    REASONING = "reasoning"
    STRUCTURED_DATA = "structured_data"
    DATA = "data"
    SIDE_EFFECT = "side_effect"
    COMPOSITE = "composite"


# Default output type mapping from behavior type
_BEHAVIOR_OUTPUT_DEFAULTS: dict[str, str] = {
    "llm_only": "text",
    "tool_user": "text",
    "orchestrator": "structured_data",
    "human_gate": "text",
    "action_executor": "side_effect",
}


class BudgetPolicy(StrEnum):
    """Budget propagation policies for collaboration."""

    INHERIT_PARENT = "inherit_parent"
    FIXED = "fixed"
    UNLIMITED = "unlimited"


class CollaborationConfig(BaseModel):
    """Configuration for dynamic agent collaboration.

    Controls delegation, spawning, messaging, and budget enforcement
    when collaboration is enabled on a team.
    """

    enabled: bool = Field(
        default=False,
        description="Whether dynamic collaboration tools are injected into orchestrator agents",
    )
    max_delegation_depth: int = Field(
        default=3,
        ge=1,
        description="Maximum nesting depth for delegation chains",
    )
    max_spawned_agents: int = Field(
        default=10,
        ge=1,
        description="Maximum agents that can be spawned per workflow execution",
    )
    allow_recursive_orchestrators: bool = Field(
        default=False,
        description="Whether spawned agents can themselves be orchestrators",
    )
    delegation_timeout_seconds: int = Field(
        default=300,
        ge=1,
        description="Maximum time (seconds) for a single delegation to complete",
    )
    budget_policy: BudgetPolicy = Field(
        default=BudgetPolicy.INHERIT_PARENT,
        description="Budget propagation: inherit_parent, fixed, or unlimited",
    )
    fixed_budget_tokens: int | None = Field(
        default=None,
        description="Token budget per child when budget_policy is 'fixed'",
    )

    @model_validator(mode="after")
    def validate_fixed_budget(self) -> "CollaborationConfig":
        """Validate fixed_budget_tokens is set when budget_policy is 'fixed'."""
        if self.budget_policy == BudgetPolicy.FIXED and self.fixed_budget_tokens is None:
            raise ValueError("fixed_budget_tokens is required when budget_policy is 'fixed'")
        if self.fixed_budget_tokens is not None and self.fixed_budget_tokens <= 0:
            raise ValueError("fixed_budget_tokens must be positive")
        return self


class ModelRequirements(BaseModel):
    """Declarative model requirements for agent model selection."""

    cost_tier: Literal["fast", "smart", "strategic"] | None = Field(
        default=None,
        description="Cost tier: fast, smart, or strategic",
    )
    supports_tools: bool | None = Field(
        default=None,
        description="Requires tool/function calling support",
    )
    supports_vision: bool | None = Field(
        default=None,
        description="Requires vision/multimodal support",
    )
    strengths: list[str] = Field(
        default_factory=list,
        description="Desired capabilities (e.g., 'reasoning', 'coding')",
    )


class AgentDefinition(BaseModel):
    """Definition of an agent in a team configuration."""

    id: str = Field(..., description="Unique identifier for this agent")
    role: str = Field(..., description="Human-readable role description")
    system_prompt: str = Field(..., description="System prompt defining agent's behavior")
    behavior_type: AgentBehaviorTypeSchema = Field(
        ..., description="How the agent executes its task"
    )
    tools: list[str] = Field(default_factory=list, description="List of tool IDs")
    skills: list[str] = Field(
        default_factory=list,
        description="List of skill names to make available to this agent",
    )
    model: str = Field(
        default="$SMART_LLM", description="Model reference (supports tier variables)"
    )
    max_tokens: int | None = Field(
        default=None,
        description="Per-agent max output tokens. None = use global default.",
    )
    documents: list[str] | None = Field(
        default=None,
        description="Document names this agent receives. None = all, [] = none.",
    )
    document_mode: DocumentMode = Field(
        default=DocumentMode.NONE,
        description="How document content is delivered: full, relevant_chunks, summary, metadata_only, none",
    )
    max_document_tokens: int | None = Field(
        default=None,
        description="Per-agent document token budget. None = use global default.",
    )
    action_policy: Literal["auto", "require_approval", "dry_run", "confirm_on_error"] | None = (
        Field(
            default=None,
            description="Safety policy for action_executor: 'auto' or 'require_approval'",
        )
    )
    model_requirements: ModelRequirements | None = Field(
        default=None,
        description="Declarative model requirements for automatic model selection",
    )
    output_type: OutputType | None = Field(
        default=None,
        description="Expected output type for differential compression: "
        "text, reasoning, structured_data, data, side_effect, composite. "
        "Inferred from behavior_type if None.",
    )
    context_recency_window: int = Field(
        default=0,
        ge=0,
        description="Sliding window for prior agent summaries. When >0, only "
        "the N most recent summaries are included fully in downstream context; "
        "older ones are collapsed into a placeholder. 0 = include all.",
    )
    context_budget: int | None = Field(
        default=None,
        description="Max words of assembled context passed to this agent. None = no limit.",
    )
    on_failure: Literal["fail", "retry", "skip"] | None = Field(
        default=None,
        description="Failure policy: 'fail' (default when None), 'retry', or 'skip'",
    )
    max_retries: int = Field(
        default=1,
        ge=1,
        description="Max retry attempts when on_failure='retry'",
    )
    rollback_on_failure: bool = Field(
        default=False,
        description="Whether to trigger rollback on downstream failure",
    )
    rollback_action: str | None = Field(
        default=None,
        description="Tool ID to invoke for rollback",
    )

    @field_validator("on_failure")
    @classmethod
    def validate_on_failure(cls, v: str | None) -> str | None:
        """Validate on_failure values."""
        if v is not None and v not in ("fail", "retry", "skip"):
            raise ValueError("on_failure must be one of: 'fail', 'retry', 'skip'")
        return v

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        """Validate agent ID format."""
        if not v or not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Agent ID must be alphanumeric with optional _ or -")
        return v

    @field_validator("system_prompt")
    @classmethod
    def validate_system_prompt(cls, v: str) -> str:
        """Validate system prompt is not empty."""
        if not v.strip():
            raise ValueError("System prompt cannot be empty")
        return v

    @field_validator("max_document_tokens")
    @classmethod
    def validate_max_document_tokens(cls, v: int | None) -> int | None:
        """Validate max_document_tokens is positive if set."""
        if v is not None and v <= 0:
            raise ValueError("max_document_tokens must be positive")
        return v

    @model_validator(mode="after")
    def validate_action_executor_policy(self) -> "AgentDefinition":
        """Validate action_policy is set iff behavior_type is action_executor."""
        if self.behavior_type == AgentBehaviorTypeSchema.ACTION_EXECUTOR:
            if self.action_policy is None:
                raise ValueError(
                    "action_policy is required when behavior_type is 'action_executor'"
                )
        elif self.action_policy is not None:
            raise ValueError(
                "action_policy must be None when behavior_type is not 'action_executor'"
            )
        return self

    def get_output_type(self) -> str:
        """Get the effective output type, inferring from behavior_type if not set."""
        if self.output_type is not None:
            return self.output_type
        return _BEHAVIOR_OUTPUT_DEFAULTS.get(self.behavior_type.value, "text")


class WorkflowStepDefinition(BaseModel):
    """Definition of a workflow step."""

    agent: str = Field(..., description="ID of the agent executing this step")
    type: WorkflowStepType = Field(..., description="Type of workflow step")
    next: str | None = Field(None, description="Next step for sequential execution")
    next_on_accept: str | None = Field(None, description="Next step if conditional accepts")
    next_on_reject: str | None = Field(None, description="Next step if conditional rejects")
    max_iterations: int | None = Field(
        default=None,
        description="Per-step iteration limit for conditional loops (default: 3)",
    )
    gate_id: str | None = Field(
        default=None,
        description="Unique gate identifier (required when type=gated)",
    )
    gate_description: str | None = Field(
        default=None,
        description="Human-readable gate context (for gated steps)",
    )
    team: str | None = Field(
        default=None,
        description="Team name for sub_workflow steps",
    )
    input_mapping: dict[str, str] | None = Field(
        default=None,
        description="Outer-to-inner state key mapping for sub_workflow",
    )
    output_mapping: dict[str, str] | None = Field(
        default=None,
        description="Inner-to-outer state key mapping for sub_workflow",
    )
    context_ttl: int | None = Field(
        default=None,
        description="Context time-to-live: number of downstream steps this agent's "
        "summary remains visible. None = never expires.",
    )

    @model_validator(mode="after")
    def validate_step_transitions(self) -> "WorkflowStepDefinition":
        """Validate step transitions based on type."""
        if self.type == WorkflowStepType.SEQUENTIAL:
            if self.next is None:
                # Last step in workflow - OK
                pass
        elif self.type == WorkflowStepType.CONDITIONAL and (
            self.next_on_accept is None or self.next_on_reject is None
        ):
            raise ValueError("Conditional steps must define next_on_accept and next_on_reject")
        elif self.type == WorkflowStepType.GATED and self.gate_id is None:
            raise ValueError("Gated steps must define gate_id")
        elif self.type == WorkflowStepType.SUB_WORKFLOW and self.team is None:
            raise ValueError("sub_workflow steps must define 'team'")
        return self


class AgentIOMapping(BaseModel):
    """Defines what state keys an agent reads and writes."""

    reads: list[str] = Field(default_factory=list, description="State keys agent reads")
    writes: list[str] = Field(default_factory=list, description="State keys agent writes")


class StateSchema(BaseModel):
    """Schema defining workflow state structure."""

    required_keys: list[str] = Field(
        default_factory=list, description="Required state keys for workflow"
    )
    agent_io: dict[str, AgentIOMapping] = Field(
        default_factory=dict, description="Agent I/O mappings"
    )
    enforcement_mode: str = Field(
        default="warn",
        description="State enforcement mode: warn, strict, or off",
    )

    @field_validator("enforcement_mode")
    @classmethod
    def validate_enforcement_mode(cls, v: str) -> str:
        """Validate enforcement_mode values."""
        if v not in ("warn", "strict", "off"):
            raise ValueError("enforcement_mode must be one of: warn, strict, off")
        return v


class WorkflowGraph(BaseModel):
    """Workflow graph definition."""

    steps: list[WorkflowStepDefinition] = Field(
        ..., description="List of workflow steps in execution order"
    )

    @field_validator("steps")
    @classmethod
    def validate_steps_not_empty(
        cls, v: list[WorkflowStepDefinition]
    ) -> list[WorkflowStepDefinition]:
        """Validate steps list is not empty."""
        if not v:
            raise ValueError("Workflow must have at least one step")
        return v


class ScoringWeights(BaseModel):
    """Signal weights for source curation scoring."""

    domain_authority: float = Field(default=0.25, description="Weight for domain authority signal")
    content_relevance: float = Field(
        default=0.30, description="Weight for content relevance signal"
    )
    freshness: float = Field(default=0.15, description="Weight for freshness signal")
    llm_judgment: float = Field(default=0.30, description="Weight for LLM judgment signal")


class CitationConfig(BaseModel):
    """Configuration for citation tracking in workflow output."""

    enabled: bool = Field(default=False, description="Activate citation tracking")
    style: str = Field(
        default="apa",
        description="Citation format: apa, numbered, inline, mla, chicago",
    )
    inline: bool = Field(default=True, description="Include inline [source](url) references")
    generate_reference_section: bool = Field(
        default=True, description="Append reference list to output"
    )


class SourceCurationConfig(BaseModel):
    """Configuration for source curation pipeline."""

    enabled: bool = Field(default=False, description="Activate source curation")
    min_score: float = Field(default=0.4, description="Minimum composite score to pass")
    max_sources: int = Field(default=10, description="Maximum URLs to deep-scrape")
    freshness_max_age_days: int = Field(
        default=730, description="Penalize content older than this many days"
    )
    domain_allow_list: list[str] = Field(
        default_factory=list, description="Domains that receive a boosted authority score"
    )
    domain_block_list: list[str] = Field(
        default_factory=list, description="Domains that receive authority score of 0"
    )
    scoring_weights: ScoringWeights = Field(
        default_factory=ScoringWeights, description="Signal weights for composite scoring"
    )


class VectorStoreConfig(BaseModel):
    """Configuration for vector store backend."""

    backend: str = Field(default="memory", description="Vector store plugin ID")
    collection_prefix: str = Field(default="workflow_", description="Namespace prefix")
    persist: bool = Field(default=False, description="Survive across workflow runs")
    similarity_metric: str = Field(default="cosine", description="Distance metric")


class PublishConfig(BaseModel):
    """Configuration for publishing workflow results."""

    formats: list[str] = Field(
        default_factory=list, description="Output formats (e.g., markdown, pdf, docx, html, json)"
    )
    layout: str = Field(default="default", description="Layout template name")
    style: str | None = Field(
        default=None,
        description="Reserved for future use: style name for PDF/HTML (CSS or LaTeX template)",
    )
    output_dir: str = Field(default="./output", description="Output directory path")
    filename: str = Field(default="output", description="Base filename without extension")


class TeamConfiguration(BaseModel):
    """Complete team configuration schema."""

    team_name: str = Field(..., description="Unique name for this team configuration")
    description: str = Field(..., description="Description of what this team does")
    agents: list[AgentDefinition] = Field(..., description="List of agent definitions")
    workflow: WorkflowGraph = Field(..., description="Workflow execution graph")
    state_schema: StateSchema | None = Field(None, description="Optional state schema definition")
    publish: PublishConfig | None = Field(None, description="Optional publishing configuration")
    citations: CitationConfig | None = Field(
        None, description="Optional citation tracking configuration"
    )
    source_curation: SourceCurationConfig | None = Field(
        None, description="Optional source curation pipeline configuration"
    )
    vector_store: VectorStoreConfig | None = Field(
        None, description="Optional vector store backend configuration"
    )
    mcp_strategy: Literal["disabled", "fast", "deep"] | None = Field(
        None,
        description="Override MCP strategy for this team (None = use global config)",
    )
    pipeline_output_type: str | None = Field(
        None,
        description=(
            "Output type for pipeline routing "
            "(e.g., 'detailed_report', 'quick_report', 'outline'). "
            "When set, selects the pipeline shape and prompt template set."
        ),
    )
    output_options: dict[str, Any] | None = Field(
        None,
        description=(
            "Per-output-type options (e.g., max_sections, words_per_section, include_introduction)"
        ),
    )
    tone: str | dict[str, Any] | None = Field(
        None,
        description=(
            "Tone for text-producing agents. "
            "String (built-in tone_id) or dict (inline ToneDefinition)."
        ),
    )
    collaboration: CollaborationConfig | None = Field(
        None,
        description="Optional dynamic collaboration configuration",
    )
    source_mode: str | None = Field(
        None,
        description=(
            "Source mode controlling which retrieval pipelines are active. "
            "One of: web, local, hybrid, cloud, mcp, custom. "
            "None = no source-mode routing (all tools available)."
        ),
    )
    source_options: dict[str, Any] | None = Field(
        None,
        description=(
            "Per-mode source configuration. Keys: web, local, cloud, "
            "custom_plugins. See SourceOptions model for structure."
        ),
    )

    @field_validator("source_mode")
    @classmethod
    def validate_source_mode(cls, v: str | None) -> str | None:
        """Validate source_mode is a recognized value."""
        valid = {"web", "local", "hybrid", "cloud", "mcp", "custom"}
        if v is not None and v not in valid:
            raise ValueError(f"source_mode must be one of {sorted(valid)}, got '{v}'")
        return v

    @field_validator("agents")
    @classmethod
    def validate_agents_not_empty(cls, v: list[AgentDefinition]) -> list[AgentDefinition]:
        """Validate agents list is not empty."""
        if not v:
            raise ValueError("Team must have at least one agent")
        return v

    @field_validator("agents")
    @classmethod
    def validate_unique_agent_ids(cls, v: list[AgentDefinition]) -> list[AgentDefinition]:
        """Validate agent IDs are unique."""
        ids = [agent.id for agent in v]
        if len(ids) != len(set(ids)):
            raise ValueError("Agent IDs must be unique")
        return v

    @model_validator(mode="after")
    def validate_workflow_references(self) -> "TeamConfiguration":
        """Validate workflow steps reference existing agents.

        Note: When collaboration is enabled, additional agents may be
        spawned dynamically at runtime. Those agents are NOT referenced
        in workflow steps (which only reference pre-configured agents),
        so no false validation errors should occur.
        """
        agent_ids = {agent.id for agent in self.agents}

        for step in self.workflow.steps:
            # Gated steps may have an empty agent
            if step.type == WorkflowStepType.GATED and not step.agent:
                continue
            if step.agent not in agent_ids:
                raise ValueError(f"Workflow step references unknown agent: {step.agent}")

            # Validate next step references
            referenced_agents = set()
            if step.next:
                referenced_agents.add(step.next)
            if step.next_on_accept:
                referenced_agents.add(step.next_on_accept)
            if step.next_on_reject:
                referenced_agents.add(step.next_on_reject)

            # Next steps should reference valid agent IDs (they're step targets)
            # Note: In a full implementation, these would reference step IDs, not agent IDs
            # For now, we'll validate they're non-empty strings
            for ref in referenced_agents:
                if not ref.strip():
                    raise ValueError("Workflow step references cannot be empty")

        return self

    @model_validator(mode="after")
    def validate_state_schema_agents(self) -> "TeamConfiguration":
        """Validate state schema references existing agents."""
        if self.state_schema:
            agent_ids = {agent.id for agent in self.agents}
            for agent_id in self.state_schema.agent_io:
                if agent_id not in agent_ids:
                    raise ValueError(f"State schema references unknown agent: {agent_id}")
        return self

    def to_json_schema(self) -> dict[str, Any]:
        """Export as JSON schema.

        Returns:
            JSON schema dictionary
        """
        return self.model_json_schema()

    @classmethod
    def from_json_file(cls, file_path: str) -> "TeamConfiguration":
        """Load team configuration from JSON file.

        Args:
            file_path: Path to JSON configuration file

        Returns:
            Validated TeamConfiguration instance
        """
        import json
        from pathlib import Path

        config_path = Path(file_path)
        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {file_path}")

        with open(config_path) as f:
            data = json.load(f)

        return cls(**data)

    @classmethod
    def from_yaml_file(cls, file_path: str) -> "TeamConfiguration":
        """Load team configuration from YAML file.

        Args:
            file_path: Path to YAML configuration file

        Returns:
            Validated TeamConfiguration instance
        """
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "PyYAML is required to load YAML files. Install with: uv add pyyaml"
            ) from exc

        from pathlib import Path

        config_path = Path(file_path)
        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {file_path}")

        with open(config_path) as f:
            data = yaml.safe_load(f)

        return cls(**data)

    def save_json(self, file_path: str) -> None:
        """Save team configuration to JSON file.

        Args:
            file_path: Path to save configuration
        """
        import json
        from pathlib import Path

        output_path = Path(file_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w") as f:
            json.dump(self.model_dump(), f, indent=2)

    def save_yaml(self, file_path: str) -> None:
        """Save team configuration to YAML file.

        Args:
            file_path: Path to save configuration
        """
        try:
            import yaml
        except ImportError as exc:
            raise ImportError(
                "PyYAML is required to save YAML files. Install with: uv add pyyaml"
            ) from exc

        from pathlib import Path

        output_path = Path(file_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w") as f:
            yaml.dump(self.model_dump(), f, default_flow_style=False, sort_keys=False)
