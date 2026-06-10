"""Shared configuration resolver for runtime, host secret, and app settings.

This module provides the supported read path for application configuration:

1. Bootstrap/runtime settings from environment-backed ``PullboxSettings``
2. Persistent host secret from ``config.xml``
3. Application settings from ``system_config``

Feature code should depend on the helpers in this module instead of mixing
direct ``os.environ`` checks, ``config.xml`` reads, and database lookups.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse, urlunparse

from sqlalchemy import select

from pullbox.config import PullboxSettings, get_settings
from pullbox.core.config_file import ConfigFileProvider, get_config_provider
from pullbox.core.https_runtime import HTTPS_CONFIG_KEYS, https_runtime_config_values
from pullbox.core.secret_validation import validate_application_secret
from pullbox.models.config import DEFAULT_SYSTEM_CONFIG, SystemConfig

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


CONFIG_SOURCE_RUNTIME = "runtime"
CONFIG_SOURCE_HOST_SECRET = "host_secret"
CONFIG_SOURCE_DATABASE = "database"
CONFIG_SOURCE_DEFAULT = "default"
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


@dataclass(frozen=True, slots=True)
class ResolvedConfigValue:
    """Typed configuration value with source metadata for UI/status display."""

    key: str
    value: str
    source: str
    editable: bool


@dataclass(frozen=True, slots=True)
class RuntimeStatusSnapshot:
    """Runtime-managed values exposed as read-only status in the UI."""

    bind_address: ResolvedConfigValue
    port: ResolvedConfigValue
    data_dir: ResolvedConfigValue
    library_root: ResolvedConfigValue
    covers_dir: ResolvedConfigValue
    logs_dir: ResolvedConfigValue
    temp_dir: ResolvedConfigValue
    backup_dir: ResolvedConfigValue
    https_cert_root: ResolvedConfigValue


@dataclass(frozen=True, slots=True)
class AppIdentitySettings:
    """Editable application identity settings stored in ``system_config``."""

    instance_name: ResolvedConfigValue
    base_url: ResolvedConfigValue


@dataclass(frozen=True, slots=True)
class HttpsSettingsSnapshot:
    """HTTPS settings resolved for display and editability in the UI."""

    https_enabled: ResolvedConfigValue
    https_cert_path: ResolvedConfigValue
    https_key_path: ResolvedConfigValue


def get_runtime_settings() -> PullboxSettings:
    """Return the bootstrap/runtime settings singleton."""
    return get_settings()


def is_container_runtime() -> bool:
    """Return whether Pullbox appears to be running inside a container."""
    return Path("/.dockerenv").exists() or Path("/run/.containerenv").exists()


def resolve_runtime_service_url(url: str) -> str:
    """Normalize service URLs for the current runtime environment.

    When Pullbox runs inside a container, a saved loopback URL like
    ``http://localhost:8112`` points back at the Pullbox container itself,
    not the developer's host machine. Rewriting those loopback hosts to
    ``host.docker.internal`` preserves the expected "local machine" behavior
    for download clients and similar integrations.
    """
    raw = url.strip()
    if not raw or not is_container_runtime():
        return raw

    parsed = urlparse(raw)
    hostname = (parsed.hostname or "").strip().lower()
    if hostname not in _LOOPBACK_HOSTS:
        return raw

    replacement_host = "host.docker.internal"
    userinfo = ""
    if parsed.username:
        userinfo = parsed.username
        if parsed.password is not None:
            userinfo = f"{userinfo}:{parsed.password}"
        userinfo = f"{userinfo}@"

    port_suffix = f":{parsed.port}" if parsed.port is not None else ""
    netloc = f"{userinfo}{replacement_host}{port_suffix}"
    return urlunparse(parsed._replace(netloc=netloc))


def get_application_secret() -> str:
    """Return the shared application secret used for signing and encryption."""
    try:
        return get_config_provider().secret_key()
    except RuntimeError:
        settings = get_runtime_settings()
        if settings.secret_key.strip():
            secret = settings.secret_key.strip()
            validate_application_secret(secret)
            return secret

        provider = ConfigFileProvider(settings.data_dir / "config.xml")
        provider.ensure_config_exists()
        return provider.secret_key()


def get_runtime_status_snapshot() -> RuntimeStatusSnapshot:
    """Return runtime-managed status values sourced from bootstrap settings."""
    settings = get_runtime_settings()
    return RuntimeStatusSnapshot(
        bind_address=ResolvedConfigValue(
            key="bind_address",
            value=settings.bind_address,
            source=CONFIG_SOURCE_RUNTIME,
            editable=False,
        ),
        port=ResolvedConfigValue(
            key="port",
            value=str(settings.port),
            source=CONFIG_SOURCE_RUNTIME,
            editable=False,
        ),
        data_dir=ResolvedConfigValue(
            key="data_dir",
            value=str(settings.data_dir),
            source=CONFIG_SOURCE_RUNTIME,
            editable=False,
        ),
        library_root=ResolvedConfigValue(
            key="library_root",
            value=str(settings.library_root),
            source=CONFIG_SOURCE_RUNTIME,
            editable=False,
        ),
        covers_dir=ResolvedConfigValue(
            key="covers_dir",
            value=str(settings.covers_dir),
            source=CONFIG_SOURCE_RUNTIME,
            editable=False,
        ),
        logs_dir=ResolvedConfigValue(
            key="logs_dir",
            value=str(settings.logs_dir),
            source=CONFIG_SOURCE_RUNTIME,
            editable=False,
        ),
        temp_dir=ResolvedConfigValue(
            key="temp_dir",
            value=str(settings.temp_dir),
            source=CONFIG_SOURCE_RUNTIME,
            editable=False,
        ),
        backup_dir=ResolvedConfigValue(
            key="backup_dir",
            value=str(settings.backup_dir),
            source=CONFIG_SOURCE_RUNTIME,
            editable=False,
        ),
        https_cert_root=ResolvedConfigValue(
            key="https_cert_root",
            value=str(settings.https_cert_root),
            source=CONFIG_SOURCE_RUNTIME,
            editable=False,
        ),
    )


async def load_system_config_values(
    session: AsyncSession,
    keys: tuple[str, ...],
) -> dict[str, str]:
    """Load app settings from ``system_config`` with defaults for missing rows."""
    defaults = {key: DEFAULT_SYSTEM_CONFIG[key][0] for key in keys}
    result = await session.execute(select(SystemConfig).where(SystemConfig.key.in_(keys)))
    defaults.update({row.key: row.value for row in result.scalars().all()})
    return defaults


async def load_all_system_config_values(session: AsyncSession) -> dict[str, SystemConfig]:
    """Load all persisted ``system_config`` rows keyed by config key."""
    result = await session.execute(select(SystemConfig).order_by(SystemConfig.key))
    return {row.key: row for row in result.scalars().all()}


async def load_app_identity_settings(session: AsyncSession) -> AppIdentitySettings:
    """Load editable application identity settings with source metadata."""
    configs = await load_system_config_values(session, ("instance_name", "base_url"))
    persisted = await session.execute(
        select(SystemConfig.key).where(SystemConfig.key.in_(("instance_name", "base_url")))
    )
    persisted_keys = set(persisted.scalars().all())
    return AppIdentitySettings(
        instance_name=ResolvedConfigValue(
            key="instance_name",
            value=configs["instance_name"],
            source=CONFIG_SOURCE_DATABASE
            if "instance_name" in persisted_keys
            else CONFIG_SOURCE_DEFAULT,
            editable=True,
        ),
        base_url=ResolvedConfigValue(
            key="base_url",
            value=configs["base_url"],
            source=(
                CONFIG_SOURCE_DATABASE if "base_url" in persisted_keys else CONFIG_SOURCE_DEFAULT
            ),
            editable=True,
        ),
    )


async def load_https_settings_snapshot(session: AsyncSession) -> HttpsSettingsSnapshot:
    """Load HTTPS settings, overlaying runtime/env-managed values for the UI."""
    configs = await load_system_config_values(session, HTTPS_CONFIG_KEYS)
    persisted = await session.execute(
        select(SystemConfig.key).where(SystemConfig.key.in_(HTTPS_CONFIG_KEYS))
    )
    persisted_keys = set(persisted.scalars().all())
    runtime_values = https_runtime_config_values(settings=get_runtime_settings())

    def resolved(key: str) -> ResolvedConfigValue:
        if key in runtime_values:
            return ResolvedConfigValue(
                key=key,
                value=runtime_values[key],
                source=CONFIG_SOURCE_RUNTIME,
                editable=False,
            )
        return ResolvedConfigValue(
            key=key,
            value=configs[key],
            source=CONFIG_SOURCE_DATABASE if key in persisted_keys else CONFIG_SOURCE_DEFAULT,
            editable=True,
        )

    return HttpsSettingsSnapshot(
        https_enabled=resolved("https_enabled"),
        https_cert_path=resolved("https_cert_path"),
        https_key_path=resolved("https_key_path"),
    )


async def resolve_app_setting(
    session: AsyncSession,
    key: str,
) -> ResolvedConfigValue:
    """Resolve a single DB-backed application setting with its source metadata."""
    if key not in DEFAULT_SYSTEM_CONFIG:
        raise KeyError(f"Unknown system configuration key: {key}")

    row = await session.get(SystemConfig, key)
    if row is not None:
        return ResolvedConfigValue(
            key=key,
            value=row.value,
            source=CONFIG_SOURCE_DATABASE,
            editable=True,
        )

    default_value, _default_type = DEFAULT_SYSTEM_CONFIG[key]
    return ResolvedConfigValue(
        key=key,
        value=default_value,
        source=CONFIG_SOURCE_DEFAULT,
        editable=True,
    )


def parse_bool(value: str | bool | None) -> bool:
    """Parse a config bool-like value."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def get_int_setting(configs: dict[str, str], key: str, default: int) -> int:
    """Best-effort integer coercion for config values."""
    raw = configs.get(key, str(default))
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def normalize_base_url(value: str) -> str:
    """Validate and normalize the public/external base URL.

    Accepted forms:
    - ``http://localhost:8585``
    - ``https://comics.example.com``
    - ``https://comics.example.com/pullbox``
    """
    raw = value.strip()
    if not raw:
        raise ValueError("External URL cannot be empty.")

    parsed = urlparse(raw)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise ValueError("External URL must start with http:// or https://.")
    if not parsed.netloc:
        raise ValueError("External URL must include a hostname.")
    if parsed.params or parsed.query or parsed.fragment:
        raise ValueError("External URL cannot include params, query strings, or fragments.")

    path = parsed.path.rstrip("/")
    if path == "/":
        path = ""

    return urlunparse((scheme, parsed.netloc, path, "", "", ""))


