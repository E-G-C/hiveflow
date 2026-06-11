"""Skill Loader - Parses SKILL.md files into Skill objects.

Handles YAML frontmatter extraction, validation, and ``{baseDir}``
variable resolution in the instruction body.
"""

from pathlib import Path

import structlog
import yaml

from hiveflow.plugins.skills.models import Skill, SkillMetadata

logger = structlog.get_logger()


class SkillLoader:
    """Parses ``SKILL.md`` files following the agentskills.io spec.

    Two loading modes support progressive disclosure:

    * :meth:`load_metadata` -- frontmatter only (~100 tokens per skill).
    * :meth:`load_full` -- complete skill with instructions body.
    """

    @staticmethod
    def load_metadata(skill_dir: Path) -> SkillMetadata | None:
        """Load only the YAML frontmatter from a SKILL.md file.

        This is the *progressive disclosure* path: cheap to load,
        suitable for populating the ``<available_skills>`` prompt block.

        Args:
            skill_dir: Directory containing ``SKILL.md``.

        Returns:
            Parsed :class:`SkillMetadata`, or ``None`` on failure.
        """
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.is_file():
            return None

        try:
            content = skill_file.read_text(encoding="utf-8")
        except OSError:
            logger.warning("Cannot read %s", skill_file)
            return None

        frontmatter_str, _ = SkillLoader._split_frontmatter(content)
        if frontmatter_str is None:
            logger.warning("No YAML frontmatter in %s", skill_file)
            return None

        try:
            data = yaml.safe_load(frontmatter_str)
            if not isinstance(data, dict):
                logger.warning("Frontmatter is not a mapping in %s", skill_file)
                return None
            # Normalize kebab-case key from spec to snake_case
            if "allowed-tools" in data:
                data["allowed_tools"] = data.pop("allowed-tools")
            return SkillMetadata(**data)
        except Exception:
            logger.warning("Failed to parse SKILL.md frontmatter in %s", skill_dir)
            return None

    @staticmethod
    def load_full(skill_dir: Path, source: str = "builtin") -> Skill | None:
        """Load complete skill with metadata and instruction body.

        Args:
            skill_dir: Directory containing ``SKILL.md``.
            source: Discovery tier label (e.g. ``"builtin"``).

        Returns:
            Fully loaded :class:`Skill`, or ``None`` on failure.
        """
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.is_file():
            return None

        try:
            content = skill_file.read_text(encoding="utf-8")
        except OSError:
            logger.warning("Cannot read %s", skill_file)
            return None

        frontmatter_str, body = SkillLoader._split_frontmatter(content)
        if frontmatter_str is None:
            logger.warning("No YAML frontmatter in %s", skill_file)
            return None

        try:
            data = yaml.safe_load(frontmatter_str)
            if not isinstance(data, dict):
                logger.warning("Frontmatter is not a mapping in %s", skill_file)
                return None
            if "allowed-tools" in data:
                data["allowed_tools"] = data.pop("allowed-tools")
            metadata = SkillMetadata(**data)
        except Exception:
            logger.warning("Failed to parse SKILL.md in %s", skill_dir, exc_info=True)
            return None

        # Validate name matches directory (per agentskills.io spec)
        if metadata.name != skill_dir.name:
            logger.warning(
                "Skill name '%s' does not match directory '%s' — skipping",
                metadata.name,
                skill_dir.name,
            )
            return None

        # Resolve {baseDir} template variable in instructions
        instructions = body.replace("{baseDir}", str(skill_dir))

        return Skill(
            metadata=metadata,
            instructions=instructions,
            base_dir=skill_dir.resolve(),
            source=source,
        )

    @staticmethod
    def _split_frontmatter(content: str) -> tuple[str | None, str]:
        """Split a SKILL.md file into YAML frontmatter and Markdown body.

        Frontmatter is delimited by ``---`` markers at the start of the
        file.

        Returns:
            ``(frontmatter_yaml, body_markdown)`` or
            ``(None, full_content)`` if no frontmatter found.
        """
        content = content.lstrip()
        if not content.startswith("---"):
            return None, content

        # Find the closing --- delimiter
        end_idx = content.find("---", 3)
        if end_idx == -1:
            return None, content

        frontmatter = content[3:end_idx].strip()
        body = content[end_idx + 3 :].strip()
        return frontmatter, body
