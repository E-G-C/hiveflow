"""Plugin Registry - Shared plugin discovery and registration infrastructure.

Provides base classes and registry for discovering plugins via:
1. Python entry points (primary) - pip installable packages
2. Drop-in directories (convenience) - local development
"""

import importlib
import importlib.metadata
import importlib.util
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Generic, TypeVar

import structlog

logger = structlog.get_logger()

T = TypeVar("T", bound="BasePlugin")


class BasePlugin(ABC):
    """Base class for all HiveFlow plugins."""

    @property
    @abstractmethod
    def plugin_id(self) -> str:
        """Unique identifier for this plugin."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description."""
        ...


class PluginRegistry(Generic[T]):
    """Generic plugin registry with discovery and validation.

    Discovers plugins from Python entry points and drop-in directories,
    validates them, and provides lookup by ID.
    """

    def __init__(
        self,
        entry_point_group: str,
        drop_in_dir: str | None = None,
    ) -> None:
        """Initialize plugin registry.

        Args:
            entry_point_group: Entry point group name (e.g. 'hiveflow.tools')
            drop_in_dir: Optional path to drop-in plugin directory
        """
        self._entry_point_group = entry_point_group
        self._drop_in_dir = drop_in_dir
        self._plugins: dict[str, T] = {}

    @property
    def plugins(self) -> dict[str, T]:
        """Get all registered plugins."""
        return dict(self._plugins)

    def get(self, plugin_id: str) -> T | None:
        """Look up a plugin by ID.

        Args:
            plugin_id: Plugin identifier

        Returns:
            Plugin instance or None if not found
        """
        return self._plugins.get(plugin_id)

    def get_or_raise(self, plugin_id: str) -> T:
        """Look up a plugin by ID, raising if not found.

        Args:
            plugin_id: Plugin identifier

        Returns:
            Plugin instance

        Raises:
            KeyError: If plugin not found
        """
        plugin = self._plugins.get(plugin_id)
        if plugin is None:
            available = ", ".join(sorted(self._plugins.keys()))
            raise KeyError(f"Plugin '{plugin_id}' not found. Available: {available or '(none)'}")
        return plugin

    def register(self, plugin: T) -> None:
        """Manually register a plugin instance.

        Args:
            plugin: Plugin instance to register
        """
        if not hasattr(plugin, "plugin_id") or not plugin.plugin_id:
            raise ValueError("Plugin must have a non-empty plugin_id")

        if plugin.plugin_id in self._plugins:
            logger.warning("Overwriting existing plugin: %s", plugin.plugin_id)

        self._plugins[plugin.plugin_id] = plugin
        logger.debug("Registered plugin: %s", plugin.plugin_id)

    def discover(self) -> None:
        """Discover and register plugins from entry points and drop-in directory."""
        self._discover_entry_points()
        if self._drop_in_dir:
            self._discover_drop_in(self._drop_in_dir)

    def _discover_entry_points(self) -> None:
        """Discover plugins from Python entry points."""
        try:
            group_eps = importlib.metadata.entry_points(group=self._entry_point_group)

            for ep in group_eps:
                try:
                    plugin_cls = ep.load()
                    plugin = plugin_cls() if isinstance(plugin_cls, type) else plugin_cls
                    self.register(plugin)
                    logger.info("Discovered plugin via entry point: %s", ep.name)
                except (ImportError, AttributeError, TypeError):
                    logger.exception("Failed to load plugin from entry point: %s", ep.name)
        except (TypeError, ValueError):
            logger.exception(
                "Failed to scan entry points for group: %s",
                self._entry_point_group,
            )

    def _discover_drop_in(self, directory: str) -> None:
        """Discover plugins from a drop-in directory.

        Args:
            directory: Path to the drop-in directory
        """
        drop_in_path = Path(directory)
        if not drop_in_path.is_dir():
            logger.debug("Drop-in directory does not exist: %s", directory)
            return

        for item in drop_in_path.iterdir():
            if item.is_dir() and (item / "__init__.py").exists():
                module_name = item.name
            elif item.is_file() and item.suffix == ".py" and item.name != "__init__.py":
                module_name = item.stem
            else:
                continue

            try:
                spec = importlib.util.spec_from_file_location(
                    module_name,
                    str(item / "__init__.py") if item.is_dir() else str(item),
                )
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)

                    # Look for plugin classes in the module
                    for attr_name in dir(module):
                        attr = getattr(module, attr_name)
                        if (
                            isinstance(attr, type)
                            and issubclass(attr, BasePlugin)
                            and attr is not BasePlugin
                            and not getattr(attr, "__abstractmethods__", None)
                        ):
                            try:
                                plugin = attr()
                                self.register(plugin)  # type: ignore[arg-type]
                                logger.info(
                                    "Discovered plugin from drop-in: %s",
                                    plugin.plugin_id,
                                )
                            except Exception:
                                logger.exception(
                                    "Failed to instantiate plugin: %s.%s",
                                    module_name,
                                    attr_name,
                                )
            except Exception:
                logger.exception("Failed to load drop-in module: %s", module_name)

    def list_ids(self) -> list[str]:
        """List all registered plugin IDs.

        Returns:
            Sorted list of plugin IDs
        """
        return sorted(self._plugins.keys())

    def __contains__(self, plugin_id: str) -> bool:
        return plugin_id in self._plugins

    def __len__(self) -> int:
        return len(self._plugins)

    def __repr__(self) -> str:
        return f"PluginRegistry(group={self._entry_point_group!r}, plugins={self.list_ids()})"
