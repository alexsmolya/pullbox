"""Validation helpers for operator-configured service URLs."""

from __future__ import annotations

from urllib.parse import urlparse, urlunparse

_ALLOWED_PEER_SCHEMES = frozenset({"http", "https"})


def normalize_peer_base_url(
    value: str,
    *,
    reject_query_or_fragment: bool = False,
) -> str:
    """Normalize and validate an HTTP(S) peer/service base URL."""
    raw = value.strip()
    if any(char.isspace() for char in raw):
        raise ValueError("URL must not contain whitespace.")

    parsed = urlparse(raw)

    if parsed.scheme.lower() not in _ALLOWED_PEER_SCHEMES:
        raise ValueError("URL must use http or https.")
    if not parsed.netloc or not parsed.hostname:
        raise ValueError("URL must include a host.")
    if parsed.username or parsed.password:
        raise ValueError("URL must not include embedded credentials.")
    if reject_query_or_fragment and (parsed.params or parsed.query or parsed.fragment):
        raise ValueError("URL must not include a query or fragment.")

    normalized_path = parsed.path.rstrip("/")
    normalized = parsed._replace(scheme=parsed.scheme.lower(), path=normalized_path)
    return urlunparse(normalized)
