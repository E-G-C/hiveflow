"""Source Mode — routing layer for data retrieval pipelines.

Controls which retrieval and ingestion plugins are active for a given
workflow run.  This is a task-level setting: different runs of the same
team configuration can use different source modes.

The source mode does **not** replace the plugin architecture — it selects
which subset of installed plugins participate in a given run.
"""

from enum import StrEnum
from typing import Any

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger()


class SourceMode(StrEnum):
    """Built-in source modes controlling data retrieval pipelines."""

    WEB = "web"  # Retriever + scraper plugins
    LOCAL = "local"  # Document loaders + local vector store
    HYBRID = "hybrid"  # Both web + local, merged & deduplicated
    CLOUD = "cloud"  # Cloud source plugins + document loaders
    MCP = "mcp"  # MCP client + connected MCP servers
    CUSTOM = "custom"  # Only explicitly listed plugins


class WebSourceOptions(BaseModel):
    """Options for web source mode."""

    retrievers: list[str] = Field(
        default_factory=list,
        description="Retriever plugin IDs to activate (empty = use config default)",
    )
    max_results_per_query: int = Field(default=10, description="Max results per retriever query")


class LocalSourceOptions(BaseModel):
    """Options for local source mode."""

    doc_path: str | None = Field(
        default=None,
        description="Path to local documents directory",
    )
    formats: list[str] = Field(
        default_factory=list,
        description="Allowed file formats (e.g. ['pdf', 'docx', 'md']). Empty = all.",
    )


class CloudSourceOptions(BaseModel):
    """Options for cloud source mode."""

    provider: str = Field(
        default="", description="Cloud provider plugin ID (e.g. 'azure_blob', 's3')"
    )
    container: str = Field(default="", description="Container or bucket name")
    path_prefix: str = Field(default="", description="Path prefix filter")


class SourceOptions(BaseModel):
    """Per-mode source configuration."""

    web: WebSourceOptions | None = Field(default=None, description="Web source mode options")
    local: LocalSourceOptions | None = Field(default=None, description="Local source mode options")
    cloud: CloudSourceOptions | None = Field(default=None, description="Cloud source mode options")
    custom_plugins: list[str] = Field(
        default_factory=list,
        description="Explicit plugin IDs for custom mode",
    )


# Tool categories activated by each source mode.
# Keys are SourceMode values; values are sets of tool "categories".
# Categories map to well-known plugin_id prefixes or exact IDs that the
# router uses to filter the tool registry.
_MODE_TOOL_CATEGORIES: dict[str, set[str]] = {
    SourceMode.WEB: {"web_search", "web_retriever", "scraper", "tavily", "duckduckgo"},
    SourceMode.LOCAL: {"document_retriever", "vector_store", "document_loader"},
    SourceMode.HYBRID: {
        "web_search",
        "web_retriever",
        "scraper",
        "tavily",
        "duckduckgo",
        "document_retriever",
        "vector_store",
        "document_loader",
    },
    SourceMode.CLOUD: {
        "cloud_source",
        "document_retriever",
        "document_loader",
    },
    SourceMode.MCP: {"mcp"},
    SourceMode.CUSTOM: set(),  # Determined by custom_plugins list
}


class SourceModeRouter:
    """Routes tool activation based on the active source mode.

    Sits between the tool registry and agent tool injection.  When a
    source mode is active, only tools whose ``plugin_id`` matches the
    allowed categories for that mode are passed through to agents.
    """

    def __init__(
        self,
        source_mode: str | SourceMode | None = None,
        source_options: SourceOptions | dict[str, Any] | None = None,
    ) -> None:
        if source_mode is None:
            self._mode: SourceMode | None = None
        else:
            self._mode = SourceMode(source_mode)

        if source_options is None:
            self._options = SourceOptions()
        elif isinstance(source_options, dict):
            self._options = SourceOptions(**source_options)
        else:
            self._options = source_options

    @property
    def mode(self) -> SourceMode | None:
        return self._mode

    @property
    def options(self) -> SourceOptions:
        return self._options

    @property
    def is_active(self) -> bool:
        """Whether source mode routing is enabled."""
        return self._mode is not None

    def get_allowed_categories(self) -> set[str]:
        """Return the set of allowed tool categories for the active mode."""
        if self._mode is None:
            return set()  # No filtering — all tools allowed
        if self._mode == SourceMode.CUSTOM:
            return set(self._options.custom_plugins)
        return _MODE_TOOL_CATEGORIES.get(self._mode, set())

    def filter_tools(self, tool_ids: list[str]) -> list[str]:
        """Filter a list of tool IDs to only those allowed by the active mode.

        When no source mode is set, all tools pass through unchanged.
        Internal framework tools (delegate_task, send_message, etc.) always
        pass through regardless of source mode.

        Args:
            tool_ids: Tool IDs declared on an agent definition.

        Returns:
            Filtered list of tool IDs.
        """
        if not self.is_active:
            return tool_ids

        allowed = self.get_allowed_categories()
        result = []
        for tid in tool_ids:
            if self._is_framework_tool(tid) or self._matches_categories(tid, allowed):
                result.append(tid)
        return result

    def _matches_categories(self, tool_id: str, categories: set[str]) -> bool:
        """Check if a tool_id matches any of the allowed categories.

        Matching rules:
        1. Exact match: tool_id is in the categories set.
        2. Prefix match: tool_id starts with a category + "_".
        """
        if tool_id in categories:
            return True
        return any(tool_id.startswith(cat + "_") for cat in categories)

    @staticmethod
    def _is_framework_tool(tool_id: str) -> bool:
        """Framework tools that should never be filtered out."""
        return tool_id in {
            "delegate_task",
            "send_message",
            "read_messages",
            "spawn_agent",
            "plan_and_execute",
            "skill_activation",
        }
