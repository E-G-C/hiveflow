"""Tool Plugin Architecture - Extensible tool system for agents.

Tools are the primary extension point of the framework. Each tool is a
self-contained plugin that implements a standard interface and can be
developed independently.
"""

from abc import abstractmethod
from typing import Any

from hiveflow.core.registry import BasePlugin, PluginRegistry


class ToolPlugin(BasePlugin):
    """Base class for tool plugins.

    Every tool plugin must implement this interface:
    - plugin_id: Unique identifier (e.g., "web_search")
    - description: Natural-language description for LLM tool selection
    - input_schema: JSON Schema describing expected input
    - output_schema: JSON Schema describing output shape
    - execute(input): Runs the tool and returns results
    """

    @property
    @abstractmethod
    def plugin_id(self) -> str:
        """Unique identifier for this tool (e.g., 'web_search')."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Natural-language description used by LLM for tool selection."""
        ...

    @property
    @abstractmethod
    def input_schema(self) -> dict[str, Any]:
        """JSON Schema describing expected input."""
        ...

    @property
    @abstractmethod
    def output_schema(self) -> dict[str, Any]:
        """JSON Schema describing output shape."""
        ...

    @abstractmethod
    async def execute(self, tool_input: dict[str, Any]) -> dict[str, Any]:
        """Execute the tool with the given input.

        Args:
            tool_input: Input parameters matching input_schema

        Returns:
            Result matching output_schema
        """
        ...

    def to_llm_tool_spec(self) -> dict[str, Any]:
        """Convert to LLM function/tool calling spec.

        Returns a format compatible with OpenAI-style function calling.

        Returns:
            Tool specification dictionary
        """
        return {
            "type": "function",
            "function": {
                "name": self.plugin_id,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }


class ToolRegistry(PluginRegistry[ToolPlugin]):
    """Registry for tool plugins.

    Discovers tools from:
    - Python entry points under 'hiveflow.tools'
    - Drop-in directory at 'plugins/tools/'
    """

    def __init__(self, drop_in_dir: str | None = "plugins/tools") -> None:
        """Initialize tool registry.

        Args:
            drop_in_dir: Path to drop-in tools directory
        """
        super().__init__(
            entry_point_group="hiveflow.tools",
            drop_in_dir=drop_in_dir,
        )

    def get_tools_for_agent(self, tool_ids: list[str]) -> list[ToolPlugin]:
        """Look up multiple tools by ID for agent injection.

        Args:
            tool_ids: List of tool IDs to look up

        Returns:
            List of tool plugin instances

        Raises:
            KeyError: If any tool ID is not found
        """
        tools = []
        for tool_id in tool_ids:
            tools.append(self.get_or_raise(tool_id))
        return tools

    def get_llm_tool_specs(self, tool_ids: list[str]) -> list[dict[str, Any]]:
        """Get LLM tool calling specs for a list of tool IDs.

        Args:
            tool_ids: Tool IDs to generate specs for

        Returns:
            List of tool spec dictionaries
        """
        tools = self.get_tools_for_agent(tool_ids)
        return [tool.to_llm_tool_spec() for tool in tools]


# Global tool registry instance
_tool_registry: ToolRegistry | None = None


def get_tool_registry() -> ToolRegistry:
    """Get or create the global tool registry.

    Returns:
        ToolRegistry instance
    """
    global _tool_registry
    if _tool_registry is None:
        _tool_registry = ToolRegistry()
        _tool_registry.discover()
    return _tool_registry


def reset_tool_registry() -> None:
    """Reset global tool registry (mainly for testing)."""
    global _tool_registry
    _tool_registry = None
