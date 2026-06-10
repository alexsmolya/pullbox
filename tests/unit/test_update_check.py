"""Tests for update check service.

Validates version comparison, GitHub API response parsing,
caching behavior, and error handling.

Run:
    pytest tests/unit/test_update_check.py -v
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from pullbox.services.update_check import (
    UpdateCheckResult,
    UpdateCheckService,
    compare_versions,
)


class TestVersionComparison:
    """compare_versions correctly detects newer, same, and older releases."""

    def test_newer_release_available(self) -> None:
        assert compare_versions("0.5.0-dev", "0.6.0") is True

    def test_same_version(self) -> None:
        assert compare_versions("0.5.0", "0.5.0") is False

    def test_older_release(self) -> None:
        assert compare_versions("0.6.0", "0.5.0") is False

    def test_dev_suffix_older_than_release(self) -> None:
        assert compare_versions("0.5.0-dev", "0.5.0") is True

    def test_rc_suffix_older_than_release(self) -> None:
        assert compare_versions("0.5.0-rc1", "0.5.0") is True

    def test_patch_bump_detected(self) -> None:
        assert compare_versions("0.5.0", "0.5.1") is True

    def test_major_bump_detected(self) -> None:
        assert compare_versions("0.5.0", "1.0.0") is True

    def test_current_newer_than_latest(self) -> None:
        assert compare_versions("1.0.0", "0.9.0") is False

    def test_handles_v_prefix(self) -> None:
        assert compare_versions("0.5.0", "v0.6.0") is True

    def test_handles_both_v_prefix(self) -> None:
        assert compare_versions("v0.5.0", "v0.5.0") is False

    def test_invalid_version_returns_false(self) -> None:
        assert compare_versions("invalid", "0.5.0") is False
        assert compare_versions("0.5.0", "invalid") is False

    def test_empty_version_returns_false(self) -> None:
        assert compare_versions("", "0.5.0") is False
        assert compare_versions("0.5.0", "") is False


class TestUpdateCheckResult:
    """UpdateCheckResult data structure."""

    def test_no_update_available(self) -> None:
        result = UpdateCheckResult(
            current_version="0.5.0",
            latest_version="0.5.0",
            update_available=False,
            checked_at=datetime.now(UTC),
        )
        assert not result.update_available

    def test_update_available(self) -> None:
        result = UpdateCheckResult(
            current_version="0.5.0",
            latest_version="0.6.0",
            update_available=True,
            release_url="https://github.com/pullboxapp/pullbox/releases/tag/v0.6.0",
            release_notes="Bug fixes",
            release_date="2026-04-01",
            checked_at=datetime.now(UTC),
        )
        assert result.update_available
        assert result.release_url is not None


class TestUpdateCheckService:
    """Service handles GitHub API, caching, and errors."""

    @pytest.mark.asyncio
    async def test_check_returns_result(self) -> None:
        """Successful check returns an UpdateCheckResult."""
        service = UpdateCheckService()
        mock_response = {
            "tag_name": "v0.7.0",
            "html_url": "https://github.com/pullboxapp/pullbox/releases/tag/v0.7.0",
            "body": "Release notes here",
            "published_at": "2026-04-01T00:00:00Z",
        }
        with (
            patch("pullbox.__version__", "0.6.5"),
            patch.object(service, "_fetch_latest_release", return_value=mock_response),
        ):
            result = await service.check_for_update()

        assert result is not None
        assert result.current_version == "0.6.5"
        assert result.latest_version == "0.7.0"
        assert result.update_available is True

    @pytest.mark.asyncio
    async def test_cache_prevents_repeated_calls(self) -> None:
        """Second call within cache TTL returns cached result."""
        service = UpdateCheckService(cache_ttl_hours=24)
        mock_response = {
            "tag_name": "v0.6.0",
            "html_url": "https://github.com/test",
            "body": "",
            "published_at": "2026-04-01T00:00:00Z",
        }
        with patch.object(service, "_fetch_latest_release", return_value=mock_response) as mock:
            await service.check_for_update()
            await service.check_for_update()
            assert mock.call_count == 1

    @pytest.mark.asyncio
    async def test_force_bypasses_cache(self) -> None:
        """force=True ignores the cache."""
        service = UpdateCheckService(cache_ttl_hours=24)
        mock_response = {
            "tag_name": "v0.6.0",
            "html_url": "https://github.com/test",
            "body": "",
            "published_at": "2026-04-01T00:00:00Z",
        }
        with patch.object(service, "_fetch_latest_release", return_value=mock_response) as mock:
            await service.check_for_update()
            await service.check_for_update(force=True)
            assert mock.call_count == 2

    @pytest.mark.asyncio
    async def test_github_unreachable_returns_none(self) -> None:
        """When GitHub API fails, returns None (no crash)."""
        service = UpdateCheckService()
        with patch.object(service, "_fetch_latest_release", side_effect=Exception("timeout")):
            result = await service.check_for_update()
        assert result is None

    @pytest.mark.asyncio
    async def test_no_releases_returns_up_to_date(self) -> None:
        """When GitHub has no releases (404), returns up-to-date (not an error)."""
        service = UpdateCheckService()
        with patch.object(service, "_fetch_latest_release", return_value=None):
            result = await service.check_for_update()
        assert result is not None
        assert result.update_available is False
        assert result.current_version == result.latest_version

    @pytest.mark.asyncio
    async def test_cached_result_returned(self) -> None:
        """get_cached returns the last successful result."""
        service = UpdateCheckService()
        assert service.get_cached() is None

        mock_response = {
            "tag_name": "v0.6.0",
            "html_url": "https://github.com/test",
            "body": "",
            "published_at": "2026-04-01T00:00:00Z",
        }
        with patch.object(service, "_fetch_latest_release", return_value=mock_response):
            await service.check_for_update()

        cached = service.get_cached()
        assert cached is not None
        assert cached.latest_version == "0.6.0"

    @pytest.mark.asyncio
    async def test_expired_cache_refetches(self) -> None:
        """Expired cache triggers a new fetch."""
        service = UpdateCheckService(cache_ttl_hours=24)
        mock_response = {
            "tag_name": "v0.6.0",
            "html_url": "https://github.com/test",
            "body": "",
            "published_at": "2026-04-01T00:00:00Z",
        }
        with patch.object(service, "_fetch_latest_release", return_value=mock_response) as mock:
            await service.check_for_update()
            # Manually expire the cache
            service._last_check = datetime.now(UTC) - timedelta(hours=25)
            await service.check_for_update()
            assert mock.call_count == 2

    @pytest.mark.asyncio
    async def test_concurrent_calls_share_single_fetch(self) -> None:
        """Concurrent checks should collapse into a single GitHub fetch."""
        service = UpdateCheckService()
        mock_response = {
            "tag_name": "v0.6.0",
            "html_url": "https://github.com/test",
            "body": "",
            "published_at": "2026-04-01T00:00:00Z",
        }

        async def _delayed_fetch() -> dict[str, str]:
            await asyncio.sleep(0.01)
            return mock_response

        with patch.object(service, "_fetch_latest_release", side_effect=_delayed_fetch) as mock:
            first, second = await asyncio.gather(
                service.check_for_update(),
                service.check_for_update(),
            )

        assert first is not None
        assert second is not None
        assert first.latest_version == "0.6.0"
        assert second.latest_version == "0.6.0"
        assert mock.call_count == 1

    @pytest.mark.asyncio
    async def test_no_update_when_current_is_latest(self) -> None:
        """No update flagged when versions match."""
        service = UpdateCheckService()
        mock_response = {
            "tag_name": "v0.5.0-dev",
            "html_url": "https://github.com/test",
            "body": "",
            "published_at": "2026-04-01T00:00:00Z",
        }
        with patch.object(service, "_fetch_latest_release", return_value=mock_response):
            result = await service.check_for_update()

        assert result is not None
        assert result.update_available is False
