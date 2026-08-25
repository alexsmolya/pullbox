"""Batched authoritative AirDC++ queue-to-history convergence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import PurePath
from typing import TYPE_CHECKING, Protocol

from sqlalchemy import or_, select
from sqlalchemy.orm import joinedload

from pullbox.models.airdcpp import AirDcppAcquisition
from pullbox.models.download import DownloadHistory, DownloadState

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from pullbox.providers.airdcpp.contracts import AirDcppQueueBundle, AirDcppQueueFile
    from pullbox.services.airdcpp_search_cooldown import AirDcppCooldownReservation

_PAGE_SIZE = 100
_MAX_PAGES = 10
_MAX_PRE_ID_LOOKUPS = 10
_PROGRESS_WRITE_INTERVAL = timedelta(seconds=5)
_TERMINAL_STATES = frozenset(
    {
        DownloadState.COMPLETED,
        DownloadState.IMPORTED,
        DownloadState.FAILED,
    }
)


class AirDcppReconciliationApi(Protocol):
    async def get_queue_bundles(
        self,
        *,
        start: int,
        count: int,
    ) -> list[AirDcppQueueBundle]: ...

    async def get_queue_files_by_tth(self, tth: str) -> list[AirDcppQueueFile]: ...

    async def search_queue_bundle(self, bundle_id: int) -> None: ...


class AirDcppReconciliationCooldown(Protocol):
    async def reserve(self, config_id: int) -> AirDcppCooldownReservation: ...


@dataclass(frozen=True, slots=True)
class AirDcppReconciliationResult:
    processed: int
    changed: int
    missing: int
    completed: int
    partial: bool
    pages: int


@dataclass(frozen=True, slots=True)
class _ActiveSnapshot:
    acquisition_id: int
    bundle_id: int | None
    tth: str
    size_bytes: int
    target_name: str


class AirDcppReconciler:
    """Reconcile one exact client without retaining a DB transaction over I/O."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | Callable[[], AsyncSession],
        *,
        cooldown: AirDcppReconciliationCooldown | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._cooldown = cooldown

    async def reconcile_client(
        self,
        client_config_id: int,
        api_client: AirDcppReconciliationApi,
    ) -> AirDcppReconciliationResult:
        await self._request_due_alternate(client_config_id, api_client)
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(AirDcppAcquisition)
                    .join(DownloadHistory)
                    .where(
                        AirDcppAcquisition.client_config_id == client_config_id,
                        DownloadHistory.imported_at.is_(None),
                        DownloadHistory.state.not_in(_TERMINAL_STATES),
                    )
                    .order_by(AirDcppAcquisition.id)
                    .limit(_PAGE_SIZE)
                )
            ).scalars()
            snapshots = tuple(
                _ActiveSnapshot(
                    row.id,
                    row.bundle_id,
                    row.tth,
                    row.size_bytes,
                    row.original_name,
                )
                for row in rows
            )
            await session.commit()
        if not snapshots:
            return AirDcppReconciliationResult(0, 0, 0, 0, False, 0)

        adopted: dict[int, AirDcppQueueFile] = {}
        pre_id = [snapshot for snapshot in snapshots if snapshot.bundle_id is None]
        for snapshot in pre_id[:_MAX_PRE_ID_LOOKUPS]:
            files = await api_client.get_queue_files_by_tth(snapshot.tth)
            exact = [
                item
                for item in files
                if item.size == snapshot.size_bytes
                and PurePath(item.target.get_secret_value().replace("\\", "/")).name
                == snapshot.target_name
            ]
            bundle_ids = {item.bundle_id for item in exact}
            if len(bundle_ids) == 1:
                adopted[snapshot.acquisition_id] = exact[0]

        bundles: dict[int, AirDcppQueueBundle] = {}
        pages = 0
        complete_snapshot = False
        for page_index in range(_MAX_PAGES):
            page = await api_client.get_queue_bundles(
                start=page_index * _PAGE_SIZE,
                count=_PAGE_SIZE,
            )
            pages += 1
            for page_bundle in page:
                bundles[page_bundle.id] = page_bundle
            if len(page) < _PAGE_SIZE:
                complete_snapshot = True
                break

        changed = 0
        missing = 0
        completed = 0
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            result = await session.execute(
                select(AirDcppAcquisition)
                .options(joinedload(AirDcppAcquisition.download_history))
                .where(AirDcppAcquisition.id.in_(snapshot.acquisition_id for snapshot in snapshots))
            )
            acquisitions = {item.id: item for item in result.unique().scalars()}
            for snapshot in snapshots:
                acquisition = acquisitions.get(snapshot.acquisition_id)
                if acquisition is None:
                    continue
                bundle = bundles.get(snapshot.bundle_id) if snapshot.bundle_id else None
                if bundle is not None:
                    was_completed = (
                        DownloadState(acquisition.download_history.state) is DownloadState.COMPLETED
                    )
                    changed += int(apply_airdcpp_bundle(acquisition, bundle, at=now))
                    completed += int(
                        not was_completed
                        and acquisition.download_history.state is DownloadState.COMPLETED
                    )
                elif snapshot.acquisition_id in adopted:
                    changed += int(
                        _apply_adopted_file(
                            acquisition,
                            adopted[snapshot.acquisition_id],
                            at=now,
                        )
                    )
                elif snapshot.bundle_id is not None and complete_snapshot:
                    missing += 1
                    changed += int(_apply_missing_bundle(acquisition, at=now))
            await session.commit()

        return AirDcppReconciliationResult(
            processed=len(snapshots),
            changed=changed,
            missing=missing,
            completed=completed,
            partial=not complete_snapshot,
            pages=pages,
        )

    async def _request_due_alternate(
        self,
        client_config_id: int,
        api_client: AirDcppReconciliationApi,
    ) -> None:
        if self._cooldown is None:
            return
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            pending = (
                await session.execute(
                    select(AirDcppAcquisition)
                    .where(
                        AirDcppAcquisition.client_config_id == client_config_id,
                        AirDcppAcquisition.client_state == "source_search_pending",
                        AirDcppAcquisition.bundle_id.is_not(None),
                        or_(
                            AirDcppAcquisition.next_retry_at.is_(None),
                            AirDcppAcquisition.next_retry_at <= now,
                        ),
                    )
                    .order_by(AirDcppAcquisition.id)
                    .limit(1)
                )
            ).scalar_one_or_none()
            pending_id = pending.id if pending is not None else None
            bundle_id = pending.bundle_id if pending is not None else None
            await session.commit()
        if pending_id is None or bundle_id is None:
            return

        reservation = await self._cooldown.reserve(client_config_id)
        if not reservation.granted:
            async with self._session_factory() as session:
                current = await session.get(AirDcppAcquisition, pending_id)
                if current is not None and current.client_state == "source_search_pending":
                    current.next_retry_at = reservation.next_allowed_at
                    await session.commit()
            return

        try:
            await api_client.search_queue_bundle(bundle_id)
        except Exception:
            async with self._session_factory() as session:
                current = await session.get(AirDcppAcquisition, pending_id)
                if current is not None and current.client_state == "source_search_pending":
                    current.reconciliation_error = "alternate_search_failed"
                    await session.commit()
            return
        async with self._session_factory() as session:
            current = await session.get(AirDcppAcquisition, pending_id)
            if current is not None:
                current.client_state = "source_search_requested"
                current.next_retry_at = None
                current.last_event_at = now
                current.reconciliation_error = None
                await session.commit()


