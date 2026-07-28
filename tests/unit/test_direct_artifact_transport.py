from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import httpx
import pytest

from pullbox.models.direct_acquisition import (
    DirectArtifactFailureClass,
    DirectArtifactHostKind,
)
from pullbox.providers.artifact_hosts.contract import ResolvedTransfer
from pullbox.providers.artifact_hosts.transport import (
    ArtifactTransferCancelledError,
    ArtifactTransferError,
    ArtifactTransferPausedError,
    ArtifactTransferPolicy,
    HttpArtifactTransport,
    HttpTransferCheckpoint,
    TransferProgressSnapshot,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path


_PUBLIC_IP = "93.184.216.34"


@pytest.mark.asyncio
async def test_http_transport_streams_to_quarantine_and_reports_final_progress(
    tmp_path: Path,
) -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={
                "content-length": "6",
                "etag": '"v1"',
                "content-disposition": 'attachment; filename="issue.cbz"',
            },
            content=b"abcdef",
        )

    root, destination = _quarantine_paths(tmp_path)
    progress: list[TransferProgressSnapshot] = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await HttpArtifactTransport(
            client=client,
            resolver=_public_resolver,
            policy=ArtifactTransferPolicy(progress_interval_seconds=0),
        ).transfer(
            resolved=_resolved(expected_size=6),
            destination=destination,
            quarantine_root=root,
            progress_callback=progress.append,
        )

    assert destination.read_bytes() == b"abcdef"
    assert result.bytes_transferred == 6
    assert result.etag == '"v1"'
    assert result.filename_hint == "issue.cbz"
    assert result.resumed is False
    assert progress[-1].bytes_transferred == 6
    assert progress[-1].percent == 100
    assert requests[0].headers["host"] == "files.example.com"
    assert requests[0].url.host == _PUBLIC_IP


