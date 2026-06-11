"""Tests for Deep Research Capability."""

import pytest

from hiveflow.core.research import (
    BranchResult,
    DeepResearchConfig,
    DeepResearcher,
    ResearchProgress,
)

# --- Config Tests ---


class TestDeepResearchConfig:
    def test_defaults(self):
        cfg = DeepResearchConfig()
        assert cfg.breadth == 3
        assert cfg.depth == 2
        assert cfg.concurrency == 4
        assert cfg.max_context_words == 25000

    def test_custom(self):
        cfg = DeepResearchConfig(breadth=5, depth=3, concurrency=8, max_context_words=10000)
        assert cfg.breadth == 5
        assert cfg.depth == 3


# --- Progress Tests ---


class TestResearchProgress:
    def test_zero_progress(self):
        p = ResearchProgress()
        assert p.completion_percentage == 0.0
        assert p.is_complete is True  # 0 of 0

    def test_partial_progress(self):
        p = ResearchProgress(total_branches=10, completed_branches=3)
        assert p.completion_percentage == 30.0
        assert p.is_complete is False

    def test_complete_progress(self):
        p = ResearchProgress(total_branches=5, completed_branches=5)
        assert p.completion_percentage == 100.0
        assert p.is_complete is True

    def test_failed_counts_toward_complete(self):
        p = ResearchProgress(total_branches=4, completed_branches=2, failed_branches=2)
        assert p.is_complete is True

    def test_to_dict(self):
        p = ResearchProgress(total_branches=10, completed_branches=7, max_depth=3)
        d = p.to_dict()
        assert d["total_branches"] == 10
        assert d["completion_percentage"] == 70.0
        assert d["max_depth"] == 3


# --- BranchResult Tests ---


class TestBranchResult:
    def test_basic(self):
        r = BranchResult(query="test", findings="some findings", depth=0)
        assert r.query == "test"
        assert r.all_findings == ["some findings"]

    def test_nested_findings(self):
        child = BranchResult(query="sub", findings="child findings", depth=1)
        parent = BranchResult(
            query="main", findings="parent findings", depth=0, sub_results=[child],
        )
        assert parent.all_findings == ["parent findings", "child findings"]

    def test_nested_citations(self):
        child = BranchResult(
            query="sub", depth=1,
            citations=[{"url": "https://b.com", "title": "B"}],
        )
        parent = BranchResult(
            query="main", depth=0, sub_results=[child],
            citations=[{"url": "https://a.com", "title": "A"}],
        )
        all_cites = parent.all_citations
        assert len(all_cites) == 2
        assert all_cites[0]["url"] == "https://a.com"
        assert all_cites[1]["url"] == "https://b.com"

    def test_to_dict(self):
        r = BranchResult(query="q", findings="f", depth=1, error="oops")
        d = r.to_dict()
        assert d["query"] == "q"
        assert d["findings"] == "f"
        assert d["depth"] == 1
        assert d["error"] == "oops"

    def test_empty_findings(self):
        r = BranchResult(query="empty")
        assert r.all_findings == []


# --- DeepResearcher Tests ---


