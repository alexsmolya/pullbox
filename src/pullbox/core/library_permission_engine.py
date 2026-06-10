"""Filesystem permission engine for Pullbox library maintenance."""

from __future__ import annotations

import enum
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

from pullbox.core.library_permissions import format_mode


class PermissionAction(enum.StrEnum):
    """Outcome action for one permission decision."""

    APPLIED = "applied"
    FAILED = "failed"
    SKIPPED = "skipped"
    UNSUPPORTED = "unsupported"
    WOULD_APPLY = "would_apply"


class PermissionReason(enum.StrEnum):
    """Stable reason codes for permission decisions and probes."""

    ALREADY_MATCHES = "already_matches"
    APPLIED = "applied"
    CAPABILITY_SUPPORTED = "capability_supported"
    CHMOD_IGNORED = "chmod_ignored"
    DRY_RUN = "dry_run"
    HARDLINK_SKIPPED = "hardlink_skipped"
    MISSING = "missing"
    OS_ERROR = "os_error"
    PERMISSION_DENIED = "permission_denied"
    SYMLINK_SKIPPED = "symlink_skipped"
    UNSUPPORTED_TARGET = "unsupported_target"


class PermissionTargetKind(enum.StrEnum):
    """Filesystem target type for a permission decision."""

    FILE = "file"
    FOLDER = "folder"
    HARDLINK = "hardlink"
    MISSING = "missing"
    SYMLINK = "symlink"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class PermissionChangeResult:
    """Result for one chmod decision."""

    path: Path
    target_kind: PermissionTargetKind
    action: PermissionAction
    reason: PermissionReason
    requested_mode: int
    previous_mode: int | None
    resulting_mode: int | None
    error_message: str | None = None

    def serialized(self) -> dict[str, object]:
        """Return a JSON-friendly result payload for logs and utility jobs."""
        return {
            "path": str(self.path),
            "target_kind": self.target_kind.value,
            "action": self.action.value,
            "reason": self.reason.value,
            "requested_mode": format_mode(self.requested_mode),
            "previous_mode": _format_optional_mode(self.previous_mode),
            "resulting_mode": _format_optional_mode(self.resulting_mode),
            "error_message": self.error_message,
        }


@dataclass(frozen=True, slots=True)
class PermissionCapabilityResult:
    """Capability probe result for a selected root or mounted folder."""

    path: Path
    supported: bool
    reason: PermissionReason
    can_stat_root: bool
    can_create_file: bool
    can_create_directory: bool
    file_chmod_supported: bool
    directory_chmod_supported: bool
    restore_supported: bool
    error_message: str | None = None


def apply_permission_change(
    path: Path,
    requested_mode: int,
    *,
    dry_run: bool,
    skip_hardlinks: bool = True,
    skip_symlinks: bool = True,
) -> PermissionChangeResult:
    """Apply or preview a chmod operation with seed-safe skip behavior."""
    target_kind, previous_mode = _inspect_target(path)
    if target_kind is PermissionTargetKind.MISSING:
        return _result(
            path,
            target_kind,
            PermissionAction.SKIPPED,
            PermissionReason.MISSING,
            requested_mode,
            previous_mode,
            None,
        )

    if target_kind is PermissionTargetKind.SYMLINK and skip_symlinks:
        return _result(
            path,
            target_kind,
            PermissionAction.SKIPPED,
            PermissionReason.SYMLINK_SKIPPED,
            requested_mode,
            previous_mode,
            previous_mode,
        )

    if target_kind is PermissionTargetKind.HARDLINK and skip_hardlinks:
        return _result(
            path,
            target_kind,
            PermissionAction.SKIPPED,
            PermissionReason.HARDLINK_SKIPPED,
            requested_mode,
            previous_mode,
            previous_mode,
        )

    if target_kind is PermissionTargetKind.UNSUPPORTED:
        return _result(
            path,
            target_kind,
            PermissionAction.SKIPPED,
            PermissionReason.UNSUPPORTED_TARGET,
            requested_mode,
            previous_mode,
            previous_mode,
        )

    if previous_mode == requested_mode:
        return _result(
            path,
            target_kind,
            PermissionAction.SKIPPED,
            PermissionReason.ALREADY_MATCHES,
            requested_mode,
            previous_mode,
            previous_mode,
        )

    if dry_run:
        return _result(
            path,
            target_kind,
            PermissionAction.WOULD_APPLY,
            PermissionReason.DRY_RUN,
            requested_mode,
            previous_mode,
            previous_mode,
        )

    try:
        path.chmod(requested_mode)
    except PermissionError as exc:
        return _result(
            path,
            target_kind,
            PermissionAction.FAILED,
            PermissionReason.PERMISSION_DENIED,
            requested_mode,
            previous_mode,
            _safe_mode(path),
            error_message=str(exc),
        )
    except OSError as exc:
        return _result(
            path,
            target_kind,
            PermissionAction.FAILED,
            PermissionReason.OS_ERROR,
            requested_mode,
            previous_mode,
            _safe_mode(path),
            error_message=str(exc),
        )

    resulting_mode = _safe_mode(path)
    if resulting_mode != requested_mode:
        return _result(
            path,
            target_kind,
            PermissionAction.UNSUPPORTED,
            PermissionReason.CHMOD_IGNORED,
            requested_mode,
            previous_mode,
            resulting_mode,
        )

    return _result(
        path,
        target_kind,
        PermissionAction.APPLIED,
        PermissionReason.APPLIED,
        requested_mode,
        previous_mode,
        resulting_mode,
    )


