"""Health check item presenter mapping."""

from __future__ import annotations

from pullbox.core.duration_format import replace_duration_ms_tokens
from pullbox.ui.health_data import _health_detail_checks
from pullbox.ui.health_presenters import (
    HealthCheckItemView,
    _health_check_response_label,
    _health_led_tone,
    _health_pill_tone,
    _health_response_label,
)


def build_health_checks_from_details(details: object) -> tuple[HealthCheckItemView, ...]:
    """Extract normalized health checks from a component details payload."""
    rendered: list[HealthCheckItemView] = []
    for index, raw_check in enumerate(_health_detail_checks(details)):
        status = str(raw_check.get("status") or "unknown")
        raw_message = str(raw_check.get("message") or "")
        message = replace_duration_ms_tokens(raw_message)
        response_ms = raw_check.get("response_time_ms")
        rendered.append(
            HealthCheckItemView(
                key=f"check-{index}",
                name=str(raw_check.get("name") or "Check"),
                status=status,
                status_label=status.capitalize(),
                pill_tone=_health_pill_tone(status),
                led_tone=_health_led_tone(status),
                message=message,
                response_label=(
                    _health_response_label(response_ms)
                    if isinstance(response_ms, (int, float))
                    else _health_check_response_label(raw_message)
                ),
            )
        )
    return tuple(rendered)
