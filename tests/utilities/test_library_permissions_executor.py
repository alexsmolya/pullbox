"""Tests for the library permissions utility executor."""

from __future__ import annotations

import os
import stat
from typing import TYPE_CHECKING

import pytest

import pullbox.utilities.executors.library_permissions as library_permissions_module
from pullbox.core.library_permission_engine import PermissionCapabilityResult, PermissionReason
from pullbox.models.library import LibraryRoot
from pullbox.utilities.base_executor import ItemResult, JobRunSummary, ProcessedItem
from pullbox.utilities.executors.library_permissions import LibraryPermissionsExecutor

if TYPE_CHECKING:
    from pathlib import Path


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


def _context_for(*roots: Path) -> dict[str, object]:
    return {
        "library_roots": [
            {
                "id": index + 1,
                "path": str(root),
            }
            for index, root in enumerate(roots)
        ]
    }


class TestValidateConfig:
    """Validate recursive permissions utility configuration."""

    def test_valid_dry_run_config(self) -> None:
        executor = LibraryPermissionsExecutor()
        assert (
            executor.validate_config(
                {
                    "scope": "library",
                    "run_mode": "dry_run",
                    "folder_mode": "750",
                    "file_mode": "640",
                }
            )
            == []
        )

    def test_rejects_missing_scope(self) -> None:
        executor = LibraryPermissionsExecutor()
        errors = executor.validate_config({"run_mode": "dry_run"})
        assert any("scope is required" in error for error in errors)

    def test_rejects_apply_without_confirm(self) -> None:
        executor = LibraryPermissionsExecutor()
        errors = executor.validate_config(
            {
                "scope": "library",
                "run_mode": "apply",
                "folder_mode": "750",
                "file_mode": "640",
            }
        )
        assert any("confirm_apply" in error for error in errors)

    def test_rejects_unsafe_file_mode(self) -> None:
        executor = LibraryPermissionsExecutor()
        errors = executor.validate_config(
            {
                "scope": "library",
                "run_mode": "dry_run",
                "file_mode": "755",
            }
        )
        assert any("file modes must not include execute" in error for error in errors)

    def test_rejects_folder_mode_without_owner_execute(self) -> None:
        executor = LibraryPermissionsExecutor()
        errors = executor.validate_config(
            {
                "scope": "library",
                "run_mode": "dry_run",
                "folder_mode": "640",
            }
        )
        assert any("folder modes must include owner execute" in error for error in errors)


