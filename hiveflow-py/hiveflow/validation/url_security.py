"""URL security validation -- SSRF protection.

Validates URLs before fetching to prevent Server-Side Request Forgery (SSRF)
attacks that could probe internal networks, cloud metadata endpoints, or
loopback services.
"""

import ipaddress
import socket
from urllib.parse import urlparse

# Cloud metadata endpoints commonly targeted in SSRF attacks
_METADATA_IPS = frozenset({"169.254.169.254", "fd00:ec2::254"})


class SSRFError(ValueError):
    """Raised when a URL targets a disallowed address."""


def validate_url(url: str) -> None:
    """Validate that a URL targets a public, non-internal address.

    Args:
        url: The URL to validate.

    Raises:
        SSRFError: If the URL targets a private, loopback, link-local,
            or cloud metadata address.
        ValueError: If the URL scheme is not http/https or has no hostname.
    """
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported URL scheme: {parsed.scheme!r}")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError(f"URL has no hostname: {url!r}")

    # Resolve hostname to IP addresses
    try:
        addr_infos = socket.getaddrinfo(hostname, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise SSRFError(f"Cannot resolve hostname: {hostname!r}") from exc

    for _family, _type, _proto, _canonname, sockaddr in addr_infos:
        ip_str = sockaddr[0]

        # Check cloud metadata endpoints
        if ip_str in _METADATA_IPS:
            raise SSRFError(f"URL resolves to cloud metadata endpoint: {ip_str}")

        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError:
            continue

        if addr.is_private:
            raise SSRFError(f"URL resolves to private address: {ip_str}")
        if addr.is_loopback:
            raise SSRFError(f"URL resolves to loopback address: {ip_str}")
        if addr.is_link_local:
            raise SSRFError(f"URL resolves to link-local address: {ip_str}")
        if addr.is_reserved:
            raise SSRFError(f"URL resolves to reserved address: {ip_str}")
