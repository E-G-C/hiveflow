"""Tests for Agent Skills system.

Verifies:
- SKILL.md parsing (frontmatter + body extraction)
- SkillMetadata validation (name format, description length)
- SkillRegistry discovery across priority tiers
- SkillActivationTool execution
- Agent system prompt injection (llm_only vs tool_user)
- TeamGenerator.build() skill resolution
- Progressive disclosure (metadata-only vs full load)
- Name collision priority (user > project > builtin)
- Error handling (missing skills, invalid SKILL.md)
"""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from hiveflow.plugins.skills import (
    Skill,
    SkillActivationTool,
    SkillLoader,
    SkillMetadata,
    SkillRegistry,
)


# ======================================================================
# SkillMetadata validation
# ======================================================================


class TestSkillMetadata:
    """Pydantic validation for SkillMetadata."""

    def test_valid_name(self) -> None:
        meta = SkillMetadata(name="code-review", description="Review code.")
        assert meta.name == "code-review"

    def test_valid_single_char_name(self) -> None:
        meta = SkillMetadata(name="x", description="Test.")
        assert meta.name == "x"

    def test_valid_numeric_name(self) -> None:
        meta = SkillMetadata(name="v2", description="Test.")
        assert meta.name == "v2"

    def test_name_rejects_uppercase(self) -> None:
        with pytest.raises(ValueError, match="lowercase"):
            SkillMetadata(name="Code-Review", description="Review code.")

    def test_name_rejects_leading_hyphen(self) -> None:
        with pytest.raises(ValueError):
            SkillMetadata(name="-code", description="Review code.")

    def test_name_rejects_trailing_hyphen(self) -> None:
        with pytest.raises(ValueError):
            SkillMetadata(name="code-", description="Review code.")

    def test_name_rejects_consecutive_hyphens(self) -> None:
        with pytest.raises(ValueError, match="consecutive"):
            SkillMetadata(name="code--review", description="Review code.")

    def test_name_rejects_spaces(self) -> None:
        with pytest.raises(ValueError):
            SkillMetadata(name="code review", description="Review code.")

    def test_name_rejects_empty(self) -> None:
        with pytest.raises(ValueError):
            SkillMetadata(name="", description="Review code.")

    def test_name_rejects_too_long(self) -> None:
        with pytest.raises(ValueError):
            SkillMetadata(name="a" * 65, description="Review code.")

    def test_description_max_length(self) -> None:
        with pytest.raises(ValueError):
            SkillMetadata(name="test", description="x" * 1025)

    def test_description_rejects_empty(self) -> None:
        with pytest.raises(ValueError):
            SkillMetadata(name="test", description="")

    def test_allowed_tools_from_string(self) -> None:
        meta = SkillMetadata(
            name="test",
            description="Test.",
            allowed_tools="Bash Read Write",
        )
        assert meta.allowed_tools == ["Bash", "Read", "Write"]

    def test_allowed_tools_from_list(self) -> None:
        meta = SkillMetadata(
            name="test",
            description="Test.",
            allowed_tools=["Bash", "Read"],
        )
        assert meta.allowed_tools == ["Bash", "Read"]

    def test_allowed_tools_empty_string(self) -> None:
        meta = SkillMetadata(
            name="test",
            description="Test.",
            allowed_tools="",
        )
        assert meta.allowed_tools == []

    def test_optional_fields_default(self) -> None:
        meta = SkillMetadata(name="test", description="Test.")
        assert meta.license is None
        assert meta.compatibility is None
        assert meta.metadata == {}
        assert meta.allowed_tools == []


# ======================================================================
# Skill class
# ======================================================================


class TestSkill:
    """Tests for the Skill data class."""

    def test_properties(self) -> None:
        meta = SkillMetadata(name="test", description="Test skill.")
        skill = Skill(
            metadata=meta,
            instructions="# Instructions here",
            base_dir=Path("/fake"),
            source="builtin",
        )
        assert skill.name == "test"
        assert skill.description == "Test skill."
        assert skill.source == "builtin"
        assert skill.token_estimate > 0

    def test_repr(self) -> None:
        meta = SkillMetadata(name="test", description="Test.")
        skill = Skill(
            metadata=meta,
            instructions="Some instructions",
            base_dir=Path("/fake"),
        )
        r = repr(skill)
        assert "test" in r
        assert "builtin" in r


