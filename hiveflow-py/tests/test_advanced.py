"""Tests for Citations, Compression, Prompts, and Team Templates."""

import json

import pytest

from hiveflow.core.citations import Citation, CitationTracker
from hiveflow.core.compression import ContextCompressor
from hiveflow.core.prompts import (
    PromptLibrary,
    PromptTemplate,
    get_default_library,
)
from hiveflow.core.teams import TeamGenerator, TeamTemplateLibrary

# --- Citation Tests ---


class TestCitation:
    def test_citation_id_is_stable(self):
        c = Citation(url="https://example.com", title="Test")
        cid1 = c.citation_id
        cid2 = c.citation_id
        assert cid1 == cid2
        assert len(cid1) == 8

    def test_format_apa(self):
        c = Citation(
            url="https://example.com",
            title="A Paper",
            author="Smith, J.",
            date="2024",
        )
        apa = c.format_apa()
        assert "Smith, J." in apa
        assert "2024" in apa
        assert "A Paper" in apa

    def test_format_inline_with_author(self):
        c = Citation(url="https://example.com", title="T", author="Smith", date="2024")
        assert c.format_inline() == "(Smith, 2024)"

    def test_format_inline_without_author(self):
        c = Citation(url="https://example.com", title="T")
        inline = c.format_inline()
        assert inline.startswith("[")

    def test_to_dict(self):
        c = Citation(url="https://example.com", title="Test")
        d = c.to_dict()
        assert d["url"] == "https://example.com"
        assert "citation_id" in d


class TestCitationTracker:
    def test_add_and_count(self):
        tracker = CitationTracker()
        tracker.add(Citation(url="https://a.com", title="A"))
        tracker.add(Citation(url="https://b.com", title="B"))
        assert tracker.count == 2

    def test_deduplication(self):
        tracker = CitationTracker()
        tracker.add(Citation(url="https://a.com", title="First"))
        tracker.add(Citation(url="https://a.com", title="Duplicate"))
        assert tracker.count == 1

    def test_add_from_search_result(self):
        tracker = CitationTracker()
        cid = tracker.add_from_search_result(
            title="Result", url="https://r.com", content="Some content",
        )
        assert isinstance(cid, str)
        assert tracker.count == 1

    def test_get_by_url(self):
        tracker = CitationTracker()
        tracker.add(Citation(url="https://a.com", title="A"))
        assert tracker.get("https://a.com") is not None
        assert tracker.get("https://b.com") is None

    def test_get_by_id(self):
        tracker = CitationTracker()
        c = Citation(url="https://a.com", title="A")
        tracker.add(c)
        found = tracker.get_by_id(c.citation_id)
        assert found is not None
        assert found.title == "A"

    def test_format_references_apa(self):
        tracker = CitationTracker()
        tracker.add(Citation(
            url="https://a.com", title="Paper A", author="Smith", date="2024",
        ))
        refs = tracker.format_references(style="apa")
        assert "References" in refs
        assert "Smith" in refs

    def test_format_references_numbered(self):
        tracker = CitationTracker()
        tracker.add(Citation(url="https://a.com", title="A"))
        refs = tracker.format_references(style="numbered")
        assert "1." in refs

    def test_format_references_empty(self):
        tracker = CitationTracker()
        assert tracker.format_references() == ""

    def test_to_state_dict(self):
        tracker = CitationTracker()
        tracker.add(Citation(url="https://a.com", title="A"))
        d = tracker.to_state_dict()
        assert d["citation_count"] == 1
        assert len(d["citations"]) == 1

    def test_clear(self):
        tracker = CitationTracker()
        tracker.add(Citation(url="https://a.com", title="A"))
        tracker.clear()
        assert tracker.count == 0


# --- Compression Tests ---


