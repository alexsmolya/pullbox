"""Opt-in harmless live smokes for native artifact-host adapters.

Every configured URL must point to the same operator-owned fixture described by
``FIXTURE_SHA256``. URLs, sessions, and API keys are supplied only through the
process environment and are never rendered by this module.
"""

from __future__ import annotations

import hashlib
import os
import shlex
from typing import TYPE_CHECKING

import httpx
import pytest

from pullbox.models.direct_acquisition import (
    DirectArtifactFailureClass,
    DirectArtifactHostKind,
)
from pullbox.providers.artifact_hosts.contract import (
    ArtifactHostResolutionError,
    HostResolutionRequest,
)
from pullbox.providers.artifact_hosts.datanodes import DataNodesAdapter
from pullbox.providers.artifact_hosts.mediafire import MediaFireAdapter
from pullbox.providers.artifact_hosts.mega import MegaArtifactHostAdapter, MegaBridgeRunner
from pullbox.providers.artifact_hosts.pixeldrain import PixelDrainAdapter
from pullbox.providers.artifact_hosts.rootz import RootzAdapter
from pullbox.providers.artifact_hosts.terabox import TeraBoxAdapter
from pullbox.providers.artifact_hosts.transport import HttpArtifactTransport

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path

    from pullbox.providers.artifact_hosts.contract import ArtifactHostAdapter, ResolvedTransfer
    from pullbox.providers.artifact_hosts.transport_contract import TransferProgressSnapshot

    AdapterFactory = Callable[[httpx.AsyncClient], ArtifactHostAdapter]

FIXTURE_SIZE = 30_893
FIXTURE_SHA256 = "9d9097dde17474676b1d9b65fefab0ca02e2bcd6eabfb6d6cbec52e331930b10"


def _configured(*names: str) -> bool:
    return all(os.environ.get(name) for name in names)


def _request(host_kind: DirectArtifactHostKind, url_env: str) -> HostResolutionRequest:
    return HostResolutionRequest(
        artifact_identity=f"live-{host_kind.value}",
        host_kind=host_kind,
        share_url=os.environ[url_env],
        final_url=None,
        expected_size=FIXTURE_SIZE,
    )


async def _exercise_http_host(
    tmp_path: Path,
    *,
    adapter_type: AdapterFactory,
    host_kind: DirectArtifactHostKind,
    url_env: str,
    credentials: Mapping[str, str],
) -> None:
    request = _request(host_kind, url_env)
    timeout = httpx.Timeout(connect=30, read=120, write=30, pool=30)
    async with httpx.AsyncClient(timeout=timeout) as client:
        adapter = adapter_type(client)
        resolved = await adapter.resolve(request, credentials=credentials)
        quarantine_root = tmp_path / host_kind.value
        quarantine_root.mkdir()
        destination = quarantine_root / "fixture.partial"
        progress: list[int | None] = []

        async def record(snapshot: TransferProgressSnapshot) -> None:
            progress.append(snapshot.percent)

        async def refresh() -> ResolvedTransfer:
            return await adapter.resolve(request, credentials=credentials)

        result = await HttpArtifactTransport(client=client).transfer(
            resolved=resolved,
            destination=destination,
            quarantine_root=quarantine_root,
            progress_callback=record,
            refresh_transfer=refresh,
        )

    assert result.bytes_transferred == FIXTURE_SIZE
    assert hashlib.sha256(destination.read_bytes()).hexdigest() == FIXTURE_SHA256
    assert progress[-1] == 100


@pytest.mark.skipif(
    not _configured("PULLBOX_LIVE_PIXELDRAIN_URL", "PULLBOX_LIVE_PIXELDRAIN_API_KEY"),
    reason="PixelDrain live account fixture is not configured",
)
async def test_pixeldrain_account_fixture(tmp_path: Path) -> None:
    await _exercise_http_host(
        tmp_path,
        adapter_type=PixelDrainAdapter,
        host_kind=DirectArtifactHostKind.PIXELDRAIN,
        url_env="PULLBOX_LIVE_PIXELDRAIN_URL",
        credentials={"api_key": os.environ["PULLBOX_LIVE_PIXELDRAIN_API_KEY"]},
    )


@pytest.mark.skipif(
    not _configured("PULLBOX_LIVE_PIXELDRAIN_URL"),
    reason="PixelDrain live anonymous fixture is not configured",
)
async def test_pixeldrain_anonymous_fixture(tmp_path: Path) -> None:
    await _exercise_http_host(
        tmp_path,
        adapter_type=PixelDrainAdapter,
        host_kind=DirectArtifactHostKind.PIXELDRAIN,
        url_env="PULLBOX_LIVE_PIXELDRAIN_URL",
        credentials={},
    )


