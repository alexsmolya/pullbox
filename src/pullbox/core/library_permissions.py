"""Library permission policy and chmod validation helpers."""

from __future__ import annotations

import enum
import stat
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from pullbox.core.config_resolver import load_system_config_values, parse_bool

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class PermissionPolicyError(ValueError):
    """Raised when library permission policy settings are invalid."""


class HardlinkPermissionBehavior(enum.StrEnum):
    """How permission changes should treat hardlinked files."""

    SKIP = "skip"


class SymlinkPermissionBehavior(enum.StrEnum):
    """How permission changes should treat symlinks."""

    SKIP = "skip"


class OwnershipCapability(enum.StrEnum):
    """Ownership support status reserved for future chown/chgrp work."""

    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class LibraryPermissionPolicy:
    """Effective library permission policy resolved from ``SystemConfig``."""

    enabled: bool
    folder_mode: int
    file_mode: int
    apply_to_created_folders: bool
    apply_to_materialized_files: bool
    hardlink_behavior: HardlinkPermissionBehavior
    symlink_behavior: SymlinkPermissionBehavior
    ownership_capability: OwnershipCapability = OwnershipCapability.UNSUPPORTED

    def serialized(self) -> dict[str, object]:
        """Return a JSON-friendly representation for logs and job payloads."""
        return {
            "enabled": self.enabled,
            "folder_mode": format_mode(self.folder_mode),
            "file_mode": format_mode(self.file_mode),
            "apply_to_created_folders": self.apply_to_created_folders,
            "apply_to_materialized_files": self.apply_to_materialized_files,
            "hardlink_behavior": self.hardlink_behavior.value,
            "symlink_behavior": self.symlink_behavior.value,
            "ownership_capability": self.ownership_capability.value,
        }


_PERMISSION_POLICY_KEYS = (
    "library_permissions_enabled",
    "library_permissions_folder_mode",
    "library_permissions_file_mode",
    "library_permissions_apply_to_created_folders",
    "library_permissions_apply_to_materialized_files",
    "library_permissions_hardlink_behavior",
    "library_permissions_symlink_behavior",
)


def format_mode(mode: int) -> str:
    """Format a POSIX mode as a three-digit octal permission label."""
    return f"{stat.S_IMODE(mode):03o}"


def parse_permission_mode(
    raw_mode: str,
    *,
    target_kind: Literal["file", "folder"],
    allow_file_execute: bool = False,
) -> int:
    """Parse and validate a strict three-digit chmod mode.

    A single leading zero is accepted for familiar ``0644`` style values, but
    the resulting mode is normalized to the permission bits only.
    """
    raw = raw_mode.strip()
    if raw.startswith("0") and len(raw) == 4:
        raw = raw[1:]

    if len(raw) != 3 or any(char not in "01234567" for char in raw):
        msg = f"invalid {target_kind} chmod mode: {raw_mode!r}"
        raise PermissionPolicyError(msg)

    mode = int(raw, 8)
    if target_kind == "folder" and not mode & stat.S_IXUSR:
        msg = "folder modes must include owner execute"
        raise PermissionPolicyError(msg)

    if target_kind == "file" and not allow_file_execute and mode & 0o111:
        msg = "file modes must not include execute"
        raise PermissionPolicyError(msg)

    return mode


async def load_library_permission_policy(session: AsyncSession) -> LibraryPermissionPolicy:
    """Load the effective library permission policy from ``SystemConfig``."""
    configs = await load_system_config_values(session, _PERMISSION_POLICY_KEYS)
    return LibraryPermissionPolicy(
        enabled=parse_bool(configs["library_permissions_enabled"]),
        folder_mode=parse_permission_mode(
            configs["library_permissions_folder_mode"],
            target_kind="folder",
        ),
        file_mode=parse_permission_mode(
            configs["library_permissions_file_mode"],
            target_kind="file",
        ),
        apply_to_created_folders=parse_bool(
            configs["library_permissions_apply_to_created_folders"]
        ),
        apply_to_materialized_files=parse_bool(
            configs["library_permissions_apply_to_materialized_files"]
        ),
        hardlink_behavior=_parse_hardlink_behavior(
            configs["library_permissions_hardlink_behavior"]
        ),
        symlink_behavior=_parse_symlink_behavior(configs["library_permissions_symlink_behavior"]),
        ownership_capability=OwnershipCapability.UNSUPPORTED,
    )


def _parse_hardlink_behavior(raw_value: str) -> HardlinkPermissionBehavior:
    value = raw_value.strip().lower()
    if value == HardlinkPermissionBehavior.SKIP.value:
        return HardlinkPermissionBehavior.SKIP
    msg = f"unsupported hardlink behavior: {raw_value!r}"
    raise PermissionPolicyError(msg)


def _parse_symlink_behavior(raw_value: str) -> SymlinkPermissionBehavior:
    value = raw_value.strip().lower()
    if value == SymlinkPermissionBehavior.SKIP.value:
        return SymlinkPermissionBehavior.SKIP
    msg = f"unsupported symlink behavior: {raw_value!r}"
    raise PermissionPolicyError(msg)
