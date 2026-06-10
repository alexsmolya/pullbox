"""Health UI data-loading and history helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING
from typing import cast as typing_cast
from urllib.parse import urlencode

from sqlalchemy import ColumnElement, String, asc, cast, desc, func, select

from pullbox.models.health import HealthCheckResult as HealthCheckResultModel
from pullbox.models.health import HealthCurrentStatus as HealthCurrentStatusModel
from pullbox.models.health import HealthStatus

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_HEALTH_HISTORY_SORT_DEFAULT = "-checked_at"
_HEALTH_HISTORY_SORT_FIELDS = frozenset({"checked_at", "check_name", "status", "response_time_ms"})


async def _load_health_data(
    session: AsyncSession,
) -> tuple[list[object], str]:
    """Load current health check results for the UI."""
    stmt = select(HealthCurrentStatusModel).where(
        HealthCurrentStatusModel.is_summary.is_(True),
        HealthCurrentStatusModel.subject_key_norm == "",
    )
    result = await session.execute(stmt)
    rows = list(result.scalars().all())

    components: list[object] = []
    precedence = {
        HealthStatus.UNHEALTHY: 3,
        HealthStatus.DEGRADED: 2,
        HealthStatus.UNKNOWN: 1,
        HealthStatus.HEALTHY: 0,
    }
    worst_status = HealthStatus.HEALTHY

    for row in rows:
        details = _parse_health_details_json(row.details_json)
        components.append(
            {
                "component": row.component,
                "status": row.status.value,
                "message": row.message,
                "response_time_ms": row.response_time_ms,
                "last_checked": row.checked_at,
                "actionable_guidance": None,
                "details": details,
            }
        )
        if precedence.get(row.status, 0) > precedence.get(worst_status, 0):
            worst_status = row.status

    overall = worst_status.value if rows else "unknown"
    return components, overall


def _normalize_health_history_sort(value: str | None) -> str:
    """Normalize health history sort input to a supported field token."""
    raw = (value or _HEALTH_HISTORY_SORT_DEFAULT).strip() or _HEALTH_HISTORY_SORT_DEFAULT
    descending = raw.startswith("-")
    field = raw[1:] if descending else raw
    if field not in _HEALTH_HISTORY_SORT_FIELDS:
        return _HEALTH_HISTORY_SORT_DEFAULT
    return f"-{field}" if descending else field


def _health_history_order_by(sort: str) -> tuple[ColumnElement[object], ...]:
    """Return deterministic order clauses for health history tables."""
    normalized = _normalize_health_history_sort(sort)
    descending = normalized.startswith("-")
    field = normalized[1:] if descending else normalized

    primary: ColumnElement[object]
    if field == "check_name":
        primary = typing_cast(
            "ColumnElement[object]",
            func.lower(HealthCheckResultModel.check_name),
        )
    elif field == "status":
        primary = typing_cast(
            "ColumnElement[object]",
            cast(HealthCheckResultModel.status, String),
        )
    elif field == "response_time_ms":
        null_fallback = -1 if descending else 10**9
        primary = typing_cast(
            "ColumnElement[object]",
            func.coalesce(HealthCheckResultModel.response_time_ms, null_fallback),
        )
    else:
        primary = typing_cast("ColumnElement[object]", HealthCheckResultModel.checked_at)

    ordered_primary = (
        typing_cast("ColumnElement[object]", desc(primary))
        if descending
        else typing_cast("ColumnElement[object]", asc(primary))
    )
    if field == "checked_at":
        return (ordered_primary,)
    return (
        ordered_primary,
        typing_cast("ColumnElement[object]", desc(HealthCheckResultModel.checked_at)),
    )


def _health_history_url(
    component_key: str,
    *,
    base_path: str | None = None,
    search_query: str = "",
    sort: str = _HEALTH_HISTORY_SORT_DEFAULT,
    page: int = 1,
    partial: bool = False,
) -> str:
    """Build a canonical health detail URL for page or partial refreshes."""
    params: list[tuple[str, str]] = []
    normalized_search = search_query.strip()
    normalized_sort = _normalize_health_history_sort(sort)

    if normalized_search:
        params.append(("search", normalized_search))
    if normalized_sort != _HEALTH_HISTORY_SORT_DEFAULT:
        params.append(("sort", normalized_sort))
    if page > 1:
        params.append(("history_page", str(page)))

    path = base_path or f"/health/{component_key}"
    if partial:
        path = f"{path}/status"
    return f"{path}?{urlencode(params)}" if params else path


async def _health_history_prefers_subchecks(
    session: AsyncSession,
    component_key: str,
    *,
    subject_key: str | None = None,
) -> bool:
    """Return True when a component has dedicated sub-check history rows."""
    subcheck_count = int(
        (
            await session.execute(
                select(func.count(HealthCheckResultModel.id)).where(
                    HealthCheckResultModel.component == component_key,
                    HealthCheckResultModel.is_summary.is_(False),
                    HealthCheckResultModel.subject_key.is_(None)
                    if subject_key is None
                    else HealthCheckResultModel.subject_key == subject_key,
                )
            )
        ).scalar_one()
        or 0
    )
    return subcheck_count > 0


def _parse_health_details_json(details_json: str | None) -> dict[str, object] | None:
    """Safely deserialize persisted health details JSON."""
    if not details_json:
        return None
    try:
        parsed = json.loads(details_json)
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _health_detail_checks(details: object) -> tuple[Mapping[str, object], ...]:
    """Return the raw check payloads embedded in a health details dict."""
    if not isinstance(details, Mapping):
        return ()
    raw_checks = details.get("checks")
    if not isinstance(raw_checks, Sequence):
        return ()
    return tuple(item for item in raw_checks if isinstance(item, Mapping))


async def _load_latest_health_subject_summary_rows(
    session: AsyncSession,
    component_key: str,
) -> dict[str, HealthCurrentStatusModel]:
    """Return current subject summary rows for a component."""
    rows = (
        (
            await session.execute(
                select(HealthCurrentStatusModel).where(
                    HealthCurrentStatusModel.component == component_key,
                    HealthCurrentStatusModel.is_summary.is_(True),
                    HealthCurrentStatusModel.subject_key_norm != "",
                )
            )
        )
        .scalars()
        .all()
    )
    return {str(row.subject_key): row for row in rows if row.subject_key is not None}
