"""Result Payload - Structured output of a completed workflow.

Assembles the final content, per-section breakdown, metadata, references,
actions, and cost summary into a single immutable data model that publishers
consume to render output documents.
"""

import time
from dataclasses import dataclass, field
from typing import Any

import structlog

from hiveflow.core.citations import Citation
from hiveflow.core.cost import WorkflowCostReport

logger = structlog.get_logger()


@dataclass(frozen=True)
class ActionRecord:
    """A real-world action taken during workflow execution.

    Attributes:
        action_id: Unique identifier for this action.
        action_type: Category (e.g. "email", "api_call", "file_write").
        description: Human-readable description of what was done.
        status: One of "completed", "failed", "pending", "approved", "rejected".
        agent_id: The agent that initiated this action.
        timestamp: Unix timestamp of execution.
        metadata: Action-specific details.
    """

    action_id: str
    action_type: str
    description: str
    status: str
    agent_id: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)
    policy: str | None = None
    approved_by: str | None = None
    reversible: bool = False
    rollback_action: str | None = None
    workflow_run_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        result = {
            "action_id": self.action_id,
            "action_type": self.action_type,
            "description": self.description,
            "status": self.status,
            "agent_id": self.agent_id,
            "timestamp": self.timestamp,
            "metadata": dict(self.metadata),
            "policy": self.policy,
            "approved_by": self.approved_by,
            "reversible": self.reversible,
            "rollback_action": self.rollback_action,
            "workflow_run_id": self.workflow_run_id,
        }
        return result


@dataclass(frozen=True)
class PayloadSection:
    """A named block of content within a ResultPayload.

    Attributes:
        section_id: Machine-readable identifier (e.g. "executive_summary").
        title: Human-readable section heading.
        content: Markdown content for this section.
        order: Sort position within the payload.
        agent_id: The agent that produced this section, if attributable.
    """

    section_id: str
    title: str
    content: str
    order: int
    agent_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dictionary."""
        result: dict[str, Any] = {
            "section_id": self.section_id,
            "title": self.title,
            "content": self.content,
            "order": self.order,
        }
        if self.agent_id is not None:
            result["agent_id"] = self.agent_id
        return result


@dataclass(frozen=True)
class ResultPayload:
    """Structured output of a completed workflow execution.

    Contains the full assembled content, per-section breakdown, metadata,
    references/citations, actions taken, cost summary, and step results.
    Immutable after creation — publishers read from this, never modify it.

    Attributes:
        title: Workflow title (from task description or team config).
        content: Full assembled text output.
        sections: Ordered named content blocks.
        metadata: Arbitrary key-value pairs (date, workflow_id, duration, etc.).
        references: Cited sources (reuses existing Citation dataclass).
        actions: Real-world actions taken during execution.
        cost_summary: Per-agent and total token/cost figures.
        step_results: Per-step execution details from the workflow engine.
    """

    title: str
    content: str
    sections: list[PayloadSection] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    references: list[Citation] = field(default_factory=list)
    actions: list[ActionRecord] = field(default_factory=list)
    cost_summary: WorkflowCostReport = field(default_factory=WorkflowCostReport)
    step_results: list[Any] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the entire payload to a JSON-compatible dictionary.

        Returns:
            A dictionary containing all payload fields, suitable for
            JSON serialization or direct consumption by the JSON publisher.
        """
        return {
            "title": self.title,
            "content": self.content,
            "sections": [s.to_dict() for s in self.sections],
            "metadata": dict(self.metadata),
            "references": [
                {
                    "url": ref.url,
                    "title": ref.title,
                    "content_snippet": ref.content_snippet,
                    "author": ref.author,
                    "date": ref.date,
                    "source_type": ref.source_type,
                }
                for ref in self.references
            ],
            "actions": [a.to_dict() for a in self.actions],
            "cost_summary": {
                "total_prompt_tokens": self.cost_summary.total_prompt_tokens,
                "total_completion_tokens": self.cost_summary.total_completion_tokens,
                "total_tokens": self.cost_summary.total_tokens,
                "total_estimated_cost_usd": self.cost_summary.total_estimated_cost_usd,
                "agent_summaries": {
                    agent_id: {
                        "agent_id": summary.agent_id,
                        "total_prompt_tokens": summary.total_prompt_tokens,
                        "total_completion_tokens": summary.total_completion_tokens,
                        "total_tokens": summary.total_tokens,
                        "total_estimated_cost_usd": summary.total_estimated_cost_usd,
                        "call_count": summary.call_count,
                    }
                    for agent_id, summary in self.cost_summary.agent_summaries.items()
                },
                "duration_seconds": self.cost_summary.duration_seconds,
            },
            "step_results": [
                {
                    "agent_id": sr.agent_id,
                    "step_type": sr.step_type,
                    "status": sr.status,
                    "error": sr.error,
                }
                if hasattr(sr, "agent_id")
                else sr
                for sr in self.step_results
            ],
        }

    @classmethod
    def from_workflow_result(
        cls,
        result: Any,
        *,
        cost_report: WorkflowCostReport | None = None,
        citations: list[Citation] | None = None,
        title: str | None = None,
        actions: list[ActionRecord] | None = None,
    ) -> "ResultPayload":
        """Assemble a ResultPayload from a WorkflowResult.

        This class method extracts content, metadata, and step results from
        an executed workflow and combines them with optional cost, citation,
        and action data into a single structured payload.

        Args:
            result: A WorkflowResult (or compatible object with .status,
                .state, .step_results, and optional .error).
            cost_report: Aggregated cost/token report for the workflow run.
            citations: List of source citations gathered during execution.
            title: Override title. Defaults to state["task"] if present.
            actions: List of actions taken during execution.

        Returns:
            An immutable ResultPayload ready for publishing.
        """
        state = getattr(result, "state", {}) or {}
        step_results_raw = getattr(result, "step_results", []) or []
        status = getattr(result, "status", None)

        # Derive title: explicit override > state report_title > raw task
        resolved_title = (
            title or state.get("report_title") or state.get("task", "Untitled Workflow")
        )

        # Assemble full content from the last agent's output or final_output
        content = state.get("final_output", "")
        if not content:
            # Fall back to the last history entry
            history = state.get("history", [])
            if history:
                last_entry = history[-1]
                if isinstance(last_entry, dict):
                    content = last_entry.get("output", "")

        # Build sections from agent history
        sections: list[PayloadSection] = []
        history = state.get("history", [])
        for idx, entry in enumerate(history):
            if isinstance(entry, dict):
                agent_id = entry.get("agent_id", f"agent_{idx}")
                output = entry.get("output", "")
                if output:
                    sections.append(
                        PayloadSection(
                            section_id=f"agent_{agent_id}",
                            title=entry.get("role", agent_id),
                            content=output,
                            order=idx,
                            agent_id=agent_id,
                        )
                    )

        # Build metadata
        metadata: dict[str, Any] = {
            "status": status.value if hasattr(status, "value") else str(status),
        }
        if "workflow_id" in state:
            metadata["workflow_id"] = state["workflow_id"]

        logger.info(
            "Assembled ResultPayload",
            extra={
                "title": resolved_title,
                "section_count": len(sections),
                "reference_count": len(citations or []),
                "action_count": len(actions or []),
            },
        )

        return cls(
            title=resolved_title,
            content=content,
            sections=sections,
            metadata=metadata,
            references=citations or [],
            actions=actions or [],
            cost_summary=cost_report or WorkflowCostReport(),
            step_results=list(step_results_raw),
        )
