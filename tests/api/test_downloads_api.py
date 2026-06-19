"""API contract tests for download queue, history, and retry routes."""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from pullbox.api.v1 import downloads as downloads_api
from pullbox.core.exceptions import NotFoundError
from pullbox.models import Base
from pullbox.models.download import DownloadClientType, DownloadHistory, DownloadState
from pullbox.models.issue import Issue, IssueStatus
from pullbox.models.series import Series
from pullbox.models.user import APIKey, User
from pullbox.services.auth_service import AuthService

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-downloads-api")


@pytest.fixture
async def db_factory() -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
async def api_key(db_factory: async_sessionmaker[AsyncSession]) -> str:
    raw_key = "pb_k1_" + "a" * 64
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    async with db_factory() as session:
        user = User(
            username="downloadsapi",
            password_hash=AuthService.hash_password("Test@1234"),
        )
        session.add(user)
        await session.flush()
        session.add(APIKey(user_id=user.id, key_hash=key_hash, name="downloads-api-test"))
        await session.commit()
    return raw_key


@pytest.fixture
async def client(
    db_factory: async_sessionmaker[AsyncSession],
    api_key: str,
) -> AsyncGenerator[AsyncClient, None]:
    from pullbox.api.deps import get_db_dep
    from pullbox.api.middleware import reset_setup_cache
    from pullbox.app import create_app

    app = create_app()

    async def _override_db() -> AsyncGenerator[AsyncSession, None]:
        async with db_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db_dep] = _override_db
    reset_setup_cache()

    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
        headers={"X-Api-Key": api_key},
    ) as ac:
        yield ac

    app.dependency_overrides.clear()
    reset_setup_cache()


async def _seed_issue(
    factory: async_sessionmaker[AsyncSession],
    *,
    status: IssueStatus = IssueStatus.WANTED,
) -> int:
    async with factory() as session:
        series = Series(title="Batman", sort_title="batman", year_start=2025)
        session.add(series)
        await session.flush()
        issue = Issue(series_id=series.id, issue_number=4.0, status=status)
        session.add(issue)
        await session.flush()
        issue_id = issue.id
        await session.commit()
        return issue_id


async def _seed_download(
    factory: async_sessionmaker[AsyncSession],
    issue_id: int,
    *,
    title: str = "Batman 004 (2025)",
    state: DownloadState = DownloadState.FAILED,
    client_type: DownloadClientType = DownloadClientType.SABNZBD,
    download_url: str = "https://example.com/batman-004.nzb",
    external_id: str | None = "download-ext",
    downloaded_path: str | None = None,
    error_message: str | None = "Download failed",
    completed_at: datetime | None = None,
) -> int:
    async with factory() as session:
        download = DownloadHistory(
            title=title,
            state=state,
            download_client=client_type,
            download_url=download_url,
            external_id=external_id,
            issue_id=issue_id,
            downloaded_path=downloaded_path,
            error_message=error_message,
            completed_at=completed_at,
        )
        session.add(download)
        await session.flush()
        download_id = download.id
        await session.commit()
        return download_id


async def _get_download(
    factory: async_sessionmaker[AsyncSession],
    download_id: int,
) -> DownloadHistory:
    async with factory() as session:
        download = await session.get(DownloadHistory, download_id)
        assert download is not None
        return download


async def _get_issue(factory: async_sessionmaker[AsyncSession], issue_id: int) -> Issue:
    async with factory() as session:
        issue = await session.get(Issue, issue_id)
        assert issue is not None
        return issue