def probe_permission_capability(
    root: Path,
    *,
    file_mode: int = 0o644,
    folder_mode: int = 0o755,
) -> PermissionCapabilityResult:
    """Probe whether a root supports verified chmod behavior."""
    try:
        root.stat()
    except FileNotFoundError:
        return _capability_result(
            root,
            supported=False,
            reason=PermissionReason.MISSING,
            can_stat_root=False,
        )
    except PermissionError as exc:
        return _capability_result(
            root,
            supported=False,
            reason=PermissionReason.PERMISSION_DENIED,
            can_stat_root=False,
            error_message=str(exc),
        )
    except OSError as exc:
        return _capability_result(
            root,
            supported=False,
            reason=PermissionReason.OS_ERROR,
            can_stat_root=False,
            error_message=str(exc),
        )

    probe_file: Path | None = None
    probe_dir: Path | None = None
    try:
        probe_file = _create_probe_file(root)
        file_original_mode = _safe_mode(probe_file)
        file_probe_mode = _mode_that_differs(file_mode, file_original_mode)
        file_result = apply_permission_change(probe_file, file_probe_mode, dry_run=False)
        if file_result.action is not PermissionAction.APPLIED:
            return _capability_result(
                root,
                supported=False,
                reason=file_result.reason,
                can_stat_root=True,
                can_create_file=True,
                file_chmod_supported=False,
                error_message=file_result.error_message,
            )

        if not _restore_mode(probe_file, file_original_mode):
            return _capability_result(
                root,
                supported=False,
                reason=PermissionReason.OS_ERROR,
                can_stat_root=True,
                can_create_file=True,
                file_chmod_supported=True,
                error_message="failed to restore probe file mode",
            )

        probe_dir = _create_probe_dir(root)
        dir_original_mode = _safe_mode(probe_dir)
        dir_probe_mode = _mode_that_differs(folder_mode, dir_original_mode)
        dir_result = apply_permission_change(probe_dir, dir_probe_mode, dry_run=False)
        if dir_result.action is not PermissionAction.APPLIED:
            return _capability_result(
                root,
                supported=False,
                reason=dir_result.reason,
                can_stat_root=True,
                can_create_file=True,
                can_create_directory=True,
                file_chmod_supported=True,
                directory_chmod_supported=False,
                restore_supported=True,
                error_message=dir_result.error_message,
            )

        if not _restore_mode(probe_dir, dir_original_mode):
            return _capability_result(
                root,
                supported=False,
                reason=PermissionReason.OS_ERROR,
                can_stat_root=True,
                can_create_file=True,
                can_create_directory=True,
                file_chmod_supported=True,
                directory_chmod_supported=True,
                error_message="failed to restore probe directory mode",
            )

        return _capability_result(
            root,
            supported=True,
            reason=PermissionReason.CAPABILITY_SUPPORTED,
            can_stat_root=True,
            can_create_file=True,
            can_create_directory=True,
            file_chmod_supported=True,
            directory_chmod_supported=True,
            restore_supported=True,
        )
    except PermissionError as exc:
        return _capability_result(
            root,
            supported=False,
            reason=PermissionReason.PERMISSION_DENIED,
            can_stat_root=True,
            error_message=str(exc),
        )
    except OSError as exc:
        return _capability_result(
            root,
            supported=False,
            reason=PermissionReason.OS_ERROR,
            can_stat_root=True,
            error_message=str(exc),
        )
    finally:
        _cleanup_probe_path(probe_file)
        _cleanup_probe_path(probe_dir)