def apply_airdcpp_bundle(
    acquisition: AirDcppAcquisition,
    bundle: AirDcppQueueBundle,
    *,
    at: datetime,
) -> bool:
    """Apply one REST or event observation with monotonic terminal semantics."""
    history = acquisition.download_history
    current = DownloadState(history.state)
    next_state = current
    next_error = history.error_message
    if history.imported_at is None and current not in _TERMINAL_STATES:
        next_state = _download_state(bundle)
        next_error = _failure_summary(bundle) if next_state is DownloadState.FAILED else None
    remote_target = bundle.target.get_secret_value()
    observation_changed = (
        current is not next_state
        or acquisition.client_state != bundle.status.id
        or acquisition.remote_target != remote_target
        or history.error_message != next_error
    )
    last_reconciled_at = acquisition.last_reconciled_at
    progress_due = last_reconciled_at is None or at - last_reconciled_at >= _PROGRESS_WRITE_INTERVAL
    if not observation_changed and not progress_due:
        return False

    acquisition.client_state = bundle.status.id
    acquisition.remote_target = remote_target
    route_snapshot = dict(acquisition.route_snapshot or {})
    route_snapshot["queue"] = {
        "version": 1,
        "downloaded_bytes": bundle.downloaded_bytes,
        "size_bytes": bundle.size,
        "speed_bytes": bundle.speed,
        "eta_seconds": bundle.seconds_left,
        "status_id": bundle.status.id,
        "sources_online": bundle.sources.online,
        "sources_total": bundle.sources.total,
    }
    acquisition.route_snapshot = route_snapshot
    acquisition.last_reconciled_at = at
    acquisition.reconciliation_error = None
    history.file_size = bundle.size

    if history.imported_at is None and current not in _TERMINAL_STATES:
        history.state = next_state
        if next_state is DownloadState.COMPLETED:
            history.completed_at = history.completed_at or at
            history.downloaded_path = remote_target
        history.error_message = next_error
    return True


