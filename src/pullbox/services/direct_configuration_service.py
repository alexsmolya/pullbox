"""Write-only secret handling for direct providers and artifact hosts."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pullbox.core.encryption import decrypt_secret, encrypt_secret
from pullbox.core.exceptions import ValidationError
from pullbox.models.direct_acquisition import (
    DirectArtifactHostKind,
    DirectHostAccountState,
    DirectHostConfig,
    DirectProviderConfig,
    DirectProviderState,
    DirectProviderTrustLevel,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime


_SECRET_FIELD_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_MAX_SECRET_LENGTH = 16_384
_HOST_CREDENTIAL_FIELDS: dict[DirectArtifactHostKind, frozenset[str]] = {
    DirectArtifactHostKind.GENERIC_HTTPS: frozenset(),
    DirectArtifactHostKind.PIXELDRAIN: frozenset({"api_key"}),
    DirectArtifactHostKind.MEGA: frozenset({"session"}),
    DirectArtifactHostKind.ROOTZ: frozenset(),
    DirectArtifactHostKind.MEDIAFIRE: frozenset(),
    DirectArtifactHostKind.TERABOX: frozenset({"session_token", "cookie"}),
    DirectArtifactHostKind.DATANODES: frozenset({"username", "password"}),
}
_REQUIRED_HOST_CREDENTIAL_FIELDS: dict[DirectArtifactHostKind, frozenset[str]] = {
    DirectArtifactHostKind.DATANODES: frozenset({"username", "password"}),
}
_HOST_CREDENTIAL_FIELD_ORDER: dict[DirectArtifactHostKind, tuple[str, ...]] = {
    DirectArtifactHostKind.DATANODES: ("username", "password"),
}


def credential_fields_for_host(host_kind: DirectArtifactHostKind) -> tuple[str, ...]:
    """Return the closed write-only credential contract for one host."""
    return _HOST_CREDENTIAL_FIELD_ORDER.get(
        host_kind,
        tuple(sorted(_HOST_CREDENTIAL_FIELDS[host_kind])),
    )


@dataclass(frozen=True, slots=True)
class DirectProviderConfigRead:
    """Secret-free provider configuration projection for future APIs."""

    provider_id: str
    display_name: str
    endpoint: str
    enabled: bool
    priority: int
    state: DirectProviderState
    negotiated_protocol: str | None
    trust_level: DirectProviderTrustLevel
    resolver_enabled: bool
    bearer_token_configured: bool
    configuration_secret_fields: tuple[str, ...]
    last_health_at: datetime | None
    last_tested_at: datetime | None
    last_error_code: str | None


@dataclass(frozen=True, slots=True)
class DirectHostConfigRead:
    """Secret-free artifact-host configuration projection for future APIs."""

    host_kind: DirectArtifactHostKind
    enabled: bool
    preference: int
    account_state: DirectHostAccountState
    credentials_configured: bool
    credential_fields: tuple[str, ...]
    redacted_identity: str | None
    quota_remaining: int | None
    quota_reset_at: datetime | None
    last_tested_at: datetime | None
    last_error_code: str | None


@dataclass(frozen=True, slots=True)
class ProviderSecretMaterial:
    """Decrypted provider material scoped to one active operation."""

    bearer_token: str | None = field(repr=False)
    configuration: dict[str, str] = field(repr=False)


@dataclass(frozen=True, slots=True)
class HostCredentialMaterial:
    """Decrypted host credentials scoped to one active operation."""

    credentials: dict[str, str] = field(repr=False)


def write_provider_bearer_token(
    config: DirectProviderConfig,
    bearer_token: str | None,
) -> None:
    """Encrypt a provider bearer token, or clear it when blank."""
    if not bearer_token:
        config.encrypted_bearer_token = None
    else:
        _validate_plaintext_secret(bearer_token)
        config.encrypted_bearer_token = encrypt_secret(bearer_token)
    _reset_provider_test_state(config)


def clear_provider_bearer_token(config: DirectProviderConfig) -> None:
    """Explicitly clear a configured provider bearer token."""
    write_provider_bearer_token(config, None)


def update_provider_configuration_secrets(
    config: DirectProviderConfig,
    updates: Mapping[str, str | None],
) -> None:
    """Merge encrypted provider configuration secret updates atomically."""
    _validate_secret_updates(updates)
    encrypted = _encrypted_mapping(config.encrypted_configuration)
    _apply_secret_updates(encrypted, updates)
    config.encrypted_configuration = _json_secret_mapping(encrypted)
    config.configuration_metadata = _with_configured_fields(
        config.configuration_metadata,
        "configured_secret_fields",
        encrypted,
    )
    _reset_provider_test_state(config)


def update_host_credentials(
    config: DirectHostConfig,
    updates: Mapping[str, str | None],
) -> None:
    """Merge encrypted credentials allowed for the selected host kind."""
    _validate_host_updates(config.host_kind, updates)
    encrypted = _encrypted_mapping(config.encrypted_credentials)
    _apply_secret_updates(encrypted, updates)
    _validate_complete_host_credentials(config.host_kind, set(encrypted))
    config.encrypted_credentials = _json_secret_mapping(encrypted)
    config.account_metadata = _with_configured_fields(
        config.account_metadata,
        "configured_credential_fields",
        encrypted,
    )
    config.account_state = (
        DirectHostAccountState.UNKNOWN if encrypted else DirectHostAccountState.NOT_CONFIGURED
    )
    config.quota_remaining = None
    config.quota_reset_at = None
    config.last_tested_at = None
    config.last_error_code = None


def read_provider_config(config: DirectProviderConfig) -> DirectProviderConfigRead:
    """Build a provider read model without ciphertext or plaintext secrets."""
    fields = tuple(sorted(_encrypted_mapping(config.encrypted_configuration)))
    return DirectProviderConfigRead(
        provider_id=config.provider_id,
        display_name=config.display_name,
        endpoint=config.endpoint,
        enabled=bool(config.enabled),
        priority=config.priority if config.priority is not None else 50,
        state=config.state or DirectProviderState.DISABLED,
        negotiated_protocol=config.negotiated_protocol,
        trust_level=config.trust_level or DirectProviderTrustLevel.CUSTOM,
        resolver_enabled=bool(config.resolver_enabled),
        bearer_token_configured=bool(config.encrypted_bearer_token),
        configuration_secret_fields=fields,
        last_health_at=config.last_health_at,
        last_tested_at=config.last_tested_at,
        last_error_code=config.last_error_code,
    )


def read_host_config(config: DirectHostConfig) -> DirectHostConfigRead:
    """Build a host read model without ciphertext or plaintext credentials."""
    credentials = _encrypted_mapping(config.encrypted_credentials)
    metadata = config.account_metadata or {}
    identity = metadata.get("redacted_identity")
    return DirectHostConfigRead(
        host_kind=config.host_kind,
        enabled=bool(config.enabled),
        preference=config.preference if config.preference is not None else 50,
        account_state=config.account_state or DirectHostAccountState.NOT_CONFIGURED,
        credentials_configured=bool(credentials),
        credential_fields=tuple(sorted(credentials)),
        redacted_identity=identity if isinstance(identity, str) else None,
        quota_remaining=config.quota_remaining,
        quota_reset_at=config.quota_reset_at,
        last_tested_at=config.last_tested_at,
        last_error_code=config.last_error_code,
    )


def load_provider_secret_material(
    config: DirectProviderConfig,
) -> ProviderSecretMaterial:
    """Decrypt provider secrets only for an active provider operation."""
    token = decrypt_secret(config.encrypted_bearer_token) if config.encrypted_bearer_token else None
    return ProviderSecretMaterial(
        bearer_token=token,
        configuration=_decrypt_mapping(config.encrypted_configuration),
    )


def load_host_credential_material(config: DirectHostConfig) -> HostCredentialMaterial:
    """Decrypt host credentials only for an active host operation."""
    return HostCredentialMaterial(credentials=_decrypt_mapping(config.encrypted_credentials))


def _validate_host_updates(
    host_kind: DirectArtifactHostKind,
    updates: Mapping[str, str | None],
) -> None:
    _validate_secret_updates(updates)
    allowed = _HOST_CREDENTIAL_FIELDS[host_kind]
    unsupported = sorted(key for key, value in updates.items() if value and key not in allowed)
    if unsupported:
        if not allowed:
            raise ValidationError(f"{host_kind.value} does not accept credentials.")
        raise ValidationError(
            f"Unsupported credential field for {host_kind.value}: {unsupported[0]}."
        )


def _validate_complete_host_credentials(
    host_kind: DirectArtifactHostKind,
    configured_fields: set[str],
) -> None:
    required = _REQUIRED_HOST_CREDENTIAL_FIELDS.get(host_kind)
    if required and configured_fields and not required.issubset(configured_fields):
        raise ValidationError(f"{host_kind.value} requires both username and password.")


def _validate_secret_updates(updates: Mapping[str, str | None]) -> None:
    for field_name, value in updates.items():
        if not _SECRET_FIELD_NAME.fullmatch(field_name):
            raise ValidationError("Invalid secret field name.")
        if value:
            _validate_plaintext_secret(value)


def _validate_plaintext_secret(value: str) -> None:
    if not isinstance(value, str):
        raise ValidationError("A plaintext secret value must be a string.")
    if value.startswith("enc:"):
        raise ValidationError("Expected a plaintext secret value, not stored ciphertext.")
    if len(value) > _MAX_SECRET_LENGTH:
        raise ValidationError("The plaintext secret value exceeds the supported length.")


def _encrypted_mapping(stored: object) -> dict[str, str]:
    if stored is None:
        return {}
    if not isinstance(stored, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in stored.items()
    ):
        raise ValueError("Stored direct-download secret data is malformed.")
    return dict(stored)


def _apply_secret_updates(
    encrypted: dict[str, str],
    updates: Mapping[str, str | None],
) -> None:
    for field_name, value in updates.items():
        if value:
            encrypted[field_name] = encrypt_secret(value)
        else:
            encrypted.pop(field_name, None)


def _decrypt_mapping(stored: object) -> dict[str, str]:
    return {
        field_name: decrypt_secret(ciphertext)
        for field_name, ciphertext in _encrypted_mapping(stored).items()
    }


def _json_secret_mapping(encrypted: Mapping[str, str]) -> dict[str, object]:
    return dict(encrypted)


def _with_configured_fields(
    metadata: object,
    field_name: str,
    encrypted: Mapping[str, str],
) -> dict[str, object]:
    result = dict(metadata) if isinstance(metadata, dict) else {}
    result[field_name] = sorted(encrypted)
    return result


def _reset_provider_test_state(config: DirectProviderConfig) -> None:
    config.last_tested_at = None
    config.last_error_code = None
