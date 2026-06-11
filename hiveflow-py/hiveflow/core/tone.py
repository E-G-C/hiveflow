"""Tone & Style System — catalog, resolution, and injection.

Implements the tone system (FR-028–FR-035): a structured, extensible
collection of tone definitions that affect prompt generation across
text-producing agents in a workflow.
"""

from pathlib import Path
from typing import Any

import structlog
import yaml
from pydantic import BaseModel, Field

logger = structlog.get_logger()


class ToneDefinition(BaseModel):
    """A single tone entry in the catalog (FR-029).

    The ``prompt_modifier`` is injected into the system prompt of every
    agent with ``behavior_type == LLM_ONLY`` (FR-030).
    """

    tone_id: str = Field(description="Unique identifier (e.g., 'formal', 'executive')")
    label: str = Field(description="Human-readable display name")
    description: str = Field(description="Purpose description")
    prompt_modifier: str = Field(description="1–3 sentence instruction injected into agent prompts")


# ---------------------------------------------------------------------------
# Built-in tone catalog (FR-028)
# ---------------------------------------------------------------------------

_BUILTIN_TONES: list[ToneDefinition] = [
    ToneDefinition(
        tone_id="objective",
        label="Objective",
        description="Impartial and unbiased presentation of facts and findings",
        prompt_modifier=(
            "Adopt an objective tone throughout your output. Present facts and "
            "findings impartially without personal bias or advocacy."
        ),
    ),
    ToneDefinition(
        tone_id="formal",
        label="Formal",
        description="Adheres to academic standards with sophisticated language and structure",
        prompt_modifier=(
            "Write in a formal, academic tone. Use precise language, structured "
            "arguments, and maintain professional register throughout."
        ),
    ),
    ToneDefinition(
        tone_id="analytical",
        label="Analytical",
        description="Critical evaluation and detailed examination of data and theories",
        prompt_modifier=(
            "Adopt an analytical tone throughout your output. Critically evaluate "
            "the data and theories presented. Examine evidence in detail, identify "
            "patterns, and highlight strengths and weaknesses in the reasoning."
        ),
    ),
    ToneDefinition(
        tone_id="persuasive",
        label="Persuasive",
        description="Convincing the audience of a particular viewpoint or argument",
        prompt_modifier=(
            "Write persuasively. Build compelling arguments supported by evidence. "
            "Anticipate counterarguments and address them proactively."
        ),
    ),
    ToneDefinition(
        tone_id="informative",
        label="Informative",
        description="Providing clear and comprehensive information on a topic",
        prompt_modifier=(
            "Write in an informative tone. Provide clear, comprehensive information "
            "that helps the reader understand the topic thoroughly."
        ),
    ),
    ToneDefinition(
        tone_id="explanatory",
        label="Explanatory",
        description="Clarifying complex concepts and processes",
        prompt_modifier=(
            "Write in an explanatory tone. Break down complex concepts into "
            "understandable parts. Use analogies and examples where helpful."
        ),
    ),
    ToneDefinition(
        tone_id="descriptive",
        label="Descriptive",
        description="Detailed depiction of phenomena, experiments, or case studies",
        prompt_modifier=(
            "Write descriptively. Paint a vivid picture of phenomena, processes, "
            "and findings with rich detail and concrete examples."
        ),
    ),
    ToneDefinition(
        tone_id="critical",
        label="Critical",
        description="Judging the validity and relevance of the research and its conclusions",
        prompt_modifier=(
            "Adopt a critical tone. Evaluate the validity, methodology, and "
            "conclusions rigorously. Identify gaps, limitations, and potential biases."
        ),
    ),
    ToneDefinition(
        tone_id="comparative",
        label="Comparative",
        description="Juxtaposing different theories, data, or methods to highlight differences",
        prompt_modifier=(
            "Write in a comparative tone. Systematically juxtapose alternatives, "
            "highlighting similarities, differences, and trade-offs."
        ),
    ),
    ToneDefinition(
        tone_id="speculative",
        label="Speculative",
        description="Exploring hypotheses and potential implications or future research directions",
        prompt_modifier=(
            "Write speculatively. Explore hypotheses, potential implications, and "
            "future directions. Clearly distinguish speculation from established facts."
        ),
    ),
    ToneDefinition(
        tone_id="reflective",
        label="Reflective",
        description="Considering the process and personal insights or experiences",
        prompt_modifier=(
            "Adopt a reflective tone. Consider the broader implications, lessons "
            "learned, and insights that emerge from the material."
        ),
    ),
    ToneDefinition(
        tone_id="narrative",
        label="Narrative",
        description="Telling a story to illustrate findings or methodologies",
        prompt_modifier=(
            "Write in a narrative style. Tell the story behind the findings, "
            "using chronological flow and engaging storytelling techniques."
        ),
    ),
    ToneDefinition(
        tone_id="humorous",
        label="Humorous",
        description="Light-hearted and engaging, making the content more relatable",
        prompt_modifier=(
            "Write with a light, humorous touch. Keep the content engaging and "
            "relatable while maintaining accuracy and professionalism."
        ),
    ),
    ToneDefinition(
        tone_id="optimistic",
        label="Optimistic",
        description="Highlighting positive findings and potential benefits",
        prompt_modifier=(
            "Adopt an optimistic tone. Emphasize positive findings, opportunities, "
            "and potential benefits while remaining grounded in evidence."
        ),
    ),
    ToneDefinition(
        tone_id="pessimistic",
        label="Pessimistic",
        description="Focusing on limitations, challenges, or negative outcomes",
        prompt_modifier=(
            "Adopt a cautious, skeptical tone. Focus on limitations, risks, and "
            "challenges. Highlight what could go wrong and where gaps remain."
        ),
    ),
    ToneDefinition(
        tone_id="concise",
        label="Concise",
        description="Brief and to the point, minimal elaboration",
        prompt_modifier=(
            "Be concise. Use short sentences, eliminate filler, and get straight "
            "to the point. Every word should earn its place."
        ),
    ),
    ToneDefinition(
        tone_id="executive",
        label="Executive",
        description="High-level summary oriented toward decision-makers",
        prompt_modifier=(
            "Write for an executive audience. Lead with key takeaways and "
            "recommendations. Quantify impact. Keep detail minimal — decision-makers "
            "need actionable insights, not exhaustive analysis."
        ),
    ),
]


