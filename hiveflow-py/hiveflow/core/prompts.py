"""Prompt Template Library - Reusable prompt templates for agents.

Provides a template system using Python's string.Template with
support for loading from files and composing complex prompts.
Includes prompt families for model-specific prompt variants and
categorized templates for different task types.
"""

import re
from enum import StrEnum
from pathlib import Path
from string import Template
from typing import Any

import structlog

logger = structlog.get_logger()


class PromptFamily(StrEnum):
    """Prompt family for model-specific prompt variants."""

    DEFAULT = "default"  # GPT-4o, Claude, Gemini — standard instruction-following
    GRANITE = "granite"  # IBM Granite — structured XML-style
    LOCAL = "local"  # Ollama, local models — simpler, explicit instructions


# Prefix patterns for family auto-detection
_FAMILY_PREFIXES: list[tuple[str, PromptFamily]] = [
    ("granite:", PromptFamily.GRANITE),
    ("ibm:", PromptFamily.GRANITE),
    ("ollama:", PromptFamily.LOCAL),
    ("local:", PromptFamily.LOCAL),
    ("lmstudio:", PromptFamily.LOCAL),
]


def detect_family(model_name: str) -> PromptFamily:
    """Auto-detect prompt family from model name using prefix matching.

    Args:
        model_name: Model identifier (e.g., "openai:gpt-4o", "ollama:llama3")

    Returns:
        Detected PromptFamily
    """
    lower = model_name.lower()
    for prefix, family in _FAMILY_PREFIXES:
        if lower.startswith(prefix):
            return family
    return PromptFamily.DEFAULT


class PromptCategory(StrEnum):
    """Categories for prompt templates."""

    SUB_TASK_DECOMPOSITION = "sub_task_decomposition"
    SEARCH_QUERY_GENERATION = "search_query_generation"
    REPORT_WRITING = "report_writing"
    INTRO_CONCLUSION = "intro_conclusion"
    SOURCE_CURATION = "source_curation"
    DRAFT_REVIEW = "draft_review"
    REVISION_FEEDBACK = "revision_feedback"
    AGENT_ROLE_SELECTION = "agent_role_selection"
    SUMMARY_GENERATION = "summary_generation"
    OUTLINE_ASSEMBLY = "outline_assembly"
    ACTION_PLANNING = "action_planning"
    ACTION_VALIDATION = "action_validation"
    DECISION_FRAMING = "decision_framing"
    CODE_GENERATION = "code_generation"
    INCIDENT_ANALYSIS = "incident_analysis"


def resolve_dotted_path(obj: Any, path: str) -> Any:
    """Traverse an object by dot-separated path.

    Supports dict keys and object attributes at each level.
    Returns None if the path cannot be resolved.

    Args:
        obj: Root object to traverse
        path: Dot-separated path (e.g., "task.description")

    Returns:
        Resolved value, or None if path doesn't exist
    """
    current = obj
    for part in path.split("."):
        if current is None:
            return None
        current = current.get(part) if isinstance(current, dict) else getattr(current, part, None)
    return current