class TestGenerateItems:
    """Discover recursive permission work without escaping library roots."""

    @pytest.mark.asyncio
    async def test_build_job_context_includes_permission_capability_summary(
        self,
        db_session,
        tmp_path: Path,
    ) -> None:
        root = tmp_path / "library"
        root.mkdir()
        db_session.add(LibraryRoot(name="Comics", path=str(root), enabled=True))
        await db_session.flush()

        executor = LibraryPermissionsExecutor()
        context = await executor.build_job_context(
            db_session,
            {
                "folder_mode": "750",
                "file_mode": "640",
            },
        )

        capabilities = context["permission_capabilities"]
        assert len(capabilities) == 1
        assert capabilities[0]["path"] == str(root)
        assert capabilities[0]["supported"] is True

    @pytest.mark.asyncio
    async def test_build_job_context_probes_only_selected_root(
        self,
        db_session,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        root_a = tmp_path / "library-a"
        root_b = tmp_path / "library-b"
        root_a.mkdir()
        root_b.mkdir()
        root_a_record = LibraryRoot(name="Comics A", path=str(root_a), enabled=True)
        root_b_record = LibraryRoot(name="Comics B", path=str(root_b), enabled=True)
        db_session.add_all([root_a_record, root_b_record])
        await db_session.flush()
        probed_paths: list[Path] = []

        def fake_probe(path: Path, **_: object) -> PermissionCapabilityResult:
            probed_paths.append(path)
            return PermissionCapabilityResult(
                path=path,
                supported=True,
                reason=PermissionReason.CAPABILITY_SUPPORTED,
                can_stat_root=True,
                can_create_file=True,
                can_create_directory=True,
                file_chmod_supported=True,
                directory_chmod_supported=True,
                restore_supported=True,
            )

        monkeypatch.setattr(library_permissions_module, "probe_permission_capability", fake_probe)

        executor = LibraryPermissionsExecutor()
        context = await executor.build_job_context(
            db_session,
            {
                "scope": "root",
                "run_mode": "dry_run",
                "library_root_id": root_b_record.id,
                "folder_mode": "755",
                "file_mode": "644",
            },
        )

        assert probed_paths == [root_b]
        assert [capability["path"] for capability in context["permission_capabilities"]] == [
            str(root_b)
        ]

    @pytest.mark.asyncio
    async def test_build_job_context_probes_only_roots_containing_selected_paths(
        self,
        db_session,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        root_a = tmp_path / "library-a"
        root_b = tmp_path / "library-b"
        root_c = tmp_path / "library-c"
        root_a.mkdir()
        root_b.mkdir()
        root_c.mkdir()
        issue_a = root_a / "Batman 001.cbz"
        issue_b = root_b / "Superman 001.cbz"
        issue_a.write_bytes(b"PK")
        issue_b.write_bytes(b"PK")
        db_session.add_all(
            [
                LibraryRoot(name="Comics A", path=str(root_a), enabled=True),
                LibraryRoot(name="Comics B", path=str(root_b), enabled=True),
                LibraryRoot(name="Comics C", path=str(root_c), enabled=True),
            ]
        )
        await db_session.flush()
        probed_paths: list[Path] = []

        def fake_probe(path: Path, **_: object) -> PermissionCapabilityResult:
            probed_paths.append(path)
            return PermissionCapabilityResult(
                path=path,
                supported=True,
                reason=PermissionReason.CAPABILITY_SUPPORTED,
                can_stat_root=True,
                can_create_file=True,
                can_create_directory=True,
                file_chmod_supported=True,
                directory_chmod_supported=True,
                restore_supported=True,
            )

        monkeypatch.setattr(library_permissions_module, "probe_permission_capability", fake_probe)

        executor = LibraryPermissionsExecutor()
        context = await executor.build_job_context(
            db_session,
            {
                "scope": "paths",
                "run_mode": "dry_run",
                "file_paths": [str(issue_a), str(issue_b)],
                "folder_mode": "755",
                "file_mode": "644",
            },
        )

        assert probed_paths == [root_a, root_b]
        assert [capability["path"] for capability in context["permission_capabilities"]] == [
            str(root_a),
            str(root_b),
        ]

    @pytest.mark.asyncio
    async def test_build_job_context_rejects_stale_root_id_even_with_one_enabled_root(
        self,
        db_session,
        tmp_path: Path,
    ) -> None:
        root = tmp_path / "library"
        root.mkdir()
        db_session.add(LibraryRoot(name="Comics", path=str(root), enabled=True))
        await db_session.flush()

        executor = LibraryPermissionsExecutor()
        with pytest.raises(ValueError, match="Library root not found: 999"):
            await executor.build_job_context(
                db_session,
                {
                    "scope": "root",
                    "run_mode": "dry_run",
                    "library_root_id": 999,
                    "folder_mode": "755",
                    "file_mode": "644",
                },
            )

    @pytest.mark.asyncio
    async def test_library_scope_discovers_files_and_folders(self, tmp_path: Path) -> None:
        root = tmp_path / "library"
        series = root / "Batman (2024)"
        nested = series / "Annuals"
        nested.mkdir(parents=True)
        issue = series / "Batman 001.cbz"
        annual = nested / "Batman Annual 001.cbz"
        issue.write_bytes(b"PK")
        annual.write_bytes(b"PK")

        executor = LibraryPermissionsExecutor()
        items = await executor.generate_items(
            {
                "scope": "library",
                "run_mode": "dry_run",
                "include_folders": True,
                "include_files": True,
            },
            _context_for(root),
        )

        discovered = {item["file_path"] for item in items}
        assert str(root) in discovered
        assert str(series) in discovered
        assert str(nested) in discovered
        assert str(issue) in discovered
        assert str(annual) in discovered
        assert [item["file_path"] for item in items] == sorted(discovered)

    @pytest.mark.asyncio
    async def test_root_scope_discovers_only_selected_library_root(self, tmp_path: Path) -> None:
        root_a = tmp_path / "library-a"
        root_b = tmp_path / "library-b"
        root_a.mkdir()
        root_b.mkdir()
        issue_a = root_a / "Batman 001.cbz"
        issue_b = root_b / "Superman 001.cbz"
        issue_a.write_bytes(b"PK")
        issue_b.write_bytes(b"PK")

        executor = LibraryPermissionsExecutor()
        items = await executor.generate_items(
            {
                "scope": "root",
                "run_mode": "dry_run",
                "library_root_id": 2,
                "include_folders": False,
                "include_files": True,
            },
            _context_for(root_a, root_b),
        )

        assert [item["file_path"] for item in items] == [str(issue_b)]

    @pytest.mark.asyncio
    async def test_root_scope_rejects_stale_root_id_even_with_one_enabled_root(
        self,
        tmp_path: Path,
    ) -> None:
        root = tmp_path / "library"
        root.mkdir()

        executor = LibraryPermissionsExecutor()
        with pytest.raises(ValueError, match="Library root not found: 999"):
            await executor.generate_items(
                {
                    "scope": "root",
                    "run_mode": "apply",
                    "library_root_id": 999,
                    "include_folders": True,
                    "include_files": True,
                },
                _context_for(root),
            )

    @pytest.mark.asyncio
    async def test_folder_scope_rejects_path_outside_library_root(self, tmp_path: Path) -> None:
        root = tmp_path / "library"
        outside = tmp_path / "outside"
        root.mkdir()
        outside.mkdir()

        executor = LibraryPermissionsExecutor()
        with pytest.raises(ValueError, match="outside enabled library roots"):
            await executor.generate_items(
                {
                    "scope": "folder",
                    "run_mode": "dry_run",
                    "selected_path": str(outside),
                },
                _context_for(root),
            )

    @pytest.mark.asyncio
    async def test_folder_scope_rejects_selected_symlink(self, tmp_path: Path) -> None:
        root = tmp_path / "library"
        target = tmp_path / "outside"
        root.mkdir()
        target.mkdir()
        selected = root / "linked-folder"
        selected.symlink_to(target, target_is_directory=True)

        executor = LibraryPermissionsExecutor()
        with pytest.raises(ValueError, match="Selected folder cannot be a symlink"):
            await executor.generate_items(
                {
                    "scope": "folder",
                    "run_mode": "dry_run",
                    "selected_path": str(selected),
                },
                _context_for(root),
            )

    @pytest.mark.asyncio
    async def test_scanner_includes_but_does_not_descend_symlinked_directories(
        self,
        tmp_path: Path,
    ) -> None:
        root = tmp_path / "library"
        target = tmp_path / "outside"
        target_nested = target / "hidden.cbz"
        root.mkdir()
        target.mkdir()
        target_nested.write_bytes(b"PK")
        linked = root / "linked-folder"
        linked.symlink_to(target, target_is_directory=True)

        executor = LibraryPermissionsExecutor()
        items = await executor.generate_items(
            {
                "scope": "library",
                "run_mode": "dry_run",
                "include_folders": True,
                "include_files": True,
            },
            _context_for(root),
        )

        discovered = {item["file_path"] for item in items}
        assert str(linked) in discovered
        assert str(target_nested) not in discovered


class TestProcessItem:
    """Apply and preview chmod work item behavior."""

    def test_dry_run_reports_would_apply_without_mutating(self, tmp_path: Path) -> None:
        source = tmp_path / "issue.cbz"
        source.write_bytes(b"PK")
        source.chmod(0o600)

        executor = LibraryPermissionsExecutor()
        result = executor.process_item(
            {"id": "item-1", "file_path": str(source), "operation": "permission_dry_run"},
            {"run_mode": "dry_run", "file_mode": "640"},
        )

        assert result.result == ItemResult.COMPLETED
        assert result.after_state["action"] == "would_apply"
        assert _mode(source) == 0o600

    def test_apply_changes_file_mode(self, tmp_path: Path) -> None:
        source = tmp_path / "issue.cbz"
        source.write_bytes(b"PK")
        source.chmod(0o600)

        executor = LibraryPermissionsExecutor()
        result = executor.process_item(
            {"id": "item-1", "file_path": str(source), "operation": "permission_apply"},
            {
                "run_mode": "apply",
                "file_mode": "640",
                "confirm_apply": True,
            },
        )

        assert result.result == ItemResult.COMPLETED
        assert result.before_state["previous_mode"] == "600"
        assert result.after_state["resulting_mode"] == "640"
        assert _mode(source) == 0o640

    def test_apply_skips_hardlink_without_changing_source_inode(self, tmp_path: Path) -> None:
        source = tmp_path / "source.cbz"
        linked = tmp_path / "linked.cbz"
        source.write_bytes(b"PK")
        source.chmod(0o600)
        os.link(source, linked)

        executor = LibraryPermissionsExecutor()
        result = executor.process_item(
            {"id": "item-1", "file_path": str(linked), "operation": "permission_apply"},
            {
                "run_mode": "apply",
                "file_mode": "640",
                "confirm_apply": True,
            },
        )

        assert result.result == ItemResult.SKIPPED
        assert result.after_state["reason"] == "hardlink_skipped"
        assert _mode(source) == 0o600


class TestRollbackItem:
    """Rollback restores only safe, unchanged permission updates."""

    def test_rollback_restores_previous_mode_when_current_matches_apply(
        self, tmp_path: Path
    ) -> None:
        source = tmp_path / "issue.cbz"
        source.write_bytes(b"PK")
        source.chmod(0o640)

        executor = LibraryPermissionsExecutor()
        result = executor.rollback_item(
            {
                "id": "item-1",
                "file_path": str(source),
                "before_state": {"previous_mode": "600"},
                "after_state": {"resulting_mode": "640"},
            },
            {},
        )

        assert result.result == ItemResult.COMPLETED
        assert _mode(source) == 0o600

    def test_rollback_skips_when_user_changed_mode_after_apply(self, tmp_path: Path) -> None:
        source = tmp_path / "issue.cbz"
        source.write_bytes(b"PK")
        source.chmod(0o644)

        executor = LibraryPermissionsExecutor()
        result = executor.rollback_item(
            {
                "id": "item-1",
                "file_path": str(source),
                "before_state": {"previous_mode": "600"},
                "after_state": {"resulting_mode": "640"},
            },
            {},
        )

        assert result.result == ItemResult.SKIPPED
        assert "changed after apply" in (result.warning_message or "")
        assert _mode(source) == 0o644


class TestJobSummary:
    """Queue-side summary hooks keep permission jobs understandable."""

    @pytest.mark.asyncio
    async def test_apply_item_result_counts_permission_actions(self) -> None:
        executor = LibraryPermissionsExecutor()
        summary = JobRunSummary()
        processed = ProcessedItem(
            item_id="item-1",
            result=ItemResult.COMPLETED,
            after_state={"action": "applied"},
        )

        await executor.apply_item_result(None, None, {}, processed, {}, None, summary)

        assert summary.metadata["permission_actions"] == {"applied": 1}

    @pytest.mark.asyncio
    async def test_finalize_job_warns_for_unsupported_roots(self) -> None:
        executor = LibraryPermissionsExecutor()
        summary = JobRunSummary(completed=2, skipped=1)

        result = await executor.finalize_job(
            None,
            None,
            summary,
            {"run_mode": "dry_run"},
            {
                "permission_capabilities": [
                    {"path": "/comics", "supported": True},
                    {"path": "/nas", "supported": False, "reason": "chmod_ignored"},
                ]
            },
        )

        assert "dry-run mode" in result.final_parts
        assert "1 root unsupported" in result.final_parts
        assert result.final_log_level == "WARNING"

    @pytest.mark.asyncio
    async def test_finalize_job_logs_chmod_only_ownership_limitation(self) -> None:
        executor = LibraryPermissionsExecutor()
        summary = JobRunSummary()

        result = await executor.finalize_job(
            None,
            None,
            summary,
            {"run_mode": "apply"},
            {"permission_capabilities": []},
        )

        assert result.extra_logs
        log = result.extra_logs[0]
        assert log.level == "INFO"
        assert "chmod-only" in log.message
        assert log.extra == {
            "ownership_capability": "unsupported",
            "chown_attempted": False,
            "chgrp_attempted": False,
        }
