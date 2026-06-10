"""Placeholder health check presenter builders."""

from __future__ import annotations

from pullbox.ui.health_presenters import (
    HealthCheckItemView,
    _health_led_tone,
    _health_pill_tone,
)


def build_download_client_placeholder_checks() -> tuple[HealthCheckItemView, ...]:
    """Return placeholder checks for a client without recorded health yet."""
    return _build_placeholder_checks(
        prefix="placeholder",
        labels=(
            ("Endpoint reachability", "Waiting for the next health check"),
            ("Authentication", "Waiting for the next health check"),
            ("Client identity", "Waiting for the next health check"),
            ("Queue access", "Waiting for the next health check"),
        ),
    )


def build_prowlarr_placeholder_checks() -> tuple[HealthCheckItemView, ...]:
    """Return placeholder checks for Prowlarr before any health data exists."""
    return _build_placeholder_checks(
        prefix="prowlarr-placeholder",
        labels=(
            ("API connectivity", "Waiting for the next health check"),
            ("Authentication", "Waiting for the next health check"),
            ("Indexer registry", "Waiting for the next health check"),
            ("Latency", "Waiting for the next health check"),
        ),
    )


def build_indexer_placeholder_checks() -> tuple[HealthCheckItemView, ...]:
    """Return placeholder checks for an indexer before any health data exists."""
    return _build_placeholder_checks(
        prefix="indexer-placeholder",
        labels=(
            ("Endpoint reachability", "Waiting for the next health check"),
            ("Authentication", "Waiting for the next health check"),
            ("Capabilities", "Waiting for the next health check"),
            ("Latency", "Waiting for the next health check"),
        ),
    )


def _build_placeholder_checks(
    *,
    prefix: str,
    labels: tuple[tuple[str, str], ...],
) -> tuple[HealthCheckItemView, ...]:
    return tuple(
        HealthCheckItemView(
            key=f"{prefix}-{index}",
            name=name,
            status="unknown",
            status_label="Unknown",
            pill_tone=_health_pill_tone("unknown"),
            led_tone=_health_led_tone("unknown"),
            message=message,
            response_label="—",
        )
        for index, (name, message) in enumerate(labels)
    )
