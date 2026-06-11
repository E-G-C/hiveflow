"""PDF Publisher — converts ResultPayload to PDF via pypandoc (pandoc + LaTeX).

Requires pypandoc and a LaTeX engine (e.g. xelatex, pdflatex) for PDF output.
Part of the ``hiveflow[publishers]`` optional extra.
"""

import asyncio
from pathlib import Path
from typing import Any

import structlog

from hiveflow.core.layout import LayoutTemplate
from hiveflow.core.result_payload import ResultPayload
from hiveflow.plugins.publishers import PublisherPlugin

logger = structlog.get_logger()


class PDFPublisher(PublisherPlugin):
    """Publisher that converts Markdown content to PDF via pypandoc."""

    @property
    def plugin_id(self) -> str:
        return "pdf"

    @property
    def description(self) -> str:
        return "PDF output publisher (via pandoc + LaTeX)"

    @property
    def output_extension(self) -> str:
        return ".pdf"

    async def publish(
        self,
        content: str,
        output_path: str | Path,
        metadata: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> Path:
        """Convert markdown content to PDF (legacy API)."""
        path = Path(output_path)
        if not path.suffix:
            path = path.with_suffix(".pdf")
        path.parent.mkdir(parents=True, exist_ok=True)

        await self._convert_to_pdf(content, path)
        return path

    async def publish_payload(
        self,
        payload: ResultPayload,
        output_path: str | Path,
        layout: LayoutTemplate | None = None,
        config: dict[str, Any] | None = None,
    ) -> Path:
        """Convert a ResultPayload to a styled PDF.

        Assembles Markdown from the payload, then converts via pandoc.
        Accepts an optional LaTeX template via config["template"].
        """
        path = Path(output_path)
        if not path.suffix:
            path = path.with_suffix(".pdf")
        path.parent.mkdir(parents=True, exist_ok=True)

        md = self.assemble_markdown(payload, layout)
        extra_args = []
        if config and config.get("template"):
            extra_args.extend(["--template", config["template"]])

        await self._convert_to_pdf(md, path, extra_args=extra_args)
        logger.info(
            "output.publish.complete",
            extra={"publisher_id": "pdf", "format": "pdf", "output_path": str(path)},
        )
        return path

    @staticmethod
    async def _convert_to_pdf(
        content: str,
        output_path: Path,
        extra_args: list[str] | None = None,
    ) -> None:
        """Run pypandoc conversion in a thread."""
        import pypandoc  # type: ignore[import-untyped]

        def _convert() -> None:
            pypandoc.convert_text(
                content,
                "pdf",
                format="md",
                outputfile=str(output_path),
                extra_args=extra_args or [],
            )

        await asyncio.to_thread(_convert)
