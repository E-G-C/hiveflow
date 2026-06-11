"""JSON document loader using stdlib json."""

import json as json_lib
from pathlib import Path

from hiveflow.plugins.documents import Document, DocumentLoaderPlugin


class JSONLoader(DocumentLoaderPlugin):
    """Loader for JSON files using stdlib json."""

    @property
    def plugin_id(self) -> str:
        return "json"

    @property
    def description(self) -> str:
        return "JSON file loader"

    @property
    def supported_extensions(self) -> list[str]:
        return [".json", ".jsonl"]

    async def load(self, file_path: str | Path) -> Document:
        path = Path(file_path)
        raw = path.read_text(encoding="utf-8")

        if path.suffix == ".jsonl":
            # JSONL: parse each line as separate JSON object
            lines = []
            for _i, line in enumerate(raw.strip().split("\n"), 1):
                line = line.strip()
                if line:
                    try:
                        obj = json_lib.loads(line)
                        lines.append(json_lib.dumps(obj, indent=2))
                    except json_lib.JSONDecodeError:
                        lines.append(line)
            content = "\n---\n".join(lines)
        else:
            # Standard JSON: pretty-print
            try:
                data = json_lib.loads(raw)
                content = json_lib.dumps(data, indent=2, ensure_ascii=False)
            except json_lib.JSONDecodeError:
                content = raw

        return Document(
            content=content,
            source=str(path),
            metadata={
                "filename": path.name,
                "size_bytes": path.stat().st_size,
            },
        )
