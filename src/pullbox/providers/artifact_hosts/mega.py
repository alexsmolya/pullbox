"""MEGA adapter and isolated official-SDK bridge process contract."""

from __future__ import annotations

import asyncio
import inspect
import os
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, cast

from pullbox.models.direct_acquisition import (
    DirectArtifactFailureClass,
    DirectArtifactHostKind,
)
from pullbox.providers.artifact_hosts.contract import (
    ArtifactTransferProtocol,
    HostResolutionRequest,
    ResolvedTransfer,
)
from pullbox.providers.artifact_hosts.helpers import safe_filename, validate_resolution_request
from pullbox.providers.artifact_hosts.transfer_safety import (
    DiskFreeProvider,
    check_disk_budget,
    disk_free_bytes,
    parse_checksum,
    validate_expected_size,
    verify_checksum,
)
from pullbox.providers.artifact_hosts.transport_contract import ArtifactTransferPolicy

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from pullbox.providers.artifact_hosts.contract import ArtifactResolutionProgressCallback

MegaProgressCallback = Callable[[int, int], Awaitable[None] | None]

_PROTOCOL_HEADER = b"PULLBOX_MEGA_BRIDGE 1\n"
_MAX_REQUEST_FIELD_BYTES = 16 * 1024
_MAX_EVENT_LINE_BYTES = 64 * 1024
_MAX_EVENT_COUNT = 1_000_000
_DEFAULT_IDLE_TIMEOUT_SECONDS = 120.0
_DEFAULT_TOTAL_TIMEOUT_SECONDS = 24 * 60 * 60.0
_PROCESS_TERMINATE_TIMEOUT_SECONDS = 2.0
_ERROR_CODE = re.compile(r"[a-z][a-z0-9_]{0,99}\Z")


class MegaArtifactHostAdapter:
    """Resolve a MEGA share into the process-isolated transfer protocol."""

    host_kind = DirectArtifactHostKind.MEGA

    async def resolve(
        self,
        request: HostResolutionRequest,
        *,
        credentials: Mapping[str, str],
        progress_callback: ArtifactResolutionProgressCallback | None = None,
    ) -> ResolvedTransfer:
        url = validate_resolution_request(
            request,
            expected_kind=self.host_kind,
            credentials=credentials,
        )
        return ResolvedTransfer(
            host_kind=self.host_kind,
            url=url,
            expected_size=request.expected_size,
            checksum=request.checksum,
            etag=request.etag,
            last_modified=request.last_modified,
            expires_at=request.expires_at,
            allowed_domains=("mega.nz", "mega.co.nz"),
            transport_protocol=ArtifactTransferProtocol.MEGA_BRIDGE,
            bridge_session=credentials.get("session") or None,
        )


@dataclass(frozen=True, slots=True)
class MegaBridgeTransferResult:
    """Secret-free result returned after a bridge process exits cleanly."""

    bytes_transferred: int
    filename_hint: str | None
    command_summary: str
    _destination: Path = field(repr=False)


class MegaBridgeTransferError(RuntimeError):
    """Stable MEGA bridge failure that never includes process output."""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        failure_class: DirectArtifactFailureClass,
        retryable: bool,
        intervention: bool,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.failure_class = failure_class
        self.retryable = retryable
        self.intervention = intervention

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(code={self.code!r}, "
            f"failure_class={self.failure_class.value!r}, "
            f"retryable={self.retryable!r}, intervention={self.intervention!r})"
        )


class MegaBridgePausedError(MegaBridgeTransferError):
    """MEGA pause outcome; SDK transfers restart from zero on resume."""

    def __init__(self) -> None:
        super().__init__(
            code="mega_transfer_paused",
            message="The MEGA transfer was paused and will restart from the beginning.",
            failure_class=DirectArtifactFailureClass.USER_ACTION,
            retryable=True,
            intervention=False,
        )
        self.bytes_transferred = 0


class MegaBridgeCancelledError(MegaBridgeTransferError):
    """Explicit user cancellation, distinct from process shutdown."""

    def __init__(self) -> None:
        super().__init__(
            code="mega_transfer_cancelled",
            message="The MEGA transfer was cancelled.",
            failure_class=DirectArtifactFailureClass.USER_ACTION,
            retryable=False,
            intervention=False,
        )


