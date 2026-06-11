"""Tests for URL document loader."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from hiveflow.plugins.documents import Document
from hiveflow.plugins.documents.url_loader import load_url


@pytest.fixture(autouse=True)
def _bypass_url_validation():
    """Bypass SSRF DNS resolution for fake test hostnames."""
    with patch("hiveflow.validation.url_security.validate_url"):
        yield


def _make_response(
    text: str = "",
    content_type: str = "text/html",
    status_code: int = 200,
    url: str = "https://example.com/page.html",
) -> httpx.Response:
    """Build a minimal httpx.Response for testing."""
    response = httpx.Response(
        status_code=status_code,
        headers={"content-type": content_type},
        text=text,
        request=httpx.Request("GET", url),
    )
    return response


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------
class TestLoadUrl:
    """Tests for load_url."""

    async def test_load_html(self) -> None:
        """HTML content is returned as a Document."""
        html = "<html><body><p>Hello</p></body></html>"
        resp = _make_response(text=html, content_type="text/html; charset=utf-8")

        with patch("hiveflow.plugins.documents.url_loader.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = resp
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            doc = await load_url("https://example.com/page.html")

        assert isinstance(doc, Document)
        assert doc.content == html
        assert doc.format == "html"

    async def test_load_plain_text(self) -> None:
        """Plain text content is loaded correctly."""
        body = "Just some plain text."
        resp = _make_response(text=body, content_type="text/plain")

        with patch("hiveflow.plugins.documents.url_loader.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = resp
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            doc = await load_url("https://example.com/readme.txt")

        assert doc.content == body
        assert doc.format == "plain"

    async def test_source_metadata(self) -> None:
        """Source metadata is populated correctly."""
        resp = _make_response(
            text="data",
            content_type="text/csv",
            url="https://data.example.com/report.csv",
        )

        with patch("hiveflow.plugins.documents.url_loader.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = resp
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            doc = await load_url("https://data.example.com/report.csv")

        assert doc.source == "https://data.example.com/report.csv"
        assert doc.name == "report.csv"
        assert doc.metadata["url"] == "https://data.example.com/report.csv"
        assert doc.metadata["content_type"] == "text/csv"
        assert doc.metadata["status_code"] == 200

    async def test_json_content_type(self) -> None:
        """application/json is accepted as a supported content type."""
        resp = _make_response(text='{"key": "value"}', content_type="application/json")

        with patch("hiveflow.plugins.documents.url_loader.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = resp
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            doc = await load_url("https://api.example.com/data.json")

        assert doc.content == '{"key": "value"}'
        assert doc.format == "json"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
class TestLoadUrlErrors:
    """Tests for error handling in load_url."""

    async def test_unsupported_content_type(self) -> None:
        """Unsupported content type raises ValueError."""
        resp = _make_response(text="", content_type="application/octet-stream")

        with patch("hiveflow.plugins.documents.url_loader.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = resp
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(ValueError, match="Unsupported content type"):
                await load_url("https://example.com/file.bin")

    async def test_http_error_propagates(self) -> None:
        """HTTP errors from the server are propagated."""
        resp = _make_response(text="Not Found", status_code=404)

        with patch("hiveflow.plugins.documents.url_loader.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.return_value = resp
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            with pytest.raises(httpx.HTTPStatusError):
                await load_url("https://example.com/missing")
