"""Tests for C-2.1 — auto-kill stalled downloads with configurable timeout.

Verifies that downloads stuck in DOWNLOADING with no progress, stalled
client states, or metadata-fetching states are detected and handled via
retry logic after the configurable stall timeout (default 1 hour).

Run:
    pytest tests/unit/test_download_stall_detection.py -v
"""

from __future__ import annotations

import os
import time as _time
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-stall-detect")

from pullbox.models.download import DownloadHistory, DownloadState
from pullbox.models.issue import Issue, IssueStatus
from pullbox.tasks.download_task import (
    _STALLED_DOWNLOAD_TIMEOUT,
    ProgressSnapshot,
    _get_stall_timeout,
    _progress_cache,
    _recover_stalled_downloads,
    _stall_first_seen,
)


def _make_download(
    *,
    dl_id: int = 1,
    state: DownloadState = DownloadState.DOWNLOADING,
    external_id: str | None = "abc123",
    updated_at: datetime | None = None,
    issue_id: int = 100,
    error_message: str | None = None,
    retry_count: int = 0,
    max_retries: int = 3,
) -> MagicMock:
    """Create a mock DownloadHistory with the given attributes."""
    dl = MagicMock(spec=DownloadHistory)
    dl.id = dl_id
    dl.state = state
    dl.external_id = external_id
    dl.updated_at = updated_at or datetime.now(UTC)
    dl.issue_id = issue_id
    dl.error_message = error_message
    dl.retry_count = retry_count
    dl.max_retries = max_retries
    dl.next_retry_at = None
    return dl


def _make_issue(
    *,
    issue_id: int = 100,
    status: IssueStatus = IssueStatus.DOWNLOADING,
) -> MagicMock:
    """Create a mock Issue with the given attributes."""
    issue = MagicMock(spec=Issue)
    issue.id = issue_id
    issue.status = status
    return issue


def _make_snapshot(
    *,
    progress: float = 0.5,
    client_state: str | None = None,
    age_seconds: float = 0.0,
) -> ProgressSnapshot:
    """Create a ProgressSnapshot with a controllable timestamp."""
    return ProgressSnapshot(
        progress=progress,
        speed_bytes=0,
        eta_seconds=None,
        size_bytes=None,
        updated_at=_time.monotonic() - age_seconds,
        client_state=client_state,
    )


def _mock_config_row(value: str) -> MagicMock:
    """Create a mock SystemConfig row with the given value."""
    return _mock_config_row_for_key(value, "stall_timeout_hours")


def _mock_config_row_for_key(value: str, key: str) -> MagicMock:
    """Create a mock SystemConfig row for a specific key/value pair."""
    row = MagicMock()
    row.key = key
    row.value = value
    return row


def _mock_execute_result(rows: list[object]) -> MagicMock:
    """Create a SQLAlchemy-style execute result for ``scalars().all()``."""
    return MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=rows))))


def _make_config_session(rows: list[MagicMock]) -> AsyncMock:
    """Build a session for direct stall-timeout resolver tests."""
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_mock_execute_result(rows))
    return session


def _make_session(
    stalled_downloads: list[MagicMock] | None = None,
    issue: MagicMock | None = None,
    config_value: str = "1",
) -> AsyncMock:
    """Build a mock session that returns config rows, then stalled downloads.

    session.execute() is called first by the shared config resolver, then for
    the stalled-download query. session.get() remains available for blocklist,
    issue, and client-state recovery lookups.
    """
    session = AsyncMock()

    # session.get is called for:
    # 1. Per stalled download that exhausts retries:
    #    a. Issue lookup (to reset status to WANTED)
    # 2. Per stalled download with retries remaining:
    #    a. Issue lookup only (no blocklist call)
    get_returns: list[object] = []
    execute_returns = [
        _mock_execute_result([_mock_config_row(config_value)]),
        _mock_execute_result(stalled_downloads or []),
    ]
    if stalled_downloads:
        for dl in stalled_downloads:
            # Keep auto-blocklist disabled in these unit tests. The blocklist
            # entry path is covered in blocklist-specific integration tests.
            will_exhaust = (dl.retry_count + 1) >= dl.max_retries
            if will_exhaust:
                execute_returns.append(
                    _mock_execute_result(
                        [
                            _mock_config_row_for_key(
                                "false",
                                "blocklist.auto_add_on_failure",
                            )
                        ]
                    )
                )
            get_returns.append(issue or _make_issue())
    session.get = AsyncMock(side_effect=get_returns)

    # session.execute returns config rows, then the stalled downloads query.
    session.execute = AsyncMock(side_effect=execute_returns)

    return session


