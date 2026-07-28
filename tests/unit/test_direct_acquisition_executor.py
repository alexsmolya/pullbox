"""Durable execution tests for direct artifact acquisition."""

from __future__ import annotations

import asyncio
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from pullbox.models import Base
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
from pullbox.models.issue import Issue, IssueStatus, IssueType
from pullbox.models.library import FileFormat, LibraryFile, LibraryRoot, MatchConfidence
from pullbox.models.series import Series, SeriesStatus, SeriesType
from pullbox.providers.artifact_hosts.contract import (
    ArtifactHostResolutionError,
    ArtifactTransferProtocol,
    HostResolutionRequest,
    ResolvedTransfer,
)
from pullbox.providers.artifact_hosts.mega import (
    MegaBridgePausedError,
    MegaBridgeTransferResult,
)
from pullbox.providers.artifact_hosts.transport_contract import (
    ArtifactTransferCancelledError,
    ArtifactTransferError,
    ArtifactTransferPausedError,
    ArtifactTransferResult,
    HttpTransferCheckpoint,
    TransferProgressSnapshot,
)
from pullbox.services.direct_acquisition_executor import DirectAcquisitionExecutor
from pullbox.services.direct_artifact_post_processing import DirectPostProcessingResult
from pullbox.services.direct_artifact_quarantine import DirectArtifactQuarantine
from pullbox.services.direct_configuration_service import update_host_credentials

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


@pytest.fixture
async def session(tmp_path: Path) -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db_session:
        series = Series(
            comicvine_id=995_001,
            title="Direct Executor",
            sort_title="Direct Executor",
            year_start=2026,
            status=SeriesStatus.CONTINUING,
            series_type=SeriesType.STANDARD,
            monitored=True,
            issue_count=1,
        )
        db_session.add(series)
        await db_session.flush()
        db_session.add(
            Issue(
                id=1,
                series_id=series.id,
                comicvine_id=996_001,
                issue_number=1,
                status=IssueStatus.WANTED,
                issue_type=IssueType.ISSUE,
            )
        )
        library_root = LibraryRoot(
            id=1,
            name="Test Library",
            path=str(tmp_path / "library"),
            enabled=True,
        )
        db_session.add(library_root)
        db_session.add(
            LibraryFile(
                id=77,
                file_path="/library/Issue 1.cbz",
                file_name="Issue 1.cbz",
                file_size=100,
                file_format=FileFormat.CBZ,
                file_modified_at=NOW,
                match_confidence=MatchConfidence.HIGH,
                issue_id=1,
                library_root_id=1,
            )
        )
        await db_session.commit()
        yield db_session
    await engine.dispose()


def _attempt() -> DirectAcquisitionAttempt:
    attempt = DirectAcquisitionAttempt(
        request_key="direct-executor:1",
        issue_id=1,
        provider_identity="community.test",
        provider_candidate_id="candidate-1",
        state=DirectAcquisitionState.QUEUED,
        plan_revision=1,
        plan_snapshot={"schema_version": 1},
        progress_revision=0,
        progress_snapshot={},
    )
    attempt.artifact_attempts = [
        DirectArtifactAttempt(
            sequence_no=0,
            artifact_identity="artifact-1",
            route_kind=DirectArtifactRouteKind.DIRECT,
            host_kind=DirectArtifactHostKind.GENERIC_HTTPS,
            state=DirectArtifactState.PLANNED,
            is_selected=True,
            etag='"stable"',
        )
    ]
    return attempt


def _source_request() -> HostResolutionRequest:
    return HostResolutionRequest(
        artifact_identity="artifact-1",
        host_kind=DirectArtifactHostKind.GENERIC_HTTPS,
        share_url=None,
        final_url="https://files.example/signed-secret.cbz",
        expected_size=None,
        etag='"stable"',
    )


@dataclass
class _FakeResolver:
    resolved: ResolvedTransfer
    calls: int = 0

    async def resolve(
        self,
        request: HostResolutionRequest,
        *,
        credentials: Any,
    ) -> ResolvedTransfer:
        self.calls += 1
        assert request.artifact_identity == "artifact-1"
        assert credentials == {}
        return self.resolved


