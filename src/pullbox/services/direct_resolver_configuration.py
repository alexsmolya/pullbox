"""Write-only resolver authentication and secret-free configuration reads."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pullbox.core.encryption import decrypt_secret, encrypt_secret
from pullbox.core.exceptions import ValidationError
from pullbox.models.direct_acquisition import DirectResolverConfig, DirectResolverState

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime

_HEADER_NAME = re.compile(r"[A-Za-z][A-Za-z0-9-]{0,63}\Z")
_MAX_HEADERS = 4
_MAX_HEADER_VALUE = 16_384
_FORBIDDEN_HEADERS = frozenset(
    {
        "connection",
        "content-length",
        "content-type",
        "cookie",
        "host",
        "proxy-authenticate",
        "proxy-authorization",
        "set-cookie",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)


@dataclass(frozen=True, slots=True)
class DirectResolverConfigRead:
    name: str
    endpoint: str
    enabled: bool
    state: DirectResolverState
    allow_private_http: bool
    timeout_seconds: int
    max_concurrency: int
    auth_headers_configured: bool
    auth_header_names: tuple[str, ...]
    last_health_at: datetime | None
    last_tested_at: datetime | None
    last_error_code: str | None


@dataclass(frozen=True, slots=True)
class ResolverAuthMaterial:
    headers: dict[str, str] = field(repr=False)


def update_resolver_auth_headers(
    config: DirectResolverConfig,
    updates: Mapping[str, str | None],
) -> None:
    """Merge write-only resolver auth headers and reset stale health state."""
    current = _stored_headers(config.encrypted_auth_headers)
    normalized_updates = {_validate_header_name(name): value for name, value in updates.items()}
    resulting_names = set(current)
    for name, value in normalized_updates.items():
        if value:
            resulting_names.add(name)
        else:
            resulting_names.discard(name)
    if len(resulting_names) > _MAX_HEADERS:
        raise ValidationError(f"At most {_MAX_HEADERS} resolver auth headers are supported.")

    for name, value in normalized_updates.items():
        if value:
            if not isinstance(value, str) or len(value) > _MAX_HEADER_VALUE:
                raise ValidationError("Resolver auth header values must be bounded strings.")
            if "\r" in value or "\n" in value:
                raise ValidationError("Resolver auth header values cannot contain line breaks.")
            if value.startswith("enc:"):
                raise ValidationError("Expected a plaintext resolver auth header value.")
            current[name] = encrypt_secret(value)
        else:
            current.pop(name, None)

    config.encrypted_auth_headers = dict(current)
    config.auth_metadata = {"configured_header_names": sorted(current)}
    config.state = DirectResolverState.UNKNOWN if config.enabled else DirectResolverState.DISABLED
    config.last_health_at = None
    config.last_tested_at = None
    config.last_error_code = None


def load_resolver_auth_headers(config: DirectResolverConfig) -> ResolverAuthMaterial:
    """Decrypt resolver auth only for one active request boundary."""
    return ResolverAuthMaterial(
        headers={
            name: decrypt_secret(ciphertext)
            for name, ciphertext in _stored_headers(config.encrypted_auth_headers).items()
        }
    )


def read_resolver_config(config: DirectResolverConfig) -> DirectResolverConfigRead:
    """Return a projection that exposes header names but never values."""
    headers = _stored_headers(config.encrypted_auth_headers)
    return DirectResolverConfigRead(
        name=config.name,
        endpoint=config.endpoint,
        enabled=bool(config.enabled),
        state=config.state or DirectResolverState.DISABLED,
        allow_private_http=bool(config.allow_private_http),
        timeout_seconds=config.timeout_seconds or 60,
        max_concurrency=config.max_concurrency or 1,
        auth_headers_configured=bool(headers),
        auth_header_names=tuple(sorted(headers)),
        last_health_at=config.last_health_at,
        last_tested_at=config.last_tested_at,
        last_error_code=config.last_error_code,
    )


def _validate_header_name(raw_name: str) -> str:
    if not isinstance(raw_name, str) or not _HEADER_NAME.fullmatch(raw_name):
        raise ValidationError("Resolver auth header names must use HTTP token characters.")
    if raw_name.casefold() in _FORBIDDEN_HEADERS or raw_name.casefold().startswith("proxy-"):
        raise ValidationError(f"Resolver auth header '{raw_name}' is not permitted.")
    return raw_name


def _stored_headers(stored: object) -> dict[str, str]:
    if stored is None:
        return {}
    if not isinstance(stored, dict) or not all(
        isinstance(name, str) and isinstance(value, str) for name, value in stored.items()
    ):
        raise ValueError("Stored resolver auth headers are malformed.")
    return dict(stored)
