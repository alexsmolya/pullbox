"""Tests for library permission policy parsing and defaults."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from pullbox.core.library_permissions import (
    HardlinkPermissionBehavior,
    LibraryPermissionPolicy,
    OwnershipCapability,
    PermissionPolicyError,
    SymlinkPermissionBehavior,
    format_mode,
    load_library_permission_policy,
    parse_permission_mode,
)
from pullbox.models.config import DEFAULT_SYSTEM_CONFIG, SystemConfig

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.parametrize(
    ("raw", "expected_mode", "expected_label"),
    [
        ("644", 0o644, "644"),
        ("0644", 0o644, "644"),
        ("664", 0o664, "664"),
        ("640", 0o640, "640"),
        ("600", 0o600, "600"),
        (" 644 ", 0o644, "644"),
    ],
)
def test_parse_permission_mode_accepts_supported_octal_forms(
    raw: str,
    expected_mode: int,
    expected_label: str,
) -> None:
    mode = parse_permission_mode(raw, target_kind="file")

    assert mode == expected_mode
    assert format_mode(mode) == expected_label


@pytest.mark.parametrize(
    "raw",
    [
        "",
        " ",
        "64",
        "06444",
        "6444",
        "abc",
        "6a4",
        "888",
        "-644",
        "+644",
        "0o644",
        "0x1a4",
        "644 # comment",
        "rwxr-xr-x",
    ],
)
def test_parse_permission_mode_rejects_malformed_values(raw: str) -> None:
    with pytest.raises(PermissionPolicyError):
        parse_permission_mode(raw, target_kind="file")


@pytest.mark.parametrize("raw", ["644", "640", "600", "400", "444", "666", "000"])
def test_parse_permission_mode_rejects_folder_modes_without_owner_execute(raw: str) -> None:
    with pytest.raises(PermissionPolicyError, match="folder modes must include owner execute"):
        parse_permission_mode(raw, target_kind="folder")


@pytest.mark.parametrize("raw", ["744", "754", "755", "775", "777", "700", "711"])
def test_parse_permission_mode_accepts_folder_modes_with_owner_execute(raw: str) -> None:
    assert parse_permission_mode(raw, target_kind="folder") == int(raw, 8)


@pytest.mark.parametrize("raw", ["755", "777", "711", "700"])
def test_parse_permission_mode_rejects_executable_files_by_default(raw: str) -> None:
    with pytest.raises(PermissionPolicyError, match="file modes must not include execute"):
        parse_permission_mode(raw, target_kind="file")


@pytest.mark.parametrize("raw", ["755", "777", "711", "700"])
def test_parse_permission_mode_can_allow_executable_files_explicitly(raw: str) -> None:
    assert parse_permission_mode(raw, target_kind="file", allow_file_execute=True) == int(raw, 8)


def test_library_permission_config_defaults_exist() -> None:
    assert DEFAULT_SYSTEM_CONFIG["library_permissions_enabled"] == ("false", "bool")
    assert DEFAULT_SYSTEM_CONFIG["library_permissions_folder_mode"] == ("755", "string")
    assert DEFAULT_SYSTEM_CONFIG["library_permissions_file_mode"] == ("644", "string")
    assert DEFAULT_SYSTEM_CONFIG["library_permissions_apply_to_created_folders"] == ("true", "bool")
    assert DEFAULT_SYSTEM_CONFIG["library_permissions_apply_to_materialized_files"] == (
        "true",
        "bool",
    )
    assert DEFAULT_SYSTEM_CONFIG["library_permissions_hardlink_behavior"] == ("skip", "string")
    assert DEFAULT_SYSTEM_CONFIG["library_permissions_symlink_behavior"] == ("skip", "string")


async def test_library_permission_policy_defaults_to_disabled(db_session: AsyncSession) -> None:
    policy = await load_library_permission_policy(db_session)

    assert policy == LibraryPermissionPolicy(
        enabled=False,
        folder_mode=0o755,
        file_mode=0o644,
        apply_to_created_folders=True,
        apply_to_materialized_files=True,
        hardlink_behavior=HardlinkPermissionBehavior.SKIP,
        symlink_behavior=SymlinkPermissionBehavior.SKIP,
        ownership_capability=OwnershipCapability.UNSUPPORTED,
    )
    assert policy.serialized() == {
        "enabled": False,
        "folder_mode": "755",
        "file_mode": "644",
        "apply_to_created_folders": True,
        "apply_to_materialized_files": True,
        "hardlink_behavior": "skip",
        "symlink_behavior": "skip",
        "ownership_capability": "unsupported",
    }


async def test_library_permission_policy_loads_persisted_values(
    db_session: AsyncSession,
) -> None:
    db_session.add_all(
        [
            SystemConfig(
                key="library_permissions_enabled",
                value="true",
                value_type="bool",
            ),
            SystemConfig(
                key="library_permissions_folder_mode",
                value="775",
                value_type="string",
            ),
            SystemConfig(
                key="library_permissions_file_mode",
                value="664",
                value_type="string",
            ),
            SystemConfig(
                key="library_permissions_apply_to_created_folders",
                value="false",
                value_type="bool",
            ),
            SystemConfig(
                key="library_permissions_apply_to_materialized_files",
                value="false",
                value_type="bool",
            ),
        ]
    )
    await db_session.flush()

    policy = await load_library_permission_policy(db_session)

    assert policy.enabled is True
    assert policy.folder_mode == 0o775
    assert policy.file_mode == 0o664
    assert policy.apply_to_created_folders is False
    assert policy.apply_to_materialized_files is False
    assert policy.hardlink_behavior is HardlinkPermissionBehavior.SKIP
    assert policy.symlink_behavior is SymlinkPermissionBehavior.SKIP


@pytest.mark.parametrize(
    ("key", "value", "error"),
    [
        ("library_permissions_folder_mode", "644", "folder modes must include owner execute"),
        ("library_permissions_file_mode", "755", "file modes must not include execute"),
        ("library_permissions_hardlink_behavior", "apply", "unsupported hardlink behavior"),
        ("library_permissions_symlink_behavior", "target", "unsupported symlink behavior"),
    ],
)
async def test_library_permission_policy_rejects_unsafe_or_unknown_values(
    db_session: AsyncSession,
    key: str,
    value: str,
    error: str,
) -> None:
    db_session.add(SystemConfig(key=key, value=value, value_type="string"))
    await db_session.flush()

    with pytest.raises(PermissionPolicyError, match=error):
        await load_library_permission_policy(db_session)


async def test_library_permission_policy_does_not_expose_chown_controls(
    db_session: AsyncSession,
) -> None:
    policy = await load_library_permission_policy(db_session)

    assert policy.ownership_capability is OwnershipCapability.UNSUPPORTED
    assert "owner" not in policy.serialized()
    assert "group" not in policy.serialized()