@pytest.mark.asyncio
async def test_http_transport_resumes_only_with_stable_validator(
    tmp_path: Path,
) -> None:
    seen_headers: list[httpx.Headers] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.append(request.headers)
        return httpx.Response(
            206,
            headers={
                "content-range": "bytes 3-5/6",
                "content-length": "3",
                "etag": '"stable"',
            },
            content=b"def",
        )

    root, destination = _quarantine_paths(tmp_path)
    destination.write_bytes(b"abc")
    checkpoint = HttpTransferCheckpoint(
        bytes_transferred=3,
        expected_size=6,
        etag='"stable"',
        last_modified=None,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await HttpArtifactTransport(
            client=client,
            resolver=_public_resolver,
        ).transfer(
            resolved=_resolved(expected_size=6, etag='"stable"', range_supported=True),
            destination=destination,
            quarantine_root=root,
            checkpoint=checkpoint,
        )

    assert destination.read_bytes() == b"abcdef"
    assert seen_headers[0]["range"] == "bytes=3-"
    assert seen_headers[0]["if-range"] == '"stable"'
    assert result.resumed is True


@pytest.mark.asyncio
async def test_http_transport_restarts_when_server_returns_changed_object(
    tmp_path: Path,
) -> None:
    seen_ranges: list[str | None] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_ranges.append(request.headers.get("range"))
        return httpx.Response(
            200,
            headers={"content-length": "6", "etag": '"changed"'},
            content=b"uvwxyz",
        )

    root, destination = _quarantine_paths(tmp_path)
    destination.write_bytes(b"abc")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await HttpArtifactTransport(
            client=client,
            resolver=_public_resolver,
        ).transfer(
            resolved=_resolved(expected_size=6, etag='"stable"', range_supported=True),
            destination=destination,
            quarantine_root=root,
            checkpoint=HttpTransferCheckpoint(
                bytes_transferred=3,
                expected_size=6,
                etag='"stable"',
                last_modified=None,
            ),
        )

    assert seen_ranges == ["bytes=3-"]
    assert destination.read_bytes() == b"uvwxyz"
    assert result.etag == '"changed"'
    assert result.resumed is False


@pytest.mark.asyncio
async def test_http_transport_retries_without_range_for_invalid_partial_response(
    tmp_path: Path,
) -> None:
    seen_ranges: list[str | None] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_ranges.append(request.headers.get("range"))
        if len(seen_ranges) == 1:
            return httpx.Response(
                206,
                headers={"content-range": "bytes 0-2/6", "etag": '"stable"'},
                content=b"abc",
            )
        return httpx.Response(
            200,
            headers={"content-length": "6", "etag": '"stable"'},
            content=b"abcdef",
        )

    root, destination = _quarantine_paths(tmp_path)
    destination.write_bytes(b"abc")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await HttpArtifactTransport(
            client=client,
            resolver=_public_resolver,
        ).transfer(
            resolved=_resolved(expected_size=6, etag='"stable"', range_supported=True),
            destination=destination,
            quarantine_root=root,
            checkpoint=HttpTransferCheckpoint(
                bytes_transferred=3,
                expected_size=6,
                etag='"stable"',
                last_modified=None,
            ),
        )

    assert seen_ranges == ["bytes=3-", None]
    assert destination.read_bytes() == b"abcdef"
    assert result.resumed is False


@pytest.mark.asyncio
async def test_http_transport_refreshes_expired_url_without_new_logical_attempt(
    tmp_path: Path,
) -> None:
    hosts: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        hosts.append(request.headers["host"])
        return httpx.Response(200, headers={"content-length": "3"}, content=b"new")

    refresh_calls = 0

    async def refresh() -> ResolvedTransfer:
        nonlocal refresh_calls
        refresh_calls += 1
        return _resolved(url="https://fresh.example.com/issue.cbz", expected_size=3)

    root, destination = _quarantine_paths(tmp_path)
    expired = _resolved(expected_size=3)
    expired = ResolvedTransfer(
        host_kind=expired.host_kind,
        url=expired.url,
        expected_size=expired.expected_size,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
        allowed_domains=expired.allowed_domains,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await HttpArtifactTransport(
            client=client,
            resolver=_public_resolver,
        ).transfer(
            resolved=expired,
            destination=destination,
            quarantine_root=root,
            refresh_transfer=refresh,
        )

    assert refresh_calls == 1
    assert hosts == ["fresh.example.com"]
    assert result.bytes_transferred == 3


@pytest.mark.asyncio
async def test_http_transport_cancel_removes_partial_and_pause_preserves_it(
    tmp_path: Path,
) -> None:
    cancel_event = asyncio.Event()
    pause_event = asyncio.Event()

    async def cancel_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_TwoChunkStream(b"abc", b"def", cancel_event.set))

    root, destination = _quarantine_paths(tmp_path)
    async with httpx.AsyncClient(transport=httpx.MockTransport(cancel_handler)) as client:
        with pytest.raises(ArtifactTransferCancelledError):
            await HttpArtifactTransport(
                client=client,
                resolver=_public_resolver,
                policy=ArtifactTransferPolicy(chunk_size_bytes=3),
            ).transfer(
                resolved=_resolved(expected_size=6),
                destination=destination,
                quarantine_root=root,
                cancel_event=cancel_event,
            )
    assert not destination.exists()

    async def pause_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_TwoChunkStream(b"abc", b"def", pause_event.set))

    async with httpx.AsyncClient(transport=httpx.MockTransport(pause_handler)) as client:
        with pytest.raises(ArtifactTransferPausedError) as caught:
            await HttpArtifactTransport(
                client=client,
                resolver=_public_resolver,
                policy=ArtifactTransferPolicy(chunk_size_bytes=3),
            ).transfer(
                resolved=_resolved(expected_size=6),
                destination=destination,
                quarantine_root=root,
                pause_event=pause_event,
            )
    assert destination.read_bytes() == b"abc"
    assert caught.value.checkpoint.bytes_transferred == 3


