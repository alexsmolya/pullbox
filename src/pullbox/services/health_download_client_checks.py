"""Download-client-specific health check implementation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from pullbox.models.health import HealthStatus
from pullbox.services.health_helpers import (
    _STATUS_PRECEDENCE,
    _download_client_endpoint_details,
    _download_client_failure_kind,
    _download_client_type_display,
    _serialize_download_client_summary,
    _serialize_sub_check,
)
from pullbox.services.health_types import CheckOutcome, SubCheckOutcome

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

    from sqlalchemy.ext.asyncio import AsyncSession

    from pullbox.models.client import DownloadClientConfig
    from pullbox.providers.base import DownloadClient, ProviderRegistry


async def check_download_clients(
    session: AsyncSession,
    *,
    registry: ProviderRegistry | None,
    bootstrap_errors: dict[str, list[dict[str, str]]],
    check_subject: Callable[[DownloadClientConfig, DownloadClient], Awaitable[CheckOutcome]],
    bootstrap_outcome: Callable[[DownloadClientConfig, Mapping[str, str]], CheckOutcome],
    unknown_outcome: Callable[[DownloadClientConfig], CheckOutcome],
) -> list[CheckOutcome]:
    """Test download clients as a grouped multi-entity health component."""
    from pullbox.models.client import DownloadClientConfig

    result = await session.execute(
        select(DownloadClientConfig).where(DownloadClientConfig.enabled.is_(True))
    )
    client_configs = list(result.scalars().all())
    bootstrap_checks = list(bootstrap_errors.get("download_clients", []))

    if not client_configs:
        return [
            CheckOutcome(
                component="download_clients",
                check_name="connectivity",
                status=HealthStatus.UNKNOWN,
                message="Not configured",
                actionable_guidance=("Configure a download client in Settings > Download Clients."),
            )
        ]

    clients_by_id = {
        str(config_id): client
        for config_id, client in (registry.get_download_client_items() if registry else [])
    }
    bootstrap_by_id = {
        str(raw.get("config_id")): raw for raw in bootstrap_checks if raw.get("config_id")
    }
    generic_bootstrap_error = next(
        (raw for raw in bootstrap_checks if not raw.get("config_id")),
        None,
    )

    subject_outcomes: list[CheckOutcome] = []
    summary_checks: list[dict[str, Any]] = []
    flagged_names: list[str] = []
    healthy_count = 0
    total_ms = 0.0

    for config in client_configs:
        config_key = str(config.id)
        if config_key in bootstrap_by_id:
            outcome = bootstrap_outcome(config, bootstrap_by_id[config_key])
        elif config_key in clients_by_id:
            outcome = await check_subject(config, clients_by_id[config_key])
        elif generic_bootstrap_error:
            outcome = bootstrap_outcome(config, generic_bootstrap_error)
        else:
            outcome = unknown_outcome(config)

        subject_outcomes.append(outcome)
        summary_checks.append(_serialize_download_client_summary(outcome))
        total_ms += outcome.response_time_ms
        if outcome.status == HealthStatus.HEALTHY:
            healthy_count += 1
        else:
            flagged_names.append(config.name)

    total = len(subject_outcomes)

    if flagged_names and healthy_count == 0:
        component_status = HealthStatus.UNHEALTHY
        message = "All clients unreachable or misconfigured"
        guidance = (
            "Verify host, port, and credentials for each download client in "
            "Settings > Download Clients."
        )
    elif flagged_names:
        component_status = HealthStatus.DEGRADED
        message = f"{len(flagged_names)} of {total} client(s) need attention"
        guidance = f"Review {', '.join(flagged_names)} in Settings > Download Clients."
    else:
        component_status = HealthStatus.HEALTHY
        message = "All clients reachable"
        guidance = ""

    return [
        CheckOutcome(
            component="download_clients",
            check_name="connectivity",
            status=component_status,
            message=message,
            details={"checks": summary_checks},
            response_time_ms=total_ms,
            actionable_guidance=guidance,
        ),
        *subject_outcomes,
    ]


async def check_download_client_subject(
    config: DownloadClientConfig,
    client: DownloadClient,
    *,
    perf_counter: Callable[[], float],
) -> CheckOutcome:
    """Build a persisted health summary for one download client."""
    test_health = await client.test_connection()
    response_ms = float(test_health.response_time_ms or 0.0)
    failure_kind = _download_client_failure_kind(test_health.message)
    version = str((test_health.details or {}).get("version") or "").strip()
    endpoint_details = _download_client_endpoint_details(config.url)
    guidance_parts: list[str] = []

    if test_health.healthy:
        queue_started = perf_counter()
        try:
            queue_items = await client.get_queue()
            queue_elapsed_ms = (perf_counter() - queue_started) * 1000
            response_ms += queue_elapsed_ms
            queue_check = SubCheckOutcome(
                check_name="queue_access",
                name="Queue access",
                status=HealthStatus.HEALTHY,
                message=(
                    "Queue accessible (empty)"
                    if not queue_items
                    else f"Queue accessible ({len(queue_items)} active)"
                ),
                subject_key=str(config.id),
                subject_label=config.name,
                response_time_ms=queue_elapsed_ms,
                details={"active_count": len(queue_items)},
            )
        except Exception as exc:
            queue_check = SubCheckOutcome(
                check_name="queue_access",
                name="Queue access",
                status=HealthStatus.UNHEALTHY,
                message=f"Queue request failed: {exc}",
                subject_key=str(config.id),
                subject_label=config.name,
            )
            guidance_parts.append(
                "The client answered its identity probe but the queue endpoint failed. "
                "Check the client API logs and permissions."
            )

        sub_checks = (
            SubCheckOutcome(
                check_name="endpoint_reachability",
                name="Endpoint reachability",
                status=HealthStatus.HEALTHY,
                message="Endpoint reachable",
                subject_key=str(config.id),
                subject_label=config.name,
                response_time_ms=test_health.response_time_ms,
            ),
            SubCheckOutcome(
                check_name="authentication",
                name="Authentication",
                status=HealthStatus.HEALTHY,
                message="Credentials accepted",
                subject_key=str(config.id),
                subject_label=config.name,
            ),
            SubCheckOutcome(
                check_name="client_identity",
                name="Client identity",
                status=HealthStatus.HEALTHY,
                message=(
                    f"{_download_client_type_display(config.client_type.value)} {version}"
                    if version
                    else (test_health.message or "Identity probe succeeded")
                ),
                subject_key=str(config.id),
                subject_label=config.name,
                response_time_ms=test_health.response_time_ms,
                details={"version": version} if version else {},
            ),
            queue_check,
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
                response_time_ms=test_health.response_time_ms,
            ),
            SubCheckOutcome(
                check_name="authentication",
                name="Authentication",
                status=HealthStatus.UNHEALTHY,
                message=test_health.message or "Authentication failed",
                subject_key=str(config.id),
                subject_label=config.name,
            ),
            SubCheckOutcome(
                check_name="client_identity",
                name="Client identity",
                status=HealthStatus.UNKNOWN,
                message="Blocked by authentication failure",
                subject_key=str(config.id),
                subject_label=config.name,
            ),
            SubCheckOutcome(
                check_name="queue_access",
                name="Queue access",
                status=HealthStatus.UNKNOWN,
                message="Not evaluated",
                subject_key=str(config.id),
                subject_label=config.name,
            ),
        )
        guidance_parts.append(
            "The client endpoint responded but rejected the saved credentials. "
            "Re-save the username, password, or API key in Settings > Download Clients."
        )
    elif failure_kind == "network":
        sub_checks = (
            SubCheckOutcome(
                check_name="endpoint_reachability",
                name="Endpoint reachability",
                status=HealthStatus.UNHEALTHY,
                message=test_health.message or "Endpoint unreachable",
                subject_key=str(config.id),
                subject_label=config.name,
                response_time_ms=test_health.response_time_ms,
            ),
            SubCheckOutcome(
                check_name="authentication",
                name="Authentication",
                status=HealthStatus.UNKNOWN,
                message="Not evaluated",
                subject_key=str(config.id),
                subject_label=config.name,
            ),
            SubCheckOutcome(
                check_name="client_identity",
                name="Client identity",
                status=HealthStatus.UNKNOWN,
                message="Not evaluated",
                subject_key=str(config.id),
                subject_label=config.name,
            ),
            SubCheckOutcome(
                check_name="queue_access",
                name="Queue access",
                status=HealthStatus.UNKNOWN,
                message="Not evaluated",
                subject_key=str(config.id),
                subject_label=config.name,
            ),
        )
        guidance_parts.append(
            "Pullbox could not reach this client. Verify the host, port, protocol, "
            "and that the service is running."
        )
    else:
        sub_checks = (
            SubCheckOutcome(
                check_name="endpoint_reachability",
                name="Endpoint reachability",
                status=HealthStatus.DEGRADED,
                message=test_health.message or "Probe failed",
                subject_key=str(config.id),
                subject_label=config.name,
                response_time_ms=test_health.response_time_ms,
            ),
            SubCheckOutcome(
                check_name="authentication",
                name="Authentication",
                status=HealthStatus.UNKNOWN,
                message="Not evaluated",
                subject_key=str(config.id),
                subject_label=config.name,
            ),
            SubCheckOutcome(
                check_name="client_identity",
                name="Client identity",
                status=HealthStatus.UNKNOWN,
                message="Not evaluated",
                subject_key=str(config.id),
                subject_label=config.name,
            ),
            SubCheckOutcome(
                check_name="queue_access",
                name="Queue access",
                status=HealthStatus.UNKNOWN,
                message="Not evaluated",
                subject_key=str(config.id),
                subject_label=config.name,
            ),
        )
        guidance_parts.append(
            "The client probe failed in an unexpected way. Check the client logs and "
            "network path for more detail."
        )

    worst = max(
        (check.status for check in sub_checks),
        key=lambda status: _STATUS_PRECEDENCE.get(status, 0),
        default=HealthStatus.UNKNOWN,
    )
    if worst == HealthStatus.HEALTHY:
        summary_message = test_health.message or "Connected"
    elif any(
        check.check_name == "authentication" and check.status == HealthStatus.UNHEALTHY
        for check in sub_checks
    ):
        summary_message = "Authentication failed"
    elif any(
        check.check_name == "queue_access" and check.status == HealthStatus.UNHEALTHY
        for check in sub_checks
    ):
        summary_message = "Queue unavailable"
    elif any(
        check.check_name == "endpoint_reachability" and check.status == HealthStatus.UNHEALTHY
        for check in sub_checks
    ):
        summary_message = "Client unreachable"
    else:
        summary_message = "Client needs attention"

    return CheckOutcome(
        component="download_clients",
        check_name="client_summary",
        status=worst,
        message=summary_message,
        subject_key=str(config.id),
        subject_label=config.name,
        details={
            "checks": [_serialize_sub_check(check) for check in sub_checks],
            "client_type": config.client_type.value,
            "url": config.url,
            "protocol": endpoint_details["protocol"],
            "host": endpoint_details["host"],
            "port": endpoint_details["port"],
            "version": version or None,
        },
        response_time_ms=response_ms,
        actionable_guidance=" ".join(dict.fromkeys(guidance_parts)),
        sub_checks=sub_checks,
    )


def download_client_bootstrap_outcome(
    config: DownloadClientConfig,
    bootstrap_error: Mapping[str, str],
) -> CheckOutcome:
    """Return a structured subject outcome for a client that could not load."""
    endpoint_details = _download_client_endpoint_details(config.url)
    message = bootstrap_error.get("message") or "Configuration error"
    sub_checks = (
        SubCheckOutcome(
            check_name="endpoint_reachability",
            name="Endpoint reachability",
            status=HealthStatus.UNKNOWN,
            message="Not evaluated",
            subject_key=str(config.id),
            subject_label=config.name,
        ),
        SubCheckOutcome(
            check_name="authentication",
            name="Authentication",
            status=HealthStatus.UNHEALTHY,
            message=message,
            subject_key=str(config.id),
            subject_label=config.name,
        ),
        SubCheckOutcome(
            check_name="client_identity",
            name="Client identity",
            status=HealthStatus.UNKNOWN,
            message="Not evaluated",
            subject_key=str(config.id),
            subject_label=config.name,
        ),
        SubCheckOutcome(
            check_name="queue_access",
            name="Queue access",
            status=HealthStatus.UNKNOWN,
            message="Not evaluated",
            subject_key=str(config.id),
            subject_label=config.name,
        ),
    )
    return CheckOutcome(
        component="download_clients",
        check_name="client_summary",
        status=HealthStatus.UNHEALTHY,
        message="Configuration error",
        subject_key=str(config.id),
        subject_label=config.name,
        details={
            "checks": [_serialize_sub_check(check) for check in sub_checks],
            "client_type": config.client_type.value,
            "url": config.url,
            "protocol": endpoint_details["protocol"],
            "host": endpoint_details["host"],
            "port": endpoint_details["port"],
        },
        actionable_guidance=(
            "Re-save this client in Settings > Download Clients so Pullbox can "
            "rebuild the provider connection."
        ),
        sub_checks=sub_checks,
    )


def download_client_unknown_outcome(
    config: DownloadClientConfig,
    *,
    message: str,
) -> CheckOutcome:
    """Return a placeholder client outcome when no live result exists yet."""
    endpoint_details = _download_client_endpoint_details(config.url)
    sub_checks = tuple(
        SubCheckOutcome(
            check_name=check_name,
            name=name,
            status=HealthStatus.UNKNOWN,
            message="Waiting for the next health check",
            subject_key=str(config.id),
            subject_label=config.name,
        )
        for check_name, name in (
            ("endpoint_reachability", "Endpoint reachability"),
            ("authentication", "Authentication"),
            ("client_identity", "Client identity"),
            ("queue_access", "Queue access"),
        )
    )
    return CheckOutcome(
        component="download_clients",
        check_name="client_summary",
        status=HealthStatus.UNKNOWN,
        message=message,
        subject_key=str(config.id),
        subject_label=config.name,
        details={
            "checks": [_serialize_sub_check(check) for check in sub_checks],
            "client_type": config.client_type.value,
            "url": config.url,
            "protocol": endpoint_details["protocol"],
            "host": endpoint_details["host"],
            "port": endpoint_details["port"],
        },
        sub_checks=sub_checks,
    )