class PromptTemplate:
    """A reusable prompt template with variable substitution.

    Uses Python's string.Template ($variable syntax) for safe,
    predictable substitution.

    Usage:
        t = PromptTemplate("You are a $role. Your task: $task")
        prompt = t.render(role="researcher", task="Find papers")
    """

    def __init__(
        self,
        template: str,
        name: str = "",
        description: str = "",
        required_vars: list[str] | None = None,
        category: PromptCategory | None = None,
        family: PromptFamily = PromptFamily.DEFAULT,
    ) -> None:
        """Initialize prompt template.

        Args:
            template: Template string with $variable placeholders
            name: Optional template name
            description: Optional description
            required_vars: Variables that must be provided
            category: Optional category for template classification
            family: Prompt family (default, granite, local)
        """
        self.template = template
        self.name = name
        self.description = description
        self.required_vars = required_vars or []
        self.category = category
        self.family = family
        self._tmpl = Template(template)

    def render(self, _variables: dict[str, Any] | None = None, /, **kwargs: Any) -> str:
        """Render template with variables, supporting dotted-path resolution.

        Supports both flat variables ($task) and dotted-path references
        (${task.description}) by resolving paths against the provided
        variables dict.

        Args:
            _variables: Optional dict of nested objects for dotted-path resolution
            **kwargs: Flat variable values to substitute

        Returns:
            Rendered prompt string

        Raises:
            ValueError: If required variables are missing
        """
        all_vars = dict(_variables or {})
        all_vars.update(kwargs)

        missing = [v for v in self.required_vars if v not in all_vars]
        if missing:
            raise ValueError(f"Template '{self.name}' missing required variables: {missing}")

        # Resolve dotted-path references: ${task.description} → resolved value
        result = self.template
        dotted_pattern = re.compile(r"\$\{([a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)+)\}")
        for match in dotted_pattern.finditer(self.template):
            path = match.group(1)
            resolved = resolve_dotted_path(all_vars, path)
            if resolved is not None:
                result = result.replace(match.group(0), str(resolved))
            else:
                logger.warning("Template '%s': unresolved dotted path '%s'", self.name, path)

        # Use string.Template for remaining flat variables
        return Template(result).safe_substitute(**all_vars)

    @property
    def variables(self) -> list[str]:
        """Extract variable names from template.

        Returns:
            List of variable names found in template
        """
        # Parse Template identifiers
        result: list[str] = []
        for match in Template.pattern.finditer(self.template):
            name = match.group("named") or match.group("braced")
            if name and name not in result:
                result.append(name)
        return result

    def to_dict(self) -> dict[str, Any]:
        """Serialize template to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "template": self.template,
            "required_vars": self.required_vars,
            "variables": self.variables,
        }


class PromptLibrary:
    """Collection of named prompt templates.

    Usage:
        lib = PromptLibrary()
        lib.add(PromptTemplate("...", name="researcher"))
        prompt = lib.render("researcher", task="Find papers")
    """

    def __init__(self) -> None:
        self._templates: dict[str, PromptTemplate] = {}

    def add(self, template: PromptTemplate) -> None:
        """Add a template to the library.

        Args:
            template: Template to add (must have a name)
        """
        if not template.name:
            raise ValueError("Template must have a name")
        self._templates[template.name] = template

    def get(self, name: str) -> PromptTemplate | None:
        """Get a template by name.

        Args:
            name: Template name

        Returns:
            Template or None
        """
        return self._templates.get(name)

    def render(self, template_name: str, /, **kwargs: Any) -> str:
        """Render a named template.

        Args:
            template_name: Template name (positional-only)
            **kwargs: Template variables

        Returns:
            Rendered prompt string
        """
        template = self._templates.get(template_name)
        if not template:
            raise KeyError(f"Template '{template_name}' not found")
        return template.render(**kwargs)

    def list_templates(self) -> list[str]:
        """List all template names.

        Returns:
            Sorted list of template names
        """
        return sorted(self._templates.keys())

    @classmethod
    def from_directory(cls, directory: str | Path) -> "PromptLibrary":
        """Load templates from a directory of .txt files.

        Each file becomes a template named after the file stem.

        Args:
            directory: Path to directory of template files

        Returns:
            Populated PromptLibrary
        """
        lib = cls()
        dir_path = Path(directory)

        if not dir_path.exists():
            logger.warning("Prompt template directory not found: %s", dir_path)
            return lib

        for file_path in sorted(dir_path.glob("*.txt")):
            content = file_path.read_text(encoding="utf-8")
            template = PromptTemplate(
                template=content,
                name=file_path.stem,
            )
            lib.add(template)
            logger.debug("Loaded prompt template: %s", file_path.stem)

        return lib


# --- Built-in Prompt Templates ---

SYSTEM_RESEARCHER = PromptTemplate(
    template=(
        "You are a research agent specializing in $topic. "
        "Your goal is to find and synthesize information from multiple sources. "
        "Always cite your sources and provide balanced, factual analysis.\n\n"
        "IMPORTANT: Write a thorough, comprehensive response. Do not truncate "
        "or abbreviate your findings. Aim for at least 1000 words of detailed "
        "analysis.\n\n"
        "Current task: $task"
    ),
    name="system_researcher",
    description="System prompt for research agents",
    required_vars=["topic", "task"],
    category=PromptCategory.SEARCH_QUERY_GENERATION,
)

SYSTEM_WRITER = PromptTemplate(
    template=(
        "You are a professional writer composing a $format about $topic. "
        "Write in a $tone tone, targeting a $audience audience. "
        "Use clear, well-structured prose with appropriate headings.\n\n"
        "IMPORTANT: Write a complete, detailed $format. Do not summarize or "
        "abbreviate. Each section should be thorough and well-developed. "
        "Aim for at least 1500 words.\n\n"
        "Source material:\n$sources\n\n"
        "Write the $format now."
    ),
    name="system_writer",
    description="System prompt for writing agents",
    required_vars=["format", "topic", "tone", "audience", "sources"],
    category=PromptCategory.REPORT_WRITING,
)

SYSTEM_REVIEWER = PromptTemplate(
    template=(
        "You are a quality reviewer evaluating a $document_type. "
        "Check for:\n"
        "1. Factual accuracy\n"
        "2. Completeness of coverage\n"
        "3. Clarity and readability\n"
        "4. Proper source attribution\n"
        "5. Logical structure\n\n"
        "Provide specific, actionable feedback with examples from the text. "
        "State clearly whether the document is APPROVED or NEEDS REVISION.\n\n"
        "Document to review:\n$document"
    ),
    name="system_reviewer",
    description="System prompt for review agents",
    required_vars=["document_type", "document"],
    category=PromptCategory.DRAFT_REVIEW,
)

SYSTEM_SUMMARIZER = PromptTemplate(
    template=(
        "You are a summarization assistant. Produce a concise summary of the "
        "following text in at most $max_tokens tokens. Preserve key facts, "
        "conclusions, and action items. Output ONLY the summary.\n\n"
        "Text to summarize:\n$text"
    ),
    name="system_summarizer",
    description="System prompt for summary generation",
    required_vars=["text", "max_tokens"],
    category=PromptCategory.SUMMARY_GENERATION,
)

SYSTEM_OUTLINE_BUILDER = PromptTemplate(
    template=(
        "You are an outline assistant. Given the following section summaries, "
        "produce a coherent outline that captures the overall structure and "
        "key points. Use bullet points. Keep it under $max_tokens tokens.\n\n"
        "$summaries"
    ),
    name="system_outline_builder",
    description="System prompt for outline assembly from summaries",
    required_vars=["summaries", "max_tokens"],
    category=PromptCategory.OUTLINE_ASSEMBLY,
)

# --- New Categorized Templates (T019) ---

SYSTEM_SUB_TASK_DECOMPOSITION = PromptTemplate(
    template=(
        "Break the following task into concrete, actionable sub-tasks.\n"
        "Return a JSON object with a 'sub_tasks' array of strings.\n\n"
        "Task: $task\n\nContext: $context"
    ),
    name="sub_task_decomposition",
    category=PromptCategory.SUB_TASK_DECOMPOSITION,
    required_vars=["task", "context"],
)

SYSTEM_SEARCH_QUERY = PromptTemplate(
    template=(
        "Generate $count diverse search queries to research: $topic\n"
        "Queries should cover different angles and aspects.\n"
        "Return one query per line."
    ),
    name="search_query_generation",
    category=PromptCategory.SEARCH_QUERY_GENERATION,
    required_vars=["count", "topic"],
)

SYSTEM_INTRO_CONCLUSION = PromptTemplate(
    template=(
        "Write a compelling $section_type for a $format about $topic.\n"
        "Tone: $tone. Audience: $audience.\n\n"
        "Key points to address:\n$key_points"
    ),
    name="intro_conclusion",
    category=PromptCategory.INTRO_CONCLUSION,
    required_vars=["section_type", "format", "topic", "tone", "audience", "key_points"],
)

SYSTEM_SOURCE_CURATION = PromptTemplate(
    template=(
        "Evaluate and rank the following sources for relevance to: $query\n"
        "Score each source 1-10 for relevance, credibility, and recency.\n"
        "Return a ranked list with scores and brief justification.\n\n"
        "Sources:\n$sources"
    ),
    name="source_curation",
    category=PromptCategory.SOURCE_CURATION,
    required_vars=["query", "sources"],
)

SYSTEM_REVISION = PromptTemplate(
    template=(
        "Revise the following $document_type based on the feedback provided.\n"
        "Apply all feedback items while preserving the original structure.\n\n"
        "Original:\n$original\n\nFeedback:\n$feedback"
    ),
    name="revision_feedback",
    category=PromptCategory.REVISION_FEEDBACK,
    required_vars=["document_type", "original", "feedback"],
)

SYSTEM_AGENT_ROLE_SELECTION = PromptTemplate(
    template=(
        "Given the following task, select the most appropriate agent role.\n"
        "Available roles: $available_roles\n\n"
        "Task: $task\n\n"
        "Return the role ID and a brief justification."
    ),
    name="agent_role_selection",
    category=PromptCategory.AGENT_ROLE_SELECTION,
    required_vars=["available_roles", "task"],
)

SYSTEM_ACTION_PLANNING = PromptTemplate(
    template=(
        "Plan the actions needed to accomplish: $goal\n"
        "Available tools: $available_tools\n\n"
        "For each action, specify the tool, arguments, and expected outcome.\n"
        "Consider dependencies between actions."
    ),
    name="action_planning",
    category=PromptCategory.ACTION_PLANNING,
    required_vars=["goal", "available_tools"],
)

SYSTEM_ACTION_VALIDATION = PromptTemplate(
    template=(
        "Validate that the following action can be safely executed:\n"
        "Tool: $tool_name\nArguments: $arguments\n\n"
        "Check prerequisites, potential side effects, and reversibility.\n"
        "Return APPROVED or BLOCKED with reasoning."
    ),
    name="action_validation",
    category=PromptCategory.ACTION_VALIDATION,
    required_vars=["tool_name", "arguments"],
)

SYSTEM_DECISION_FRAMING = PromptTemplate(
    template=(
        "Frame the following decision for evaluation:\n"
        "Decision: $decision\n\n"
        "Define evaluation criteria, list alternatives, and assess each "
        "alternative against the criteria. Recommend the best option."
    ),
    name="decision_framing",
    category=PromptCategory.DECISION_FRAMING,
    required_vars=["decision"],
)

SYSTEM_CODE_GENERATION = PromptTemplate(
    template=(
        "Generate $language code for: $task\n\n"
        "Requirements:\n$requirements\n\n"
        "Follow best practices for $language. Include error handling "
        "and documentation. Output only the code."
    ),
    name="code_generation",
    category=PromptCategory.CODE_GENERATION,
    required_vars=["language", "task", "requirements"],
)

SYSTEM_INCIDENT_ANALYSIS = PromptTemplate(
    template=(
        "Analyze the following incident and determine the root cause.\n\n"
        "Incident description: $incident\n"
        "Timeline: $timeline\n"
        "Affected systems: $systems\n\n"
        "Provide: root cause, contributing factors, impact assessment, "
        "and recommended remediation steps."
    ),
    name="incident_analysis",
    category=PromptCategory.INCIDENT_ANALYSIS,
    required_vars=["incident", "timeline", "systems"],
)

# Default library with built-in templates
_default_library: PromptLibrary | None = None


def get_default_library() -> PromptLibrary:
    """Get the default prompt library with built-in templates.

    Returns:
        PromptLibrary with built-in templates
    """
    global _default_library  # noqa: PLW0603
    if _default_library is None:
        _default_library = PromptLibrary()
        for tmpl in [
            SYSTEM_RESEARCHER,
            SYSTEM_WRITER,
            SYSTEM_REVIEWER,
            SYSTEM_SUMMARIZER,
            SYSTEM_OUTLINE_BUILDER,
            SYSTEM_SUB_TASK_DECOMPOSITION,
            SYSTEM_SEARCH_QUERY,
            SYSTEM_INTRO_CONCLUSION,
            SYSTEM_SOURCE_CURATION,
            SYSTEM_REVISION,
            SYSTEM_AGENT_ROLE_SELECTION,
            SYSTEM_ACTION_PLANNING,
            SYSTEM_ACTION_VALIDATION,
            SYSTEM_DECISION_FRAMING,
            SYSTEM_CODE_GENERATION,
            SYSTEM_INCIDENT_ANALYSIS,
        ]:
            _default_library.add(tmpl)
    return _default_library