@dataclass
class _AccountResolver:
    resolved: ResolvedTransfer | None = None
    error: ArtifactHostResolutionError | None = None

    async def resolve(
        self,
        request: HostResolutionRequest,
        *,
        credentials: Any,
    ) -> ResolvedTransfer:
        assert request.host_kind is DirectArtifactHostKind.PIXELDRAIN
        assert credentials == {"api_key": "configured-pixeldrain-key"}
        if self.error is not None:
            raise self.error
        assert self.resolved is not None
        return self.resolved


class _SuccessfulTransport:
    def __init__(self) -> None:
        self.checkpoint: HttpTransferCheckpoint | None = None

    async def transfer(self, **kwargs: Any) -> ArtifactTransferResult:
        destination = kwargs["destination"]
        self.checkpoint = kwargs["checkpoint"]
        with zipfile.ZipFile(destination, "w") as archive:
            archive.writestr("001.jpg", b"synthetic fixture")
        size = destination.stat().st_size
        await kwargs["progress_callback"](
            TransferProgressSnapshot(
                bytes_transferred=size,
                total_bytes=size,
                percent=100,
                bytes_per_second=1024.0,
                eta_seconds=0.0,
            )
        )
        return ArtifactTransferResult(
            path=destination,
            bytes_transferred=size,
            expected_size=size,
            etag='"stable"',
            last_modified=None,
            filename_hint="issue.cbz",
            resumed=self.checkpoint is not None,
        )


class _FailingTransport:
    def __init__(self, error: BaseException, *, write_partial: bool = False) -> None:
        self.error = error
        self.write_partial = write_partial

    async def transfer(self, **kwargs: Any) -> ArtifactTransferResult:
        if self.write_partial:
            kwargs["destination"].write_bytes(b"partial")
        raise self.error


class _CancelledTaskTransport:
    async def transfer(self, **kwargs: Any) -> ArtifactTransferResult:
        destination = kwargs["destination"]
        destination.write_bytes(b"restartable-partial")
        await kwargs["progress_callback"](
            TransferProgressSnapshot(
                bytes_transferred=destination.stat().st_size,
                total_bytes=100,
                percent=19,
                bytes_per_second=100.0,
                eta_seconds=1.0,
            )
        )
        raise asyncio.CancelledError


class _PausedMegaRunner:
    async def transfer(self, **kwargs: Any) -> MegaBridgeTransferResult:
        destination = kwargs["destination"]
        destination.write_bytes(b"non-resumable-mega-partial")
        await kwargs["progress_callback"](destination.stat().st_size, 100)
        raise MegaBridgePausedError


def _executor(
    tmp_path: Path,
    *,
    transport: Any,
    post_processor: Any,
) -> DirectAcquisitionExecutor:
    resolved = ResolvedTransfer(
        host_kind=DirectArtifactHostKind.GENERIC_HTTPS,
        url="https://files.example/signed-secret.cbz",
        etag='"stable"',
        allowed_domains=("files.example",),
        transport_protocol=ArtifactTransferProtocol.HTTPS,
    )
    return DirectAcquisitionExecutor(
        host_resolver=_FakeResolver(resolved),
        http_transport=transport,
        mega_runner=object(),
        quarantine=DirectArtifactQuarantine(tmp_path / "quarantine"),
        post_processor=post_processor,
        now=lambda: NOW,
    )


async def _successful_post_processor(*_args: Any, **_kwargs: Any) -> DirectPostProcessingResult:
    return DirectPostProcessingResult(
        library_file_id=77,
        final_path=Path("/library/Issue 1.cbz"),
    )


