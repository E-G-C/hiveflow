"""Agent Skill Models - Data structures for the Agent Skills system.

Skills are prompt-based instruction packages that teach agents HOW to
approach specific tasks. They follow the agentskills.io open standard:
directory-based, SKILL.md format with YAML frontmatter + Markdown body.
"""

import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator


class SkillMetadata(BaseModel):
    """YAML frontmatter from a SKILL.md file.

    Follows the agentskills.io specification. Required fields are ``name``
    and ``description``; all others are optional.

    Example frontmatter::

        ---
        name: code-review
        description: Perform systematic code reviews on source code.
        license: Apache-2.0
        metadata:
          author: hiveflow
          version: "1.0"
        allowed-tools: Bash Read
        ---
    """

    name: str = Field(
        ...,
        min_length=1,
        max_length=64,
        description=(
            "Skill identifier: lowercase alphanumeric + hyphens. "
            "Must match the parent directory name."
        ),
    )
    description: str = Field(
        ...,
        min_length=1,
        max_length=1024,
        description="What this skill does and when to use it.",
    )
    license: str | None = Field(
        default=None,
        description="License name or reference to bundled license file.",
    )
    compatibility: str | None = Field(
        default=None,
        max_length=500,
        description="Environment requirements (system packages, etc.).",
    )
    metadata: dict[str, str] = Field(
        default_factory=dict,
        description="Arbitrary key-value metadata (author, version, tags, etc.).",
    )
    allowed_tools: list[str] = Field(
        default_factory=list,
        description="Pre-approved tool IDs this skill may use.",
    )

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Enforce agentskills.io name constraints.

        - Lowercase letters, numbers, and single hyphens only.
        - Must not start or end with a hyphen.
        - No consecutive hyphens.
        """
        if not re.match(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$", v):
            raise ValueError(
                "Skill name must contain only lowercase letters, numbers, "
                "and hyphens, and must not start or end with a hyphen"
            )
        if "--" in v:
            raise ValueError("Skill name must not contain consecutive hyphens")
        return v

    @field_validator("allowed_tools", mode="before")
    @classmethod
    def parse_allowed_tools(cls, v: Any) -> list[str]:
        """Parse space-delimited string to list (per agentskills.io spec)."""
        if isinstance(v, str):
            return v.split() if v.strip() else []
        return v


class Skill:
    """A fully loaded skill with metadata and instruction body.

    Attributes:
        metadata: Parsed YAML frontmatter.
        instructions: Full Markdown body below the frontmatter.
        base_dir: Absolute path to the skill directory (for resolving
            scripts/, references/, and assets/ subdirectories).
        source: Discovery tier label (``"builtin"``, ``"project"``,
            ``"user"``, or ``"entrypoint"``).
    """

    __slots__ = ("metadata", "instructions", "base_dir", "source")

    def __init__(
        self,
        metadata: SkillMetadata,
        instructions: str,
        base_dir: Path,
        source: str = "builtin",
    ) -> None:
        self.metadata = metadata
        self.instructions = instructions
        self.base_dir = base_dir
        self.source = source

    @property
    def name(self) -> str:
        """Shortcut to ``metadata.name``."""
        return self.metadata.name

    @property
    def description(self) -> str:
        """Shortcut to ``metadata.description``."""
        return self.metadata.description

    @property
    def token_estimate(self) -> int:
        """Rough token estimate for the instructions body (~0.75 words/token)."""
        word_count = len(self.instructions.split())
        return int(word_count / 0.75)

    def __repr__(self) -> str:
        return f"Skill(name={self.name!r}, source={self.source!r}, ~{self.token_estimate} tokens)"
