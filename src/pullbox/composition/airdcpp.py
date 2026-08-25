"""AirDC++ runtime composition with feature-flag and exact-client isolation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from pullbox.core.encryption import decrypt_secret
from pullbox.models.client import DownloadClientConfig
from pullbox.models.download import DownloadClientType
from pullbox.providers.airdcpp.api_client import AirDcppApiClient
from pullbox.providers.airdcpp.socket_client import AirDcppSocketClient
from pullbox.providers.airdcpp.supervisor import (
    AirDcppSupervisor,
    AirDcppSupervisorConfig,
    AirDcppSupervisorRegistry,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_registry: AirDcppSupervisorRegistry | None = None


async def build_airdcpp_supervisor_configs(
    session: AsyncSession,
) -> tuple[AirDcppSupervisorConfig, ...]:
    """Load enabled AirDC++ clients and decrypt only their in-memory password."""
    result = await session.execute(
        select(DownloadClientConfig)
        .where(
            DownloadClientConfig.client_type == DownloadClientType.AIRDCPP,
            DownloadClientConfig.enabled.is_(True),
        )
        .options(selectinload(DownloadClientConfig.airdcpp_settings))
        .order_by(DownloadClientConfig.id)
    )
    configs: list[AirDcppSupervisorConfig] = []
    for client in result.scalars().all():
        settings = client.airdcpp_settings
        if settings is None or not client.username or not client.password:
            continue
        configs.append(
            AirDcppSupervisorConfig(
                config_id=client.id,
                client_identity=f"airdcpp:{client.id}",
                name=client.name,
                base_url=client.url,
                username=client.username,
                password=SecretStr(decrypt_secret(client.password)),
                request_timeout_seconds=settings.request_timeout_seconds,
                enabled=client.enabled,
            )
        )
    return tuple(configs)


async def start_airdcpp_supervisor_registry(
    session_factory: async_sessionmaker[AsyncSession] | Callable[[], AsyncSession],
    *,
    enabled: bool,
) -> AirDcppSupervisorRegistry | None:
    """Load local config and schedule remote work without delaying app readiness."""
    global _registry
    if not enabled:
        _registry = None
        return None

    registry = AirDcppSupervisorRegistry(supervisor_factory=_build_supervisor)
    async with session_factory() as session:
        configs = await build_airdcpp_supervisor_configs(session)
    await registry.apply(configs)
    _registry = registry
    return registry


def get_airdcpp_supervisor_registry() -> AirDcppSupervisorRegistry | None:
    """Return the process registry for search, queue, and health services."""
    return _registry


async def refresh_airdcpp_supervisor_registry(
    session_factory: async_sessionmaker[AsyncSession] | Callable[[], AsyncSession],
) -> None:
    """Apply committed config changes to only the affected supervisors."""
    registry = _registry
    if registry is None:
        return
    async with session_factory() as session:
        configs = await build_airdcpp_supervisor_configs(session)
    await registry.apply(configs)


async def stop_airdcpp_supervisor_registry() -> None:
    """Stop and clear the process registry, if it was enabled."""
    global _registry
    registry = _registry
    _registry = None
    if registry is not None:
        await registry.stop()


def _build_supervisor(config: AirDcppSupervisorConfig) -> AirDcppSupervisor:
    api_client = AirDcppApiClient(
        base_url=config.base_url,
        username=config.username,
        password=config.password.get_secret_value(),
        timeout_seconds=config.request_timeout_seconds,
    )
    socket_client = AirDcppSocketClient(
        base_url=config.base_url,
        timeout_seconds=config.request_timeout_seconds,
    )
    return AirDcppSupervisor(
        config=config,
        api_client=api_client,
        socket_client=socket_client,
    )
