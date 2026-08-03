"""Provider quota telemetry and automatic-download reserve policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from pullbox.models.direct_acquisition import DirectProviderConfig, DirectProviderState

if TYPE_CHECKING:
    from pullbox.providers.direct.contract import DirectQuotaStatus

DEFAULT_AUTOMATIC_QUOTA_RESERVE = 5
_TRANSIENT_BACKOFF = timedelta(minutes=15)


@dataclass(frozen=True, slots=True)
class ProviderQuotaSnapshot:
    """Safe account-capacity telemetry persisted without download history."""

    remaining: int | None
    limit: int | None
    window_seconds: int | None
    reset_at: datetime | None
    observed_at: datetime


def automatic_quota_reserve(provider: DirectProviderConfig) -> int:
    value = _metadata(provider).get("automatic_quota_reserve")
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return DEFAULT_AUTOMATIC_QUOTA_RESERVE


def set_automatic_quota_reserve(provider: DirectProviderConfig, reserve: int) -> None:
    if reserve < 0 or reserve > 100_000:
        raise ValueError("Automatic quota reserve must be between 0 and 100000.")
    metadata = _metadata(provider)
    metadata["automatic_quota_reserve"] = reserve
    provider.configuration_metadata = metadata


def provider_supports_quota(provider: DirectProviderConfig) -> bool:
    manifest = provider.manifest_snapshot if isinstance(provider.manifest_snapshot, dict) else {}
    capabilities = manifest.get("capabilities", {})
    return isinstance(capabilities, dict) and capabilities.get("quota") is True


def provider_quota_status(provider: DirectProviderConfig) -> ProviderQuotaSnapshot | None:
    raw = _metadata(provider).get("quota_status")
    if not isinstance(raw, dict):
        return None
    observed_at = _parse_datetime(raw.get("observed_at"))
    if observed_at is None:
        return None
    return ProviderQuotaSnapshot(
        remaining=_optional_nonnegative_int(raw.get("remaining")),
        limit=_optional_nonnegative_int(raw.get("limit")),
        window_seconds=_optional_nonnegative_int(raw.get("window_seconds")),
        reset_at=_parse_datetime(raw.get("reset_at")),
        observed_at=observed_at,
    )


def record_provider_quota(
    provider: DirectProviderConfig,
    quota: DirectQuotaStatus,
    *,
    observed_at: datetime | None = None,
) -> None:
    observed = observed_at or datetime.now(UTC)
    reset_at = quota.reset_at
    if reset_at is None and quota.window_seconds is not None:
        reset_at = observed + timedelta(seconds=quota.window_seconds)
    metadata = _metadata(provider)
    metadata["quota_status"] = {
        "remaining": quota.remaining,
        "limit": quota.limit,
        "window_seconds": quota.window_seconds,
        "reset_at": reset_at.isoformat() if reset_at else None,
        "observed_at": observed.isoformat(),
    }
    metadata.pop("automatic_backoff_until", None)
    provider.configuration_metadata = metadata
    if provider.state in {
        DirectProviderState.RATE_LIMITED,
        DirectProviderState.UNAVAILABLE,
    } and (quota.remaining is None or quota.remaining > 0):
        provider.state = DirectProviderState.HEALTHY
    provider.last_error_code = None


def record_provider_resolution_error(
    provider: DirectProviderConfig,
    code: str,
    *,
    observed_at: datetime | None = None,
    retry_after_seconds: int | None = None,
) -> None:
    observed = observed_at or datetime.now(UTC)
    metadata = _metadata(provider)
    provider.last_error_code = code
    if code == "source_quota_limited":
        current = provider_quota_status(provider)
        reset_at = current.reset_at if current else None
        if reset_at is None and current and current.window_seconds is not None:
            reset_at = observed + timedelta(seconds=current.window_seconds)
        retry_window = (
            retry_after_seconds
            if isinstance(retry_after_seconds, int)
            and not isinstance(retry_after_seconds, bool)
            and 0 <= retry_after_seconds <= 86_400
            else None
        )
        if reset_at is None and retry_window is not None:
            reset_at = observed + timedelta(seconds=retry_window)
        metadata["quota_status"] = {
            "remaining": 0,
            "limit": current.limit if current else None,
            "window_seconds": current.window_seconds if current else retry_window,
            "reset_at": reset_at.isoformat() if reset_at else None,
            "observed_at": observed.isoformat(),
        }
        provider.state = DirectProviderState.RATE_LIMITED
    elif code == "source_authentication_required":
        provider.state = DirectProviderState.AUTHENTICATION_REQUIRED
    elif code in {"source_unavailable", "source_malformed_response"}:
        metadata["automatic_backoff_until"] = (observed + _TRANSIENT_BACKOFF).isoformat()
        provider.state = DirectProviderState.DEGRADED
    provider.configuration_metadata = metadata


def automatic_quota_available(
    provider: DirectProviderConfig,
    *,
    at: datetime | None = None,
) -> bool:
    now = at or datetime.now(UTC)
    quota = provider_quota_status(provider)
    if not provider.enabled:
        return False
    if provider.state is DirectProviderState.RATE_LIMITED:
        return quota is not None and quota.reset_at is not None and quota.reset_at <= now
    if provider.state in {
        DirectProviderState.DISABLED,
        DirectProviderState.AUTHENTICATION_REQUIRED,
        DirectProviderState.INCOMPATIBLE,
        DirectProviderState.UNAVAILABLE,
    }:
        return False
    backoff_until = _parse_datetime(_metadata(provider).get("automatic_backoff_until"))
    if backoff_until is not None and backoff_until > now:
        return False
    if quota is not None and quota.reset_at is not None and quota.reset_at <= now:
        return True
    if quota is None or quota.remaining is None:
        return True
    return quota.remaining > automatic_quota_reserve(provider)


def refresh_expired_provider_quota(
    provider: DirectProviderConfig,
    *,
    at: datetime | None = None,
) -> bool:
    """Discard stale capacity and recover an elapsed rate-limited provider."""
    now = at or datetime.now(UTC)
    quota = provider_quota_status(provider)
    if quota is None or quota.reset_at is None or quota.reset_at > now:
        return False
    metadata = _metadata(provider)
    metadata.pop("quota_status", None)
    provider.configuration_metadata = metadata
    if provider.state is DirectProviderState.RATE_LIMITED:
        provider.state = DirectProviderState.DEGRADED
        provider.last_error_code = None
    return True


def _metadata(provider: DirectProviderConfig) -> dict[str, object]:
    return (
        dict(provider.configuration_metadata)
        if isinstance(provider.configuration_metadata, dict)
        else {}
    )


def _optional_nonnegative_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed
