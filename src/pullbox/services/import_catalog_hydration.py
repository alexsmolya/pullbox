"""Background catalog hydration helpers for targeted-first imports."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog

from pullbox.models.series import IssueCatalogState, Series

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = structlog.get_logger(__name__)

catalog_hydration_tasks: set[asyncio.Task[None]] = set()
_catalog_hydration_semaphore: asyncio.Semaphore | None = None
_catalog_hydration_semaphore_loop: asyncio.AbstractEventLoop | None = None


@dataclass(frozen=True, slots=True)
class CatalogHydrationPlan:
    comicvine_id: int
    library_root_id: int | None
    search_on_add: bool


def reset_catalog_hydration_gate() -> None:
    """Reset the app-local hydration gate for tests and loop restarts."""
    global _catalog_hydration_semaphore, _catalog_hydration_semaphore_loop
    _catalog_hydration_semaphore = None
    _catalog_hydration_semaphore_loop = None


def schedule_catalog_hydration(
    session_factory: async_sessionmaker[AsyncSession] | None,
    *,
    series_service: Any,
    series_id: int,
    search_on_add: bool,
) -> None:
    """Queue full catalog hydration after the Step 4 file-placement hot path."""
    prefetch_descriptor = getattr(type(series_service), "prefetch_comicvine_bundle", None)
    add_prefetched_descriptor = getattr(
        type(series_service),
        "add_from_comicvine_prefetched",
        None,
    )
    if prefetch_descriptor is None or add_prefetched_descriptor is None:
        return
    if session_factory is None:
        return

    prefetch_comicvine_bundle = prefetch_descriptor.__get__(
        series_service,
        type(series_service),
    )
    add_from_comicvine_prefetched = add_prefetched_descriptor.__get__(
        series_service,
        type(series_service),
    )

    async def run_hydration() -> None:
        async with catalog_hydration_gate():
            try:
                await run_catalog_hydration(
                    session_factory,
                    series_id=series_id,
                    search_on_add=search_on_add,
                    prefetch_comicvine_bundle=prefetch_comicvine_bundle,
                    add_from_comicvine_prefetched=add_from_comicvine_prefetched,
                )
            except Exception as exc:
                await mark_catalog_hydration_failed(
                    session_factory,
                    series_id=series_id,
                    error=str(exc),
                )
                logger.warning(
                    "import_catalog_hydration_failed",
                    series_id=series_id,
                    error=str(exc),
                )

    task = asyncio.create_task(run_hydration())
    catalog_hydration_tasks.add(task)
    task.add_done_callback(catalog_hydration_tasks.discard)


def catalog_hydration_gate() -> asyncio.Semaphore:
    """Return the app-local lane for background catalog hydration."""
    global _catalog_hydration_semaphore, _catalog_hydration_semaphore_loop

    loop = asyncio.get_running_loop()
    if _catalog_hydration_semaphore is None or _catalog_hydration_semaphore_loop is not loop:
        _catalog_hydration_semaphore = asyncio.Semaphore(1)
        _catalog_hydration_semaphore_loop = loop
    return _catalog_hydration_semaphore


async def run_catalog_hydration(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    series_id: int,
    search_on_add: bool,
    prefetch_comicvine_bundle: Callable[[int], Awaitable[tuple[Any, list[Any]]]],
    add_from_comicvine_prefetched: Callable[..., Awaitable[Series]],
) -> None:
    plan = await load_catalog_hydration_plan(
        session_factory,
        series_id=series_id,
        search_on_add=search_on_add,
    )
    if plan is None:
        return

    # ComicVine can be slow for giant series. Fetch outside any DB session so
    # the UI and active import writer keep access to the pool while we wait.
    series_meta, issue_summaries = await prefetch_comicvine_bundle(plan.comicvine_id)

    async with session_factory() as hydrate_session:
        await add_from_comicvine_prefetched(
            hydrate_session,
            comicvine_id=plan.comicvine_id,
            library_root_id=plan.library_root_id,
            search_on_add=plan.search_on_add,
            series_meta=series_meta,
            issue_summaries=issue_summaries,
        )
        await hydrate_session.commit()


async def load_catalog_hydration_plan(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    series_id: int,
    search_on_add: bool,
) -> CatalogHydrationPlan | None:
    async with session_factory() as session:
        series = await session.get(Series, series_id)
        if series is None:
            return None
        if series.comicvine_id is None:
            msg = "Series has no ComicVine ID"
            raise ValueError(msg)

        series.issue_catalog_state = IssueCatalogState.HYDRATING
        series.issue_catalog_error = None
        series.issue_catalog_last_synced_at = None
        series.issue_catalog_last_checked_at = None
        await session.commit()

        return CatalogHydrationPlan(
            comicvine_id=int(series.comicvine_id),
            library_root_id=series.library_root_id,
            search_on_add=search_on_add,
        )


async def mark_catalog_hydration_failed(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    series_id: int,
    error: str,
) -> None:
    async with session_factory() as session:
        series = await session.get(Series, series_id)
        if series is None:
            return
        series.issue_catalog_state = IssueCatalogState.FAILED
        series.issue_catalog_error = error
        series.issue_catalog_last_synced_at = None
        series.issue_catalog_last_checked_at = None
        await session.commit()
