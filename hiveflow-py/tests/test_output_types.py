"""Tests for hiveflow.core.output_types module."""

import textwrap

import pytest

from hiveflow.core.output_types import (
    CitationsConfig,
    OutputOptions,
    OutputTypeDefinition,
    OutputTypeId,
    OutputTypeRegistry,
    PromptTemplateSet,
    route_output,
)


class TestOutputOptions:
    def test_defaults(self):
        opts = OutputOptions()
        assert opts.max_sections is None
        assert opts.words_per_section is None
        assert opts.include_introduction is True
        assert opts.include_conclusion is True
        assert opts.include_table_of_contents is True

    def test_custom_values(self):
        opts = OutputOptions(max_sections=5, words_per_section=600)
        assert opts.max_sections == 5
        assert opts.words_per_section == 600


class TestCitationsConfig:
    def test_defaults(self):
        cfg = CitationsConfig()
        assert cfg.enabled is True
        assert cfg.style == "apa"
        assert cfg.inline is True
        assert cfg.generate_reference_section is True

    def test_disabled(self):
        cfg = CitationsConfig(enabled=False, inline=False)
        assert cfg.enabled is False
        assert cfg.inline is False


class TestPromptTemplateSet:
    def test_all_none_by_default(self):
        pts = PromptTemplateSet()
        assert pts.query_generation is None
        assert pts.writing is None
        assert pts.review is None
        assert pts.action is None
        assert pts.introduction is None
        assert pts.conclusion is None

    def test_custom_prompts(self):
        pts = PromptTemplateSet(
            writing="Write a detailed section.",
            review="Check for accuracy.",
        )
        assert pts.writing == "Write a detailed section."
        assert pts.review == "Check for accuracy."
        assert pts.query_generation is None


class TestOutputTypeDefinition:
    def test_construction(self):
        defn = OutputTypeDefinition(
            type_id="test_type",
            label="Test Type",
            pipeline_shape=["collect", "produce"],
        )
        assert defn.type_id == "test_type"
        assert defn.label == "Test Type"
        assert defn.pipeline_shape == ["collect", "produce"]
        assert isinstance(defn.prompt_template_set, PromptTemplateSet)
        assert isinstance(defn.default_output_options, OutputOptions)

    def test_json_round_trip(self):
        defn = OutputTypeDefinition(
            type_id="test_type",
            label="Test",
            pipeline_shape=["collect"],
            prompt_template_set=PromptTemplateSet(writing="Write it."),
        )
        data = defn.model_dump(mode="json")
        restored = OutputTypeDefinition.model_validate(data)
        assert restored.type_id == "test_type"
        assert restored.prompt_template_set.writing == "Write it."


class TestOutputTypeId:
    def test_all_ten_types(self):
        ids = list(OutputTypeId)
        assert len(ids) == 10
        assert "detailed_report" in [i.value for i in ids]
        assert "custom" in [i.value for i in ids]


class TestOutputTypeRegistry:
    def test_builtin_types_loaded(self):
        registry = OutputTypeRegistry()
        types = registry.list_types()
        assert len(types) == 10
        assert "detailed_report" in types
        assert "quick_report" in types
        assert "outline" in types
        assert "custom" in types

    def test_resolve_known_type(self):
        registry = OutputTypeRegistry()
        defn = registry.resolve("detailed_report")
        assert defn is not None
        assert defn.type_id == "detailed_report"
        assert defn.label == "Detailed Report"
        assert len(defn.pipeline_shape) > 0

    def test_resolve_unknown_type(self):
        registry = OutputTypeRegistry()
        assert registry.resolve("nonexistent") is None

    def test_resolve_custom_type(self):
        registry = OutputTypeRegistry()
        defn = registry.resolve("custom")
        assert defn is not None
        assert defn.pipeline_shape == []

    def test_register_custom_type(self):
        registry = OutputTypeRegistry()
        custom = OutputTypeDefinition(
            type_id="my_custom",
            label="My Custom Type",
            pipeline_shape=["collect", "produce", "emit"],
        )
        registry.register(custom)
        assert "my_custom" in registry.list_types()
        assert registry.resolve("my_custom") is custom

    def test_register_overrides_builtin(self):
        registry = OutputTypeRegistry()
        override = OutputTypeDefinition(
            type_id="outline",
            label="Custom Outline",
            pipeline_shape=["collect", "produce"],
        )
        registry.register(override)
        defn = registry.resolve("outline")
        assert defn is not None
        assert defn.label == "Custom Outline"
        assert defn.pipeline_shape == ["collect", "produce"]

    def test_each_builtin_has_distinct_pipeline(self):
        registry = OutputTypeRegistry()
        shapes = set()
        for type_id in registry.list_types():
            defn = registry.resolve(type_id)
            assert defn is not None
            shape_tuple = tuple(defn.pipeline_shape)
            # custom has empty pipeline, rest should vary
            if type_id != "custom":
                assert len(defn.pipeline_shape) > 0
            shapes.add(shape_tuple)
        # At least 5 distinct shapes among 10 types
        assert len(shapes) >= 5


