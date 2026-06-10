"""Generic Server-Sent Events publisher with channel-based routing.

Designed for reuse across utility jobs, download progress (Sprint 9),
and blocklist notifications (Sprint 4). Not utility-specific.

Channel naming convention:
    "utility:{job_id}" — events for a specific utility job
    "downloads"        — events for all active downloads (future Sprint 9)
    "blocklist"        — notifications when items are blocklisted (future Sprint 4)

Usage:
    # Publishing (from job queue, download service, etc.):
    await publish("utility:abc123", "progress", {"completed": 5, "total": 20})
    await publish("downloads", "speed_update", {"bytes_per_sec": 1024000})

    # Subscribing (from SSE endpoint):
    async with subscribe("utility:abc123") as queue:
        while True:
            event = await asyncio.wait_for(queue.get(), timeout=15.0)
            if event is None:
                break
            yield event.format_sse()
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator  # noqa: TC003
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class SSEEvent:
    """A single server-sent event."""

    channel: str
    event_type: str
    data: dict[str, Any]

    @property
    def data_json(self) -> str:
        return json.dumps(self.data, ensure_ascii=False)

    def format_sse(self) -> str:
        """Format as SSE wire protocol. Handles newlines in data."""
        lines = [f"event: {self.event_type}"]
        for line in self.data_json.split("\n"):
            lines.append(f"data: {line}")
        lines.append("")  # trailing blank line
        lines.append("")  # double newline = end of event
        return "\n".join(lines)


# ── Subscriber Registry (module-level singleton) ──────────────
# Channel name → list of subscriber queues

_subscribers: dict[str, list[asyncio.Queue[SSEEvent | None]]] = {}
_lock = asyncio.Lock()


async def publish(channel: str, event_type: str, data: dict[str, Any]) -> None:
    """Publish an event to all subscribers on a channel.

    If a subscriber's queue is full, it is dropped (slow consumer protection).
    """
    event = SSEEvent(channel=channel, event_type=event_type, data=data)
    async with _lock:
        queues = _subscribers.get(channel, [])
        dead: list[asyncio.Queue[SSEEvent | None]] = []
        for q in queues:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(q)
                logger.warning(
                    "sse_subscriber_dropped",
                    channel=channel,
                    reason="queue_full",
                )
        # Clean up dead subscribers
        for q in dead:
            queues.remove(q)


@asynccontextmanager
async def subscribe(
    channel: str, maxsize: int = 100
) -> AsyncIterator[asyncio.Queue[SSEEvent | None]]:
    """Context manager that registers a subscriber queue for a channel.

    Yields the queue. Automatically unregisters on exit (disconnect).
    Send None to the queue to signal the subscriber should stop.
    """
    queue: asyncio.Queue[SSEEvent | None] = asyncio.Queue(maxsize=maxsize)
    async with _lock:
        _subscribers.setdefault(channel, []).append(queue)
    try:
        yield queue
    finally:
        async with _lock:
            channel_queues = _subscribers.get(channel, [])
            if queue in channel_queues:
                channel_queues.remove(queue)
            if not channel_queues:
                _subscribers.pop(channel, None)
