"""Deep Research Capability - Recursive multi-level research orchestration.

Provides breadth-first query tree generation, nested workflow spawning,
configurable breadth/depth/concurrency, branch merging, and progress
tracking across all research branches.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any

import structlog

from hiveflow.core.citations import CitationTracker
from hiveflow.core.compression import ContextCompressor

logger = structlog.get_logger()


@dataclass
class DeepResearchConfig:
    """Configuration for deep research execution.

    Attributes:
        breadth: Number of sub-queries per level
        depth: Maximum recursion depth
        concurrency: Max parallel research branches
        max_context_words: Context window budget across all branches
    """

    breadth: int = 3
    depth: int = 2
    concurrency: int = 4
    max_context_words: int = 25000


@dataclass
class BranchResult:
    """Result from a single research branch.

    Attributes:
        query: The query this branch researched
        findings: Text findings from this branch
        sub_results: Results from child branches (recursive)
        citations: Citations collected by this branch
        depth: Depth level of this branch (0 = root)
        error: Error message if branch failed
    """

    query: str
    findings: str = ""
    sub_results: list["BranchResult"] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    depth: int = 0
    error: str | None = None

    @property
    def all_findings(self) -> list[str]:
        """Collect findings from this branch and all sub-branches."""
        result = []
        if self.findings:
            result.append(self.findings)
        for sub in self.sub_results:
            result.extend(sub.all_findings)
        return result

    @property
    def all_citations(self) -> list[dict[str, Any]]:
        """Collect citations from this branch and all sub-branches."""
        result = list(self.citations)
        for sub in self.sub_results:
            result.extend(sub.all_citations)
        return result

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "query": self.query,
            "findings": self.findings,
            "sub_results": [s.to_dict() for s in self.sub_results],
            "citations": self.citations,
            "depth": self.depth,
            "error": self.error,
        }


@dataclass
class ResearchProgress:
    """Tracks progress across all research branches.

    Thread-safe progress tracking for reporting completion
    percentage during deep research execution.
    """

    total_branches: int = 0
    completed_branches: int = 0
    failed_branches: int = 0
    current_depth: int = 0
    max_depth: int = 0

    @property
    def completion_percentage(self) -> float:
        """Calculate completion percentage (0.0 to 100.0)."""
        if self.total_branches == 0:
            return 0.0
        return (self.completed_branches / self.total_branches) * 100.0

    @property
    def is_complete(self) -> bool:
        """Check if all branches have been processed."""
        return self.completed_branches + self.failed_branches >= self.total_branches

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "total_branches": self.total_branches,
            "completed_branches": self.completed_branches,
            "failed_branches": self.failed_branches,
            "current_depth": self.current_depth,
            "max_depth": self.max_depth,
            "completion_percentage": round(self.completion_percentage, 1),
            "is_complete": self.is_complete,
        }


# Type for research functions that can be provided by the caller
ResearchFunc = Any  # Callable[[str, dict], Awaitable[dict]]
QueryGeneratorFunc = Any  # Callable[[str, int], Awaitable[list[str]]]


class DeepResearcher:
    """Orchestrates recursive multi-level research.

    Given a topic, generates a breadth-first query tree and spawns
    nested research workflows for each branch up to a configurable
    depth. Results are merged and compressed to fit context budgets.

    Usage:
        researcher = DeepResearcher(
            config=DeepResearchConfig(breadth=3, depth=2),
            research_fn=my_research_function,
            query_generator_fn=my_query_generator,
        )
        result = await researcher.research("Impact of AI on healthcare")
    """

    def __init__(
        self,
        config: DeepResearchConfig | None = None,
        research_fn: ResearchFunc | None = None,
        query_generator_fn: QueryGeneratorFunc | None = None,
    ) -> None:
        """Initialize deep researcher.

        Args:
            config: Research configuration
            research_fn: Async function(query, context) -> {"findings": str, "citations": list}
            query_generator_fn: Async function(topic, breadth) -> list[str]
        """
        self.config = config or DeepResearchConfig()
        self._research_fn = research_fn
        self._query_generator_fn = query_generator_fn
        self._progress = ResearchProgress(max_depth=self.config.depth)
        self._citation_tracker = CitationTracker()
        self._compressor = ContextCompressor(
            max_words=self.config.max_context_words,
        )
        self._semaphore = asyncio.Semaphore(self.config.concurrency)

    @property
    def progress(self) -> ResearchProgress:
        """Current research progress."""
        return self._progress

    @property
    def citations(self) -> CitationTracker:
        """Citation tracker with all collected citations."""
        return self._citation_tracker

    async def research(
        self,
        topic: str,
        context: dict[str, Any] | None = None,
    ) -> BranchResult:
        """Execute deep research on a topic.

        Args:
            topic: Main research topic/question
            context: Optional initial context

        Returns:
            BranchResult with all findings and sub-results
        """
        self._progress = ResearchProgress(max_depth=self.config.depth)
        self._citation_tracker.clear()

        logger.info(
            "Starting deep research: topic=%r, breadth=%d, depth=%d",
            topic,
            self.config.breadth,
            self.config.depth,
        )

        result = await self._research_branch(
            query=topic,
            depth=0,
            context=context or {},
        )

        logger.info(
            "Deep research complete: %d branches, %d citations",
            self._progress.completed_branches,
            self._citation_tracker.count,
        )

        return result

    async def _research_branch(
        self,
        query: str,
        depth: int,
        context: dict[str, Any],
    ) -> BranchResult:
        """Research a single branch, potentially spawning sub-branches.

        Args:
            query: Query for this branch
            depth: Current recursion depth
            context: Accumulated context

        Returns:
            BranchResult for this branch
        """
        self._progress.current_depth = max(self._progress.current_depth, depth)
        result = BranchResult(query=query, depth=depth)

        # Execute research for this branch
        try:
            async with self._semaphore:
                branch_result = await self._execute_research(query, context)

            result.findings = branch_result.get("findings", "")
            result.citations = branch_result.get("citations", [])

            # Track citations
            for cite in result.citations:
                if isinstance(cite, dict) and "url" in cite and "title" in cite:
                    self._citation_tracker.add_from_search_result(
                        title=cite["title"],
                        url=cite["url"],
                        content=cite.get("content", ""),
                    )

            self._progress.completed_branches += 1

        except Exception as e:
            logger.warning("Research branch failed for query %r: %s", query, e)
            result.error = str(e)
            self._progress.failed_branches += 1
            return result

        # Recurse if not at max depth
        if depth < self.config.depth:
            sub_queries = await self._generate_sub_queries(query, depth)
            self._progress.total_branches += len(sub_queries)

            # Execute sub-branches concurrently (bounded by semaphore)
            sub_context = {
                **context,
                "parent_query": query,
                "parent_findings": result.findings,
                "depth": depth + 1,
            }

            tasks = [self._research_branch(sq, depth + 1, sub_context) for sq in sub_queries]
            sub_results = await asyncio.gather(*tasks, return_exceptions=True)

            for sr in sub_results:
                if isinstance(sr, BaseException):
                    logger.warning("Sub-branch failed: %s", sr)
                    self._progress.failed_branches += 1
                else:
                    result.sub_results.append(sr)

        return result

    async def _execute_research(self, query: str, context: dict[str, Any]) -> dict[str, Any]:
        """Execute research for a single query.

        If a research_fn was provided, delegates to it. Otherwise returns
        an empty result (to be wired up with actual agents).

        Args:
            query: Research query
            context: Current context

        Returns:
            Dict with 'findings' and 'citations' keys
        """
        if self._research_fn is not None:
            result: dict[str, Any] = await self._research_fn(query, context)
            return result

        # Default: no-op placeholder
        return {"findings": "", "citations": []}

    async def _generate_sub_queries(self, query: str, _depth: int) -> list[str]:
        """Generate sub-queries for deeper research.

        If a query_generator_fn was provided, delegates to it. Otherwise
        returns an empty list (no further branching).

        Args:
            query: Parent query to decompose
            _depth: Current depth level (reserved for future use)

        Returns:
            List of sub-query strings
        """
        if self._query_generator_fn is not None:
            queries: list[str] = await self._query_generator_fn(query, self.config.breadth)
            return queries[: self.config.breadth]

        return []

    def merge_findings(self, result: BranchResult) -> str:
        """Merge all findings from a research tree into compressed context.

        Args:
            result: Root BranchResult containing the full tree

        Returns:
            Compressed, merged text of all findings
        """
        all_findings = result.all_findings
        if not all_findings:
            return ""

        # Build chunks from findings for compression
        chunks = [
            {"content": finding, "score": 1.0 / (i + 1)} for i, finding in enumerate(all_findings)
        ]

        compressed = self._compressor.compress(chunks, query=result.query)
        return self._compressor.format_context(compressed, include_sources=False)

    def get_research_state(self, result: BranchResult) -> dict[str, Any]:
        """Build a state dict from research results.

        Suitable for passing into a workflow state for further processing.

        Args:
            result: Root BranchResult

        Returns:
            State dictionary with research findings, citations, and progress
        """
        return {
            "research_topic": result.query,
            "research_findings": self.merge_findings(result),
            "research_tree": result.to_dict(),
            "research_citations": self._citation_tracker.to_state_dict(),
            "research_progress": self._progress.to_dict(),
        }
