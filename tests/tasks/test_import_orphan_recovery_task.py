"""Unit tests for orphan recovery background progress state."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from pullbox.models.import_job import ImportSeriesStatus
from pullbox.schemas.import_job import OrphanRecoveryDecision, RecoverOrphanRequest
from pullbox.tasks import import_orphan_recovery_task as task


@pytest.fixture(autouse=True)
def clear_orphan_recovery_state() -> None:
    task._orphan_recovery_states.clear()
    task._background_tasks.clear()


def _request() -> RecoverOrphanRequest:
    return RecoverOrphanRequest(
        decisions=[
            OrphanRecoveryDecision(
                imported_file_id=1,
                action="assign",
                issue_cv_id=1001,
            ),
            OrphanRecoveryDecision(imported_file_id=2, action="skip"),
        ]
    )


@pytest.mark.asyncio
async def test_start_orphan_recovery_run_records_initial_state_and_reuses_running_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: list[object] = []

    class FakeTask:
        def add_done_callback(self, _callback: object) -> None:
            return None

    def fake_create_task(coro: object) -> FakeTask:
        close = getattr(coro, "close", None)
        if close is not None:
            close()
        created.append(coro)
        return FakeTask()

    monkeypatch.setattr(task.asyncio, "create_task", fake_create_task)

    initial = await task.start_orphan_recovery_run(7, _request())
    reused = await task.start_orphan_recovery_run(7, _request())

    assert initial is reused
    assert len(created) == 1
    assert initial.imported_series_id == 7
    assert initial.state == "running"
    assert initial.message == "Preparing recovery import..."
    assert initial.total_files == 1
    assert initial.skipped_count == 1
    assert task.get_orphan_recovery_progress_state(7) == initial


@pytest.mark.asyncio
async def test_run_orphan_recovery_updates_progress_and_final_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commits = 0
    rollbacks = 0

    class FakeSession:
        async def __aenter__(self) -> FakeSession:
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

        async def commit(self) -> None:
            nonlocal commits
            commits += 1

        async def rollback(self) -> None:
            nonlocal rollbacks
            rollbacks += 1

    class FakeService:
        async def _load_orphan_recovery_item(
            self,
            _session: object,
            imported_series_id: int,
        ) -> tuple[object, object]:
            assert imported_series_id == 7
            return (
                SimpleNamespace(
                    move_to_library=True,
                    convert_to_preferred_format=True,
                    update_embedded_comicinfo_from_match=False,
                ),
                SimpleNamespace(cv_title="Recovered Series", raw_series_name="Raw Series"),
            )

        async def recover_orphan(
            self,
            _session: object,
            _imported_series_id: int,
            _request: RecoverOrphanRequest,
            *,
            progress_callback: object,
        ) -> dict[str, object]:
            await progress_callback(
                imp_file=SimpleNamespace(
                    file_name="Recovered.cbr",
                    file_path="/imports/Recovered.cbr",
                ),
                file_index=1,
                total_files=1,
                stage="transferring",
                current=1,
                total=1,
                unit="bytes",
            )
            return {
                "status": ImportSeriesStatus.IMPORTED,
                "imported_count": 1,
                "skipped_count": 1,
                "failed_count": 0,
                "files_remaining": 0,
            }

    async def build_import_service(_session: object) -> FakeService:
        return FakeService()

    monkeypatch.setattr(task, "get_session_factory", lambda: lambda: FakeSession())
    monkeypatch.setattr("pullbox.composition.services.build_import_service", build_import_service)

    await task._run_orphan_recovery(7, _request().model_dump(mode="python"))

    progress = task.get_orphan_recovery_progress_state(7)
    assert progress is not None
    assert progress.state == "completed"
    assert progress.message == "Recovery complete."
    assert progress.imported_count == 1
    assert progress.skipped_count == 1
    assert progress.failed_count == 0
    assert progress.files_remaining == 0
    assert commits == 1
    assert rollbacks == 0


@pytest.mark.asyncio
async def test_run_orphan_recovery_rolls_back_and_marks_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rollbacks = 0

    class FakeSession:
        async def __aenter__(self) -> FakeSession:
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

        async def rollback(self) -> None:
            nonlocal rollbacks
            rollbacks += 1

    async def build_import_service(_session: object) -> object:
        raise RuntimeError("service unavailable")

    monkeypatch.setattr(task, "get_session_factory", lambda: lambda: FakeSession())
    monkeypatch.setattr("pullbox.composition.services.build_import_service", build_import_service)

    await task._run_orphan_recovery(9, _request().model_dump(mode="python"))

    progress = task.get_orphan_recovery_progress_state(9)
    assert progress is not None
    assert progress.state == "failed"
    assert progress.message == "Recovery failed."
    assert progress.error_message == "service unavailable"
    assert rollbacks == 1
