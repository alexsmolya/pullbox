"""Tests for UT-3.1 — mass rename executor.

Verifies rename logic, conflict detection, case-only renames,
forbidden character sanitization, rollback, and edge cases.

Run:
    pytest tests/utilities/test_mass_rename.py -v
"""

from __future__ import annotations

from pathlib import Path  # noqa: TC003

import pytest

from pullbox.utilities.base_executor import ItemResult
from pullbox.utilities.executors.mass_rename import MassRenameExecutor

# ── Config Validation ──────────────────────────────────────────


class TestValidateConfig:
    """Verify config validation."""

    def test_valid_config(self) -> None:
        executor = MassRenameExecutor()
        errors = executor.validate_config(
            {
                "target": "files",
                "template": "{Series} ({Year}) #{Issue:03d}",
            }
        )
        assert errors == []

    def test_missing_target(self) -> None:
        executor = MassRenameExecutor()
        errors = executor.validate_config({"template": "{Series}"})
        assert any("target" in e.lower() for e in errors)

    def test_invalid_target(self) -> None:
        executor = MassRenameExecutor()
        errors = executor.validate_config({"target": "invalid", "template": "{Series}"})
        assert any("target" in e.lower() for e in errors)

    def test_missing_template(self) -> None:
        executor = MassRenameExecutor()
        errors = executor.validate_config({"target": "folders"})
        assert any("template" in e.lower() for e in errors)


# ── Generate Items ─────────────────────────────────────────────


class TestGenerateItems:
    """Verify queued item payload generation."""

    @pytest.mark.asyncio
    async def test_prefers_explicit_items_payload(self, tmp_path: Path) -> None:
        source = tmp_path / "batman-2016-001.cbz"
        source.write_text("content")

        executor = MassRenameExecutor()
        items = await executor.generate_items(
            {
                "target": "files",
                "template": "{Series} ({Year}) #{Issue:03d}",
                "items": [
                    {
                        "file_path": str(source),
                        "proposed_name": "Batman (2016) #001.cbz",
                        "operation": "rename",
                    }
                ],
            }
        )

        assert items == [
            {
                "file_path": str(source),
                "proposed_name": "Batman (2016) #001.cbz",
                "operation": "rename",
            }
        ]


# ── Process Item: File Rename ──────────────────────────────────


class TestFileRename:
    """Verify file rename operations."""

    def test_basic_rename(self, tmp_path: Path) -> None:
        source = tmp_path / "batman-2016-001.cbz"
        source.write_text("content")

        executor = MassRenameExecutor()
        result = executor.process_item(
            item_data={
                "id": "item-001",
                "file_path": str(source),
                "operation": "rename",
                "proposed_name": "Batman (2016) #001.cbz",
            },
            job_config={"target": "files"},
        )

        assert result.result == ItemResult.COMPLETED
        new_path = tmp_path / "Batman (2016) #001.cbz"
        assert new_path.exists()
        assert not source.exists()

    def test_no_change_skipped(self, tmp_path: Path) -> None:
        source = tmp_path / "Batman (2016) #001.cbz"
        source.write_text("content")

        executor = MassRenameExecutor()
        result = executor.process_item(
            item_data={
                "id": "item-002",
                "file_path": str(source),
                "operation": "rename",
                "proposed_name": "Batman (2016) #001.cbz",
            },
            job_config={"target": "files"},
        )

        assert result.result == ItemResult.SKIPPED

    def test_target_exists_fails(self, tmp_path: Path) -> None:
        source = tmp_path / "old_name.cbz"
        source.write_text("source")
        target = tmp_path / "Batman (2016) #001.cbz"
        target.write_text("existing")

        executor = MassRenameExecutor()
        result = executor.process_item(
            item_data={
                "id": "item-003",
                "file_path": str(source),
                "operation": "rename",
                "proposed_name": "Batman (2016) #001.cbz",
            },
            job_config={"target": "files"},
        )

        assert result.result == ItemResult.FAILED
        assert "already exists" in (result.error_message or "").lower()

    def test_source_missing_fails(self, tmp_path: Path) -> None:
        executor = MassRenameExecutor()
        result = executor.process_item(
            item_data={
                "id": "item-004",
                "file_path": str(tmp_path / "ghost.cbz"),
                "operation": "rename",
                "proposed_name": "New Name.cbz",
            },
            job_config={"target": "files"},
        )

        assert result.result == ItemResult.FAILED

    def test_empty_proposed_name_skipped(self, tmp_path: Path) -> None:
        source = tmp_path / "test.cbz"
        source.write_text("content")

        executor = MassRenameExecutor()
        result = executor.process_item(
            item_data={
                "id": "item-005",
                "file_path": str(source),
                "operation": "rename",
                "proposed_name": "",
            },
            job_config={"target": "files"},
        )

        assert result.result == ItemResult.SKIPPED


