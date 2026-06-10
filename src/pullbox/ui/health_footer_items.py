"""Health detail footer presenter helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pullbox.ui.health_presenters import HealthComponentView


def build_health_component_footer_items(
    component: HealthComponentView,
) -> tuple[dict[str, str | None], ...]:
    """Build footer dock values for the single-component detail page."""
    items: list[dict[str, str | None]] = [
        {"label": "component", "value": component.display_name, "led": None},
        {"label": "", "value": component.status_label, "led": component.led_tone},
    ]

    stat_values = {stat.label.lower(): stat.value_label for stat in component.detail_stats}
    for key in ("response", "last check", "checks", "endpoints"):
        value = stat_values.get(key)
        if value:
            items.append({"label": key, "value": value, "led": None})

    return tuple(items)