class TestDownloadQueueAndHistory:
    @pytest.mark.asyncio
    async def test_queue_returns_only_active_downloads_with_series_context(
        self,
        client: AsyncClient,
        db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        issue_id = await _seed_issue(db_factory)
        await _seed_download(
            db_factory,
            issue_id,
            state=DownloadState.QUEUED,
            error_message=None,
        )
        await _seed_download(
            db_factory,
            issue_id,
            state=DownloadState.FINALIZING,
            error_message=None,
        )
        await _seed_download(db_factory, issue_id, state=DownloadState.COMPLETED)
        await _seed_download(db_factory, issue_id, state=DownloadState.FAILED)

        response = await client.get("/api/v1/downloads/queue")

        assert response.status_code == 200
        data = response.json()
        assert {item["state"] for item in data} == {"queued", "finalizing"}
        assert data[0]["series_title"] == "Batman"
        assert data[0]["issue_number"] == 4.0

    @pytest.mark.asyncio
    async def test_history_paginates_download_page_records_only(
        self,
        client: AsyncClient,
        db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        issue_id = await _seed_issue(db_factory)
        for index in range(3):
            await _seed_download(
                db_factory,
                issue_id,
                title=f"Batman history {index}",
                state=DownloadState.COMPLETED,
                error_message=None,
            )
        await _seed_download(
            db_factory,
            issue_id,
            title="Imported row",
            state=DownloadState.IMPORTED,
            downloaded_path="/downloads/imported.cbz",
            error_message=None,
        )

        response = await client.get("/api/v1/downloads/history?limit=2&offset=1")

        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 3
        assert data["limit"] == 2
        assert data["offset"] == 1
        assert data["has_more"] is False
        assert len(data["items"]) == 2
        assert all(item["series_title"] == "Batman" for item in data["items"])


class TestDownloadPostProcessingRetry:
    @pytest.mark.asyncio
    async def test_retry_processing_requeues_failed_downloaded_file(
        self,
        client: AsyncClient,
        db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        issue_id = await _seed_issue(db_factory)
        download_id = await _seed_download(
            db_factory,
            issue_id,
            downloaded_path="/downloads/batman-004.cbz",
            error_message="File placement failed",
        )
        scheduler = MagicMock()

        with patch("pullbox.core.scheduler.get_scheduler", return_value=scheduler):
            response = await client.post(f"/api/v1/downloads/{download_id}/retry-processing")

        assert response.status_code == 200
        assert response.json() == {"status": "queued"}
        scheduler.run_task_now.assert_called_once_with("process_completed")
        download = await _get_download(db_factory, download_id)
        assert download.state == DownloadState.COMPLETED
        assert download.error_message == "File placement failed"

    @pytest.mark.asyncio
    async def test_retry_processing_rejects_non_post_processing_failure(
        self,
        client: AsyncClient,
        db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        issue_id = await _seed_issue(db_factory)
        download_id = await _seed_download(db_factory, issue_id, downloaded_path=None)

        response = await client.post(f"/api/v1/downloads/{download_id}/retry-processing")

        assert response.status_code == 409
        assert response.json()["detail"] == "Only failed post-processing items can be retried."


class TestDownloadRetry:
    @pytest.mark.asyncio
    async def test_retry_failed_usenet_download_resends_to_configured_client(
        self,
        client: AsyncClient,
        db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        issue_id = await _seed_issue(db_factory, status=IssueStatus.WANTED)
        download_id = await _seed_download(
            db_factory,
            issue_id,
            downloaded_path=None,
            error_message="Connection failed",
            completed_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        mock_client = AsyncMock()
        mock_client.client_type = "sabnzbd"
        mock_client.add_nzb = AsyncMock(return_value="resent-nzb-id")

        with patch(
            "pullbox.composition.providers.register_download_clients",
            new_callable=AsyncMock,
        ) as mock_register:

            async def _register(_session: object, registry: object) -> None:
                registry.register_download_client(1, mock_client)  # type: ignore[union-attr]

            mock_register.side_effect = _register

            response = await client.post(f"/api/v1/downloads/{download_id}/retry")

        assert response.status_code == 200
        assert response.json() == {"status": "sent"}
        mock_client.add_nzb.assert_awaited_once_with(
            "https://example.com/batman-004.nzb",
            "Batman 004 (2025)",
        )
        download = await _get_download(db_factory, download_id)
        assert download.state == DownloadState.SENT
        assert download.external_id == "resent-nzb-id"
        assert download.error_message is None
        assert download.downloaded_path is None
        assert download.completed_at is None
        assert download.sent_at is not None
        issue = await _get_issue(db_factory, issue_id)
        assert issue.status == IssueStatus.DOWNLOADING

    @pytest.mark.asyncio
    async def test_retry_failed_torrent_download_uses_torrent_client_method(
        self,
        client: AsyncClient,
        db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        issue_id = await _seed_issue(db_factory, status=IssueStatus.OWNED)
        download_id = await _seed_download(
            db_factory,
            issue_id,
            client_type=DownloadClientType.QBITTORRENT,
            download_url="https://example.com/batman-004.torrent",
            downloaded_path=None,
            error_message="Cancelled by user",
        )
        mock_client = AsyncMock()
        mock_client.client_type = "qbittorrent"
        mock_client.add_torrent = AsyncMock(return_value="torrent-hash")

        with patch(
            "pullbox.composition.providers.register_download_clients",
            new_callable=AsyncMock,
        ) as mock_register:

            async def _register(_session: object, registry: object) -> None:
                registry.register_download_client(2, mock_client)  # type: ignore[union-attr]

            mock_register.side_effect = _register

            response = await client.post(f"/api/v1/downloads/{download_id}/retry")

        assert response.status_code == 200
        mock_client.add_torrent.assert_awaited_once_with(
            "https://example.com/batman-004.torrent",
            "Batman 004 (2025)",
        )
        download = await _get_download(db_factory, download_id)
        assert download.external_id == "torrent-hash"
        issue = await _get_issue(db_factory, issue_id)
        assert issue.status == IssueStatus.DOWNLOADING

    @pytest.mark.asyncio
    async def test_retry_download_rejects_post_processing_failures(
        self,
        client: AsyncClient,
        db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        issue_id = await _seed_issue(db_factory)
        download_id = await _seed_download(
            db_factory,
            issue_id,
            downloaded_path="/downloads/batman-004.cbz",
            error_message="ComicInfo write failed",
        )

        response = await client.post(f"/api/v1/downloads/{download_id}/retry")

        assert response.status_code == 409
        assert response.json()["detail"] == "Use retry-processing for post-processing failures."

    @pytest.mark.asyncio
    async def test_retry_download_requires_configured_client(
        self,
        client: AsyncClient,
        db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        issue_id = await _seed_issue(db_factory)
        download_id = await _seed_download(db_factory, issue_id, downloaded_path=None)

        with patch(
            "pullbox.composition.providers.register_download_clients",
            new_callable=AsyncMock,
        ):
            response = await client.post(f"/api/v1/downloads/{download_id}/retry")

        assert response.status_code == 503
        assert response.json()["detail"] == "No download client configured for this download type."

    @pytest.mark.asyncio
    async def test_retry_download_rejects_non_failed_rows(
        self,
        client: AsyncClient,
        db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        issue_id = await _seed_issue(db_factory)
        download_id = await _seed_download(
            db_factory,
            issue_id,
            state=DownloadState.COMPLETED,
            error_message=None,
        )

        response = await client.post(f"/api/v1/downloads/{download_id}/retry")

        assert response.status_code == 409
        assert response.json()["detail"] == "Only failed downloads can be retried."


class TestDownloadRouteFunctions:
    @pytest.mark.asyncio
    async def test_queue_history_and_clear_routes(
        self,
        db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        issue_id = await _seed_issue(db_factory)
        await _seed_download(db_factory, issue_id, state=DownloadState.QUEUED)
        await _seed_download(
            db_factory,
            issue_id,
            state=DownloadState.COMPLETED,
            error_message=None,
        )
        await _seed_download(
            db_factory,
            issue_id,
            state=DownloadState.IMPORTED,
            downloaded_path="/downloads/imported.cbz",
            error_message=None,
        )

        async with db_factory() as session:
            queue = await downloads_api.download_queue(object(), session)  # type: ignore[arg-type]
            history = await downloads_api.download_history(object(), session, limit=10, offset=0)  # type: ignore[arg-type]
            deleted_downloads = await downloads_api.clear_download_history(  # type: ignore[arg-type]
                object(),
                session,
            )
            deleted_post_processing = await downloads_api.clear_post_processing_history(  # type: ignore[arg-type]
                object(),
                session,
            )
            await session.commit()

        assert [item.state for item in queue] == [DownloadState.QUEUED]
        assert queue[0].series_title == "Batman"
        assert history.total == 1
        assert history.items[0].series_title == "Batman"
        assert deleted_downloads == {"deleted": 1}
        assert deleted_post_processing == {"deleted": 1}

    @pytest.mark.asyncio
    async def test_retry_processing_route_requeues_failed_downloaded_file(
        self,
        db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        issue_id = await _seed_issue(db_factory)
        download_id = await _seed_download(
            db_factory,
            issue_id,
            downloaded_path="/downloads/batman-004.cbz",
            error_message="File placement failed",
        )
        scheduler = MagicMock()

        async with db_factory() as session:
            with patch("pullbox.core.scheduler.get_scheduler", return_value=scheduler):
                result = await downloads_api.retry_post_processing(  # type: ignore[arg-type]
                    download_id,
                    object(),
                    session,
                )
            await session.commit()

        assert result == {"status": "queued"}
        scheduler.run_task_now.assert_called_once_with("process_completed")
        download = await _get_download(db_factory, download_id)
        assert download.state == DownloadState.COMPLETED

    @pytest.mark.asyncio
    async def test_blocklist_failed_download_route_creates_entry(
        self,
        db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        issue_id = await _seed_issue(db_factory)
        download_id = await _seed_download(
            db_factory,
            issue_id,
            title="Batman 004 (2025) (Digital) (Empire)",
            error_message="CRC failed",
        )

        async with db_factory() as session:
            response = await downloads_api.blocklist_failed_download(  # type: ignore[arg-type]
                download_id,
                object(),
                session,
            )
            await session.commit()

        assert response.release_title == "Batman 004 (2025) (Digital) (Empire)"
        assert response.reason.value == "failed"
        assert response.release_group == "Empire"
        assert response.download_history_id == download_id
        assert response.series_title == "Batman"

    @pytest.mark.asyncio
    async def test_blocklist_failed_download_route_rejects_duplicate(
        self,
        db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        issue_id = await _seed_issue(db_factory)
        download_id = await _seed_download(db_factory, issue_id)

        async with db_factory() as session:
            await downloads_api.blocklist_failed_download(download_id, object(), session)  # type: ignore[arg-type]
            with pytest.raises(Exception) as exc_info:
                await downloads_api.blocklist_failed_download(download_id, object(), session)  # type: ignore[arg-type]

        assert "Release already in blocklist" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_retry_download_route_sends_usenet_and_updates_issue(
        self,
        db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        issue_id = await _seed_issue(db_factory, status=IssueStatus.OWNED)
        download_id = await _seed_download(
            db_factory,
            issue_id,
            downloaded_path=None,
            error_message="Download failed",
            completed_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        mock_client = AsyncMock()
        mock_client.client_type = "sabnzbd"
        mock_client.add_nzb = AsyncMock(return_value="resent-id")

        async with db_factory() as session:
            with patch(
                "pullbox.composition.providers.register_download_clients",
                new_callable=AsyncMock,
            ) as mock_register:

                async def _register(_session: object, registry: object) -> None:
                    registry.register_download_client(1, mock_client)  # type: ignore[union-attr]

                mock_register.side_effect = _register
                result = await downloads_api.retry_download(download_id, object(), session)  # type: ignore[arg-type]
            await session.commit()

        assert result == {"status": "sent"}
        mock_client.add_nzb.assert_awaited_once_with(
            "https://example.com/batman-004.nzb",
            "Batman 004 (2025)",
        )
        download = await _get_download(db_factory, download_id)
        assert download.state == DownloadState.SENT
        assert download.external_id == "resent-id"
        issue = await _get_issue(db_factory, issue_id)
        assert issue.status == IssueStatus.DOWNLOADING

    @pytest.mark.asyncio
    async def test_retry_download_route_sends_torrent(
        self,
        db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        issue_id = await _seed_issue(db_factory)
        download_id = await _seed_download(
            db_factory,
            issue_id,
            client_type=DownloadClientType.QBITTORRENT,
            download_url="https://example.com/batman-004.torrent",
            downloaded_path=None,
            error_message="Cancelled by user",
        )
        mock_client = AsyncMock()
        mock_client.client_type = "qbittorrent"
        mock_client.add_torrent = AsyncMock(return_value="torrent-hash")

        async with db_factory() as session:
            with patch(
                "pullbox.composition.providers.register_download_clients",
                new_callable=AsyncMock,
            ) as mock_register:

                async def _register(_session: object, registry: object) -> None:
                    registry.register_download_client(1, mock_client)  # type: ignore[union-attr]

                mock_register.side_effect = _register
                result = await downloads_api.retry_download(download_id, object(), session)  # type: ignore[arg-type]
            await session.commit()

        assert result == {"status": "sent"}
        mock_client.add_torrent.assert_awaited_once_with(
            "https://example.com/batman-004.torrent",
            "Batman 004 (2025)",
        )

    @pytest.mark.asyncio
    async def test_cancel_download_route_cancels_active_and_deletes_terminal_rows(
        self,
        db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        issue_id = await _seed_issue(db_factory, status=IssueStatus.DOWNLOADING)
        active_id = await _seed_download(
            db_factory,
            issue_id,
            state=DownloadState.DOWNLOADING,
            error_message=None,
        )
        terminal_id = await _seed_download(
            db_factory,
            issue_id,
            title="Old history row",
            state=DownloadState.COMPLETED,
            error_message=None,
        )
        mock_client = AsyncMock()
        mock_client.client_type = "sabnzbd"
        mock_client.remove_download = AsyncMock(return_value=True)

        async with db_factory() as session:
            with (
                patch(
                    "pullbox.composition.providers.register_download_clients",
                    new_callable=AsyncMock,
                ) as mock_register,
                patch("pullbox.tasks.download_task._clear_progress") as clear_progress,
            ):

                async def _register(_session: object, registry: object) -> None:
                    registry.register_download_client(1, mock_client)  # type: ignore[union-attr]

                mock_register.side_effect = _register
                await downloads_api.cancel_download(active_id, object(), session)  # type: ignore[arg-type]
                await downloads_api.cancel_download(terminal_id, object(), session)  # type: ignore[arg-type]
            await session.commit()

        mock_client.remove_download.assert_awaited_once_with("download-ext", delete_files=True)
        clear_progress.assert_called_once_with(active_id)
        download = await _get_download(db_factory, active_id)
        assert download.state == DownloadState.FAILED
        assert download.error_message == "Cancelled by user"
        issue = await _get_issue(db_factory, issue_id)
        assert issue.status == IssueStatus.WANTED
        async with db_factory() as session:
            deleted = await session.get(DownloadHistory, terminal_id)
        assert deleted is None

    @pytest.mark.asyncio
    async def test_route_error_branches_raise_expected_http_errors(
        self,
        db_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        issue_id = await _seed_issue(db_factory)
        failed_no_file_id = await _seed_download(
            db_factory,
            issue_id,
            title="Failed without file",
            downloaded_path=None,
        )
        completed_id = await _seed_download(
            db_factory,
            issue_id,
            title="Completed row",
            state=DownloadState.COMPLETED,
            error_message=None,
        )
        cancelled_id = await _seed_download(
            db_factory,
            issue_id,
            title="Cancelled row",
            error_message="Cancelled by user",
        )
        post_processing_failure_id = await _seed_download(
            db_factory,
            issue_id,
            title="Post processing failure",
            downloaded_path="/downloads/batman-004.cbz",
            error_message="ComicInfo write failed",
        )

        async with db_factory() as session:
            with pytest.raises(NotFoundError):
                await downloads_api.retry_post_processing(999_001, object(), session)  # type: ignore[arg-type]
            with pytest.raises(NotFoundError):
                await downloads_api.blocklist_failed_download(999_002, object(), session)  # type: ignore[arg-type]
            with pytest.raises(NotFoundError):
                await downloads_api.retry_download(999_003, object(), session)  # type: ignore[arg-type]
            with pytest.raises(NotFoundError):
                await downloads_api.cancel_download(999_004, object(), session)  # type: ignore[arg-type]

            with pytest.raises(HTTPException) as retry_processing_error:
                await downloads_api.retry_post_processing(failed_no_file_id, object(), session)  # type: ignore[arg-type]
            with pytest.raises(HTTPException) as blocklist_non_failed_error:
                await downloads_api.blocklist_failed_download(completed_id, object(), session)  # type: ignore[arg-type]
            with pytest.raises(HTTPException) as blocklist_cancelled_error:
                await downloads_api.blocklist_failed_download(cancelled_id, object(), session)  # type: ignore[arg-type]
            with pytest.raises(HTTPException) as retry_non_failed_error:
                await downloads_api.retry_download(completed_id, object(), session)  # type: ignore[arg-type]
            with pytest.raises(HTTPException) as retry_pp_failure_error:
                await downloads_api.retry_download(post_processing_failure_id, object(), session)  # type: ignore[arg-type]
            with (
                patch(
                    "pullbox.composition.providers.register_download_clients",
                    new_callable=AsyncMock,
                ),
                pytest.raises(HTTPException) as retry_no_client_error,
            ):
                await downloads_api.retry_download(failed_no_file_id, object(), session)  # type: ignore[arg-type]

        assert retry_processing_error.value.status_code == 409
        assert blocklist_non_failed_error.value.status_code == 409
        assert blocklist_cancelled_error.value.status_code == 409
        assert retry_non_failed_error.value.status_code == 409
        assert retry_pp_failure_error.value.status_code == 409
        assert retry_no_client_error.value.status_code == 503
