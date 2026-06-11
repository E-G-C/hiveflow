"""Skill Registry - Filesystem-based discovery and lookup for Agent Skills.

Discovers skills from multiple directory tiers with priority override:

1. **user**     — ``~/.config/hiveflow/skills/`` (or ``HIVEFLOW_SKILLS_DIR``)
2. **project**  — ``.hiveflow/skills/`` (relative to working directory)
3. **entrypoint** — Python entry points under ``hiveflow.skills``
4. **builtin**  — ``hiveflow/skills/`` (shipped with the package)

Higher-priority tiers override lower ones on name collision.
"""

import importlib.metadata
import os
from pathlib import Path

import structlog

from hiveflow.plugins.skills.loader import SkillLoader
from hiveflow.plugins.skills.models import Skill, SkillMetadata

logger = structlog.get_logger()


class SkillRegistry:
    """Registry for discovering and managing Agent Skills.

    Unlike :class:`~hiveflow.core.registry.PluginRegistry`, this is a
    filesystem-based registry — skills are Markdown files, not Python
    modules.

    Usage::

        registry = SkillRegistry()
        registry.discover()
        skill = registry.get_skill("code-review")
    """

    def __init__(
        self,
        builtin_dir: Path | None = None,
        project_dir: Path | None = None,
        user_dir: Path | None = None,
        extra_dirs: list[Path] | None = None,
    ) -> None:
        """Initialize the skill registry.

        Args:
            builtin_dir: Path to built-in skills (default: ``hiveflow/skills/``).
            project_dir: Path to project skills (default: ``.hiveflow/skills/``).
            user_dir: Path to user skills (default: ``~/.config/hiveflow/skills/``).
            extra_dirs: Additional directories to scan for skills.
        """
        self._builtin_dir = builtin_dir or (Path(__file__).parent.parent.parent / "skills")
        self._project_dir = project_dir
        self._user_dir = user_dir
        self._extra_dirs = extra_dirs or []

        # name -> (SkillMetadata, skill_dir, source)
        self._metadata: dict[str, tuple[SkillMetadata, Path, str]] = {}
        # name -> Skill (lazily populated on first access)
        self._loaded: dict[str, Skill] = {}

    def discover(self) -> None:
        """Scan all tiers and load skill metadata (frontmatter only).

        Lower-priority tiers are scanned first; higher-priority tiers
        overwrite on name collision.
        """
        self._metadata.clear()
        self._loaded.clear()

        # Lowest priority first
        self._scan_dir(self._builtin_dir, "builtin")
        self._scan_entry_points()
        for extra in self._extra_dirs:
            self._scan_dir(extra, "extra")
        if self._project_dir:
            self._scan_dir(self._project_dir, "project")
        if self._user_dir:
            self._scan_dir(self._user_dir, "user")

        logger.info(
            "Discovered %d skill(s): %s",
            len(self._metadata),
            ", ".join(sorted(self._metadata)),
        )

    def _scan_dir(self, directory: Path | None, source: str) -> None:
        """Scan a directory for skill subdirectories containing SKILL.md."""
        if directory is None or not directory.is_dir():
            return

        for child in sorted(directory.iterdir()):
            if child.is_dir() and (child / "SKILL.md").is_file():
                meta = SkillLoader.load_metadata(child)
                if meta is not None:
                    if meta.name in self._metadata:
                        prev_source = self._metadata[meta.name][2]
                        logger.debug(
                            "Skill '%s' from %s overrides %s",
                            meta.name,
                            source,
                            prev_source,
                        )
                    self._metadata[meta.name] = (meta, child, source)
                    # Invalidate cached full load
                    self._loaded.pop(meta.name, None)
                    logger.debug("Discovered skill: %s (%s)", meta.name, source)

    def _scan_entry_points(self) -> None:
        """Discover skills from Python entry points ``hiveflow.skills``.

        Each entry point should resolve to either a ``Path`` or a
        callable returning a ``Path`` to a directory containing skill
        subdirectories.
        """
        try:
            eps = importlib.metadata.entry_points(group="hiveflow.skills")
            for ep in eps:
                try:
                    obj = ep.load()
                    skill_dir = obj() if callable(obj) else obj
                    if isinstance(skill_dir, (str, Path)):
                        self._scan_dir(Path(skill_dir), "entrypoint")
                except Exception:
                    logger.warning("Failed to load skill entry point: %s", ep.name)
        except Exception:
            logger.debug("No skill entry points found")

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def list_skills(self) -> list[str]:
        """Return all discovered skill names, sorted alphabetically."""
        return sorted(self._metadata.keys())

    def get_metadata(self, name: str) -> SkillMetadata | None:
        """Get frontmatter metadata for a skill by name."""
        entry = self._metadata.get(name)
        return entry[0] if entry else None

    def get_skill(self, name: str) -> Skill | None:
        """Load and return the full skill (lazily cached).

        Returns ``None`` if the skill does not exist or fails to load.
        """
        if name in self._loaded:
            return self._loaded[name]

        entry = self._metadata.get(name)
        if entry is None:
            return None

        _meta, skill_dir, source = entry
        skill = SkillLoader.load_full(skill_dir, source=source)
        if skill is not None:
            self._loaded[name] = skill
        return skill

    def get_or_raise(self, name: str) -> Skill:
        """Load skill or raise :exc:`KeyError`."""
        skill = self.get_skill(name)
        if skill is None:
            available = ", ".join(self.list_skills())
            raise KeyError(f"Skill '{name}' not found. Available: {available or '(none)'}")
        return skill

    def get_skills(self, names: list[str]) -> list[Skill]:
        """Load multiple skills by name, raising on any missing.

        Args:
            names: List of skill names.

        Returns:
            Ordered list of :class:`Skill` instances.

        Raises:
            KeyError: If any skill is not found.
        """
        return [self.get_or_raise(name) for name in names]

    # ------------------------------------------------------------------
    # Prompt generation
    # ------------------------------------------------------------------

    def get_prompt_section(self, names: list[str] | None = None) -> str:
        """Generate ``<available_skills>`` XML for system prompt injection.

        Per the agentskills.io integration guide, uses XML format with
        ``name`` and ``description`` for each skill.

        Args:
            names: Specific skill names.  ``None`` = all discovered.

        Returns:
            XML string suitable for system prompt injection.
        """
        target_names = names if names is not None else self.list_skills()
        if not target_names:
            return ""

        lines = ["<available_skills>"]
        for name in target_names:
            entry = self._metadata.get(name)
            if entry is None:
                continue
            meta, skill_dir, _ = entry
            lines.append("  <skill>")
            lines.append(f"    <name>{meta.name}</name>")
            lines.append(f"    <description>{meta.description}</description>")
            lines.append(f"    <location>{skill_dir / 'SKILL.md'}</location>")
            lines.append("  </skill>")
        lines.append("</available_skills>")
        return "\n".join(lines)

    def get_full_instructions_section(self, names: list[str]) -> str:
        """Generate system prompt section with full skill instructions.

        Used for ``llm_only`` agents that cannot dynamically activate.

        Args:
            names: Skill names to include fully.

        Returns:
            Formatted instruction block for system prompt.
        """
        parts = []
        for name in names:
            skill = self.get_skill(name)
            if skill is None:
                continue
            parts.append(f'<skill name="{skill.name}">')
            parts.append(skill.instructions)
            parts.append("</skill>")
        return "\n\n".join(parts) if parts else ""

    # ------------------------------------------------------------------
    # Manual registration (for testing / programmatic use)
    # ------------------------------------------------------------------

    def register(self, skill: Skill) -> None:
        """Manually register a skill instance."""
        self._metadata[skill.name] = (
            skill.metadata,
            skill.base_dir,
            skill.source,
        )
        self._loaded[skill.name] = skill

    # ------------------------------------------------------------------
    # Container protocol
    # ------------------------------------------------------------------

    def __contains__(self, name: str) -> bool:
        return name in self._metadata

    def __len__(self) -> int:
        return len(self._metadata)

    def __repr__(self) -> str:
        return f"SkillRegistry(skills={self.list_skills()})"


# ======================================================================
# Global singleton
# ======================================================================

_skill_registry: SkillRegistry | None = None


def get_skill_registry() -> SkillRegistry:
    """Get or create the global skill registry.

    On first call, discovers skills from all default tiers.
    """
    global _skill_registry
    if _skill_registry is None:
        user_dir = Path(
            os.environ.get(
                "HIVEFLOW_SKILLS_DIR",
                str(Path.home() / ".config" / "hiveflow" / "skills"),
            )
        )
        project_dir = Path.cwd() / ".hiveflow" / "skills"
        _skill_registry = SkillRegistry(
            user_dir=user_dir,
            project_dir=project_dir,
        )
        _skill_registry.discover()
    return _skill_registry


def reset_skill_registry() -> None:
    """Reset global skill registry (mainly for testing)."""
    global _skill_registry
    _skill_registry = None
