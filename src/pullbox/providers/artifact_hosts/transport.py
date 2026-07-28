"""Validated, resumable HTTP streaming into app-owned quarantine."""

from __future__ import annotations

import asyncio
import inspect
import shutil
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urljoin

import httpx

from pullbox.models.direct_acquisition import DirectArtifactFailureClass
from pullbox.providers.artifact_hosts.contract import (
    ArtifactHostResolutionError,
    ResolvedTransfer,
)
from pullbox.providers.artifact_hosts.helpers import (
    filename_from_content_disposition,
    filename_from_url,
)
from pullbox.providers.artifact_hosts.http import (
    ArtifactUrlResolver,
    pinned_request_target,
    validate_artifact_url,
)
from pullbox.providers.artifact_hosts.quarantine import (
    open_quarantine_file,
    remove_quarantine_file,
    validate_quarantine_file,
)
from pullbox.providers.artifact_hosts.transport_contract import (
    ArtifactTransferCancelledError,
    ArtifactTransferError,
    ArtifactTransferPausedError,
    ArtifactTransferPolicy,
    ArtifactTransferResult,
    HttpTransferCheckpoint,
    TransferProgressSnapshot,
)

if TYPE_CHECKING:
    from typing import BinaryIO

ProgressCallback = Callable[[TransferProgressSnapshot], Awaitable[None] | None]
RefreshTransfer = Callable[[], Awaitable[ResolvedTransfer]]
DiskFreeProvider = Callable[[Path], int]

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_EXPIRED_URL_STATUSES = frozenset({401, 403, 410})
_SENSITIVE_HEADER_NAMES = frozenset({"authorization", "cookie", "proxy-authorization"})

__all__ = [
    "ArtifactTransferCancelledError",
    "ArtifactTransferError",
    "ArtifactTransferPausedError",
    "ArtifactTransferPolicy",
    "ArtifactTransferResult",
    "HttpArtifactTransport",
    "HttpTransferCheckpoint",
    "TransferProgressSnapshot",
]