@pytest.mark.asyncio
async def test_http_transport_rejects_oversize_or_insufficient_disk(
    tmp_path: Path,
) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-length": "100"}, content=b"x" * 100)

    root, destination = _quarantine_paths(tmp_path)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ArtifactTransferError) as oversize:
            await HttpArtifactTransport(
                client=client,
                resolver=_public_resolver,
                policy=ArtifactTransferPolicy(max_artifact_bytes=50),
            ).transfer(
                resolved=_resolved(expected_size=None),
                destination=destination,
                quarantine_root=root,
            )
    assert oversize.value.code == "artifact_too_large"
    assert oversize.value.failure_class is DirectArtifactFailureClass.SAFETY

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ArtifactTransferError) as disk:
            await HttpArtifactTransport(
                client=client,
                resolver=_public_resolver,
                disk_free_provider=lambda _path: 10,
                policy=ArtifactTransferPolicy(min_free_bytes=5),
            ).transfer(
                resolved=_resolved(expected_size=100),
                destination=destination,
                quarantine_root=root,
            )
    assert disk.value.code == "artifact_disk_space_insufficient"


@pytest.mark.asyncio
async def test_http_transport_revalidates_redirect_and_rejects_private_target(
    tmp_path: Path,
) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://private.example/file.cbz"})

    async def resolver(host: str, _port: int) -> Sequence[str]:
        return ("127.0.0.1",) if host == "private.example" else (_PUBLIC_IP,)

    root, destination = _quarantine_paths(tmp_path)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ArtifactTransferError) as caught:
            await HttpArtifactTransport(client=client, resolver=resolver).transfer(
                resolved=_resolved(expected_size=None, allowed_domains=()),
                destination=destination,
                quarantine_root=root,
            )

    assert caught.value.code == "unsafe_artifact_url"
    assert not destination.exists()


@pytest.mark.asyncio
async def test_http_transport_idle_timeout_is_retryable_and_preserves_crash_checkpoint(
    tmp_path: Path,
) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_StalledStream())

    root, destination = _quarantine_paths(tmp_path)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ArtifactTransferError) as caught:
            await HttpArtifactTransport(
                client=client,
                resolver=_public_resolver,
                policy=ArtifactTransferPolicy(idle_timeout_seconds=0.01),
            ).transfer(
                resolved=_resolved(expected_size=None),
                destination=destination,
                quarantine_root=root,
            )

    assert caught.value.code == "artifact_transfer_idle_timeout"
    assert caught.value.retryable is True


def _resolved(
    *,
    url: str = "https://files.example.com/issue.cbz",
    expected_size: int | None,
    etag: str | None = None,
    range_supported: bool = False,
    allowed_domains: tuple[str, ...] = ("example.com",),
) -> ResolvedTransfer:
    return ResolvedTransfer(
        host_kind=DirectArtifactHostKind.GENERIC_HTTPS,
        url=url,
        expected_size=expected_size,
        etag=etag,
        range_supported=range_supported,
        allowed_domains=allowed_domains,
    )


def _quarantine_paths(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "quarantine"
    root.mkdir(exist_ok=True)
    return root, root / "attempt.part"


async def _public_resolver(_host: str, _port: int) -> Sequence[str]:
    return (_PUBLIC_IP,)


class _TwoChunkStream(httpx.AsyncByteStream):
    def __init__(self, first: bytes, second: bytes, between: object) -> None:
        self._first = first
        self._second = second
        self._between = between

    async def __aiter__(self):  # type: ignore[no-untyped-def]
        yield self._first
        callback = self._between
        assert callable(callback)
        callback()
        yield self._second


class _StalledStream(httpx.AsyncByteStream):
    async def __aiter__(self):  # type: ignore[no-untyped-def]
        await asyncio.sleep(30)
        yield b"never"