# ======================================================================
# SkillLoader
# ======================================================================


class TestSkillLoader:
    """SKILL.md parsing and loading."""

    def test_split_frontmatter_basic(self) -> None:
        content = "---\nname: test\n---\n# Instructions"
        fm, body = SkillLoader._split_frontmatter(content)
        assert fm == "name: test"
        assert body == "# Instructions"

    def test_split_frontmatter_no_frontmatter(self) -> None:
        content = "# Just markdown"
        fm, body = SkillLoader._split_frontmatter(content)
        assert fm is None
        assert body == "# Just markdown"

    def test_split_frontmatter_empty(self) -> None:
        content = ""
        fm, body = SkillLoader._split_frontmatter(content)
        assert fm is None

    def test_split_frontmatter_unclosed(self) -> None:
        content = "---\nname: test\nno closing delimiter"
        fm, body = SkillLoader._split_frontmatter(content)
        assert fm is None

    def test_load_metadata_from_dir(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: A test skill.\n---\n# Body",
            encoding="utf-8",
        )
        meta = SkillLoader.load_metadata(skill_dir)
        assert meta is not None
        assert meta.name == "my-skill"
        assert meta.description == "A test skill."

    def test_load_metadata_missing_file(self, tmp_path: Path) -> None:
        meta = SkillLoader.load_metadata(tmp_path)
        assert meta is None

    def test_load_metadata_invalid_yaml(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "bad"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\n: invalid yaml [\n---\nBody",
            encoding="utf-8",
        )
        meta = SkillLoader.load_metadata(skill_dir)
        assert meta is None

    def test_load_full_success(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: Test.\n---\n# Full body here",
            encoding="utf-8",
        )
        skill = SkillLoader.load_full(skill_dir)
        assert skill is not None
        assert skill.name == "my-skill"
        assert skill.instructions == "# Full body here"
        assert skill.source == "builtin"

    def test_load_full_validates_dir_name(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "wrong-name"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: actual-name\ndescription: Test.\n---\nBody.",
            encoding="utf-8",
        )
        skill = SkillLoader.load_full(skill_dir)
        assert skill is None  # name mismatch

    def test_basedir_variable_resolution(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: Test.\n---\n"
            "Run: {baseDir}/scripts/run.sh",
            encoding="utf-8",
        )
        skill = SkillLoader.load_full(skill_dir)
        assert skill is not None
        assert str(skill_dir) in skill.instructions
        assert "{baseDir}" not in skill.instructions

    def test_load_full_with_allowed_tools(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: Test.\n"
            "allowed-tools: Bash Read\n---\nBody.",
            encoding="utf-8",
        )
        skill = SkillLoader.load_full(skill_dir)
        assert skill is not None
        assert skill.metadata.allowed_tools == ["Bash", "Read"]

    def test_load_full_with_metadata_fields(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: Test.\n"
            "license: MIT\ncompatibility: Python 3.11+\n"
            "metadata:\n  author: test\n  version: '1.0'\n---\nBody.",
            encoding="utf-8",
        )
        skill = SkillLoader.load_full(skill_dir)
        assert skill is not None
        assert skill.metadata.license == "MIT"
        assert skill.metadata.compatibility == "Python 3.11+"
        assert skill.metadata.metadata == {"author": "test", "version": "1.0"}


# ======================================================================
# SkillRegistry
# ======================================================================


class TestSkillRegistry:
    """Discovery and lookup."""

    def _make_skill_dir(
        self, parent: Path, name: str, description: str = "Test."
    ) -> Path:
        """Helper to create a valid skill directory."""
        skill_dir = parent / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {description}\n---\nBody for {name}.",
            encoding="utf-8",
        )
        return skill_dir

    def test_discover_builtin_skills(self, tmp_path: Path) -> None:
        self._make_skill_dir(tmp_path, "test-skill")
        registry = SkillRegistry(builtin_dir=tmp_path)
        registry.discover()
        assert "test-skill" in registry
        assert len(registry) == 1

    def test_list_skills(self, tmp_path: Path) -> None:
        self._make_skill_dir(tmp_path, "alpha")
        self._make_skill_dir(tmp_path, "beta")
        registry = SkillRegistry(builtin_dir=tmp_path)
        registry.discover()
        assert registry.list_skills() == ["alpha", "beta"]

    def test_get_metadata(self, tmp_path: Path) -> None:
        self._make_skill_dir(tmp_path, "test-skill", "A test skill.")
        registry = SkillRegistry(builtin_dir=tmp_path)
        registry.discover()
        meta = registry.get_metadata("test-skill")
        assert meta is not None
        assert meta.description == "A test skill."

    def test_get_skill_lazily_loads(self, tmp_path: Path) -> None:
        self._make_skill_dir(tmp_path, "test-skill")
        registry = SkillRegistry(builtin_dir=tmp_path)
        registry.discover()
        # Not loaded yet
        assert "test-skill" not in registry._loaded
        skill = registry.get_skill("test-skill")
        assert skill is not None
        # Now cached
        assert "test-skill" in registry._loaded

    def test_get_or_raise_missing(self, tmp_path: Path) -> None:
        registry = SkillRegistry(builtin_dir=tmp_path)
        registry.discover()
        with pytest.raises(KeyError, match="nonexistent"):
            registry.get_or_raise("nonexistent")

    def test_get_skills_multiple(self, tmp_path: Path) -> None:
        self._make_skill_dir(tmp_path, "alpha")
        self._make_skill_dir(tmp_path, "beta")
        registry = SkillRegistry(builtin_dir=tmp_path)
        registry.discover()
        skills = registry.get_skills(["alpha", "beta"])
        assert len(skills) == 2
        assert skills[0].name == "alpha"
        assert skills[1].name == "beta"

    def test_priority_override(self, tmp_path: Path) -> None:
        builtin = tmp_path / "builtin"
        user = tmp_path / "user"
        self._make_skill_dir(builtin, "my-skill", "Builtin version.")
        self._make_skill_dir(user, "my-skill", "User version.")

        registry = SkillRegistry(builtin_dir=builtin, user_dir=user)
        registry.discover()
        meta = registry.get_metadata("my-skill")
        assert meta is not None
        assert meta.description == "User version."

    def test_project_overrides_builtin(self, tmp_path: Path) -> None:
        builtin = tmp_path / "builtin"
        project = tmp_path / "project"
        self._make_skill_dir(builtin, "my-skill", "Builtin.")
        self._make_skill_dir(project, "my-skill", "Project.")

        registry = SkillRegistry(builtin_dir=builtin, project_dir=project)
        registry.discover()
        meta = registry.get_metadata("my-skill")
        assert meta.description == "Project."

    def test_get_prompt_section_generates_xml(self, tmp_path: Path) -> None:
        self._make_skill_dir(tmp_path, "test-skill", "Does testing.")
        registry = SkillRegistry(builtin_dir=tmp_path)
        registry.discover()
        xml = registry.get_prompt_section()
        assert "<available_skills>" in xml
        assert "</available_skills>" in xml
        assert "<name>test-skill</name>" in xml
        assert "<description>Does testing.</description>" in xml

    def test_get_prompt_section_specific_names(self, tmp_path: Path) -> None:
        self._make_skill_dir(tmp_path, "alpha")
        self._make_skill_dir(tmp_path, "beta")
        registry = SkillRegistry(builtin_dir=tmp_path)
        registry.discover()
        xml = registry.get_prompt_section(["alpha"])
        assert "alpha" in xml
        assert "beta" not in xml

    def test_get_prompt_section_empty(self, tmp_path: Path) -> None:
        registry = SkillRegistry(builtin_dir=tmp_path)
        registry.discover()
        assert registry.get_prompt_section() == ""

    def test_get_full_instructions_section(self, tmp_path: Path) -> None:
        self._make_skill_dir(tmp_path, "test-skill")
        registry = SkillRegistry(builtin_dir=tmp_path)
        registry.discover()
        section = registry.get_full_instructions_section(["test-skill"])
        assert '<skill name="test-skill">' in section
        assert "Body for test-skill." in section
        assert "</skill>" in section

    def test_register_manual(self) -> None:
        meta = SkillMetadata(name="manual", description="Manual skill.")
        skill = Skill(
            metadata=meta,
            instructions="# Manual",
            base_dir=Path("/fake"),
            source="test",
        )
        registry = SkillRegistry(builtin_dir=Path("/nonexistent"))
        registry.register(skill)
        assert "manual" in registry
        assert registry.get_skill("manual") is skill

    def test_discover_clears_previous(self, tmp_path: Path) -> None:
        self._make_skill_dir(tmp_path, "first")
        registry = SkillRegistry(builtin_dir=tmp_path)
        registry.discover()
        assert "first" in registry

        # Remove the skill directory and rediscover
        import shutil
        shutil.rmtree(tmp_path / "first")
        registry.discover()
        assert "first" not in registry

    def test_contains_and_len(self, tmp_path: Path) -> None:
        self._make_skill_dir(tmp_path, "alpha")
        self._make_skill_dir(tmp_path, "beta")
        registry = SkillRegistry(builtin_dir=tmp_path)
        registry.discover()
        assert "alpha" in registry
        assert "gamma" not in registry
        assert len(registry) == 2

    def test_repr(self, tmp_path: Path) -> None:
        self._make_skill_dir(tmp_path, "test-skill")
        registry = SkillRegistry(builtin_dir=tmp_path)
        registry.discover()
        r = repr(registry)
        assert "test-skill" in r


