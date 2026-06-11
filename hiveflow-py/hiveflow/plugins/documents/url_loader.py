"""URL document loader using httpx."""

from urllib.parse import urlparse

import httpx
import structlog

from hiveflow.plugins.documents import Document

logger = structlog.get_logger(__name__)

# Content types we can handle as text
_SUPPORTED_CONTENT_TYPES = {"text/plain", "text/html", "text/csv", "text/xml", "application/json"}


def _is_supported_content_type(content_type: str) -> bool:
    """Check whether the content-type header indicates a text-based format."""
    # Strip parameters like charset
    media_type = content_type.split(";")[0].strip().lower()
    return media_type in _SUPPORTED_CONTENT_TYPES or media_type.startswith("text/")


async def load_url(url: str, *, timeout: float = 30.0) -> Document:
    """Fetch a URL and return its content as a :class:`Document`.

    Args:
        url: The URL to fetch.
        timeout: Request timeout in seconds.

    Returns:
        A :class:`Document` containing the response text.

    Raises:
        httpx.HTTPStatusError: On non-2xx responses.
        ValueError: If the content type is not supported.
    """
    logger.info("loading_url", url=url)

    from hiveflow.validation.url_security import validate_url

    validate_url(url)

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()

    content_type = response.headers.get("content-type", "text/plain")
    if not _is_supported_content_type(content_type):
        raise ValueError(
            f"Unsupported content type '{content_type}' from {url}. "
            f"Only text-based content types are supported."
        )

    content = response.text
    parsed = urlparse(url)
    name = parsed.path.rsplit("/", 1)[-1] or parsed.hostname or url

    media_type = content_type.split(";")[0].strip().lower()
    fmt = media_type.split("/")[-1] if "/" in media_type else "text"

    logger.info(
        "url_loaded",
        url=url,
        content_type=content_type,
        size_bytes=len(response.content),
    )

    return Document(
        content=content,
        source=url,
        name=name,
        format=fmt,
        size_bytes=len(response.content),
        metadata={
            "url": url,
            "content_type": content_type,
            "status_code": response.status_code,
        },
    )
