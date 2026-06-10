"""Event-bus composition helpers with explicit runtime intent."""

from __future__ import annotations

from pullbox.core.events import EventBus, get_event_bus


def build_domain_event_bus() -> EventBus:
    """Return the shared application bus for domain side effects."""
    return get_event_bus()


def build_scoped_event_bus() -> EventBus:
    """Return an isolated bus for workflows that intentionally suppress side effects."""
    return EventBus()
