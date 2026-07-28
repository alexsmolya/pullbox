"""Durable coordinator for direct artifact transfer and existing ingestion."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from pullbox.models.direct_acquisition import (
    DirectAcquisitionAttempt,
    DirectAcquisitionState,
    DirectArtifactAttempt,
    DirectArtifactFailureClass,
    DirectArtifactHostKind,
    DirectArtifactRouteKind,
    DirectArtifactState,
    DirectHostAccountState,
    DirectHostConfig,
)
from pullbox.providers.artifact_hosts.contract import (
    ArtifactHostResolutionError,
    ArtifactTransferProtocol,
    HostResolutionRequest,
    ResolvedTransfer,
)
from pullbox.providers.artifact_hosts.limiter import ArtifactTransferLimiter
from pullbox.providers.artifact_hosts.mega import (
    MegaBridgeCancelledError,
    MegaBridgePausedError,
    MegaBridgeTransferError,
)
from pullbox.providers.artifact_hosts.quarantine import remove_quarantine_file
from pullbox.providers.artifact_hosts.transport_contract import (
    ArtifactTransferCancelledError,
    ArtifactTransferError,
    ArtifactTransferPausedError,
    ArtifactTransferResult,
    HttpTransferCheckpoint,
    TransferProgressSnapshot,
)
from pullbox.services.direct_acquisition_state import (
    advance_acquisition_progress,
    transition_acquisition,
    transition_artifact,
)
from pullbox.services.direct_artifact_post_processing import (
    DirectPostProcessingResult,
    run_direct_artifact_post_processing,
)
from pullbox.services.direct_artifact_quarantine import (
    DirectArtifactQuarantine,
    DirectArtifactValidationError,
    DirectArtifactValidationResult,
    DirectQuarantineWorkspace,
    validate_direct_artifact,
)
from pullbox.services.direct_configuration_service import load_host_credential_material

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

SourceFactory = Callable[[], Awaitable[HostResolutionRequest]]
PostProcessor = Callable[..., Awaitable[DirectPostProcessingResult]]
ArtifactValidator = Callable[["AsyncSession", Path], Awaitable[DirectArtifactValidationResult]]
Clock = Callable[[], datetime]

_PROGRESS_INTERVAL_SECONDS = 1.0
_PROGRESS_BYTES = 8 * 1024**2


@dataclass(frozen=True, slots=True)
class DirectExecutionResult:
    """Redacted durable outcome from one coordinator pass."""

    acquisition_id: int
    artifact_id: int
    state: DirectAcquisitionState
    artifact_state: DirectArtifactState
    library_file_id: int | None


class DirectAcquisitionExecutor:
    """Own direct state transitions while delegating bytes and ingestion."""

    def __init__(
        self,
        *,
        host_resolver: Any,
        http_transport: Any,
        mega_runner: Any,
        quarantine: DirectArtifactQuarantine,
        limiter: ArtifactTransferLimiter | None = None,
        validator: ArtifactValidator = validate_direct_artifact,
        post_processor: PostProcessor = run_direct_artifact_post_processing,
        now: Clock | None = None,
    ) -> None:
        self._host_resolver = host_resolver
        self._http_transport = http_transport
        self._mega_runner = mega_runner
        self._quarantine = quarantine
        self._limiter = limiter or ArtifactTransferLimiter(global_limit=3, per_host_limit=1)
        self._validator = validator
        self._post_processor = post_processor
        self._now = now or (lambda: datetime.now(UTC))

    async def execute(
        self,
        session: AsyncSession,
        *,
        acquisition_id: int,
        artifact_id: int,
        source_factory: SourceFactory,
        cancel_event: asyncio.Event | None = None,
        pause_event: asyncio.Event | None = None,
    ) -> DirectExecutionResult:
        """Run or recover one selected direct artifact without persisting secrets."""
        attempt, artifact = await _load_attempt(session, acquisition_id, artifact_id)
        _validate_runnable(attempt, artifact)
        workspace = self._quarantine.prepare(
            acquisition_id=attempt.id,
            artifact_id=artifact.id,
        )
        progress = _ProgressWriter(session, attempt, artifact)

        try:
            final_path = _recover_final_path(workspace, artifact)
            if attempt.state is DirectAcquisitionState.POST_PROCESSING:
                if final_path is None:
                    raise _missing_quarantine_error()
                return await self._post_process(
                    session,
                    attempt,
                    artifact,
                    workspace,
                    final_path,
                    progress,
                )
            if attempt.state is DirectAcquisitionState.VALIDATING:
                if final_path is None:
                    raise _missing_quarantine_error()
                return await self._validate_and_post_process(
                    session,
                    attempt,
                    artifact,
                    workspace,
                    final_path,
                    progress,
                )

            await _enter_resolving(session, attempt, artifact, progress)
            request = await source_factory()
            _validate_source_request(request, artifact)
            credentials, host_config_id = await _load_host_credentials(
                session,
                artifact.host_kind,
            )

            async with self._limiter.slot(artifact.host_kind):
                resolved = await self._resolve_host(
                    session,
                    request=request,
                    credentials=credentials,
                    host_config_id=host_config_id,
                )
                await _enter_downloading(session, attempt, artifact, workspace, progress)
                transfer_result = await self._transfer(
                    session=session,
                    attempt=attempt,
                    artifact=artifact,
                    workspace=workspace,
                    resolved=resolved,
                    source_factory=source_factory,
                    credentials=credentials,
                    host_config_id=host_config_id,
                    progress=progress,
                    cancel_event=cancel_event,
                    pause_event=pause_event,
                )

            final_path = self._quarantine.finalize(
                workspace,
                filename_hint=transfer_result.filename_hint,
            )
            artifact.quarantine_path = str(final_path)
            artifact.bytes_transferred = transfer_result.bytes_transferred
            artifact.expected_size = transfer_result.expected_size
            artifact.etag = transfer_result.etag
            artifact.last_modified_at = _parse_last_modified(transfer_result.last_modified)
            transition_acquisition(attempt, DirectAcquisitionState.VALIDATING, at=self._now())
            transition_artifact(artifact, DirectArtifactState.VALIDATING, at=self._now())
            await progress.write(stage="validating", force=True)
            return await self._validate_and_post_process(
                session,
                attempt,
                artifact,
                workspace,
                final_path,
                progress,
            )
        except (ArtifactTransferPausedError, MegaBridgePausedError) as exc:
            return await self._pause(session, attempt, artifact, workspace, progress, exc)
        except (ArtifactTransferCancelledError, MegaBridgeCancelledError):
            self._quarantine.cleanup(workspace)
            artifact.quarantine_path = None
            artifact.bytes_transferred = 0
            transition_artifact(artifact, DirectArtifactState.CANCELLED, at=self._now())
            transition_acquisition(attempt, DirectAcquisitionState.CANCELLED, at=self._now())
            await progress.write(stage="cancelled", force=True)
            return _result(attempt, artifact)
        except (
            ArtifactHostResolutionError,
            ArtifactTransferError,
            MegaBridgeTransferError,
            DirectArtifactValidationError,
        ) as exc:
            return await self._classified_failure(
                session,
                attempt,
                artifact,
                progress,
                exc,
            )
        except asyncio.CancelledError:
            await session.commit()
            raise

    async def _resolve_host(
        self,
        session: AsyncSession,
        *,
        request: HostResolutionRequest,
        credentials: dict[str, str],
        host_config_id: int | None,
    ) -> ResolvedTransfer:
        try:
            resolved = cast(
                "ResolvedTransfer",
                await self._host_resolver.resolve(request, credentials=credentials),
            )
        except ArtifactHostResolutionError as exc:
            await _record_host_account_result(
                session,
                host_config_id=host_config_id,
                checked_at=self._now(),
                error=exc,
            )
            raise
        await _record_host_account_result(
            session,
            host_config_id=host_config_id,
            checked_at=self._now(),
            error=None,
        )
        return resolved

    async def _transfer(
        self,
        *,
        session: AsyncSession,
        attempt: DirectAcquisitionAttempt,
        artifact: DirectArtifactAttempt,
        workspace: DirectQuarantineWorkspace,
        resolved: ResolvedTransfer,
        source_factory: SourceFactory,
        credentials: dict[str, str],
        host_config_id: int | None,
        progress: _ProgressWriter,
        cancel_event: asyncio.Event | None,
        pause_event: asyncio.Event | None,
    ) -> ArtifactTransferResult:
        if resolved.transport_protocol is ArtifactTransferProtocol.MEGA_BRIDGE:
            remove_quarantine_file(workspace.partial_path)
            artifact.bytes_transferred = 0
            artifact.etag = None
            artifact.last_modified_at = None
            await session.commit()

            async def mega_progress(current: int, total: int) -> None:
                artifact.bytes_transferred = current
                artifact.expected_size = total
                await progress.write(
                    stage="downloading",
                    snapshot=TransferProgressSnapshot(
                        bytes_transferred=current,
                        total_bytes=total,
                        percent=round((current / total) * 100) if total else None,
                        bytes_per_second=None,
                        eta_seconds=None,
                    ),
                )

            mega_result = await self._mega_runner.transfer(
                public_link=resolved.url,
                destination=workspace.partial_path,
                quarantine_root=workspace.root,
                session=resolved.bridge_session,
                expected_size=resolved.expected_size,
                cancel_event=cancel_event,
                pause_event=pause_event,
                progress_callback=mega_progress,
            )
            await progress.write(stage="downloading", force=True)
            return ArtifactTransferResult(
                path=workspace.partial_path,
                bytes_transferred=mega_result.bytes_transferred,
                expected_size=resolved.expected_size or mega_result.bytes_transferred,
                etag=None,
                last_modified=None,
                filename_hint=mega_result.filename_hint,
                resumed=False,
            )

        checkpoint = _recover_http_checkpoint(workspace, artifact)

        async def http_progress(snapshot: TransferProgressSnapshot) -> None:
            artifact.bytes_transferred = snapshot.bytes_transferred
            artifact.expected_size = snapshot.total_bytes
            await progress.write(stage="downloading", snapshot=snapshot)

        async def refresh_transfer() -> ResolvedTransfer:
            refreshed_request = await source_factory()
            _validate_source_request(refreshed_request, artifact)
            return await self._resolve_host(
                session,
                request=refreshed_request,
                credentials=credentials,
                host_config_id=host_config_id,
            )

        result = await self._http_transport.transfer(
            resolved=resolved,
            destination=workspace.partial_path,
            quarantine_root=workspace.root,
            checkpoint=checkpoint,
            progress_callback=http_progress,
            cancel_event=cancel_event,
            pause_event=pause_event,
            refresh_transfer=refresh_transfer,
        )
        await progress.write(stage="downloading", force=True)
        return cast("ArtifactTransferResult", result)

    async def _validate_and_post_process(
        self,
        session: AsyncSession,
        attempt: DirectAcquisitionAttempt,
        artifact: DirectArtifactAttempt,
        workspace: DirectQuarantineWorkspace,
        final_path: Path,
        progress: _ProgressWriter,
    ) -> DirectExecutionResult:
        await self._validator(session, final_path)
        transition_acquisition(attempt, DirectAcquisitionState.POST_PROCESSING, at=self._now())
        await progress.write(stage="post_processing", force=True)
        return await self._post_process(
            session,
            attempt,
            artifact,
            workspace,
            final_path,
            progress,
        )

    async def _post_process(
        self,
        session: AsyncSession,
        attempt: DirectAcquisitionAttempt,
        artifact: DirectArtifactAttempt,
        workspace: DirectQuarantineWorkspace,
        final_path: Path,
        progress: _ProgressWriter,
    ) -> DirectExecutionResult:
        try:
            processed = await self._post_processor(
                session,
                acquisition_id=attempt.id,
                issue_id=attempt.issue_id,
                source_path=final_path,
                replace_existing_file=attempt.replace_existing_file,
            )
        except Exception:
            attempt.failure_class = DirectArtifactFailureClass.POST_PROCESS
            attempt.failure_code = "direct_post_processing_failed"
            attempt.error_message = "Direct artifact post-processing failed."
            artifact.failure_class = DirectArtifactFailureClass.POST_PROCESS
            artifact.failure_code = "direct_post_processing_failed"
            artifact.error_message = "Direct artifact post-processing failed."
            transition_artifact(artifact, DirectArtifactState.INTERVENTION, at=self._now())
            transition_acquisition(attempt, DirectAcquisitionState.INTERVENTION, at=self._now())
            await progress.write(stage="intervention", force=True)
            return _result(attempt, artifact)

        attempt.library_file_id = processed.library_file_id
        attempt.failure_class = None
        attempt.failure_code = None
        attempt.error_message = None
        artifact.failure_class = None
        artifact.failure_code = None
        artifact.error_message = None
        artifact.quarantine_path = None
        transition_artifact(artifact, DirectArtifactState.COMPLETED, at=self._now())
        transition_acquisition(attempt, DirectAcquisitionState.COMPLETED, at=self._now())
        self._quarantine.cleanup(workspace)
        await progress.write(stage="completed", force=True)
        return _result(attempt, artifact)

    async def _pause(
        self,
        session: AsyncSession,
        attempt: DirectAcquisitionAttempt,
        artifact: DirectArtifactAttempt,
        workspace: DirectQuarantineWorkspace,
        progress: _ProgressWriter,
        exc: ArtifactTransferPausedError | MegaBridgePausedError,
    ) -> DirectExecutionResult:
        if isinstance(exc, ArtifactTransferPausedError):
            artifact.bytes_transferred = exc.checkpoint.bytes_transferred
            artifact.expected_size = exc.checkpoint.expected_size
            artifact.etag = exc.checkpoint.etag
            artifact.last_modified_at = _parse_last_modified(exc.checkpoint.last_modified)
        else:
            remove_quarantine_file(workspace.partial_path)
            artifact.bytes_transferred = 0
            artifact.etag = None
            artifact.last_modified_at = None
        transition_artifact(artifact, DirectArtifactState.PAUSED, at=self._now())
        transition_acquisition(attempt, DirectAcquisitionState.PAUSED, at=self._now())
        await progress.write(stage="paused", force=True)
        return _result(attempt, artifact)

    async def _classified_failure(
        self,
        session: AsyncSession,
        attempt: DirectAcquisitionAttempt,
        artifact: DirectArtifactAttempt,
        progress: _ProgressWriter,
        exc: Any,
    ) -> DirectExecutionResult:
        attempt.failure_class = exc.failure_class
        attempt.failure_code = exc.code
        attempt.error_message = str(exc)
        artifact.failure_class = exc.failure_class
        artifact.failure_code = exc.code
        artifact.error_message = str(exc)
        can_retry = (
            bool(exc.retryable)
            and attempt.retry_count < attempt.max_retries
            and artifact.retry_count < artifact.max_retries
        )
        if can_retry:
            attempt.retry_count += 1
            artifact.retry_count += 1
            delay = timedelta(seconds=min(3600, 60 * (2 ** (attempt.retry_count - 1))))
            retry_at = self._now() + delay
            attempt.next_retry_at = retry_at
            artifact.next_retry_at = retry_at
            transition_artifact(artifact, DirectArtifactState.RETRY_PENDING, at=self._now())
            transition_acquisition(attempt, DirectAcquisitionState.RETRY_PENDING, at=self._now())
            stage = "retry_pending"
        elif bool(exc.intervention):
            transition_artifact(artifact, DirectArtifactState.INTERVENTION, at=self._now())
            transition_acquisition(attempt, DirectAcquisitionState.INTERVENTION, at=self._now())
            stage = "intervention"
        else:
            transition_artifact(artifact, DirectArtifactState.FAILED, at=self._now())
            transition_acquisition(attempt, DirectAcquisitionState.FAILED, at=self._now())
            stage = "failed"
        await progress.write(stage=stage, force=True)
        return _result(attempt, artifact)


class _ProgressWriter:
    def __init__(
        self,
        session: AsyncSession,
        attempt: DirectAcquisitionAttempt,
        artifact: DirectArtifactAttempt,
    ) -> None:
        self._session = session
        self._attempt = attempt
        self._artifact = artifact
        self._last_saved_at = 0.0
        self._last_saved_bytes = -1

    async def write(
        self,
        *,
        stage: str,
        snapshot: TransferProgressSnapshot | None = None,
        force: bool = False,
    ) -> None:
        now = time.monotonic()
        current_bytes = (
            snapshot.bytes_transferred if snapshot is not None else self._artifact.bytes_transferred
        )
        if (
            not force
            and self._last_saved_bytes >= 0
            and now - self._last_saved_at < _PROGRESS_INTERVAL_SECONDS
            and current_bytes - self._last_saved_bytes < _PROGRESS_BYTES
        ):
            return
        data: dict[str, object] = {
            "schema_version": 1,
            "stage": stage,
            "artifact_attempt_id": self._artifact.id,
            "host_kind": self._artifact.host_kind.value,
            "bytes_transferred": current_bytes,
            "total_bytes": snapshot.total_bytes if snapshot is not None else None,
            "percent": snapshot.percent if snapshot is not None else None,
            "bytes_per_second": snapshot.bytes_per_second if snapshot is not None else None,
            "eta_seconds": snapshot.eta_seconds if snapshot is not None else None,
        }
        advance_acquisition_progress(
            self._attempt,
            revision=self._attempt.progress_revision + 1,
            snapshot=data,
        )
        await self._session.commit()
        self._last_saved_at = now
        self._last_saved_bytes = current_bytes


async def _load_attempt(
    session: AsyncSession,
    acquisition_id: int,
    artifact_id: int,
) -> tuple[DirectAcquisitionAttempt, DirectArtifactAttempt]:
    result = await session.execute(
        select(DirectAcquisitionAttempt)
        .options(selectinload(DirectAcquisitionAttempt.artifact_attempts))
        .where(DirectAcquisitionAttempt.id == acquisition_id)
    )
    attempt = result.scalar_one_or_none()
    if attempt is None:
        raise ValueError("Direct acquisition attempt was not found.")
    artifact = next(
        (candidate for candidate in attempt.artifact_attempts if candidate.id == artifact_id),
        None,
    )
    if artifact is None:
        raise ValueError("Direct artifact attempt was not found.")
    return attempt, artifact


def _validate_runnable(
    attempt: DirectAcquisitionAttempt,
    artifact: DirectArtifactAttempt,
) -> None:
    if artifact.route_kind is not DirectArtifactRouteKind.DIRECT:
        raise ValueError("Only direct artifact routes use the native transfer executor.")
    if attempt.state in {
        DirectAcquisitionState.COMPLETED,
        DirectAcquisitionState.CANCELLED,
        DirectAcquisitionState.FAILED,
    }:
        raise ValueError("Direct acquisition attempt is terminal.")


async def _enter_resolving(
    session: AsyncSession,
    attempt: DirectAcquisitionAttempt,
    artifact: DirectArtifactAttempt,
    progress: _ProgressWriter,
) -> None:
    if attempt.state is DirectAcquisitionState.PAUSED:
        transition_acquisition(attempt, DirectAcquisitionState.DOWNLOADING)
        transition_artifact(artifact, DirectArtifactState.TRANSFERRING)
    elif attempt.state is DirectAcquisitionState.DOWNLOADING:
        if artifact.state is not DirectArtifactState.TRANSFERRING:
            raise _missing_quarantine_error()
    elif attempt.state is DirectAcquisitionState.RESOLVING:
        if artifact.state is not DirectArtifactState.RESOLVING:
            raise _missing_quarantine_error()
    else:
        transition_acquisition(attempt, DirectAcquisitionState.RESOLVING)
        transition_artifact(artifact, DirectArtifactState.RESOLVING)
    attempt.next_retry_at = None
    artifact.next_retry_at = None
    attempt.failure_class = None
    attempt.failure_code = None
    attempt.error_message = None
    artifact.failure_class = None
    artifact.failure_code = None
    artifact.error_message = None
    await progress.write(stage="resolving", force=True)


async def _enter_downloading(
    session: AsyncSession,
    attempt: DirectAcquisitionAttempt,
    artifact: DirectArtifactAttempt,
    workspace: DirectQuarantineWorkspace,
    progress: _ProgressWriter,
) -> None:
    if attempt.state is DirectAcquisitionState.RESOLVING:
        transition_acquisition(attempt, DirectAcquisitionState.DOWNLOADING)
    if artifact.state is DirectArtifactState.RESOLVING:
        transition_artifact(artifact, DirectArtifactState.TRANSFERRING)
    artifact.quarantine_path = str(workspace.partial_path)
    await progress.write(stage="downloading", force=True)


async def _load_host_credentials(
    session: AsyncSession,
    host_kind: DirectArtifactHostKind,
) -> tuple[dict[str, str], int | None]:
    result = await session.execute(
        select(DirectHostConfig).where(DirectHostConfig.host_kind == host_kind)
    )
    config = result.scalar_one_or_none()
    if config is None:
        await session.commit()
        return {}, None
    if not config.enabled:
        raise ArtifactHostResolutionError(
            code="artifact_host_disabled",
            message="The selected artifact host is disabled.",
            failure_class=DirectArtifactFailureClass.USER_ACTION,
            retryable=False,
            intervention=True,
        )
    credentials = load_host_credential_material(config).credentials
    config_id = config.id if credentials else None
    await session.commit()
    return credentials, config_id


async def _record_host_account_result(
    session: AsyncSession,
    *,
    host_config_id: int | None,
    checked_at: datetime,
    error: ArtifactHostResolutionError | None,
) -> None:
    if host_config_id is None:
        return
    config = await session.get(DirectHostConfig, host_config_id)
    if config is None:
        return
    config.last_tested_at = checked_at
    config.last_error_code = error.code if error is not None else None
    config.quota_remaining = None
    config.quota_reset_at = None
    if error is None:
        config.account_state = DirectHostAccountState.HEALTHY
    elif error.failure_class is DirectArtifactFailureClass.ARTIFACT_HOST_AUTH_REQUIRED:
        config.account_state = DirectHostAccountState.AUTHENTICATION_REQUIRED
    elif error.failure_class is DirectArtifactFailureClass.HOST_QUOTA:
        config.account_state = DirectHostAccountState.QUOTA_LIMITED
        config.quota_remaining = 0
    elif error.failure_class is DirectArtifactFailureClass.TRANSIENT_HOST:
        config.account_state = DirectHostAccountState.UNAVAILABLE
    else:
        config.account_state = DirectHostAccountState.UNKNOWN


def _validate_source_request(
    request: HostResolutionRequest,
    artifact: DirectArtifactAttempt,
) -> None:
    if (
        request.artifact_identity != artifact.artifact_identity
        or request.host_kind is not artifact.host_kind
    ):
        raise ArtifactHostResolutionError(
            code="artifact_identity_mismatch",
            message="The refreshed artifact no longer matches the selected plan.",
            failure_class=DirectArtifactFailureClass.CANDIDATE_INVALID,
            retryable=False,
            intervention=True,
        )


def _recover_http_checkpoint(
    workspace: DirectQuarantineWorkspace,
    artifact: DirectArtifactAttempt,
) -> HttpTransferCheckpoint | None:
    partial = workspace.partial_path
    if not partial.exists():
        artifact.bytes_transferred = 0
        return None
    if partial.is_symlink() or not partial.is_file():
        raise _missing_quarantine_error()
    actual_size = partial.stat().st_size
    artifact.bytes_transferred = actual_size
    if actual_size <= 0 or not (artifact.etag or artifact.last_modified_at):
        remove_quarantine_file(partial)
        artifact.bytes_transferred = 0
        return None
    return HttpTransferCheckpoint(
        bytes_transferred=actual_size,
        expected_size=artifact.expected_size,
        etag=artifact.etag,
        last_modified=_format_last_modified(artifact.last_modified_at),
    )


def _recover_final_path(
    workspace: DirectQuarantineWorkspace,
    artifact: DirectArtifactAttempt,
) -> Path | None:
    raw_path = artifact.quarantine_path
    if not raw_path:
        return None
    candidate = Path(raw_path)
    if candidate == workspace.partial_path:
        return None
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(workspace.directory)
    except (OSError, ValueError) as exc:
        raise _missing_quarantine_error() from exc
    if resolved.is_symlink() or not resolved.is_file():
        raise _missing_quarantine_error()
    return resolved


def _parse_last_modified(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _format_last_modified(value: datetime | None) -> str | None:
    if value is None:
        return None
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return format_datetime(aware.astimezone(UTC), usegmt=True)


def _missing_quarantine_error() -> DirectArtifactValidationError:
    return DirectArtifactValidationError(
        code="artifact_quarantine_missing",
        message="The quarantined artifact is missing or no longer safe to use.",
        retryable=False,
        intervention=True,
    )


def _result(
    attempt: DirectAcquisitionAttempt,
    artifact: DirectArtifactAttempt,
) -> DirectExecutionResult:
    return DirectExecutionResult(
        acquisition_id=attempt.id,
        artifact_id=artifact.id,
        state=DirectAcquisitionState(attempt.state),
        artifact_state=DirectArtifactState(artifact.state),
        library_file_id=attempt.library_file_id,
    )
