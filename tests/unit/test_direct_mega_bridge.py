from __future__ import annotations

import asyncio
import stat
import sys
from typing import TYPE_CHECKING

import pytest

from pullbox.models.direct_acquisition import (
    DirectArtifactFailureClass,
    DirectArtifactHostKind,
)
from pullbox.providers.artifact_hosts.contract import (
    ArtifactHostResolutionError,
    ArtifactTransferProtocol,
    HostResolutionRequest,
)
from pullbox.providers.artifact_hosts.mega import (
    MegaArtifactHostAdapter,
    MegaBridgeCancelledError,
    MegaBridgePausedError,
    MegaBridgeRunner,
    MegaBridgeTransferError,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.asyncio
async def test_mega_adapter_returns_secret_safe_native_transfer() -> None:
    link = "https://mega.nz/file/public-handle#private-link-key"
    session = "revocable-account-session"

    transfer = await MegaArtifactHostAdapter().resolve(
        HostResolutionRequest(
            artifact_identity="mega-artifact-1",
            host_kind=DirectArtifactHostKind.MEGA,
            share_url=link,
            final_url=None,
        ),
        credentials={"session": session},
    )

    assert transfer.transport_protocol is ArtifactTransferProtocol.MEGA_BRIDGE
    assert transfer.url == link
    assert transfer.bridge_session == session
    assert link not in repr(transfer)
    assert session not in repr(transfer)


@pytest.mark.asyncio
async def test_mega_bridge_sends_link_and_session_only_over_stdin(
    tmp_path: Path,
) -> None:
    executable = _write_fake_bridge(
        tmp_path,
        body="""
request = read_request()
assert request[\"session\"] == \"revocable-account-session\"
destination = Path(request[\"destination\"])
destination.write_bytes(b\"comic\")
emit(\"META 5 69737375652e63627a\")
emit(\"PROGRESS 5 5\")
emit(\"COMPLETE 5 69737375652e63627a\")
""",
    )
    quarantine_root = tmp_path / "quarantine"
    quarantine_root.mkdir()
    destination = quarantine_root / "attempt-1.part"
    link = "https://mega.nz/file/public-handle#private-link-key"
    session = "revocable-account-session"
    observed: list[tuple[int, int]] = []

    result = await MegaBridgeRunner(command=(sys.executable, str(executable))).transfer(
        public_link=link,
        destination=destination,
        quarantine_root=quarantine_root,
        session=session,
        progress_callback=lambda current, total: observed.append((current, total)),
    )

    assert destination.read_bytes() == b"comic"
    assert result.bytes_transferred == 5
    assert result.filename_hint == "issue.cbz"
    assert observed == [(5, 5)]
    assert link not in result.command_summary
    assert session not in result.command_summary
    assert link not in repr(result)
    assert session not in repr(result)


@pytest.mark.asyncio
async def test_mega_bridge_rejects_destination_outside_quarantine(
    tmp_path: Path,
) -> None:
    root = tmp_path / "quarantine"
    root.mkdir()

    with pytest.raises(MegaBridgeTransferError, match="quarantine") as caught:
        await MegaBridgeRunner(command=("unused",)).transfer(
            public_link="https://mega.nz/file/id#key",
            destination=tmp_path / "outside.cbz",
            quarantine_root=root,
        )

    assert caught.value.failure_class is DirectArtifactFailureClass.SAFETY
    assert caught.value.retryable is False


@pytest.mark.asyncio
async def test_mega_bridge_rejects_symlink_destination(
    tmp_path: Path,
) -> None:
    root = tmp_path / "quarantine"
    root.mkdir()
    outside = tmp_path / "outside.cbz"
    outside.write_bytes(b"untouched")
    destination = root / "attempt.part"
    destination.symlink_to(outside)

    with pytest.raises(MegaBridgeTransferError, match="quarantine"):
        await MegaBridgeRunner(command=("unused",)).transfer(
            public_link="https://mega.nz/file/id#key",
            destination=destination,
            quarantine_root=root,
        )

    assert outside.read_bytes() == b"untouched"


@pytest.mark.asyncio
async def test_mega_bridge_cancellation_terminates_process_and_removes_partial(
    tmp_path: Path,
) -> None:
    executable = _write_fake_bridge(
        tmp_path,
        body="""
request = read_request()
destination = Path(request[\"destination\"])
destination.write_bytes(b\"partial\")
emit(\"PROGRESS 7 100\")
time.sleep(30)
""",
    )
    root = tmp_path / "quarantine"
    root.mkdir()
    destination = root / "attempt.part"
    cancel_event = asyncio.Event()

    async def cancel_after_progress(current: int, total: int) -> None:
        assert (current, total) == (7, 100)
        cancel_event.set()

    with pytest.raises(MegaBridgeCancelledError):
        await asyncio.wait_for(
            MegaBridgeRunner(command=(sys.executable, str(executable))).transfer(
                public_link="https://mega.nz/file/id#key",
                destination=destination,
                quarantine_root=root,
                cancel_event=cancel_event,
                progress_callback=cancel_after_progress,
            ),
            timeout=5,
        )

    assert not destination.exists()


@pytest.mark.asyncio
async def test_mega_bridge_pause_terminates_and_restarts_safely_from_zero(
    tmp_path: Path,
) -> None:
    executable = _write_fake_bridge(
        tmp_path,
        body="""
request = read_request()
destination = Path(request["destination"])
destination.write_bytes(b"partial")
emit("PROGRESS 7 100")
time.sleep(30)
""",
    )
    root = tmp_path / "quarantine"
    root.mkdir()
    destination = root / "attempt.part"
    pause_event = asyncio.Event()

    async def pause_after_progress(current: int, total: int) -> None:
        assert (current, total) == (7, 100)
        pause_event.set()

    with pytest.raises(MegaBridgePausedError) as caught:
        await asyncio.wait_for(
            MegaBridgeRunner(command=(sys.executable, str(executable))).transfer(
                public_link="https://mega.nz/file/id#key",
                destination=destination,
                quarantine_root=root,
                pause_event=pause_event,
                progress_callback=pause_after_progress,
            ),
            timeout=5,
        )

    assert caught.value.bytes_transferred == 0
    assert not destination.exists()


@pytest.mark.asyncio
async def test_mega_bridge_maps_stable_error_without_exposing_output(
    tmp_path: Path,
) -> None:
    executable = _write_fake_bridge(
        tmp_path,
        body='emit("ERROR mega_quota_exceeded 1 0")',
    )
    root = tmp_path / "quarantine"
    root.mkdir()

    with pytest.raises(MegaBridgeTransferError) as caught:
        await MegaBridgeRunner(command=(sys.executable, str(executable))).transfer(
            public_link="https://mega.nz/file/id#secret-link-key",
            destination=root / "attempt.part",
            quarantine_root=root,
            session="secret-session",
        )

    assert caught.value.code == "mega_quota_exceeded"
    assert caught.value.retryable is True
    assert "secret" not in str(caught.value)
    assert "secret" not in repr(caught.value)


@pytest.mark.asyncio
async def test_mega_bridge_rejects_malformed_or_unbounded_protocol_output(
    tmp_path: Path,
) -> None:
    executable = _write_fake_bridge(
        tmp_path,
        body='emit("X" * 70000)',
    )
    root = tmp_path / "quarantine"
    root.mkdir()

    with pytest.raises(MegaBridgeTransferError) as caught:
        await MegaBridgeRunner(command=(sys.executable, str(executable))).transfer(
            public_link="https://mega.nz/file/id#key",
            destination=root / "attempt.part",
            quarantine_root=root,
        )

    assert caught.value.code == "mega_bridge_protocol_error"
    assert caught.value.retryable is False


@pytest.mark.asyncio
async def test_mega_bridge_rejects_unbounded_stderr_output(tmp_path: Path) -> None:
    executable = _write_fake_bridge(
        tmp_path,
        body="""
request = read_request()
destination = Path(request["destination"])
destination.write_bytes(b"comic")
sys.stderr.buffer.write(b"X" * 65537)
sys.stderr.buffer.flush()
emit("COMPLETE 5 69737375652e63627a")
""",
    )
    root = tmp_path / "quarantine"
    root.mkdir()
    destination = root / "attempt.part"

    with pytest.raises(MegaBridgeTransferError) as caught:
        await MegaBridgeRunner(command=(sys.executable, str(executable))).transfer(
            public_link="https://mega.nz/file/id#key",
            destination=destination,
            quarantine_root=root,
        )

    assert caught.value.code == "mega_bridge_protocol_error"
    assert not destination.exists()


@pytest.mark.asyncio
async def test_mega_adapter_rejects_non_mega_url() -> None:
    with pytest.raises(ArtifactHostResolutionError) as caught:
        await MegaArtifactHostAdapter().resolve(
            HostResolutionRequest(
                artifact_identity="wrong-host",
                host_kind=DirectArtifactHostKind.MEGA,
                share_url="https://example.com/not-mega.cbz",
                final_url=None,
            ),
            credentials={},
        )

    assert caught.value.code == "artifact_host_kind_mismatch"


def _write_fake_bridge(tmp_path: Path, *, body: str) -> Path:
    script = tmp_path / "fake_mega_bridge.py"
    source = f"""\
import sys
import time
from pathlib import Path


def read_exact(length):
    data = sys.stdin.buffer.read(length)
    if len(data) != length:
        raise RuntimeError("short request")
    return data.decode("utf-8")


def read_request():
    header = sys.stdin.buffer.readline().decode("ascii").strip()
    if header != "PULLBOX_MEGA_BRIDGE 1":
        raise RuntimeError("bad header")
    lengths = sys.stdin.buffer.readline().decode("ascii").strip().split()
    if len(lengths) != 4 or lengths[0] != "DOWNLOAD":
        raise RuntimeError("bad lengths")
    link_length, session_length, destination_length = map(int, lengths[1:])
    return {{
        "link": read_exact(link_length),
        "session": read_exact(session_length),
        "destination": read_exact(destination_length),
    }}


def emit(value):
    print(value, flush=True)


{body}
"""
    script.write_text(source, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script
