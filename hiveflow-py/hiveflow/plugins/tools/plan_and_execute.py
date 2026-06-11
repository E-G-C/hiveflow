"""PlanAndExecuteTool - Decompose tasks into structured plans and execute them.

Implements the plan_and_execute tool plugin that allows orchestrator agents
to create dependency-ordered sub-task plans and execute them with concurrent
independent sub-tasks.
"""

import uuid
from typing import Any

import structlog

from hiveflow.plugins.tools import ToolPlugin

logger = structlog.get_logger()


class PlanAndExecuteTool(ToolPlugin):
    """Tool for creating and executing structured task plans.

    When an orchestrator agent calls this tool, it creates a TaskPlan
    from the provided sub-tasks, validates the dependency DAG, executes
    sub-tasks in topological order (with concurrent independent tasks),
    and returns synthesized results.
    """

    def __init__(self, runtime: Any, caller_agent_id: str, state: dict[str, Any]) -> None:
        """Initialize with runtime reference and caller identity.

        Args:
            runtime: CollaborationRuntime instance
            caller_agent_id: ID of the agent using this tool
            state: Workflow state dict
        """
        self._runtime = runtime
        self._caller_agent_id = caller_agent_id
        self._state = state

    @property
    def plugin_id(self) -> str:
        return "plan_and_execute"

    @property
    def description(self) -> str:
        return (
            "Decompose a complex task into a dependency-ordered plan of sub-tasks "
            "and execute them. Independent sub-tasks run concurrently. Each sub-task "
            "is delegated to an agent (by ID, 'auto' for best match, or "
            "'spawn:{archetype}' to create a new agent)."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "plan": {
                    "type": "object",
                    "description": "The task plan to execute",
                    "properties": {
                        "sub_tasks": {
                            "type": "array",
                            "description": "Ordered list of sub-tasks",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {
                                        "type": "string",
                                        "description": "Unique ID for this sub-task (e.g., 'st_1')",
                                    },
                                    "description": {
                                        "type": "string",
                                        "description": "What needs to be done",
                                    },
                                    "assigned_to": {
                                        "type": "string",
                                        "description": (
                                            "Agent ID, 'auto' for best match, or "
                                            "'spawn:{archetype}' to create a new agent"
                                        ),
                                    },
                                    "depends_on": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                        "description": "IDs of prerequisite sub-tasks",
                                    },
                                    "expected_output": {
                                        "type": "string",
                                        "enum": ["text", "structured_data", "decision"],
                                        "description": "What kind of output to expect",
                                    },
                                },
                                "required": ["id", "description"],
                            },
                        },
                    },
                    "required": ["sub_tasks"],
                },
            },
            "required": ["plan"],
        }

    @property
    def output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["completed", "partial", "failed"]},
                "results": {
                    "type": "object",
                    "description": "Mapping of sub-task ID to result",
                },
                "sub_task_statuses": {
                    "type": "object",
                    "description": "Mapping of sub-task ID to status",
                },
                "plan_id": {"type": "string"},
            },
        }

    async def execute(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        """Create and execute a task plan.

        Args:
            tool_input: Dict with plan containing sub_tasks array

        Returns:
            Dict with status, results, sub_task_statuses, plan_id
        """
        from hiveflow.core.collaboration import SubTask, TaskPlan

        plan_input = tool_input.get("plan", {})
        sub_tasks_input = plan_input.get("sub_tasks", [])

        if not sub_tasks_input:
            return {
                "status": "failed",
                "results": {},
                "sub_task_statuses": {},
                "plan_id": "",
                "error": "No sub-tasks provided",
            }

        # Build SubTask instances
        sub_tasks = []
        for st_input in sub_tasks_input:
            sub_tasks.append(
                SubTask(
                    id=st_input["id"],
                    description=st_input["description"],
                    assigned_to=st_input.get("assigned_to", "auto"),
                    depends_on=st_input.get("depends_on", []),
                    expected_output=st_input.get("expected_output", "text"),
                )
            )

        # Build plan
        plan = TaskPlan(
            plan_id=str(uuid.uuid4()),
            created_by=self._caller_agent_id,
            sub_tasks=sub_tasks,
        )

        # Current delegation depth
        depth = self._state.get("_delegation_depth", 0) + 1

        try:
            results = await self._runtime.execute_plan(
                plan=plan,
                state=self._state,
                caller_agent_id=self._caller_agent_id,
                depth=depth,
            )

            # Collect statuses
            sub_task_statuses = {st.id: st.status for st in plan.sub_tasks}

            # Determine overall status
            statuses = set(sub_task_statuses.values())
            if statuses == {"completed"}:
                overall_status = "completed"
            elif "completed" in statuses:
                overall_status = "partial"
            else:
                overall_status = "failed"

            return {
                "status": overall_status,
                "results": results,
                "sub_task_statuses": sub_task_statuses,
                "plan_id": plan.plan_id,
            }

        except ValueError as e:
            return {
                "status": "failed",
                "results": {},
                "sub_task_statuses": {},
                "plan_id": plan.plan_id,
                "error": str(e),
            }

        except Exception as e:
            logger.exception("Plan execution failed: %s", e)
            return {
                "status": "failed",
                "results": {},
                "sub_task_statuses": {},
                "plan_id": plan.plan_id,
                "error": f"Plan execution error: {e}",
            }