class HttpArtifactTransport:
    """Stream one resolved HTTPS artifact with bounded restart-safe behavior."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        resolver: ArtifactUrlResolver | None = None,
        policy: ArtifactTransferPolicy | None = None,
        disk_free_provider: DiskFreeProvider | None = None,
    ) -> None:
        self._client = client
        self._resolver = resolver
        self._policy = policy or ArtifactTransferPolicy()
        self._disk_free_provider = disk_free_provider or _disk_free_bytes

    async def transfer(
        self,
        *,
        resolved: ResolvedTransfer,
        destination: Path,
        quarantine_root: Path,
        checkpoint: HttpTransferCheckpoint | None = None,
        progress_callback: ProgressCallback | None = None,
        cancel_event: asyncio.Event | None = None,
        pause_event: asyncio.Event | None = None,
        refresh_transfer: RefreshTransfer | None = None,
    ) -> ArtifactTransferResult:
        """Stream a resolved transfer, preserving only safe retry checkpoints."""
        safe_path = validate_quarantine_file(
            destination,
            quarantine_root,
            allow_existing=checkpoint is not None,
        )
        _validate_expected_size(resolved.expected_size, self._policy)
        _validate_checkpoint(safe_path, checkpoint)
        _check_disk_budget(
            self._disk_free_provider,
            quarantine_root,
            expected_size=resolved.expected_size,
            existing_size=checkpoint.bytes_transferred if checkpoint else 0,
            policy=self._policy,
        )

        active = resolved
        refreshed = False
        if _is_expired(active):
            active = await _refresh_or_raise(refresh_transfer)
            refreshed = True
            _validate_expected_size(active.expected_size, self._policy)

        try:
            return await self._transfer_with_response_recovery(
                resolved=active,
                destination=safe_path,
                quarantine_root=quarantine_root,
                checkpoint=checkpoint,
                progress_callback=progress_callback,
                cancel_event=cancel_event,
                pause_event=pause_event,
                refresh_transfer=None if refreshed else refresh_transfer,
            )
        except ArtifactTransferCancelledError:
            remove_quarantine_file(safe_path)
            raise
        except ArtifactTransferPausedError:
            raise
        except ArtifactTransferError as exc:
            if not exc.retryable:
                remove_quarantine_file(safe_path)
            raise
        except asyncio.CancelledError:
            # Process shutdown keeps a regular partial so restart recovery can
            # prove identity and resume or restart it safely.
            raise

    async def _transfer_with_response_recovery(
        self,
        *,
        resolved: ResolvedTransfer,
        destination: Path,
        quarantine_root: Path,
        checkpoint: HttpTransferCheckpoint | None,
        progress_callback: ProgressCallback | None,
        cancel_event: asyncio.Event | None,
        pause_event: asyncio.Event | None,
        refresh_transfer: RefreshTransfer | None,
    ) -> ArtifactTransferResult:
        resume_offset = _eligible_resume_offset(resolved, checkpoint)
        active = resolved
        refreshed = False
        restarted_bad_range = False

        while True:
            response = await self._open_response(active, resume_offset=resume_offset)
            try:
                if response.status_code in _EXPIRED_URL_STATUSES and refresh_transfer is not None:
                    if refreshed:
                        raise _http_status_error(response.status_code)
                    await response.aclose()
                    active = await _refresh_or_raise(refresh_transfer)
                    _validate_expected_size(active.expected_size, self._policy)
                    resume_offset = _eligible_resume_offset(active, checkpoint)
                    refreshed = True
                    continue

                if resume_offset > 0 and not _valid_partial_response(
                    response,
                    resume_offset=resume_offset,
                    checkpoint=checkpoint,
                ):
                    if response.status_code == 200:
                        resume_offset = 0
                    elif not restarted_bad_range:
                        await response.aclose()
                        resume_offset = 0
                        restarted_bad_range = True
                        continue
                    else:
                        raise _object_changed_error()
                elif resume_offset == 0 and response.status_code != 200:
                    raise _http_status_error(response.status_code)

                return await self._stream_response(
                    response=response,
                    resolved=active,
                    destination=destination,
                    quarantine_root=quarantine_root,
                    resume_offset=resume_offset,
                    progress_callback=progress_callback,
                    cancel_event=cancel_event,
                    pause_event=pause_event,
                )
            finally:
                await response.aclose()

    async def _open_response(
        self,
        resolved: ResolvedTransfer,
        *,
        resume_offset: int,
    ) -> httpx.Response:
        current_url = resolved.url
        credential_origin: tuple[str, int] | None = None
        for redirect_count in range(self._policy.max_redirects + 1):
            try:
                target = await validate_artifact_url(
                    current_url,
                    allowed_domains=resolved.allowed_domains or None,
                    resolver=self._resolver,
                )
            except ArtifactHostResolutionError as exc:
                raise _from_resolution_error(exc) from exc

            if credential_origin is None:
                credential_origin = (target.host, target.port)
            include_sensitive = (target.host, target.port) == credential_origin

            request_url, host_header = pinned_request_target(target)
            request_headers = {
                **{
                    name: value
                    for name, value in resolved.headers.items()
                    if include_sensitive or name.lower() not in _SENSITIVE_HEADER_NAMES
                },
                "Accept-Encoding": "identity",
                "Host": host_header,
            }
            if resume_offset > 0:
                request_headers["Range"] = f"bytes={resume_offset}-"
                validator = resolved.etag or resolved.last_modified
                if validator:
                    request_headers["If-Range"] = validator
            request = self._client.build_request(
                "GET",
                request_url,
                headers=request_headers,
                extensions={"sni_hostname": target.host},
            )
            try:
                response = await self._client.send(
                    request,
                    stream=True,
                    follow_redirects=False,
                )
            except asyncio.CancelledError:
                raise
            except (httpx.HTTPError, TimeoutError) as exc:
                raise ArtifactTransferError(
                    code="artifact_host_unavailable",
                    message="The artifact host is temporarily unavailable.",
                    failure_class=DirectArtifactFailureClass.TRANSIENT_HOST,
                    retryable=True,
                    intervention=False,
                ) from exc

            if response.status_code not in _REDIRECT_STATUSES:
                return response
            if redirect_count == self._policy.max_redirects:
                await response.aclose()
                raise ArtifactTransferError(
                    code="artifact_host_redirect_limit",
                    message="The artifact host returned too many redirects.",
                    failure_class=DirectArtifactFailureClass.TRANSIENT_HOST,
                    retryable=True,
                    intervention=False,
                )
            location = response.headers.get("location")
            await response.aclose()
            if not location:
                raise ArtifactTransferError(
                    code="artifact_host_contract_changed",
                    message="The artifact host response no longer matches its supported contract.",
                    failure_class=DirectArtifactFailureClass.PERMANENT_MIRROR,
                    retryable=False,
                    intervention=True,
                )
            current_url = urljoin(target.url, location)

        raise AssertionError("redirect loop must return or raise")

    async def _stream_response(
        self,
        *,
        response: httpx.Response,
        resolved: ResolvedTransfer,
        destination: Path,
        quarantine_root: Path,
        resume_offset: int,
        progress_callback: ProgressCallback | None,
        cancel_event: asyncio.Event | None,
        pause_event: asyncio.Event | None,
    ) -> ArtifactTransferResult:
        total = _response_total(response, resume_offset=resume_offset)
        expected = total if total is not None else resolved.expected_size
        _validate_expected_size(expected, self._policy)
        if (
            resolved.expected_size is not None
            and expected is not None
            and resolved.expected_size != expected
        ):
            raise _object_changed_error()
        _check_disk_budget(
            self._disk_free_provider,
            quarantine_root,
            expected_size=expected,
            existing_size=resume_offset,
            policy=self._policy,
        )

        transferred = resume_offset
        start_time = time.monotonic()
        last_progress_at = start_time
        last_progress_bytes = transferred
        deadline = start_time + self._policy.total_timeout_seconds
        etag = response.headers.get("etag") or resolved.etag
        last_modified = response.headers.get("last-modified") or resolved.last_modified
        filename = (
            filename_from_content_disposition(response.headers.get("content-disposition"))
            or resolved.filename_hint
            or filename_from_url(resolved.url)
        )
        handle: BinaryIO | None = None
        iterator = response.aiter_bytes(self._policy.chunk_size_bytes).__aiter__()

        try:
            handle = open_quarantine_file(destination, append=resume_offset > 0)
            while True:
                _raise_for_control(
                    cancel_event=cancel_event,
                    pause_event=pause_event,
                    checkpoint=HttpTransferCheckpoint(
                        bytes_transferred=transferred,
                        expected_size=expected,
                        etag=etag,
                        last_modified=last_modified,
                    ),
                )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise _timeout_error("artifact_transfer_total_timeout")
                timeout = min(self._policy.idle_timeout_seconds, remaining)
                try:
                    chunk = await asyncio.wait_for(iterator.__anext__(), timeout=timeout)
                except StopAsyncIteration:
                    break
                except TimeoutError as exc:
                    raise _timeout_error("artifact_transfer_idle_timeout") from exc

                _raise_for_control(
                    cancel_event=cancel_event,
                    pause_event=pause_event,
                    checkpoint=HttpTransferCheckpoint(
                        bytes_transferred=transferred,
                        expected_size=expected,
                        etag=etag,
                        last_modified=last_modified,
                    ),
                )
                if not chunk:
                    continue
                if transferred + len(chunk) > self._policy.max_artifact_bytes:
                    raise _artifact_too_large_error()
                await asyncio.to_thread(handle.write, chunk)
                transferred += len(chunk)
                now = time.monotonic()
                if (
                    now - last_progress_at >= self._policy.progress_interval_seconds
                    or transferred - last_progress_bytes >= self._policy.progress_bytes
                ):
                    await _emit_progress(
                        progress_callback,
                        transferred=transferred,
                        total=expected,
                        started_at=start_time,
                        now=now,
                    )
                    last_progress_at = now
                    last_progress_bytes = transferred
        finally:
            if handle is not None:
                handle.close()

        if expected is not None and transferred != expected:
            raise _object_changed_error()
        await _emit_progress(
            progress_callback,
            transferred=transferred,
            total=expected,
            started_at=start_time,
            now=time.monotonic(),
        )
        return ArtifactTransferResult(
            path=destination,
            bytes_transferred=transferred,
            expected_size=expected,
            etag=etag,
            last_modified=last_modified,
            filename_hint=filename,
            resumed=resume_offset > 0,
        )


def _eligible_resume_offset(
    resolved: ResolvedTransfer,
    checkpoint: HttpTransferCheckpoint | None,
) -> int:
    if checkpoint is None or checkpoint.bytes_transferred <= 0:
        return 0
    validator_matches = bool(
        (checkpoint.etag and checkpoint.etag == resolved.etag)
        or (checkpoint.last_modified and checkpoint.last_modified == resolved.last_modified)
    )
    return checkpoint.bytes_transferred if resolved.range_supported and validator_matches else 0


def _valid_partial_response(
    response: httpx.Response,
    *,
    resume_offset: int,
    checkpoint: HttpTransferCheckpoint | None,
) -> bool:
    if response.status_code != 206 or checkpoint is None:
        return False
    content_range = response.headers.get("content-range", "")
    prefix = f"bytes {resume_offset}-"
    if not content_range.lower().startswith(prefix):
        return False
    response_etag = response.headers.get("etag")
    response_modified = response.headers.get("last-modified")
    if checkpoint.etag and response_etag and checkpoint.etag != response_etag:
        return False
    return not (
        checkpoint.last_modified
        and response_modified
        and checkpoint.last_modified != response_modified
    )


def _response_total(response: httpx.Response, *, resume_offset: int) -> int | None:
    content_range = response.headers.get("content-range", "")
    if "/" in content_range:
        raw_total = content_range.rsplit("/", 1)[1]
        if raw_total.isdigit():
            return int(raw_total)
    content_length = response.headers.get("content-length")
    if content_length and content_length.isdigit():
        return resume_offset + int(content_length)
    return None


def _validate_expected_size(size: int | None, policy: ArtifactTransferPolicy) -> None:
    if size is not None and (size < 0 or size > policy.max_artifact_bytes):
        raise _artifact_too_large_error()


def _validate_checkpoint(path: Path, checkpoint: HttpTransferCheckpoint | None) -> None:
    if checkpoint is None:
        return
    if checkpoint.bytes_transferred < 0:
        raise _object_changed_error()
    try:
        actual = path.stat().st_size
    except OSError as exc:
        raise _object_changed_error() from exc
    if actual != checkpoint.bytes_transferred:
        raise _object_changed_error()


def _check_disk_budget(
    provider: DiskFreeProvider,
    root: Path,
    *,
    expected_size: int | None,
    existing_size: int,
    policy: ArtifactTransferPolicy,
) -> None:
    remaining = max(0, (expected_size or 0) - existing_size)
    try:
        free = provider(root)
    except OSError as exc:
        raise ArtifactTransferError(
            code="artifact_disk_space_unavailable",
            message="Pullbox could not verify quarantine disk space.",
            failure_class=DirectArtifactFailureClass.SAFETY,
            retryable=False,
            intervention=True,
        ) from exc
    if free < remaining + policy.min_free_bytes:
        raise ArtifactTransferError(
            code="artifact_disk_space_insufficient",
            message="The direct-download quarantine does not have enough free space.",
            failure_class=DirectArtifactFailureClass.SAFETY,
            retryable=False,
            intervention=True,
        )


def _raise_for_control(
    *,
    cancel_event: asyncio.Event | None,
    pause_event: asyncio.Event | None,
    checkpoint: HttpTransferCheckpoint,
) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise ArtifactTransferCancelledError
    if pause_event is not None and pause_event.is_set():
        raise ArtifactTransferPausedError(checkpoint)


async def _emit_progress(
    callback: ProgressCallback | None,
    *,
    transferred: int,
    total: int | None,
    started_at: float,
    now: float,
) -> None:
    if callback is None:
        return
    elapsed = max(0.0, now - started_at)
    rate = transferred / elapsed if elapsed > 0 else None
    eta = (
        max(0.0, (total - transferred) / rate)
        if total is not None and rate and transferred <= total
        else None
    )
    percent = min(100, int((transferred * 100) / total)) if total and total > 0 else None
    result = callback(
        TransferProgressSnapshot(
            bytes_transferred=transferred,
            total_bytes=total,
            percent=percent,
            bytes_per_second=rate,
            eta_seconds=eta,
        )
    )
    if inspect.isawaitable(result):
        await result


async def _refresh_or_raise(refresh: RefreshTransfer | None) -> ResolvedTransfer:
    if refresh is None:
        raise ArtifactTransferError(
            code="artifact_url_expired",
            message="The artifact URL expired and must be resolved again.",
            failure_class=DirectArtifactFailureClass.TRANSIENT_HOST,
            retryable=True,
            intervention=False,
        )
    try:
        return await refresh()
    except ArtifactHostResolutionError as exc:
        raise _from_resolution_error(exc) from exc


def _is_expired(resolved: ResolvedTransfer) -> bool:
    expires_at = resolved.expires_at
    if expires_at is None:
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at <= datetime.now(UTC)


def _disk_free_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free


def _from_resolution_error(exc: ArtifactHostResolutionError) -> ArtifactTransferError:
    return ArtifactTransferError(
        code=exc.code,
        message=exc.message,
        failure_class=exc.failure_class,
        retryable=exc.retryable,
        intervention=exc.intervention,
    )


def _artifact_too_large_error() -> ArtifactTransferError:
    return ArtifactTransferError(
        code="artifact_too_large",
        message="The artifact exceeds the configured transfer size limit.",
        failure_class=DirectArtifactFailureClass.SAFETY,
        retryable=False,
        intervention=True,
    )


def _object_changed_error() -> ArtifactTransferError:
    return ArtifactTransferError(
        code="artifact_object_changed",
        message="The remote artifact changed during transfer.",
        failure_class=DirectArtifactFailureClass.TRANSIENT_HOST,
        retryable=True,
        intervention=False,
    )


def _timeout_error(code: str) -> ArtifactTransferError:
    return ArtifactTransferError(
        code=code,
        message="The artifact transfer stopped making progress.",
        failure_class=DirectArtifactFailureClass.TRANSIENT_HOST,
        retryable=True,
        intervention=False,
    )


def _http_status_error(status_code: int) -> ArtifactTransferError:
    if status_code in _EXPIRED_URL_STATUSES:
        return ArtifactTransferError(
            code="artifact_url_expired",
            message="The artifact URL expired and must be resolved again.",
            failure_class=DirectArtifactFailureClass.TRANSIENT_HOST,
            retryable=True,
            intervention=False,
        )
    if status_code == 429:
        return ArtifactTransferError(
            code="artifact_host_rate_limited",
            message="The artifact host is temporarily rate limited.",
            failure_class=DirectArtifactFailureClass.TRANSIENT_HOST,
            retryable=True,
            intervention=False,
        )
    return ArtifactTransferError(
        code="artifact_host_download_failed",
        message="The artifact host did not return a downloadable file.",
        failure_class=DirectArtifactFailureClass.PERMANENT_MIRROR,
        retryable=500 <= status_code < 600,
        intervention=status_code < 500,
    )
