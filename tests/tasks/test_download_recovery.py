"""Download recovery module characterization tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

pytest_plugins = ["tests.conftest_security"]


def test_recovery_module_exposes_retry_and_orphan_helpers() -> None:
    """Retry and orphan recovery should live in the adjacent recovery module."""
    from pullbox.tasks import download_recovery

    assert timedelta(minutes=10) == download_recovery._STALE_DOWNLOAD_TIMEOUT
    assert callable(download_recovery._process_retry_pending)
    assert callable(download_recovery._recover_orphaned_downloads)


@pytest.mark.asyncio
async def test_recover_orphaned_downloads_resets_stale_and_permission_failures(
    sec_db, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    from pullbox.models.download import DownloadClientType, DownloadHistory, DownloadState
    from pullbox.models.issue import Issue, IssueStatus
    from pullbox.models.library import FileFormat, LibraryFile, LibraryRoot, MatchConfidence
    from pullbox.models.series import Series
    from pullbox.tasks import download_recovery

    async def recover_stalled(_session: object) -> int:
        return 1

    monkeypatch.setattr(download_recovery, "_recover_stalled_downloads", recover_stalled)
    stale_time = datetime.now(UTC) - timedelta(minutes=30)

    async with sec_db() as session:
        root = LibraryRoot(name="Library", path="/comics")
        series = Series(title="Recovery Series", sort_title="recovery series")
        session.add_all([root, series])
        await session.flush()

        stale_issue = Issue(
            series_id=series.id,
            issue_number=1,
            status=IssueStatus.DOWNLOADING,
        )
        permission_issue = Issue(
            series_id=series.id,
            issue_number=2,
            status=IssueStatus.WANTED,
        )
        orphan_wanted_issue = Issue(
            series_id=series.id,
            issue_number=3,
            status=IssueStatus.DOWNLOADING,
        )
        orphan_owned_issue = Issue(
            series_id=series.id,
            issue_number=4,
            status=IssueStatus.DOWNLOADING,
        )
        active_issue = Issue(
            series_id=series.id,
            issue_number=5,
            status=IssueStatus.DOWNLOADING,
        )
        session.add_all(
            [
                stale_issue,
                permission_issue,
                orphan_wanted_issue,
                orphan_owned_issue,
                active_issue,
            ]
        )
        await session.flush()

        session.add(
            LibraryFile(
                file_path="/comics/recovery-004.cbz",
                file_name="recovery-004.cbz",
                file_size=100,
                file_format=FileFormat.CBZ,
                file_modified_at=stale_time,
                match_confidence=MatchConfidence.HIGH,
                issue_id=orphan_owned_issue.id,
                library_root_id=root.id,
            )
        )
        stale_download = DownloadHistory(
            issue_id=stale_issue.id,
            title="stale",
            download_url="https://example.test/stale",
            download_client=DownloadClientType.SABNZBD,
            external_id=None,
            state=DownloadState.SENT,
            updated_at=stale_time,
        )
        permission_download = DownloadHistory(
            issue_id=permission_issue.id,
            title="permission",
            download_url="https://example.test/permission",
            download_client=DownloadClientType.SABNZBD,
            external_id="abc",
            state=DownloadState.FAILED,
            error_message="Operation not permitted while setting xattr",
        )
        active_download = DownloadHistory(
            issue_id=active_issue.id,
            title="active",
            download_url="https://example.test/active",
            download_client=DownloadClientType.SABNZBD,
            external_id="active",
            state=DownloadState.COMPLETED,
            imported_at=None,
        )
        session.add_all(
            [
                stale_download,
                permission_download,
                active_download,
            ]
        )
        await session.commit()

        recovered = await download_recovery._recover_orphaned_downloads(session)
        await session.commit()

        assert recovered == 5
        assert stale_issue.status == IssueStatus.WANTED
        assert permission_issue.status == IssueStatus.DOWNLOADING
        assert orphan_wanted_issue.status == IssueStatus.WANTED
        assert orphan_owned_issue.status == IssueStatus.OWNED
        assert active_issue.status == IssueStatus.DOWNLOADING

        refreshed_stale = await session.get(DownloadHistory, stale_download.id)
        refreshed_permission = await session.get(DownloadHistory, permission_download.id)
        assert refreshed_stale is not None
        assert refreshed_permission is not None
        assert refreshed_stale.error_message == "Download client never acknowledged this download"
        assert refreshed_permission.state == DownloadState.COMPLETED
        assert refreshed_permission.error_message is None


@pytest.mark.asyncio
async def test_process_retry_pending_continues_after_retry_errors(sec_db) -> None:  # type: ignore[no-untyped-def]
    from pullbox.models.download import DownloadClientType, DownloadHistory, DownloadState
    from pullbox.models.issue import Issue
    from pullbox.models.series import Series
    from pullbox.tasks.download_recovery import _process_retry_pending

    now = datetime.now(UTC)
    async with sec_db() as session:
        series = Series(title="Retry Series", sort_title="retry series")
        session.add(series)
        await session.flush()
        first_issue = Issue(series_id=series.id, issue_number=1)
        second_issue = Issue(series_id=series.id, issue_number=2)
        session.add_all([first_issue, second_issue])
        await session.flush()
        first_download = DownloadHistory(
            issue_id=first_issue.id,
            title="first",
            download_url="https://example.test/first",
            download_client=DownloadClientType.QBITTORRENT,
            retry_count=1,
            state=DownloadState.RETRY_PENDING,
            next_retry_at=now - timedelta(seconds=1),
        )
        second_download = DownloadHistory(
            issue_id=second_issue.id,
            title="second",
            download_url="https://example.test/second",
            download_client=DownloadClientType.QBITTORRENT,
            retry_count=2,
            state=DownloadState.RETRY_PENDING,
            next_retry_at=now - timedelta(seconds=1),
        )
        session.add_all([first_download, second_download])
        await session.flush()
        first_download_id = first_download.id
        second_download_id = second_download.id
        await session.commit()

    class RetryService:
        def __init__(self) -> None:
            self.calls: list[int] = []

        async def retry_download(self, _session: object, download_id: int) -> None:
            self.calls.append(download_id)
            if download_id == second_download_id:
                raise RuntimeError("retry failed")

    service = RetryService()

    retried = await _process_retry_pending(sec_db, service)  # type: ignore[arg-type]

    assert retried == 1
    assert service.calls == [first_download_id, second_download_id]