# ======================================================================
# SkillActivationTool
# ======================================================================


class TestSkillActivationTool:
    """Dynamic skill loading via tool call."""

    def _make_tool(self) -> tuple[SkillActivationTool, Skill]:
        meta = SkillMetadata(
            name="test",
            description="Test skill.",
            allowed_tools=["Bash", "Read"],
        )
        skill = Skill(
            metadata=meta,
            instructions="# Test instructions\n\nDo things.",
            base_dir=Path("/fake"),
            source="builtin",
        )
        tool = SkillActivationTool(available_skills={"test": skill})
        return tool, skill

    def test_plugin_id(self) -> None:
        tool, _ = self._make_tool()
        assert tool.plugin_id == "activate_skill"

    def test_description(self) -> None:
        tool, _ = self._make_tool()
        assert "skill" in tool.description.lower()

    def test_input_schema_has_enum(self) -> None:
        tool, _ = self._make_tool()
        schema = tool.input_schema
        assert schema["properties"]["skill_name"]["enum"] == ["test"]

    def test_output_schema(self) -> None:
        tool, _ = self._make_tool()
        schema = tool.output_schema
        assert "instructions" in schema["properties"]

    def test_to_llm_tool_spec(self) -> None:
        tool, _ = self._make_tool()
        spec = tool.to_llm_tool_spec()
        assert spec["type"] == "function"
        assert spec["function"]["name"] == "activate_skill"

    @pytest.mark.asyncio
    async def test_activate_existing_skill(self) -> None:
        tool, skill = self._make_tool()
        result = await tool.execute({"skill_name": "test"})
        assert result["skill_name"] == "test"
        assert result["instructions"] == skill.instructions
        assert result["allowed_tools"] == ["Bash", "Read"]
        assert "error" not in result

    @pytest.mark.asyncio
    async def test_activate_missing_skill(self) -> None:
        tool, _ = self._make_tool()
        result = await tool.execute({"skill_name": "missing"})
        assert "error" in result
        assert "missing" in result["error"]

    @pytest.mark.asyncio
    async def test_activate_empty_name(self) -> None:
        tool, _ = self._make_tool()
        result = await tool.execute({"skill_name": ""})
        assert "error" in result


