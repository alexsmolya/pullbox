"""Health subject detail presenter builders."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import TYPE_CHECKING

from fastapi import HTTPException

from pullbox.core.duration_format import replace_duration_ms_tokens
from pullbox.models.client import DownloadClientConfig
from pullbox.models.indexer import IndexerConfig
from pullbox.ui.health_check_items import build_health_checks_from_details
from pullbox.ui.health_data import (
    _load_latest_health_subject_summary_rows,
    _parse_health_details_json,
)
from pullbox.ui.health_history_rows import build_health_history_rows
from pullbox.ui.health_placeholder_checks import (
    build_download_client_placeholder_checks,
    build_indexer_placeholder_checks,
    build_prowlarr_placeholder_checks,
)
from pullbox.ui.health_presenters import (
    HealthComponentStatView,
    HealthComponentView,
    _health_card_tone,
    _health_led_tone,
    _health_pill_tone,
    _object_to_int,
)
from pullbox.ui.health_registry_rows import (
    download_client_endpoint_summary,
    health_response_or_dash,
    indexer_content_type_label,
    indexer_endpoint_summary,
    indexer_kind_detail_label,
    load_jackett_route_config,
    load_prowlarr_route_config,
)
from pullbox.ui.health_subject_history import load_health_subject_history

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from pullbox.ui.health_presenters import HealthHistoryRowView
    from pullbox.ui.health_subject_history import HealthSubjectHistoryResult


async def build_download_client_detail_view(
    session: AsyncSession,
    *,
    subject_key: str,
    current_time: datetime,
    history_page: int,
    history_sort: str,
    history_search: str,
    relative_time_label: Callable[[datetime, datetime], str],
    download_client_type_label: Callable[[str], str],
) -> HealthComponentView:
    """Build a detail-page presenter for one download client subject."""
    try:
        config_id = int(subject_key)
    except ValueError as exc:  # pragma: no cover - defensive 404
        raise HTTPException(status_code=404, detail="Download client not found") from exc

    config = await session.get(DownloadClientConfig, config_id)
    if config is None or not config.enabled:
        raise HTTPException(status_code=404, detail="Download client not found")

    latest_rows = await _load_latest_health_subject_summary_rows(session, "download_clients")
    latest_row = latest_rows.get(subject_key)
    details = _parse_health_details_json(getattr(latest_row, "details_json", None))
    checks = (
        build_health_checks_from_details(details)
        if latest_row is not None
        else build_download_client_placeholder_checks()
    )

    subject_history = await load_health_subject_history(
        session,
        component_key="download_clients",
        subject_key=subject_key,
        page=history_page,
        sort=history_sort,
        search=history_search,
    )

    protocol, host, port = download_client_endpoint_summary(config.url)
    version = str(details.get("version") or "").strip() if isinstance(details, Mapping) else ""
    status = latest_row.status.value if latest_row is not None else "unknown"
    message = replace_duration_ms_tokens(
        str(latest_row.message or "Waiting for the next client health check.")
        if latest_row is not None
        else "Waiting for the next client health check."
    )
    response_ms = latest_row.response_time_ms if latest_row is not None else None
    history = build_health_history_rows(
        subject_history.rows,
        key_prefix="download-client",
        current_time=current_time,
        relative_time_label=relative_time_label,
    )

    detail_stats = (
        HealthComponentStatView(label="Status", value_label=message),
        HealthComponentStatView(
            label="Response",
            value_label=health_response_or_dash(response_ms),
        ),
        HealthComponentStatView(
            label="Last Healthy",
            value_label=(
                relative_time_label(subject_history.latest_healthy_at, current_time)
                if isinstance(subject_history.latest_healthy_at, datetime)
                else "—"
            ),
        ),
        HealthComponentStatView(
            label="Consecutive Fails",
            value_label=str(subject_history.consecutive_failures),
        ),
        HealthComponentStatView(label="Host", value_label=host),
        HealthComponentStatView(label="Port", value_label=port),
        HealthComponentStatView(
            label="Protocol",
            value_label=protocol if not version else f"{protocol} · {version}",
        ),
    )

    return HealthComponentView(
        key=subject_key,
        component_key="download_clients",
        display_name=config.name,
        detail_title=f"{config.name.upper()} DETAILS",
        status=status,
        status_label=status.capitalize(),
        pill_tone=_health_pill_tone(status),
        led_tone=_health_led_tone(status),
        card_tone=_health_card_tone(status),
        message=message,
        sublabel=download_client_type_label(config.client_type.value),
        stats=detail_stats[:2],
        detail_stats=detail_stats,
        detail_variant="table",
        checks=checks,
        history=history,
        history_page=subject_history.page,
        history_total_pages=subject_history.total_pages,
        history_total_count=subject_history.total_count,
        history_sort=subject_history.normalized_sort,
        history_search_query=subject_history.normalized_search,
        subject_key=subject_key,
        history_base_path=f"/health/download_clients/{subject_key}",
        back_href="/health/download_clients",
        back_label="Back to download clients",
    )


async def build_indexer_detail_view(
    session: AsyncSession,
    *,
    subject_key: str,
    current_time: datetime,
    history_page: int,
    history_sort: str,
    history_search: str,
    relative_time_label: Callable[[datetime, datetime], str],
) -> HealthComponentView:
    """Build a detail-page presenter for a search proxy or one indexer subject."""
    latest_rows = await _load_latest_health_subject_summary_rows(session, "indexers")
    latest_row = latest_rows.get(subject_key)
    details = _parse_health_details_json(getattr(latest_row, "details_json", None))

    subject_history = await load_health_subject_history(
        session,
        component_key="indexers",
        subject_key=subject_key,
        page=history_page,
        sort=history_sort,
        search=history_search,
    )

    history = build_health_history_rows(
        subject_history.rows,
        key_prefix="indexer",
        current_time=current_time,
        relative_time_label=relative_time_label,
    )

    status = latest_row.status.value if latest_row is not None else "unknown"
    message = replace_duration_ms_tokens(
        str(latest_row.message or "Waiting for the next indexer health check.")
        if latest_row is not None
        else "Waiting for the next indexer health check."
    )
    response_ms = latest_row.response_time_ms if latest_row is not None else None

    if subject_key in {"prowlarr", "jackett"}:
        return await _build_search_proxy_detail_view(
            session,
            subject_key=subject_key,
            current_time=current_time,
            details=details,
            latest_row_exists=latest_row is not None,
            status=status,
            message=message,
            response_ms=response_ms,
            subject_history=subject_history,
            history=history,
            relative_time_label=relative_time_label,
        )

    try:
        config_id = int(subject_key)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Indexer not found") from exc

    config = await session.get(IndexerConfig, config_id)
    if config is None or not config.enabled:
        raise HTTPException(status_code=404, detail="Indexer not found")

    _, host, port = indexer_endpoint_summary(config.url)
    checks = (
        build_health_checks_from_details(details)
        if latest_row is not None
        else build_indexer_placeholder_checks()
    )
    detail_stats = (
        HealthComponentStatView(label="Status", value_label=message),
        HealthComponentStatView(
            label="Response",
            value_label=health_response_or_dash(response_ms),
        ),
        HealthComponentStatView(
            label="Last Healthy",
            value_label=(
                relative_time_label(subject_history.latest_healthy_at, current_time)
                if isinstance(subject_history.latest_healthy_at, datetime)
                else "—"
            ),
        ),
        HealthComponentStatView(
            label="Consecutive Fails",
            value_label=str(subject_history.consecutive_failures),
        ),
        HealthComponentStatView(label="Host", value_label=host),
        HealthComponentStatView(label="Port", value_label=port),
        HealthComponentStatView(
            label="Type",
            value_label=(
                f"{indexer_content_type_label(config.indexer_type.value)}"
                f" · {indexer_kind_detail_label(config.indexer_type.value)}"
            ),
        ),
    )
    return HealthComponentView(
        key=subject_key,
        component_key="indexers",
        display_name=config.name,
        detail_title=f"{config.name.upper()} DETAILS",
        status=status,
        status_label=status.capitalize(),
        pill_tone=_health_pill_tone(status),
        led_tone=_health_led_tone(status),
        card_tone=_health_card_tone(status),
        message=message,
        sublabel=(
            f"{indexer_content_type_label(config.indexer_type.value)}"
            f" · {indexer_kind_detail_label(config.indexer_type.value)}"
        ),
        stats=detail_stats[:2],
        detail_stats=detail_stats,
        detail_variant="table",
        checks=checks,
        history=history,
        history_page=subject_history.page,
        history_total_pages=subject_history.total_pages,
        history_total_count=subject_history.total_count,
        history_sort=subject_history.normalized_sort,
        history_search_query=subject_history.normalized_search,
        subject_key=subject_key,
        history_base_path=f"/health/indexers/{subject_key}",
        back_href="/health/indexers",
        back_label="Back to indexers",
    )


async def _build_search_proxy_detail_view(
    session: AsyncSession,
    *,
    subject_key: str,
    current_time: datetime,
    details: object,
    latest_row_exists: bool,
    status: str,
    message: str,
    response_ms: object,
    subject_history: HealthSubjectHistoryResult,
    history: tuple[HealthHistoryRowView, ...],
    relative_time_label: Callable[[datetime, datetime], str],
) -> HealthComponentView:
    proxy_name = "Prowlarr" if subject_key == "prowlarr" else "Jackett"
    proxy_url = (
        await load_prowlarr_route_config(session)
        if subject_key == "prowlarr"
        else await load_jackett_route_config(session)
    )
    if not proxy_url:
        raise HTTPException(status_code=404, detail=f"{proxy_name} not configured")

    _, host, port = indexer_endpoint_summary(proxy_url)
    checks = (
        build_health_checks_from_details(details)
        if latest_row_exists
        else build_prowlarr_placeholder_checks()
    )
    indexer_count = (
        _object_to_int(details.get("indexer_count")) if isinstance(details, Mapping) else 0
    )
    detail_stats = (
        HealthComponentStatView(label="Status", value_label=message),
        HealthComponentStatView(
            label="Response",
            value_label=health_response_or_dash(response_ms),
        ),
        HealthComponentStatView(
            label="Last Healthy",
            value_label=(
                relative_time_label(subject_history.latest_healthy_at, current_time)
                if isinstance(subject_history.latest_healthy_at, datetime)
                else "—"
            ),
        ),
        HealthComponentStatView(
            label="Consecutive Fails",
            value_label=str(subject_history.consecutive_failures),
        ),
        HealthComponentStatView(label="Host", value_label=host),
        HealthComponentStatView(label="Port", value_label=port),
        HealthComponentStatView(
            label="Indexers",
            value_label=str(indexer_count),
        ),
    )
    return HealthComponentView(
        key=subject_key,
        component_key="indexers",
        display_name=proxy_name,
        detail_title=f"{proxy_name.upper()} DETAILS",
        status=status,
        status_label=status.capitalize(),
        pill_tone=_health_pill_tone(status),
        led_tone=_health_led_tone(status),
        card_tone=_health_card_tone(status),
        message=message,
        sublabel="Search proxy",
        stats=detail_stats[:2],
        detail_stats=detail_stats,
        detail_variant="table",
        checks=checks,
        history=history,
        history_page=subject_history.page,
        history_total_pages=subject_history.total_pages,
        history_total_count=subject_history.total_count,
        history_sort=subject_history.normalized_sort,
        history_search_query=subject_history.normalized_search,
        subject_key=subject_key,
        history_base_path=f"/health/indexers/{subject_key}",
        back_href="/health/indexers",
        back_label="Back to indexers",
    )
