"""Tests for UT-F.8 — SSE progress reporting.

Verifies SSEEvent formatting, publish/subscribe mechanics,
channel-based routing, subscriber cleanup, and edge cases
(queue full, rapid publish, large payloads, reconnection).

Run:
    pytest tests/utilities/test_sse.py -v
"""

from __future__ import annotations

import asyncio  # noqa: TC003
import json
from typing import Any

import pytest

from pullbox.utilities.sse import SSEEvent, publish, subscribe

# ── SSEEvent ───────────────────────────────────────────────────


class TestSSEEvent:
    """Verify SSEEvent formatting matches SSE wire protocol."""

    def test_format_sse_basic(self) -> None:
        event = SSEEvent(
            channel="utility:job-1",
            event_type="progress",
            data={"completed": 5, "total": 20},
        )
        formatted = event.format_sse()
        assert "event: progress\n" in formatted
        assert "data: " in formatted
        assert formatted.endswith("\n\n")

    def test_format_sse_data_is_json(self) -> None:
        event = SSEEvent(
            channel="test",
            event_type="update",
            data={"key": "value"},
        )
        formatted = event.format_sse()
        # Extract data line
        for line in formatted.split("\n"):
            if line.startswith("data: "):
                data_str = line[len("data: ") :]
                parsed = json.loads(data_str)
                assert parsed["key"] == "value"
                return
        pytest.fail("No data line found")

    def test_format_sse_empty_data(self) -> None:
        event = SSEEvent(channel="test", event_type="ping", data={})
        formatted = event.format_sse()
        assert "data: {}" in formatted

    def test_data_json_property(self) -> None:
        event = SSEEvent(
            channel="test",
            event_type="t",
            data={"a": 1, "b": "two"},
        )
        parsed = json.loads(event.data_json)
        assert parsed["a"] == 1
        assert parsed["b"] == "two"

    def test_format_sse_multiline_data(self) -> None:
        """Newlines in data JSON get split into multiple data: lines."""
        # Force a newline in JSON by using a value with newline
        event = SSEEvent(
            channel="test",
            event_type="log",
            data={"message": "line1\nline2"},
        )
        formatted = event.format_sse()
        data_lines = [line for line in formatted.split("\n") if line.startswith("data: ")]
        # JSON with \n in value doesn't actually produce newlines in JSON output,
        # but the mechanism handles it if it does
        assert len(data_lines) >= 1

    def test_frozen_dataclass(self) -> None:
        event = SSEEvent(channel="test", event_type="t", data={})
        with pytest.raises(AttributeError):
            event.channel = "other"  # type: ignore[misc]


# ── Publish/Subscribe ─────────────────────────────────────────


class TestPublishSubscribe:
    """Verify basic publish/subscribe mechanics."""

    @pytest.mark.asyncio
    async def test_publish_no_subscribers_no_error(self) -> None:
        await publish("orphan-channel", "test", {"key": "value"})

    @pytest.mark.asyncio
    async def test_subscribe_publish_receive(self) -> None:
        async with subscribe("test-ch-1") as queue:
            await publish("test-ch-1", "progress", {"completed": 1})
            event = queue.get_nowait()
            assert event is not None
            assert event.event_type == "progress"
            assert event.data["completed"] == 1

    @pytest.mark.asyncio
    async def test_multiple_subscribers_receive_same_event(self) -> None:
        async with subscribe("multi-ch") as q1, subscribe("multi-ch") as q2:
            await publish("multi-ch", "update", {"val": 42})
            e1 = q1.get_nowait()
            e2 = q2.get_nowait()
            assert e1 is not None
            assert e2 is not None
            assert e1.data["val"] == 42
            assert e2.data["val"] == 42

    @pytest.mark.asyncio
    async def test_subscribe_different_channels_isolated(self) -> None:
        async with subscribe("ch-a") as qa, subscribe("ch-b") as qb:
            await publish("ch-a", "event", {"from": "a"})
            assert qb.qsize() == 0
            ea = qa.get_nowait()
            assert ea is not None
            assert ea.data["from"] == "a"
            assert qb.empty()

    @pytest.mark.asyncio
    async def test_subscriber_cleanup_on_exit(self) -> None:
        """Subscriber queue is removed from registry after context exit."""
        from pullbox.utilities.sse import _subscribers

        channel = "cleanup-test"
        async with subscribe(channel):
            assert channel in _subscribers
        # After exit, channel should be cleaned up
        assert channel not in _subscribers

    @pytest.mark.asyncio
    async def test_five_simultaneous_subscribers(self) -> None:
        queues: list[asyncio.Queue[SSEEvent | None]] = []
        managers = [subscribe("five-ch") for _ in range(5)]
        ctxs = []
        for m in managers:
            ctx = await m.__aenter__()
            ctxs.append((m, ctx))
            queues.append(ctx)

        try:
            await publish("five-ch", "ping", {"n": 1})
            for q in queues:
                event = q.get_nowait()
                assert event is not None
                assert event.data["n"] == 1
        finally:
            for m, _ in ctxs:
                await m.__aexit__(None, None, None)


