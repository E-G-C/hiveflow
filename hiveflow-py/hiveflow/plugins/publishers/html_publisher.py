"""HTML Publisher — converts ResultPayload to styled HTML via pypandoc + Jinja2.

Converts Markdown to HTML using pypandoc, then wraps it in a Jinja2 template
for styling and layout. Part of the ``hiveflow[publishers]`` optional extra.
"""

import asyncio
from importlib import resources as importlib_resources
from pathlib import Path
from typing import Any

import structlog

from hiveflow.core.layout import LayoutTemplate
from hiveflow.core.result_payload import ResultPayload
from hiveflow.plugins.publishers import PublisherPlugin

logger = structlog.get_logger()

_DEFAULT_TEMPLATE_PACKAGE = "hiveflow.templates.html"


class HTMLPublisher(PublisherPlugin):
    """Publisher that converts Markdown content to styled HTML."""

    @property
    def plugin_id(self) -> str:
        return "html"

    @property
    def description(self) -> str:
        return "HTML output publisher (via pandoc + Jinja2)"

    @property
    def output_extension(self) -> str:
        return ".html"

    async def publish(
        self,
        content: str,
        output_path: str | Path,
        metadata: dict[str, Any] | None = None,
    ) -> Path:
        """Convert markdown content to HTML (legacy API)."""
        path = Path(output_path)
        if not path.suffix:
            path = path.with_suffix(".html")
        path.parent.mkdir(parents=True, exist_ok=True)

        html_body = await self._md_to_html(content)
        title = (metadata or {}).get("title", "Report")
        full_html = self._wrap_in_template(title, html_body, metadata or {})
        path.write_text(full_html, encoding="utf-8")
        logger.info(
            "output.publish.complete",
            extra={"publisher_id": "html", "format": "html", "output_path": str(path)},
        )
        return path

    async def publish_payload(
        self,
        payload: ResultPayload,
        output_path: str | Path,
        layout: LayoutTemplate | None = None,
        config: dict[str, Any] | None = None,
    ) -> Path:
        """Convert a ResultPayload to a styled HTML document."""
        path = Path(output_path)
        if not path.suffix:
            path = path.with_suffix(".html")
        path.parent.mkdir(parents=True, exist_ok=True)

        md = self.assemble_markdown(payload, layout)
        html_body = await self._md_to_html(md)

        template_path = (config or {}).get("template") if config else None
        full_html = self._wrap_in_template(
            payload.title,
            html_body,
            payload.metadata,
            template_path=template_path,
        )
        path.write_text(full_html, encoding="utf-8")
        logger.info(
            "output.publish.complete",
            extra={"publisher_id": "html", "format": "html", "output_path": str(path)},
        )
        return path

    @staticmethod
    async def _md_to_html(md_content: str) -> str:
        """Convert Markdown to HTML via pypandoc in a thread."""
        import pypandoc  # type: ignore[import-untyped]

        def _convert() -> str:
            return pypandoc.convert_text(md_content, "html", format="md")  # type: ignore[no-any-return]

        return await asyncio.to_thread(_convert)

    @staticmethod
    def _wrap_in_template(
        title: str,
        body_html: str,
        metadata: dict[str, Any],
        *,
        template_path: str | None = None,
    ) -> str:
        """Wrap HTML body in a Jinja2 template."""
        import jinja2

        template_str: str | None = None

        # Try custom template path
        if template_path:
            p = Path(template_path)
            if p.is_file():
                template_str = p.read_text(encoding="utf-8")

        # Try built-in template
        if template_str is None:
            try:
                files = importlib_resources.files(_DEFAULT_TEMPLATE_PACKAGE)
                default_file = files.joinpath("default.html")
                template_str = default_file.read_text(encoding="utf-8")
            except (ModuleNotFoundError, FileNotFoundError, TypeError):
                pass

        # Final fallback: minimal HTML wrapper
        if template_str is None:
            template_str = (
                "<!DOCTYPE html>\n<html>\n<head>"
                '<meta charset="utf-8"><title>{{ title }}</title></head>\n'
                "<body>{{ body }}</body>\n</html>"
            )

        env = jinja2.Environment(autoescape=True)
        template = env.from_string(template_str)
        # body is pre-rendered HTML from pypandoc — mark safe to prevent
        # double-escaping while title/metadata remain auto-escaped.
        from markupsafe import Markup

        return template.render(
            title=title,
            body=Markup(body_html),
            metadata=metadata,
        )