@pytest.mark.asyncio
async def test_executor_completes_with_durable_redacted_progress(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    attempt = _attempt()
    session.add(attempt)
    await session.commit()
    artifact = attempt.artifact_attempts[0]
    source_calls = 0

    async def source_factory() -> HostResolutionRequest:
        nonlocal source_calls
        source_calls += 1
        return _source_request()

    result = await _executor(
        tmp_path,
        transport=_SuccessfulTransport(),
        post_processor=_successful_post_processor,
    ).execute(
        session,
        acquisition_id=attempt.id,
        artifact_id=artifact.id,
        source_factory=source_factory,
    )

    assert result.state is DirectAcquisitionState.COMPLETED
    assert attempt.state is DirectAcquisitionState.COMPLETED
    assert artifact.state is DirectArtifactState.COMPLETED
    assert attempt.library_file_id == 77
    assert artifact.quarantine_path is None
    assert attempt.progress_snapshot["stage"] == "completed"
    assert "signed-secret" not in repr(attempt.progress_snapshot)
    assert source_calls == 1
    assert not (tmp_path / "quarantine" / f"attempt-{attempt.id}").exists()


@pytest.mark.asyncio
async def test_executor_pauses_http_with_resume_checkpoint(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    attempt = _attempt()
    session.add(attempt)
    await session.commit()
    artifact = attempt.artifact_attempts[0]
    checkpoint = HttpTransferCheckpoint(
        bytes_transferred=7,
        expected_size=100,
        etag='"stable"',
        last_modified=None,
    )
    transport = _FailingTransport(ArtifactTransferPausedError(checkpoint), write_partial=True)

    result = await _executor(
        tmp_path,
        transport=transport,
        post_processor=_successful_post_processor,
    ).execute(
        session,
        acquisition_id=attempt.id,
        artifact_id=artifact.id,
        source_factory=_async_source,
    )

    assert result.state is DirectAcquisitionState.PAUSED
    assert artifact.state is DirectArtifactState.PAUSED
    assert artifact.bytes_transferred == 7
    assert artifact.quarantine_path is not None
    assert Path(artifact.quarantine_path).exists()


@pytest.mark.asyncio
async def test_executor_cancellation_is_terminal_and_cleans_quarantine(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    attempt = _attempt()
    session.add(attempt)
    await session.commit()
    artifact = attempt.artifact_attempts[0]

    result = await _executor(
        tmp_path,
        transport=_FailingTransport(ArtifactTransferCancelledError(), write_partial=True),
        post_processor=_successful_post_processor,
    ).execute(
        session,
        acquisition_id=attempt.id,
        artifact_id=artifact.id,
        source_factory=_async_source,
    )

    assert result.state is DirectAcquisitionState.CANCELLED
    assert artifact.state is DirectArtifactState.CANCELLED
    assert artifact.quarantine_path is None
    assert not (tmp_path / "quarantine" / f"attempt-{attempt.id}").exists()


@pytest.mark.asyncio
async def test_executor_schedules_retry_without_losing_safe_partial(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    attempt = _attempt()
    session.add(attempt)
    await session.commit()
    artifact = attempt.artifact_attempts[0]
    error = ArtifactTransferError(
        code="artifact_host_unavailable",
        message="The artifact host is temporarily unavailable.",
        failure_class=DirectArtifactFailureClass.TRANSIENT_HOST,
        retryable=True,
        intervention=False,
    )

    result = await _executor(
        tmp_path,
        transport=_FailingTransport(error, write_partial=True),
        post_processor=_successful_post_processor,
    ).execute(
        session,
        acquisition_id=attempt.id,
        artifact_id=artifact.id,
        source_factory=_async_source,
    )

    assert result.state is DirectAcquisitionState.RETRY_PENDING
    assert artifact.state is DirectArtifactState.RETRY_PENDING
    assert artifact.retry_count == 1
    assert attempt.retry_count == 1
    assert artifact.next_retry_at is not None
    assert Path(artifact.quarantine_path or "").exists()


@pytest.mark.asyncio
async def test_executor_recovers_inflight_transfer_from_persisted_checkpoint(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    attempt = _attempt()
    attempt.state = DirectAcquisitionState.DOWNLOADING
    artifact = attempt.artifact_attempts[0]
    artifact.state = DirectArtifactState.TRANSFERRING
    session.add(attempt)
    await session.commit()
    quarantine = DirectArtifactQuarantine(tmp_path / "quarantine")
    workspace = quarantine.prepare(acquisition_id=attempt.id, artifact_id=artifact.id)
    workspace.partial_path.write_bytes(b"partial")
    artifact.quarantine_path = str(workspace.partial_path)
    artifact.bytes_transferred = workspace.partial_path.stat().st_size
    await session.commit()
    transport = _SuccessfulTransport()
    resolved = ResolvedTransfer(
        host_kind=DirectArtifactHostKind.GENERIC_HTTPS,
        url="https://files.example/refreshed.cbz",
        etag='"stable"',
        allowed_domains=("files.example",),
    )
    executor = DirectAcquisitionExecutor(
        host_resolver=_FakeResolver(resolved),
        http_transport=transport,
        mega_runner=object(),
        quarantine=quarantine,
        post_processor=_successful_post_processor,
        now=lambda: NOW,
    )

    result = await executor.execute(
        session,
        acquisition_id=attempt.id,
        artifact_id=artifact.id,
        source_factory=_async_source,
    )

    assert result.state is DirectAcquisitionState.COMPLETED
    assert transport.checkpoint is not None
    assert transport.checkpoint.bytes_transferred == len(b"partial")
    assert transport.checkpoint.etag == '"stable"'


@pytest.mark.asyncio
async def test_credentialed_resolution_records_healthy_account_state(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    attempt = _attempt()
    artifact = attempt.artifact_attempts[0]
    artifact.host_kind = DirectArtifactHostKind.PIXELDRAIN
    config = DirectHostConfig(
        host_kind=DirectArtifactHostKind.PIXELDRAIN,
        enabled=True,
    )
    update_host_credentials(config, {"api_key": "configured-pixeldrain-key"})
    session.add_all([attempt, config])
    await session.commit()
    resolved = ResolvedTransfer(
        host_kind=DirectArtifactHostKind.PIXELDRAIN,
        url="https://pixeldrain.com/api/file/fixture",
        etag='"stable"',
        allowed_domains=("pixeldrain.com",),
    )

    async def source() -> HostResolutionRequest:
        return HostResolutionRequest(
            artifact_identity="artifact-1",
            host_kind=DirectArtifactHostKind.PIXELDRAIN,
            share_url="https://pixeldrain.com/u/fixture",
            final_url=None,
        )

    executor = DirectAcquisitionExecutor(
        host_resolver=_AccountResolver(resolved=resolved),
        http_transport=_SuccessfulTransport(),
        mega_runner=object(),
        quarantine=DirectArtifactQuarantine(tmp_path / "quarantine"),
        post_processor=_successful_post_processor,
        now=lambda: NOW,
    )

    result = await executor.execute(
        session,
        acquisition_id=attempt.id,
        artifact_id=artifact.id,
        source_factory=source,
    )

    await session.refresh(config)
    assert result.state is DirectAcquisitionState.COMPLETED
    assert config.account_state is DirectHostAccountState.HEALTHY
    assert config.last_tested_at == NOW
    assert config.last_error_code is None


@pytest.mark.asyncio
async def test_credentialed_auth_failure_records_reauthentication_state(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    attempt = _attempt()
    artifact = attempt.artifact_attempts[0]
    artifact.host_kind = DirectArtifactHostKind.PIXELDRAIN
    config = DirectHostConfig(
        host_kind=DirectArtifactHostKind.PIXELDRAIN,
        enabled=True,
    )
    update_host_credentials(config, {"api_key": "configured-pixeldrain-key"})
    session.add_all([attempt, config])
    await session.commit()
    error = ArtifactHostResolutionError(
        code="artifact_host_auth_required",
        message="This artifact host requires account authentication.",
        failure_class=DirectArtifactFailureClass.ARTIFACT_HOST_AUTH_REQUIRED,
        retryable=False,
        intervention=True,
    )

    async def source() -> HostResolutionRequest:
        return HostResolutionRequest(
            artifact_identity="artifact-1",
            host_kind=DirectArtifactHostKind.PIXELDRAIN,
            share_url="https://pixeldrain.com/u/fixture",
            final_url=None,
        )

    executor = DirectAcquisitionExecutor(
        host_resolver=_AccountResolver(error=error),
        http_transport=object(),
        mega_runner=object(),
        quarantine=DirectArtifactQuarantine(tmp_path / "quarantine"),
        post_processor=_successful_post_processor,
        now=lambda: NOW,
    )

    result = await executor.execute(
        session,
        acquisition_id=attempt.id,
        artifact_id=artifact.id,
        source_factory=source,
    )

    await session.refresh(config)
    assert result.state is DirectAcquisitionState.INTERVENTION
    assert config.account_state is DirectHostAccountState.AUTHENTICATION_REQUIRED
    assert config.last_tested_at == NOW
    assert config.last_error_code == "artifact_host_auth_required"


@pytest.mark.asyncio
async def test_process_task_cancellation_preserves_restartable_inflight_state(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    attempt = _attempt()
    session.add(attempt)
    await session.commit()
    artifact = attempt.artifact_attempts[0]

    with pytest.raises(asyncio.CancelledError):
        await _executor(
            tmp_path,
            transport=_CancelledTaskTransport(),
            post_processor=_successful_post_processor,
        ).execute(
            session,
            acquisition_id=attempt.id,
            artifact_id=artifact.id,
            source_factory=_async_source,
        )

    await session.refresh(attempt)
    await session.refresh(artifact)
    assert attempt.state is DirectAcquisitionState.DOWNLOADING
    assert artifact.state is DirectArtifactState.TRANSFERRING
    assert artifact.bytes_transferred == len(b"restartable-partial")
    assert Path(artifact.quarantine_path or "").read_bytes() == b"restartable-partial"


@pytest.mark.asyncio
async def test_mega_pause_discards_partial_and_restarts_from_zero(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    attempt = _attempt()
    artifact = attempt.artifact_attempts[0]
    artifact.host_kind = DirectArtifactHostKind.MEGA
    session.add(attempt)
    await session.commit()

    async def mega_source() -> HostResolutionRequest:
        return HostResolutionRequest(
            artifact_identity="artifact-1",
            host_kind=DirectArtifactHostKind.MEGA,
            share_url="https://mega.nz/file/fixture#fixture-key",
            final_url=None,
            expected_size=100,
        )

    resolved = ResolvedTransfer(
        host_kind=DirectArtifactHostKind.MEGA,
        url="https://mega.nz/file/fixture#fixture-key",
        expected_size=100,
        allowed_domains=("mega.nz",),
        transport_protocol=ArtifactTransferProtocol.MEGA_BRIDGE,
    )
    executor = DirectAcquisitionExecutor(
        host_resolver=_FakeResolver(resolved),
        http_transport=object(),
        mega_runner=_PausedMegaRunner(),
        quarantine=DirectArtifactQuarantine(tmp_path / "quarantine"),
        post_processor=_successful_post_processor,
        now=lambda: NOW,
    )

    result = await executor.execute(
        session,
        acquisition_id=attempt.id,
        artifact_id=artifact.id,
        source_factory=mega_source,
    )

    assert result.state is DirectAcquisitionState.PAUSED
    assert artifact.state is DirectArtifactState.PAUSED
    assert artifact.bytes_transferred == 0
    assert artifact.etag is None
    assert not Path(artifact.quarantine_path or "").exists()


@pytest.mark.asyncio
async def test_post_processing_failure_keeps_valid_artifact_for_intervention(
    session: AsyncSession,
    tmp_path: Path,
) -> None:
    attempt = _attempt()
    session.add(attempt)
    await session.commit()
    artifact = attempt.artifact_attempts[0]

    async def fail_post_processing(*_args: Any, **_kwargs: Any) -> DirectPostProcessingResult:
        raise RuntimeError("synthetic post-processing failure")

    result = await _executor(
        tmp_path,
        transport=_SuccessfulTransport(),
        post_processor=fail_post_processing,
    ).execute(
        session,
        acquisition_id=attempt.id,
        artifact_id=artifact.id,
        source_factory=_async_source,
    )

    assert result.state is DirectAcquisitionState.INTERVENTION
    assert artifact.state is DirectArtifactState.INTERVENTION
    assert attempt.failure_class is DirectArtifactFailureClass.POST_PROCESS
    assert artifact.quarantine_path is not None
    assert Path(artifact.quarantine_path).exists()


async def _async_source() -> HostResolutionRequest:
    await asyncio.sleep(0)
    return _source_request()
