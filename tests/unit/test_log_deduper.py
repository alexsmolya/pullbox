"""Unit coverage for repeated-warning suppression helpers."""

from __future__ import annotations

from typing import Any

from pullbox.core.log_deduper import WarningDeduper, log_deduped_warning


class _FakeLogger:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def warning(self, event: str, **kwargs: Any) -> None:
        self.events.append((event, kwargs))


def test_warning_deduper_suppresses_repeats_inside_window() -> None:
    """Repeated warnings inside the window should not emit repeatedly."""
    ticks = iter((10.0, 15.0, 19.0))
    deduper = WarningDeduper(now=lambda: next(ticks))

    assert deduper.should_emit("same-warning", window_seconds=30.0) == 0
    assert deduper.should_emit("same-warning", window_seconds=30.0) is None
    assert deduper.should_emit("same-warning", window_seconds=30.0) is None


def test_warning_deduper_reports_suppressed_count_after_window_expires() -> None:
    """The next emitted warning should carry how many repeats were suppressed."""
    ticks = iter((10.0, 15.0, 45.0))
    deduper = WarningDeduper(now=lambda: next(ticks))

    assert deduper.should_emit("same-warning", window_seconds=30.0) == 0
    assert deduper.should_emit("same-warning", window_seconds=30.0) is None
    assert deduper.should_emit("same-warning", window_seconds=30.0) == 1


def test_log_deduped_warning_emits_suppressed_count_metadata(monkeypatch) -> None:
    """The helper should expose suppressed repeats on the next emitted warning."""
    logger = _FakeLogger()
    ticks = iter((10.0, 15.0, 50.0))
    deduper = WarningDeduper(now=lambda: next(ticks))
    monkeypatch.setattr("pullbox.core.log_deduper._warning_deduper", deduper)

    log_deduped_warning(
        logger, "health_registry_skipped", key="k", window_seconds=30.0, error="boom"
    )
    log_deduped_warning(
        logger, "health_registry_skipped", key="k", window_seconds=30.0, error="boom"
    )
    log_deduped_warning(
        logger, "health_registry_skipped", key="k", window_seconds=30.0, error="boom"
    )

    assert len(logger.events) == 2
    assert logger.events[0] == ("health_registry_skipped", {"error": "boom"})
    assert logger.events[1] == (
        "health_registry_skipped",
        {"error": "boom", "suppressed_count": 1},
    )
