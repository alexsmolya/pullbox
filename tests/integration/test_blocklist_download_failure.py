"""
Integration tests for auto-blocklisting on download failure.

Validates that downloads which exhaust max retries are automatically
added to the blocklist when the config is enabled.

Run:
    pytest tests/integration/test_blocklist_download_failure.py -v
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pullbox.models.blocklist import BlocklistEntry, BlocklistReason
from pullbox.models.config import SystemConfig
from pullbox.models.download import DownloadHistory, DownloadState
from pullbox.models.issue import Issue, IssueStatus
from pullbox.models.series import Series, SeriesStatus
from pullbox.tasks.download_task import _handle_download_failure

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture()
async def test_series(db_session: AsyncSession) -> Series:
    """Create a minimal series for FK references."""
    series = Series(
        title="Batman",
        sort_title="batman",
        comicvine_id=99999,
        status=SeriesStatus.CONTINUING,
    )
    db_session.add(series)
    await db_session.flush()
    return series


@pytest.fixture()
async def test_issue(db_session: AsyncSession, test_series: Series) -> Issue:
    """Create a minimal issue for FK references."""
    issue = Issue(
        series_id=test_series.id,
        issue_number=18.0,
        status=IssueStatus.DOWNLOADING,
    )
    db_session.add(issue)
    await db_session.flush()
    return issue


@pytest.fixture()
async def make_download(db_session: AsyncSession, test_issue: Issue) -> callable:  # type: ignore[type-arg]
    """Factory fixture for DownloadHistory entries."""

    async def _make(
        title: str = "Batman.018.2026.Digital.Zone-Empire",
        *,
        retry_count: int = 2,
        max_retries: int = 3,
        state: DownloadState = DownloadState.DOWNLOADING,
        indexer_id: int | None = None,
    ) -> DownloadHistory:
        dl = DownloadHistory(
            issue_id=test_issue.id,
            title=title,
            download_url=f"https://example.com/nzb/{title}",
            download_client="sabnzbd",
            state=state,
            retry_count=retry_count,
            max_retries=max_retries,
            indexer_id=indexer_id,
        )
        db_session.add(dl)
        await db_session.flush()
        return dl

    return _make


async def _set_config(session: AsyncSession, key: str, value: str) -> None:
    """Helper to set a SystemConfig value."""
    existing = await session.get(SystemConfig, key)
    if existing:
        existing.value = value
    else:
        session.add(SystemConfig(key=key, value=value, value_type="string"))
    await session.flush()


# ── Auto-add on failure tests ─────────────────────────────────────────


@pytest.mark.slow
class TestAutoBlocklistOnFailure:
    """Tests for auto-blocklisting when downloads exhaust max retries."""

    async def test_max_retries_exhausted_adds_to_blocklist(
        self,
        db_session: AsyncSession,
        make_download: callable,  # type: ignore[type-arg]
    ) -> None:
        """Download at max retries → state=FAILED → blocklist entry created."""
        dl = await make_download(retry_count=2, max_retries=3)
        await _handle_download_failure(db_session, dl, "Connection timeout")

        assert dl.state == DownloadState.FAILED

        from sqlalchemy import select

        result = await db_session.execute(select(BlocklistEntry))
        entries = list(result.scalars().all())
        assert len(entries) == 1
        assert entries[0].reason == BlocklistReason.FAILED
        assert entries[0].release_title == dl.title
        assert entries[0].download_url == dl.download_url
        assert entries[0].issue_id == dl.issue_id
        assert entries[0].download_history_id == dl.id

    async def test_blocklist_entry_has_error_message(
        self,
        db_session: AsyncSession,
        make_download: callable,  # type: ignore[type-arg]
    ) -> None:
        dl = await make_download(retry_count=2, max_retries=3)
        await _handle_download_failure(db_session, dl, "Extraction failed")

        from sqlalchemy import select

        entry = (await db_session.execute(select(BlocklistEntry))).scalar_one()
        assert entry.error_message == "Extraction failed"

    async def test_retries_remaining_not_blocklisted(
        self,
        db_session: AsyncSession,
        make_download: callable,  # type: ignore[type-arg]
    ) -> None:
        """Download with retries remaining → RETRY_PENDING, NOT blocklisted."""
        dl = await make_download(retry_count=0, max_retries=3)
        await _handle_download_failure(db_session, dl, "Timeout")

        assert dl.state == DownloadState.RETRY_PENDING

        from sqlalchemy import select

        result = await db_session.execute(select(BlocklistEntry))
        assert result.scalar_one_or_none() is None

    async def test_duplicate_failure_idempotent(
        self,
        db_session: AsyncSession,
        make_download: callable,  # type: ignore[type-arg]
    ) -> None:
        """Two downloads of same title fail → only one blocklist entry."""
        dl1 = await make_download(title="Same.Release.001", retry_count=2, max_retries=3)
        await _handle_download_failure(db_session, dl1, "Error 1")

        dl2 = await make_download(title="Same.Release.001", retry_count=2, max_retries=3)
        await _handle_download_failure(db_session, dl2, "Error 2")

        from sqlalchemy import select

        result = await db_session.execute(select(BlocklistEntry))
        entries = list(result.scalars().all())
        assert len(entries) == 1


@pytest.mark.slow
class TestAutoBlocklistDisabled:
    """Tests for when auto-blocklist is disabled via config."""

    async def test_disabled_config_no_blocklist(
        self,
        db_session: AsyncSession,
        make_download: callable,  # type: ignore[type-arg]
    ) -> None:
        """Config auto_add_on_failure=false → no blocklist on failure."""
        await _set_config(db_session, "blocklist.auto_add_on_failure", "false")

        dl = await make_download(retry_count=2, max_retries=3)
        await _handle_download_failure(db_session, dl, "Connection timeout")

        assert dl.state == DownloadState.FAILED

        from sqlalchemy import select

        result = await db_session.execute(select(BlocklistEntry))
        assert result.scalar_one_or_none() is None


@pytest.mark.slow
class TestAutoBlocklistEdgeCases:
    """Edge cases for download failure auto-blocklist."""

    async def test_no_indexer_id(
        self,
        db_session: AsyncSession,
        make_download: callable,  # type: ignore[type-arg]
    ) -> None:
        """Download with no indexer → entry created with indexer_id=None."""
        dl = await make_download(retry_count=2, max_retries=3, indexer_id=None)
        await _handle_download_failure(db_session, dl, "Error")

        from sqlalchemy import select

        entry = (await db_session.execute(select(BlocklistEntry))).scalar_one()
        assert entry.indexer_id is None

    async def test_unparseable_title_no_group(
        self,
        db_session: AsyncSession,
        make_download: callable,  # type: ignore[type-arg]
    ) -> None:
        """Title that parser can't extract group → release_group=None."""
        dl = await make_download(title="just some random text", retry_count=2, max_retries=3)
        await _handle_download_failure(db_session, dl, "Error")

        from sqlalchemy import select

        entry = (await db_session.execute(select(BlocklistEntry))).scalar_one()
        assert entry.release_group is None


