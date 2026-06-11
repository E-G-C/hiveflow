"""Context Reducer - Intelligent context compression using LLM reflection.

Implements waste classification (useless/redundant/expired) from AgentDiet
and smart budget enforcement from both DeepMiner and AgentDiet papers.
Uses a cheap LLM as a "reflection module" to intelligently compress context
before falling back to mechanical truncation.
"""

import structlog

from hiveflow.plugins.llm import LLMConfig, LLMMessage, LLMProvider

logger = structlog.get_logger()

REDUCTION_SYSTEM_PROMPT = (
    "You are a context reduction assistant. Your job is to remove waste "
    "from the given context while preserving all essential information.\n\n"
    "Remove these types of waste:\n"
    "- USELESS: Irrelevant metadata, verbose boilerplate, debug traces, "
    "repeated headers\n"
    "- REDUNDANT: Information that appears multiple times across sections "
    "(e.g., restating the task, duplicating conclusions)\n"
    "- EXPIRED: Context from earlier steps that has been fully superseded "
    "by later outputs\n\n"
    "Rules:\n"
    "- Preserve key facts, decisions, requirements, and action items\n"
    "- Keep the task description intact\n"
    "- Replace removed content with brief placeholders like "
    "'[earlier research incorporated above]'\n"
    "- Do NOT add commentary\n"
    "- Output ONLY the reduced context"
)


class ContextReducer:
    """Reduces assembled context by removing waste before token truncation.

    Uses a cheap LLM (FAST_LLM tier) as a reflection module to identify
    and remove useless, redundant, and expired information from context.
    This is more effective than mechanical word-level truncation while
    costing far less than the main agent's context budget.

    Inspired by AgentDiet's trajectory reduction approach and DeepMiner's
    insight about preserving reasoning while compressing data.
    """

    def __init__(
        self,
        llm_provider: LLMProvider,
        model: str = "",
        overflow_threshold: float = 1.5,
    ) -> None:
        """Initialize context reducer.

        Args:
            llm_provider: LLM provider for reduction (should be fast/cheap)
            model: Model name to use for reduction
            overflow_threshold: Only invoke LLM reduction when context
                exceeds budget by this factor. E.g., 1.5 means reduce
                only when context is >150% of budget. Below this, fall
                back to mechanical truncation.
        """
        self.llm_provider = llm_provider
        self.model = model.split(":", 1)[-1] if ":" in model else model
        self.overflow_threshold = overflow_threshold

    async def reduce(
        self,
        context: str,
        budget: int,
        task: str = "",
    ) -> str:
        """Reduce context to fit within budget using LLM-based waste removal.

        Two-pass approach:
        1. If context exceeds budget * overflow_threshold, use LLM to
           intelligently remove waste
        2. If still over budget after LLM reduction, fall back to
           mechanical truncation

        Args:
            context: Assembled context text to reduce
            budget: Target word count budget
            task: Optional task description for context-aware reduction

        Returns:
            Reduced context text fitting within budget
        """
        word_count = len(context.split())
        if word_count <= budget:
            return context

        # Only invoke LLM reduction when overflow is significant
        if word_count > budget * self.overflow_threshold:
            try:
                context = await self._llm_reduce(context, budget, task)
            except Exception as e:
                logger.warning("LLM context reduction failed: %s", e)

        # Mechanical fallback: truncate at word level if still over budget
        words = context.split()
        if len(words) > budget:
            context = " ".join(words[:budget]) + "\n[truncated to fit context budget]"

        return context

    async def _llm_reduce(
        self,
        context: str,
        budget: int,
        task: str,
    ) -> str:
        """Use LLM to intelligently reduce context.

        Args:
            context: Context text to reduce
            budget: Target word count
            task: Task description for context-aware reduction

        Returns:
            LLM-reduced context text
        """
        task_hint = f" for the task: {task}" if task else ""
        messages = [
            LLMMessage(role="system", content=REDUCTION_SYSTEM_PROMPT),
            LLMMessage(
                role="user",
                content=(
                    f"Reduce the following context to approximately {budget} words"
                    f"{task_hint}. Remove useless, redundant, and expired "
                    f"information.\n\n{context}"
                ),
            ),
        ]
        config = LLMConfig(
            model=self.model,
            max_tokens=budget * 2,  # Allow some headroom for LLM response
            temperature=0.2,
        )
        response = await self.llm_provider.chat(messages, config)
        return response.content
