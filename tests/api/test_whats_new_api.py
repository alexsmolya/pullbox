"""Baseline API coverage for the PD-6 What's New surface."""

from __future__ import annotations

import os
import sys
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import pytest
from fastapi import BackgroundTasks

from pullbox.api.v1 import whats_new as whats_new_api
from pullbox.core.exceptions import PullboxError
from pullbox.models.whats_new import WhatsNewCacheKind, WhatsNewReleaseCache
from pullbox.services.auth_service import SESSION_COOKIE_NAME, AuthService
from pullbox.services.whats_new_refresh_queue import RefreshQueueResult, RefreshQueueStatus

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

pytest_plugins = ["conftest_security"]

os.environ.setdefault("PULLBOX_SECRET_KEY", "test-secret-key-for-whats-new-api")

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _csrf_header_for(authenticated_client) -> dict[str, str]:  # type: ignore[no-untyped-def]
    session_token = authenticated_client.cookies.get(SESSION_COOKIE_NAME)
    assert session_token is not None
    csrf_token = AuthService.get_csrf_token_from_session(session_token)
    assert csrf_token is not None
    return {"X-CSRF-Token": csrf_token}


@pytest.mark.asyncio
async def test_whats_new_api_requires_authentication(
    unauthenticated_client,
) -> None:  # type: ignore[no-untyped-def]
    response = await unauthenticated_client.get("/api/v1/whats-new")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_whats_new_api_surface_exists_with_empty_cache_state(
    authenticated_client,
) -> None:  # type: ignore[no-untyped-def]
    response = await authenticated_client.get("/api/v1/whats-new")

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "WHATS_NEW_CACHE_EMPTY",
            "message": "No cached release data is available yet.",
        }
    }


@pytest.mark.asyncio
async def test_whats_new_api_returns_cached_current_week(
    authenticated_client,
    sec_db: async_sessionmaker[AsyncSession],
) -> None:
    fetched_at = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)
    async with sec_db() as session:
        session.add(
            WhatsNewReleaseCache(
                cache_key="current-week:2026-03-11",
                cache_kind=WhatsNewCacheKind.CURRENT_WEEK,
                store_date=date(2026, 3, 11),
                payload={
                    "store_date": "2026-03-11",
                    "count": 1,
                    "last_updated": "2026-03-10T12:15:00+00:00",
                    "issues": [_issue_summary()],
                },
                fetched_at=fetched_at,
                last_successful_refresh_at=fetched_at,
            )
        )
        await session.commit()

    response = await authenticated_client.get("/api/v1/whats-new?date=2026-03-11")

    assert response.status_code == 200
    data = response.json()
    assert data["store_date"] == "2026-03-11"
    assert data["count"] == 1
    assert data["issues"][0]["title"] == "Absolute Flash #1"
    assert data["cache"]["status"] == "stale"
    assert data["cache"]["fetched_at"] == "2026-05-15T12:00:00Z"


@pytest.mark.asyncio
async def test_whats_new_api_allows_nullable_upstream_release_fields(
    authenticated_client,
    sec_db: async_sessionmaker[AsyncSession],
) -> None:
    fetched_at = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)
    async with sec_db() as session:
        session.add(
            WhatsNewReleaseCache(
                cache_key="current-week:2026-03-11",
                cache_kind=WhatsNewCacheKind.CURRENT_WEEK,
                store_date=date(2026, 3, 11),
                payload={
                    "store_date": "2026-03-11",
                    "count": 1,
                    "last_updated": "2026-03-10T12:15:00+00:00",
                    "issues": [
                        _issue_summary(
                            issue_number=None,
                            locg_series_id=None,
                            locg_publisher_id=None,
                            series_locg_series_id=None,
                            series_locg_url=None,
                        )
                    ],
                },
                fetched_at=fetched_at,
                last_successful_refresh_at=fetched_at,
            )
        )
        await session.commit()

    response = await authenticated_client.get("/api/v1/whats-new?date=2026-03-11")

    assert response.status_code == 200
    issue = response.json()["issues"][0]
    assert issue["locg_series_id"] is None
    assert issue["issue_number"] is None
    assert issue["publisher"]["locg_publisher_id"] is None
    assert issue["series"]["locg_series_id"] is None
    assert issue["series"]["locg_url"] is None


