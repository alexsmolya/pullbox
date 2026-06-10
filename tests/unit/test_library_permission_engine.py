"""Tests for library permission filesystem decisions."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

import pullbox.core.library_permission_engine as engine
from pullbox.core.library_permission_engine import (
    PermissionAction,
    PermissionCapabilityResult,
    PermissionChangeResult,
    PermissionReason,
    PermissionTargetKind,
    apply_permission_change,
    probe_permission_capability,
)


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


def test_apply_permission_change_skips_missing_path(tmp_path: Path) -> None:
    target = tmp_path / "missing.cbz"

    result = apply_permission_change(target, 0o644, dry_run=False)

    assert result.action is PermissionAction.SKIPPED
    assert result.reason is PermissionReason.MISSING
    assert result.target_kind is PermissionTargetKind.MISSING
    assert result.previous_mode is None
    assert result.resulting_mode is None


def test_apply_permission_change_dry_run_does_not_mutate_file(tmp_path: Path) -> None:
    target = tmp_path / "Batman 001.cbz"
    target.write_bytes(b"comic")
    target.chmod(0o600)

    result = apply_permission_change(target, 0o644, dry_run=True)

    assert result.action is PermissionAction.WOULD_APPLY
    assert result.reason is PermissionReason.DRY_RUN
    assert result.target_kind is PermissionTargetKind.FILE
    assert result.previous_mode == 0o600
    assert result.resulting_mode == 0o600
    assert _mode(target) == 0o600


def test_apply_permission_change_applies_and_verifies_file_mode(tmp_path: Path) -> None:
    target = tmp_path / "Batman 001.cbz"
    target.write_bytes(b"comic")
    target.chmod(0o600)

    result = apply_permission_change(target, 0o644, dry_run=False)

    assert result.action is PermissionAction.APPLIED
    assert result.reason is PermissionReason.APPLIED
    assert result.target_kind is PermissionTargetKind.FILE
    assert result.previous_mode == 0o600
    assert result.resulting_mode == 0o644
    assert _mode(target) == 0o644


def test_apply_permission_change_skips_already_matching_file(tmp_path: Path) -> None:
    target = tmp_path / "Batman 001.cbz"
    target.write_bytes(b"comic")
    target.chmod(0o644)

    result = apply_permission_change(target, 0o644, dry_run=False)

    assert result.action is PermissionAction.SKIPPED
    assert result.reason is PermissionReason.ALREADY_MATCHES
    assert result.previous_mode == 0o644
    assert result.resulting_mode == 0o644


def test_apply_permission_change_applies_and_verifies_folder_mode(tmp_path: Path) -> None:
    target = tmp_path / "Batman (2024)"
    target.mkdir()
    target.chmod(0o700)

    result = apply_permission_change(target, 0o755, dry_run=False)

    assert result.action is PermissionAction.APPLIED
    assert result.target_kind is PermissionTargetKind.FOLDER
    assert result.previous_mode == 0o700
    assert result.resulting_mode == 0o755
    assert _mode(target) == 0o755


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlink support unavailable")
def test_apply_permission_change_skips_symlink_without_following_target(tmp_path: Path) -> None:
    real_file = tmp_path / "real.cbz"
    real_file.write_bytes(b"comic")
    real_file.chmod(0o600)
    symlink = tmp_path / "linked.cbz"
    symlink.symlink_to(real_file)

    result = apply_permission_change(symlink, 0o644, dry_run=False)

    assert result.action is PermissionAction.SKIPPED
    assert result.reason is PermissionReason.SYMLINK_SKIPPED
    assert result.target_kind is PermissionTargetKind.SYMLINK
    assert _mode(real_file) == 0o600


@pytest.mark.skipif(not hasattr(os, "link"), reason="hardlink support unavailable")
def test_apply_permission_change_skips_hardlink_by_default(tmp_path: Path) -> None:
    source = tmp_path / "source.cbz"
    source.write_bytes(b"comic")
    source.chmod(0o600)
    hardlink = tmp_path / "hardlink.cbz"
    os.link(source, hardlink)

    result = apply_permission_change(hardlink, 0o644, dry_run=False)

    assert result.action is PermissionAction.SKIPPED
    assert result.reason is PermissionReason.HARDLINK_SKIPPED
    assert result.target_kind is PermissionTargetKind.HARDLINK
    assert _mode(source) == 0o600
    assert _mode(hardlink) == 0o600


@pytest.mark.skipif(not hasattr(os, "link"), reason="hardlink support unavailable")
def test_apply_permission_change_can_apply_hardlink_when_explicitly_allowed(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.cbz"
    source.write_bytes(b"comic")
    source.chmod(0o600)
    hardlink = tmp_path / "hardlink.cbz"
    os.link(source, hardlink)

    result = apply_permission_change(
        hardlink,
        0o644,
        dry_run=False,
        skip_hardlinks=False,
    )

    assert result.action is PermissionAction.APPLIED
    assert result.reason is PermissionReason.APPLIED
    assert result.target_kind is PermissionTargetKind.HARDLINK
    assert _mode(source) == 0o644
    assert _mode(hardlink) == 0o644


def test_apply_permission_change_reports_ignored_chmod(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "ignored.cbz"
    target.write_bytes(b"comic")
    target.chmod(0o600)

    def fake_chmod(self: Path, mode: int) -> None:
        del self, mode

    monkeypatch.setattr(Path, "chmod", fake_chmod)

    result = apply_permission_change(target, 0o644, dry_run=False)

    assert result.action is PermissionAction.UNSUPPORTED
    assert result.reason is PermissionReason.CHMOD_IGNORED
    assert result.previous_mode == 0o600
    assert result.resulting_mode == 0o600


def test_apply_permission_change_reports_permission_denied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "denied.cbz"
    target.write_bytes(b"comic")
    target.chmod(0o600)

    def fake_chmod(self: Path, mode: int) -> None:
        del self, mode
        raise PermissionError("operation not permitted")

    monkeypatch.setattr(Path, "chmod", fake_chmod)

    result = apply_permission_change(target, 0o644, dry_run=False)

    assert result.action is PermissionAction.FAILED
    assert result.reason is PermissionReason.PERMISSION_DENIED
    assert "operation not permitted" in (result.error_message or "")
    assert result.previous_mode == 0o600
    assert result.resulting_mode == 0o600


def test_probe_permission_capability_reports_supported_temp_path(tmp_path: Path) -> None:
    result = probe_permission_capability(tmp_path)

    assert result.supported is True
    assert result.can_stat_root is True
    assert result.can_create_file is True
    assert result.can_create_directory is True
    assert result.file_chmod_supported is True
    assert result.directory_chmod_supported is True
    assert result.restore_supported is True
    assert result.reason is PermissionReason.CAPABILITY_SUPPORTED
    assert not any(tmp_path.iterdir())


def test_probe_permission_capability_reports_missing_root(tmp_path: Path) -> None:
    result = probe_permission_capability(tmp_path / "missing")

    assert result.supported is False
    assert result.can_stat_root is False
    assert result.reason is PermissionReason.MISSING


@pytest.mark.parametrize(
    ("raiser", "expected_reason"),
    [
        (PermissionError("stat denied"), PermissionReason.PERMISSION_DENIED),
        (OSError("stale mount"), PermissionReason.OS_ERROR),
    ],
)
def test_probe_permission_capability_reports_root_stat_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    raiser: OSError,
    expected_reason: PermissionReason,
) -> None:
    def fake_stat(self: Path, *args: object, **kwargs: object) -> object:
        del self, args, kwargs
        raise raiser

    monkeypatch.setattr(Path, "stat", fake_stat)

    result = probe_permission_capability(tmp_path)

    assert result.supported is False
    assert result.can_stat_root is False
    assert result.reason is expected_reason
    assert result.error_message


def test_probe_permission_capability_reports_ignored_chmod(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_chmod(self: Path, mode: int) -> None:
        del self, mode

    monkeypatch.setattr(Path, "chmod", fake_chmod)

    result = probe_permission_capability(tmp_path)

    assert result.supported is False
    assert result.can_stat_root is True
    assert result.file_chmod_supported is False
    assert result.reason is PermissionReason.CHMOD_IGNORED


def test_probe_permission_capability_reports_restore_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(engine, "_restore_mode", lambda path, mode: False)

    result = probe_permission_capability(tmp_path)

    assert result.supported is False
    assert result.file_chmod_supported is True
    assert result.restore_supported is False
    assert result.reason is PermissionReason.OS_ERROR
    assert result.error_message == "failed to restore probe file mode"


def test_probe_permission_capability_reports_directory_chmod_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def fake_apply_permission_change(
        path: Path,
        requested_mode: int,
        *,
        dry_run: bool,
        skip_hardlinks: bool = True,
        skip_symlinks: bool = True,
    ) -> PermissionChangeResult:
        nonlocal calls
        del requested_mode, dry_run, skip_hardlinks, skip_symlinks
        calls += 1
        if calls == 1:
            return PermissionChangeResult(
                path=path,
                target_kind=PermissionTargetKind.FILE,
                action=PermissionAction.APPLIED,
                reason=PermissionReason.APPLIED,
                requested_mode=0o644,
                previous_mode=0o600,
                resulting_mode=0o644,
            )
        return PermissionChangeResult(
            path=path,
            target_kind=PermissionTargetKind.FOLDER,
            action=PermissionAction.UNSUPPORTED,
            reason=PermissionReason.CHMOD_IGNORED,
            requested_mode=0o755,
            previous_mode=0o700,
            resulting_mode=0o700,
        )

    monkeypatch.setattr(engine, "apply_permission_change", fake_apply_permission_change)

    result = probe_permission_capability(tmp_path)

    assert result.supported is False
    assert result.file_chmod_supported is True
    assert result.directory_chmod_supported is False
    assert result.restore_supported is True
    assert result.reason is PermissionReason.CHMOD_IGNORED


@pytest.mark.parametrize(
    ("raiser", "expected_reason"),
    [
        (PermissionError("cannot create probe"), PermissionReason.PERMISSION_DENIED),
        (OSError("read-only root"), PermissionReason.OS_ERROR),
    ],
)
def test_probe_permission_capability_reports_probe_creation_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    raiser: OSError,
    expected_reason: PermissionReason,
) -> None:
    def fake_create_probe_file(root: Path) -> Path:
        del root
        raise raiser

    monkeypatch.setattr(engine, "_create_probe_file", fake_create_probe_file)

    result = probe_permission_capability(tmp_path)

    assert result.supported is False
    assert result.can_stat_root is True
    assert result.reason is expected_reason
    assert result.error_message


@pytest.mark.parametrize(
    ("raiser", "expected_reason"),
    [
        (PermissionError("permission denied"), PermissionReason.PERMISSION_DENIED),
        (OSError("read-only filesystem"), PermissionReason.OS_ERROR),
    ],
)
def test_probe_permission_capability_reports_chmod_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    raiser: OSError,
    expected_reason: PermissionReason,
) -> None:
    def fake_chmod(self: Path, mode: int) -> None:
        del self, mode
        raise raiser

    monkeypatch.setattr(Path, "chmod", fake_chmod)

    result = probe_permission_capability(tmp_path)

    assert result.supported is False
    assert result.file_chmod_supported is False
    assert result.reason is expected_reason
    assert result.error_message


def test_apply_permission_change_reports_unsupported_special_file(
    tmp_path: Path,
) -> None:
    fifo = tmp_path / "pipe"
    if not hasattr(os, "mkfifo"):
        pytest.skip("fifo support unavailable")
    os.mkfifo(fifo)

    result = apply_permission_change(fifo, 0o644, dry_run=True)

    assert result.action is PermissionAction.SKIPPED
    assert result.reason is PermissionReason.UNSUPPORTED_TARGET
    assert result.target_kind is PermissionTargetKind.UNSUPPORTED


def test_permission_result_serializes_paths_and_modes(tmp_path: Path) -> None:
    target = tmp_path / "Batman 001.cbz"
    target.write_bytes(b"comic")
    target.chmod(0o600)

    result = apply_permission_change(target, 0o644, dry_run=True)

    assert result.serialized() == {
        "path": str(target),
        "target_kind": "file",
        "action": "would_apply",
        "reason": "dry_run",
        "requested_mode": "644",
        "previous_mode": "600",
        "resulting_mode": "600",
        "error_message": None,
    }


def test_missing_permission_result_serializes_null_modes(tmp_path: Path) -> None:
    target = tmp_path / "missing.cbz"

    result = apply_permission_change(target, 0o644, dry_run=False)

    assert result.serialized()["previous_mode"] is None
    assert result.serialized()["resulting_mode"] is None


def test_capability_result_can_represent_unsupported_ownership_future_state(
    tmp_path: Path,
) -> None:
    result = PermissionCapabilityResult(
        path=tmp_path,
        supported=False,
        reason=PermissionReason.OS_ERROR,
        can_stat_root=True,
        can_create_file=False,
        can_create_directory=False,
        file_chmod_supported=False,
        directory_chmod_supported=False,
        restore_supported=False,
        error_message="ownership changes are not supported in v1",
    )

    assert result.error_message == "ownership changes are not supported in v1"
