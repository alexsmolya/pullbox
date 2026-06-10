"""Update check service — checks GitHub releases for newer versions.

Queries the GitHub Releases API to compare the running version against
the latest published release. Results are cached to avoid excessive API
calls (GitHub rate limit: 60 req/hr unauthenticated).

Usage:
    service = UpdateCheckService()
    result = await service.check_for_update()
    if result and result.update_available:
        logger.info("update_available", version=result.latest_version)
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx
import structlog

import pullbox

logger = structlog.get_logger(__name__)

GITHUB_RELEASES_URL = "https://api.github.com/repos/pullboxapp/pullbox/releases/latest"
_REQUEST_TIMEOUT = 10.0

_VERSION_RE = re.compile(r"^v?(\d+\.\d+\.\d+)")


def compare_versions(current: str, latest: str) -> bool:
    """Return True if latest is newer than current.

    Strips 'v' prefix and pre-release suffixes (-dev, -rc1, etc.)
    for comparison. A pre-release current version is considered
    older than the same base version without suffix.
    """

    def _parse(v: str) -> tuple[tuple[int, ...], bool]:
        v = v.lstrip("v")
        match = _VERSION_RE.match(v)
        if not match:
            return (0, 0, 0), False
        base = tuple(int(x) for x in match.group(1).split("."))
        is_prerelease = "-" in v
        return base, is_prerelease

    try:
        cur_base, cur_pre = _parse(current)
        lat_base, lat_pre = _parse(latest)
    except (ValueError, AttributeError):
        return False

    if cur_base == (0, 0, 0) or lat_base == (0, 0, 0):
        return False

    if lat_base > cur_base:
        return True
    return lat_base == cur_base and cur_pre and not lat_pre


@dataclass
class UpdateCheckResult:
    """Result of an update check."""

    current_version: str
    latest_version: str
    update_available: bool
    checked_at: datetime
    release_url: str | None = None
    release_notes: str | None = None
    release_date: str | None = None
    error: str | None = None


class UpdateCheckService:
    """Checks GitHub releases for newer versions with caching."""

    def __init__(self, cache_ttl_hours: int = 24) -> None:
        self._cache_ttl = timedelta(hours=cache_ttl_hours)
        self._cached_result: UpdateCheckResult | None = None
        self._last_check: datetime | None = None
        self._check_lock = asyncio.Lock()

    def get_cached(self) -> UpdateCheckResult | None:
        """Return the last cached result, or None if never checked."""
        return self._cached_result

    async def check_for_update(self, *, force: bool = False) -> UpdateCheckResult | None:
        """Check for a newer version on GitHub.

        Returns cached result if within TTL unless force=True.
        Returns None if the check fails (network error, etc.).
        """
        if not force and self._is_cache_valid():
            return self._cached_result
        async with self._check_lock:
            if not force and self._is_cache_valid():
                return self._cached_result

            try:
                release_data = await self._fetch_latest_release()
            except Exception as exc:
                logger.warning(
                    "update_check_failed",
                    error=str(exc),
                )
                return None

            current = pullbox.__version__

            if release_data is None:
                # No releases published yet (404) — treat as up to date
                result = UpdateCheckResult(
                    current_version=current,
                    latest_version=current,
                    update_available=False,
                    checked_at=datetime.now(UTC),
                )
                self._cached_result = result
                self._last_check = datetime.now(UTC)
                logger.debug("update_check_no_releases", version=current)
                return result

            tag = str(release_data.get("tag_name", "")).lstrip("v")

            result = UpdateCheckResult(
                current_version=current,
                latest_version=tag,
                update_available=compare_versions(current, tag),
                checked_at=datetime.now(UTC),
                release_url=release_data.get("html_url"),
                release_notes=release_data.get("body"),
                release_date=release_data.get("published_at"),
            )

            self._cached_result = result
            self._last_check = datetime.now(UTC)

            logger.debug(
                "update_check_completed",
                current=current,
                latest=tag,
                update_available=result.update_available,
            )

            return result

    def _is_cache_valid(self) -> bool:
        """Return True if cached result exists and hasn't expired."""
        if self._cached_result is None or self._last_check is None:
            return False
        return datetime.now(UTC) - self._last_check < self._cache_ttl

    async def _fetch_latest_release(self) -> dict[str, Any] | None:
        """Fetch the latest release from GitHub API."""
        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            resp = await client.get(
                GITHUB_RELEASES_URL,
                headers={
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": f"Pullbox/{pullbox.__version__}",
                },
            )
            if resp.status_code == 404:
                # No releases published yet
                return None
            resp.raise_for_status()
            payload = resp.json()
            if not isinstance(payload, dict):
                return None
            return cast("dict[str, Any]", payload)
