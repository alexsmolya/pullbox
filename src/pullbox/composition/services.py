"""Service composition helpers shared by API, UI, and task entrypoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pullbox.composition import providers
from pullbox.composition.events import build_domain_event_bus, build_scoped_event_bus
from pullbox.config import get_settings
from pullbox.core.comicvine_key import get_comicvine_api_key
from pullbox.models.config import SystemConfig
from pullbox.providers.metadata.comicvine import ComicVineProvider
from pullbox.services import download_service
from pullbox.services.cover_resolver import resolve_covers_dir
from pullbox.services.import_provider_cache import build_persistent_import_metadata_provider
from pullbox.services.import_service import ImportService
from pullbox.services.matching_service import MatchingService
from pullbox.services.metadata_service import MetadataService
from pullbox.services.series_service import SeriesService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from pullbox.models.indexer import IndexerConfig
    from pullbox.providers.base import ProviderRegistry
    from pullbox.services.download_service import DownloadService


async def build_metadata_service(session: AsyncSession) -> MetadataService:
    """Construct a MetadataService using persisted ComicVine settings."""
    settings = get_settings()
    api_key = await get_comicvine_api_key(session)
    provider = ComicVineProvider(api_key=api_key)
    covers_dir = await resolve_covers_dir(session)
    return MetadataService(
        provider=provider,
        covers_dir=covers_dir,
        refresh_days=settings.metadata_refresh_days,
    )


def build_series_service(metadata_service: MetadataService) -> SeriesService:
    """Construct a SeriesService for domain flows with shared side effects."""
    return SeriesService(metadata_service=metadata_service, event_bus=build_domain_event_bus())


async def build_domain_series_service(session: AsyncSession) -> SeriesService:
    """Construct a SeriesService using persisted metadata settings and domain events."""
    return build_series_service(await build_metadata_service(session))


def build_matching_service() -> MatchingService:
    """Construct a MatchingService for domain flows with shared side effects."""
    return MatchingService(event_bus=build_domain_event_bus())


async def build_import_service(
    session: AsyncSession,
    *,
    min_burst_limit: int | None = None,
) -> ImportService:
    """Construct an ImportService using persisted ComicVine settings."""
    settings = get_settings()
    api_key = await get_comicvine_api_key(session)
    persisted_rate_config = await session.get(SystemConfig, "comicvine_rate_limit_per_second")
    persisted_rate_value: str | None = None
    if persisted_rate_config is not None:
        candidate_value = getattr(persisted_rate_config, "value", None)
        if isinstance(candidate_value, str | int | float):
            persisted_rate_value = str(candidate_value).strip()

    if persisted_rate_value:
        try:
            burst_limit = max(1, min(int(persisted_rate_value), 10))
        except ValueError:
            burst_limit = 1
    else:
        burst_limit = 1

    if min_burst_limit is not None:
        burst_limit = max(burst_limit, max(1, min(int(min_burst_limit), 10)))

    rate_limit = max(1, int(getattr(settings, "comicvine_rate_limit", 200)))

    provider = ComicVineProvider(
        api_key=api_key or "",
        rate_limit=rate_limit,
        burst_limit=burst_limit,
    )
    provider = build_persistent_import_metadata_provider(session, provider)
    metadata_svc = MetadataService(
        provider,
        covers_dir=await resolve_covers_dir(session),
        refresh_days=settings.metadata_refresh_days,
    )
    event_bus = build_scoped_event_bus()
    series_svc = SeriesService(metadata_svc, event_bus)

    return ImportService(
        series_service=series_svc,
        metadata_service=metadata_svc,
        event_bus=event_bus,
    )


def build_import_control_service() -> ImportService:
    """Construct an ImportService for DB-only import review/control helpers."""
    return ImportService(
        series_service=None,  # type: ignore[arg-type]
        metadata_service=None,  # type: ignore[arg-type]
        event_bus=None,  # type: ignore[arg-type]
    )


def build_download_service(registry: ProviderRegistry) -> DownloadService:
    """Construct a DownloadService using the shared domain event bus."""
    return download_service.DownloadService(registry=registry, event_bus=build_domain_event_bus())


async def build_domain_download_service(
    session: AsyncSession,
) -> tuple[DownloadService, dict[int, IndexerConfig]] | None:
    """Build a registry-backed DownloadService for route/task domain flows."""
    built = await providers.build_registry(session)
    if built is None:
        return None

    registry, indexer_configs = built
    return build_download_service(registry), indexer_configs
