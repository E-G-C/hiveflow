"""DOCX Publisher — converts ResultPayload to Word (.docx) via pypandoc.

Requires pypandoc (wraps pandoc binary) for Markdown → DOCX conversion.
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


class DOCXPublisher(PublisherPlugin):
    """Publisher that converts Markdown content to DOCX via pypandoc."""

    @property
    def plugin_id(self) -> str:
        return "docx"

    @property
    def description(self) -> str:
        return "DOCX output publisher (via pandoc)"

    @property
    def output_extension(self) -> str:
        return ".docx"

    async def publish(
        self,
        content: str,
        output_path: str | Path,
        metadata: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> Path:
        """Convert markdown content to DOCX (legacy API)."""
        path = Path(output_path)
        if not path.suffix:
            path = path.with_suffix(".docx")
        path.parent.mkdir(parents=True, exist_ok=True)

        await self._convert_to_docx(content, path)
        return path

    async def publish_payload(
        self,
        payload: ResultPayload,
        output_path: str | Path,
        layout: LayoutTemplate | None = None,
        config: dict[str, Any] | None = None,
    ) -> Path:
        """Convert a ResultPayload to a DOCX file with proper formatting."""
        path = Path(output_path)
        if not path.suffix:
            path = path.with_suffix(".docx")
        path.parent.mkdir(parents=True, exist_ok=True)

        md = self.assemble_markdown(payload, layout)
        extra_args = []
        if config and config.get("reference_doc"):
            extra_args.extend(["--reference-doc", config["reference_doc"]])

        await self._convert_to_docx(md, path, extra_args=extra_args)
        logger.info(
            "output.publish.complete",
            extra={"publisher_id": "docx", "format": "docx", "output_path": str(path)},
        )
        return path

    @staticmethod
    async def _convert_to_docx(
        content: str,
        output_path: Path,
        extra_args: list[str] | None = None,
    ) -> None:
        """Run pypandoc conversion in a thread."""
        import pypandoc  # type: ignore[import-untyped]

        def _convert() -> None:
            pypandoc.convert_text(
                content,
                "docx",
                format="md",
                outputfile=str(output_path),
                extra_args=extra_args or [],
            )

        await asyncio.to_thread(_convert)
