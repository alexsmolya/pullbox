"""Tests for backup service — create, restore, cleanup, and verification.

Run:
    pytest tests/unit/test_backup_service.py -v
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from zipfile import ZipFile

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from pullbox.core.exceptions import BackupError
from pullbox.services.backup_service import (
    BACKUP_EXTENSION,
    BACKUP_PREFIX,
    DB_FILENAME,
    METADATA_FILENAME,
    PRE_RESTORE_EXTENSION,
    PRE_RESTORE_PREFIX,
    BackupInfo,
    BackupService,
)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Create a small SQLite database for testing."""
    path = tmp_path / "pullbox.db"
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO test VALUES (1, 'hello')")
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def backup_dir(tmp_path: Path) -> Path:
    return tmp_path / "backups"


@pytest.fixture
def svc(backup_dir: Path, db_path: Path) -> BackupService:
    return BackupService(backup_dir=backup_dir, db_path=db_path)


class TestCreateBackup:
    """Tests for create_backup() including error handling and verification."""

    def test_returns_backup_info(self, svc: BackupService) -> None:
        info = svc.create_backup()
        assert info.filename.startswith(BACKUP_PREFIX)
        assert info.filename.endswith(BACKUP_EXTENSION)
        assert info.backup_type == "manual"
        assert info.size_bytes > 0
        assert info.db_size_bytes > 0

    def test_creates_valid_zip(self, svc: BackupService, backup_dir: Path) -> None:
        info = svc.create_backup()
        zip_path = backup_dir / info.filename
        with ZipFile(zip_path, "r") as zf:
            assert zf.testzip() is None
            assert DB_FILENAME in zf.namelist()
            assert METADATA_FILENAME in zf.namelist()

    def test_metadata_contains_required_fields(
        self,
        svc: BackupService,
        backup_dir: Path,
    ) -> None:
        info = svc.create_backup()
        zip_path = backup_dir / info.filename
        with ZipFile(zip_path, "r") as zf:
            meta = json.loads(zf.read(METADATA_FILENAME))
        assert "pullbox_version" in meta
        assert "created_at" in meta
        assert "backup_type" in meta
        assert meta["backup_type"] == "manual"
        assert "/data/config.xml" in meta["notes"]
        assert "PULLBOX_SECRET_KEY" in meta["notes"]

    def test_scheduled_backup_type(self, svc: BackupService) -> None:
        info = svc.create_backup(backup_type="scheduled")
        assert info.backup_type == "scheduled"

    def test_missing_db_raises_backup_error(
        self,
        backup_dir: Path,
        tmp_path: Path,
    ) -> None:
        svc = BackupService(backup_dir=backup_dir, db_path=tmp_path / "nonexistent.db")
        with pytest.raises(BackupError, match="backup"):
            svc.create_backup()

    def test_creates_backup_dir_if_missing(
        self,
        svc: BackupService,
        backup_dir: Path,
    ) -> None:
        assert not backup_dir.exists()
        svc.create_backup()
        assert backup_dir.is_dir()

    def test_backup_database_retries_transient_errors(
        self,
        svc: BackupService,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        attempts = {"count": 0}
        roles = iter(["source", "dest", "source", "dest", "source", "dest"])
        sleep_calls: list[float] = []

        class _FakeConnection:
            def __init__(self, role: str) -> None:
                self.role = role

            def execute(self, _sql: str) -> None:
                return None

            def backup(
                self,
                _dest: object,
                *,
                pages: int | None = None,
                sleep: float | None = None,
            ) -> None:
                assert self.role == "source"
                assert pages == svc._BACKUP_RETRY_PAGE_COUNT
                assert sleep == 0.05
                attempts["count"] += 1
                if attempts["count"] < 3:
                    raise sqlite3.OperationalError("disk I/O error")

            def close(self) -> None:
                return None

        def _fake_connect(*_args: object, **_kwargs: object) -> _FakeConnection:
            return _FakeConnection(next(roles))

        monkeypatch.setattr("pullbox.services.backup_service.sqlite3.connect", _fake_connect)
        monkeypatch.setattr("pullbox.services.backup_service.time.sleep", sleep_calls.append)

        svc._backup_database(tmp_path / "copy.db")

        assert attempts["count"] == 3
        assert sleep_calls == [0.5, 1.0]


class TestCleanupOldBackups:
    """Tests for cleanup_old_backups() including metadata corruption safety."""

    def _create_backup_zip(
        self,
        backup_dir: Path,
        filename: str,
        backup_type: str = "scheduled",
        age_days: int = 0,
        *,
        created_at: str | None = None,
    ) -> Path:
        """Helper to create a backup ZIP with metadata for testing."""
        import time

        backup_dir.mkdir(parents=True, exist_ok=True)
        zip_path = backup_dir / filename
        created_at_value = created_at or (datetime.now(UTC) - timedelta(days=age_days)).isoformat()
        meta = {
            "pullbox_version": "0.5.0",
            "created_at": created_at_value,
            "backup_type": backup_type,
            "db_size_bytes": 1000,
        }
        with ZipFile(zip_path, "w") as zf:
            zf.writestr(METADATA_FILENAME, json.dumps(meta))
            zf.writestr(DB_FILENAME, "fake db content")
        if age_days > 0:
            old_time = time.time() - (age_days * 86400)
            import os

            os.utime(zip_path, (old_time, old_time))
        return zip_path

    def test_deletes_old_scheduled_backups(
        self,
        svc: BackupService,
        backup_dir: Path,
    ) -> None:
        self._create_backup_zip(backup_dir, f"{BACKUP_PREFIX}old{BACKUP_EXTENSION}", age_days=30)
        deleted = svc.cleanup_old_backups(retention_days=28)
        assert deleted == 1

    def test_preserves_manual_backups(
        self,
        svc: BackupService,
        backup_dir: Path,
    ) -> None:
        self._create_backup_zip(
            backup_dir,
            f"{BACKUP_PREFIX}manual{BACKUP_EXTENSION}",
            backup_type="manual",
            age_days=60,
        )
        deleted = svc.cleanup_old_backups(retention_days=28)
        assert deleted == 0

    def test_preserves_recent_scheduled_backups(
        self,
        svc: BackupService,
        backup_dir: Path,
    ) -> None:
        self._create_backup_zip(backup_dir, f"{BACKUP_PREFIX}recent{BACKUP_EXTENSION}", age_days=5)
        deleted = svc.cleanup_old_backups(retention_days=28)
        assert deleted == 0

    def test_prefers_metadata_created_at_over_file_mtime(
        self,
        svc: BackupService,
        backup_dir: Path,
    ) -> None:
        old_mtime_recent_metadata = self._create_backup_zip(
            backup_dir,
            f"{BACKUP_PREFIX}metadata-wins{BACKUP_EXTENSION}",
            age_days=60,
            created_at=(datetime.now(UTC) - timedelta(days=1)).isoformat(),
        )

        deleted = svc.cleanup_old_backups(retention_days=28)

        assert deleted == 0
        assert old_mtime_recent_metadata.exists()

    def test_falls_back_to_file_mtime_when_metadata_timestamp_invalid(
        self,
        svc: BackupService,
        backup_dir: Path,
    ) -> None:
        old_backup = self._create_backup_zip(
            backup_dir,
            f"{BACKUP_PREFIX}mtime-fallback{BACKUP_EXTENSION}",
            age_days=60,
            created_at="not-a-date",
        )

        deleted = svc.cleanup_old_backups(retention_days=28)

        assert deleted == 1
        assert not old_backup.exists()

    def test_skips_corrupted_metadata(
        self,
        svc: BackupService,
        backup_dir: Path,
    ) -> None:
        """Backups with corrupted metadata should be SKIPPED, not deleted."""
        import time

        backup_dir.mkdir(parents=True, exist_ok=True)
        zip_path = backup_dir / f"{BACKUP_PREFIX}corrupt{BACKUP_EXTENSION}"
        with ZipFile(zip_path, "w") as zf:
            zf.writestr(METADATA_FILENAME, "not valid json {{{")
            zf.writestr(DB_FILENAME, "fake")
        # Make it old enough to be eligible for deletion
        old_time = time.time() - (60 * 86400)
        import os

        os.utime(zip_path, (old_time, old_time))

        deleted = svc.cleanup_old_backups(retention_days=28)
        assert deleted == 0
        assert zip_path.exists()

    def test_handles_empty_directory(
        self,
        svc: BackupService,
        backup_dir: Path,
    ) -> None:
        backup_dir.mkdir(parents=True, exist_ok=True)
        deleted = svc.cleanup_old_backups(retention_days=28)
        assert deleted == 0

    def test_handles_missing_directory(self, svc: BackupService) -> None:
        deleted = svc.cleanup_old_backups(retention_days=28)
        assert deleted == 0


class TestRestoreBackup:
    """Tests for restore_backup()."""

    def test_replaces_database(
        self,
        svc: BackupService,
        db_path: Path,
        backup_dir: Path,
    ) -> None:
        info = svc.create_backup()
        # Modify the original DB
        conn = sqlite3.connect(str(db_path))
        conn.execute("INSERT INTO test VALUES (2, 'modified')")
        conn.commit()
        conn.close()
        # Restore should overwrite with the backup version
        assert svc.restore_backup(info.filename) is True
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute("SELECT COUNT(*) FROM test").fetchone()[0]
        conn.close()
        assert rows == 1  # Only the original row

    def test_creates_pre_restore_safety_copy(
        self,
        svc: BackupService,
        backup_dir: Path,
    ) -> None:
        info = svc.create_backup()
        svc.restore_backup(info.filename)
        safety_backups = list(backup_dir.glob(f"{PRE_RESTORE_PREFIX}*{PRE_RESTORE_EXTENSION}"))
        assert len(safety_backups) == 1

    def test_restore_removes_sqlite_sidecars(
        self,
        svc: BackupService,
        db_path: Path,
    ) -> None:
        info = svc.create_backup()
        db_path.with_suffix(".db-wal").write_text("wal")
        db_path.with_suffix(".db-shm").write_text("shm")

        svc.restore_backup(info.filename)

        assert not db_path.with_suffix(".db-wal").exists()
        assert not db_path.with_suffix(".db-shm").exists()

    def test_restore_rejects_invalid_extracted_database(
        self,
        svc: BackupService,
        backup_dir: Path,
    ) -> None:
        backup_dir.mkdir(parents=True, exist_ok=True)
        corrupt_zip = backup_dir / f"{BACKUP_PREFIX}corrupt{BACKUP_EXTENSION}"
        metadata = {
            "pullbox_version": "0.5.0",
            "created_at": datetime.now(UTC).isoformat(),
            "backup_type": "manual",
            "db_size_bytes": 1000,
        }
        with ZipFile(corrupt_zip, "w") as zf:
            zf.writestr(DB_FILENAME, "this is not a sqlite database" * 64)
            zf.writestr(METADATA_FILENAME, json.dumps(metadata, indent=2))

        with pytest.raises(BackupError, match="failed validation"):
            svc.restore_backup(corrupt_zip.name)

    def test_verify_restore_database_rejects_failed_quick_check(
        self,
        svc: BackupService,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        class _FakeCursor:
            def fetchone(self) -> tuple[str]:
                return ("not ok",)

        class _FakeConnection:
            def execute(self, _sql: str) -> _FakeCursor:
                return _FakeCursor()

            def close(self) -> None:
                return None

        monkeypatch.setattr(
            "pullbox.services.backup_service.sqlite3.connect",
            lambda _path: _FakeConnection(),
        )

        with pytest.raises(BackupError, match="quick_check did not return ok"):
            svc._verify_restore_database(tmp_path / "restore.db")

    def test_invalid_filename_returns_false(self, svc: BackupService) -> None:
        assert svc.restore_backup("nonexistent.zip") is False

    def test_metadata_note_mentions_sessions_not_api_keys(
        self,
        svc: BackupService,
        backup_dir: Path,
    ) -> None:
        info = svc.create_backup()

        with ZipFile(backup_dir / info.filename, "r") as zf:
            meta = json.loads(zf.read(METADATA_FILENAME))

        assert "browser sessions" in meta["notes"]
        assert "API key" not in meta["notes"]


class TestListBackups:
    """Tests for list_backups()."""

    def test_returns_sorted_newest_first(
        self,
        svc: BackupService,
    ) -> None:
        import time

        svc.create_backup()
        time.sleep(1.1)  # Ensure different timestamp in filename
        svc.create_backup()
        backups = svc.list_backups()
        assert len(backups) == 2
        assert backups[0].created_at >= backups[1].created_at

    def test_empty_directory(self, svc: BackupService, backup_dir: Path) -> None:
        backup_dir.mkdir(parents=True, exist_ok=True)
        assert svc.list_backups() == []

    def test_missing_directory(self, svc: BackupService) -> None:
        assert svc.list_backups() == []


class TestBackupCreatedTimestamp:
    def test_naive_metadata_timestamp_is_treated_as_utc(
        self,
        backup_dir: Path,
    ) -> None:
        path = backup_dir / f"{BACKUP_PREFIX}naive{BACKUP_EXTENSION}"
        backup_dir.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder")
        info = BackupInfo(
            filename=path.name,
            created_at="2026-05-02T12:00:00",
            size_bytes=path.stat().st_size,
            pullbox_version="0.0.0",
            db_size_bytes=0,
            backup_type="scheduled",
        )

        timestamp = BackupService._backup_created_timestamp(path, info)

        assert timestamp == datetime(2026, 5, 2, 12, 0, tzinfo=UTC).timestamp()
