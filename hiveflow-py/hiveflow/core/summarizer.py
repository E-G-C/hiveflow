"""Summary Generator - Produces compact summaries of agent outputs.

Used for summary propagation between workflow steps so downstream
agents receive condensed context instead of full output text.
"""

import structlog

from hiveflow.plugins.llm import LLMConfig, LLMMessage, LLMProvider

logger = structlog.get_logger()

SUMMARY_SYSTEM_PROMPT = (
    "You are a summarization assistant. Produce a concise summary of the "
    "following text. Preserve key facts, conclusions, and action items. "
    "Do NOT add commentary. Output ONLY the summary."
)

OUTLINE_SYSTEM_PROMPT = (
    "You are an outline assistant. Given a set of section summaries, "
    "produce a coherent outline that captures the structure and key points. "
    "Use bullet points. Output ONLY the outline."
)

# Differential compression: reasoning outputs get more generous summaries
# than data outputs, based on DeepMiner's insight that reasoning traces
# have long-term strategic value.
REASONING_SUMMARY_MULTIPLIER = 2.0  # 2x budget for reasoning outputs
DATA_SUMMARY_MULTIPLIER = 0.5  # 0.5x budget for data outputs


class SummaryGenerator:
    """Generates compact summaries of agent outputs for context propagation.

    After each agent step, the workflow engine uses this to generate a
    short summary (~200 tokens) stored alongside the full output. Downstream
    agents receive summaries instead of full text, keeping context budgets
    under control while enabling large combined outputs.
    """

    def __init__(
        self,
        llm_provider: LLMProvider,
        model: str = "",
        max_summary_tokens: int = 200,
        max_outline_tokens: int = 1000,
        summary_threshold: int | None = None,
    ) -> None:
        """Initialize summary generator.

        Args:
            llm_provider: LLM provider for summary generation
            model: Model name to use (should be a fast/cheap model)
            max_summary_tokens: Max tokens for individual summaries
            max_outline_tokens: Max tokens for assembled outlines
            summary_threshold: Minimum word count before summarization
                activates. Text with fewer words than this threshold is
                returned unchanged by summarize(). When None (default),
                falls back to max_summary_tokens as the threshold,
                preserving existing behavior.
        """
        self.llm_provider = llm_provider
        # Strip provider prefix (e.g. "azure:gpt-4o-mini" → "gpt-4o-mini")
        # consistent with Agent._build_config()
        self.model = model.split(":", 1)[-1] if ":" in model else model
        self.max_summary_tokens = max_summary_tokens
        self.max_outline_tokens = max_outline_tokens
        self.summary_threshold = summary_threshold

    async def summarize(
        self,
        text: str,
        max_tokens: int | None = None,
        output_type: str | None = None,
    ) -> str:
        """Generate a summary of the given text.

        Short-circuits if text word count is below the summary_threshold
        (or below max_summary_tokens when no threshold is configured).

        Applies differential compression when output_type is specified:
        reasoning outputs (orchestrator decisions, reviewer feedback) get
        higher-fidelity summaries, while data outputs (research results,
        raw content) get more aggressive compression.

        Args:
            text: The text to summarize
            max_tokens: Override for max summary tokens (output budget)
            output_type: Agent output type for differential compression.
                "reasoning" or "structured_data" -> higher fidelity (2x tokens).
                "data" or "side_effect" -> more aggressive (0.5x tokens).
                None -> standard budget.

        Returns:
            Summary string, or original text if shorter than threshold
        """
        effective_max = max_tokens or self.max_summary_tokens

        # Apply differential compression multiplier
        if output_type in ("reasoning", "structured_data"):
            effective_max = int(effective_max * REASONING_SUMMARY_MULTIPLIER)
        elif output_type in ("data", "side_effect"):
            effective_max = int(effective_max * DATA_SUMMARY_MULTIPLIER)

        # Determine the skip threshold: use summary_threshold if set,
        # otherwise fall back to effective_max (preserving legacy behavior
        # where max_summary_tokens served as both output budget and skip
        # threshold).
        skip_threshold = (
            self.summary_threshold if self.summary_threshold is not None else effective_max
        )

        # Skip summarization if text is below the threshold
        word_count = len(text.split())
        if word_count <= skip_threshold:
            return text

        messages = [
            LLMMessage(role="system", content=SUMMARY_SYSTEM_PROMPT),
            LLMMessage(
                role="user",
                content=(f"Summarize the following in at most {effective_max} tokens:\n\n{text}"),
            ),
        ]
        config = LLMConfig(
            model=self.model,
            max_tokens=effective_max,
            temperature=0.3,
        )
        response = await self.llm_provider.chat(messages, config)
        return response.content

    async def build_outline(
        self,
        summaries: dict[str, str],
        max_tokens: int | None = None,
    ) -> str:
        """Build an outline from multiple agent summaries.

        Args:
            summaries: Mapping of agent_id -> summary text
            max_tokens: Override for max outline tokens

        Returns:
            Outline string
        """
        effective_max = max_tokens or self.max_outline_tokens

        parts = []
        for agent_id, summary in summaries.items():
            parts.append(f"## {agent_id}\n{summary}")
        combined = "\n\n".join(parts)

        # If already within budget, return as-is
        if len(combined.split()) <= effective_max:
            return combined

        messages = [
            LLMMessage(role="system", content=OUTLINE_SYSTEM_PROMPT),
            LLMMessage(
                role="user",
                content=(
                    f"Create an outline (max {effective_max} tokens) from "
                    f"these section summaries:\n\n{combined}"
                ),
            ),
        ]
        config = LLMConfig(
            model=self.model,
            max_tokens=effective_max,
            temperature=0.3,
        )
        response = await self.llm_provider.chat(messages, config)
        return response.content
