"""Download client API routes — CRUD and test connection."""

from datetime import UTC, datetime

import httpx
import structlog
from fastapi import APIRouter
from sqlalchemy import select

from pullbox.api.deps import DbSession, InteractiveOperatorUser
from pullbox.core.encryption import decrypt_secret, encrypt_secret
from pullbox.core.exceptions import NotFoundError, ProviderError
from pullbox.models.client import DownloadClientConfig
from pullbox.schemas.client import ClientCreate, ClientResponse, ClientUpdate

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/clients", tags=["clients"], include_in_schema=False)


# ── Helpers ───────────────────────────────────────────────────────────


def _redact_client(client: DownloadClientConfig) -> dict[str, object]:
    """Build response dict with secrets redacted."""
    return {
        "id": client.id,
        "name": client.name,
        "client_type": client.client_type,
        "url": client.url,
        "enabled": client.enabled,
        "priority": client.priority,
        "has_api_key": client.api_key is not None and len(client.api_key) > 0,
        "username": client.username,
        "has_password": client.password is not None and len(client.password) > 0,
        "category": client.category,
        "download_dir": client.download_dir,
        "remote_path": client.remote_path,
        # SABnzbd
        "sab_priority": client.sab_priority,
        "sab_post_processing": client.sab_post_processing,
        # qBittorrent
        "qbt_content_layout": client.qbt_content_layout,
        "qbt_ratio_limit": client.qbt_ratio_limit,
        "qbt_seeding_time_limit": client.qbt_seeding_time_limit,
        # NZBGet
        "nzbget_priority": client.nzbget_priority,
        "nzbget_post_processing": client.nzbget_post_processing,
        # Transmission
        "transmission_bandwidth_priority": client.transmission_bandwidth_priority,
        "transmission_seed_ratio_limit": client.transmission_seed_ratio_limit,
        "transmission_seed_idle_limit": client.transmission_seed_idle_limit,
        # Deluge
        "deluge_label": client.deluge_label,
        "deluge_max_ratio": client.deluge_max_ratio,
        "deluge_move_completed_path": client.deluge_move_completed_path,
        # Health
        "last_success_at": client.last_success_at,
        "last_failure_at": client.last_failure_at,
        "last_error": client.last_error,
        "last_test_message": client.last_test_message,
        "created_at": client.created_at,
        "updated_at": client.updated_at,
    }


def _decryption_failure_response() -> dict[str, object]:
    """Return a failed test result for unreadable stored credentials."""
    return {
        "healthy": False,
        "message": (
            "Saved credentials could not be decrypted. Re-enter and save this "
            "client configuration, then test again."
        ),
        "response_time_ms": 0.0,
    }


# ── List ─────────────────────────────────────────────────────────────


@router.get("", response_model=list[ClientResponse])
async def list_clients(
    _user: InteractiveOperatorUser,
    session: DbSession,
) -> list[ClientResponse]:
    """List all configured download clients."""
    result = await session.execute(
        select(DownloadClientConfig).order_by(
            DownloadClientConfig.priority, DownloadClientConfig.name
        )
    )
    clients = result.scalars().all()
    return [ClientResponse.model_validate(_redact_client(c)) for c in clients]


# ── Get single ──────────────────────────────────────────────────────


@router.get("/{client_id}", response_model=ClientResponse)
async def get_client(
    client_id: int,
    _user: InteractiveOperatorUser,
    session: DbSession,
) -> ClientResponse:
    """Get a single download client configuration."""
    client = await session.get(DownloadClientConfig, client_id)
    if not client:
        raise NotFoundError("DownloadClient", client_id)
    return ClientResponse.model_validate(_redact_client(client))


# ── Create ───────────────────────────────────────────────────────────