# ── Process Item: Folder Rename ────────────────────────────────


class TestFolderRename:
    """Verify folder rename operations."""

    def test_basic_folder_rename(self, tmp_path: Path) -> None:
        folder = tmp_path / "batman-2016"
        folder.mkdir()
        (folder / "issue_001.cbz").write_text("content")

        executor = MassRenameExecutor()
        result = executor.process_item(
            item_data={
                "id": "item-010",
                "file_path": str(folder),
                "operation": "rename",
                "proposed_name": "Batman (2016)",
            },
            job_config={"target": "folders"},
        )

        assert result.result == ItemResult.COMPLETED
        new_folder = tmp_path / "Batman (2016)"
        assert new_folder.exists()
        assert (new_folder / "issue_001.cbz").exists()
        assert not folder.exists()

    def test_folder_no_change_skipped(self, tmp_path: Path) -> None:
        folder = tmp_path / "Batman (2016)"
        folder.mkdir()

        executor = MassRenameExecutor()
        result = executor.process_item(
            item_data={
                "id": "item-011",
                "file_path": str(folder),
                "operation": "rename",
                "proposed_name": "Batman (2016)",
            },
            job_config={"target": "folders"},
        )

        assert result.result == ItemResult.SKIPPED


# ── Case-Only Rename ──────────────────────────────────────────


class TestCaseOnlyRename:
    """Verify case-only renames work on case-insensitive filesystems."""

    def test_case_only_file_rename(self, tmp_path: Path) -> None:
        source = tmp_path / "batman.cbz"
        source.write_text("content")

        executor = MassRenameExecutor()
        result = executor.process_item(
            item_data={
                "id": "item-020",
                "file_path": str(source),
                "operation": "rename",
                "proposed_name": "Batman.cbz",
            },
            job_config={"target": "files"},
        )

        assert result.result == ItemResult.COMPLETED
        # On case-insensitive FS, the file exists at the new casing
        entries = list(tmp_path.iterdir())
        assert len(entries) == 1
        assert entries[0].name == "Batman.cbz"


# ── Rollback ───────────────────────────────────────────────────


class TestRollback:
    """Verify rollback restores original names."""

    def test_rollback_file(self, tmp_path: Path) -> None:
        renamed = tmp_path / "Batman (2016) #001.cbz"
        renamed.write_text("content")

        executor = MassRenameExecutor()
        result = executor.rollback_item(
            item_data={
                "id": "rb-001",
                "before_state": {"path": str(tmp_path / "old_name.cbz")},
                "after_state": {"path": str(renamed)},
            },
            job_config={},
        )

        assert result.result == ItemResult.COMPLETED
        assert (tmp_path / "old_name.cbz").exists()
        assert not renamed.exists()

    def test_rollback_missing_renamed_file(self, tmp_path: Path) -> None:
        """Rollback when renamed file no longer exists."""
        executor = MassRenameExecutor()
        result = executor.rollback_item(
            item_data={
                "id": "rb-002",
                "before_state": {"path": str(tmp_path / "old.cbz")},
                "after_state": {"path": str(tmp_path / "gone.cbz")},
            },
            job_config={},
        )

        assert result.result == ItemResult.FAILED


# ── Forbidden Characters ───────────────────────────────────────


