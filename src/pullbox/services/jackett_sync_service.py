"""Persistence and lifecycle rules for Jackett-managed trackers."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select

from pullbox.core.encryption import decrypt_secret, encrypt_secret
from pullbox.core.exceptions import NotFoundError
from pullbox.models.config import SystemConfig
from pullbox.models.indexer import IndexerConfig, IndexerSource, IndexerType
from pullbox.providers.indexer.jackett import JackettClient
from pullbox.schemas.indexer import IndexerResponse, JackettSyncResult

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


def _redact(indexer: IndexerConfig) -> IndexerResponse:
    return IndexerResponse.model_validate(
        {
            "id": indexer.id,
            "name": indexer.name,
            "indexer_type": indexer.indexer_type,
            "url": indexer.url,
            "has_api_key": bool(indexer.api_key),
            "enabled": indexer.enabled,
            "priority": indexer.priority,
            "categories": indexer.categories,
            "source": indexer.source,
            "prowlarr_indexer_id": indexer.prowlarr_indexer_id,
            "manager_indexer_id": indexer.manager_indexer_id,
            "manager_available": indexer.manager_available,
            "enable_rss": indexer.enable_rss,
            "enable_automatic_search": indexer.enable_automatic_search,
            "enable_interactive_search": indexer.enable_interactive_search,
            "resolver_enabled": indexer.resolver_enabled,
            "last_success_at": indexer.last_success_at,
            "last_failure_at": indexer.last_failure_at,
            "last_error": indexer.last_error,
            "failure_count": indexer.failure_count,
            "disabled_until": indexer.disabled_until,
            "created_at": indexer.created_at,
            "updated_at": indexer.updated_at,
        }
    )


async def test_jackett_credentials(url: str, api_key: str) -> dict[str, object]:
    client = JackettClient(url=url, api_key=api_key)
    try:
        result = await client.test_connection()
    finally:
        await client.close()
    return {
        "healthy": result.healthy,
        "message": result.message,
        "response_time_ms": result.response_time_ms,
    }


async def load_jackett_credentials(session: AsyncSession) -> tuple[str, str]:
    rows = await session.execute(
        select(SystemConfig).where(SystemConfig.key.in_(("jackett_url", "jackett_api_key")))
    )
    configs = {row.key: row.value for row in rows.scalars().all()}
    url = str(configs.get("jackett_url") or "").strip()
    encrypted_key = str(configs.get("jackett_api_key") or "")
    if not url or not encrypted_key:
        raise NotFoundError("Jackett credentials", 0)
    return url, decrypt_secret(encrypted_key)


async def sync_jackett(
    session: AsyncSession,
    *,
    url: str,
    api_key: str,
) -> JackettSyncResult:
    """Discover Jackett trackers while preserving Pullbox-owned controls."""
    base_url = url.rstrip("/")
    client = JackettClient(url=base_url, api_key=api_key)
    try:
        remote_indexers = await client.get_configured_indexers()
    except Exception as exc:
        logger.warning("jackett_sync_failed", error_type=type(exc).__name__)
        raise NotFoundError("Jackett", 0) from exc
    finally:
        await client.close()

    encrypted_key = encrypt_secret(api_key)
    existing_result = await session.execute(
        select(IndexerConfig).where(IndexerConfig.source == IndexerSource.JACKETT)
    )
    existing_by_id = {
        indexer.manager_indexer_id: indexer
        for indexer in existing_result.scalars().all()
        if indexer.manager_indexer_id
    }

    added = 0
    updated = 0
    retired = 0
    reactivated = 0
    seen_ids: set[str] = set()

    for remote in remote_indexers:
        if remote.id in seen_ids:
            continue
        seen_ids.add(remote.id)
        display_name = f"{remote.name} (Jackett)"
        feed_url = f"{base_url}/api/v2.0/indexers/{remote.id}/results/torznab"
        capabilities_json = json.dumps(
            {
                "description": remote.description,
                "categories": list(remote.categories),
                "search_modes": list(remote.search_modes),
            },
            sort_keys=True,
        )

        existing = existing_by_id.get(remote.id)
        if existing is not None:
            if not existing.manager_available:
                reactivated += 1
            existing.name = display_name
            existing.indexer_type = IndexerType.TORZNAB
            existing.url = feed_url
            existing.api_key = encrypted_key
            existing.manager_available = True
            existing.resolver_enabled = False
            existing.capabilities_json = capabilities_json
            updated += 1
            continue

        indexer = IndexerConfig(
            name=display_name,
            indexer_type=IndexerType.TORZNAB,
            url=feed_url,
            api_key=encrypted_key,
            enabled=True,
            priority=50,
            categories=_default_comic_categories(remote.categories),
            source=IndexerSource.JACKETT,
            manager_indexer_id=remote.id,
            manager_available=True,
            resolver_enabled=False,
            capabilities_json=capabilities_json,
        )
        session.add(indexer)
        added += 1

    for manager_id, indexer in existing_by_id.items():
        if manager_id not in seen_ids and indexer.manager_available:
            indexer.manager_available = False
            retired += 1

    await _save_connection_settings(session, base_url, encrypted_key)
    await session.flush()

    active_result = await session.execute(
        select(IndexerConfig)
        .where(
            IndexerConfig.source == IndexerSource.JACKETT,
            IndexerConfig.manager_available.is_(True),
        )
        .order_by(IndexerConfig.priority, IndexerConfig.name)
    )
    active = list(active_result.scalars().all())
    logger.info(
        "jackett_sync_complete",
        added=added,
        updated=updated,
        retired=retired,
        reactivated=reactivated,
        total=len(active),
    )
    return JackettSyncResult(
        added=added,
        updated=updated,
        retired=retired,
        reactivated=reactivated,
        total=len(active),
        indexers=[_redact(indexer) for indexer in active],
    )


async def _save_connection_settings(
    session: AsyncSession,
    base_url: str,
    encrypted_key: str,
) -> None:
    for key, value, value_type in (
        ("jackett_url", base_url, "string"),
        ("jackett_api_key", encrypted_key, "secret"),
    ):
        config = await session.get(SystemConfig, key)
        if config is None:
            session.add(SystemConfig(key=key, value=value, value_type=value_type))
        else:
            config.value = value
            config.value_type = value_type


def _default_comic_categories(categories: tuple[str, ...]) -> str | None:
    if "7030" in categories:
        return "7030"
    if "7000" in categories:
        return "7000"
    return None