class TestDeepResearcher:
    @pytest.mark.asyncio
    async def test_research_no_functions(self):
        """Without research/query functions, returns empty results."""
        researcher = DeepResearcher()
        result = await researcher.research("Test topic")
        assert result.query == "Test topic"
        assert result.findings == ""
        assert result.sub_results == []

    @pytest.mark.asyncio
    async def test_research_with_research_fn(self):
        """With a research function, captures findings."""
        async def mock_research(query: str, context: dict) -> dict:
            return {
                "findings": f"Findings for: {query}",
                "citations": [{"url": "https://a.com", "title": "A"}],
            }

        researcher = DeepResearcher(research_fn=mock_research)
        result = await researcher.research("AI in healthcare")
        assert "Findings for: AI in healthcare" in result.findings
        assert len(result.citations) == 1
        assert researcher.citations.count == 1

    @pytest.mark.asyncio
    async def test_research_with_branching(self):
        """With query generator, spawns sub-branches."""
        call_count = 0

        async def mock_research(query: str, context: dict) -> dict:
            nonlocal call_count
            call_count += 1
            return {"findings": f"Finding #{call_count}", "citations": []}

        async def mock_query_gen(query: str, breadth: int) -> list[str]:
            return [f"{query} - sub{i}" for i in range(breadth)]

        config = DeepResearchConfig(breadth=2, depth=1, concurrency=4)
        researcher = DeepResearcher(
            config=config,
            research_fn=mock_research,
            query_generator_fn=mock_query_gen,
        )
        result = await researcher.research("Main topic")

        # Root + 2 sub-branches
        assert call_count == 3
        assert len(result.sub_results) == 2
        assert result.depth == 0
        assert result.sub_results[0].depth == 1

    @pytest.mark.asyncio
    async def test_depth_limit(self):
        """Research stops at configured depth."""
        queries_at_depth: dict[int, int] = {}

        async def mock_research(query: str, context: dict) -> dict:
            depth = context.get("depth", 0)
            queries_at_depth[depth] = queries_at_depth.get(depth, 0) + 1
            return {"findings": "f", "citations": []}

        async def mock_query_gen(query: str, breadth: int) -> list[str]:
            return [f"{query}-sub"]

        config = DeepResearchConfig(breadth=1, depth=2, concurrency=4)
        researcher = DeepResearcher(
            config=config,
            research_fn=mock_research,
            query_generator_fn=mock_query_gen,
        )
        await researcher.research("Root")

        # depth 0 (root): research called with no depth context
        # depth 1: 1 sub-branch
        # depth 2: 1 sub-sub-branch
        # depth 3: should NOT happen (depth limit is 2)
        assert researcher.progress.current_depth == 2

    @pytest.mark.asyncio
    async def test_research_fn_failure(self):
        """Failed research branches are tracked."""
        async def failing_research(query: str, context: dict) -> dict:
            raise RuntimeError("API error")

        researcher = DeepResearcher(research_fn=failing_research)
        result = await researcher.research("Will fail")
        assert result.error == "API error"
        assert researcher.progress.failed_branches == 1

    @pytest.mark.asyncio
    async def test_progress_tracking(self):
        """Progress updates during execution."""
        async def mock_research(query: str, context: dict) -> dict:
            return {"findings": "ok", "citations": []}

        async def mock_query_gen(query: str, breadth: int) -> list[str]:
            return ["sub1", "sub2"]

        config = DeepResearchConfig(breadth=2, depth=1)
        researcher = DeepResearcher(
            config=config,
            research_fn=mock_research,
            query_generator_fn=mock_query_gen,
        )
        await researcher.research("Topic")

        p = researcher.progress
        assert p.completed_branches == 3  # root + 2 subs
        assert p.failed_branches == 0

    @pytest.mark.asyncio
    async def test_merge_findings(self):
        """merge_findings compresses results from all branches."""
        async def mock_research(query: str, context: dict) -> dict:
            return {"findings": f"Info about {query}", "citations": []}

        async def mock_query_gen(query: str, breadth: int) -> list[str]:
            return ["sub1"]

        config = DeepResearchConfig(breadth=1, depth=1)
        researcher = DeepResearcher(
            config=config,
            research_fn=mock_research,
            query_generator_fn=mock_query_gen,
        )
        result = await researcher.research("Test")
        merged = researcher.merge_findings(result)
        assert "Info about Test" in merged
        assert "Info about sub1" in merged

    @pytest.mark.asyncio
    async def test_get_research_state(self):
        """get_research_state builds a complete state dict."""
        async def mock_research(query: str, context: dict) -> dict:
            return {
                "findings": "Some findings",
                "citations": [{"url": "https://a.com", "title": "A"}],
            }

        researcher = DeepResearcher(research_fn=mock_research)
        result = await researcher.research("Topic")
        state = researcher.get_research_state(result)

        assert state["research_topic"] == "Topic"
        assert "research_findings" in state
        assert state["research_citations"]["citation_count"] == 1
        assert state["research_progress"]["completed_branches"] == 1

    @pytest.mark.asyncio
    async def test_concurrency_limiting(self):
        """Concurrency semaphore limits parallel branches."""
        import asyncio

        max_concurrent = 0
        current_concurrent = 0
        lock = asyncio.Lock()

        async def tracked_research(query: str, context: dict) -> dict:
            nonlocal max_concurrent, current_concurrent
            async with lock:
                current_concurrent += 1
                max_concurrent = max(max_concurrent, current_concurrent)
            await asyncio.sleep(0.01)
            async with lock:
                current_concurrent -= 1
            return {"findings": "ok", "citations": []}

        async def mock_query_gen(query: str, breadth: int) -> list[str]:
            return [f"sub{i}" for i in range(breadth)]

        config = DeepResearchConfig(breadth=6, depth=1, concurrency=2)
        researcher = DeepResearcher(
            config=config,
            research_fn=tracked_research,
            query_generator_fn=mock_query_gen,
        )
        await researcher.research("Test")

        assert max_concurrent <= 2

    @pytest.mark.asyncio
    async def test_breadth_limiting(self):
        """Query generator results are capped at breadth."""
        async def mock_research(query: str, context: dict) -> dict:
            return {"findings": "f", "citations": []}

        async def greedy_query_gen(query: str, breadth: int) -> list[str]:
            return [f"sub{i}" for i in range(10)]  # Returns more than breadth

        config = DeepResearchConfig(breadth=3, depth=1)
        researcher = DeepResearcher(
            config=config,
            research_fn=mock_research,
            query_generator_fn=greedy_query_gen,
        )
        result = await researcher.research("Test")

        assert len(result.sub_results) == 3
