"""Source Citation & Reference System - Track and format source citations.

Provides citation tracking across agent workflows, ensuring all sourced
information can be traced back and formatted in standard citation styles.
"""

import hashlib
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass
class Citation:
    """A single source citation."""

    url: str
    title: str
    content_snippet: str = ""
    author: str = ""
    date: str = ""
    source: str = ""  # Publication/journal name for MLA/Chicago
    source_type: str = "web"  # web, academic, document, api
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def citation_id(self) -> str:
        """Generate a stable short ID for this citation."""
        return hashlib.md5(self.url.encode()).hexdigest()[:8]

    def format_apa(self) -> str:
        """Format citation in APA style."""
        parts = []
        if self.author:
            parts.append(f"{self.author}.")
        if self.date:
            parts.append(f"({self.date}).")
        parts.append(f"{self.title}.")
        if self.url:
            parts.append(f"Retrieved from {self.url}")
        return " ".join(parts)

    def format_inline(self) -> str:
        """Format as inline reference."""
        if self.author and self.date:
            return f"({self.author}, {self.date})"
        return f"[{self.citation_id}]"

    def format_mla(self) -> str:
        """Format citation in MLA style."""
        parts = []
        if self.author:
            parts.append(f"{self.author}.")
        parts.append(f'"{self.title}."')
        if self.source:
            parts.append(f"*{self.source}*,")
        if self.date:
            parts.append(f"{self.date}.")
        if self.url:
            parts.append(f"{self.url}.")
        return " ".join(parts)

    def format_chicago(self) -> str:
        """Format citation in Chicago style."""
        parts = []
        if self.author:
            parts.append(f"{self.author}.")
        parts.append(f'"{self.title}."')
        if self.source:
            parts.append(f"*{self.source}*.")
        if self.date:
            parts.append(f"Last modified {self.date}.")
        if self.url:
            parts.append(self.url)
        return " ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "citation_id": self.citation_id,
            "url": self.url,
            "title": self.title,
            "content_snippet": self.content_snippet,
            "author": self.author,
            "date": self.date,
            "source_type": self.source_type,
            "metadata": self.metadata,
        }


class CitationTracker:
    """Tracks citations across a workflow execution.

    Collects citations as agents process information, deduplicates them,
    and generates formatted reference lists.

    Usage:
        tracker = CitationTracker()
        tracker.add(Citation(url="...", title="..."))
        references = tracker.format_references()
    """

    def __init__(self) -> None:
        self._citations: dict[str, Citation] = {}  # keyed by URL

    def add(self, citation: Citation) -> str:
        """Add a citation. Deduplicates by URL.

        Args:
            citation: Citation to add

        Returns:
            Citation ID for inline reference
        """
        if citation.url not in self._citations:
            self._citations[citation.url] = citation
        return citation.citation_id

    def add_from_search_result(
        self,
        title: str,
        url: str,
        content: str,
        **kwargs: Any,
    ) -> str:
        """Add a citation from a search result.

        Args:
            title: Result title
            url: Result URL
            content: Content snippet
            **kwargs: Additional citation fields

        Returns:
            Citation ID
        """
        citation = Citation(
            url=url,
            title=title,
            content_snippet=content[:500] if content else "",
            **kwargs,
        )
        return self.add(citation)

    def get(self, url: str) -> Citation | None:
        """Get a citation by URL.

        Args:
            url: Citation URL

        Returns:
            Citation or None
        """
        return self._citations.get(url)

    def get_by_id(self, citation_id: str) -> Citation | None:
        """Get a citation by its short ID.

        Args:
            citation_id: Citation short ID

        Returns:
            Citation or None
        """
        for citation in self._citations.values():
            if citation.citation_id == citation_id:
                return citation
        return None

    @property
    def citations(self) -> list[Citation]:
        """All tracked citations in order of addition."""
        return list(self._citations.values())

    @property
    def count(self) -> int:
        """Number of tracked citations."""
        return len(self._citations)

    def format_references(self, style: str = "apa") -> str:
        """Format all citations as a reference list.

        Args:
            style: Citation style ('apa', 'numbered', 'inline', 'mla', 'chicago')

        Returns:
            Formatted reference list string
        """
        if not self._citations:
            return ""

        lines = ["## References\n"]

        if style == "numbered":
            for i, citation in enumerate(self._citations.values(), 1):
                lines.append(f"{i}. {citation.format_apa()}")
        elif style == "inline":
            for citation in self._citations.values():
                lines.append(f"- [{citation.citation_id}] {citation.format_apa()}")
        elif style == "mla":
            for citation in self._citations.values():
                lines.append(f"- {citation.format_mla()}")
        elif style == "chicago":
            for citation in self._citations.values():
                lines.append(f"- {citation.format_chicago()}")
        else:  # apa
            for citation in self._citations.values():
                lines.append(f"- {citation.format_apa()}")

        return "\n".join(lines)

    def to_state_dict(self) -> dict[str, Any]:
        """Export citations for workflow state.

        Returns:
            Dictionary suitable for workflow state
        """
        return {
            "citation_count": self.count,
            "citations": [c.to_dict() for c in self.citations],
        }

    def clear(self) -> None:
        """Remove all tracked citations."""
        self._citations.clear()