# ======================================================================
# Agent skill integration
# ======================================================================


class TestAgentSkillIntegration:
    """Agent-level skill injection into system prompt."""

    def _make_skill(self, name: str = "test") -> Skill:
        return Skill(
            metadata=SkillMetadata(name=name, description="Test skill."),
            instructions="# Full instructions here\n\nDetailed steps.",
            base_dir=Path("/fake"),
        )

    def test_llm_only_gets_full_instructions(self) -> None:
        from hiveflow.core.agent import Agent, AgentBehaviorType

        skill = self._make_skill()
        agent = Agent(
            agent_id="writer",
            role="Writer",
            system_prompt="You are a writer.",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            skills=[skill],
        )
        messages = agent._build_messages({"task": "Write something"})
        system_content = messages[0].content
        assert '<skill name="test">' in system_content
        assert "# Full instructions here" in system_content

    def test_tool_user_gets_metadata_only(self) -> None:
        from hiveflow.core.agent import Agent, AgentBehaviorType

        skill = self._make_skill()
        agent = Agent(
            agent_id="researcher",
            role="Researcher",
            system_prompt="You are a researcher.",
            behavior_type=AgentBehaviorType.TOOL_USER,
            skills=[skill],
        )
        messages = agent._build_messages({"task": "Research something"})
        system_content = messages[0].content
        assert "<available_skills>" in system_content
        assert "activate_skill" in system_content
        # Full instructions should NOT be in the prompt
        assert "# Full instructions here" not in system_content

    def test_orchestrator_gets_full_instructions(self) -> None:
        from hiveflow.core.agent import Agent, AgentBehaviorType

        skill = self._make_skill()
        agent = Agent(
            agent_id="orchestrator",
            role="Orchestrator",
            system_prompt="You orchestrate.",
            behavior_type=AgentBehaviorType.ORCHESTRATOR,
            skills=[skill],
        )
        messages = agent._build_messages({"task": "Plan"})
        system_content = messages[0].content
        assert '<skill name="test">' in system_content

    def test_action_executor_gets_metadata_only(self) -> None:
        from hiveflow.core.agent import Agent, AgentBehaviorType

        skill = self._make_skill()
        agent = Agent(
            agent_id="executor",
            role="Executor",
            system_prompt="You execute.",
            behavior_type=AgentBehaviorType.ACTION_EXECUTOR,
            skills=[skill],
        )
        messages = agent._build_messages({"task": "Execute"})
        system_content = messages[0].content
        assert "<available_skills>" in system_content

    def test_no_skills_no_injection(self) -> None:
        from hiveflow.core.agent import Agent, AgentBehaviorType

        agent = Agent(
            agent_id="plain",
            role="Plain",
            system_prompt="You are plain.",
            behavior_type=AgentBehaviorType.LLM_ONLY,
        )
        messages = agent._build_messages({"task": "Do something"})
        system_content = messages[0].content
        assert "<skill" not in system_content
        assert "<available_skills>" not in system_content

    def test_multiple_skills_injected(self) -> None:
        from hiveflow.core.agent import Agent, AgentBehaviorType

        skill1 = self._make_skill("alpha")
        skill2 = self._make_skill("beta")
        agent = Agent(
            agent_id="multi",
            role="Multi",
            system_prompt="You do everything.",
            behavior_type=AgentBehaviorType.LLM_ONLY,
            skills=[skill1, skill2],
        )
        messages = agent._build_messages({"task": "Do everything"})
        system_content = messages[0].content
        assert '<skill name="alpha">' in system_content
        assert '<skill name="beta">' in system_content

    def test_from_definition_passes_skills(self) -> None:
        from hiveflow.core.agent import Agent
        from hiveflow.core.schema import AgentDefinition

        definition = AgentDefinition(
            id="test-agent",
            role="Tester",
            system_prompt="Test.",
            behavior_type="llm_only",
            skills=["code-review"],
        )
        skill = self._make_skill("code-review")
        agent = Agent.from_definition(definition, skills=[skill])
        assert len(agent.skills) == 1
        assert agent.skills[0].name == "code-review"


