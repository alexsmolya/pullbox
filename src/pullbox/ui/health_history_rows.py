"""Shared health history row presenter helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pullbox.ui.health_presenters import (
    HealthHistoryRowView,
    _health_pill_tone,
    _health_response_label,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from datetime import datetime

    from pullbox.models.health import HealthCheckResult


def build_health_history_rows(
    rows: Sequence[HealthCheckResult],
    *,
    key_prefix: str,
    current_time: datetime,
    relative_time_label: Callable[[datetime, datetime], str],
) -> tuple[HealthHistoryRowView, ...]:
    """Map health result rows to reusable history row presenters."""
    return tuple(
        HealthHistoryRowView(
            key=f"{key_prefix}-{row.id}",
            time_label=relative_time_label(row.checked_at, current_time),
            check_name=str(row.check_name).replace("_", " ").title(),
            status_label=str(row.status.value).capitalize(),
            pill_tone=_health_pill_tone(str(row.status.value)),
            response_label=_health_response_label(row.response_time_ms),
        )
        for row in rows
    )