@router.post("", response_model=ClientResponse, status_code=201)
async def add_client(
    body: ClientCreate,
    _user: InteractiveOperatorUser,
    session: DbSession,
) -> ClientResponse:
    """Add a new download client configuration."""
    # Only one instance per client type allowed
    from pullbox.core.exceptions import ValidationError

    existing = await session.execute(
        select(DownloadClientConfig).where(DownloadClientConfig.client_type == body.client_type)
    )
    if existing.scalar_one_or_none():
        raise ValidationError(
            f"A {body.client_type.value} client is already configured. "
            "Only one instance per client type is allowed."
        )

    client = DownloadClientConfig(
        name=body.name,
        client_type=body.client_type,
        url=body.url,
        enabled=body.enabled,
        priority=body.priority,
        api_key=encrypt_secret(body.api_key) if body.api_key else body.api_key,
        username=body.username,
        password=encrypt_secret(body.password) if body.password else body.password,
        category=body.category,
        download_dir=body.download_dir,
        remote_path=body.remote_path,
        sab_priority=body.sab_priority,
        sab_post_processing=body.sab_post_processing,
        qbt_content_layout=body.qbt_content_layout,
        qbt_ratio_limit=body.qbt_ratio_limit,
        qbt_seeding_time_limit=body.qbt_seeding_time_limit,
        nzbget_priority=body.nzbget_priority,
        nzbget_post_processing=body.nzbget_post_processing,
        transmission_bandwidth_priority=body.transmission_bandwidth_priority,
        transmission_seed_ratio_limit=body.transmission_seed_ratio_limit,
        transmission_seed_idle_limit=body.transmission_seed_idle_limit,
        deluge_label=body.deluge_label,
        deluge_max_ratio=body.deluge_max_ratio,
        deluge_move_completed_path=body.deluge_move_completed_path,
    )
    session.add(client)
    await session.flush()
    return ClientResponse.model_validate(_redact_client(client))


# ── Update ───────────────────────────────────────────────────────────


@router.put("/{client_id}", response_model=ClientResponse)
async def update_client(
    client_id: int,
    body: ClientUpdate,
    _user: InteractiveOperatorUser,
    session: DbSession,
) -> ClientResponse:
    """Update a download client configuration."""
    client: DownloadClientConfig | None = await session.get(DownloadClientConfig, client_id)
    if not client:
        raise NotFoundError("DownloadClient", client_id)

    update_data = body.model_dump(exclude_unset=True)

    # Encrypt secrets if provided; omitted fields keep existing encrypted value
    if update_data.get("api_key"):
        update_data["api_key"] = encrypt_secret(update_data["api_key"])
    elif "api_key" in update_data and not update_data["api_key"]:
        # Empty string or None → remove the key
        pass

    if update_data.get("password"):
        update_data["password"] = encrypt_secret(update_data["password"])
    elif "password" in update_data and not update_data["password"]:
        # Empty string submitted → keep existing (don't wipe on edit)
        del update_data["password"]

    for field, value in update_data.items():
        setattr(client, field, value)

    await session.flush()
    await session.refresh(client)
    return ClientResponse.model_validate(_redact_client(client))


# ── Delete ───────────────────────────────────────────────────────────


@router.delete("/{client_id}", status_code=204)
async def delete_client(
    client_id: int,
    _user: InteractiveOperatorUser,
    session: DbSession,
) -> None:
    """Remove a download client configuration."""
    client = await session.get(DownloadClientConfig, client_id)
    if not client:
        raise NotFoundError("DownloadClient", client_id)
    await session.delete(client)


# ── Test Connection ──────────────────────────────────────────────────


@router.post("/test", status_code=200)
async def test_client_inline(
    body: ClientCreate,
    _user: InteractiveOperatorUser,
    session: DbSession,
    existing_id: int | None = None,
) -> dict[str, object]:
    """Test connectivity using form values.

    When editing an existing client and credentials are left blank,
    pass ``existing_id`` to fill in stored (encrypted) credentials.
    """
    from pullbox.providers.download.deluge import DelugeClient
    from pullbox.providers.download.nzbget import NZBGetClient
    from pullbox.providers.download.qbittorrent import QBittorrentClient
    from pullbox.providers.download.sabnzbd import SABnzbdClient
    from pullbox.providers.download.transmission import TransmissionClient

    # For edit mode: fill blank credentials from stored config
    api_key = body.api_key or ""
    username = body.username or ""
    password = body.password or ""

    if existing_id and (not api_key or not password):
        saved = await session.get(DownloadClientConfig, existing_id)
        if saved:
            try:
                if not api_key and saved.api_key:
                    api_key = decrypt_secret(saved.api_key)
                if not username and saved.username:
                    username = saved.username
                if not password and saved.password:
                    password = decrypt_secret(saved.password)
            except ValueError as exc:
                message = str(_decryption_failure_response()["message"])
                saved.last_failure_at = datetime.now(UTC)
                saved.last_error = message
                saved.last_test_message = message
                await session.flush()
                logger.warning(
                    "client_test_decrypt_failed",
                    client_id=existing_id,
                    error=str(exc),
                )
                return _decryption_failure_response()

    dl_provider: (
        SABnzbdClient | NZBGetClient | QBittorrentClient | TransmissionClient | DelugeClient
    )
    if body.client_type == "sabnzbd":
        dl_provider = SABnzbdClient(
            url=body.url,
            api_key=api_key,
            category=body.category,
        )
    elif body.client_type == "nzbget":
        dl_provider = NZBGetClient(
            url=body.url,
            username=username or "nzbget",
            password=password,
            category=body.category,
        )
    elif body.client_type == "qbittorrent":
        dl_provider = QBittorrentClient(
            url=body.url,
            username=username,
            password=password,
            category=body.category,
        )
    elif body.client_type == "transmission":
        dl_provider = TransmissionClient(
            url=body.url,
            username=username,
            password=password,
        )
    elif body.client_type == "deluge":
        dl_provider = DelugeClient(
            url=body.url,
            password=password,
        )
    else:
        raise ProviderError("download", f"Unknown client type: {body.client_type}")

    # Use a shorter timeout for test connections (5s instead of default 10s)
    if hasattr(dl_provider, "_client") and isinstance(dl_provider._client, httpx.AsyncClient):
        dl_provider._client.timeout = httpx.Timeout(5.0, connect=2.0)

    result = await dl_provider.test_connection()

    return {
        "healthy": result.healthy,
        "message": result.message,
        "response_time_ms": result.response_time_ms,
    }