class MegaBridgeRunner:
    """Run one SDK-backed MEGA transfer without putting secrets in argv or env."""

    def __init__(
        self,
        *,
        command: Sequence[str | os.PathLike[str]] = ("/usr/bin/pullbox-mega-bridge",),
        idle_timeout_seconds: float = _DEFAULT_IDLE_TIMEOUT_SECONDS,
        total_timeout_seconds: float = _DEFAULT_TOTAL_TIMEOUT_SECONDS,
        policy: ArtifactTransferPolicy | None = None,
        disk_free_provider: DiskFreeProvider | None = None,
    ) -> None:
        if not command or any(not os.fspath(part) for part in command):
            raise ValueError("MEGA bridge command cannot be empty.")
        if idle_timeout_seconds <= 0 or total_timeout_seconds <= 0:
            raise ValueError("MEGA bridge timeouts must be positive.")
        self._command = tuple(os.fspath(part) for part in command)
        self._idle_timeout_seconds = idle_timeout_seconds
        self._total_timeout_seconds = total_timeout_seconds
        self._policy = policy or ArtifactTransferPolicy()
        self._disk_free_provider = disk_free_provider or disk_free_bytes

    async def transfer(
        self,
        *,
        public_link: str,
        destination: Path,
        quarantine_root: Path,
        session: str | None = None,
        expected_size: int | None = None,
        checksum: str | None = None,
        cancel_event: asyncio.Event | None = None,
        pause_event: asyncio.Event | None = None,
        progress_callback: MegaProgressCallback | None = None,
    ) -> MegaBridgeTransferResult:
        """Download one MEGA artifact into an unused app-owned quarantine path."""
        _validate_request_field("public link", public_link, allow_empty=False)
        _validate_request_field("session", session or "", allow_empty=True)
        safe_destination = _validate_quarantine_destination(destination, quarantine_root)
        validate_expected_size(expected_size, self._policy)
        parse_checksum(checksum)
        check_disk_budget(
            self._disk_free_provider,
            quarantine_root,
            expected_size=expected_size,
            existing_size=0,
            policy=self._policy,
        )
        if cancel_event is not None and cancel_event.is_set():
            raise MegaBridgeCancelledError

        try:
            proc = await asyncio.create_subprocess_exec(
                *self._command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=_bridge_environment(),
                limit=_MAX_EVENT_LINE_BYTES + 1,
            )
        except OSError as exc:
            raise _bridge_unavailable_error() from exc
        if proc.stdin is None or proc.stdout is None or proc.stderr is None:
            await _terminate_process(proc)
            raise _protocol_error()

        stderr_task = asyncio.create_task(_read_stderr_bounded(proc.stderr))
        cancel_task = asyncio.create_task(cancel_event.wait()) if cancel_event is not None else None
        pause_task = asyncio.create_task(pause_event.wait()) if pause_event is not None else None
        completed_bytes: int | None = None
        filename_hint: str | None = None
        event_count = 0
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._total_timeout_seconds

        try:
            await _send_request(
                proc.stdin,
                public_link=public_link,
                session=session or "",
                destination=safe_destination,
            )
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise _timeout_error("mega_bridge_total_timeout")
                timeout = min(self._idle_timeout_seconds, remaining)
                line_task = asyncio.create_task(proc.stdout.readline())
                waiters: set[asyncio.Task[object]] = {line_task}
                if cancel_task is not None:
                    waiters.add(cancel_task)
                if pause_task is not None:
                    waiters.add(pause_task)
                done, _pending = await asyncio.wait(
                    waiters,
                    timeout=timeout,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if cancel_task is not None and cancel_task in done:
                    line_task.cancel()
                    await _terminate_process(proc)
                    raise MegaBridgeCancelledError
                if pause_task is not None and pause_task in done:
                    line_task.cancel()
                    await _terminate_process(proc)
                    raise MegaBridgePausedError
                if line_task not in done:
                    line_task.cancel()
                    raise _timeout_error("mega_bridge_idle_timeout")

                try:
                    raw_line = line_task.result()
                except (ValueError, asyncio.LimitOverrunError) as exc:
                    raise _protocol_error() from exc
                if not raw_line:
                    break
                event_count += 1
                if event_count > _MAX_EVENT_COUNT or len(raw_line) > _MAX_EVENT_LINE_BYTES:
                    raise _protocol_error()

                event, values = _parse_event(raw_line)
                if event == "META":
                    metadata_size = cast("int", values[0])
                    metadata_name = cast("str | None", values[1])
                    validate_expected_size(metadata_size, self._policy)
                    if expected_size is not None and metadata_size != expected_size:
                        raise _changed_object_error()
                    check_disk_budget(
                        self._disk_free_provider,
                        quarantine_root,
                        expected_size=metadata_size,
                        existing_size=0,
                        policy=self._policy,
                    )
                    filename_hint = metadata_name
                elif event == "PROGRESS":
                    current = cast("int", values[0])
                    total = cast("int", values[1])
                    validate_expected_size(total, self._policy)
                    if expected_size is not None and total != expected_size:
                        raise _changed_object_error()
                    check_disk_budget(
                        self._disk_free_provider,
                        quarantine_root,
                        expected_size=total,
                        existing_size=current,
                        policy=self._policy,
                    )
                    await _emit_progress(progress_callback, current, total)
                elif event == "COMPLETE":
                    completed_bytes = cast("int", values[0])
                    validate_expected_size(completed_bytes, self._policy)
                    filename_hint = cast("str | None", values[1])
                elif event == "ERROR":
                    code = cast("str", values[0])
                    retryable = cast("bool", values[1])
                    intervention = cast("bool", values[2])
                    raise _mapped_bridge_error(code, retryable, intervention)

            return_code = await proc.wait()
            await stderr_task
            if return_code != 0 or completed_bytes is None:
                raise _protocol_error()
            actual_size = _validate_completed_file(safe_destination)
            if actual_size != completed_bytes:
                raise _changed_object_error()
            if expected_size is not None and actual_size != expected_size:
                raise _changed_object_error()
            await verify_checksum(safe_destination, checksum)
            return MegaBridgeTransferResult(
                bytes_transferred=actual_size,
                filename_hint=filename_hint,
                command_summary=" ".join(Path(part).name for part in self._command),
                _destination=safe_destination,
            )
        except BaseException:
            await _terminate_process(proc)
            _remove_partial(safe_destination)
            raise
        finally:
            if cancel_task is not None:
                cancel_task.cancel()
            if pause_task is not None:
                pause_task.cancel()
            if not stderr_task.done():
                stderr_task.cancel()


async def _send_request(
    stdin: asyncio.StreamWriter,
    *,
    public_link: str,
    session: str,
    destination: Path,
) -> None:
    link_bytes = public_link.encode("utf-8")
    session_bytes = session.encode("utf-8")
    destination_bytes = os.fspath(destination).encode("utf-8")
    lengths = f"DOWNLOAD {len(link_bytes)} {len(session_bytes)} {len(destination_bytes)}\n".encode(
        "ascii"
    )
    try:
        stdin.write(_PROTOCOL_HEADER + lengths + link_bytes + session_bytes + destination_bytes)
        await stdin.drain()
        stdin.close()
        await stdin.wait_closed()
    except (BrokenPipeError, ConnectionResetError) as exc:
        raise _protocol_error() from exc


def _parse_event(raw_line: bytes) -> tuple[str, tuple[object, ...]]:
    try:
        line = raw_line.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise _protocol_error() from exc
    parts = line.split()
    if not parts:
        raise _protocol_error()
    event = parts[0]
    try:
        if event == "META" and len(parts) == 3:
            return event, (_positive_integer(parts[1]), _decode_filename(parts[2]))
        if event == "PROGRESS" and len(parts) == 3:
            current = _positive_integer(parts[1])
            total = _positive_integer(parts[2])
            if current > total:
                raise ValueError
            return event, (current, total)
        if event == "COMPLETE" and len(parts) == 3:
            return event, (_positive_integer(parts[1]), _decode_filename(parts[2]))
        if event == "ERROR" and len(parts) == 4 and _ERROR_CODE.fullmatch(parts[1]):
            if parts[2] not in {"0", "1"} or parts[3] not in {"0", "1"}:
                raise ValueError
            return event, (parts[1], parts[2] == "1", parts[3] == "1")
    except (UnicodeDecodeError, ValueError) as exc:
        raise _protocol_error() from exc
    raise _protocol_error()


def _decode_filename(value: str) -> str | None:
    if len(value) > 510 or len(value) % 2:
        raise ValueError
    decoded = bytes.fromhex(value).decode("utf-8")
    return safe_filename(decoded)


def _positive_integer(value: str) -> int:
    if not value.isdigit():
        raise ValueError
    parsed = int(value)
    if parsed > 10 * 1024**4:
        raise ValueError
    return parsed


async def _emit_progress(
    callback: MegaProgressCallback | None,
    current: int,
    total: int,
) -> None:
    if callback is None:
        return
    result = callback(current, total)
    if inspect.isawaitable(result):
        await result


async def _read_stderr_bounded(stderr: asyncio.StreamReader) -> None:
    total = 0
    try:
        while chunk := await stderr.read(8192):
            total += len(chunk)
            if total > _MAX_EVENT_LINE_BYTES:
                raise _protocol_error()
    except (ValueError, asyncio.LimitOverrunError) as exc:
        raise _protocol_error() from exc


async def _terminate_process(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=_PROCESS_TERMINATE_TIMEOUT_SECONDS)
    except TimeoutError:
        proc.kill()
        await proc.wait()


def _validate_request_field(label: str, value: str, *, allow_empty: bool) -> None:
    encoded = value.encode("utf-8")
    if (not allow_empty and not encoded) or len(encoded) > _MAX_REQUEST_FIELD_BYTES:
        raise ValueError(f"MEGA bridge {label} is invalid.")
    if "\x00" in value:
        raise ValueError(f"MEGA bridge {label} is invalid.")


def _validate_quarantine_destination(destination: Path, quarantine_root: Path) -> Path:
    try:
        root = quarantine_root.resolve(strict=True)
    except OSError as exc:
        raise _quarantine_error() from exc
    if not root.is_dir() or root.is_symlink():
        raise _quarantine_error()

    candidate = destination.expanduser()
    if candidate.exists() or candidate.is_symlink():
        raise _quarantine_error()
    try:
        parent = candidate.parent.resolve(strict=True)
        parent.relative_to(root)
    except (OSError, ValueError) as exc:
        raise _quarantine_error() from exc
    if not parent.is_dir() or parent.is_symlink():
        raise _quarantine_error()
    return parent / candidate.name


def _validate_completed_file(destination: Path) -> int:
    try:
        if destination.is_symlink() or not destination.is_file():
            raise _quarantine_error()
        return destination.stat().st_size
    except OSError as exc:
        raise _quarantine_error() from exc


def _remove_partial(destination: Path) -> None:
    try:
        if destination.is_file() and not destination.is_symlink():
            destination.unlink()
    except OSError:
        pass


def _bridge_environment() -> dict[str, str]:
    allowed = ("PATH", "SSL_CERT_DIR", "SSL_CERT_FILE", "TZ")
    return {name: os.environ[name] for name in allowed if name in os.environ}


def _mapped_bridge_error(
    code: str,
    retryable: bool,
    intervention: bool,
) -> MegaBridgeTransferError:
    if code in {"mega_auth_required", "mega_session_expired"}:
        failure_class = DirectArtifactFailureClass.ARTIFACT_HOST_AUTH_REQUIRED
    elif code == "mega_quota_exceeded":
        failure_class = DirectArtifactFailureClass.HOST_QUOTA
    elif intervention:
        failure_class = DirectArtifactFailureClass.PERMANENT_MIRROR
    else:
        failure_class = DirectArtifactFailureClass.TRANSIENT_HOST
    return MegaBridgeTransferError(
        code=code,
        message="The MEGA transfer could not be completed.",
        failure_class=failure_class,
        retryable=retryable,
        intervention=intervention,
    )


def _protocol_error() -> MegaBridgeTransferError:
    return MegaBridgeTransferError(
        code="mega_bridge_protocol_error",
        message="The MEGA bridge returned an invalid response.",
        failure_class=DirectArtifactFailureClass.SAFETY,
        retryable=False,
        intervention=True,
    )


def _bridge_unavailable_error() -> MegaBridgeTransferError:
    return MegaBridgeTransferError(
        code="mega_bridge_unavailable",
        message="The MEGA transfer helper is unavailable.",
        failure_class=DirectArtifactFailureClass.UNSUPPORTED_ARTIFACT_HOST,
        retryable=False,
        intervention=True,
    )


def _quarantine_error() -> MegaBridgeTransferError:
    return MegaBridgeTransferError(
        code="unsafe_quarantine_destination",
        message="The MEGA bridge destination is outside its safe quarantine.",
        failure_class=DirectArtifactFailureClass.SAFETY,
        retryable=False,
        intervention=True,
    )


def _changed_object_error() -> MegaBridgeTransferError:
    return MegaBridgeTransferError(
        code="mega_object_changed",
        message="The MEGA object changed during transfer.",
        failure_class=DirectArtifactFailureClass.TRANSIENT_HOST,
        retryable=True,
        intervention=False,
    )


def _timeout_error(code: str) -> MegaBridgeTransferError:
    return MegaBridgeTransferError(
        code=code,
        message="The MEGA transfer stopped making progress.",
        failure_class=DirectArtifactFailureClass.TRANSIENT_HOST,
        retryable=True,
        intervention=False,
    )