class TestContextCompressor:
    def test_compress_within_budget(self):
        compressor = ContextCompressor(max_words=100)
        chunks = [
            {"content": "Short text here.", "score": 0.9},
            {"content": "Another short piece.", "score": 0.5},
        ]
        result = compressor.compress(chunks)
        assert len(result) == 2

    def test_compress_exceeds_budget(self):
        compressor = ContextCompressor(max_words=10)
        chunks = [
            {"content": " ".join(["word"] * 20), "score": 0.9},
            {"content": " ".join(["word"] * 20), "score": 0.5},
        ]
        result = compressor.compress(chunks)
        total_words = sum(len(c["content"].split()) for c in result)
        assert total_words <= 10

    def test_compress_empty(self):
        compressor = ContextCompressor()
        assert compressor.compress([]) == []

    def test_deduplicate(self):
        compressor = ContextCompressor()
        chunks = [
            {"content": "Same content here", "score": 0.9},
            {"content": "Same content here", "score": 0.5},
        ]
        result = compressor.compress(chunks)
        assert len(result) == 1

    def test_query_scoring(self):
        compressor = ContextCompressor(max_words=100)
        chunks = [
            {"content": "python programming language"},
            {"content": "java coffee beans"},
        ]
        result = compressor.compress(chunks, query="python programming")
        # Python chunk should score higher and come first
        assert "python" in result[0]["content"]

    def test_format_context(self):
        compressor = ContextCompressor()
        chunks = [
            {"content": "Content 1", "source": "s1", "title": "Title 1"},
            {"content": "Content 2"},
        ]
        formatted = compressor.format_context(chunks)
        assert "Source 1: Title 1" in formatted
        assert "Content 1" in formatted

    def test_chunk_truncation(self):
        compressor = ContextCompressor(chunk_max_length=5)
        chunks = [{"content": " ".join(["word"] * 20)}]
        result = compressor.compress(chunks)
        assert len(result[0]["content"].split()) <= 5


# --- Prompt Template Tests ---


class TestPromptTemplate:
    def test_render_basic(self):
        t = PromptTemplate("Hello $name, your task is $task")
        result = t.render(name="Alice", task="research")
        assert result == "Hello Alice, your task is research"

    def test_render_missing_optional(self):
        t = PromptTemplate("Hello $name")
        result = t.render()
        assert result == "Hello $name"  # safe_substitute keeps unknowns

    def test_render_missing_required(self):
        t = PromptTemplate("Hello $name", required_vars=["name"])
        with pytest.raises(ValueError, match="missing required"):
            t.render()

    def test_variables_extraction(self):
        t = PromptTemplate("$greeting $name, your $task")
        vars_ = t.variables
        assert "greeting" in vars_
        assert "name" in vars_
        assert "task" in vars_

    def test_to_dict(self):
        t = PromptTemplate(
            "Hello $name", name="test", description="Test template",
        )
        d = t.to_dict()
        assert d["name"] == "test"
        assert "name" in d["variables"]


class TestPromptLibrary:
    def test_add_and_render(self):
        lib = PromptLibrary()
        lib.add(PromptTemplate("Hello $name", name="greeting"))
        result = lib.render("greeting", name="World")
        assert result == "Hello World"

    def test_get(self):
        lib = PromptLibrary()
        t = PromptTemplate("test", name="test")
        lib.add(t)
        assert lib.get("test") is t
        assert lib.get("nonexistent") is None

    def test_missing_template(self):
        lib = PromptLibrary()
        with pytest.raises(KeyError):
            lib.render("nonexistent")

    def test_no_name_raises(self):
        lib = PromptLibrary()
        with pytest.raises(ValueError, match="must have a name"):
            lib.add(PromptTemplate("test"))

    def test_list_templates(self):
        lib = PromptLibrary()
        lib.add(PromptTemplate("b", name="beta"))
        lib.add(PromptTemplate("a", name="alpha"))
        assert lib.list_templates() == ["alpha", "beta"]

    def test_from_directory(self, tmp_path):
        (tmp_path / "greeting.txt").write_text("Hello $name!", encoding="utf-8")
        (tmp_path / "task.txt").write_text("Do $action", encoding="utf-8")

        lib = PromptLibrary.from_directory(tmp_path)
        assert "greeting" in lib.list_templates()
        assert "task" in lib.list_templates()

    def test_from_nonexistent_directory(self, tmp_path):
        lib = PromptLibrary.from_directory(tmp_path / "nonexistent")
        assert lib.list_templates() == []