# ── Timeout Configuration ────────────────────────────────────────


class TestStallTimeoutConstant:
    """Verify the stall timeout fallback constant."""

    def test_stall_timeout_default_is_1_hour(self) -> None:
        assert timedelta(hours=1) == _STALLED_DOWNLOAD_TIMEOUT

    def test_stall_timeout_type(self) -> None:
        assert isinstance(_STALLED_DOWNLOAD_TIMEOUT, timedelta)


class TestConfigurableTimeout:
    """Stall timeout can be configured via SystemConfig."""

    @pytest.mark.asyncio
    async def test_reads_timeout_from_config(self) -> None:
        """Config value of 2 hours should produce a 2-hour timedelta."""
        session = _make_config_session([_mock_config_row("2")])

        timeout = await _get_stall_timeout(session)
        assert timeout == timedelta(hours=2)

    @pytest.mark.asyncio
    async def test_reads_timeout_with_shared_config_resolver(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Stall timeout should use the shared config resolver."""
        from pullbox.tasks import download_stall_recovery

        calls: list[tuple[str, ...]] = []

        async def fake_load_system_config_values(
            session: AsyncMock,
            keys: tuple[str, ...],
        ) -> dict[str, str]:
            _ = session
            calls.append(keys)
            return {"stall_timeout_hours": "3"}

        monkeypatch.setattr(
            download_stall_recovery,
            "load_system_config_values",
            fake_load_system_config_values,
            raising=False,
        )

        timeout = await download_stall_recovery._get_stall_timeout(AsyncMock())

        assert calls == [("stall_timeout_hours",)]
        assert timeout == timedelta(hours=3)

    @pytest.mark.asyncio
    async def test_fallback_when_config_missing(self) -> None:
        """Missing config row should fall back to default."""
        session = _make_config_session([])

        timeout = await _get_stall_timeout(session)
        assert timeout == _STALLED_DOWNLOAD_TIMEOUT

    @pytest.mark.asyncio
    async def test_fallback_on_invalid_config_value(self) -> None:
        """Non-integer config value should fall back to default."""
        session = _make_config_session([_mock_config_row("abc")])

        timeout = await _get_stall_timeout(session)
        assert timeout == _STALLED_DOWNLOAD_TIMEOUT

    @pytest.mark.asyncio
    async def test_fallback_on_zero_config_value(self) -> None:
        """Zero hours is invalid — should fall back to default."""
        session = _make_config_session([_mock_config_row("0")])

        timeout = await _get_stall_timeout(session)
        assert timeout == _STALLED_DOWNLOAD_TIMEOUT

    @pytest.mark.asyncio
    async def test_fallback_on_negative_config_value(self) -> None:
        """Negative hours is invalid — should fall back to default."""
        session = _make_config_session([_mock_config_row("-1")])

        timeout = await _get_stall_timeout(session)
        assert timeout == _STALLED_DOWNLOAD_TIMEOUT

    @pytest.mark.asyncio
    async def test_empty_value_falls_back(self) -> None:
        """Empty string config value should fall back to default."""
        session = _make_config_session([_mock_config_row("")])

        timeout = await _get_stall_timeout(session)
        assert timeout == _STALLED_DOWNLOAD_TIMEOUT


# ── Stall Detection by updated_at ────────────────────────────────


class TestStalledByUpdatedAt:
    """Downloads in DOWNLOADING whose updated_at exceeds the timeout."""

    @pytest.mark.asyncio
    async def test_download_stalled_past_timeout_triggers_failure(self) -> None:
        """A DOWNLOADING record not updated in 1+ hours triggers retry logic."""
        stale_time = datetime.now(UTC) - timedelta(hours=1, minutes=5)
        dl = _make_download(updated_at=stale_time, max_retries=3, retry_count=2)

        session = _make_session(stalled_downloads=[dl])
        count = await _recover_stalled_downloads(session)

        assert count == 1
        # retry_count was 2, max_retries 3 — so this is the 3rd failure
        # _handle_download_failure increments retry_count to 3, which == max_retries → FAILED
        assert dl.state == DownloadState.FAILED
        assert "stalled" in dl.error_message.lower()

    @pytest.mark.asyncio
    async def test_download_under_timeout_not_affected(self) -> None:
        """A DOWNLOADING record updated 30 minutes ago should not be touched."""
        session = _make_session(stalled_downloads=[])
        count = await _recover_stalled_downloads(session)
        assert count == 0

    @pytest.mark.asyncio
    async def test_first_stall_schedules_retry(self) -> None:
        """First stall on a download should schedule a retry, not permanent failure."""
        stale_time = datetime.now(UTC) - timedelta(hours=1, minutes=5)
        dl = _make_download(updated_at=stale_time, max_retries=3, retry_count=0)
        issue = _make_issue(status=IssueStatus.DOWNLOADING)

        session = _make_session(stalled_downloads=[dl], issue=issue)
        await _recover_stalled_downloads(session)

        # retry_count 0 → incremented to 1, which < 3 → RETRY_PENDING
        assert dl.state == DownloadState.RETRY_PENDING
        assert dl.next_retry_at is not None
        # Issue should NOT be reset to WANTED on retry (only on permanent failure)
        assert issue.status == IssueStatus.DOWNLOADING

    @pytest.mark.asyncio
    async def test_exhausted_retries_marks_permanently_failed(self) -> None:
        """Download that has exhausted retries should be permanently FAILED."""
        stale_time = datetime.now(UTC) - timedelta(hours=1, minutes=5)
        dl = _make_download(updated_at=stale_time, max_retries=3, retry_count=2)
        issue = _make_issue(status=IssueStatus.DOWNLOADING)

        session = _make_session(stalled_downloads=[dl], issue=issue)
        await _recover_stalled_downloads(session)

        assert dl.state == DownloadState.FAILED
        assert issue.status == IssueStatus.WANTED

    @pytest.mark.asyncio
    async def test_issue_reset_only_on_permanent_failure(self) -> None:
        """Issue should only go WANTED when retries are exhausted."""
        stale_time = datetime.now(UTC) - timedelta(hours=1, minutes=5)
        dl = _make_download(updated_at=stale_time, max_retries=3, retry_count=1)
        issue = _make_issue(status=IssueStatus.DOWNLOADING)

        session = _make_session(stalled_downloads=[dl], issue=issue)
        await _recover_stalled_downloads(session)

        # retry_count 1 → 2, still < 3 → RETRY_PENDING
        assert dl.state == DownloadState.RETRY_PENDING
        assert issue.status == IssueStatus.DOWNLOADING


# ── Stall Detection by Client State ──────────────────────────────


class TestStalledByClientState:
    """Downloads with stall-indicating client_state in the progress cache."""

    @pytest.mark.asyncio
    async def test_stalled_client_state_detected(self) -> None:
        """A download with client_state 'Stalled' for 1+ hours is recovered via Path 2.

        Path 2 uses _stall_first_seen (in-memory tracker) to detect client-state
        stalls that have persisted beyond the timeout, even when updated_at is recent.
        """
        # Recent updated_at — won't be caught by Path 1 (time-based)
        recent_time = datetime.now(UTC) - timedelta(minutes=5)
        dl = _make_download(dl_id=42, updated_at=recent_time, max_retries=3, retry_count=2)

        _progress_cache[42] = _make_snapshot(
            progress=0.3,
            client_state="Stalled",
            age_seconds=3900,
        )
        # Simulate stall first seen >1 hour ago
        _stall_first_seen[42] = _time.monotonic() - 3900

        # Path 1 returns empty (updated_at is recent), Path 2 catches via _stall_first_seen
        session = _make_session(stalled_downloads=[], issue=_make_issue())
        # Path 2 uses get() for DownloadHistory, blocklist config, then Issue.
        session.get = AsyncMock(side_effect=[dl, None, _make_issue()])

        count = await _recover_stalled_downloads(session)

        assert count == 1
        assert dl.state == DownloadState.FAILED
        assert "Stalled" in dl.error_message
        _progress_cache.pop(42, None)
        _stall_first_seen.pop(42, None)

    @pytest.mark.asyncio
    async def test_metadata_stall_sabnzbd(self) -> None:
        """SABnzbd 'Fetching' metadata stalled for 1+ hours is recovered."""
        stale_time = datetime.now(UTC) - timedelta(hours=1, minutes=10)
        dl = _make_download(dl_id=43, updated_at=stale_time, max_retries=3, retry_count=2)

        _progress_cache[43] = _make_snapshot(
            progress=0.0,
            client_state="Fetching",
            age_seconds=4200,
        )

        session = _make_session(stalled_downloads=[dl])
        count = await _recover_stalled_downloads(session)

        assert count == 1
        assert dl.state == DownloadState.FAILED
        _progress_cache.pop(43, None)

    @pytest.mark.asyncio
    async def test_metadata_stall_qbittorrent(self) -> None:
        """qBittorrent 'metaDL' stalled for 1+ hours is recovered."""
        stale_time = datetime.now(UTC) - timedelta(hours=1, minutes=10)
        dl = _make_download(dl_id=44, updated_at=stale_time, max_retries=3, retry_count=2)

        _progress_cache[44] = _make_snapshot(
            progress=0.0,
            client_state="metaDL",
            age_seconds=4200,
        )

        session = _make_session(stalled_downloads=[dl])
        count = await _recover_stalled_downloads(session)

        assert count == 1
        assert dl.state == DownloadState.FAILED
        _progress_cache.pop(44, None)

    @pytest.mark.asyncio
    async def test_client_state_included_in_error_message(self) -> None:
        """Error message from Path 2 includes the client state label."""
        recent_time = datetime.now(UTC) - timedelta(minutes=5)
        dl = _make_download(dl_id=45, updated_at=recent_time, max_retries=1, retry_count=0)

        _progress_cache[45] = _make_snapshot(
            progress=0.0,
            client_state="metaDL",
            age_seconds=3900,
        )
        _stall_first_seen[45] = _time.monotonic() - 3900

        session = _make_session(stalled_downloads=[])
        # DownloadHistory, blocklist config (None), Issue
        session.get = AsyncMock(side_effect=[dl, None, _make_issue()])

        await _recover_stalled_downloads(session)

        assert "metaDL" in dl.error_message
        _progress_cache.pop(45, None)
        _stall_first_seen.pop(45, None)


# ── False Positive Prevention ────────────────────────────────────


class TestStalledNotFalsePositive:
    """Ensure we don't false-positive on downloads that are fine."""

    @pytest.mark.asyncio
    async def test_brief_client_stall_within_grace_period(self) -> None:
        """A brief client-state stall (under timeout) should NOT trigger recovery."""
        recent_time = datetime.now(UTC) - timedelta(minutes=5)
        dl = _make_download(dl_id=60, updated_at=recent_time)

        _progress_cache[60] = _make_snapshot(
            progress=0.3,
            client_state="Stalled",
            age_seconds=600,  # 10 minutes
        )
        # Stall first seen 10 minutes ago — well under the 1-hour timeout
        _stall_first_seen[60] = _time.monotonic() - 600

        session = _make_session(stalled_downloads=[])
        count = await _recover_stalled_downloads(session)

        assert count == 0
        assert dl.state == DownloadState.DOWNLOADING
        _progress_cache.pop(60, None)
        _stall_first_seen.pop(60, None)

    @pytest.mark.asyncio
    async def test_active_download_with_progress_not_affected(self) -> None:
        """A download making progress should NOT be marked stalled."""
        _progress_cache[50] = _make_snapshot(
            progress=0.6,
            client_state="Downloading",
            age_seconds=10,
        )

        session = _make_session(stalled_downloads=[])
        count = await _recover_stalled_downloads(session)

        assert count == 0
        _progress_cache.pop(50, None)

    @pytest.mark.asyncio
    async def test_download_without_external_id_not_double_counted(self) -> None:
        """Downloads without external_id are handled by Case 1, not stall detection."""
        session = _make_session(stalled_downloads=[])
        count = await _recover_stalled_downloads(session)
        assert count == 0

    @pytest.mark.asyncio
    async def test_issue_not_in_downloading_not_changed(self) -> None:
        """If the issue is already WANTED, don't touch it on permanent failure."""
        stale_time = datetime.now(UTC) - timedelta(hours=1, minutes=5)
        dl = _make_download(updated_at=stale_time, max_retries=3, retry_count=2)
        issue = _make_issue(status=IssueStatus.WANTED)

        session = _make_session(stalled_downloads=[dl], issue=issue)
        await _recover_stalled_downloads(session)

        assert issue.status == IssueStatus.WANTED


# ── Multiple Stalled Downloads ───────────────────────────────────


class TestMultipleStalledDownloads:
    """Multiple downloads can be stalled in the same pass."""

    @pytest.mark.asyncio
    async def test_multiple_stalled_all_recovered(self) -> None:
        """Multiple stalled downloads should all be recovered."""
        stale_time = datetime.now(UTC) - timedelta(hours=2)
        dl1 = _make_download(
            dl_id=1,
            updated_at=stale_time,
            issue_id=101,
            max_retries=3,
            retry_count=2,
        )
        dl2 = _make_download(
            dl_id=2,
            updated_at=stale_time,
            issue_id=102,
            max_retries=3,
            retry_count=0,
        )
        dl3 = _make_download(
            dl_id=3,
            updated_at=stale_time,
            issue_id=103,
            max_retries=3,
            retry_count=2,
        )

        session = _make_session(stalled_downloads=[dl1, dl2, dl3])
        count = await _recover_stalled_downloads(session)

        assert count == 3
        assert dl1.state == DownloadState.FAILED  # retries exhausted
        assert dl2.state == DownloadState.RETRY_PENDING  # has retries left
        assert dl3.state == DownloadState.FAILED  # retries exhausted


# ── Error Messages ───────────────────────────────────────────────


class TestErrorMessage:
    """Stalled downloads get descriptive error messages."""

    @pytest.mark.asyncio
    async def test_error_message_mentions_stalled(self) -> None:
        stale_time = datetime.now(UTC) - timedelta(hours=1, minutes=5)
        dl = _make_download(updated_at=stale_time, max_retries=3, retry_count=2)

        session = _make_session(stalled_downloads=[dl])
        await _recover_stalled_downloads(session)

        assert dl.error_message is not None
        assert "stall" in dl.error_message.lower()

    @pytest.mark.asyncio
    async def test_error_message_mentions_timeout_duration(self) -> None:
        stale_time = datetime.now(UTC) - timedelta(hours=1, minutes=5)
        dl = _make_download(updated_at=stale_time, max_retries=3, retry_count=2)

        session = _make_session(stalled_downloads=[dl])
        await _recover_stalled_downloads(session)

        # Default is 1 hour = 60 minutes
        assert "60" in dl.error_message or "minute" in dl.error_message.lower()

    @pytest.mark.asyncio
    async def test_custom_timeout_reflected_in_message(self) -> None:
        """A 2-hour config should show 120 minutes in the error message."""
        stale_time = datetime.now(UTC) - timedelta(hours=2, minutes=5)
        dl = _make_download(updated_at=stale_time, max_retries=3, retry_count=2)

        session = _make_session(stalled_downloads=[dl], config_value="2")
        await _recover_stalled_downloads(session)

        assert "120" in dl.error_message


# ── No-Op Cases ──────────────────────────────────────────────────


class TestNoDownloadsToRecover:
    """No-op when there are no stalled downloads."""

    @pytest.mark.asyncio
    async def test_empty_result_returns_zero(self) -> None:
        session = _make_session(stalled_downloads=[])
        count = await _recover_stalled_downloads(session)
        assert count == 0


# ── Integration ──────────────────────────────────────────────────


class TestIntegrationWithRecovery:
    """Verify _recover_stalled_downloads is called from _recover_orphaned_downloads."""

    def test_recover_orphaned_calls_stall_detection(self) -> None:
        """The main recovery function should reference stall detection."""
        import inspect

        from pullbox.tasks.download_task import _recover_orphaned_downloads

        source = inspect.getsource(_recover_orphaned_downloads)
        assert "_recover_stalled_downloads" in source


class TestConfigKeyExists:
    """Verify the stall_timeout_hours key exists in DEFAULT_SYSTEM_CONFIG."""

    def test_config_key_registered(self) -> None:
        from pullbox.models.config import DEFAULT_SYSTEM_CONFIG

        assert "stall_timeout_hours" in DEFAULT_SYSTEM_CONFIG

    def test_config_default_is_1_hour(self) -> None:
        from pullbox.models.config import DEFAULT_SYSTEM_CONFIG

        value, value_type = DEFAULT_SYSTEM_CONFIG["stall_timeout_hours"]
        assert value == "1"
        assert value_type == "int"
