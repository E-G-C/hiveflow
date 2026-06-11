"""Tests for built-in skills validation.

Ensures all shipped skills parse correctly and contain
non-trivial content.
"""

from pathlib import Path

import pytest

from hiveflow.plugins.skills import SkillLoader, SkillRegistry

SKILLS_DIR = Path(__file__).parent.parent / "hiveflow" / "skills"
EXPECTED_SKILLS = {
    "code-review",
    "research-synthesis",
    "structured-extraction",
    "document-writing",
}


class TestBuiltinSkills:
    """Validate built-in skill definitions."""

    def test_skills_directory_exists(self) -> None:
        assert SKILLS_DIR.is_dir(), f"Missing skills directory: {SKILLS_DIR}"

    @pytest.mark.parametrize("name", sorted(EXPECTED_SKILLS))
    def test_skill_directory_exists(self, name: str) -> None:
        assert (SKILLS_DIR / name).is_dir(), f"Missing skill directory: {name}"

    @pytest.mark.parametrize("name", sorted(EXPECTED_SKILLS))
    def test_skill_md_exists(self, name: str) -> None:
        assert (SKILLS_DIR / name / "SKILL.md").is_file()

    @pytest.mark.parametrize("name", sorted(EXPECTED_SKILLS))
    def test_skill_parses_valid_metadata(self, name: str) -> None:
        meta = SkillLoader.load_metadata(SKILLS_DIR / name)
        assert meta is not None, f"Failed to parse {name}/SKILL.md"
        assert meta.name == name

    @pytest.mark.parametrize("name", sorted(EXPECTED_SKILLS))
    def test_skill_loads_fully(self, name: str) -> None:
        skill = SkillLoader.load_full(SKILLS_DIR / name, source="builtin")
        assert skill is not None
        assert len(skill.instructions) > 100, (
            f"Skill {name} has trivial instructions ({len(skill.instructions)} chars)"
        )

    @pytest.mark.parametrize("name", sorted(EXPECTED_SKILLS))
    def test_skill_has_description(self, name: str) -> None:
        meta = SkillLoader.load_metadata(SKILLS_DIR / name)
        assert meta is not None
        assert len(meta.description) >= 10

    def test_registry_discovers_all_builtins(self) -> None:
        registry = SkillRegistry(builtin_dir=SKILLS_DIR)
        registry.discover()
        found = set(registry.list_skills())
        assert EXPECTED_SKILLS.issubset(found), (
            f"Missing skills: {EXPECTED_SKILLS - found}"
        )

    def test_all_builtins_have_author_metadata(self) -> None:
        for name in EXPECTED_SKILLS:
            meta = SkillLoader.load_metadata(SKILLS_DIR / name)
            assert meta is not None
            assert "author" in meta.metadata, (
                f"Skill {name} missing author in metadata"
            )
