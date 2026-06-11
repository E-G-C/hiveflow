"""Tests for the layout template system."""

import tempfile
from pathlib import Path

import pytest

from hiveflow.core.layout import (
    LayoutSection,
    LayoutTemplate,
    list_layouts,
    load_layout,
)


class TestLayoutSection:

    def test_basic_construction(self) -> None:
        sec = LayoutSection(id="intro", source="content")
        assert sec.id == "intro"
        assert sec.required is False
        assert sec.heading is None

    def test_to_dict_minimal(self) -> None:
        sec = LayoutSection(id="x", source="y")
        d = sec.to_dict()
        assert d == {"id": "x", "source": "y", "required": False}

    def test_to_dict_with_heading(self) -> None:
        sec = LayoutSection(id="x", source="y", heading="Custom Heading")
        d = sec.to_dict()
        assert d["heading"] == "Custom Heading"


class TestLayoutTemplate:

    def test_basic_construction(self) -> None:
        t = LayoutTemplate(name="test")
        assert t.name == "test"
        assert t.sections == []

    def test_to_dict(self) -> None:
        t = LayoutTemplate(
            name="brief",
            description="A brief layout",
            sections=[
                LayoutSection(id="title", source="metadata.title", required=True),
                LayoutSection(id="content", source="content"),
            ],
        )
        d = t.to_dict()
        assert d["name"] == "brief"
        assert len(d["sections"]) == 2
        assert d["sections"][0]["required"] is True


class TestLoadLayout:

    def test_load_builtin_default(self) -> None:
        layout = load_layout("default")
        assert layout.name == "default"
        assert len(layout.sections) > 0

    def test_default_has_expected_sections(self) -> None:
        layout = load_layout("default")
        ids = [s.id for s in layout.sections]
        assert "title" in ids
        assert "content" in ids
        assert "references" in ids
        assert "appendix" in ids

    def test_default_title_is_required(self) -> None:
        layout = load_layout("default")
        title_sec = next(s for s in layout.sections if s.id == "title")
        assert title_sec.required is True

    def test_default_references_is_optional(self) -> None:
        layout = load_layout("default")
        refs_sec = next(s for s in layout.sections if s.id == "references")
        assert refs_sec.required is False

    def test_missing_layout_raises(self) -> None:
        with pytest.raises(FileNotFoundError, match="nonexistent"):
            load_layout("nonexistent")

    def test_error_lists_available_layouts(self) -> None:
        with pytest.raises(FileNotFoundError, match="default"):
            load_layout("nonexistent")

    def test_load_from_extra_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            layout_file = Path(tmpdir) / "custom.yaml"
            layout_file.write_text(
                "name: custom\n"
                "description: Custom test layout\n"
                "sections:\n"
                "  - id: body\n"
                "    source: content\n"
                "    required: true\n",
                encoding="utf-8",
            )
            layout = load_layout("custom", extra_dirs=[tmpdir])
            assert layout.name == "custom"
            assert len(layout.sections) == 1
            assert layout.sections[0].id == "body"

    def test_extra_dir_overrides_builtin(self) -> None:
        """An extra dir layout with the same name as a builtin takes precedence."""
        with tempfile.TemporaryDirectory() as tmpdir:
            layout_file = Path(tmpdir) / "default.yaml"
            layout_file.write_text(
                "name: default-override\n"
                "sections:\n"
                "  - id: only_section\n"
                "    source: content\n",
                encoding="utf-8",
            )
            layout = load_layout("default", extra_dirs=[tmpdir])
            assert layout.name == "default-override"
            assert len(layout.sections) == 1

    def test_yml_extension_supported(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            layout_file = Path(tmpdir) / "alt.yml"
            layout_file.write_text(
                "name: alt\nsections:\n  - id: a\n    source: content\n",
                encoding="utf-8",
            )
            layout = load_layout("alt", extra_dirs=[tmpdir])
            assert layout.name == "alt"


class TestListLayouts:

    def test_includes_default(self) -> None:
        names = list_layouts()
        assert "default" in names

    def test_returns_sorted(self) -> None:
        names = list_layouts()
        assert names == sorted(names)

    def test_includes_extra_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "bravo.yaml").write_text("name: bravo\n")
            (Path(tmpdir) / "alpha.yaml").write_text("name: alpha\n")
            names = list_layouts(extra_dirs=[tmpdir])
            assert "alpha" in names
            assert "bravo" in names
            assert "default" in names

    def test_deduplicates(self) -> None:
        names = list_layouts()
        assert len(names) == len(set(names))

    def test_nonexistent_extra_dir_ignored(self) -> None:
        names = list_layouts(extra_dirs=["/nonexistent/path"])
        assert "default" in names

    def test_section_ordering_preserved(self) -> None:
        layout = load_layout("default")
        ids = [s.id for s in layout.sections]
        # title should come before content
        assert ids.index("title") < ids.index("content")
        # content should come before references
        assert ids.index("content") < ids.index("references")


