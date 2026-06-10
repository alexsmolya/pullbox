"""Pure helper functions for health checks and health result payloads."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from sqlalchemy.engine import Connection, Engine

from pullbox.core.duration_format import format_duration_ms
from pullbox.models.health import HealthStatus
from pullbox.services.health_types import CheckOutcome, SubCheckOutcome

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sqlalchemy.ext.asyncio import AsyncSession

_SCHEDULER_STUCK_MINUTES = 15


def _download_client_failure_kind(message: str | None) -> str:
    """Classify a download-client probe failure into a useful health bucket."""
    raw = (message or "").strip().lower()
    if not raw:
        return "unknown"

    auth_tokens = (
        "invalid username or password",
        "unauthorized",
        "forbidden",
        "login failed",
        "authentication",
        "api key",
        "apikey",
        "credentials",
        "403",
        "401",
    )
    if any(token in raw for token in auth_tokens):
        return "authentication"

    network_tokens = (
        "timed out",
        "timeout",
        "request failed",
        "connection failed",
        "connection refused",
        "refused",
        "temporarily unavailable",
        "name or service not known",
        "no route to host",
        "network is unreachable",
        "http 5",
        "not found",
    )
    if any(token in raw for token in network_tokens):
        return "network"

    return "unknown"


def _download_client_endpoint_details(url: str) -> dict[str, str]:
    """Return normalized protocol/host/port details for a client URL."""
    parsed = urlparse(url)
    scheme = (parsed.scheme or "http").lower()
    default_port = "443" if scheme == "https" else "80"
    return {
        "protocol": scheme.upper(),
        "host": parsed.hostname or "—",
        "port": str(parsed.port) if parsed.port is not None else default_port,
    }


def _download_client_type_display(client_type: str) -> str:
    """Return a stable human label for a download client type."""
    labels = {
        "sabnzbd": "SABnzbd",
        "nzbget": "NZBGet",
        "qbittorrent": "qBittorrent",
        "transmission": "Transmission",
        "deluge": "Deluge",
    }
    return labels.get(client_type, client_type.replace("_", " ").title())


def _serialize_download_client_summary(outcome: CheckOutcome) -> dict[str, Any]:
    """Convert a client subject summary into the component details payload."""
    payload: dict[str, Any] = {
        "check_name": outcome.check_name,
        "name": outcome.subject_label or "Download client",
        "status": outcome.status.value,
        "message": outcome.message,
        "subject_key": outcome.subject_key,
        "subject_label": outcome.subject_label,
    }
    if outcome.response_time_ms:
        payload["response_time_ms"] = round(outcome.response_time_ms, 1)
    if outcome.details:
        payload.update(
            {
                "client_type": outcome.details.get("client_type"),
                "protocol": outcome.details.get("protocol"),
                "host": outcome.details.get("host"),
                "port": outcome.details.get("port"),
                "version": outcome.details.get("version"),
            }
        )
    return payload


def _indexer_failure_kind(message: str | None) -> str:
    """Classify an indexer/proxy probe failure into a useful health bucket."""
    return _download_client_failure_kind(message)


def _indexer_endpoint_details(url: str) -> dict[str, str]:
    """Return normalized protocol/host/port details for an indexer URL."""
    parsed = urlparse(url)
    scheme = (parsed.scheme or "http").lower()
    default_port = "443" if scheme == "https" else "80"
    return {
        "protocol": scheme.upper(),
        "host": parsed.hostname or "—",
        "port": str(parsed.port) if parsed.port is not None else default_port,
    }


def _indexer_kind_label(indexer_type: str) -> str:
    """Return the protocol family label for an indexer implementation."""
    labels = {
        "newznab": "Newznab",
        "torznab": "Torznab",
    }
    return labels.get(indexer_type, indexer_type.replace("_", " ").title())


def _indexer_content_type_label(indexer_type: str) -> str:
    """Return the content family label for an indexer implementation."""
    labels = {
        "newznab": "Usenet",
        "torznab": "Torrent",
    }
    return labels.get(indexer_type, indexer_type.replace("_", " ").title())


def _latency_message(response_ms: float, prefix: str) -> str:
    """Return a compact human latency message."""
    return f"{prefix} in {format_duration_ms(response_ms)}"


def _serialize_indexer_summary(outcome: CheckOutcome) -> dict[str, Any]:
    """Convert an indexer subject summary into the component details payload."""
    payload: dict[str, Any] = {
        "check_name": outcome.check_name,
        "name": outcome.subject_label or "Indexer",
        "status": outcome.status.value,
        "message": outcome.message,
        "subject_key": outcome.subject_key,
        "subject_label": outcome.subject_label,
    }
    if outcome.response_time_ms:
        payload["response_time_ms"] = round(outcome.response_time_ms, 1)
    if outcome.details:
        payload.update(
            {
                "subject_kind": outcome.details.get("subject_kind"),
                "proxy_type": outcome.details.get("proxy_type"),
                "indexer_kind": outcome.details.get("indexer_kind"),
                "content_type": outcome.details.get("content_type"),
                "protocol": outcome.details.get("protocol"),
                "host": outcome.details.get("host"),
                "port": outcome.details.get("port"),
                "url": outcome.details.get("url"),
                "indexer_count": outcome.details.get("indexer_count"),
                "categories": outcome.details.get("categories"),
            }
        )
    return payload


def _coerce_pathlike(raw: object) -> Path | None:
    """Return a Path for string/pathlike config values, otherwise None."""
    if isinstance(raw, Path):
        return raw
    if isinstance(raw, str) and raw:
        return Path(raw)
    return None


def _serialize_sub_check(check: SubCheckOutcome) -> dict[str, Any]:
    """Convert a sub-check to the details payload consumed by the UI."""
    payload: dict[str, Any] = {
        "check_name": check.check_name,
        "name": check.name,
        "status": check.status.value,
        "message": check.message,
    }
    if check.subject_key is not None:
        payload["subject_key"] = check.subject_key
    if check.subject_label is not None:
        payload["subject_label"] = check.subject_label
    if check.response_time_ms is not None:
        payload["response_time_ms"] = round(check.response_time_ms, 1)
    if check.details:
        payload["details"] = check.details
    return payload


def _coerce_sub_check(raw: SubCheckOutcome | dict[str, Any] | None) -> SubCheckOutcome | None:
    """Normalize patched or persisted sub-check payloads into the dataclass contract."""
    if raw is None or isinstance(raw, SubCheckOutcome):
        return raw
    status = HealthStatus(str(raw.get("status") or HealthStatus.UNKNOWN.value))
    check_name = str(raw.get("check_name") or raw.get("name") or "check")
    return SubCheckOutcome(
        check_name=check_name.lower().replace(" ", "_"),
        name=str(raw.get("name") or "Check"),
        status=status,
        message=str(raw.get("message") or ""),
        response_time_ms=(
            float(raw["response_time_ms"]) if raw.get("response_time_ms") is not None else None
        ),
        details=dict(raw.get("details") or {}),
    )


def _parse_optional_datetime(value: object) -> datetime | None:
    """Parse an ISO datetime-ish value into a datetime when possible."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _scheduler_event_cleared(
    event_at: datetime | None,
    last_execution: datetime | None,
) -> bool:
    """Return whether a recent scheduler incident has been cleared by a later run."""
    return event_at is not None and last_execution is not None and last_execution > event_at