@pytest.mark.slow
class TestAutoBlocklistPerClient:
    """Verify auto-blocklist works for all 5 download client types.

    Each client type stores a different client identifier in the download
    history. The auto-blocklist path must work regardless of which client
    the download was sent to.
    """

    @pytest.mark.parametrize(
        "client_type",
        ["SABNZBD", "NZBGET", "QBITTORRENT", "TRANSMISSION", "DELUGE"],
    )
    async def test_auto_blocklist_per_client(
        self,
        db_session: AsyncSession,
        test_issue: Issue,
        client_type: str,
    ) -> None:
        """Download failure via {client_type} → blocklist entry created."""
        from sqlalchemy import select

        title = f"Test.Release.{client_type}.001.2026.Digital.Zone-Empire"
        dl = DownloadHistory(
            issue_id=test_issue.id,
            title=title,
            download_url=f"https://example.com/nzb/{title}",
            download_client=client_type,
            state=DownloadState.DOWNLOADING,
            retry_count=2,
            max_retries=3,
        )
        db_session.add(dl)
        await db_session.flush()

        await _handle_download_failure(db_session, dl, f"{client_type} connection refused")

        assert dl.state == DownloadState.FAILED

        result = await db_session.execute(
            select(BlocklistEntry).where(BlocklistEntry.release_title == title)
        )
        entry = result.scalars().first()
        assert entry is not None, f"Blocklist entry not created for {client_type}"
        assert entry.reason == BlocklistReason.FAILED
        assert entry.error_message == f"{client_type} connection refused"
        assert entry.download_history_id == dl.id
        assert entry.issue_id == test_issue.id

    @pytest.mark.parametrize(
        "client_type",
        ["SABNZBD", "NZBGET", "QBITTORRENT", "TRANSMISSION", "DELUGE"],
    )
    async def test_retries_remaining_not_blocklisted_per_client(
        self,
        db_session: AsyncSession,
        test_issue: Issue,
        client_type: str,
    ) -> None:
        """Download with retries remaining via {client_type} → NOT blocklisted."""
        from sqlalchemy import select

        title = f"Test.Retry.{client_type}.001.2026.Digital.Empire"
        dl = DownloadHistory(
            issue_id=test_issue.id,
            title=title,
            download_url=f"https://example.com/nzb/{title}",
            download_client=client_type,
            state=DownloadState.DOWNLOADING,
            retry_count=0,
            max_retries=3,
        )
        db_session.add(dl)
        await db_session.flush()

        await _handle_download_failure(db_session, dl, "Temporary error")

        assert dl.state == DownloadState.RETRY_PENDING

        result = await db_session.execute(
            select(BlocklistEntry).where(BlocklistEntry.release_title == title)
        )
        assert result.scalar_one_or_none() is None, (
            f"Entry should NOT be blocklisted with retries remaining ({client_type})"
        )