@router.post("/{client_id}/test", status_code=200)
async def test_client(
    client_id: int,
    _user: InteractiveOperatorUser,
    session: DbSession,
) -> dict[str, object]:
    """Test connectivity to a download client."""
    client = await session.get(DownloadClientConfig, client_id)
    if not client:
        raise NotFoundError("DownloadClient", client_id)

    from pullbox.providers.download.deluge import DelugeClient
    from pullbox.providers.download.nzbget import NZBGetClient
    from pullbox.providers.download.qbittorrent import QBittorrentClient
    from pullbox.providers.download.sabnzbd import SABnzbdClient
    from pullbox.providers.download.transmission import TransmissionClient

    url = str(client.url)
    category = str(client.category) if client.category else None

    dl_provider: (
        SABnzbdClient | NZBGetClient | QBittorrentClient | TransmissionClient | DelugeClient
    )
    try:
        if client.client_type == "sabnzbd":
            dl_provider = SABnzbdClient(
                url=url,
                api_key=decrypt_secret(str(client.api_key or "")),
                category=category,
                priority=client.sab_priority,
                post_processing=client.sab_post_processing,
            )
        elif client.client_type == "nzbget":
            dl_provider = NZBGetClient(
                url=url,
                username=str(client.username or "nzbget"),
                password=decrypt_secret(str(client.password or "")),
                category=category,
                priority=client.nzbget_priority,
                post_processing=client.nzbget_post_processing,
            )
        elif client.client_type == "qbittorrent":
            dl_provider = QBittorrentClient(
                url=url,
                username=str(client.username or ""),
                password=decrypt_secret(str(client.password or "")),
                category=category,
                content_layout=client.qbt_content_layout,
                ratio_limit=client.qbt_ratio_limit,
                seeding_time_limit=client.qbt_seeding_time_limit,
            )
        elif client.client_type == "transmission":
            dl_provider = TransmissionClient(
                url=url,
                username=str(client.username or ""),
                password=decrypt_secret(str(client.password or "")),
                download_dir=client.transmission_download_dir,
                bandwidth_priority=client.transmission_bandwidth_priority,
                seed_ratio_limit=client.transmission_seed_ratio_limit,
                seed_idle_limit=client.transmission_seed_idle_limit,
            )
        elif client.client_type == "deluge":
            dl_provider = DelugeClient(
                url=url,
                password=decrypt_secret(str(client.password or "")),
                label=client.deluge_label,
                max_ratio=client.deluge_max_ratio,
                move_completed_path=client.deluge_move_completed_path,
            )
        else:
            raise ProviderError("download", f"Unknown client type: {client.client_type}")
    except ValueError as exc:
        message = str(_decryption_failure_response()["message"])
        client.last_failure_at = datetime.now(UTC)
        client.last_error = message
        client.last_test_message = message
        await session.flush()
        logger.warning("client_test_decrypt_failed", client_id=client_id, error=str(exc))
        return _decryption_failure_response()

    # Shorter timeout for test connections
    if hasattr(dl_provider, "_client") and isinstance(dl_provider._client, httpx.AsyncClient):
        dl_provider._client.timeout = httpx.Timeout(5.0, connect=2.0)

    result = await dl_provider.test_connection()
    checked_at = datetime.now(UTC)
    client.last_test_message = result.message
    if result.healthy:
        client.last_success_at = checked_at
        client.last_error = None
    else:
        client.last_failure_at = checked_at
        client.last_error = result.message
    await session.flush()

    logger.info(
        "client_test_connection",
        client_id=client_id,
        healthy=result.healthy,
        response_time_ms=result.response_time_ms,
    )
    return {
        "healthy": result.healthy,
        "message": result.message,
        "response_time_ms": result.response_time_ms,
    }