def _download_state(bundle: AirDcppQueueBundle) -> DownloadState:
    status = bundle.status
    if status.completed or status.id in {"completed", "shared"}:
        return DownloadState.COMPLETED
    if status.failed or status.id in {"download_error", "completion_validation_error"}:
        return DownloadState.FAILED
    if status.downloaded or status.id in {
        "downloaded",
        "completion_validation_running",
        "recheck",
    }:
        return DownloadState.FINALIZING
    if bundle.priority.id == -1:
        return DownloadState.PAUSED
    if bundle.downloaded_bytes > 0:
        return DownloadState.DOWNLOADING
    return DownloadState.SENT


def _failure_summary(bundle: AirDcppQueueBundle) -> str:
    if bundle.status.id == "completion_validation_error":
        return "AirDC++ completion validation failed."
    return "AirDC++ reported a fatal download error."


def _apply_missing_bundle(acquisition: AirDcppAcquisition, *, at: datetime) -> bool:
    history = acquisition.download_history
    acquisition.last_reconciled_at = at
    if history.imported_at is not None or history.state in {
        DownloadState.IMPORTED,
        DownloadState.FAILED,
    }:
        return False
    acquisition.client_state = "missing"
    acquisition.reconciliation_error = "external_bundle_missing"
    history.state = DownloadState.FAILED
    history.completed_at = at
    history.error_message = "The AirDC++ queue item was removed outside Pullbox."
    return True


def _apply_adopted_file(
    acquisition: AirDcppAcquisition,
    queue_file: AirDcppQueueFile,
    *,
    at: datetime,
) -> bool:
    """Adopt only an exact TTH/size/target match after a pre-ID restart."""
    history = acquisition.download_history
    acquisition.bundle_id = queue_file.bundle_id
    acquisition.client_state = queue_file.status.id
    acquisition.remote_target = queue_file.target.get_secret_value()
    acquisition.last_reconciled_at = at
    acquisition.reconciliation_error = None
    history.external_id = f"airdcpp:{acquisition.client_config_id}:bundle:{queue_file.bundle_id}"
    if history.imported_at is None and history.state not in _TERMINAL_STATES:
        history.state = DownloadState.SENT
        history.next_retry_at = None
        history.error_message = None
    return True
