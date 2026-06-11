"""Agent Skills Plugin - Open-standard skill system for HiveFlow agents.

Skills are prompt-based instruction packages that teach agents *how* to
approach specific categories of tasks.  They follow the `agentskills.io
<https://agentskills.io>`_ open standard:

* **Directory-based** — each skill is a folder with a ``SKILL.md`` file.
* **YAML frontmatter** — metadata (name, description, allowed-tools).
* **Progressive disclosure** — only metadata loaded at startup; full
  instructions loaded on activation.

Quick start::

    from hiveflow.plugins.skills import SkillRegistry

    registry = SkillRegistry()
    registry.discover()

    # List available skills
    print(registry.list_skills())

    # Get full skill
    skill = registry.get_skill("code-review")
    print(skill.instructions)
"""

from hiveflow.plugins.skills.activation_tool import SkillActivationTool
from hiveflow.plugins.skills.loader import SkillLoader
from hiveflow.plugins.skills.models import Skill, SkillMetadata
from hiveflow.plugins.skills.registry import (
    SkillRegistry,
    get_skill_registry,
    reset_skill_registry,
)

__all__ = [
    "Skill",
    "SkillActivationTool",
    "SkillLoader",
    "SkillMetadata",
    "SkillRegistry",
    "get_skill_registry",
    "reset_skill_registry",
]