def _scheduler_incident_message(
    *,
    unresolved: list[str],
    cleared: list[str],
    none_message: str,
    cleared_label: str,
) -> str:
    """Render scheduler incident text without surfacing misleading lifetime counters."""
    if unresolved:
        return ", ".join(unresolved)
    if cleared:
        return f"{cleared_label}: {', '.join(cleared)}"
    return none_message


def _scheduler_stuck_threshold(task_info: Mapping[str, object]) -> timedelta:
    """Return a conservative stuck-task threshold for a running scheduler job."""
    base = timedelta(minutes=_SCHEDULER_STUCK_MINUTES)
    last_duration_raw = task_info.get("last_duration_seconds")
    if isinstance(last_duration_raw, (int, float)) and last_duration_raw > 0:
        base = max(base, timedelta(seconds=float(last_duration_raw) * 5))
    return base


def _status_for_latency(
    elapsed_ms: float,
    *,
    degraded_ms: float,
    unhealthy_ms: float,
) -> HealthStatus:
    """Map a latency measurement onto health-state thresholds."""
    if elapsed_ms > unhealthy_ms:
        return HealthStatus.UNHEALTHY
    if elapsed_ms > degraded_ms:
        return HealthStatus.DEGRADED
    return HealthStatus.HEALTHY


def _sqlite_database_path(session: AsyncSession) -> Path | None:
    """Return the SQLite database path for the bound session, if file-backed."""
    bind = session.get_bind()
    if bind is None:
        return None
    engine: Engine = bind.engine if isinstance(bind, Connection) else bind
    url = engine.url
    if hasattr(url, "get_backend_name"):
        if url.get_backend_name() != "sqlite":
            return None
        database = url.database
    else:
        url_str = str(url)
        if "sqlite" not in url_str:
            return None
        database = url_str.split("///", 1)[-1] if "///" in url_str else None
    if not database or database == ":memory:":
        return None
    db_path = Path(database)
    if not db_path.is_absolute():
        db_path = Path.cwd() / db_path
    return db_path


# Status precedence for worst-of comparisons
_STATUS_PRECEDENCE: dict[HealthStatus, int] = {
    HealthStatus.HEALTHY: 0,
    HealthStatus.UNKNOWN: 1,
    HealthStatus.DEGRADED: 2,
    HealthStatus.UNHEALTHY: 3,
}