# ======================================================================
# TeamGenerator skill wiring
# ======================================================================


class TestTeamGeneratorSkillWiring:
    """TeamGenerator.build() skill resolution."""

    def _make_registry(self, tmp_path: Path, *names: str) -> SkillRegistry:
        for name in names:
            skill_dir = tmp_path / name
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: Skill {name}.\n"
                f"---\n# Instructions for {name}",
                encoding="utf-8",
            )
        registry = SkillRegistry(builtin_dir=tmp_path)
        registry.discover()
        return registry

    def test_build_resolves_skills_for_llm_only(self, tmp_path: Path) -> None:
        from hiveflow.core.teams import TeamGenerator

        registry = self._make_registry(tmp_path, "code-review")
        config: dict[str, Any] = {
            "agents": [
                {
                    "id": "reviewer",
                    "role": "Code Reviewer",
                    "system_prompt": "Review code.",
                    "behavior_type": "llm_only",
                    "skills": ["code-review"],
                }
            ],
            "workflow": {
                "steps": [{"agent": "reviewer", "type": "sequential"}]
            },
        }
        gen = TeamGenerator()
        agents, _ = gen.build(
            config, MagicMock(), skill_registry=registry
        )
        agent = agents["reviewer"]
        assert len(agent.skills) == 1
        assert agent.skills[0].name == "code-review"

    def test_build_auto_injects_activation_tool(self, tmp_path: Path) -> None:
        from hiveflow.core.agent import AgentBehaviorType
        from hiveflow.core.teams import TeamGenerator

        registry = self._make_registry(tmp_path, "test-skill")
        config: dict[str, Any] = {
            "agents": [
                {
                    "id": "agent",
                    "role": "Agent",
                    "system_prompt": "Do things.",
                    "behavior_type": "tool_user",
                    "skills": ["test-skill"],
                }
            ],
            "workflow": {
                "steps": [{"agent": "agent", "type": "sequential"}]
            },
        }
        gen = TeamGenerator()
        agents, _ = gen.build(
            config, MagicMock(), skill_registry=registry
        )
        agent = agents["agent"]
        # Should have the SkillActivationTool injected
        tool_ids = [t.plugin_id for t in agent.tools]
        assert "activate_skill" in tool_ids
        # tool_user should NOT fall back to llm_only (it has the tool)
        assert agent.behavior_type == AgentBehaviorType.TOOL_USER

    def test_build_without_skill_registry_ignores_skills(self) -> None:
        from hiveflow.core.teams import TeamGenerator

        config: dict[str, Any] = {
            "agents": [
                {
                    "id": "agent",
                    "role": "Agent",
                    "system_prompt": "Do things.",
                    "behavior_type": "llm_only",
                    "skills": ["code-review"],
                }
            ],
            "workflow": {
                "steps": [{"agent": "agent", "type": "sequential"}]
            },
        }
        gen = TeamGenerator()
        # No skill_registry passed — skills should be ignored
        agents, _ = gen.build(config, MagicMock())
        agent = agents["agent"]
        assert agent.skills == []

    def test_missing_skill_raises_key_error(self, tmp_path: Path) -> None:
        from hiveflow.core.teams import TeamGenerator

        registry = SkillRegistry(builtin_dir=tmp_path)
        registry.discover()
        config: dict[str, Any] = {
            "agents": [
                {
                    "id": "agent",
                    "role": "Agent",
                    "system_prompt": "Do.",
                    "behavior_type": "llm_only",
                    "skills": ["nonexistent"],
                }
            ],
            "workflow": {
                "steps": [{"agent": "agent", "type": "sequential"}]
            },
        }
        gen = TeamGenerator()
        with pytest.raises(KeyError, match="nonexistent"):
            gen.build(config, MagicMock(), skill_registry=registry)

    def test_build_with_no_skills_unchanged(self) -> None:
        """Backward compatibility: configs without skills work as before."""
        from hiveflow.core.teams import TeamGenerator

        config: dict[str, Any] = {
            "agents": [
                {
                    "id": "agent",
                    "role": "Agent",
                    "system_prompt": "Do things.",
                    "behavior_type": "llm_only",
                }
            ],
            "workflow": {
                "steps": [{"agent": "agent", "type": "sequential"}]
            },
        }
        gen = TeamGenerator()
        agents, _ = gen.build(config, MagicMock())
        agent = agents["agent"]
        assert agent.skills == []
        assert len(agent.tools) == 0
