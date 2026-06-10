"""Health component stat and sublabel presenter helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pullbox.ui.health_data import _health_detail_checks
from pullbox.ui.health_presenters import (
    HealthComponentStatView,
    _health_parenthetical_next_line,
    _health_response_label,
    _mapping_text,
)
from pullbox.ui.health_registry_rows import health_response_or_dash

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from pullbox.ui.health_presenters import HealthCheckItemView


def health_component_card_stats(
    component_key: str,
    *,
    checks: tuple[HealthCheckItemView, ...],
    response_ms: object,
    last_checked: datetime | None,
    current_time: datetime,
    details: object,
    message: str,
    relative_time_label: Callable[[datetime, datetime], str],
) -> tuple[HealthComponentStatView, ...]:
    """Return the compact stats shown on component cards."""
    if component_key == "download_clients":
        return (
            HealthComponentStatView(label="Clients", value_label=str(len(checks))),
            HealthComponentStatView(
                label="Status",
                value_label=health_attention_label(checks, down_noun="down"),
                tone=(
                    "danger" if any(check.status == "unhealthy" for check in checks) else "default"
                ),
            ),
        )

    if component_key == "indexers":
        raw_checks = _health_detail_checks(details)
        proxy_check = next(
            (check for check in raw_checks if str(check.get("subject_key") or "") == "prowlarr"),
            None,
        )
        indexer_checks = [
            check for check in raw_checks if str(check.get("subject_kind") or "") == "indexer"
        ]
        healthy_indexers = sum(
            1 for check in indexer_checks if str(check.get("status") or "") == "healthy"
        )
        proxy_status = str(proxy_check.get("status") or "unknown") if proxy_check else "unknown"
        return (
            HealthComponentStatView(
                label="Prowlarr",
                value_label=(
                    health_response_or_dash(proxy_check.get("response_time_ms"))
                    if proxy_check
                    else "Not configured"
                ),
                tone=(
                    "danger"
                    if proxy_status == "unhealthy"
                    else "warning"
                    if proxy_status == "degraded"
                    else "default"
                )
                if proxy_check
                else "default",
            ),
            HealthComponentStatView(
                label="Indexers",
                value_label=(
                    "Not configured"
                    if not indexer_checks
                    else f"{healthy_indexers}/{len(indexer_checks)} OK"
                    if healthy_indexers != len(indexer_checks)
                    else f"{len(indexer_checks)} active"
                ),
            ),
        )

    if component_key == "filesystem":
        healthy = sum(1 for check in checks if check.status == "healthy")
        total = len(checks)
        return (
            HealthComponentStatView(label="Paths", value_label=f"{healthy}/{total} OK"),
            HealthComponentStatView(
                label="Last Check",
                value_label=(
                    relative_time_label(last_checked, current_time)
                    if last_checked is not None
                    else "—"
                ),
            ),
        )

    if component_key == "scheduler":
        job_count = _mapping_text(details, "job_count")
        return (
            HealthComponentStatView(label="Status", value_label=message or "Unknown"),
            HealthComponentStatView(
                label="Jobs",
                value_label=job_count or str(len(checks) or 0),
            ),
        )

    if component_key == "system":
        cpu_check = next(
            (check for check in checks if check.name.lower() == "cpu load"),
            None,
        )
        memory_check = next(
            (check for check in checks if check.name.lower() == "memory pressure"),
            None,
        )
        return (
            HealthComponentStatView(
                label="CPU",
                value_label=(
                    _health_parenthetical_next_line(cpu_check.message) if cpu_check else "—"
                ),
            ),
            HealthComponentStatView(
                label="Memory",
                value_label=(
                    _health_parenthetical_next_line(memory_check.message) if memory_check else "—"
                ),
            ),
        )

    return (
        HealthComponentStatView(
            label="Response",
            value_label=_health_response_label(response_ms),
        ),
        HealthComponentStatView(
            label="Last Check",
            value_label=(
                relative_time_label(last_checked, current_time) if last_checked is not None else "—"
            ),
        ),
    )


def health_component_detail_stats(
    component_key: str,
    *,
    checks: tuple[HealthCheckItemView, ...],
    response_ms: object,
    last_checked: datetime | None,
    current_time: datetime,
    details: object,
    message: str,
    relative_time_label: Callable[[datetime, datetime], str],
) -> tuple[HealthComponentStatView, ...]:
    """Return the larger stat strip shown in component detail."""
    attention_count = sum(1 for check in checks if check.status in {"degraded", "unhealthy"})
    if component_key == "indexers":
        raw_checks = _health_detail_checks(details)
        proxy_check = next(
            (check for check in raw_checks if str(check.get("subject_key") or "") == "prowlarr"),
            None,
        )
        indexer_checks = [
            check for check in raw_checks if str(check.get("subject_kind") or "") == "indexer"
        ]
        healthy_indexers = sum(
            1 for check in indexer_checks if str(check.get("status") or "") == "healthy"
        )
        proxy_status = str(proxy_check.get("status") or "unknown") if proxy_check else "unknown"
        return (
            HealthComponentStatView(label="Status", value_label=message or "Unknown"),
            HealthComponentStatView(
                label="Prowlarr",
                value_label=(
                    health_response_or_dash(proxy_check.get("response_time_ms"))
                    if proxy_check
                    else "Not configured"
                ),
                tone=(
                    "danger"
                    if proxy_status == "unhealthy"
                    else "warning"
                    if proxy_status == "degraded"
                    else "default"
                )
                if proxy_check
                else "default",
            ),
            HealthComponentStatView(
                label="Indexers",
                value_label=(
                    "Not configured"
                    if not indexer_checks
                    else f"{healthy_indexers}/{len(indexer_checks)} OK"
                    if healthy_indexers != len(indexer_checks)
                    else f"{len(indexer_checks)} active"
                ),
                tone="danger" if attention_count else "default",
            ),
            HealthComponentStatView(
                label="Last Check",
                value_label=(
                    relative_time_label(last_checked, current_time)
                    if last_checked is not None
                    else "—"
                ),
            ),
        )
    return (
        HealthComponentStatView(label="Status", value_label=message or "Unknown"),
        HealthComponentStatView(label="Response", value_label=_health_response_label(response_ms)),
        HealthComponentStatView(
            label="Last Check",
            value_label=(
                relative_time_label(last_checked, current_time) if last_checked is not None else "—"
            ),
        ),
        HealthComponentStatView(
            label=(
                "Checks" if component_key not in {"download_clients", "indexers"} else "Endpoints"
            ),
            value_label=(
                str(len(checks))
                if attention_count == 0
                else f"{len(checks)} ({attention_count} flagged)"
            ),
            tone="danger" if attention_count else "default",
        ),
    )


def health_attention_label(
    checks: tuple[HealthCheckItemView, ...],
    *,
    down_noun: str,
) -> str:
    """Summarize attention needed for grouped health components."""
    unhealthy = sum(1 for check in checks if check.status == "unhealthy")
    degraded = sum(1 for check in checks if check.status == "degraded")
    if unhealthy:
        return f"{unhealthy} {down_noun}"
    if degraded:
        return f"{degraded} need review"
    return "All clear"


def health_component_sublabel(
    component_key: str,
    checks: tuple[HealthCheckItemView, ...],
    details: object,
) -> str:
    """Return the compact monospace sublabel for a health component card."""
    if component_key == "download_clients":
        return f"{len(checks)} clients"
    if component_key == "indexers":
        raw_checks = _health_detail_checks(details)
        proxy_count = sum(
            1 for check in raw_checks if str(check.get("subject_kind") or "") == "proxy"
        )
        indexer_count = sum(
            1 for check in raw_checks if str(check.get("subject_kind") or "") == "indexer"
        )
        if proxy_count:
            return f"{proxy_count} proxy + {indexer_count} indexers"
        return f"{indexer_count} indexers"
    if component_key == "filesystem":
        return f"{len(checks)} paths checked"
    if component_key == "system":
        return f"{len(checks)} resource checks"
    return f"{len(checks)} checks"
