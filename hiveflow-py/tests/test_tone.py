"""Tests for hiveflow.core.tone module."""

from hiveflow.core.tone import (
    ToneCatalog,
    ToneDefinition,
    inject_tone,
    should_inject_tone,
)


class TestToneDefinition:
    def test_construction(self):
        tone = ToneDefinition(
            tone_id="test",
            label="Test Tone",
            description="A test tone",
            prompt_modifier="Write in a test tone.",
        )
        assert tone.tone_id == "test"
        assert tone.prompt_modifier == "Write in a test tone."

    def test_json_round_trip(self):
        tone = ToneDefinition(
            tone_id="test",
            label="Test",
            description="Test",
            prompt_modifier="Be testy.",
        )
        data = tone.model_dump(mode="json")
        restored = ToneDefinition.model_validate(data)
        assert restored.tone_id == "test"
        assert restored.prompt_modifier == "Be testy."


class TestToneCatalog:
    def test_builtin_tones_loaded(self):
        catalog = ToneCatalog()
        tones = catalog.list_tones()
        assert len(tones) == 17
        assert "formal" in tones
        assert "executive" in tones
        assert "objective" in tones
        assert "concise" in tones

    def test_resolve_known_tone(self):
        catalog = ToneCatalog()
        tone = catalog.resolve("formal")
        assert tone is not None
        assert tone.tone_id == "formal"
        assert tone.label == "Formal"
        assert len(tone.prompt_modifier) > 0

    def test_resolve_unknown_tone(self):
        catalog = ToneCatalog()
        tone = catalog.resolve("nonexistent")
        assert tone is None

    def test_register_custom_tone(self):
        catalog = ToneCatalog()
        custom = ToneDefinition(
            tone_id="investor_update",
            label="Investor Update",
            description="Professional, metrics-focused",
            prompt_modifier="Write for investors. Lead with metrics.",
        )
        catalog.register(custom)
        assert "investor_update" in catalog.list_tones()
        resolved = catalog.resolve("investor_update")
        assert resolved is not None
        assert resolved.prompt_modifier == "Write for investors. Lead with metrics."

    def test_custom_overrides_builtin(self):
        catalog = ToneCatalog()
        override = ToneDefinition(
            tone_id="formal",
            label="Custom Formal",
            description="Our version of formal",
            prompt_modifier="Our custom formal modifier.",
        )
        catalog.register(override)
        resolved = catalog.resolve("formal")
        assert resolved is not None
        assert resolved.label == "Custom Formal"
        assert resolved.prompt_modifier == "Our custom formal modifier."

    def test_resolve_from_config_string(self):
        catalog = ToneCatalog()
        tone = catalog.resolve_from_config("executive")
        assert tone is not None
        assert tone.tone_id == "executive"

    def test_resolve_from_config_none(self):
        catalog = ToneCatalog()
        tone = catalog.resolve_from_config(None)
        assert tone is None

    def test_resolve_from_config_dict(self):
        catalog = ToneCatalog()
        tone = catalog.resolve_from_config({
            "tone_id": "brand_voice",
            "label": "Brand Voice",
            "description": "Our brand",
            "prompt_modifier": "Write in our brand voice.",
        })
        assert tone is not None
        assert tone.tone_id == "brand_voice"
        # Also registered in catalog
        assert "brand_voice" in catalog.list_tones()

    def test_resolve_from_config_invalid_dict(self):
        catalog = ToneCatalog()
        tone = catalog.resolve_from_config({"invalid": "data"})
        assert tone is None

    def test_resolve_from_config_unknown_string(self):
        catalog = ToneCatalog()
        tone = catalog.resolve_from_config("nonexistent_tone")
        assert tone is None

    def test_all_builtin_tones_have_distinct_modifiers(self):
        catalog = ToneCatalog()
        modifiers = set()
        for tone_id in catalog.list_tones():
            tone = catalog.resolve(tone_id)
            assert tone is not None
            assert len(tone.prompt_modifier) > 0
            modifiers.add(tone.prompt_modifier)
        # All 17 should have distinct modifiers
        assert len(modifiers) == 17


