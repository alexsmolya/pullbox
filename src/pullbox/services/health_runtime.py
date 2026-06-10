"""Shared health refresh runner and bootstrap helpers.

This module centralizes health refresh orchestration so scheduled checks and
manual UI/API-triggered refreshes share the same dependency bootstrap and
runtime serialization behavior.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

from pullbox.config import get_settings
from pullbox.core.comicvine_key import get_comicvine_api_key
from pullbox.core.log_deduper import log_deduped_warning
from pullbox.core.scheduler import get_scheduler
from pullbox.database import get_session_factory
from pullbox.providers.base import ProviderRegistry
from pullbox.providers.metadata.comicvine import ComicVineProvider
from pullbox.services.health_service import CheckOutcome, HealthService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

_health_refresh_lock = asyncio.Lock()


def _needs_indexers(component: str | None) -> bool:
    return component in {None, "indexers"}


def _needs_download_clients(component: str | None) -> bool:
    return component in {None, "download_clients"}


def _needs_comicvine(component: str | None) -> bool:
    return component in {None, "comicvine"}


async def build_health_service(
    session: AsyncSession,
    *,
    component: str | None = None,
) -> HealthService:
    """Build a HealthService with only the dependencies a refresh needs."""
    from pullbox.composition.providers import register_download_clients, register_indexers

    settings = get_settings()
    scheduler = get_scheduler()
    bootstrap_errors: dict[str, list[dict[str, str]]] = {}
    registry: ProviderRegistry | None = None

    if any(
        (
            _needs_indexers(component),
            _needs_download_clients(component),
            _needs_comicvine(component),
        )
    ):
        registry = ProviderRegistry()

    if registry is not None and _needs_indexers(component):
        try:
            await register_indexers(session, registry)
        except Exception as exc:
            log_deduped_warning(
                logger,
                "health_indexer_registry_skipped",
                key=(
                    "health_indexer_registry_skipped",
                    component,
                    exc.__class__.__name__,
                    str(exc),
                ),
                component=component,
                error=str(exc),
            )

    if registry is not None and _needs_download_clients(component):
        try:
            download_client_errors = await register_download_clients(session, registry)
            if download_client_errors:
                bootstrap_errors["download_clients"] = download_client_errors
        except Exception as exc:
            log_deduped_warning(
                logger,
                "health_download_client_registry_skipped",
                key=(
                    "health_download_client_registry_skipped",
                    component,
                    exc.__class__.__name__,
                    str(exc),
                ),
                component=component,
                error=str(exc),
            )
            bootstrap_errors["download_clients"] = [
                {
                    "name": "Download clients",
                    "status": "unhealthy",
                    "message": "Configuration error: download clients could not be loaded.",
                }
            ]

    if registry is not None and _needs_comicvine(component):
        try:
            api_key = await get_comicvine_api_key(session)
        except Exception as exc:
            log_deduped_warning(
                logger,
                "health_comicvine_provider_skipped",
                key=(
                    "health_comicvine_provider_skipped",
                    component,
                    exc.__class__.__name__,
                    str(exc),
                ),
                component=component,
                error=str(exc),
            )
            api_key = ""

        if api_key:
            try:
                provider = ComicVineProvider(api_key=api_key)
                registry.register_metadata_provider("comicvine", provider)
            except Exception as exc:
                log_deduped_warning(
                    logger,
                    "health_comicvine_provider_registration_failed",
                    key=(
                        "health_comicvine_provider_registration_failed",
                        component,
                        exc.__class__.__name__,
                        str(exc),
                    ),
                    component=component,
                    error=str(exc),
                )

    return HealthService(
        settings=settings,
        registry=registry,
        scheduler=scheduler,
        bootstrap_errors=bootstrap_errors,
    )


async def run_health_refresh(component: str | None = None) -> list[CheckOutcome]:
    """Run a health refresh with serialized execution and committed results."""
    async with _health_refresh_lock:
        factory = get_session_factory()
        async with factory() as session:
            service = await build_health_service(session, component=component)
            if component is None:
                outcomes = await service.run_all_checks(session)
            else:
                outcomes = await service.run_check(session, component)
            await session.commit()
            return outcomes
