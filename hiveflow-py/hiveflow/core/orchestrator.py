"""Orchestrator Agent - Wraps DeepResearcher for workflow integration.

Provides an Agent-compatible wrapper around DeepResearcher that
participates in the agent registry and workflow graph, emitting
stream events for progress tracking.
"""

from typing import Any

import structlog

from hiveflow.core.research import BranchResult, DeepResearchConfig, DeepResearcher

logger = structlog.get_logger()


class OrchestratorAgent:
    """Agent wrapper for DeepResearcher recursive exploration.

    Wraps DeepResearcher as an agent that can participate in the workflow
    graph. Delegates to DeepResearcher's plan/branch/dive/merge logic
    and reports progress via stream events.

    Usage:
        agent = OrchestratorAgent(
            agent_id="explorer",
            config=DeepResearchConfig(breadth=3, depth=2),
            research_fn=my_research_fn,
            query_generator_fn=my_query_gen,
        )
        result = await agent.execute(state)
    """

    def __init__(
        self,
        agent_id: str = "orchestrator",
        role: str = "Deep research orchestrator",
        config: DeepResearchConfig | None = None,
        research_fn: Any = None,
        query_generator_fn: Any = None,
    ) -> None:
        self.agent_id = agent_id
        self.role = role
        self._config = config or DeepResearchConfig()
        self._research_fn = research_fn
        self._query_generator_fn = query_generator_fn
        self._researcher: DeepResearcher | None = None
        self._progress: float = 0.0

    def _ensure_researcher(self) -> DeepResearcher:
        """Create or return the DeepResearcher instance."""
        if self._researcher is None:
            self._researcher = DeepResearcher(
                config=self._config,
                research_fn=self._research_fn,
                query_generator_fn=self._query_generator_fn,
            )
        return self._researcher

    async def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        """Run recursive exploration using DeepResearcher.

        Reads the topic from state["task"], runs the research,
        and writes results back to state.

        Args:
            state: Current workflow state (must contain "task" key)

        Returns:
            Updated state with exploration results
        """
        topic = state.get("task", "")
        researcher = self._ensure_researcher()

        # Emit EXECUTOR_INVOKED if stream channel available
        stream_channel = state.get("_stream_channel")
        if stream_channel and hasattr(stream_channel, "publish"):
            from hiveflow.core.streaming import StreamEvent, StreamEventType

            await stream_channel.publish(
                StreamEvent(
                    event_type=StreamEventType.EXECUTOR_INVOKED,
                    agent_id=self.agent_id,
                    content=f"Starting recursive exploration: {topic[:100]}",
                    data={"breadth": self._config.breadth, "depth": self._config.depth},
                )
            )

        try:
            result: BranchResult = await researcher.research(topic, context=state)
            self._progress = 1.0

            output = {
                **state,
                f"{self.agent_id}_output": result.content,
                f"{self.agent_id}_citations": [
                    c.to_dict() if hasattr(c, "to_dict") else str(c)
                    for c in (result.citations or [])
                ],
                f"{self.agent_id}_branch_count": len(result.sub_results or []),
            }

        except Exception as exc:
            logger.exception("Orchestrator %s failed", self.agent_id)
            output = {
                **state,
                f"{self.agent_id}_output": f"Exploration failed: {exc}",
                f"{self.agent_id}_error": str(exc),
            }

        # Emit EXECUTOR_COMPLETED
        if stream_channel and hasattr(stream_channel, "publish"):
            from hiveflow.core.streaming import StreamEvent, StreamEventType

            await stream_channel.publish(
                StreamEvent(
                    event_type=StreamEventType.EXECUTOR_COMPLETED,
                    agent_id=self.agent_id,
                    content=str(output.get(f"{self.agent_id}_output", ""))[:500],
                )
            )

        return output

    def get_progress(self) -> float:
        """Return completion percentage (0.0 to 1.0) across all branches."""
        if self._researcher:
            progress = self._researcher.progress
            if hasattr(progress, "completion_pct"):
                return progress.completion_pct / 100.0
        return self._progress