class TestLayoutApply:
    """Tests for LayoutTemplate.apply()."""

    def _make_payload(self, **kwargs):
        from hiveflow.core.result_payload import ResultPayload
        defaults = {"title": "Test Report", "content": "Body content"}
        defaults.update(kwargs)
        return ResultPayload(**defaults)

    def test_apply_default_layout(self) -> None:
        layout = load_layout("default")
        payload = self._make_payload()
        rendered = layout.apply(payload)
        # Should have at least title and content
        ids = [r.section_id for r in rendered]
        assert "title" in ids
        assert "content" in ids

    def test_optional_sections_omitted_when_empty(self) -> None:
        from hiveflow.core.layout import LayoutSection, LayoutTemplate
        layout = LayoutTemplate(
            name="test",
            sections=[
                LayoutSection(id="title", source="title", required=True),
                LayoutSection(id="refs", source="references", required=False),
            ],
        )
        payload = self._make_payload(references=[])
        rendered = layout.apply(payload)
        ids = [r.section_id for r in rendered]
        assert "title" in ids
        assert "refs" not in ids  # empty optional → omitted

    def test_required_sections_kept_when_empty(self) -> None:
        from hiveflow.core.layout import LayoutSection, LayoutTemplate
        layout = LayoutTemplate(
            name="test",
            sections=[
                LayoutSection(id="missing", source="sections.nonexistent", required=True, heading="Missing"),
            ],
        )
        payload = self._make_payload()
        rendered = layout.apply(payload)
        assert len(rendered) == 1
        assert rendered[0].section_id == "missing"

    def test_custom_layout_reorders_sections(self) -> None:
        from hiveflow.core.layout import LayoutSection, LayoutTemplate
        layout = LayoutTemplate(
            name="reversed",
            sections=[
                LayoutSection(id="content", source="content", required=True),
                LayoutSection(id="title", source="title", required=True),
            ],
        )
        payload = self._make_payload()
        rendered = layout.apply(payload)
        assert rendered[0].section_id == "content"
        assert rendered[1].section_id == "title"

    def test_heading_override(self) -> None:
        from hiveflow.core.layout import LayoutSection, LayoutTemplate
        layout = LayoutTemplate(
            name="test",
            sections=[
                LayoutSection(id="content", source="content", heading="Main Body"),
            ],
        )
        payload = self._make_payload()
        rendered = layout.apply(payload)
        assert rendered[0].heading == "Main Body"

    def test_auto_source_returns_empty(self) -> None:
        from hiveflow.core.layout import LayoutSection, LayoutTemplate
        layout = LayoutTemplate(
            name="test",
            sections=[
                LayoutSection(id="toc", source="auto", required=False),
            ],
        )
        payload = self._make_payload()
        rendered = layout.apply(payload)
        # auto source returns empty, optional → omitted
        assert len(rendered) == 0

    def test_metadata_dotpath_resolution(self) -> None:
        from hiveflow.core.layout import LayoutSection, LayoutTemplate
        layout = LayoutTemplate(
            name="test",
            sections=[
                LayoutSection(id="date", source="metadata.date", required=True),
            ],
        )
        payload = self._make_payload(metadata={"date": "2026-02-20"})
        rendered = layout.apply(payload)
        assert rendered[0].content == "2026-02-20"

    def test_references_list_detected(self) -> None:
        from hiveflow.core.citations import Citation
        from hiveflow.core.layout import LayoutSection, LayoutTemplate
        layout = LayoutTemplate(
            name="test",
            sections=[
                LayoutSection(id="refs", source="references", required=False),
            ],
        )
        payload = self._make_payload(
            references=[Citation(url="https://x.com", title="X")],
        )
        rendered = layout.apply(payload)
        assert len(rendered) == 1  # non-empty list → included
