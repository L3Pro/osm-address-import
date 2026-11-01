"""Conservative target checks for *future* isolated-sandbox experiments.

This module does not issue HTTP requests, authenticate, or perform an upload.
A URL check alone is not sufficient to prove server isolation.
"""
from urllib.parse import urlsplit


class UnsafeTargetError(ValueError):
    """Target may not be used for this repository's local test harness."""


def require_local_sandbox_url(url: str) -> str:
    """Accept an explicit HTTP loopback address with a port; reject all others."""
    if not isinstance(url, str) or not url or url.strip() != url:
        raise UnsafeTargetError("A single explicit local URL is required")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise UnsafeTargetError("Malformed URL") from exc
    if (
        parts.scheme != "http"
        or parts.hostname not in ("localhost", "127.0.0.1", "::1")
        or not port
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
    ):
        raise UnsafeTargetError("Only an unauthenticated, explicit HTTP loopback target with a port is allowed")
    return url