def _inspect_target(path: Path) -> tuple[PermissionTargetKind, int | None]:
    try:
        path_stat = path.lstat()
    except FileNotFoundError:
        return PermissionTargetKind.MISSING, None

    mode = stat.S_IMODE(path_stat.st_mode)
    if stat.S_ISLNK(path_stat.st_mode):
        return PermissionTargetKind.SYMLINK, mode
    if stat.S_ISDIR(path_stat.st_mode):
        return PermissionTargetKind.FOLDER, mode
    if stat.S_ISREG(path_stat.st_mode) and path_stat.st_nlink > 1:
        return PermissionTargetKind.HARDLINK, mode
    if stat.S_ISREG(path_stat.st_mode):
        return PermissionTargetKind.FILE, mode
    return PermissionTargetKind.UNSUPPORTED, mode


def _safe_mode(path: Path) -> int | None:
    try:
        return stat.S_IMODE(path.lstat().st_mode)
    except OSError:
        return None


def _restore_mode(path: Path, mode: int | None) -> bool:
    if mode is None:
        return False
    try:
        path.chmod(mode)
    except OSError:
        return False
    return _safe_mode(path) == mode


def _create_probe_file(root: Path) -> Path:
    with tempfile.NamedTemporaryFile(
        prefix=".pullbox-permission-probe-",
        suffix=".tmp",
        dir=root,
        delete=False,
    ) as handle:
        handle.write(b"pullbox permission probe")
        return Path(handle.name)


def _create_probe_dir(root: Path) -> Path:
    return Path(tempfile.mkdtemp(prefix=".pullbox-permission-probe-", dir=root))


def _cleanup_probe_path(path: Path | None) -> None:
    if path is None:
        return
    try:
        if path.is_dir() and not path.is_symlink():
            path.rmdir()
        else:
            path.unlink()
    except FileNotFoundError:
        return
    except OSError:
        return


def _mode_that_differs(preferred_mode: int, current_mode: int | None) -> int:
    if current_mode != preferred_mode:
        return preferred_mode
    return 0o600 if preferred_mode != 0o600 else 0o644


def _result(
    path: Path,
    target_kind: PermissionTargetKind,
    action: PermissionAction,
    reason: PermissionReason,
    requested_mode: int,
    previous_mode: int | None,
    resulting_mode: int | None,
    *,
    error_message: str | None = None,
) -> PermissionChangeResult:
    return PermissionChangeResult(
        path=path,
        target_kind=target_kind,
        action=action,
        reason=reason,
        requested_mode=requested_mode,
        previous_mode=previous_mode,
        resulting_mode=resulting_mode,
        error_message=error_message,
    )


def _capability_result(
    path: Path,
    *,
    supported: bool,
    reason: PermissionReason,
    can_stat_root: bool,
    can_create_file: bool = False,
    can_create_directory: bool = False,
    file_chmod_supported: bool = False,
    directory_chmod_supported: bool = False,
    restore_supported: bool = False,
    error_message: str | None = None,
) -> PermissionCapabilityResult:
    return PermissionCapabilityResult(
        path=path,
        supported=supported,
        reason=reason,
        can_stat_root=can_stat_root,
        can_create_file=can_create_file,
        can_create_directory=can_create_directory,
        file_chmod_supported=file_chmod_supported,
        directory_chmod_supported=directory_chmod_supported,
        restore_supported=restore_supported,
        error_message=error_message,
    )


def _format_optional_mode(mode: int | None) -> str | None:
    if mode is None:
        return None
    return format_mode(mode)
