"""ComicVine-specific health check implementation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pullbox.core.duration_format import format_duration_ms
from pullbox.models.health import HealthStatus
from pullbox.services.health_helpers import (
    _STATUS_PRECEDENCE,
    _serialize_sub_check,
    _status_for_latency,
)
from pullbox.services.health_types import CheckOutcome, SubCheckOutcome

if TYPE_CHECKING:
    from pullbox.providers.base import ProviderRegistry

_COMICVINE_LATENCY_DEGRADED_MS = 1500.0
_COMICVINE_LATENCY_UNHEALTHY_MS = 5000.0


async def check_comicvine(registry: ProviderRegistry | None) -> CheckOutcome:
    """Verify ComicVine auth, connectivity, latency, and rate-limit state."""
    if not registry or not registry.has_metadata_provider("comicvine"):
        return CheckOutcome(
            component="comicvine",
            check_name="api_connectivity",
            status=HealthStatus.UNKNOWN,
            message="Not configured",
            actionable_guidance=(
                "Configure the API key in Settings > Metadata, or set "
                "the PULLBOX_COMICVINE_API_KEY environment variable."
            ),
        )

    provider = registry.get_metadata_provider("comicvine")
    health = await provider.test_connection()
    provider_details = dict(health.details or {})
    status_code = str(provider_details.get("status_code") or "").strip()
    invalid_key = status_code == "100"
    rate_limited = status_code == "107"
    network_failure = not health.healthy and not invalid_key and not rate_limited

    sub_checks: list[SubCheckOutcome] = [
        SubCheckOutcome(
            check_name="api_key",
            name="API key",
            status=HealthStatus.UNHEALTHY if invalid_key else HealthStatus.HEALTHY,
            message="Invalid API key" if invalid_key else "Configured",
            details={"status_code": status_code} if status_code else {},
        ),
        SubCheckOutcome(
            check_name="api_connectivity",
            name="API connectivity",
            status=HealthStatus.UNHEALTHY if network_failure else HealthStatus.HEALTHY,
            message=health.message if network_failure else "Reachable",
            details={"status_code": status_code} if status_code else {},
        ),
        SubCheckOutcome(
            check_name="api_latency",
            name="API latency",
            status=(
                HealthStatus.UNKNOWN
                if network_failure
                else _status_for_latency(
                    health.response_time_ms,
                    degraded_ms=_COMICVINE_LATENCY_DEGRADED_MS,
                    unhealthy_ms=_COMICVINE_LATENCY_UNHEALTHY_MS,
                )
            ),
            message=(
                "Not measured"
                if network_failure
                else format_duration_ms(float(health.response_time_ms or 0.0))
            ),
            response_time_ms=health.response_time_ms if not network_failure else None,
        ),
        SubCheckOutcome(
            check_name="rate_limit",
            name="Rate limit",
            status=(
                HealthStatus.DEGRADED
                if rate_limited
                else HealthStatus.UNKNOWN
                if network_failure
                else HealthStatus.HEALTHY
            ),
            message=(
                "Rate limited by ComicVine"
                if rate_limited
                else "Not evaluated"
                if network_failure
                else "No rate limit detected"
            ),
            details={"status_code": status_code} if status_code else {},
        ),
    ]

    worst = max(
        (check.status for check in sub_checks),
        key=lambda status: _STATUS_PRECEDENCE.get(status, 0),
        default=HealthStatus.UNKNOWN,
    )

    if invalid_key:
        message = "API key invalid"
        guidance = "ComicVine rejected the configured API key. Update it in Settings > Metadata."
    elif rate_limited:
        message = "Rate limit reached"
        guidance = (
            "ComicVine is rate limiting Pullbox right now. Wait for the limit window "
            "to reset before retrying metadata operations."
        )
    elif network_failure:
        message = "API unreachable"
        guidance = (
            "ComicVine API is unreachable. Check network connectivity and that "
            "api.comicvine.com is accessible."
        )
    elif any(
        check.check_name == "api_latency" and check.status != HealthStatus.HEALTHY
        for check in sub_checks
    ):
        message = "API latency elevated"
        guidance = (
            "ComicVine is reachable but responding slowly. Metadata lookups may feel delayed."
        )
    else:
        message = "API connected"
        guidance = ""

    return CheckOutcome(
        component="comicvine",
        check_name="api_connectivity",
        status=worst,
        message=message,
        details={
            "checks": [_serialize_sub_check(check) for check in sub_checks],
            **provider_details,
        },
        response_time_ms=health.response_time_ms,
        actionable_guidance=guidance,
        sub_checks=tuple(sub_checks),
    )