class TestForbiddenCharacters:
    """Verify proposed names with forbidden chars are sanitized."""

    def test_sanitizes_colons(self, tmp_path: Path) -> None:
        source = tmp_path / "test.cbz"
        source.write_text("content")

        executor = MassRenameExecutor()
        result = executor.process_item(
            item_data={
                "id": "item-030",
                "file_path": str(source),
                "operation": "rename",
                "proposed_name": "Batman: The Dark Knight.cbz",
            },
            job_config={"target": "files"},
        )

        assert result.result == ItemResult.COMPLETED
        # Colon should be sanitized
        entries = list(tmp_path.iterdir())
        assert len(entries) == 1
        assert ":" not in entries[0].name


# ── Long Names ─────────────────────────────────────────────────


class TestLongNames:
    """Verify handling of very long proposed names."""

    def test_very_long_name_fails(self, tmp_path: Path) -> None:
        source = tmp_path / "test.cbz"
        source.write_text("content")

        executor = MassRenameExecutor()
        result = executor.process_item(
            item_data={
                "id": "item-040",
                "file_path": str(source),
                "operation": "rename",
                "proposed_name": "x" * 260 + ".cbz",
            },
            job_config={"target": "files"},
        )

        assert result.result == ItemResult.FAILED
        err = (result.error_message or "").lower()
        assert "limit" in err or "long" in err


# ── Mass Rename Edge Cases ────────────────────────────────────


class TestMassRenameEdgeCases:
    """Verify edge cases in mass rename operations."""

    def test_proposed_name_with_whitespace_trimmed(self, tmp_path: Path) -> None:
        """Leading/trailing whitespace in proposed name is trimmed."""
        source = tmp_path / "test.cbz"
        source.write_text("content")

        executor = MassRenameExecutor()
        result = executor.process_item(
            item_data={
                "id": "item-ws",
                "file_path": str(source),
                "operation": "rename",
                "proposed_name": " Batman .cbz",
            },
            job_config={"target": "files"},
        )

        assert result.result == ItemResult.COMPLETED
        entries = list(tmp_path.iterdir())
        assert len(entries) == 1
        # _sanitize_name trims whitespace and trailing dots/spaces
        assert entries[0].name.strip() == entries[0].name
        assert "Batman" in entries[0].name

    def test_folder_with_contents_moves_all_files(self, tmp_path: Path) -> None:
        """Folder rename moves all contained files (.cbz, .nfo, .jpg)."""
        folder = tmp_path / "batman-2016"
        folder.mkdir()
        (folder / "issue_001.cbz").write_text("comic")
        (folder / "info.nfo").write_text("metadata")
        (folder / "cover.jpg").write_bytes(b"\xff\xd8\xff")

        executor = MassRenameExecutor()
        result = executor.process_item(
            item_data={
                "id": "item-folder-contents",
                "file_path": str(folder),
                "operation": "rename",
                "proposed_name": "Batman (2016)",
            },
            job_config={"target": "folders"},
        )

        assert result.result == ItemResult.COMPLETED
        new_folder = tmp_path / "Batman (2016)"
        assert new_folder.exists()
        assert (new_folder / "issue_001.cbz").exists()
        assert (new_folder / "info.nfo").exists()
        assert (new_folder / "cover.jpg").exists()
        assert not folder.exists()

    def test_three_way_conflict_detection(self, tmp_path: Path) -> None:
        """Three files resolving to same target name each get target_exists failure."""
        # Create three source files and one existing target
        source1 = tmp_path / "bat_001.cbz"
        source2 = tmp_path / "bat_002.cbz"
        source3 = tmp_path / "bat_003.cbz"
        source1.write_text("file1")
        source2.write_text("file2")
        source3.write_text("file3")

        # Pre-create the target
        target = tmp_path / "Batman #001.cbz"
        target.write_text("existing")

        executor = MassRenameExecutor()

        # All three should fail because target exists
        results = []
        for i, source in enumerate([source1, source2, source3]):
            result = executor.process_item(
                item_data={
                    "id": f"item-3way-{i}",
                    "file_path": str(source),
                    "operation": "rename",
                    "proposed_name": "Batman #001.cbz",
                },
                job_config={"target": "files"},
            )
            results.append(result)

        assert all(r.result == ItemResult.FAILED for r in results)
        assert all("already exists" in (r.error_message or "").lower() for r in results)
