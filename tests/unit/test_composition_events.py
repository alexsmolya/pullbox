"""Characterization tests for event-bus composition intent."""

from __future__ import annotations

from pathlib import Path

import pytest

from pullbox.composition.events import build_domain_event_bus, build_scoped_event_bus
from pullbox.core import events as core_events
from pullbox.core.events import SeriesAdded, get_event_bus


def test_domain_event_bus_uses_application_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(core_events, "_event_bus_instance", None)

    assert build_domain_event_bus() is get_event_bus()


@pytest.mark.asyncio
async def test_scoped_event_bus_is_isolated_from_domain_subscribers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(core_events, "_event_bus_instance", None)
    seen: list[int] = []

    domain_bus = build_domain_event_bus()
    scoped_bus = build_scoped_event_bus()
    domain_bus.subscribe(SeriesAdded, lambda event: seen.append(event.series_id))

    await scoped_bus.emit(SeriesAdded(series_id=101, comicvine_id=202))
    assert seen == []

    await domain_bus.emit(SeriesAdded(series_id=303, comicvine_id=404))
    assert seen == [303]


def test_production_event_bus_construction_goes_through_composition_helpers() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    src_root = repo_root / "src" / "pullbox"
    allowed = {
        "composition/events.py",
        "core/events.py",
    }
    offenders: list[str] = []

    for path in src_root.rglob("*.py"):
        rel_path = path.relative_to(src_root).as_posix()
        if rel_path in allowed:
            continue
        if "EventBus()" in path.read_text():
            offenders.append(path.relative_to(repo_root).as_posix())

    assert offenders == []