class TestDefaultLibrary:
    def test_has_builtin_templates(self):
        lib = get_default_library()
        templates = lib.list_templates()
        assert "system_researcher" in templates
        assert "system_writer" in templates
        assert "system_reviewer" in templates

    def test_builtin_renders(self):
        lib = get_default_library()
        result = lib.render("system_researcher", topic="AI", task="Find papers")
        assert "AI" in result
        assert "Find papers" in result


# --- Team Template Library Tests ---


class TestTeamTemplateLibrary:
    def test_register_and_get(self):
        lib = TeamTemplateLibrary()
        lib.register("test", {"name": "Test Team"})
        assert lib.get("test") == {"name": "Test Team"}
        assert lib.get("nonexistent") is None

    def test_list_templates(self):
        lib = TeamTemplateLibrary()
        lib.register("beta", {})
        lib.register("alpha", {})
        assert lib.list_templates() == ["alpha", "beta"]

    def test_from_directory(self, tmp_path):
        (tmp_path / "team1.json").write_text(
            json.dumps({"name": "Team 1"}), encoding="utf-8",
        )
        lib = TeamTemplateLibrary.from_directory(tmp_path)
        assert "team1" in lib.list_templates()
        assert lib.get("team1") == {"name": "Team 1"}

    def test_default_loads_bundled(self):
        lib = TeamTemplateLibrary.default()
        # Should have the research_report template
        templates = lib.list_templates()
        assert "research_report" in templates


class TestTeamGenerator:
    def test_generate_basic(self):
        gen = TeamGenerator()
        team = gen.generate_team("Write a report about AI")
        assert "agents" in team
        assert "workflow" in team
        assert len(team["agents"]) >= 2

    def test_generate_with_review(self):
        gen = TeamGenerator()
        team = gen.generate_team("Test task", include_review=True)
        agent_ids = [a["id"] for a in team["agents"]]
        assert "reviewer" in agent_ids

    def test_generate_without_review(self):
        gen = TeamGenerator()
        team = gen.generate_team(
            "Test task",
            agent_types=["researcher", "writer"],
            include_review=False,
        )
        agent_ids = [a["id"] for a in team["agents"]]
        assert "reviewer" not in agent_ids

    def test_generate_custom_types(self):
        gen = TeamGenerator()
        team = gen.generate_team(
            "Test",
            agent_types=["editor", "researcher", "writer"],
            include_review=False,
        )
        assert len(team["agents"]) == 3

    def test_workflow_steps_match_agents(self):
        gen = TeamGenerator()
        team = gen.generate_team("Test", include_review=False)
        agent_ids = {a["id"] for a in team["agents"]}
        step_agents = {s["agent"] for s in team["workflow"]["steps"]}
        assert step_agents == agent_ids


# ---------------------------------------------------------------------------
# T035 – Conditional ambiguity → reject default
# ---------------------------------------------------------------------------


