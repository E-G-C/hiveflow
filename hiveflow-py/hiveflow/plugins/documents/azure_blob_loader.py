"""Azure Blob Storage document loader."""

from pathlib import PurePosixPath
from urllib.parse import urlparse

import structlog

from hiveflow.plugins.documents import Document

logger = structlog.get_logger(__name__)

# Extension-to-format mapping for common document types
_EXT_FORMAT_MAP: dict[str, str] = {
    ".txt": "text",
    ".log": "text",
    ".csv": "csv",
    ".tsv": "tsv",
    ".json": "json",
    ".jsonl": "jsonl",
    ".xml": "xml",
    ".html": "html",
    ".htm": "html",
    ".md": "markdown",
    ".markdown": "markdown",
    ".pdf": "pdf",
    ".docx": "docx",
    ".pptx": "pptx",
    ".xlsx": "xlsx",
}


def _parse_blob_url(url: str) -> tuple[str, str, str]:
    """Parse an Azure blob URL into (account, container, blob_path).

    Expected format:
        https://<account>.blob.core.windows.net/<container>/<blob_path>

    Raises:
        ValueError: If the URL does not match the expected format.
    """
    parsed = urlparse(url)
    host = parsed.hostname or ""

    if not host.endswith(".blob.core.windows.net"):
        raise ValueError(
            f"Invalid Azure blob URL: expected host '<account>.blob.core.windows.net', got '{host}'"
        )

    account = host.split(".")[0]
    # Strip leading '/' then split into container + blob path
    path_parts = parsed.path.lstrip("/").split("/", 1)
    if len(path_parts) < 2 or not path_parts[1]:
        raise ValueError(
            f"Invalid Azure blob URL: expected '/<container>/<blob_path>' in path, got '{parsed.path}'"
        )

    container = path_parts[0]
    blob_path = path_parts[1]
    return account, container, blob_path


def _detect_format(blob_path: str) -> str:
    """Detect document format from blob path extension."""
    ext = PurePosixPath(blob_path).suffix.lower()
    return _EXT_FORMAT_MAP.get(ext, ext.lstrip(".") or "unknown")


async def load_azure_blob(url: str, *, credential: object | None = None) -> Document:
    """Load a document from Azure Blob Storage.

    Supports three authentication methods (checked in order):
      1. SAS token embedded in the URL query string
      2. Explicit *credential* (e.g. ``DefaultAzureCredential()``)
      3. Connection-string style is NOT supported here; pass a credential instead.

    Args:
        url: Full Azure blob URL
            (``https://<account>.blob.core.windows.net/<container>/<blob>``).
        credential: Optional Azure credential object. When *None* and no SAS
            token is present in the URL, ``DefaultAzureCredential`` is used.

    Returns:
        A :class:`Document` with the blob content.

    Raises:
        ImportError: If ``azure-storage-blob`` or ``azure-identity`` is missing.
        ValueError: If the URL cannot be parsed.
    """
    try:
        from azure.storage.blob.aio import BlobClient
    except ImportError as exc:
        raise ImportError(
            "azure-storage-blob is required for Azure Blob Storage support. "
            "Install with: pip install azure-storage-blob"
        ) from exc

    account, container, blob_path = _parse_blob_url(url)
    fmt = _detect_format(blob_path)
    blob_name = PurePosixPath(blob_path).name

    logger.info(
        "loading_azure_blob",
        account=account,
        container=container,
        blob_path=blob_path,
        format=fmt,
    )

    parsed = urlparse(url)
    has_sas = bool(parsed.query)

    if has_sas:
        # SAS token is part of the URL; no extra credential needed
        client = BlobClient.from_blob_url(url)
    else:
        if credential is None:
            try:
                from azure.identity.aio import DefaultAzureCredential
            except ImportError as exc:
                raise ImportError(
                    "azure-identity is required when no SAS token is provided. "
                    "Install with: pip install azure-identity"
                ) from exc
            credential = DefaultAzureCredential()

        account_url = f"https://{account}.blob.core.windows.net"
        client = BlobClient(
            account_url=account_url,
            container_name=container,
            blob_name=blob_path,
            credential=credential,
        )

    async with client:
        downloader = await client.download_blob()
        data = await downloader.readall()

    content = data.decode("utf-8")

    logger.info(
        "azure_blob_loaded",
        blob_path=blob_path,
        size_bytes=len(data),
        format=fmt,
    )

    return Document(
        content=content,
        source=url,
        name=blob_name,
        format=fmt,
        size_bytes=len(data),
        metadata={
            "account": account,
            "container": container,
            "blob_path": blob_path,
        },
    )
