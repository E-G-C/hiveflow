"""Tests for archetype JSON file loading and team template validation (T021)."""

import json
from pathlib import Path

import pytest

from hiveflow.core.schema import TeamConfiguration
from hiveflow.core.teams import ArchetypeLibrary, TeamGenerator, TeamTemplateLibrary

TEMPLATES_DIR = Path(__file__).parent.parent / "hiveflow" / "templates"
ARCHETYPES_DIR = TEMPLATES_DIR / "archetypes"

EXPECTED_ARCHETYPES = {"researcher", "planner", "writer", "reviewer", "editor", "human_reviewer"}


class TestArchetypeJsonLoading:
    """Tests for loading archetypes from JSON files on disk."""

    def test_all_archetype_json_files_exist(self):
        """All 6 archetype JSON files should exist on disk."""
        for name in EXPECTED_ARCHETYPES:
            path = ARCHETYPES_DIR / f"{name}.json"
            assert path.exists(), f"Missing archetype file: {path}"

    def test_all_archetype_json_files_valid(self):
        """Each archetype JSON file should be valid JSON with required fields."""
        for name in EXPECTED_ARCHETYPES:
            path = ARCHETYPES_DIR / f"{name}.json"
            with open(path) as f:
                data = json.load(f)
            assert "role" in data, f"{name}.json missing 'role'"
            assert "system_prompt" in data, f"{name}.json missing 'system_prompt'"
            assert "behavior_type" in data, f"{name}.json missing 'behavior_type'"

    def test_archetype_library_loads_from_disk(self):
        """ArchetypeLibrary.from_directory should load all archetype files."""
        lib = ArchetypeLibrary.from_directory(ARCHETYPES_DIR)
        loaded = set(lib.list_archetypes())
        assert EXPECTED_ARCHETYPES.issubset(loaded)

    def test_archetype_library_default_includes_all(self):
        """ArchetypeLibrary.default() should include all 6 archetypes."""
        lib = ArchetypeLibrary.default()
        loaded = set(lib.list_archetypes())
        assert EXPECTED_ARCHETYPES.issubset(loaded)

    def test_disk_archetypes_match_in_memory(self):
        """JSON archetype files should match the in-memory ARCHETYPES dict."""
        for name in EXPECTED_ARCHETYPES:
            path = ARCHETYPES_DIR / f"{name}.json"
            with open(path) as f:
                disk_data = json.load(f)
            in_memory = TeamGenerator.ARCHETYPES[name]
            assert disk_data["role"] == in_memory["role"], (
                f"{name}: role mismatch"
            )
            assert disk_data["behavior_type"] == in_memory["behavior_type"], (
                f"{name}: behavior_type mismatch"
            )

    def test_archetype_get_returns_dict(self):
        """Getting an archetype by name should return a dict."""
        lib = ArchetypeLibrary.default()
        researcher = lib.get("researcher")
        assert isinstance(researcher, dict)
        assert researcher["role"] == "Deep Researcher"
        assert researcher["behavior_type"] == "tool_user"


class TestTeamTemplateLoading:
    """Tests for loading team templates from JSON files."""

    def test_code_review_template_exists(self):
        """code_review.json should exist in templates/."""
        path = TEMPLATES_DIR / "code_review.json"
        assert path.exists()

    def test_content_creation_template_exists(self):
        """content_creation.json should exist in templates/."""
        path = TEMPLATES_DIR / "content_creation.json"
        assert path.exists()

    def test_code_review_validates_as_team_config(self):
        """code_review.json should validate as a TeamConfiguration."""
        path = TEMPLATES_DIR / "code_review.json"
        with open(path) as f:
            data = json.load(f)
        config = TeamConfiguration(**data)
        assert config.team_name == "code_review"
        assert len(config.agents) == 3

    def test_content_creation_validates_as_team_config(self):
        """content_creation.json should validate as a TeamConfiguration."""
        path = TEMPLATES_DIR / "content_creation.json"
        with open(path) as f:
            data = json.load(f)
        config = TeamConfiguration(**data)
        assert config.team_name == "content_creation"
        assert len(config.agents) == 4

    def test_team_library_default_loads_templates(self):
        """TeamTemplateLibrary.default() should load team templates from disk."""
        lib = TeamTemplateLibrary.default()
        templates = lib.list_templates()
        assert "research_report" in templates
        assert "code_review" in templates
        assert "content_creation" in templates

    def test_research_report_template_validates(self):
        """Existing research_report.json should still validate."""
        path = TEMPLATES_DIR / "research_report.json"
        with open(path) as f:
            data = json.load(f)
        config = TeamConfiguration(**data)
        assert config.team_name == "research_report"


