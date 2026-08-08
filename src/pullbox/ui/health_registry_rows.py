"""Health registry row loading for download clients and indexers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from sqlalchemy import func, select

from pullbox.models.client import DownloadClientConfig
from pullbox.models.config import SystemConfig
from pullbox.models.direct_acquisition import DirectHostConfig, DirectProviderConfig
from pullbox.models.indexer import IndexerConfig
from pullbox.ui.health_data import (
    _load_latest_health_subject_summary_rows,
    _parse_health_details_json,
)
from pullbox.ui.health_presenters import (
    HealthSubjectSummaryView,
    _health_led_tone,
    _health_pill_tone,
    _health_response_label,
    _object_to_int,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession


def download_client_endpoint_summary(url: str) -> tuple[str, str, str]:
    """Return protocol, host, and port labels for a client URL."""
    parsed = urlparse(url)
    scheme = (parsed.scheme or "http").lower()
    host = parsed.hostname or "—"
    port = str(parsed.port) if parsed.port is not None else ("443" if scheme == "https" else "80")
    return scheme.upper(), host, port


def health_response_or_dash(response_ms: object) -> str:
    """Format a response time unless it is missing or effectively unmeasured."""
    if not isinstance(response_ms, int | float) or float(response_ms) <= 0:
        return "—"
    return _health_response_label(response_ms)


async def load_prowlarr_route_config(session: AsyncSession) -> str | None:
    """Return the configured Prowlarr URL when both URL and API key are present."""
    rows = (
        (
            await session.execute(
                select(SystemConfig).where(
                    SystemConfig.key.in_(("prowlarr_url", "prowlarr_api_key"))
                )
            )
        )
        .scalars()
        .all()
    )
    values = {row.key: row.value for row in rows}
    url = str(values.get("prowlarr_url") or "").strip()
    api_key = str(values.get("prowlarr_api_key") or "").strip()
    if not url or not api_key:
        return None
    return url


def indexer_endpoint_summary(url: str) -> tuple[str, str, str]:
    """Return protocol, host, and port labels for an indexer URL."""
    return download_client_endpoint_summary(url)


def indexer_kind_detail_label(indexer_type: str) -> str:
    """Return the API family label shown under an indexer name."""
    labels = {
        "newznab": "Newznab",
        "torznab": "Torznab",
    }
    return labels.get(indexer_type, indexer_type.replace("_", " ").title())


def indexer_content_type_label(indexer_type: str) -> str:
    """Return the content family label shown in the Type column."""
    labels = {
        "newznab": "Usenet",
        "torznab": "Torrent",
    }
    return labels.get(indexer_type, indexer_type.replace("_", " ").title())


async def build_download_client_registry_rows(
    session: AsyncSession,
    *,
    current_time: datetime,
    relative_time_label: Callable[[datetime, datetime], str],
    download_client_type_label: Callable[[str], str],
) -> tuple[HealthSubjectSummaryView, ...]:
    """Build the Download Clients registry rows for the list-style health page."""
    latest_rows = await _load_latest_health_subject_summary_rows(session, "download_clients")
    configs = (
        (
            await session.execute(
                select(DownloadClientConfig)
                .where(DownloadClientConfig.enabled.is_(True))
                .order_by(func.lower(DownloadClientConfig.name))
            )
        )
        .scalars()
        .all()
    )
    direct_providers = (
        (
            await session.execute(
                select(DirectProviderConfig)
                .where(DirectProviderConfig.enabled.is_(True))
                .order_by(DirectProviderConfig.priority, DirectProviderConfig.display_name)
            )
        )
        .scalars()
        .all()
    )
    artifact_hosts = (
        (
            await session.execute(
                select(DirectHostConfig)
                .where(DirectHostConfig.enabled.is_(True))
                .order_by(DirectHostConfig.preference, DirectHostConfig.host_kind)
            )
        )
        .scalars()
        .all()
    )

    rows: list[HealthSubjectSummaryView] = []
    for config in configs:
        subject_key = str(config.id)
        latest_row = latest_rows.get(subject_key)
        protocol, host, port = download_client_endpoint_summary(config.url)
        details = _parse_health_details_json(getattr(latest_row, "details_json", None))
        version = str(details.get("version") or "").strip() if isinstance(details, Mapping) else ""
        status = latest_row.status.value if latest_row is not None else "unknown"
        rows.append(
            HealthSubjectSummaryView(
                key=subject_key,
                display_name=config.name,
                kind_label=download_client_type_label(config.client_type.value),
                detail_label=(f"{protocol} · {host}:{port}" + (f" · {version}" if version else "")),
                response_label=(
                    health_response_or_dash(latest_row.response_time_ms)
                    if latest_row is not None
                    else "—"
                ),
                last_check_label=(
                    relative_time_label(latest_row.checked_at, current_time)
                    if latest_row is not None
                    else "—"
                ),
                status_label=status.capitalize(),
                pill_tone=_health_pill_tone(status),
                led_tone=_health_led_tone(status),
                href=f"/health/download_clients/{subject_key}",
            )
        )

    for config in direct_providers:
        subject_key = f"direct-provider:{config.id}"
        latest_row = latest_rows.get(subject_key)
        protocol, host, port = download_client_endpoint_summary(config.endpoint)
        status = latest_row.status.value if latest_row is not None else "unknown"
        rows.append(
            HealthSubjectSummaryView(
                key=subject_key,
                display_name=config.display_name,
                kind_label="Direct Provider",
                detail_label=f"{protocol} · {host}:{port}",
                response_label="—",
                last_check_label=(
                    relative_time_label(latest_row.checked_at, current_time)
                    if latest_row is not None
                    else "—"
                ),
                status_label=status.capitalize(),
                pill_tone=_health_pill_tone(status),
                led_tone=_health_led_tone(status),
                href="/settings?tab=direct",
            )
        )

    for config in artifact_hosts:
        subject_key = f"artifact-host:{config.host_kind.value}"
        latest_row = latest_rows.get(subject_key)
        status = latest_row.status.value if latest_row is not None else "unknown"
        rows.append(
            HealthSubjectSummaryView(
                key=subject_key,
                display_name=config.host_kind.value.replace("_", " ").title(),
                kind_label="Artifact Host",
                detail_label=f"Preference {config.preference}",
                response_label="—",
                last_check_label=(
                    relative_time_label(latest_row.checked_at, current_time)
                    if latest_row is not None
                    else "—"
                ),
                status_label=status.capitalize(),
                pill_tone=_health_pill_tone(status),
                led_tone=_health_led_tone(status),
                href="/settings?tab=direct",
            )
        )
    return tuple(rows)


async def build_indexer_registry_rows(
    session: AsyncSession,
    *,
    current_time: datetime,
    relative_time_label: Callable[[datetime, datetime], str],
) -> tuple[HealthSubjectSummaryView | None, tuple[HealthSubjectSummaryView, ...]]:
    """Build the split proxy/indexer registry rows for the indexers page."""
    latest_rows = await _load_latest_health_subject_summary_rows(session, "indexers")
    prowlarr_url = await load_prowlarr_route_config(session)
    prowlarr_row: HealthSubjectSummaryView | None = None

    if prowlarr_url:
        latest_row = latest_rows.get("prowlarr")
        protocol, host, port = indexer_endpoint_summary(prowlarr_url)
        details = _parse_health_details_json(getattr(latest_row, "details_json", None))
        indexer_count = (
            _object_to_int(details.get("indexer_count")) if isinstance(details, Mapping) else 0
        )
        status = latest_row.status.value if latest_row is not None else "unknown"
        prowlarr_row = HealthSubjectSummaryView(
            key="prowlarr",
            display_name="Prowlarr",
            kind_label="Proxy",
            detail_label=(
                f"{protocol} · {host}:{port}"
                + (f" · {indexer_count} indexers" if indexer_count else "")
            ),
            response_label=(
                health_response_or_dash(latest_row.response_time_ms)
                if latest_row is not None
                else "—"
            ),
            last_check_label=(
                relative_time_label(latest_row.checked_at, current_time)
                if latest_row is not None
                else "—"
            ),
            status_label=status.capitalize(),
            pill_tone=_health_pill_tone(status),
            led_tone=_health_led_tone(status),
            href="/health/indexers/prowlarr",
        )

    configs = (
        (
            await session.execute(
                select(IndexerConfig)
                .where(
                    IndexerConfig.enabled.is_(True),
                    IndexerConfig.manager_available.is_(True),
                )
                .order_by(func.lower(IndexerConfig.name))
            )
        )
        .scalars()
        .all()
    )

    rows: list[HealthSubjectSummaryView] = []
    for config in configs:
        subject_key = str(config.id)
        latest_row = latest_rows.get(subject_key)
        status = latest_row.status.value if latest_row is not None else "unknown"
        rows.append(
            HealthSubjectSummaryView(
                key=subject_key,
                display_name=config.name,
                kind_label=indexer_content_type_label(config.indexer_type.value),
                detail_label=indexer_kind_detail_label(config.indexer_type.value),
                response_label=(
                    health_response_or_dash(latest_row.response_time_ms)
                    if latest_row is not None
                    else "—"
                ),
                last_check_label=(
                    relative_time_label(latest_row.checked_at, current_time)
                    if latest_row is not None
                    else "—"
                ),
                status_label=status.capitalize(),
                pill_tone=_health_pill_tone(status),
                led_tone=_health_led_tone(status),
                href=f"/health/indexers/{subject_key}",
            )
        )

    return prowlarr_row, tuple(rows)
