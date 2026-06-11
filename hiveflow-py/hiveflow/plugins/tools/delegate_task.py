"""DelegateTaskTool - Delegate sub-tasks to other agents.

Implements the delegate_task tool plugin that allows orchestrator agents
to delegate work to other agents in the collaboration runtime.
"""

from typing import Any

import structlog

from hiveflow.plugins.tools import ToolPlugin

logger = structlog.get_logger()


class DelegateTaskTool(ToolPlugin):
    """Tool for delegating sub-tasks to other agents.

    When an orchestrator agent calls this tool, the target agent executes
    the sub-task and returns its result. Supports auto-selection of the
    best agent, fallback agent creation, depth/timeout enforcement.
    """

    def __init__(self, runtime: Any, caller_agent_id: str, state: dict[str, Any]) -> None:
        """Initialize with runtime reference and caller identity.

        Args:
            runtime: CollaborationRuntime instance
            caller_agent_id: ID of the agent using this tool
            state: Workflow state dict (for sub-state propagation)
        """
        self._runtime = runtime
        self._caller_agent_id = caller_agent_id
        self._state = state

    @property
    def plugin_id(self) -> str:
        return "delegate_task"

    @property
    def description(self) -> str:
        return (
            "Delegate a sub-task to another agent or a sub-team. "
            "The task will be executed and the result returned to you."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "Clear description of the sub-task to delegate",
                },
                "delegate_to": {
                    "type": "string",
                    "description": (
                        "Agent ID to delegate to, or 'auto' to let the system choose the best agent"
                    ),
                },
                "context": {
                    "type": "object",
                    "description": "Additional context to pass to the delegate",
                },
                "expected_output": {
                    "type": "string",
                    "enum": ["text", "structured_data", "decision"],
                    "description": "What kind of output you expect back",
                },
                "chunk_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional chunk IDs to pass to the delegate. "
                        "When provided, only the specified data chunks are "
                        "included in the delegate's state."
                    ),
                },
            },
            "required": ["task"],
        }

    @property
    def output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["completed", "failed", "timeout"]},
                "result": {"type": "string"},
                "agent_id": {"type": "string"},
                "tokens_used": {"type": "integer"},
            },
        }

    async def execute(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        """Execute delegation to another agent.

        Args:
            tool_input: Dict with task, optional delegate_to/context/expected_output

        Returns:
            Dict with status, result, agent_id, tokens_used
        """

        from hiveflow.core.collaboration import BudgetExhaustedError

        task = tool_input["task"]
        delegate_to = tool_input.get("delegate_to", "auto")
        context = tool_input.get("context", {})

        # Current delegation depth
        depth = self._state.get("_delegation_depth", 0) + 1

        # Resolve target agent
        if delegate_to == "auto":
            delegate_to = self._runtime.select_best_agent(task)
            if delegate_to is None:
                # FR-003: Fallback — spawn a default llm_only agent
                delegate_to = self._spawn_fallback_agent(task)

        try:
            # Build state with context
            state = dict(self._state)
            if context:
                state.update(context)

            result_state = await self._runtime.delegate(
                task=task,
                delegate_to=delegate_to,
                delegated_by=self._caller_agent_id,
                state=state,
                depth=depth,
            )

            # Extract result
            output = result_state.get(f"{delegate_to}_output", "")
            tokens_used = None
            cost_data = result_state.get(f"{delegate_to}_cost")
            if isinstance(cost_data, dict):
                tokens_used = cost_data.get("total_tokens")

            return {
                "status": "completed",
                "result": str(output) if output else "",
                "agent_id": delegate_to,
                "tokens_used": tokens_used,
            }

        except TimeoutError:
            return {
                "status": "timeout",
                "result": f"Delegation to '{delegate_to}' timed out",
                "agent_id": delegate_to,
                "tokens_used": None,
            }

        except BudgetExhaustedError as e:
            return {
                "status": "failed",
                "result": f"Budget exhausted: {e}",
                "agent_id": delegate_to,
                "tokens_used": None,
            }

        except ValueError as e:
            # Depth limit, self-delegation, agent not found
            return {
                "status": "failed",
                "result": str(e),
                "agent_id": delegate_to,
                "tokens_used": None,
            }

        except Exception as e:
            logger.exception("Delegation failed: %s", e)
            return {
                "status": "failed",
                "result": f"Delegation error: {e}",
                "agent_id": delegate_to,
                "tokens_used": None,
            }

    def _spawn_fallback_agent(self, task: str) -> str:
        """Spawn a default llm_only agent as fallback.

        Args:
            task: Task description (used for naming)

        Returns:
            Agent ID of the spawned fallback agent
        """
        agent = self._runtime.spawn_from_definition(
            definition={
                "role": "General Assistant",
                "system_prompt": (
                    "You are a helpful general-purpose assistant. "
                    "Complete the assigned task to the best of your ability."
                ),
                "behavior_type": "llm_only",
                "tools": [],
            },
            spawned_by=self._caller_agent_id,
        )
        logger.info("Spawned fallback agent %s for task: %s", agent.agent_id, task[:100])
        return agent.agent_id
