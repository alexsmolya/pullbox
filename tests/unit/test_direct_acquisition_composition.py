"""Composition contract for the native direct-acquisition runtime."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from pullbox.models.direct_acquisition import DirectArtifactHostKind
from pullbox.tasks.direct_acquisition_task import DirectAcquisitionRunner


@pytest.mark.asyncio
async def test_runtime_forwards_cooperative_and_idle_cancellation() -> None:
    """The composition wrapper must preserve the executor cancellation contract."""
    from pullbox.composition.services import DirectAcquisitionRuntime

    executor = AsyncMock()
    executor.cancel.return_value = True
    runtime = DirectAcquisitionRuntime(
        executor=executor,
        http_client=AsyncMock(),
        host_kinds=(),
    )
    cancel_event = asyncio.Event()

    async def source_factory() -> object:
        return object()

    await runtime.execute(
        AsyncMock(),
        acquisition_id=11,
        artifact_id=12,
        source_factory=source_factory,  # type: ignore[arg-type]
        cancel_event=cancel_event,
    )
    cancelled = await runtime.cancel(
        AsyncMock(),
        acquisition_id=11,
        artifact_id=12,
    )

    assert cancelled is True
    assert executor.execute.await_args.kwargs["cancel_event"] is cancel_event
    executor.cancel.assert_awaited_once()


@pytest.mark.asyncio
async def test_composition_registers_every_closed_host_and_closes_http_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from pullbox.composition import services

    monkeypatch.setattr(
        services,
        "get_settings",
        lambda: SimpleNamespace(data_dir=tmp_path),
    )

    runtime = services.build_direct_acquisition_runtime()

    assert set(runtime.host_kinds) == set(DirectArtifactHostKind)
    datanodes = runtime._executor._host_resolver._adapters[DirectArtifactHostKind.DATANODES]
    assert datanodes._login_solver is services._solve_datanodes_login
    runner = DirectAcquisitionRunner(
        SimpleNamespace(),  # type: ignore[arg-type]
        executor=runtime,
    )
    assert runner is not None
    await runtime.aclose()
    assert runtime.closed is True
