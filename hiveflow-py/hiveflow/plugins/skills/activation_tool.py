"""Skill Activation Tool - ToolPlugin for dynamic skill loading.

For ``tool_user`` agents, this meta-tool lets the LLM load full skill
instructions on demand.  Only skill metadata is in the system prompt;
calling ``activate_skill`` returns the complete instruction body.
"""

from typing import Any

import structlog

from hiveflow.plugins.skills.models import Skill
from hiveflow.plugins.tools import ToolPlugin

logger = structlog.get_logger()


class SkillActivationTool(ToolPlugin):
    """Meta-tool that loads Agent Skill instructions on demand.

    When injected into a ``tool_user`` agent, this tool allows the LLM
    to select and activate a skill during the tool-calling loop.  The
    returned instructions are added to the conversation as a tool result.

    Follows the same :class:`~hiveflow.plugins.tools.ToolPlugin` interface
    as every other HiveFlow tool plugin.
    """

    def __init__(
        self,
        available_skills: dict[str, Skill],
    ) -> None:
        """Initialize with the set of skills available to this agent.

        Args:
            available_skills: Mapping of skill name -> Skill object.
        """
        self._skills = available_skills

    @property
    def plugin_id(self) -> str:
        return "activate_skill"

    @property
    def description(self) -> str:
        return (
            "Activate an agent skill to load detailed instructions for a "
            "specific task type. Call this when the current task matches "
            "one of the available skills listed in your context. Returns "
            "the full skill instructions to guide your approach."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        skill_names = sorted(self._skills.keys())
        return {
            "type": "object",
            "required": ["skill_name"],
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": (
                        f"Name of the skill to activate. Available: {', '.join(skill_names)}"
                    ),
                    "enum": skill_names,
                },
            },
            "additionalProperties": False,
        }

    @property
    def output_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "skill_name": {"type": "string"},
                "instructions": {"type": "string"},
                "base_dir": {"type": "string"},
                "allowed_tools": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "error": {"type": "string"},
            },
        }

    async def execute(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        """Load the full instructions for the requested skill.

        Args:
            tool_input: Must contain ``skill_name``.

        Returns:
            Dict with ``instructions``, ``base_dir``, and ``allowed_tools``,
            or ``error`` if the skill was not found.
        """
        skill_name = tool_input.get("skill_name", "")
        skill = self._skills.get(skill_name)

        if skill is None:
            available = sorted(self._skills.keys())
            logger.warning(
                "Skill activation failed: '%s' not found (available: %s)",
                skill_name,
                available,
            )
            return {
                "error": (f"Skill '{skill_name}' not found. Available: {available}"),
            }

        logger.info("Activated skill: %s (source=%s)", skill_name, skill.source)
        return {
            "skill_name": skill.name,
            "instructions": skill.instructions,
            "base_dir": str(skill.base_dir),
            "allowed_tools": skill.metadata.allowed_tools,
        }
