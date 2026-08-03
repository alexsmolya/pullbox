"""Provider-level quota telemetry and automatic reserve contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pullbox.models.direct_acquisition import DirectProviderConfig, DirectProviderState
from pullbox.providers.direct.contract import DirectQuotaStatus
from pullbox.services.direct_provider_quota import (
    DEFAULT_AUTOMATIC_QUOTA_RESERVE,
    automatic_quota_available,
    automatic_quota_reserve,
    provider_quota_status,
    record_provider_quota,
    record_provider_resolution_error,
    refresh_expired_provider_quota,
    set_automatic_quota_reserve,
)

NOW = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)


def _provider() -> DirectProviderConfig:
    return DirectProviderConfig(
        provider_id="pullbox.annas_archive",
        display_name="Anna's Archive",
        endpoint="http://annas:8780",
        enabled=True,
        state=DirectProviderState.HEALTHY,
        configuration_metadata={},
        manifest_snapshot={"capabilities": {"quota": True}},
    )


def test_quota_capable_provider_defaults_to_five_reserved_automatic_slots() -> None:
    provider = _provider()

    assert automatic_quota_reserve(provider) == DEFAULT_AUTOMATIC_QUOTA_RESERVE == 5

    set_automatic_quota_reserve(provider, 3)

    assert automatic_quota_reserve(provider) == 3


def test_quota_telemetry_is_persisted_without_download_history() -> None:
    provider = _provider()

    record_provider_quota(
        provider,
        DirectQuotaStatus(remaining=22, limit=25, window_seconds=64_800),
        observed_at=NOW,
    )

    quota = provider_quota_status(provider)
    assert quota is not None
    assert quota.remaining == 22
    assert quota.limit == 25
    assert quota.window_seconds == 64_800
    assert quota.observed_at == NOW
    assert automatic_quota_available(provider) is True


def test_automatic_reserve_blocks_automation_but_not_provider_enablement() -> None:
    provider = _provider()
    record_provider_quota(
        provider,
        DirectQuotaStatus(remaining=5, limit=25, window_seconds=64_800),
        observed_at=NOW,
    )

    assert automatic_quota_available(provider, at=NOW) is False
    assert provider.enabled is True
    assert provider.state is DirectProviderState.HEALTHY
    assert automatic_quota_available(provider, at=NOW + timedelta(hours=19)) is True


def test_expired_quota_window_does_not_reenable_disabled_provider() -> None:
    provider = _provider()
    record_provider_quota(
        provider,
        DirectQuotaStatus(remaining=5, limit=25, window_seconds=60),
        observed_at=NOW,
    )
    provider.enabled = False
    provider.state = DirectProviderState.DISABLED

    assert automatic_quota_available(provider, at=NOW.replace(minute=2)) is False


def test_quota_and_authentication_errors_update_provider_state_safely() -> None:
    quota_provider = _provider()
    record_provider_quota(
        quota_provider,
        DirectQuotaStatus(remaining=1, limit=25, window_seconds=64_800),
        observed_at=NOW,
    )
    record_provider_resolution_error(quota_provider, "source_quota_limited", observed_at=NOW)

    assert quota_provider.state is DirectProviderState.RATE_LIMITED
    assert quota_provider.last_error_code == "source_quota_limited"
    assert provider_quota_status(quota_provider).remaining == 0  # type: ignore[union-attr]
    assert provider_quota_status(quota_provider).reset_at is not None  # type: ignore[union-attr]

    auth_provider = _provider()
    record_provider_resolution_error(
        auth_provider,
        "source_authentication_required",
        observed_at=NOW,
    )

    assert auth_provider.state is DirectProviderState.AUTHENTICATION_REQUIRED
    assert auth_provider.last_error_code == "source_authentication_required"


def test_first_quota_error_uses_retry_hint_for_automatic_recovery() -> None:
    provider = _provider()

    record_provider_resolution_error(
        provider,
        "source_quota_limited",
        observed_at=NOW,
        retry_after_seconds=64_800,
    )

    quota = provider_quota_status(provider)
    assert quota is not None
    assert quota.remaining == 0
    assert quota.reset_at == NOW + timedelta(seconds=64_800)


def test_transient_source_failure_uses_bounded_automatic_backoff() -> None:
    provider = _provider()

    record_provider_resolution_error(provider, "source_unavailable", observed_at=NOW)

    assert provider.state is DirectProviderState.DEGRADED
    assert automatic_quota_available(provider, at=NOW) is False
    assert automatic_quota_available(provider, at=NOW.replace(minute=16)) is True


def test_expired_quota_window_recovers_provider_without_fabricating_capacity() -> None:
    provider = _provider()
    record_provider_quota(
        provider,
        DirectQuotaStatus(remaining=1, limit=25, window_seconds=60),
        observed_at=NOW,
    )
    record_provider_resolution_error(provider, "source_quota_limited", observed_at=NOW)

    assert automatic_quota_available(provider, at=NOW.replace(minute=2)) is True
    assert refresh_expired_provider_quota(provider, at=NOW.replace(minute=2)) is True
    assert provider.state is DirectProviderState.DEGRADED
    assert provider.last_error_code is None
    assert provider_quota_status(provider) is None