class TestOutputTypeRouting:
    """Tests for TeamGenerator.generate_team_for_output_type() (FR-022)."""

    def test_detailed_report_produces_multi_agent_pipeline(self):
        from hiveflow.core.teams import TeamGenerator

        gen = TeamGenerator()
        config = gen.generate_team_for_output_type(
            "detailed_report", "Analyze AI impact on healthcare"
        )
        assert config is not None
        assert len(config["agents"]) >= 3  # planner + researcher + writer + ...
        assert config["team_name"].startswith("Generated Team:")

    def test_outline_produces_minimal_pipeline(self):
        from hiveflow.core.teams import TeamGenerator

        gen = TeamGenerator()
        config = gen.generate_team_for_output_type(
            "outline", "Outline of climate change effects"
        )
        assert config is not None
        # outline = ["collect"] -> researcher only
        agent_ids = [a["id"] for a in config["agents"]]
        assert "researcher" in agent_ids

    def test_unknown_type_returns_none(self):
        from hiveflow.core.teams import TeamGenerator

        gen = TeamGenerator()
        config = gen.generate_team_for_output_type(
            "nonexistent_type", "Some task"
        )
        assert config is None

    def test_custom_type_returns_none(self):
        from hiveflow.core.teams import TeamGenerator

        gen = TeamGenerator()
        config = gen.generate_team_for_output_type("custom", "Some task")
        assert config is None

    def test_different_types_produce_different_configs(self):
        from hiveflow.core.teams import TeamGenerator

        gen = TeamGenerator()
        detailed = gen.generate_team_for_output_type(
            "detailed_report", "Report task"
        )
        outline = gen.generate_team_for_output_type(
            "outline", "Outline task"
        )
        assert detailed is not None and outline is not None
        assert len(detailed["agents"]) != len(outline["agents"])


class TestPromptTemplatePopulation:
    """Verify all built-in types have populated prompt templates."""

    def test_detailed_report_has_all_prompts(self):
        registry = OutputTypeRegistry()
        defn = registry.resolve("detailed_report")
        assert defn is not None
        pts = defn.prompt_template_set
        assert pts.query_generation is not None
        assert pts.writing is not None
        assert pts.review is not None
        assert pts.introduction is not None
        assert pts.conclusion is not None

    def test_quick_report_has_writing_prompt(self):
        registry = OutputTypeRegistry()
        defn = registry.resolve("quick_report")
        assert defn is not None
        assert defn.prompt_template_set.writing is not None

    def test_all_non_custom_types_have_writing_prompt(self):
        registry = OutputTypeRegistry()
        for type_id in registry.list_types():
            if type_id == "custom":
                continue
            defn = registry.resolve(type_id)
            assert defn is not None
            assert defn.prompt_template_set.writing is not None or \
                defn.prompt_template_set.query_generation is not None, \
                f"{type_id} has no writing or query_generation prompt"

    def test_deep_research_has_review_prompt(self):
        registry = OutputTypeRegistry()
        defn = registry.resolve("deep_research")
        assert defn is not None
        assert defn.prompt_template_set.review is not None

    def test_code_artifact_has_no_introduction(self):
        registry = OutputTypeRegistry()
        defn = registry.resolve("code_artifact")
        assert defn is not None
        assert defn.prompt_template_set.introduction is None
        assert defn.default_output_options.include_introduction is False


class TestDefaultOutputOptions:
    """Verify built-in types have sensible default output options."""

    def test_detailed_report_defaults(self):
        registry = OutputTypeRegistry()
        defn = registry.resolve("detailed_report")
        assert defn is not None
        assert defn.default_output_options.max_sections == 8
        assert defn.default_output_options.words_per_section == 800

    def test_quick_report_no_toc(self):
        registry = OutputTypeRegistry()
        defn = registry.resolve("quick_report")
        assert defn is not None
        assert defn.default_output_options.include_table_of_contents is False

    def test_outline_no_intro_conclusion(self):
        registry = OutputTypeRegistry()
        defn = registry.resolve("outline")
        assert defn is not None
        assert defn.default_output_options.include_introduction is False
        assert defn.default_output_options.include_conclusion is False


