"""Tests for Azure Blob Storage document loader."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hiveflow.plugins.documents import Document
from hiveflow.plugins.documents.azure_blob_loader import (
    _detect_format,
    _parse_blob_url,
    load_azure_blob,
)


# ---------------------------------------------------------------------------
# URL parsing
# ---------------------------------------------------------------------------
class TestParseBlobUrl:
    """Tests for Azure blob URL parsing."""

    def test_valid_url(self) -> None:
        account, container, blob = _parse_blob_url(
            "https://myaccount.blob.core.windows.net/mycontainer/path/to/file.txt"
        )
        assert account == "myaccount"
        assert container == "mycontainer"
        assert blob == "path/to/file.txt"

    def test_single_segment_blob(self) -> None:
        account, container, blob = _parse_blob_url(
            "https://acct.blob.core.windows.net/ctr/report.pdf"
        )
        assert account == "acct"
        assert container == "ctr"
        assert blob == "report.pdf"

    def test_invalid_host(self) -> None:
        with pytest.raises(ValueError, match="Invalid Azure blob URL"):
            _parse_blob_url("https://example.com/container/blob.txt")

    def test_missing_blob_path(self) -> None:
        with pytest.raises(ValueError, match="Invalid Azure blob URL"):
            _parse_blob_url("https://acct.blob.core.windows.net/container/")

    def test_missing_container(self) -> None:
        with pytest.raises(ValueError, match="Invalid Azure blob URL"):
            _parse_blob_url("https://acct.blob.core.windows.net/")


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------
class TestDetectFormat:
    """Tests for format detection from blob path extension."""

    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("docs/readme.md", "markdown"),
            ("data/report.pdf", "pdf"),
            ("data/sheet.xlsx", "xlsx"),
            ("logs/app.log", "text"),
            ("archive/notes.txt", "text"),
            ("data.json", "json"),
            ("page.html", "html"),
            ("file.csv", "csv"),
        ],
    )
    def test_known_extensions(self, path: str, expected: str) -> None:
        assert _detect_format(path) == expected

    def test_unknown_extension(self) -> None:
        result = _detect_format("file.parquet")
        assert result == "parquet"

    def test_no_extension(self) -> None:
        result = _detect_format("Makefile")
        assert result == "unknown"


# ---------------------------------------------------------------------------
# Content extraction (mocked Azure SDK)
# ---------------------------------------------------------------------------
class TestLoadAzureBlob:
    """Tests for load_azure_blob with mocked Azure SDK."""

    async def test_load_blob_content(self) -> None:
        """Blob content is returned as a Document."""
        blob_text = "Hello from Azure!"
        url = "https://acct.blob.core.windows.net/ctr/notes.txt"

        mock_downloader = AsyncMock()
        mock_downloader.readall.return_value = blob_text.encode("utf-8")

        mock_client = AsyncMock()
        mock_client.download_blob.return_value = mock_downloader
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mock_blob_client_cls = MagicMock(return_value=mock_client)

        with patch.dict(
            "sys.modules",
            {"azure": MagicMock(), "azure.storage": MagicMock(), "azure.storage.blob": MagicMock(), "azure.storage.blob.aio": MagicMock(BlobClient=mock_blob_client_cls)},
        ):
            doc = await load_azure_blob(url, credential=MagicMock())

        assert isinstance(doc, Document)
        assert doc.content == blob_text
        assert doc.source == url
        assert doc.name == "notes.txt"
        assert doc.format == "text"
        assert doc.metadata["container"] == "ctr"

    async def test_load_blob_with_sas_token(self) -> None:
        """SAS token in URL is used directly via from_blob_url."""
        blob_text = "SAS content"
        url = "https://acct.blob.core.windows.net/ctr/data.json?sv=2021-06-08&sig=abc"

        mock_downloader = AsyncMock()
        mock_downloader.readall.return_value = blob_text.encode("utf-8")

        mock_client = AsyncMock()
        mock_client.download_blob.return_value = mock_downloader
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mock_blob_client_cls = MagicMock()
        mock_blob_client_cls.from_blob_url = MagicMock(return_value=mock_client)

        with patch.dict(
            "sys.modules",
            {"azure": MagicMock(), "azure.storage": MagicMock(), "azure.storage.blob": MagicMock(), "azure.storage.blob.aio": MagicMock(BlobClient=mock_blob_client_cls)},
        ):
            doc = await load_azure_blob(url)

        mock_blob_client_cls.from_blob_url.assert_called_once_with(url)
        assert doc.content == blob_text
        assert doc.format == "json"

    async def test_missing_azure_package(self) -> None:
        """Clear ImportError when azure-storage-blob is not installed."""
        with patch.dict("sys.modules", {"azure": None, "azure.storage": None, "azure.storage.blob": None, "azure.storage.blob.aio": None}):
            with pytest.raises(ImportError, match="azure-storage-blob is required"):
                await load_azure_blob(
                    "https://acct.blob.core.windows.net/ctr/f.txt"
                )

    async def test_invalid_credentials_error(self) -> None:
        """Azure ClientAuthenticationError surfaces clearly."""
        url = "https://acct.blob.core.windows.net/ctr/secret.txt"

        mock_client = AsyncMock()
        mock_client.download_blob.side_effect = Exception(
            "ClientAuthenticationError: Invalid credentials"
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mock_blob_client_cls = MagicMock(return_value=mock_client)

        with patch.dict(
            "sys.modules",
            {"azure": MagicMock(), "azure.storage": MagicMock(), "azure.storage.blob": MagicMock(), "azure.storage.blob.aio": MagicMock(BlobClient=mock_blob_client_cls)},
        ):
            with pytest.raises(Exception, match="ClientAuthenticationError"):
                await load_azure_blob(url, credential=MagicMock())
