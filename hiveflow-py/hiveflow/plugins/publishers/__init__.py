"""Publisher Plugin System - Output format conversion and delivery.

Publishers convert workflow output into final deliverable formats:
markdown, PDF, DOCX, HTML, etc.
"""

import time
from abc import abstractmethod
from pathlib import Path
from typing import Any

import structlog

from hiveflow.core.layout import LayoutTemplate, load_layout
from hiveflow.core.registry import BasePlugin, PluginRegistry
from hiveflow.core.result_payload import ResultPayload

logger = structlog.get_logger()


class PublisherPlugin(BasePlugin):
    """Base class for publisher plugins.

    Publishers implement one or both of:
    - ``publish(content, output_path, metadata)`` — legacy string-based API.
    - ``publish_payload(payload, output_path, layout, config)`` — new
      payload-aware API.

    The registry calls ``publish_payload`` if defined; otherwise it extracts
    ``content`` from the payload and falls back to ``publish``.
    """

    @staticmethod
    def assemble_markdown(
        payload: ResultPayload,
        layout: LayoutTemplate | None = None,
    ) -> str:
        """Build a Markdown string from a ResultPayload, using layout if provided.

        When *layout* is given, ``layout.apply(payload)`` controls section
        ordering.  Otherwise falls back to a hardcoded order: title →
        content → sections (sorted by order) → references.

        This is a shared helper for pandoc-based publishers (PDF, DOCX, HTML)
        that convert Markdown as an intermediate step.
        """
        if layout is not None:
            return _assemble_from_layout(payload, layout)
        return _assemble_hardcoded(payload)

    @property
    @abstractmethod
    def plugin_id(self) -> str:
        """Publisher identifier (e.g., 'markdown', 'pdf')."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description."""
        ...

    @property
    @abstractmethod
    def output_extension(self) -> str:
        """File extension for output (e.g., '.pdf', '.md')."""
        ...

    @abstractmethod
    async def publish(
        self,
        content: str,
        output_path: str | Path,
        metadata: dict[str, Any] | None = None,
    ) -> Path:
        """Publish content to the target format (legacy API).

        Args:
            content: Source content (typically markdown)
            output_path: Destination file path
            metadata: Optional metadata (title, author, etc.)

        Returns:
            Path to the created output file
        """
        ...

    async def publish_payload(
        self,
        payload: ResultPayload,
        output_path: str | Path,
        layout: LayoutTemplate | None = None,  # noqa: ARG002
        config: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> Path:
        """Publish a full ResultPayload to the target format.

        Default implementation extracts ``payload.content`` and delegates
        to the legacy ``publish()`` method for backward compatibility.
        Override this in new publishers for full payload-aware rendering.

        Args:
            payload: Structured workflow result.
            output_path: Destination file path.
            layout: Optional layout template for section ordering.
            config: Optional publisher-specific configuration.

        Returns:
            Path to the created output file.
        """
        return await self.publish(
            content=payload.content,
            output_path=output_path,
            metadata=payload.metadata,
        )


# ---------------------------------------------------------------------------
# Shared Markdown assembly helpers for pandoc-based publishers
# ---------------------------------------------------------------------------


def _strip_leading_h1(text: str) -> str:
    """Remove a leading ``# ...`` line to avoid duplicate titles."""
    stripped = text.lstrip("\n")
    if stripped.startswith("# "):
        _, _, rest = stripped.partition("\n")
        return rest.lstrip("\n")
    return text


def _assemble_hardcoded(payload: ResultPayload) -> str:
    """Build Markdown with a fixed section order (no layout template)."""
    parts: list[str] = []
    parts.append(f"# {payload.title}\n")
    if payload.content:
        parts.append(_strip_leading_h1(payload.content))
    for section in sorted(payload.sections, key=lambda s: s.order):
        parts.append(f"\n## {section.title}\n")
        parts.append(_strip_leading_h1(section.content))
    if payload.references:
        parts.append("\n## References\n")
        for i, ref in enumerate(payload.references, 1):
            parts.append(f"{i}. [{ref.title}]({ref.url})")
    return "\n".join(parts)


def _assemble_from_layout(
    payload: ResultPayload,
    layout: LayoutTemplate,
) -> str:
    """Build Markdown using ``layout.apply()`` for section ordering."""
    rendered = layout.apply(payload)
    parts: list[str] = []
    parts.append(f"# {payload.title}\n")
    for section in rendered:
        if section.heading:
            parts.append(f"\n## {section.heading}\n")
        if section.content and section.content != "True":
            parts.append(_strip_leading_h1(section.content))
    # Always include references even if not in the layout
    if payload.references:
        parts.append("\n## References\n")
        for i, ref in enumerate(payload.references, 1):
            parts.append(f"{i}. [{ref.title}]({ref.url})")
    return "\n".join(parts)


class MarkdownPublisher(PublisherPlugin):
    """Built-in publisher that writes markdown output.

    When invoked with a ``ResultPayload``, renders a structured document
    using the active layout template with YAML frontmatter, optional table
    of contents, references section, and cost appendix.
    """

    @property
    def plugin_id(self) -> str:
        return "markdown"

    @property
    def description(self) -> str:
        return "Markdown output publisher"

    @property
    def output_extension(self) -> str:
        return ".md"

    async def publish(
        self,
        content: str,
        output_path: str | Path,
        metadata: dict[str, Any] | None = None,
    ) -> Path:
        """Write content as markdown file (legacy API).

        Args:
            content: Markdown content
            output_path: Output file path
            metadata: Optional metadata to prepend as YAML frontmatter

        Returns:
            Path to created file
        """
        path = Path(output_path)
        if not path.suffix:
            path = path.with_suffix(".md")

        path.parent.mkdir(parents=True, exist_ok=True)

        output = ""
        if metadata:
            output += "---\n"
            for key, value in metadata.items():
                output += f"{key}: {value}\n"
            output += "---\n\n"
        output += content

        path.write_text(output, encoding="utf-8")
        logger.info(
            "output.publish.complete",
            extra={"publisher_id": "markdown", "format": "markdown", "output_path": str(path)},
        )
        return path

    @staticmethod
    def _strip_leading_h1(text: str) -> str:
        """Remove a leading ``# ...`` line to avoid duplicate titles."""
        stripped = text.lstrip("\n")
        if stripped.startswith("# "):
            _, _, rest = stripped.partition("\n")
            return rest.lstrip("\n")
        return text

    async def publish_payload(
        self,
        payload: ResultPayload,
        output_path: str | Path,
        layout: LayoutTemplate | None = None,  # noqa: ARG002
        config: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> Path:
        """Publish a ResultPayload as a structured Markdown document.

        Renders the payload using the provided layout template (or a simple
        default order) with YAML frontmatter, optional TOC, references, and
        a cost/token appendix.

        Args:
            payload: Structured workflow result.
            output_path: Destination file path.
            layout: Optional layout template for section ordering.
            config: Optional publisher-specific config.

        Returns:
            Path to the created .md file.

        Raises:
            ValueError: If payload.content is empty.
        """
        if not payload.content and not payload.sections:
            raise ValueError("Cannot publish empty ResultPayload (no content or sections)")

        path = Path(output_path)
        if not path.suffix:
            path = path.with_suffix(".md")
        path.parent.mkdir(parents=True, exist_ok=True)

        parts: list[str] = []

        # --- YAML frontmatter ---
        parts.append("---")
        parts.append(f"title: {payload.title}")
        for key, value in payload.metadata.items():
            parts.append(f"{key}: {value}")
        parts.append("---")
        parts.append("")

        # --- Title ---
        parts.append(f"# {payload.title}")
        parts.append("")

        # --- Table of Contents ---
        if payload.sections:
            parts.append("## Table of Contents")
            parts.append("")
            for section in sorted(payload.sections, key=lambda s: s.order):
                anchor = section.section_id.replace(" ", "-").lower()
                parts.append(f"- [{section.title}](#{anchor})")
            parts.append("")

        # --- Section content ---
        for section in sorted(payload.sections, key=lambda s: s.order):
            parts.append(f"## {section.title}")
            parts.append("")
            parts.append(self._strip_leading_h1(section.content))
            parts.append("")

        # --- Main content (if no sections or as fallback) ---
        if not payload.sections and payload.content:
            parts.append(self._strip_leading_h1(payload.content))
            parts.append("")

        # --- Actions taken ---
        if payload.actions:
            parts.append("## Actions Taken")
            parts.append("")
            for action in payload.actions:
                parts.append(f"- **{action.action_type}** ({action.status}): {action.description}")
            parts.append("")

        # --- References ---
        if payload.references:
            parts.append("## References")
            parts.append("")
            for i, ref in enumerate(payload.references, 1):
                line = f"{i}. [{ref.title}]({ref.url})"
                if ref.author:
                    line += f" — {ref.author}"
                parts.append(line)
            parts.append("")

        # --- Appendix: Cost & Token Usage ---
        cost = payload.cost_summary
        if cost.total_tokens > 0:
            parts.append("## Appendix: Cost & Token Usage")
            parts.append("")
            parts.append(f"- **Total tokens**: {cost.total_tokens:,}")
            parts.append(f"- **Prompt tokens**: {cost.total_prompt_tokens:,}")
            parts.append(f"- **Completion tokens**: {cost.total_completion_tokens:,}")
            parts.append(f"- **Estimated cost**: ${cost.total_estimated_cost_usd:.4f}")
            if cost.agent_summaries:
                parts.append("")
                parts.append("| Agent | Tokens | Calls | Est. Cost |")
                parts.append("|-------|--------|-------|-----------|")
                for agent_id, summary in cost.agent_summaries.items():
                    parts.append(
                        f"| {agent_id} | {summary.total_tokens:,} "
                        f"| {summary.call_count} "
                        f"| ${summary.total_estimated_cost_usd:.4f} |"
                    )
            parts.append("")

        output = "\n".join(parts)
        path.write_text(output, encoding="utf-8")
        logger.info(
            "output.publish.complete",
            extra={"publisher_id": "markdown", "format": "markdown", "output_path": str(path)},
        )
        return path


class PublisherRegistry(PluginRegistry["PublisherPlugin"]):
    """Registry for publisher plugins.

    Discovers publishers from:
    - Built-in MarkdownPublisher (always registered)
    - Python entry points under 'hiveflow.publishers'
    - Drop-in directory
    """

    def __init__(self, drop_in_dir: str | None = "publishers") -> None:
        super().__init__(
            entry_point_group="hiveflow.publishers",
            drop_in_dir=drop_in_dir,
        )

    @classmethod
    def create(cls, drop_in_dir: str | None = None) -> "PublisherRegistry":
        """Create a registry with all available publishers discovered.

        Registers the built-in MarkdownPublisher, then runs entry-point
        and drop-in discovery so every installed publisher is available.

        Args:
            drop_in_dir: Optional path to a drop-in plugin directory.

        Returns:
            A fully-populated PublisherRegistry.
        """
        registry = cls(drop_in_dir=drop_in_dir)
        registry.register(MarkdownPublisher())
        registry.discover()
        return registry

    # ------------------------------------------------------------------
    # Legacy string-based API (backward compatible)
    # ------------------------------------------------------------------

    async def publish_all(
        self,
        content: str | ResultPayload,
        output_dir: str | Path,
        formats: list[str],
        filename: str = "output",
        metadata: dict[str, Any] | None = None,
        *,
        layout: str | LayoutTemplate | None = None,
        config: dict[str, Any] | None = None,
    ) -> list[Path]:
        """Publish content in multiple formats.

        Supports both the legacy string API and the new ResultPayload API.
        When *content* is a ``ResultPayload``, each publisher's
        ``publish_payload()`` method is called.  When *content* is a plain
        string, the legacy ``publish()`` method is used.

        Failures in individual publishers are logged but do not prevent
        other publishers from completing.

        Args:
            content: Source content (str) or a ResultPayload.
            output_dir: Output directory.
            formats: List of publisher IDs to use.
            filename: Base filename (without extension).
            metadata: Optional metadata (used only for string content).
            layout: Layout template name or object (payload mode only).
            config: Publisher-specific config (payload mode only).

        Returns:
            List of created file paths.
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # De-duplicate formats while preserving order
        seen: set[str] = set()
        unique_formats: list[str] = []
        for fmt in formats:
            if fmt not in seen:
                seen.add(fmt)
                unique_formats.append(fmt)

        # Resolve layout if given as a string
        resolved_layout: LayoutTemplate | None = None
        if isinstance(layout, str):
            resolved_layout = load_layout(layout)
        elif isinstance(layout, LayoutTemplate):
            resolved_layout = layout

        is_payload = isinstance(content, ResultPayload)

        paths: list[Path] = []
        for fmt in unique_formats:
            publisher = self.get(fmt)
            if not publisher:
                logger.warning("Publisher '%s' not found, skipping", fmt)
                continue

            dest = output_path / f"{filename}{publisher.output_extension}"
            start = time.monotonic()
            logger.info(
                "output.publish.start",
                extra={"publisher_id": fmt, "format": fmt, "output_path": str(dest)},
            )

            try:
                if is_payload:
                    result = await publisher.publish_payload(
                        content,  # type: ignore[arg-type]
                        dest,
                        layout=resolved_layout,
                        config=config,
                    )
                else:
                    result = await publisher.publish(
                        str(content),
                        dest,
                        metadata,
                    )
                paths.append(result)
                elapsed = time.monotonic() - start
                logger.info(
                    "output.publish.complete",
                    extra={
                        "publisher_id": fmt,
                        "format": fmt,
                        "output_path": str(result),
                        "duration_s": round(elapsed, 3),
                    },
                )
            except Exception:
                elapsed = time.monotonic() - start
                logger.exception(
                    "output.publish.error",
                    extra={
                        "publisher_id": fmt,
                        "format": fmt,
                        "output_path": str(dest),
                        "duration_s": round(elapsed, 3),
                    },
                )

        return paths
