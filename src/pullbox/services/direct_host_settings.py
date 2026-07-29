"""Closed artifact-host settings with write-only encrypted credentials."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import select

from pullbox.core.exceptions import ValidationError
from pullbox.models.direct_acquisition import (
    DirectArtifactHostKind,
    DirectHostAccountState,
    DirectHostConfig,
)
from pullbox.services.direct_configuration_service import (
    credential_fields_for_host,
    read_host_config,
    update_host_credentials,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

    from sqlalchemy.ext.asyncio import AsyncSession


_DEFAULT_PREFERENCE = 50
_MAX_PREFERENCE = 1_000
_ACCOUNT_REQUIRED_HOSTS = frozenset(
    {
        DirectArtifactHostKind.TERABOX,
        DirectArtifactHostKind.DATANODES,
    }
)
_REQUIRED_ACCOUNT_FIELDS: dict[DirectArtifactHostKind, frozenset[str]] = {
    DirectArtifactHostKind.DATANODES: frozenset({"username", "password"}),
}


@dataclass(frozen=True, slots=True)
class DirectHostSettingRead:
    """Secret-free host setting returned to operator-facing callers."""

    id: int | None
    host_kind: DirectArtifactHostKind
    enabled: bool
    preference: int
    account_state: DirectHostAccountState
    credentials_configured: bool
    configured_credential_fields: tuple[str, ...]
    allowed_credential_fields: tuple[str, ...]
    redacted_identity: str | None
    quota_remaining: int | None
    quota_reset_at: datetime | None
    last_tested_at: datetime | None
    last_error_code: str | None


async def list_direct_host_settings(session: AsyncSession) -> list[DirectHostSettingRead]:
    """List every native host without materializing unedited defaults."""
    rows = (
        await session.execute(select(DirectHostConfig).order_by(DirectHostConfig.id.asc()))
    ).scalars()
    configured = {row.host_kind: row for row in rows}
    return [_read_setting(kind, configured.get(kind)) for kind in DirectArtifactHostKind]


async def update_direct_host_setting(
    session: AsyncSession,
    host_kind: DirectArtifactHostKind,
    *,
    enabled: bool | None,
    preference: int | None,
    credential_updates: Mapping[str, str | None] | None,
) -> DirectHostSettingRead:
    """Upsert one host setting while preserving omitted credentials."""
    config = (
        await session.execute(
            select(DirectHostConfig).where(DirectHostConfig.host_kind == host_kind)
        )
    ).scalar_one_or_none()
    current_fields = set(read_host_config(config).credential_fields) if config else set()
    next_fields = _prospective_credential_fields(current_fields, credential_updates)
    next_enabled = bool(config.enabled) if config is not None and enabled is None else bool(enabled)
    next_preference = (
        config.preference
        if config is not None and preference is None
        else _DEFAULT_PREFERENCE
        if preference is None
        else preference
    )

    _validate_preference(next_preference)
    _validate_supported_credential_fields(host_kind, next_fields)
    _validate_required_account(host_kind, next_enabled, next_fields)

    if config is None:
        config = DirectHostConfig(host_kind=host_kind)
        session.add(config)
    if credential_updates is not None:
        update_host_credentials(config, credential_updates)
    config.enabled = next_enabled
    config.preference = next_preference
    await session.commit()
    await session.refresh(config)
    return _read_setting(host_kind, config)


def _read_setting(
    host_kind: DirectArtifactHostKind,
    config: DirectHostConfig | None,
) -> DirectHostSettingRead:
    if config is None:
        return DirectHostSettingRead(
            id=None,
            host_kind=host_kind,
            enabled=False,
            preference=_DEFAULT_PREFERENCE,
            account_state=DirectHostAccountState.NOT_CONFIGURED,
            credentials_configured=False,
            configured_credential_fields=(),
            allowed_credential_fields=credential_fields_for_host(host_kind),
            redacted_identity=None,
            quota_remaining=None,
            quota_reset_at=None,
            last_tested_at=None,
            last_error_code=None,
        )

    view = read_host_config(config)
    return DirectHostSettingRead(
        id=config.id,
        host_kind=host_kind,
        enabled=view.enabled,
        preference=view.preference,
        account_state=view.account_state,
        credentials_configured=view.credentials_configured,
        configured_credential_fields=view.credential_fields,
        allowed_credential_fields=credential_fields_for_host(host_kind),
        redacted_identity=view.redacted_identity,
        quota_remaining=view.quota_remaining,
        quota_reset_at=view.quota_reset_at,
        last_tested_at=view.last_tested_at,
        last_error_code=view.last_error_code,
    )


def _prospective_credential_fields(
    current_fields: set[str],
    updates: Mapping[str, str | None] | None,
) -> set[str]:
    fields = set(current_fields)
    for name, value in (updates or {}).items():
        if value:
            fields.add(name)
        else:
            fields.discard(name)
    return fields


def _validate_preference(preference: int) -> None:
    if not 0 <= preference <= _MAX_PREFERENCE:
        raise ValidationError("Artifact-host preference must be between 0 and 1000.")


def _validate_required_account(
    host_kind: DirectArtifactHostKind,
    enabled: bool,
    credential_fields: set[str],
) -> None:
    required = _REQUIRED_ACCOUNT_FIELDS.get(host_kind)
    if required and credential_fields and not required.issubset(credential_fields):
        raise ValidationError(f"{host_kind.value} requires both username and password.")
    if enabled and required and not required.issubset(credential_fields):
        raise ValidationError(f"{host_kind.value} requires both username and password.")
    if enabled and host_kind in _ACCOUNT_REQUIRED_HOSTS and not credential_fields:
        raise ValidationError(f"{host_kind.value} requires an account session before enabling.")


def _validate_supported_credential_fields(
    host_kind: DirectArtifactHostKind,
    credential_fields: set[str],
) -> None:
    allowed = set(credential_fields_for_host(host_kind))
    unsupported = sorted(credential_fields - allowed)
    if unsupported:
        if not allowed:
            raise ValidationError(f"{host_kind.value} does not accept credentials.")
        raise ValidationError(
            f"Unsupported credential field for {host_kind.value}: {unsupported[0]}."
        )