@pytest.mark.asyncio
async def test_whats_new_api_uses_latest_current_week_when_date_is_omitted(
    authenticated_client,
    sec_db: async_sessionmaker[AsyncSession],
) -> None:
    fetched_at = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)
    async with sec_db() as session:
        session.add_all(
            [
                WhatsNewReleaseCache(
                    cache_key="current-week:2026-03-04",
                    cache_kind=WhatsNewCacheKind.CURRENT_WEEK,
                    store_date=date(2026, 3, 4),
                    payload={
                        "store_date": "2026-03-04",
                        "count": 1,
                        "last_updated": "2026-03-03T12:15:00+00:00",
                        "issues": [_issue_summary(title="Older Book #1", store_date="2026-03-04")],
                    },
                    fetched_at=fetched_at,
                    last_successful_refresh_at=fetched_at,
                ),
                WhatsNewReleaseCache(
                    cache_key="current-week:2026-03-11",
                    cache_kind=WhatsNewCacheKind.CURRENT_WEEK,
                    store_date=date(2026, 3, 11),
                    payload={
                        "store_date": "2026-03-11",
                        "count": 1,
                        "last_updated": "2026-03-10T12:15:00+00:00",
                        "issues": [_issue_summary(store_date="2026-03-11")],
                    },
                    fetched_at=fetched_at,
                    last_successful_refresh_at=fetched_at,
                ),
            ]
        )
        await session.commit()

    response = await authenticated_client.get("/api/v1/whats-new")

    assert response.status_code == 200
    data = response.json()
    assert data["store_date"] == "2026-03-11"
    assert data["issues"][0]["title"] == "Absolute Flash #1"


@pytest.mark.asyncio
async def test_whats_new_api_returns_cached_upcoming(
    authenticated_client,
    sec_db: async_sessionmaker[AsyncSession],
) -> None:
    fetched_at = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)
    async with sec_db() as session:
        session.add(
            WhatsNewReleaseCache(
                cache_key="upcoming:dc-comics",
                cache_kind=WhatsNewCacheKind.UPCOMING,
                publisher="DC Comics",
                payload={
                    "weeks": [
                        {
                            "store_date": "2026-03-25",
                            "count": 1,
                            "issues": [_issue_summary()],
                        }
                    ],
                    "lookahead_weeks": 2,
                },
                fetched_at=fetched_at,
                last_successful_refresh_at=fetched_at,
            )
        )
        await session.commit()

    response = await authenticated_client.get(
        "/api/v1/whats-new?upcoming=true&publisher=DC%20Comics"
    )

    assert response.status_code == 200
    data = response.json()
    assert data["lookahead_weeks"] == 2
    assert data["weeks"][0]["store_date"] == "2026-03-25"
    assert data["weeks"][0]["issues"][0]["publisher"]["name"] == "DC Comics"
    assert data["cache"]["status"] == "stale"


@pytest.mark.asyncio
async def test_whats_new_api_filters_unscoped_upcoming_cache_by_publisher(
    authenticated_client,
    sec_db: async_sessionmaker[AsyncSession],
) -> None:
    fetched_at = datetime(2026, 5, 15, 12, 0, tzinfo=UTC)
    async with sec_db() as session:
        session.add(
            WhatsNewReleaseCache(
                cache_key="upcoming:all",
                cache_kind=WhatsNewCacheKind.UPCOMING,
                payload={
                    "weeks": [
                        {
                            "store_date": "2026-03-25",
                            "count": 2,
                            "issues": [
                                _issue_summary(publisher_name="DC Comics"),
                                _issue_summary(
                                    title="Something Else #1",
                                    publisher_name="Image Comics",
                                ),
                            ],
                        },
                        {
                            "store_date": "2026-04-01",
                            "count": 1,
                            "issues": [
                                _issue_summary(
                                    title="Image Future #1",
                                    publisher_name="Image Comics",
                                    store_date="2026-04-01",
                                )
                            ],
                        },
                    ],
                    "lookahead_weeks": 2,
                },
                fetched_at=fetched_at,
                last_successful_refresh_at=fetched_at,
            )
        )
        await session.commit()

    response = await authenticated_client.get(
        "/api/v1/whats-new?upcoming=true&publisher=DC%20Comics"
    )

    assert response.status_code == 200
    data = response.json()
    assert data["lookahead_weeks"] == 2
    assert len(data["weeks"]) == 1
    assert data["weeks"][0]["count"] == 1
    assert data["weeks"][0]["issues"][0]["publisher"]["name"] == "DC Comics"
    assert data["weeks"][0]["issues"][0]["title"] == "Absolute Flash #1"


