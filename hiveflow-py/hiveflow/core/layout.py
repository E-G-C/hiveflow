"""Layout Template System — document structure definitions for publishers.

Provides YAML-based layout templates that control which sections appear in
published output, in what order, and whether they are required or optional.
"""

from dataclasses import dataclass, field
from importlib import resources as importlib_resources
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()

# Sentinel for the built-in layouts bundled with the package.
_BUILTIN_LAYOUTS_PACKAGE = "hiveflow.templates.layouts"


@dataclass(frozen=True)
class LayoutSection:
    """A section definition within a LayoutTemplate.

    Attributes:
        id: Section identifier (must map to a ResultPayload field or section_id).
        source: Dot-path to the payload field (e.g. "content", "metadata.title", "auto").
        required: If True and content is empty, a warning is logged.
            If False and content is empty, the section is omitted.
        heading: Override heading text.  ``None`` means use the source's own title.
    """

    id: str
    source: str
    required: bool = False
    heading: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dictionary."""
        result: dict[str, Any] = {
            "id": self.id,
            "source": self.source,
            "required": self.required,
        }
        if self.heading is not None:
            result["heading"] = self.heading
        return result


@dataclass(frozen=True)
class RenderedSection:
    """A section rendered from a ResultPayload using a LayoutTemplate.

    Attributes:
        section_id: The layout section identifier.
        heading: The heading text to display (may be None for title/date).
        content: The rendered content for this section.
    """

    section_id: str
    heading: str | None
    content: str


@dataclass(frozen=True)
class LayoutTemplate:
    """Defines the document structure for published output.

    Attributes:
        name: Template identifier (e.g. "default", "executive-brief").
        description: Human-readable description.
        sections: Ordered list of section definitions.
    """

    name: str
    description: str = ""
    sections: list[LayoutSection] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "sections": [s.to_dict() for s in self.sections],
        }

    def apply(self, payload: Any) -> list[RenderedSection]:
        """Apply this layout to a ResultPayload, producing ordered sections.

        Walks the layout sections in order. For each section, resolves the
        content from the payload using the ``source`` dot-path. Optional
        sections with no content are omitted; required sections with no
        content emit a warning.

        Args:
            payload: A ResultPayload (or compatible object).

        Returns:
            Ordered list of RenderedSection instances.
        """
        rendered: list[RenderedSection] = []

        for layout_sec in self.sections:
            content = self._resolve_source(layout_sec, payload)

            if not content:
                if layout_sec.required:
                    logger.warning(
                        "Required layout section '%s' has no content",
                        layout_sec.id,
                    )
                # Skip optional sections with no content
                if not layout_sec.required:
                    continue

            heading = layout_sec.heading
            rendered.append(
                RenderedSection(
                    section_id=layout_sec.id,
                    heading=heading,
                    content=content or "",
                )
            )

        return rendered

    @staticmethod
    def _resolve_source(layout_sec: "LayoutSection", payload: Any) -> str:
        """Resolve a layout section's source to content from the payload."""
        source = layout_sec.source

        # Special sources
        if source == "auto":
            return ""  # Auto-generated (e.g. TOC) — handled by publisher

        # Dot-path resolution: "metadata.title" → payload.metadata["title"]
        parts = source.split(".")
        obj: Any = payload

        for part in parts:
            if isinstance(obj, dict):
                obj = obj.get(part, "")
            elif hasattr(obj, part):
                obj = getattr(obj, part, "")
            else:
                return ""

        # Handle special types
        if isinstance(obj, str):
            return obj
        if isinstance(obj, list):
            # Lists of sections, references, actions — return non-empty flag
            return str(bool(obj)) if obj else ""
        if obj is None:
            return ""
        return str(obj)


# ---------------------------------------------------------------------------
# Loading helpers
# ---------------------------------------------------------------------------


def _parse_layout_yaml(raw: dict[str, Any]) -> LayoutTemplate:
    """Parse a raw YAML dictionary into a LayoutTemplate."""
    sections: list[LayoutSection] = []
    for sec_data in raw.get("sections", []):
        sections.append(
            LayoutSection(
                id=sec_data["id"],
                source=sec_data["source"],
                required=sec_data.get("required", False),
                heading=sec_data.get("heading"),
            )
        )
    return LayoutTemplate(
        name=raw.get("name", "unknown"),
        description=raw.get("description", ""),
        sections=sections,
    )


def _load_yaml(text: str) -> dict[str, Any]:
    """Load YAML from a string, using PyYAML if available, else a minimal parser."""
    try:
        import yaml  # type: ignore[import-untyped]

        return yaml.safe_load(text) or {}  # type: ignore[no-any-return]
    except ImportError:
        pass
    # Minimal fallback: only supports the flat structure used by layout templates.
    # For production use, PyYAML should be installed.
    import json

    # Try JSON first (YAML is a superset of JSON)
    try:
        return json.loads(text)  # type: ignore[no-any-return]
    except json.JSONDecodeError:
        logger.warning(
            "PyYAML not installed and content is not JSON. "
            "Install pyyaml for full YAML layout template support."
        )
        return {}


def _builtin_layout_files() -> dict[str, str]:
    """Return a mapping of layout name → YAML content for built-in templates."""
    layouts: dict[str, str] = {}
    try:
        files = importlib_resources.files(_BUILTIN_LAYOUTS_PACKAGE)
        for item in files.iterdir():
            if hasattr(item, "name") and item.name.endswith((".yaml", ".yml")):
                name = Path(item.name).stem
                layouts[name] = item.read_text(encoding="utf-8")
    except (ModuleNotFoundError, FileNotFoundError, TypeError):
        logger.debug("No built-in layout templates found")
    return layouts


def load_layout(
    name: str,
    *,
    extra_dirs: list[str | Path] | None = None,
) -> LayoutTemplate:
    """Load a layout template by name.

    Resolution order:
    1. User-specified extra directories (searched first).
    2. Built-in layouts bundled with the hiveflow package.

    Args:
        name: Template name (e.g. "default", "executive-brief").
        extra_dirs: Optional additional directories to search for layouts.

    Returns:
        The resolved LayoutTemplate.

    Raises:
        FileNotFoundError: If the layout name cannot be resolved.
    """
    # 1. Search extra directories
    for dir_path in extra_dirs or []:
        p = Path(dir_path)
        for ext in (".yaml", ".yml"):
            candidate = p / f"{name}{ext}"
            if candidate.is_file():
                raw = _load_yaml(candidate.read_text(encoding="utf-8"))
                logger.debug("Loaded layout '%s' from %s", name, candidate)
                return _parse_layout_yaml(raw)

    # 2. Search built-in layouts
    builtins = _builtin_layout_files()
    if name in builtins:
        raw = _load_yaml(builtins[name])
        logger.debug("Loaded built-in layout '%s'", name)
        return _parse_layout_yaml(raw)

    # Not found
    available = list_layouts(extra_dirs=extra_dirs)
    raise FileNotFoundError(f"Layout template '{name}' not found. Available layouts: {available}")


def list_layouts(
    *,
    extra_dirs: list[str | Path] | None = None,
) -> list[str]:
    """List available layout template names.

    Args:
        extra_dirs: Optional additional directories to include.

    Returns:
        Sorted list of unique layout names.
    """
    names: set[str] = set()

    # Extra directories
    for dir_path in extra_dirs or []:
        p = Path(dir_path)
        if p.is_dir():
            for f in p.iterdir():
                if f.suffix in (".yaml", ".yml"):
                    names.add(f.stem)

    # Built-in
    names.update(_builtin_layout_files().keys())

    return sorted(names)
