"""Cost Tracking System - Monitor and report LLM usage costs.

Tracks token usage across all LLM calls, aggregates by agent and model,
and provides cost estimation based on published pricing.
"""

import time
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger()


# Cost per 1M tokens (input, output) - approximate published pricing
MODEL_PRICING: dict[str, tuple[float, float]] = {
    # OpenAI
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "o3-mini": (1.10, 4.40),
    "gpt-4-turbo": (10.00, 30.00),
    # Anthropic
    "claude-sonnet-4-20250514": (3.00, 15.00),
    "claude-haiku-4-20250414": (0.80, 4.00),
    "claude-3-5-sonnet-20241022": (3.00, 15.00),
    # Local / free
    "llama3.3": (0.0, 0.0),
}


@dataclass
class UsageRecord:
    """A single LLM usage record."""

    agent_id: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    timestamp: float = field(default_factory=time.time)
    estimated_cost_usd: float = 0.0


@dataclass
class AgentCostSummary:
    """Aggregated cost summary for a single agent."""

    agent_id: str
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    total_estimated_cost_usd: float = 0.0
    call_count: int = 0


@dataclass
class WorkflowCostReport:
    """Complete cost report for a workflow execution."""

    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    total_estimated_cost_usd: float = 0.0
    agent_summaries: dict[str, AgentCostSummary] = field(default_factory=dict)
    model_breakdown: dict[str, dict[str, Any]] = field(default_factory=dict)
    records: list[UsageRecord] = field(default_factory=list)
    duration_seconds: float = 0.0


class CostTracker:
    """Tracks LLM costs across a workflow execution.

    Usage:
        tracker = CostTracker()
        tracker.record(agent_id="researcher", model="gpt-4o",
                      prompt_tokens=500, completion_tokens=200)
        report = tracker.get_report()
    """

    def __init__(self, custom_pricing: dict[str, tuple[float, float]] | None = None) -> None:
        """Initialize cost tracker.

        Args:
            custom_pricing: Optional custom pricing overrides {model: (input_cost, output_cost)}
                           Costs are per 1M tokens.
        """
        self._records: list[UsageRecord] = []
        self._pricing = {**MODEL_PRICING, **(custom_pricing or {})}
        self._start_time = time.monotonic()

    def record(
        self,
        agent_id: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int | None = None,
    ) -> UsageRecord:
        """Record a single LLM usage event.

        Args:
            agent_id: Agent that made the call
            model: Model identifier
            prompt_tokens: Number of prompt/input tokens
            completion_tokens: Number of completion/output tokens
            total_tokens: Total tokens (defaults to sum)

        Returns:
            The created UsageRecord
        """
        if total_tokens is None:
            total_tokens = prompt_tokens + completion_tokens

        cost = self._estimate_cost(model, prompt_tokens, completion_tokens)

        record = UsageRecord(
            agent_id=agent_id,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=cost,
        )
        self._records.append(record)

        logger.debug(
            "Cost record: agent=%s model=%s tokens=%d cost=$%.6f",
            agent_id,
            model,
            total_tokens,
            cost,
        )

        return record

    def _estimate_cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        """Estimate cost for a single call.

        Args:
            model: Model identifier
            prompt_tokens: Input token count
            completion_tokens: Output token count

        Returns:
            Estimated cost in USD
        """
        # Try exact match first, then prefix match
        pricing = self._pricing.get(model)
        if pricing is None:
            for key in self._pricing:
                if model.startswith(key) or key.startswith(model):
                    pricing = self._pricing[key]
                    break

        if pricing is None:
            logger.debug("No pricing data for model: %s", model)
            return 0.0

        input_cost, output_cost = pricing
        return (prompt_tokens * input_cost + completion_tokens * output_cost) / 1_000_000

    def get_report(self) -> WorkflowCostReport:
        """Generate a complete cost report.

        Returns:
            WorkflowCostReport with aggregated metrics
        """
        report = WorkflowCostReport(
            records=list(self._records),
            duration_seconds=time.monotonic() - self._start_time,
        )

        # Aggregate by agent
        for record in self._records:
            report.total_prompt_tokens += record.prompt_tokens
            report.total_completion_tokens += record.completion_tokens
            report.total_tokens += record.total_tokens
            report.total_estimated_cost_usd += record.estimated_cost_usd

            # Per-agent summary
            if record.agent_id not in report.agent_summaries:
                report.agent_summaries[record.agent_id] = AgentCostSummary(agent_id=record.agent_id)
            summary = report.agent_summaries[record.agent_id]
            summary.total_prompt_tokens += record.prompt_tokens
            summary.total_completion_tokens += record.completion_tokens
            summary.total_tokens += record.total_tokens
            summary.total_estimated_cost_usd += record.estimated_cost_usd
            summary.call_count += 1

            # Per-model breakdown
            if record.model not in report.model_breakdown:
                report.model_breakdown[record.model] = {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "estimated_cost_usd": 0.0,
                    "call_count": 0,
                }
            mb = report.model_breakdown[record.model]
            mb["prompt_tokens"] += record.prompt_tokens
            mb["completion_tokens"] += record.completion_tokens
            mb["total_tokens"] += record.total_tokens
            mb["estimated_cost_usd"] += record.estimated_cost_usd
            mb["call_count"] += 1

        return report

    def reset(self) -> None:
        """Clear all records and restart timer."""
        self._records.clear()
        self._start_time = time.monotonic()

    @property
    def total_cost(self) -> float:
        """Quick access to total estimated cost so far."""
        return sum(r.estimated_cost_usd for r in self._records)

    @property
    def total_tokens(self) -> int:
        """Quick access to total tokens used."""
        return sum(r.total_tokens for r in self._records)
