"""Indexer-specific health check implementation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from pullbox.models.health import HealthStatus
from pullbox.services.health_helpers import (
    _STATUS_PRECEDENCE,
    _indexer_content_type_label,
    _indexer_endpoint_details,
    _indexer_failure_kind,
    _indexer_kind_label,
    _latency_message,
    _serialize_indexer_summary,
    _serialize_sub_check,
    _status_for_latency,
)
from pullbox.services.health_types import CheckOutcome, SubCheckOutcome

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

    from pullbox.models.indexer import IndexerConfig
    from pullbox.services.direct_resolver_service import NativeResolverOption

_INDEXER_LATENCY_DEGRADED_MS = 1000.0
_INDEXER_LATENCY_UNHEALTHY_MS = 5000.0


async def check_indexers(
    session: AsyncSession,
    *,
    load_prowlarr_subject_config: Callable[
        [AsyncSession],
        Awaitable[tuple[str | None, str | None]],
    ],
    load_jackett_subject_config: Callable[
        [AsyncSession],
        Awaitable[tuple[str | None, str | None]],
    ],
    check_prowlarr_subject: Callable[..., Awaitable[CheckOutcome]],
    check_jackett_subject: Callable[..., Awaitable[CheckOutcome]],
    check_indexer_subject: Callable[
        [IndexerConfig, Sequence[NativeResolverOption]],
        Awaitable[CheckOutcome],
    ],
) -> list[CheckOutcome]:
    """Test configured search managers and enabled indexers as one component."""
    from pullbox.models.indexer import IndexerConfig

    result = await session.execute(
        select(IndexerConfig)
        .where(
            IndexerConfig.enabled.is_(True),
            IndexerConfig.manager_available.is_(True),
        )
        .order_by(func.lower(IndexerConfig.name))
    )
    indexer_configs = list(result.scalars().all())
    prowlarr_url, prowlarr_api_key = await load_prowlarr_subject_config(session)
    jackett_url, jackett_api_key = await load_jackett_subject_config(session)

    if not indexer_configs and not any(
        (prowlarr_url and prowlarr_api_key, jackett_url and jackett_api_key)
    ):
        return [
            CheckOutcome(
                component="indexers",
                check_name="connectivity",
                status=HealthStatus.UNKNOWN,
                message="Not configured",
                actionable_guidance=(
                    "Configure a search manager or at least one indexer in Settings > Indexers."
                ),
            )
        ]

    subject_outcomes: list[CheckOutcome] = []
    summary_checks: list[dict[str, Any]] = []
    flagged_names: list[str] = []
    healthy_count = 0
    total_ms = 0.0
    proxy_count = 0
    proxy_outcome: CheckOutcome | None = None
    prowlarr_blocks_indexers = False
    prowlarr_skipped_count = 0
    jackett_outcome: CheckOutcome | None = None
    jackett_blocks_indexers = False
    jackett_skipped_count = 0

    if prowlarr_url and prowlarr_api_key:
        proxy_count = 1
        proxy_outcome = await check_prowlarr_subject(
            url=prowlarr_url,
            api_key=prowlarr_api_key,
        )
        subject_outcomes.append(proxy_outcome)
        summary_checks.append(_serialize_indexer_summary(proxy_outcome))
        total_ms += proxy_outcome.response_time_ms
        if proxy_outcome.status == HealthStatus.HEALTHY:
            healthy_count += 1
        else:
            flagged_names.append("Prowlarr")
        prowlarr_blocks_indexers = not _prowlarr_allows_indexer_checks(proxy_outcome)

    if jackett_url and jackett_api_key:
        proxy_count += 1
        jackett_outcome = await check_jackett_subject(
            url=jackett_url,
            api_key=jackett_api_key,
        )
        subject_outcomes.append(jackett_outcome)
        summary_checks.append(_serialize_indexer_summary(jackett_outcome))
        total_ms += jackett_outcome.response_time_ms
        if jackett_outcome.status == HealthStatus.HEALTHY:
            healthy_count += 1
        else:
            flagged_names.append("Jackett")
        jackett_blocks_indexers = not _jackett_allows_indexer_checks(jackett_outcome)

    from pullbox.models.indexer import IndexerSource
    from pullbox.services.direct_resolver_service import (
        build_manual_torznab_resolver_options,
    )

    for config in indexer_configs:
        is_prowlarr_managed = str(config.source) == IndexerSource.PROWLARR
        if prowlarr_blocks_indexers and proxy_outcome is not None and is_prowlarr_managed:
            outcome = _skipped_indexer_subject(config, proxy_outcome, manager_name="Prowlarr")
            subject_outcomes.append(outcome)
            summary_checks.append(_serialize_indexer_summary(outcome))
            prowlarr_skipped_count += 1
            continue
        is_jackett_managed = str(config.source) == IndexerSource.JACKETT
        if jackett_blocks_indexers and jackett_outcome is not None and is_jackett_managed:
            outcome = _skipped_indexer_subject(config, jackett_outcome, manager_name="Jackett")
            subject_outcomes.append(outcome)
            summary_checks.append(_serialize_indexer_summary(outcome))
            jackett_skipped_count += 1
            continue

        resolver_options = await build_manual_torznab_resolver_options(session, config)
        outcome = await check_indexer_subject(config, resolver_options)
        subject_outcomes.append(outcome)
        summary_checks.append(_serialize_indexer_summary(outcome))
        total_ms += outcome.response_time_ms
        if outcome.status == HealthStatus.HEALTHY:
            healthy_count += 1
        else:
            flagged_names.append(config.name)

    total = len(subject_outcomes)
    indexer_count = len(indexer_configs)

    if (
        prowlarr_blocks_indexers
        and proxy_outcome is not None
        and prowlarr_skipped_count == indexer_count
        and healthy_count == 0
    ):
        component_status = proxy_outcome.status
        message = f"Prowlarr unavailable; skipped {indexer_count} indexer check(s)"
        guidance = (
            proxy_outcome.actionable_guidance
            or "Restore Prowlarr before checking individual indexers."
        )
    elif (
        jackett_blocks_indexers
        and jackett_outcome is not None
        and jackett_skipped_count == indexer_count
        and healthy_count == 0
    ):
        component_status = jackett_outcome.status
        message = f"Jackett unavailable; skipped {indexer_count} indexer check(s)"
        guidance = (
            jackett_outcome.actionable_guidance
            or "Restore Jackett before checking individual indexers."
        )
    elif flagged_names and healthy_count == 0:
        component_status = HealthStatus.UNHEALTHY
        message = "All indexer services unreachable"
        guidance = (
            "Verify Prowlarr, indexer URLs, API keys, and network connectivity "
            "in Settings > Indexers."
        )
    elif flagged_names:
        component_status = HealthStatus.DEGRADED
        message = f"{len(flagged_names)} of {total} service(s) need attention"
        guidance = f"Review {', '.join(flagged_names)} in Settings > Indexers."
    elif proxy_count == 2 and indexer_count:
        component_status = HealthStatus.HEALTHY
        message = "Prowlarr, Jackett, and all indexers reachable"
        guidance = ""
    elif prowlarr_url and prowlarr_api_key and indexer_count:
        component_status = HealthStatus.HEALTHY
        message = "Prowlarr and all indexers reachable"
        guidance = ""
    elif jackett_url and jackett_api_key and indexer_count:
        component_status = HealthStatus.HEALTHY
        message = "Jackett and all indexers reachable"
        guidance = ""
    elif prowlarr_url and prowlarr_api_key:
        component_status = HealthStatus.HEALTHY
        message = "Prowlarr reachable"
        guidance = ""
    elif jackett_url and jackett_api_key:
        component_status = HealthStatus.HEALTHY
        message = "Jackett reachable"
        guidance = ""
    else:
        component_status = HealthStatus.HEALTHY
        message = "All indexers reachable"
        guidance = ""

    return [
        CheckOutcome(
            component="indexers",
            check_name="connectivity",
            status=component_status,
            message=message,
            details={
                "checks": summary_checks,
                "proxy_count": proxy_count,
                "indexer_count": indexer_count,
            },
            response_time_ms=total_ms,
            actionable_guidance=guidance,
        ),
        *subject_outcomes,
    ]


def _prowlarr_allows_indexer_checks(proxy_outcome: CheckOutcome) -> bool:
    """Return True when Prowlarr connectivity and auth are good enough for fan-out."""
    subcheck_statuses = {check.check_name: check.status for check in proxy_outcome.sub_checks}
    return (
        subcheck_statuses.get("api_connectivity") == HealthStatus.HEALTHY
        and subcheck_statuses.get("authentication") == HealthStatus.HEALTHY
    )


def _jackett_allows_indexer_checks(proxy_outcome: CheckOutcome) -> bool:
    """Return True when Jackett connectivity and auth are good enough for fan-out."""
    subcheck_statuses = {check.check_name: check.status for check in proxy_outcome.sub_checks}
    return (
        subcheck_statuses.get("api_connectivity") == HealthStatus.HEALTHY
        and subcheck_statuses.get("authentication") == HealthStatus.HEALTHY
    )


def _skipped_indexer_subject(
    config: IndexerConfig,
    proxy_outcome: CheckOutcome,
    *,
    manager_name: str,
) -> CheckOutcome:
    """Build an unknown indexer result when its owning manager is unavailable."""
    endpoint_details = _indexer_endpoint_details(config.url)
    message = f"Skipped because {manager_name} is unavailable"
    sub_checks = (
        SubCheckOutcome(
            check_name="endpoint_reachability",
            name="Endpoint reachability",
            status=HealthStatus.UNKNOWN,
            message=message,
            subject_key=str(config.id),
            subject_label=config.name,
        ),
        SubCheckOutcome(
            check_name="authentication",
            name="Authentication",
            status=HealthStatus.UNKNOWN,
            message=message,
            subject_key=str(config.id),
            subject_label=config.name,
        ),
        SubCheckOutcome(
            check_name="capabilities",
            name="Capabilities",
            status=HealthStatus.UNKNOWN,
            message=message,
            subject_key=str(config.id),
            subject_label=config.name,
        ),
        SubCheckOutcome(
            check_name="latency",
            name="Latency",
            status=HealthStatus.UNKNOWN,
            message=message,
            subject_key=str(config.id),
            subject_label=config.name,
        ),
    )
    return CheckOutcome(
        component="indexers",
        check_name="indexer_summary",
        status=HealthStatus.UNKNOWN,
        message=message,
        subject_key=str(config.id),
        subject_label=config.name,
        details={
            "checks": [_serialize_sub_check(check) for check in sub_checks],
            "subject_kind": "indexer",
            "indexer_kind": _indexer_kind_label(config.indexer_type.value),
            "content_type": _indexer_content_type_label(config.indexer_type.value),
            "source": str(config.source),
            "url": config.url,
            "protocol": endpoint_details["protocol"],
            "host": endpoint_details["host"],
            "port": endpoint_details["port"],
            "skipped_reason": proxy_outcome.message,
        },
        actionable_guidance=f"Restore {manager_name} before checking this indexer.",
        sub_checks=sub_checks,
    )


async def load_prowlarr_subject_config(
    session: AsyncSession,
) -> tuple[str | None, str | None]:
    """Load and decrypt Prowlarr connection settings for health checks."""
    from pullbox.core.encryption import decrypt_secret
    from pullbox.models.config import SystemConfig

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
        return None, None
    return url, decrypt_secret(api_key)


async def load_jackett_subject_config(
    session: AsyncSession,
) -> tuple[str | None, str | None]:
    """Load and decrypt Jackett connection settings for health checks."""
    from pullbox.core.encryption import decrypt_secret
    from pullbox.models.config import SystemConfig

    rows = (
        (
            await session.execute(
                select(SystemConfig).where(SystemConfig.key.in_(("jackett_url", "jackett_api_key")))
            )
        )
        .scalars()
        .all()
    )
    values = {row.key: row.value for row in rows}
    url = str(values.get("jackett_url") or "").strip()
    api_key = str(values.get("jackett_api_key") or "").strip()
    if not url or not api_key:
        return None, None
    return url, decrypt_secret(api_key)


async def check_prowlarr_subject(
    *,
    url: str,
    api_key: str,
) -> CheckOutcome:
    """Build a persisted health summary for the configured Prowlarr proxy."""
    from pullbox.providers.indexer.prowlarr import ProwlarrIndexer

    proxy = ProwlarrIndexer(url=url, api_key=api_key)
    try:
        health = await proxy.test_connection()
    finally:
        await proxy.close()

    response_ms = float(health.response_time_ms or 0.0)
    failure_kind = _indexer_failure_kind(health.message)
    endpoint_details = _indexer_endpoint_details(url)
    guidance_parts: list[str] = []
    raw_indexer_count = (health.details or {}).get("indexer_count")
    try:
        indexer_count = int(str(raw_indexer_count or "0"))
    except (TypeError, ValueError):
        indexer_count = 0

    if health.healthy:
        latency_status = _status_for_latency(
            response_ms,
            degraded_ms=_INDEXER_LATENCY_DEGRADED_MS,
            unhealthy_ms=_INDEXER_LATENCY_UNHEALTHY_MS,
        )
        sub_checks = (
            SubCheckOutcome(
                check_name="api_connectivity",
                name="API connectivity",
                status=HealthStatus.HEALTHY,
                message="Prowlarr reachable",
                subject_key="prowlarr",
                subject_label="Prowlarr",
                response_time_ms=response_ms,
            ),
            SubCheckOutcome(
                check_name="authentication",
                name="Authentication",
                status=HealthStatus.HEALTHY,
                message="API key accepted",
                subject_key="prowlarr",
                subject_label="Prowlarr",
            ),
            SubCheckOutcome(
                check_name="indexer_registry",
                name="Indexer registry",
                status=HealthStatus.HEALTHY,
                message=f"{indexer_count} indexer(s) available",
                subject_key="prowlarr",
                subject_label="Prowlarr",
                details={"indexer_count": indexer_count},
            ),
            SubCheckOutcome(
                check_name="latency",
                name="Latency",
                status=latency_status,
                message=_latency_message(response_ms, "Prowlarr responded"),
                subject_key="prowlarr",
                subject_label="Prowlarr",
                response_time_ms=response_ms,
            ),
        )
    elif failure_kind == "authentication":
        sub_checks = (
            SubCheckOutcome(
                check_name="api_connectivity",
                name="API connectivity",
                status=HealthStatus.HEALTHY,
                message="Prowlarr endpoint responded",
                subject_key="prowlarr",
                subject_label="Prowlarr",
                response_time_ms=response_ms,
            ),
            SubCheckOutcome(
                check_name="authentication",
                name="Authentication",
                status=HealthStatus.UNHEALTHY,
                message=health.message or "Authentication failed",
                subject_key="prowlarr",
                subject_label="Prowlarr",
            ),
            SubCheckOutcome(
                check_name="indexer_registry",
                name="Indexer registry",
                status=HealthStatus.UNKNOWN,
                message="Indexer registry unavailable until authentication succeeds",
                subject_key="prowlarr",
                subject_label="Prowlarr",
            ),
            SubCheckOutcome(
                check_name="latency",
                name="Latency",
                status=HealthStatus.UNKNOWN,
                message="Latency unavailable until authentication succeeds",
                subject_key="prowlarr",
                subject_label="Prowlarr",
            ),
        )
        guidance_parts.append("Verify the Prowlarr API key in Settings > Indexers.")
    else:
        network_message = health.message or "Prowlarr unreachable"
        sub_checks = (
            SubCheckOutcome(
                check_name="api_connectivity",
                name="API connectivity",
                status=HealthStatus.UNHEALTHY,
                message=network_message,
                subject_key="prowlarr",
                subject_label="Prowlarr",
                response_time_ms=response_ms,
            ),
            SubCheckOutcome(
                check_name="authentication",
                name="Authentication",
                status=HealthStatus.UNKNOWN,
                message="Authentication unavailable while the proxy is unreachable",
                subject_key="prowlarr",
                subject_label="Prowlarr",
            ),
            SubCheckOutcome(
                check_name="indexer_registry",
                name="Indexer registry",
                status=HealthStatus.UNKNOWN,
                message="Indexer registry unavailable while the proxy is unreachable",
                subject_key="prowlarr",
                subject_label="Prowlarr",
            ),
            SubCheckOutcome(
                check_name="latency",
                name="Latency",
                status=HealthStatus.UNKNOWN,
                message="Latency unavailable while the proxy is unreachable",
                subject_key="prowlarr",
                subject_label="Prowlarr",
            ),
        )
        guidance_parts.append("Verify the Prowlarr URL, container state, and network path.")

    worst = max(
        (check.status for check in sub_checks),
        key=lambda status: _STATUS_PRECEDENCE.get(status, 0),
        default=HealthStatus.UNKNOWN,
    )
    if worst == HealthStatus.HEALTHY:
        summary_message = "Prowlarr reachable"
    elif any(
        check.check_name == "authentication" and check.status == HealthStatus.UNHEALTHY
        for check in sub_checks
    ):
        summary_message = "Authentication failed"
    elif any(
        check.check_name == "api_connectivity" and check.status == HealthStatus.UNHEALTHY
        for check in sub_checks
    ):
        summary_message = "Prowlarr unreachable"
    elif any(
        check.check_name == "latency" and check.status == HealthStatus.DEGRADED
        for check in sub_checks
    ):
        summary_message = "Prowlarr response time elevated"
    else:
        summary_message = "Prowlarr needs attention"

    return CheckOutcome(
        component="indexers",
        check_name="proxy_summary",
        status=worst,
        message=summary_message,
        subject_key="prowlarr",
        subject_label="Prowlarr",
        details={
            "checks": [_serialize_sub_check(check) for check in sub_checks],
            "subject_kind": "proxy",
            "proxy_type": "Prowlarr",
            "url": url,
            "protocol": endpoint_details["protocol"],
            "host": endpoint_details["host"],
            "port": endpoint_details["port"],
            "indexer_count": indexer_count,
        },
        response_time_ms=response_ms,
        actionable_guidance=" ".join(guidance_parts).strip(),
        sub_checks=sub_checks,
    )


async def check_jackett_subject(
    *,
    url: str,
    api_key: str,
) -> CheckOutcome:
    """Build a persisted health summary for the configured Jackett proxy."""
    from pullbox.providers.indexer.jackett import JackettClient

    proxy = JackettClient(url=url, api_key=api_key)
    try:
        health = await proxy.test_connection()
    finally:
        await proxy.close()

    response_ms = float(health.response_time_ms or 0.0)
    failure_kind = _indexer_failure_kind(health.message)
    endpoint_details = _indexer_endpoint_details(url)
    raw_indexer_count = (health.details or {}).get("indexer_count")
    try:
        indexer_count = int(str(raw_indexer_count or "0"))
    except (TypeError, ValueError):
        indexer_count = 0

    if health.healthy:
        latency_status = _status_for_latency(
            response_ms,
            degraded_ms=_INDEXER_LATENCY_DEGRADED_MS,
            unhealthy_ms=_INDEXER_LATENCY_UNHEALTHY_MS,
        )
        sub_checks = (
            SubCheckOutcome(
                check_name="api_connectivity",
                name="API connectivity",
                status=HealthStatus.HEALTHY,
                message="Jackett reachable",
                subject_key="jackett",
                subject_label="Jackett",
                response_time_ms=response_ms,
            ),
            SubCheckOutcome(
                check_name="authentication",
                name="Authentication",
                status=HealthStatus.HEALTHY,
                message="API key accepted",
                subject_key="jackett",
                subject_label="Jackett",
            ),
            SubCheckOutcome(
                check_name="indexer_registry",
                name="Indexer registry",
                status=HealthStatus.HEALTHY,
                message=f"{indexer_count} indexer(s) available",
                subject_key="jackett",
                subject_label="Jackett",
                details={"indexer_count": indexer_count},
            ),
            SubCheckOutcome(
                check_name="latency",
                name="Latency",
                status=latency_status,
                message=_latency_message(response_ms, "Jackett responded"),
                subject_key="jackett",
                subject_label="Jackett",
                response_time_ms=response_ms,
            ),
        )
        guidance = ""
    elif failure_kind == "authentication":
        sub_checks = (
            SubCheckOutcome(
                check_name="api_connectivity",
                name="API connectivity",
                status=HealthStatus.HEALTHY,
                message="Jackett endpoint responded",
                subject_key="jackett",
                subject_label="Jackett",
                response_time_ms=response_ms,
            ),
            SubCheckOutcome(
                check_name="authentication",
                name="Authentication",
                status=HealthStatus.UNHEALTHY,
                message=health.message or "Authentication failed",
                subject_key="jackett",
                subject_label="Jackett",
            ),
            SubCheckOutcome(
                check_name="indexer_registry",
                name="Indexer registry",
                status=HealthStatus.UNKNOWN,
                message="Indexer registry unavailable until authentication succeeds",
                subject_key="jackett",
                subject_label="Jackett",
            ),
            SubCheckOutcome(
                check_name="latency",
                name="Latency",
                status=HealthStatus.UNKNOWN,
                message="Latency unavailable until authentication succeeds",
                subject_key="jackett",
                subject_label="Jackett",
            ),
        )
        guidance = "Verify the Jackett API key in Settings > Indexers."
    else:
        network_message = health.message or "Jackett unreachable"
        sub_checks = (
            SubCheckOutcome(
                check_name="api_connectivity",
                name="API connectivity",
                status=HealthStatus.UNHEALTHY,
                message=network_message,
                subject_key="jackett",
                subject_label="Jackett",
                response_time_ms=response_ms,
            ),
            SubCheckOutcome(
                check_name="authentication",
                name="Authentication",
                status=HealthStatus.UNKNOWN,
                message="Authentication unavailable while the proxy is unreachable",
                subject_key="jackett",
                subject_label="Jackett",
            ),
            SubCheckOutcome(
                check_name="indexer_registry",
                name="Indexer registry",
                status=HealthStatus.UNKNOWN,
                message="Indexer registry unavailable while the proxy is unreachable",
                subject_key="jackett",
                subject_label="Jackett",
            ),
            SubCheckOutcome(
                check_name="latency",
                name="Latency",
                status=HealthStatus.UNKNOWN,
                message="Latency unavailable while the proxy is unreachable",
                subject_key="jackett",
                subject_label="Jackett",
            ),
        )
        guidance = "Verify the Jackett URL, container state, and network path."

    worst = max(
        (check.status for check in sub_checks),
        key=lambda status: _STATUS_PRECEDENCE.get(status, 0),
        default=HealthStatus.UNKNOWN,
    )
    if worst == HealthStatus.HEALTHY:
        summary_message = "Jackett reachable"
    elif any(
        check.check_name == "authentication" and check.status == HealthStatus.UNHEALTHY
        for check in sub_checks
    ):
        summary_message = "Authentication failed"
    elif any(
        check.check_name == "api_connectivity" and check.status == HealthStatus.UNHEALTHY
        for check in sub_checks
    ):
        summary_message = "Jackett unreachable"
    elif any(
        check.check_name == "latency" and check.status == HealthStatus.DEGRADED
        for check in sub_checks
    ):
        summary_message = "Jackett response time elevated"
    else:
        summary_message = "Jackett needs attention"

    return CheckOutcome(
        component="indexers",
        check_name="proxy_summary",
        status=worst,
        message=summary_message,
        subject_key="jackett",
        subject_label="Jackett",
        details={
            "checks": [_serialize_sub_check(check) for check in sub_checks],
            "subject_kind": "proxy",
            "proxy_type": "Jackett",
            "url": url,
            "protocol": endpoint_details["protocol"],
            "host": endpoint_details["host"],
            "port": endpoint_details["port"],
            "indexer_count": indexer_count,
        },
        response_time_ms=response_ms,
        actionable_guidance=guidance,
        sub_checks=sub_checks,
    )


async def check_indexer_subject(
    config: IndexerConfig,
    resolver_options: Sequence[NativeResolverOption] = (),
) -> CheckOutcome:
    """Build a persisted health summary for one configured indexer."""
    from pullbox.core.encryption import decrypt_secret
    from pullbox.models.indexer import IndexerType
    from pullbox.providers.indexer.newznab import NewznabIndexer
    from pullbox.providers.indexer.torznab import TorznabIndexer

    api_key = decrypt_secret(config.api_key)

    if config.indexer_type == IndexerType.TORZNAB:
        indexer: NewznabIndexer = TorznabIndexer(
            name=config.name,
            url=config.url,
            api_key=api_key,
            resolver_enabled=bool(config.resolver_enabled),
            resolver_options=resolver_options,
        )
    else:
        indexer = NewznabIndexer(
            name=config.name,
            url=config.url,
            api_key=api_key,
        )

    try:
        health = await indexer.test_connection()
    finally:
        await indexer.close()

    response_ms = float(health.response_time_ms or 0.0)
    failure_kind = _indexer_failure_kind(health.message)
    endpoint_details = _indexer_endpoint_details(config.url)
    guidance_parts: list[str] = []
    raw_categories = (health.details or {}).get("categories")
    try:
        category_count = int(str(raw_categories or "0"))
    except (TypeError, ValueError):
        category_count = 0

    if health.healthy:
        latency_status = _status_for_latency(
            response_ms,
            degraded_ms=_INDEXER_LATENCY_DEGRADED_MS,
            unhealthy_ms=_INDEXER_LATENCY_UNHEALTHY_MS,
        )
        sub_checks = (
            SubCheckOutcome(
                check_name="endpoint_reachability",
                name="Endpoint reachability",
                status=HealthStatus.HEALTHY,
                message="Endpoint reachable",
                subject_key=str(config.id),
                subject_label=config.name,
                response_time_ms=response_ms,
            ),
            SubCheckOutcome(
                check_name="authentication",
                name="Authentication",
                status=HealthStatus.HEALTHY,
                message="API key accepted",
                subject_key=str(config.id),
                subject_label=config.name,
            ),
            SubCheckOutcome(
                check_name="capabilities",
                name="Capabilities",
                status=HealthStatus.HEALTHY,
                message=f"{category_count} categories available",
                subject_key=str(config.id),
                subject_label=config.name,
                details={"categories": category_count},
            ),
            SubCheckOutcome(
                check_name="latency",
                name="Latency",
                status=latency_status,
                message=_latency_message(response_ms, "Indexer responded"),
                subject_key=str(config.id),
                subject_label=config.name,
                response_time_ms=response_ms,
            ),
        )
    elif failure_kind == "authentication":
        sub_checks = (
            SubCheckOutcome(
                check_name="endpoint_reachability",
                name="Endpoint reachability",
                status=HealthStatus.HEALTHY,
                message="Endpoint responded",
                subject_key=str(config.id),
                subject_label=config.name,
                response_time_ms=response_ms,
            ),
            SubCheckOutcome(
                check_name="authentication",
                name="Authentication",
                status=HealthStatus.UNHEALTHY,
                message=health.message or "Authentication failed",
                subject_key=str(config.id),
                subject_label=config.name,
            ),
            SubCheckOutcome(
                check_name="capabilities",
                name="Capabilities",
                status=HealthStatus.UNKNOWN,
                message="Capabilities unavailable until authentication succeeds",
                subject_key=str(config.id),
                subject_label=config.name,
            ),
            SubCheckOutcome(
                check_name="latency",
                name="Latency",
                status=HealthStatus.UNKNOWN,
                message="Latency unavailable until authentication succeeds",
                subject_key=str(config.id),
                subject_label=config.name,
            ),
        )
        guidance_parts.append(f"Verify the API key for {config.name} in Settings > Indexers.")
    else:
        network_message = health.message or "Indexer unreachable"
        sub_checks = (
            SubCheckOutcome(
                check_name="endpoint_reachability",
                name="Endpoint reachability",
                status=HealthStatus.UNHEALTHY,
                message=network_message,
                subject_key=str(config.id),
                subject_label=config.name,
                response_time_ms=response_ms,
            ),
            SubCheckOutcome(
                check_name="authentication",
                name="Authentication",
                status=HealthStatus.UNKNOWN,
                message="Authentication unavailable while the endpoint is unreachable",
                subject_key=str(config.id),
                subject_label=config.name,
            ),
            SubCheckOutcome(
                check_name="capabilities",
                name="Capabilities",
                status=HealthStatus.UNKNOWN,
                message="Capabilities unavailable while the endpoint is unreachable",
                subject_key=str(config.id),
                subject_label=config.name,
            ),
            SubCheckOutcome(
                check_name="latency",
                name="Latency",
                status=HealthStatus.UNKNOWN,
                message="Latency unavailable while the endpoint is unreachable",
                subject_key=str(config.id),
                subject_label=config.name,
            ),
        )
        guidance_parts.append(f"Verify the URL, API key, and network path for {config.name}.")

    worst = max(
        (check.status for check in sub_checks),
        key=lambda status: _STATUS_PRECEDENCE.get(status, 0),
        default=HealthStatus.UNKNOWN,
    )
    if worst == HealthStatus.HEALTHY:
        summary_message = "Indexer reachable"
    elif any(
        check.check_name == "authentication" and check.status == HealthStatus.UNHEALTHY
        for check in sub_checks
    ):
        summary_message = "Authentication failed"
    elif any(
        check.check_name == "endpoint_reachability" and check.status == HealthStatus.UNHEALTHY
        for check in sub_checks
    ):
        summary_message = "Indexer unreachable"
    elif any(
        check.check_name == "latency" and check.status == HealthStatus.DEGRADED
        for check in sub_checks
    ):
        summary_message = "Indexer response time elevated"
    else:
        summary_message = "Indexer needs attention"

    return CheckOutcome(
        component="indexers",
        check_name="indexer_summary",
        status=worst,
        message=summary_message,
        subject_key=str(config.id),
        subject_label=config.name,
        details={
            "checks": [_serialize_sub_check(check) for check in sub_checks],
            "subject_kind": "indexer",
            "indexer_kind": _indexer_kind_label(config.indexer_type.value),
            "content_type": _indexer_content_type_label(config.indexer_type.value),
            "source": str(config.source),
            "url": config.url,
            "protocol": endpoint_details["protocol"],
            "host": endpoint_details["host"],
            "port": endpoint_details["port"],
            "categories": category_count,
        },
        response_time_ms=response_ms,
        actionable_guidance=" ".join(guidance_parts).strip(),
        sub_checks=sub_checks,
    )