@pytest.mark.asyncio
async def test_whats_new_refresh_surface_requires_csrf(
    authenticated_client,
) -> None:  # type: ignore[no-untyped-def]
    response = await authenticated_client.post("/api/v1/whats-new/refresh")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_whats_new_refresh_surface_exists(
    authenticated_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:  # type: ignore[no-untyped-def]
    class QueuedCoordinator:
        async def queue_refresh(self, _background_tasks: object) -> RefreshQueueResult:
            return RefreshQueueResult(
                status=RefreshQueueStatus.QUEUED,
                message="What's New refresh queued.",
            )

    monkeypatch.setattr(whats_new_api, "refresh_coordinator", QueuedCoordinator())

    response = await authenticated_client.post(
        "/api/v1/whats-new/refresh",
        headers=_csrf_header_for(authenticated_client),
    )

    assert response.status_code == 202
    assert response.json() == {
        "status": "queued",
        "message": "What's New refresh queued.",
    }


@pytest.mark.asyncio
async def test_whats_new_refresh_returns_conflict_when_already_running(
    authenticated_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BusyCoordinator:
        async def queue_refresh(self, _background_tasks: object) -> RefreshQueueResult:
            return RefreshQueueResult(
                status=RefreshQueueStatus.ALREADY_RUNNING,
                message="What's New refresh is already in progress.",
            )

    monkeypatch.setattr(whats_new_api, "refresh_coordinator", BusyCoordinator())

    response = await authenticated_client.post(
        "/api/v1/whats-new/refresh",
        headers=_csrf_header_for(authenticated_client),
    )

    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "WHATS_NEW_REFRESH_IN_PROGRESS",
            "message": "What's New refresh is already in progress.",
        }
    }


@pytest.mark.asyncio
async def test_whats_new_direct_current_week_empty_cache_raises_pullbox_error(
    sec_db: async_sessionmaker[AsyncSession],
) -> None:
    async with sec_db() as session:
        with pytest.raises(PullboxError) as exc:
            await whats_new_api.get_whats_new(
                session,
                object(),  # type: ignore[arg-type]
                store_date=date(2026, 3, 11),
            )

    assert exc.value.code == "WHATS_NEW_CACHE_EMPTY"
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_whats_new_direct_current_week_success_without_date(
    sec_db: async_sessionmaker[AsyncSession],
) -> None:
    fetched_at = datetime.now(UTC)
    async with sec_db() as session:
        session.add(
            WhatsNewReleaseCache(
                cache_key="current-week:2026-03-11",
                cache_kind=WhatsNewCacheKind.CURRENT_WEEK,
                store_date=date(2026, 3, 11),
                payload={
                    "store_date": "2026-03-11",
                    "count": 1,
                    "last_updated": "2026-03-10T12:15:00+00:00",
                    "issues": [_issue_summary(store_date="2026-03-11")],
                },
                fetched_at=fetched_at,
                last_successful_refresh_at=fetched_at,
            )
        )
        await session.flush()

        response = await whats_new_api.get_whats_new(
            session,
            object(),  # type: ignore[arg-type]
        )

    assert response.store_date == date(2026, 3, 11)
    assert response.count == 1


@pytest.mark.asyncio
async def test_whats_new_direct_upcoming_falls_back_to_unscoped_publisher_filter(
    sec_db: async_sessionmaker[AsyncSession],
) -> None:
    fetched_at = datetime.now(UTC)
    async with sec_db() as session:
        session.add(
            WhatsNewReleaseCache(
                cache_key="upcoming:all",
                cache_kind=WhatsNewCacheKind.UPCOMING,
                payload={
                    "weeks": [
                        {
                            "store_date": "2026-03-25",
                            "count": 3,
                            "issues": [
                                _issue_summary(publisher_name="dc comics"),
                                _issue_summary(
                                    title="Image Future #1",
                                    publisher_name="Image Comics",
                                ),
                                "not-an-issue",
                            ],
                        },
                        "not-a-week",
                        {"store_date": "2026-04-01", "issues": "not-a-list"},
                    ],
                    "lookahead_weeks": 2,
                },
                fetched_at=fetched_at,
                last_successful_refresh_at=fetched_at,
            )
        )
        await session.flush()

        response = await whats_new_api.get_whats_new(
            session,
            object(),  # type: ignore[arg-type]
            publisher=" DC Comics ",
            upcoming=True,
        )

    assert response.lookahead_weeks == 2
    assert len(response.weeks) == 1
    assert response.weeks[0].count == 1
    assert response.weeks[0].issues[0].publisher.name == "dc comics"
    assert response.cache.fetched_at == fetched_at