class TestConditionalAmbiguity:
    """Tests for _evaluate_condition with tied accept/reject scores (T035)."""

    def _make_engine(self):
        from hiveflow.core.workflow import WorkflowEngine, WorkflowStep

        return WorkflowEngine([WorkflowStep(agent="reviewer", step_type="conditional")])

    def test_tied_scores_return_false(self):
        """Equal accept/reject keyword counts must follow the reject path."""
        engine = self._make_engine()
        # "approved" (accept) + "rejected" (reject) → 1-1 tie → False
        output = "The document is approved but also rejected by the board."
        result = engine._evaluate_condition("reviewer", output, {})
        assert result is False

    def test_tied_zero_scores_return_false(self):
        """No keywords at all (0-0 tie) must also reject."""
        engine = self._make_engine()
        result = engine._evaluate_condition("reviewer", "nothing relevant here", {})
        assert result is False

    def test_structlog_warning_on_ambiguous(self):
        """A structlog warning must be emitted when scores are tied."""
        import structlog

        engine = self._make_engine()
        captured = []

        def capture_factory(*args, **kwargs):
            def processor(logger, method_name, event_dict):
                captured.append(event_dict)
                raise structlog.DropEvent
            return structlog.wrap_logger(
                None,
                processors=[processor],
            )

        # Patch the logger returned by structlog.get_logger for the condition namespace
        from unittest.mock import patch

        with patch("structlog.get_logger") as mock_get:
            log_mock = structlog.get_logger("test")
            warnings = []

            class CapturingLogger:
                def warning(self, event, **kw):
                    warnings.append({"event": event, **kw})

                def __getattr__(self, name):
                    return lambda *a, **kw: None

            mock_get.return_value = CapturingLogger()
            engine._evaluate_condition("reviewer", "approved but rejected", {})

        assert len(warnings) == 1
        assert warnings[0]["event"] == "ambiguous_condition_result"
        assert warnings[0]["accept_score"] == warnings[0]["reject_score"]

    def test_accept_wins_when_higher(self):
        """More accept keywords → True."""
        engine = self._make_engine()
        output = "The work is approved, accepted, and satisfactory."
        assert engine._evaluate_condition("reviewer", output, {}) is True

    def test_reject_wins_when_higher(self):
        """More reject keywords → False."""
        engine = self._make_engine()
        output = "The work is rejected and needs revision and is insufficient."
        assert engine._evaluate_condition("reviewer", output, {}) is False

    def test_explicit_state_approved_overrides_keywords(self):
        """State signal reviewer_approved=True overrides keyword analysis."""
        engine = self._make_engine()
        state = {"reviewer_approved": True}
        assert engine._evaluate_condition("reviewer", "rejected", state) is True

    def test_explicit_state_rejected_overrides_keywords(self):
        """State signal reviewer_rejected=True overrides keyword analysis."""
        engine = self._make_engine()
        state = {"reviewer_rejected": True}
        assert engine._evaluate_condition("reviewer", "approved", state) is False


# ---------------------------------------------------------------------------
# T036 – Namespaced parallel merge
# ---------------------------------------------------------------------------


class TestNamespacedParallel:
    """Tests for _execute_parallel namespaced result dict (T036)."""

    @pytest.mark.asyncio
    async def test_parallel_results_dict_structure(self):
        """parallel_results dict uses item_0, item_1, … keys."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from hiveflow.core.agent import Agent
        from hiveflow.core.workflow import WorkflowEngine, WorkflowStep

        engine = WorkflowEngine([WorkflowStep(agent="writer", step_type="parallel")])
        engine.summarizer = None

        agent = MagicMock(spec=Agent)
        agent.agent_id = "writer"

        async def fake_execute(a, s):
            idx = s["item_index"]
            return {"writer_output": f"result_{idx}"}

        with patch.object(engine, "_execute_agent_with_failure_policy", new=fake_execute):
            state = {"parallel_items": ["a", "b", "c"]}
            result = await engine._execute_parallel(
                WorkflowStep(agent="writer", step_type="parallel"),
                {"writer": agent},
                state,
            )

        pr = result["writer_parallel_results"]
        assert set(pr.keys()) == {"item_0", "item_1", "item_2"}
        assert pr["item_0"]["writer_output"] == "result_0"
        assert pr["item_1"]["writer_output"] == "result_1"
        assert pr["item_2"]["writer_output"] == "result_2"

    @pytest.mark.asyncio
    async def test_backward_compat_outputs_list_and_output_string(self):
        """_outputs list and _output concatenated string still populated."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from hiveflow.core.agent import Agent
        from hiveflow.core.workflow import WorkflowEngine, WorkflowStep

        engine = WorkflowEngine([WorkflowStep(agent="writer", step_type="parallel")])
        engine.summarizer = None

        agent = MagicMock(spec=Agent)
        agent.agent_id = "writer"

        async def fake_execute(a, s):
            idx = s["item_index"]
            return {"writer_output": f"line_{idx}"}

        with patch.object(engine, "_execute_agent_with_failure_policy", new=fake_execute):
            state = {"parallel_items": ["x", "y"]}
            result = await engine._execute_parallel(
                WorkflowStep(agent="writer", step_type="parallel"),
                {"writer": agent},
                state,
            )

        assert result["writer_outputs"] == ["line_0", "line_1"]
        assert "line_0" in result["writer_output"]
        assert "line_1" in result["writer_output"]
