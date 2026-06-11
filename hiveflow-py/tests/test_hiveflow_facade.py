"""Tests for HiveFlow facade and ArchetypeLibrary."""

import json
import tempfile
from pathlib import Path

import pytest

from hiveflow.core.hiveflow import HiveFlow
from hiveflow.core.teams import (
    ArchetypeLibrary,
    CapabilityGap,
    TeamGenerationResult,
    TeamTemplateLibrary,
)


class TestArchetypeLibrary:
    """Tests for ArchetypeLibrary class."""

    def test_register_and_get(self):
        """Should register and retrieve archetypes."""
        lib = ArchetypeLibrary()
        lib.register("writer", {"role": "Writer", "system_prompt": "Write."})
        result = lib.get("writer")
        assert result is not None
        assert result["role"] == "Writer"

    def test_get_nonexistent(self):
        """Should return None for unknown archetype."""
        lib = ArchetypeLibrary()
        assert lib.get("nonexistent") is None

    def test_list_archetypes(self):
        """Should list all registered archetype names sorted."""
        lib = ArchetypeLibrary()
        lib.register("writer", {})
        lib.register("reviewer", {})
        lib.register("approver", {})
        assert lib.list_archetypes() == ["approver", "reviewer", "writer"]

    def test_from_directory(self):
        """Should load archetypes from JSON files in directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create archetype files
            Path(tmpdir, "writer.json").write_text(
                json.dumps({"role": "Writer", "system_prompt": "Write."}),
                encoding="utf-8",
            )
            Path(tmpdir, "reviewer.json").write_text(
                json.dumps({"role": "Reviewer", "system_prompt": "Review."}),
                encoding="utf-8",
            )

            lib = ArchetypeLibrary.from_directory(tmpdir)
            assert sorted(lib.list_archetypes()) == ["reviewer", "writer"]
            assert lib.get("writer")["role"] == "Writer"

    def test_from_directory_nonexistent(self):
        """Should return empty library for nonexistent directory."""
        lib = ArchetypeLibrary.from_directory("/nonexistent/path")
        assert lib.list_archetypes() == []

    def test_default_loads_builtins(self):
        """default() should load built-in archetypes from TeamGenerator."""
        lib = ArchetypeLibrary.default()
        archetypes = lib.list_archetypes()
        # Should have at least the built-in archetypes
        assert "researcher" in archetypes
        assert "writer" in archetypes
        assert "reviewer" in archetypes


class TestCapabilityGap:
    """Tests for CapabilityGap model."""

    def test_valid_gap(self):
        """Should create a valid capability gap."""
        gap = CapabilityGap(
            resource_type="tool",
            resource_id="web_search",
            severity="degraded",
            description="Web search tool not registered",
            fallback_strategy="Agent will use LLM knowledge only",
        )
        assert gap.resource_type == "tool"
        assert gap.severity == "degraded"

    def test_gap_without_fallback(self):
        """fallback_strategy should be optional."""
        gap = CapabilityGap(
            resource_type="model",
            resource_id="gpt-5",
            severity="blocking",
            description="Model not available",
        )
        assert gap.fallback_strategy is None


class TestTeamGenerationResult:
    """Tests for TeamGenerationResult model."""

    def test_no_blocking_gaps(self):
        """has_blocking_gaps should be False when no blocking gaps."""
        result = TeamGenerationResult(
            config={"team_name": "test", "agents": [], "workflow": {"steps": []}},
            capability_gaps=[
                CapabilityGap(
                    resource_type="tool",
                    resource_id="web_search",
                    severity="degraded",
                    description="Not critical",
                ),
            ],
        )
        assert result.has_blocking_gaps is False

    def test_has_blocking_gaps(self):
        """has_blocking_gaps should be True when any gap is blocking."""
        result = TeamGenerationResult(
            config={"team_name": "test", "agents": [], "workflow": {"steps": []}},
            capability_gaps=[
                CapabilityGap(
                    resource_type="tool",
                    resource_id="critical_tool",
                    severity="blocking",
                    description="Required tool missing",
                ),
            ],
        )
        assert result.has_blocking_gaps is True

    def test_empty_gaps(self):
        """Empty gaps list should have no blocking gaps."""
        result = TeamGenerationResult(
            config={"team_name": "test"},
        )
        assert result.has_blocking_gaps is False
        assert result.capability_gaps == []
        assert result.new_archetypes == []


class TestHiveFlowFacade:
    """Tests for HiveFlow top-level entry point."""

    def test_default_construction(self):
        """Should construct with all defaults."""
        hf = HiveFlow()
        assert hf.team_library() is not None
        assert hf.archetype_library() is not None
        assert hf.tool_registry() is not None
        assert hf.model_registry() is not None

    def test_discovery_team_library(self):
        """team_library() should return the library."""
        lib = TeamTemplateLibrary()
        lib.register("test_team", {"team_name": "test"})
        hf = HiveFlow(team_library=lib)
        assert "test_team" in hf.team_library().list_templates()

    def test_discovery_archetype_library(self):
        """archetype_library() should return the library."""
        lib = ArchetypeLibrary()
        lib.register("custom_writer", {"role": "Writer"})
        hf = HiveFlow(archetype_library=lib)
        assert "custom_writer" in hf.archetype_library().list_archetypes()

    def test_resolve_template_name(self):
        """Should resolve string team arg to template config."""
        lib = TeamTemplateLibrary()
        lib.register("my_team", {"team_name": "my_team", "agents": [], "workflow": {}})
        hf = HiveFlow(team_library=lib)
        result = hf._resolve_team_config("my_team")
        assert result["team_name"] == "my_team"

    def test_resolve_unknown_template_raises(self):
        """Should raise KeyError for unknown template name."""
        hf = HiveFlow(team_library=TeamTemplateLibrary())
        with pytest.raises(KeyError, match="not found"):
            hf._resolve_team_config("nonexistent")

    def test_resolve_dict_passthrough(self):
        """Should pass through dict configs."""
        hf = HiveFlow()
        config = {"team_name": "inline"}
        result = hf._resolve_team_config(config)
        assert result is config

    def test_resolve_llm_provider_uses_model_ref(self):
        hf = HiveFlow()
        provider = hf._resolve_llm_provider("perplexity:sonar-pro")
        assert provider is not None
        assert provider.provider_id == "perplexity"

    @pytest.mark.asyncio
    async def test_generate_team(self):
        """generate_team should return a TeamGenerationResult."""
        hf = HiveFlow()
        result = await hf.generate_team(task="Write a market analysis")
        assert isinstance(result, TeamGenerationResult)
        assert result.config is not None
        # Should detect missing tools (web_search)
        assert len(result.capability_gaps) > 0