class TestLLMTeamGeneration:
    """Tests for LLM-based team generation (T040)."""

    @pytest.mark.asyncio
    async def test_valid_output_parses_to_team_config(self):
        """Valid LLM output should parse to a TeamConfiguration."""
        from unittest.mock import AsyncMock, MagicMock

        from hiveflow.core.teams import TeamGenerationResult

        valid_config = json.dumps({
            "team_name": "test_team",
            "description": "A test team",
            "agents": [
                {
                    "id": "writer",
                    "role": "Writer",
                    "system_prompt": "Write content.",
                    "behavior_type": "llm_only",
                },
            ],
            "workflow": {"steps": [{"agent": "writer", "type": "sequential"}]},
        })

        mock_provider = MagicMock()
        mock_response = MagicMock()
        mock_response.content = valid_config
        mock_provider.chat = AsyncMock(return_value=mock_response)

        gen = TeamGenerator()
        result = await gen.generate_team_from_llm("Write a blog post", mock_provider)

        assert isinstance(result, TeamGenerationResult)
        assert result.config["team_name"] == "test_team"
        assert len(result.config["agents"]) == 1

    @pytest.mark.asyncio
    async def test_blocking_gaps_with_auto_approve_raises(self):
        """Blocking gaps with auto_approve=True should raise ValueError."""
        from unittest.mock import AsyncMock, MagicMock

        valid_config = json.dumps({
            "team_name": "needs_tools",
            "description": "Team needing tools",
            "agents": [
                {
                    "id": "searcher",
                    "role": "Searcher",
                    "system_prompt": "Search.",
                    "behavior_type": "tool_user",
                    "tools": ["missing_tool"],
                },
            ],
            "workflow": {"steps": [{"agent": "searcher", "type": "sequential"}]},
        })

        mock_provider = MagicMock()
        mock_response = MagicMock()
        mock_response.content = valid_config
        mock_provider.chat = AsyncMock(return_value=mock_response)

        gen = TeamGenerator()
        with pytest.raises(ValueError, match="blocking gaps"):
            await gen.generate_team_from_llm(
                "Search the web",
                mock_provider,
                auto_approve=True,
            )

    @pytest.mark.asyncio
    async def test_auto_approve_false_returns_result_with_gaps(self):
        """auto_approve=False should return result for inspection even with gaps."""
        from unittest.mock import AsyncMock, MagicMock

        from hiveflow.core.teams import TeamGenerationResult

        valid_config = json.dumps({
            "team_name": "needs_tools",
            "description": "Team needing tools",
            "agents": [
                {
                    "id": "searcher",
                    "role": "Searcher",
                    "system_prompt": "Search.",
                    "behavior_type": "tool_user",
                    "tools": ["missing_tool"],
                },
            ],
            "workflow": {"steps": [{"agent": "searcher", "type": "sequential"}]},
        })

        mock_provider = MagicMock()
        mock_response = MagicMock()
        mock_response.content = valid_config
        mock_provider.chat = AsyncMock(return_value=mock_response)

        gen = TeamGenerator()
        result = await gen.generate_team_from_llm(
            "Search the web",
            mock_provider,
            auto_approve=False,
        )

        assert isinstance(result, TeamGenerationResult)
        assert result.has_blocking_gaps is True
        assert len(result.capability_gaps) >= 1

    @pytest.mark.asyncio
    async def test_new_archetypes_included_in_result(self):
        """Novel archetypes invented by LLM should be in new_archetypes."""
        from unittest.mock import AsyncMock, MagicMock

        valid_config = json.dumps({
            "team_name": "novel_team",
            "description": "Team with novel agents",
            "agents": [
                {
                    "id": "data_scientist",
                    "role": "Data Scientist",
                    "system_prompt": "Analyze data.",
                    "behavior_type": "llm_only",
                },
            ],
            "workflow": {"steps": [{"agent": "data_scientist", "type": "sequential"}]},
        })

        mock_provider = MagicMock()
        mock_response = MagicMock()
        mock_response.content = valid_config
        mock_provider.chat = AsyncMock(return_value=mock_response)

        gen = TeamGenerator()
        result = await gen.generate_team_from_llm("Analyze sales data", mock_provider)

        assert len(result.new_archetypes) >= 1
        assert any(a["id"] == "data_scientist" for a in result.new_archetypes)