@pytest.mark.skipif(
    not _configured("PULLBOX_LIVE_ROOTZ_URL"),
    reason="Rootz live fixture is not configured",
)
async def test_rootz_anonymous_fixture(tmp_path: Path) -> None:
    await _exercise_http_host(
        tmp_path,
        adapter_type=RootzAdapter,
        host_kind=DirectArtifactHostKind.ROOTZ,
        url_env="PULLBOX_LIVE_ROOTZ_URL",
        credentials={},
    )


@pytest.mark.skipif(
    not _configured("PULLBOX_LIVE_MEDIAFIRE_URL"),
    reason="MediaFire live public fixture is not configured",
)
async def test_mediafire_anonymous_fixture(tmp_path: Path) -> None:
    await _exercise_http_host(
        tmp_path,
        adapter_type=MediaFireAdapter,
        host_kind=DirectArtifactHostKind.MEDIAFIRE,
        url_env="PULLBOX_LIVE_MEDIAFIRE_URL",
        credentials={},
    )


@pytest.mark.skipif(
    not _configured("PULLBOX_LIVE_TERABOX_URL", "PULLBOX_LIVE_TERABOX_SESSION"),
    reason="TeraBox live account fixture is not configured",
)
async def test_terabox_account_fixture(tmp_path: Path) -> None:
    await _exercise_http_host(
        tmp_path,
        adapter_type=TeraBoxAdapter,
        host_kind=DirectArtifactHostKind.TERABOX,
        url_env="PULLBOX_LIVE_TERABOX_URL",
        credentials={"session_token": os.environ["PULLBOX_LIVE_TERABOX_SESSION"]},
    )


@pytest.mark.skipif(
    not _configured("PULLBOX_LIVE_DATANODES_URL"),
    reason="DataNodes live public fixture is not configured",
)
async def test_datanodes_anonymous_fixture(tmp_path: Path) -> None:
    try:
        await _exercise_http_host(
            tmp_path,
            adapter_type=DataNodesAdapter,
            host_kind=DirectArtifactHostKind.DATANODES,
            url_env="PULLBOX_LIVE_DATANODES_URL",
            credentials={},
        )
    except ArtifactHostResolutionError as exc:
        # DataNodes may require interactive verification for its free flow.
        assert exc.code == "artifact_host_challenge"
        assert exc.failure_class is DirectArtifactFailureClass.ARTIFACT_HOST_CHALLENGE
        assert exc.retryable is False
        assert exc.intervention is True


async def _exercise_mega(
    tmp_path: Path,
    *,
    credentials: Mapping[str, str],
) -> None:
    request = _request(DirectArtifactHostKind.MEGA, "PULLBOX_LIVE_MEGA_URL")
    resolved = await MegaArtifactHostAdapter().resolve(
        request,
        credentials=credentials,
    )
    quarantine_root = tmp_path / "mega"
    quarantine_root.mkdir()
    destination = quarantine_root / "fixture.partial"
    progress: list[tuple[int, int]] = []

    async def record(current: int, total: int) -> None:
        progress.append((current, total))

    result = await MegaBridgeRunner(
        command=shlex.split(os.environ["PULLBOX_LIVE_MEGA_BRIDGE_COMMAND"]),
    ).transfer(
        public_link=resolved.url,
        destination=destination,
        quarantine_root=quarantine_root,
        session=resolved.bridge_session,
        expected_size=FIXTURE_SIZE,
        progress_callback=record,
    )

    assert result.bytes_transferred == FIXTURE_SIZE
    assert hashlib.sha256(destination.read_bytes()).hexdigest() == FIXTURE_SHA256
    assert progress[-1] == (FIXTURE_SIZE, FIXTURE_SIZE)


@pytest.mark.skipif(
    not _configured(
        "PULLBOX_LIVE_MEGA_URL",
        "PULLBOX_LIVE_MEGA_BRIDGE_COMMAND",
    ),
    reason="MEGA live anonymous fixture is not configured",
)
async def test_mega_anonymous_fixture(tmp_path: Path) -> None:
    await _exercise_mega(tmp_path, credentials={})


@pytest.mark.skipif(
    not _configured(
        "PULLBOX_LIVE_MEGA_URL",
        "PULLBOX_LIVE_MEGA_SESSION",
        "PULLBOX_LIVE_MEGA_BRIDGE_COMMAND",
    ),
    reason="MEGA live account fixture is not configured",
)
async def test_mega_account_fixture(tmp_path: Path) -> None:
    await _exercise_mega(
        tmp_path,
        credentials={"session": os.environ["PULLBOX_LIVE_MEGA_SESSION"]},
    )