@pytest.mark.asyncio
async def test_whats_new_direct_upcoming_empty_cache_raises_pullbox_error(
    sec_db: async_sessionmaker[AsyncSession],
) -> None:
    async with sec_db() as session:
        with pytest.raises(PullboxError) as exc:
            await whats_new_api.get_whats_new(
                session,
                object(),  # type: ignore[arg-type]
                publisher="DC Comics",
                upcoming=True,
            )

    assert exc.value.code == "WHATS_NEW_CACHE_EMPTY"


def test_filter_upcoming_payload_handles_malformed_weeks_and_publishers() -> None:
    assert whats_new_api._filter_upcoming_payload_by_publisher(
        {"weeks": "not-a-list"},
        "DC Comics",
    ) == {"weeks": []}

    filtered = whats_new_api._filter_upcoming_payload_by_publisher(
        {
            "weeks": [
                {
                    "store_date": "2026-03-25",
                    "issues": [
                        {"publisher": "DC Comics"},
                        {"publisher": {"name": None}},
                        {"publisher": {"name": " DC Comics "}},
                    ],
                }
            ]
        },
        "dc comics",
    )

    assert filtered["weeks"][0]["count"] == 1
    assert filtered["weeks"][0]["issues"] == [{"publisher": {"name": " DC Comics "}}]


@pytest.mark.asyncio
async def test_whats_new_refresh_direct_success_and_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class QueuedCoordinator:
        async def queue_refresh(self, _background_tasks: object) -> RefreshQueueResult:
            return RefreshQueueResult(
                status=RefreshQueueStatus.QUEUED,
                message="queued",
            )

    class BusyCoordinator:
        async def queue_refresh(self, _background_tasks: object) -> RefreshQueueResult:
            return RefreshQueueResult(
                status=RefreshQueueStatus.ALREADY_RUNNING,
                message="busy",
            )

    monkeypatch.setattr(whats_new_api, "refresh_coordinator", QueuedCoordinator())
    queued = await whats_new_api.refresh_whats_new(
        BackgroundTasks(),
        object(),  # type: ignore[arg-type]
    )
    assert queued == {"status": "queued", "message": "queued"}

    monkeypatch.setattr(whats_new_api, "refresh_coordinator", BusyCoordinator())
    with pytest.raises(PullboxError) as exc:
        await whats_new_api.refresh_whats_new(
            BackgroundTasks(),
            object(),  # type: ignore[arg-type]
        )

    assert exc.value.code == "WHATS_NEW_REFRESH_IN_PROGRESS"


def _issue_summary(
    *,
    title: str = "Absolute Flash #1",
    store_date: str = "2026-03-25",
    publisher_name: str = "DC Comics",
    locg_series_id: int | None = 180901,
    issue_number: str | None = "1",
    locg_publisher_id: int | None = 501,
    series_locg_series_id: int | None = 180901,
    series_locg_url: str | None = (
        "https://leagueofcomicgeeks.com/comics/series/180901/absolute-flash"
    ),
) -> dict[str, object]:
    return {
        "locg_issue_id": 1514020,
        "locg_series_id": locg_series_id,
        "locg_url": "https://leagueofcomicgeeks.com/comic/1514020/absolute-flash-1",
        "title": title,
        "display_title": f"{title} Cover A",
        "issue_number": issue_number,
        "price": 4.99,
        "currency": "USD",
        "store_date": store_date,
        "cover_url": "https://cdn.example.com/1514020.jpg",
        "variant_count": 9,
        "community_rating": None,
        "community_counts": {
            "pull": 3100,
            "have": 0,
            "read": 0,
            "want": 1400,
            "pick": 260,
        },
        "publisher": {
            "name": publisher_name,
            "locg_publisher_id": locg_publisher_id,
            "excluded": False,
            "excluded_reason": None,
        },
        "series": {
            "title": "Absolute Flash",
            "locg_series_id": series_locg_series_id,
            "locg_url": series_locg_url,
            "start_year": 2026,
            "volume": "2026",
        },
    }