class TestLoadFromYaml:
    """Tests for YAML-based output type loading."""

    def test_load_from_yaml(self, tmp_path):
        yaml_content = textwrap.dedent("""\
            type_id: tutorial
            label: Tutorial
            description: Step-by-step tutorial
            pipeline_shape:
              - collect
              - produce
            prompt_template_set:
              writing: "Write a clear tutorial step."
            default_output_options:
              max_sections: 5
              include_table_of_contents: true
        """)
        yaml_file = tmp_path / "tutorial.yaml"
        yaml_file.write_text(yaml_content, encoding="utf-8")

        registry = OutputTypeRegistry()
        defn = registry.load_from_yaml(yaml_file)
        assert defn.type_id == "tutorial"
        assert defn.label == "Tutorial"
        assert defn.pipeline_shape == ["collect", "produce"]
        assert defn.prompt_template_set.writing == "Write a clear tutorial step."
        assert defn.default_output_options.max_sections == 5
        assert registry.resolve("tutorial") is defn

    def test_load_from_yaml_missing_file(self):
        registry = OutputTypeRegistry()
        with pytest.raises(FileNotFoundError):
            registry.load_from_yaml("/nonexistent/path.yaml")

    def test_load_from_yaml_invalid_content(self, tmp_path):
        yaml_file = tmp_path / "bad.yaml"
        yaml_file.write_text("just a string, not a mapping", encoding="utf-8")
        registry = OutputTypeRegistry()
        with pytest.raises(ValueError, match="Expected a YAML mapping"):
            registry.load_from_yaml(yaml_file)

    def test_load_from_directory(self, tmp_path):
        for name, type_id in [("alpha.yaml", "alpha"), ("beta.yml", "beta")]:
            (tmp_path / name).write_text(
                f"type_id: {type_id}\nlabel: {type_id.title()}\n"
                f"pipeline_shape: [collect]\n",
                encoding="utf-8",
            )
        registry = OutputTypeRegistry()
        loaded = registry.load_from_directory(tmp_path)
        assert len(loaded) == 2
        assert registry.resolve("alpha") is not None
        assert registry.resolve("beta") is not None

    def test_load_from_directory_nonexistent(self):
        registry = OutputTypeRegistry()
        loaded = registry.load_from_directory("/nonexistent/dir")
        assert loaded == []

    def test_load_overrides_builtin(self, tmp_path):
        yaml_content = textwrap.dedent("""\
            type_id: outline
            label: Custom Outline
            pipeline_shape: [collect, produce]
            prompt_template_set:
              writing: "Custom outline writing prompt."
        """)
        (tmp_path / "outline.yaml").write_text(yaml_content, encoding="utf-8")
        registry = OutputTypeRegistry()
        registry.load_from_directory(tmp_path)
        defn = registry.resolve("outline")
        assert defn is not None
        assert defn.label == "Custom Outline"
        assert defn.prompt_template_set.writing == "Custom outline writing prompt."


class TestRouteOutput:
    """Tests for the standalone route_output() function."""

    def test_route_known_type(self):
        result = route_output("detailed_report", "Analyze AI trends")
        assert result is not None
        assert result["output_type"] == "detailed_report"
        assert "prompt_template_set" in result
        assert "agents" in result
        assert len(result["agents"]) >= 3

    def test_route_includes_prompt_templates(self):
        result = route_output("detailed_report", "Test task")
        assert result is not None
        pts = result["prompt_template_set"]
        assert "writing" in pts
        assert "review" in pts

    def test_route_includes_default_output_options(self):
        result = route_output("detailed_report", "Test task")
        assert result is not None
        opts = result["default_output_options"]
        assert opts["max_sections"] == 8

    def test_route_unknown_type_returns_none(self):
        result = route_output("nonexistent_type", "Some task")
        assert result is None

    def test_route_custom_without_config_returns_none(self):
        result = route_output("custom", "Some task")
        assert result is None

    def test_route_custom_with_config(self):
        custom_team = {"team_name": "My Team", "agents": [], "workflow": {}}
        result = route_output(
            "custom", "Some task", config={"custom_team": custom_team}
        )
        assert result == custom_team

    def test_route_with_custom_registry(self, tmp_path):
        yaml_content = textwrap.dedent("""\
            type_id: newsletter
            label: Newsletter
            pipeline_shape: [collect, produce]
        """)
        (tmp_path / "newsletter.yaml").write_text(yaml_content, encoding="utf-8")
        registry = OutputTypeRegistry()
        registry.load_from_directory(tmp_path)
        result = route_output("newsletter", "Weekly digest", registry=registry)
        assert result is not None
        assert result["output_type"] == "newsletter"