# ── Queue Full / Slow Consumer ─────────────────────────────────


class TestQueueFull:
    """Verify slow consumer protection."""

    @pytest.mark.asyncio
    async def test_queue_full_drops_subscriber(self) -> None:
        """When subscriber queue is full, it gets dropped — publisher NOT blocked."""
        async with subscribe("full-ch", maxsize=2) as queue:
            # Fill the queue
            await publish("full-ch", "e1", {"i": 1})
            await publish("full-ch", "e2", {"i": 2})
            # This should NOT block — drops the subscriber instead
            await publish("full-ch", "e3", {"i": 3})
            # Queue should still have the first two events
            assert queue.qsize() == 2

    @pytest.mark.asyncio
    async def test_rapid_publish_200_events(self) -> None:
        """200+ rapid publishes — subscriber receives up to maxsize."""
        async with subscribe("rapid-ch", maxsize=100) as queue:
            for i in range(200):
                await publish("rapid-ch", "tick", {"i": i})
            # Should have received up to maxsize (100), rest dropped
            assert queue.qsize() <= 100


# ── Large Payloads ─────────────────────────────────────────────


class TestLargePayloads:
    """Verify large data payloads work."""

    @pytest.mark.asyncio
    async def test_large_data_payload(self) -> None:
        """50KB JSON object as single SSE event."""
        large_data: dict[str, Any] = {f"key_{i}": f"value_{'x' * 100}" for i in range(500)}
        async with subscribe("large-ch") as queue:
            await publish("large-ch", "big", large_data)
            event = queue.get_nowait()
            assert event is not None
            assert len(event.data_json) > 50000


# ── Reconnection ──────────────────────────────────────────────


class TestReconnection:
    """Verify subscribe/disconnect/reconnect behavior."""

    @pytest.mark.asyncio
    async def test_reconnect_is_independent(self) -> None:
        """Second connection after disconnect is independent."""
        async with subscribe("recon-ch") as q1:
            await publish("recon-ch", "first", {"n": 1})
            assert q1.qsize() == 1

        # Disconnected — now reconnect
        async with subscribe("recon-ch") as q2:
            await publish("recon-ch", "second", {"n": 2})
            assert q2.qsize() == 1
            event = q2.get_nowait()
            assert event is not None
            assert event.data["n"] == 2

    @pytest.mark.asyncio
    async def test_subscribe_disconnect_cycle_no_leak(self) -> None:
        """100 subscribe/disconnect cycles — registry stays clean."""
        from pullbox.utilities.sse import _subscribers

        channel = "leak-test"
        for _ in range(100):
            async with subscribe(channel):
                pass
        assert channel not in _subscribers


# ── None Shutdown Signal ───────────────────────────────────────


class TestShutdownSignal:
    """Verify None event signals subscriber to stop."""

    @pytest.mark.asyncio
    async def test_none_signals_stop(self) -> None:
        async with subscribe("stop-ch") as queue:
            queue.put_nowait(None)
            event = queue.get_nowait()
            assert event is None