class ToneCatalog:
    """Extensible collection of tone definitions (FR-028).

    Ships with 17 built-in tones. Custom tones from team config merge
    into the catalog at runtime (custom overrides built-in on ID collision).
    """

    def __init__(self, catalog_path: Path | None = None) -> None:
        """Initialize with built-in tones and optional YAML catalog file."""
        self._tones: dict[str, ToneDefinition] = {}
        # Load built-in tones
        for tone in _BUILTIN_TONES:
            self._tones[tone.tone_id] = tone
        # Load from file if provided
        if catalog_path and catalog_path.exists():
            self._load_from_yaml(catalog_path)

    def _load_from_yaml(self, path: Path) -> None:
        """Load tone definitions from a YAML file."""
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "tones" in data:
                for tone_data in data["tones"]:
                    tone = ToneDefinition.model_validate(tone_data)
                    self._tones[tone.tone_id] = tone
        except Exception:
            logger.warning("Failed to load tone catalog from %s", path, exc_info=True)

    def resolve(self, tone_id: str) -> ToneDefinition | None:
        """Resolve a tone by ID (FR-035).

        Returns the definition or ``None`` with a warning log if not found.
        """
        defn = self._tones.get(tone_id)
        if defn is None:
            logger.warning(
                "Unknown tone '%s'; available: %s",
                tone_id,
                ", ".join(sorted(self._tones.keys())),
            )
        return defn

    def resolve_from_config(self, tone: str | dict[str, Any] | None) -> ToneDefinition | None:
        """Resolve tone from a team config value (FR-031, FR-032).

        Accepts:
        - ``None`` → no tone (FR-034)
        - ``str`` → look up by ID
        - ``dict`` → parse as inline ToneDefinition, register, and return
        """
        if tone is None:
            return None
        if isinstance(tone, str):
            return self.resolve(tone)
        if isinstance(tone, dict):
            try:
                defn = ToneDefinition.model_validate(tone)
                self.register(defn)
                return defn
            except Exception:
                logger.warning("Invalid inline tone definition: %s", tone)
                return None
        return None

    def register(self, tone: ToneDefinition) -> None:
        """Register a custom tone (FR-032, FR-033).

        Overrides built-in on ID collision.
        """
        self._tones[tone.tone_id] = tone

    def list_tones(self) -> list[str]:
        """Return all available tone IDs."""
        return sorted(self._tones.keys())


# ---------------------------------------------------------------------------
# Tone injection helper
# ---------------------------------------------------------------------------

# Agent behavior types that produce text and should receive tone injection.
_TEXT_PRODUCING_BEHAVIORS: frozenset[str] = frozenset(
    {
        "llm_only",
        "tool_user",
    }
)


def inject_tone(system_prompt: str, tone_def: ToneDefinition) -> str:
    """Append the tone prompt_modifier to a system prompt.

    The modifier is added as a clearly delineated section at the end of
    the system prompt so it doesn't interfere with existing instructions.

    Args:
        system_prompt: The original agent system prompt.
        tone_def: The resolved :class:`ToneDefinition`.

    Returns:
        The augmented system prompt.
    """
    return f"{system_prompt}\n\nTONE & STYLE — {tone_def.label}\n{tone_def.prompt_modifier}"


def should_inject_tone(behavior_type: str) -> bool:
    """Return True if the agent behavior type produces text.

    Non-text-producing agents (orchestrators, human gates, action executors)
    are unaffected by tone settings per spec FR-030.
    """
    return behavior_type in _TEXT_PRODUCING_BEHAVIORS
