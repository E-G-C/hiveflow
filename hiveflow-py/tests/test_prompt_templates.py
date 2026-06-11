"""Tests for prompt template library: dotted-path resolution, families,
categories, and all 15 categories present."""

import pytest

from hiveflow.core.prompts import (
    PromptCategory,
    PromptFamily,
    PromptTemplate,
    detect_family,
    get_default_library,
    resolve_dotted_path,
)


class TestDottedPathResolution:
    """resolve_dotted_path supports dicts and objects."""

    def test_dict_single_level(self):
        assert resolve_dotted_path({"key": "value"}, "key") == "value"

    def test_dict_nested(self):
        obj = {"task": {"description": "hello", "subtopic": "world"}}
        assert resolve_dotted_path(obj, "task.description") == "hello"
        assert resolve_dotted_path(obj, "task.subtopic") == "world"

    def test_dict_deep_nesting(self):
        obj = {"a": {"b": {"c": {"d": 42}}}}
        assert resolve_dotted_path(obj, "a.b.c.d") == 42

    def test_object_attributes(self):
        class Config:
            language = "english"
            tone = "formal"

        assert resolve_dotted_path(Config(), "language") == "english"

    def test_mixed_dict_and_object(self):
        class Inner:
            value = "found"

        obj = {"outer": Inner()}
        assert resolve_dotted_path(obj, "outer.value") == "found"

    def test_missing_path_returns_none(self):
        obj = {"task": {"description": "hello"}}
        assert resolve_dotted_path(obj, "task.nonexistent") is None
        assert resolve_dotted_path(obj, "missing.path") is None

    def test_none_root_returns_none(self):
        assert resolve_dotted_path(None, "any.path") is None

    def test_empty_dict(self):
        assert resolve_dotted_path({}, "key") is None


class TestPromptFamilyDetection:
    """detect_family auto-selects family from model name."""

    def test_openai_is_default(self):
        assert detect_family("openai:gpt-4o") == PromptFamily.DEFAULT

    def test_anthropic_is_default(self):
        assert detect_family("anthropic:claude-sonnet-4-20250514") == PromptFamily.DEFAULT

    def test_ollama_is_local(self):
        assert detect_family("ollama:llama3") == PromptFamily.LOCAL

    def test_lmstudio_is_local(self):
        assert detect_family("lmstudio:mistral") == PromptFamily.LOCAL

    def test_granite_is_granite(self):
        assert detect_family("granite:13b") == PromptFamily.GRANITE

    def test_ibm_is_granite(self):
        assert detect_family("ibm:granite-13b") == PromptFamily.GRANITE

    def test_case_insensitive(self):
        assert detect_family("OLLAMA:llama3") == PromptFamily.LOCAL

    def test_unknown_prefix_is_default(self):
        assert detect_family("custom:model") == PromptFamily.DEFAULT


class TestPromptTemplateRender:
    """PromptTemplate render with flat and dotted-path variables."""

    def test_flat_variables(self):
        t = PromptTemplate("Hello $name, your task is $task", name="test")
        result = t.render(name="Alice", task="research")
        assert "Alice" in result
        assert "research" in result

    def test_dotted_path_variables(self):
        t = PromptTemplate(
            "Task: ${task.description}. Language: ${config.language}.",
            name="dotted",
        )
        result = t.render({
            "task": {"description": "analyze data"},
            "config": {"language": "english"},
        })
        assert "analyze data" in result
        assert "english" in result

    def test_mixed_flat_and_dotted(self):
        t = PromptTemplate(
            "Agent $agent_id working on ${task.name}",
            name="mixed",
        )
        result = t.render({"task": {"name": "research"}}, agent_id="agent-1")
        assert "agent-1" in result
        assert "research" in result

    def test_missing_dotted_path_preserved(self):
        t = PromptTemplate("Value: ${missing.path}", name="missing")
        result = t.render({})
        assert "${missing.path}" in result

    def test_required_vars_enforced(self):
        t = PromptTemplate("$required", name="strict", required_vars=["required"])
        with pytest.raises(ValueError, match="missing required"):
            t.render()

    def test_category_and_family_fields(self):
        t = PromptTemplate(
            "test",
            name="categorized",
            category=PromptCategory.CODE_GENERATION,
            family=PromptFamily.LOCAL,
        )
        assert t.category == PromptCategory.CODE_GENERATION
        assert t.family == PromptFamily.LOCAL


class TestPromptLibrary:
    """Default library has all 15 categories covered."""

    def test_default_library_has_16_templates(self):
        lib = get_default_library()
        assert len(lib.list_templates()) == 16

    def test_all_15_categories_covered(self):
        lib = get_default_library()
        covered = set()
        for name in lib.list_templates():
            t = lib.get(name)
            if t and t.category:
                covered.add(t.category)
        assert covered == set(PromptCategory)

    def test_all_categories_have_names(self):
        for cat in PromptCategory:
            assert cat.value  # No empty strings

    def test_existing_templates_still_work(self):
        lib = get_default_library()
        # system_researcher still renderable with old kwargs style
        result = lib.render("system_researcher", topic="AI", task="Find papers")
        assert "AI" in result
        assert "Find papers" in result

    def test_new_template_renders(self):
        lib = get_default_library()
        t = lib.get("code_generation")
        assert t is not None
        result = t.render(language="Python", task="Sort a list", requirements="O(n log n)")
        assert "Python" in result
        assert "Sort a list" in result
