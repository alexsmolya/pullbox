"""Helpers for stable, cache-busted cover URLs."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime


def _series_cover_version_key(series: object) -> str:
    """Build a stable key that changes when the series identity/cover changes."""
    updated_at = getattr(series, "updated_at", None)
    updated_at_key = ""
    if isinstance(updated_at, datetime):
        normalized = updated_at if updated_at.tzinfo else updated_at.replace(tzinfo=UTC)
        updated_at_key = normalized.astimezone(UTC).isoformat(timespec="microseconds")

    return "|".join(
        (
            str(getattr(series, "id", "") or ""),
            str(getattr(series, "comicvine_id", "") or ""),
            str(getattr(series, "title", "") or ""),
            str(getattr(series, "cover_url", "") or ""),
            updated_at_key,
        )
    )


def build_series_cover_url(series: object) -> str | None:
    """Return a versioned series-cover URL suitable for browser caches."""
    series_id = getattr(series, "id", None)
    if not series_id:
        return None

    cover_path = getattr(series, "cover_path", None)
    cover_url = getattr(series, "cover_url", None)
    if not (cover_path or cover_url):
        return None

    if cover_path and not str(cover_path).startswith("/api/v1/series/"):
        return str(cover_path)

    version = hashlib.sha256(_series_cover_version_key(series).encode("utf-8")).hexdigest()[:12]
    return f"/api/v1/series/{series_id}/cover?v={version}"
