"""JSON Publisher — serializes ResultPayload to a .json file.

This is a zero-dependency publisher that writes the full payload as
pretty-printed JSON, preserving all fields for programmatic consumption.
"""

import json
from pathlib import Path
from typing import Any

import structlog

from hiveflow.core.layout import LayoutTemplate
from hiveflow.core.result_payload import ResultPayload
from hiveflow.plugins.publishers import PublisherPlugin

logger = structlog.get_logger()


class JSONPublisher(PublisherPlugin):
    """Publisher that serializes ResultPayload to JSON."""

    @property
    def plugin_id(self) -> str:
        return "json"

    @property
    def description(self) -> str:
        return "JSON output publisher"

    @property
    def output_extension(self) -> str:
        return ".json"

    async def publish(
        self,
        content: str,
        output_path: str | Path,
        metadata: dict[str, Any] | None = None,
    ) -> Path:
        """Write content as JSON file (legacy API).

        Wraps the string content and metadata into a simple JSON object.
        """
        path = Path(output_path)
        if not path.suffix:
            path = path.with_suffix(".json")
        path.parent.mkdir(parents=True, exist_ok=True)

        data = {"content": content}
        if metadata:
            data["metadata"] = metadata

        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        logger.info(
            "output.publish.complete",
            extra={"publisher_id": "json", "format": "json", "output_path": str(path)},
        )
        return path

    async def publish_payload(
        self,
        payload: ResultPayload,
        output_path: str | Path,
        layout: LayoutTemplate | None = None,  # noqa: ARG002
        config: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> Path:
        """Serialize the full ResultPayload to a .json file.

        Args:
            payload: Structured workflow result.
            output_path: Destination file path.
            layout: Ignored for JSON (all fields are serialized regardless).
            config: Optional config (unused).

        Returns:
            Path to the created .json file.
        """
        path = Path(output_path)
        if not path.suffix:
            path = path.with_suffix(".json")
        path.parent.mkdir(parents=True, exist_ok=True)

        data = payload.to_dict()
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        logger.info(
            "output.publish.complete",
            extra={"publisher_id": "json", "format": "json", "output_path": str(path)},
        )
        return path