class TestInjectTone:
    """Tests for inject_tone() helper and should_inject_tone() filter."""

    def _make_tone(self, label: str = "Formal", modifier: str = "Be formal."):
        return ToneDefinition(
            tone_id="formal",
            label=label,
            description="Test",
            prompt_modifier=modifier,
        )

    def test_inject_appends_to_system_prompt(self):
        tone = self._make_tone()
        result = inject_tone("You are a writer.", tone)
        assert result.startswith("You are a writer.")
        assert "TONE & STYLE" in result
        assert "Be formal." in result

    def test_inject_includes_label(self):
        tone = self._make_tone(label="Executive")
        result = inject_tone("Base prompt.", tone)
        assert "Executive" in result

    def test_inject_preserves_original(self):
        tone = self._make_tone()
        original = "You are a research assistant with web access."
        result = inject_tone(original, tone)
        assert original in result

    def test_should_inject_llm_only(self):
        assert should_inject_tone("llm_only") is True

    def test_should_inject_tool_user(self):
        assert should_inject_tone("tool_user") is True

    def test_should_not_inject_orchestrator(self):
        assert should_inject_tone("orchestrator") is False

    def test_should_not_inject_human_gate(self):
        assert should_inject_tone("human_gate") is False

    def test_should_not_inject_action_executor(self):
        assert should_inject_tone("action_executor") is False


class TestToneWiringInBuild:
    """Tests that build() injects tone into text-producing agents."""

    def test_build_with_tone_injects_into_writer(self):
        from unittest.mock import MagicMock

        from hiveflow.core.teams import TeamGenerator

        gen = TeamGenerator()
        config = gen.generate_team("Test task", agent_types=["writer"])
        config["tone"] = "formal"

        mock_provider = MagicMock()
        agents, _engine = gen.build(config, mock_provider)

        writer_agent = agents["writer"]
        assert "TONE & STYLE" in writer_agent.system_prompt
        assert "formal" in writer_agent.system_prompt.lower()

    def test_build_with_tone_skips_orchestrator(self):
        from unittest.mock import MagicMock

        from hiveflow.core.teams import TeamGenerator

        gen = TeamGenerator()
        config = gen.generate_team(
            "Test task",
            agent_types=["planner", "writer"],
            include_review=False,
        )
        config["tone"] = "executive"

        mock_provider = MagicMock()
        agents, _engine = gen.build(config, mock_provider)

        # planner is orchestrator — no tone injection
        assert "TONE & STYLE" not in agents["planner"].system_prompt
        # writer is llm_only — tone injected
        assert "TONE & STYLE" in agents["writer"].system_prompt

    def test_build_without_tone_leaves_prompts_unchanged(self):
        from unittest.mock import MagicMock

        from hiveflow.core.teams import TeamGenerator

        gen = TeamGenerator()
        config = gen.generate_team("Test task", agent_types=["writer"])
        # No tone set

        mock_provider = MagicMock()
        agents, _engine = gen.build(config, mock_provider)
        assert "TONE & STYLE" not in agents["writer"].system_prompt

    def test_build_with_inline_tone_definition(self):
        from unittest.mock import MagicMock

        from hiveflow.core.teams import TeamGenerator

        gen = TeamGenerator()
        config = gen.generate_team("Test task", agent_types=["writer"])
        config["tone"] = {
            "tone_id": "brand_voice",
            "label": "Brand Voice",
            "description": "Our company voice",
            "prompt_modifier": "Write in our distinctive brand voice.",
        }

        mock_provider = MagicMock()
        agents, _engine = gen.build(config, mock_provider)
        assert "brand voice" in agents["writer"].system_prompt.lower()

    def test_build_with_researcher_injects_tone(self):
        from unittest.mock import MagicMock

        from hiveflow.core.teams import TeamGenerator

        gen = TeamGenerator()
        config = gen.generate_team(
            "Test task",
            agent_types=["researcher"],
            include_review=False,
        )
        config["tone"] = "concise"

        mock_provider = MagicMock()
        agents, _engine = gen.build(config, mock_provider)

        # researcher is tool_user — tone is injected
        assert "TONE & STYLE" in agents["researcher"].system_prompt
