"""SpawnAgentTool - Dynamically create specialist agents.

Implements the spawn_agent tool plugin that allows orchestrator agents
to create new agents from archetypes or custom definitions at runtime.
"""

from typing import Any

import structlog

from hiveflow.plugins.tools import ToolPlugin

logger = structlog.get_logger()


class SpawnAgentTool(ToolPlugin):
    """Tool for spawning new specialist agents at runtime.

    Allows orchestrators to create agents from the archetype library
    or from custom inline definitions. Spawned agents can then be
    used with delegate_task.
    """

    def __init__(self, runtime: Any, caller_agent_id: str) -> None:
        """Initialize with runtime reference and caller identity.

        Args:
            runtime: CollaborationRuntime instance
            caller_agent_id: ID of the agent using this tool
        """
        self._runtime = runtime
        self._caller_agent_id = caller_agent_id

    @property
    def plugin_id(self) -> str:
        return "spawn_agent"

    @property
    def description(self) -> str:
        archetypes = self._get_available_archetypes()
        if archetypes:
            archetype_list = ", ".join(archetypes)
            return (
                "Create a new specialist agent from an archetype or custom definition. "
                "Returns the agent's ID for use with delegate_task. "
                f"Available archetypes: {archetype_list}"
            )
        return (
            "Create a new specialist agent from an archetype or custom definition. "
            "Returns the agent's ID for use with delegate_task."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "archetype": {
                    "type": "string",
                    "description": (
                        "Name of an archetype from the library "
                        "(e.g., 'researcher', 'writer', 'reviewer'). "
                        "Use the tool description to see available options."
                    ),
                },
                "custom_definition": {
                    "type": "object",
                    "description": "Inline agent definition if no archetype fits.",
                    "properties": {
                        "role": {"type": "string", "description": "Agent role name"},
                        "system_prompt": {
                            "type": "string",
                            "description": "System prompt for the agent",
                        },
                        "behavior_type": {
                            "type": "string",
                            "enum": ["llm_only", "tool_user"],
                            "default": "llm_only",
                        },
                        "tools": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Tool IDs (must be subset of parent tools)",
                        },
                    },
                    "required": ["role", "system_prompt"],
                },
                "agent_id": {
                    "type": "string",
                    "description": "Optional custom ID. Auto-generated if omitted.",
                },
            },
        }

    @property
    def output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["spawned", "failed"]},
                "agent_id": {"type": "string"},
                "role": {"type": "string"},
                "available_tools": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
        }

    async def execute(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        """Spawn a new agent from archetype or custom definition.

        Args:
            tool_input: Dict with archetype or custom_definition, optional agent_id

        Returns:
            Dict with status, agent_id, role, available_tools
        """
        archetype_name = tool_input.get("archetype")
        custom_def = tool_input.get("custom_definition")
        agent_id = tool_input.get("agent_id")

        # Get parent agent's tools for scoping
        parent_agent = self._runtime.get_agent(self._caller_agent_id)
        parent_tools = parent_agent.tools if parent_agent else None

        try:
            if archetype_name:
                agent = self._runtime.spawn_from_archetype(
                    archetype_name=archetype_name,
                    spawned_by=self._caller_agent_id,
                    agent_id=agent_id,
                    parent_tools=parent_tools,
                )
            elif custom_def:
                agent = self._runtime.spawn_from_definition(
                    definition=custom_def,
                    spawned_by=self._caller_agent_id,
                    agent_id=agent_id,
                    parent_tools=parent_tools,
                )
            else:
                available = self._get_available_archetypes()
                return {
                    "status": "failed",
                    "agent_id": "",
                    "role": "",
                    "available_tools": [],
                    "error": (
                        "Either 'archetype' or 'custom_definition' is required. "
                        f"Available archetypes: {', '.join(available)}"
                        if available
                        else "Either 'archetype' or 'custom_definition' is required."
                    ),
                }

            tool_ids = [t.plugin_id for t in agent.tools] if agent.tools else []

            return {
                "status": "spawned",
                "agent_id": agent.agent_id,
                "role": agent.role,
                "available_tools": tool_ids,
            }

        except ValueError as e:
            error_msg = str(e)
            # If archetype not found, include available list
            if "not found" in error_msg.lower():
                available = self._get_available_archetypes()
                if available:
                    error_msg += f". Available archetypes: {', '.join(available)}"

            return {
                "status": "failed",
                "agent_id": "",
                "role": "",
                "available_tools": [],
                "error": error_msg,
            }

        except Exception as e:
            logger.exception("Spawn failed: %s", e)
            return {
                "status": "failed",
                "agent_id": "",
                "role": "",
                "available_tools": [],
                "error": f"Spawn error: {e}",
            }

    def _get_available_archetypes(self) -> list[str]:
        """Get list of available archetype names from the library."""
        lib = self._runtime._archetype_library
        if lib is not None and hasattr(lib, "list_archetypes"):
            try:
                return lib.list_archetypes()
            except Exception:
                pass
        return []