def resolved_value_to_dict(value: ResolvedConfigValue) -> dict[str, Any]:
    """Serialize a resolved value for template contexts."""
    return {
        "key": value.key,
        "value": value.value,
        "source": value.source,
        "editable": value.editable,
    }


def runtime_snapshot_to_dict(snapshot: RuntimeStatusSnapshot) -> dict[str, dict[str, Any]]:
    """Serialize runtime status for template contexts."""
    return {
        "bind_address": resolved_value_to_dict(snapshot.bind_address),
        "port": resolved_value_to_dict(snapshot.port),
        "data_dir": resolved_value_to_dict(snapshot.data_dir),
        "library_root": resolved_value_to_dict(snapshot.library_root),
        "covers_dir": resolved_value_to_dict(snapshot.covers_dir),
        "logs_dir": resolved_value_to_dict(snapshot.logs_dir),
        "temp_dir": resolved_value_to_dict(snapshot.temp_dir),
        "backup_dir": resolved_value_to_dict(snapshot.backup_dir),
        "https_cert_root": resolved_value_to_dict(snapshot.https_cert_root),
    }


def https_settings_snapshot_to_dict(snapshot: HttpsSettingsSnapshot) -> dict[str, dict[str, Any]]:
    """Serialize HTTPS setting values for template contexts."""
    return {
        "https_enabled": resolved_value_to_dict(snapshot.https_enabled),
        "https_cert_path": resolved_value_to_dict(snapshot.https_cert_path),
        "https_key_path": resolved_value_to_dict(snapshot.https_key_path),
    }


def get_runtime_data_root() -> Path:
    """Return the runtime data directory."""
    return get_runtime_settings().data_dir
