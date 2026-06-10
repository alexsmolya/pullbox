"""Anonymous usage-stats telemetry payload and client helpers."""

from __future__ import annotations

import asyncio
import platform as platform_module
import sys
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import httpx
import structlog
from sqlalchemy import func, select

import pullbox
from pullbox.config import get_settings
from pullbox.database import get_session_factory
from pullbox.models.config import DEFAULT_SYSTEM_CONFIG, SystemConfig
from pullbox.models.import_job import ImportJob, ImportJobStatus
from pullbox.models.indexer import IndexerConfig
from pullbox.models.issue import Issue
from pullbox.models.series import Series

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

JsonObject = dict[str, Any]

DEFAULT_TIMEOUT_SECONDS = 5.0
_USAGE_STATS_CONSENT_STATES = frozenset({"unknown", "enabled", "disabled"})
_background_tasks: set[asyncio.Task[None]] = set()
logger = structlog.get_logger(__name__)


async def build_usage_stats_payload(session: AsyncSession) -> JsonObject:
    """Build the anonymous install-level usage-stats payload."""
    instance_id_row = await session.get(SystemConfig, "usage_stats_instance_id")
    instance_id = instance_id_row.value.strip() if instance_id_row is not None else ""

    series_count = await _count_rows(session, Series.id)
    issues_tracked = await _count_rows(session, Issue.id)
    active_indexers = await _count_rows(session, IndexerConfig.id, IndexerConfig.enabled.is_(True))
    completed_imports = await _count_rows(
        session,
        ImportJob.id,
        ImportJob.status == ImportJobStatus.COMPLETED,
    )
    uptime_days = max(0.0, (datetime.now(UTC) - pullbox.STARTED_AT).total_seconds() / 86400)

    return {
        "instance_id": instance_id,
        "pullbox_version": pullbox.__version__,
        "platform": platform_module.platform(),
        "os": platform_module.system(),
        "python_version": (
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        ),
        "db_engine": session.bind.dialect.name if session.bind is not None else "unknown",
        "series_count": series_count,
        "issues_tracked": issues_tracked,
        "active_indexers": active_indexers,
        "import_completed": completed_imports > 0,
        "uptime_days": round(uptime_days, 2),
    }


async def send_usage_stats_ping(
    *,
    session_factory: Any | None = None,
    client: UsageStatsTelemetryClient | None = None,
) -> None:
    """Send one best-effort anonymous usage-stats ping when consent allows it."""
    factory = session_factory or get_session_factory()
    telemetry_client = client or UsageStatsTelemetryClient()
    try:
        async with factory() as session:
            consent_row = await session.get(SystemConfig, "usage_stats_consent")
            consent = _normalize_usage_stats_consent(
                consent_row.value if consent_row is not None else None
            )
            instance_row = await session.get(SystemConfig, "usage_stats_instance_id")
            instance_id = instance_row.value.strip() if instance_row is not None else ""
            if consent != "enabled":
                logger.debug(
                    "usage_stats_ping_skipped",
                    consent=consent,
                    has_instance_id=bool(instance_id),
                )
                return
            if not instance_id:
                instance_id = await _ensure_usage_stats_instance_id(session)

            payload = await build_usage_stats_payload(session)
            await telemetry_client.send(payload)
            logger.debug("usage_stats_ping_sent")
    except Exception:
        logger.debug("usage_stats_ping_failed", exc_info=True)


async def queue_usage_stats_ping(*, session_factory: Any | None = None) -> None:
    """Queue an immediate anonymous usage-stats ping without blocking the response."""
    task = asyncio.create_task(send_usage_stats_ping(session_factory=session_factory))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def _normalize_usage_stats_consent(value: str | None) -> str:
    normalized = (value or "unknown").strip().lower()
    if normalized not in _USAGE_STATS_CONSENT_STATES:
        return "unknown"
    return normalized


async def _count_rows(session: AsyncSession, column: Any, *where: Any) -> int:
    stmt = select(func.count(column))
    for criterion in where:
        stmt = stmt.where(criterion)
    return int((await session.execute(stmt)).scalar_one() or 0)


async def _ensure_usage_stats_instance_id(session: AsyncSession) -> str:
    config = await session.get(SystemConfig, "usage_stats_instance_id")
    if config is not None and config.value.strip():
        return config.value.strip()

    if config is None:
        default_value, default_type = DEFAULT_SYSTEM_CONFIG["usage_stats_instance_id"]
        config = SystemConfig(
            key="usage_stats_instance_id",
            value=default_value,
            value_type=default_type,
        )
        session.add(config)

    instance_id = str(uuid4())
    config.value = instance_id
    config.value_type = "string"
    await session.commit()
    logger.debug("usage_stats_instance_id_created")
    return instance_id


class UsageStatsTelemetryClient:
    """Async client for the public pullbox-data telemetry endpoint."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        configured_base_url = base_url or get_settings().pullbox_data_api_base_url
        self._base_url = configured_base_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout_seconds)
        self._transport = transport

    async def send(self, payload: JsonObject) -> None:
        """Post one telemetry payload to pullbox-data."""
        async with httpx.AsyncClient(
            timeout=self._timeout,
            transport=self._transport,
            headers={"User-Agent": f"Pullbox/{pullbox.__version__}"},
        ) as client:
            response = await client.post(f"{self._base_url}/api/v1/telemetry", json=payload)

        if response.status_code < 200 or response.status_code >= 300:
            raise RuntimeError(f"Telemetry request failed with HTTP {response.status_code}.")
